"""AlgoPulse™ — AlgoLang's built-in real-time event engine (v0.3.4).

AlgoPulse is a durable, append-only event log made for governed agent systems. It needs nothing outside
AlgoLang: no broker cluster, no coordinator, no extra packages.

    pulse/                         one folder per bus
      orders.intent/
        events.jsonl               the log: one event per line, numbered from 0 (its offset)
        groups/risk-gate.json      where each consumer group has got to (its committed offset)

Two ways to reach a bus:
    local   several programs on one machine share the folder (file locks keep writers in order)
    served  `algo pulse serve` puts a bus on the network; producers and streams on other machines use
            its HTTP API, protected by a bearer token (ALGO_PULSE_TOKEN)

In algo.config.json:
    "pulse": {
      "market": {"dir": "pulse"},                                       local folder (relative to the config)
      "edge":   {"url": "http://10.0.0.5:7070", "token_env": "PULSE_TOKEN"}   a served bus
    }
A bus that is not listed is a local folder: pulse/<bus>. ALGO_PULSE_URL sends every bus to one server.

Commands
    algo pulse serve   [--dir pulse] [--host 127.0.0.1] [--port 7070]
    algo pulse publish TOPIC events.jsonl [--bus NAME] [--key FIELD]
    algo pulse topics  [--bus NAME]
    algo pulse tail    TOPIC [--bus NAME] [--from N] [--max 20]

HTTP API (JSON; every call needs `Authorization: Bearer <token>` when a token is set)
    GET  /health
    GET  /topics                                   → {"topic": events, …}
    POST /topics/<t>/events   {"events": [{"key": "k", "value": "…"}]}   → {"offsets": [...]}
    GET  /topics/<t>/events?from=N&max=M           → {"events": [{"offset", "key", "value", "at"}]}
    GET  /topics/<t>/groups/<g>                    → {"offset": n}
    PUT  /topics/<t>/groups/<g>  {"offset": n}
"""
from __future__ import annotations

import hmac
import json
import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error as urlerror
from urllib import parse, request

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_BODY = 5 * 1024 * 1024
ENGINE = "AlgoPulse"


def check_name(kind, name):
    """Topic and group names: letters, digits, dot, dash, underscore. Never a path."""
    if not isinstance(name, str) or not NAME_RE.match(name) or ".." in name:
        raise ValueError(f"bad {kind} name {name!r}: use letters, digits, '.', '-' or '_' (max 128)")
    return name


@contextmanager
def _file_lock(path: Path):
    """An exclusive lock between processes and threads (POSIX flock, Windows msvcrt)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            while True:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.005)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class PulseLog:
    """A bus stored in a folder. Safe for several writers and readers on one machine."""

    def __init__(self, root):
        self.root = Path(root)
        self._index: dict[str, list[int]] = {}       # topic → byte position of every line read so far
        self._size: dict[str, int] = {}
        self._mu = threading.Lock()

    def _dir(self, topic):
        return self.root / check_name("topic", topic)

    def _refresh(self, topic):
        """Index any lines appended (by anyone) since we last looked."""
        f = self._dir(topic) / "events.jsonl"
        if not f.exists():
            return []
        idx = self._index.setdefault(topic, [])
        pos = self._size.get(topic, 0)
        size = f.stat().st_size
        if size > pos:
            with open(f, "rb") as fh:
                fh.seek(pos)
                for line in fh:
                    if not line.endswith(b"\n"):
                        break                      # a line still being written: read it next time
                    idx.append(pos)
                    pos += len(line)
            self._size[topic] = pos
        return idx

    def append(self, topic, events):
        """Append [(key, value), …]. Returns their offsets."""
        d = self._dir(topic)
        with self._mu, _file_lock(d / ".lock"):
            n = len(self._refresh(topic))
            lines, offsets = [], []
            for key, value in events:
                if not isinstance(value, str):
                    value = value.decode("utf-8", "replace") if isinstance(value, bytes) else json.dumps(value)
                lines.append(json.dumps({"offset": n, "key": key, "value": value, "at": _now()},
                                        ensure_ascii=False) + "\n")
                offsets.append(n)
                n += 1
            with open(d / "events.jsonl", "a", encoding="utf-8", newline="\n") as fh:
                fh.write("".join(lines))
                fh.flush()
                os.fsync(fh.fileno())
            self._refresh(topic)
        return offsets

    def read(self, topic, start=0, max_events=100):
        with self._mu:
            idx = list(self._refresh(topic))
        if start >= len(idx):
            return []
        out = []
        with open(self._dir(topic) / "events.jsonl", "rb") as fh:
            fh.seek(idx[start])
            for _ in range(min(max_events, len(idx) - start)):
                out.append(json.loads(fh.readline()))
        return out

    def end(self, topic):
        with self._mu:
            return len(self._refresh(topic))

    def committed(self, topic, group):
        f = self._dir(topic) / "groups" / f"{check_name('group', group)}.json"
        try:
            return int(json.loads(f.read_text(encoding="utf-8"))["offset"])
        except (FileNotFoundError, ValueError, KeyError):
            return 0

    def commit(self, topic, group, offset):
        g = self._dir(topic) / "groups"
        g.mkdir(parents=True, exist_ok=True)
        f = g / f"{check_name('group', group)}.json"
        tmp = g / f".{group}.{os.getpid()}.{threading.get_ident()}.tmp"
        tmp.write_text(json.dumps({"offset": int(offset), "at": _now()}), encoding="utf-8")
        os.replace(tmp, f)                             # atomic: a reader sees the old or the new offset

    def topics(self):
        if not self.root.exists():
            return {}
        return {d.name: self.end(d.name) for d in sorted(self.root.iterdir())
                if d.is_dir() and (d / "events.jsonl").exists()}


class PulseClient:
    """The same interface as PulseLog, for a bus served by `algo pulse serve`."""

    def __init__(self, url, token=None, timeout=30):
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout

    def _call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = request.Request(self.url + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read() or b"{}")
        except urlerror.HTTPError as e:
            raise RuntimeError(f"AlgoPulse server: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:200]}")

    def append(self, topic, events):
        return self._call("POST", f"/topics/{check_name('topic', topic)}/events",
                          {"events": [{"key": k, "value": v if isinstance(v, str) else json.dumps(v)}
                                      for k, v in events]})["offsets"]

    def read(self, topic, start=0, max_events=100):
        q = parse.urlencode({"from": start, "max": max_events})
        return self._call("GET", f"/topics/{check_name('topic', topic)}/events?{q}")["events"]

    def end(self, topic):
        return self.topics().get(topic, 0)

    def committed(self, topic, group):
        return self._call("GET", f"/topics/{check_name('topic', topic)}/groups/{check_name('group', group)}")["offset"]

    def commit(self, topic, group, offset):
        self._call("PUT", f"/topics/{check_name('topic', topic)}/groups/{check_name('group', group)}",
                   {"offset": int(offset)})

    def topics(self):
        return self._call("GET", "/topics")


# ───────────────────────────── configuration ─────────────────────────────
def bus_config(name):
    """Settings for a named bus from the "pulse" section of algo.config.json."""
    import algoruntime
    cfg = dict((algoruntime.load_config().get("pulse") or {}).get(name) or {})
    if os.environ.get("ALGO_PULSE_URL"):
        cfg = {"url": os.environ["ALGO_PULSE_URL"], "token_env": "ALGO_PULSE_TOKEN"}
    if "url" in cfg:
        env = cfg.get("token_env", "ALGO_PULSE_TOKEN")
        return {"url": cfg["url"], "token": os.environ.get(env) or cfg.get("token")}
    base = algoruntime.config_path().parent if algoruntime.config_path() else Path.cwd()
    d = Path(cfg.get("dir", Path("pulse") / name))
    return {"dir": str(d if d.is_absolute() else base / d)}


def open_bus(settings):
    if "url" in settings:
        return PulseClient(settings["url"], settings.get("token"))
    return PulseLog(settings["dir"])


def where(settings):
    return settings.get("url") or settings["dir"]


# ───────────────────────────── server ─────────────────────────────
def make_server(root, host="127.0.0.1", port=7070, token=None, quiet=False):
    log = PulseLog(root)

    class Handler(BaseHTTPRequestHandler):
        server_version = f"{ENGINE}/1"

        def log_message(self, fmt, *args):
            if not quiet:
                sys.stderr.write(f"  pulse {self.address_string()} {fmt % args}\n")

        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _auth(self):
            if not token:
                return True
            got = self.headers.get("Authorization", "")
            if got.startswith("Bearer ") and hmac.compare_digest(got[7:].encode(), token.encode()):
                return True
            self._send(401, {"error": "missing or wrong bearer token"})
            return False

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError(f"request body over {MAX_BODY} bytes")
            return json.loads(self.rfile.read(n) or b"{}")

        def _route(self, method):
            if not self._auth():
                return
            u = parse.urlparse(self.path)
            parts = [parse.unquote(p) for p in u.path.strip("/").split("/") if p]
            q = dict(parse.parse_qsl(u.query))
            try:
                if method == "GET" and parts == ["health"]:
                    return self._send(200, {"ok": True, "engine": ENGINE, "topics": len(log.topics())})
                if method == "GET" and parts == ["topics"]:
                    return self._send(200, log.topics())
                if len(parts) == 3 and parts[0] == "topics" and parts[2] == "events":
                    t = check_name("topic", parts[1])
                    if method == "POST":
                        b = self._body()
                        evs = b.get("events", [b] if "value" in b else [])
                        if not isinstance(evs, list) or not evs:
                            return self._send(400, {"error": "send {\"events\": [{\"key\": …, \"value\": …}]}"})
                        return self._send(200, {"offsets": log.append(t, [(e.get("key"), e["value"]) for e in evs])})
                    if method == "GET":
                        start, mx = max(0, int(q.get("from", 0))), min(1000, max(1, int(q.get("max", 100))))
                        return self._send(200, {"events": log.read(t, start, mx)})
                if len(parts) == 4 and parts[0] == "topics" and parts[2] == "groups":
                    t, g = check_name("topic", parts[1]), check_name("group", parts[3])
                    if method == "GET":
                        return self._send(200, {"offset": log.committed(t, g)})
                    if method == "PUT":
                        log.commit(t, g, int(self._body()["offset"]))
                        return self._send(200, {"ok": True})
                self._send(404, {"error": "unknown route"})
            except (ValueError, KeyError, TypeError) as e:
                self._send(400, {"error": str(e)})

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        def do_PUT(self):
            self._route("PUT")

    return ThreadingHTTPServer((host, port), Handler)


# ───────────────────────────── CLI ─────────────────────────────
def _load_events(path):
    text = Path(path).read_text(encoding="utf-8")
    if path.endswith(".json"):
        items = json.loads(text)
        return [i if isinstance(i, str) else json.dumps(i, ensure_ascii=False) for i in items]
    return [ln for ln in text.splitlines() if ln.strip()]


def _key(raw, field):
    if not field:
        return None
    try:
        v = json.loads(raw)
        return str(v.get(field)) if isinstance(v, dict) and field in v else None
    except ValueError:
        return None


def cli(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="algo pulse", description="AlgoPulse: AlgoLang's real-time event engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="serve a bus over HTTP (token from ALGO_PULSE_TOKEN)")
    s.add_argument("--dir", default="pulse")
    s.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to accept other machines (set a token!)")
    s.add_argument("--port", type=int, default=7070)
    for name in ("publish", "topics", "tail"):
        p = sub.add_parser(name)
        if name in ("publish", "tail"):
            p.add_argument("topic")
        if name == "publish":
            p.add_argument("file", help="JSON Lines (one event per line) or a .json list")
            p.add_argument("--key", default=None, help="JSON field to use as the event key")
        if name == "tail":
            p.add_argument("--from", dest="start", type=int, default=0)
            p.add_argument("--max", type=int, default=20)
        p.add_argument("--bus", default="local", help="bus name from the \"pulse\" section of algo.config.json")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        token = os.environ.get("ALGO_PULSE_TOKEN")
        if a.host not in ("127.0.0.1", "localhost", "::1") and not token:
            print("refusing to serve on the network without a token: set ALGO_PULSE_TOKEN", file=sys.stderr)
            return 2
        srv = make_server(a.dir, a.host, a.port, token)
        print(f"AlgoPulse serving {Path(a.dir).resolve()} on http://{a.host}:{srv.server_port}"
              f"  ({'token required' if token else 'no token: local use only'})  Ctrl+C to stop")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            srv.server_close()
        return 0
    settings = bus_config(a.bus)
    bus = open_bus(settings)
    if a.cmd == "publish":
        evs = _load_events(a.file)
        offs = bus.append(check_name("topic", a.topic), [(_key(e, a.key), e) for e in evs])
        print(f"published {len(offs)} event(s) to {a.topic} (offsets {offs[0]}–{offs[-1]}) on {where(settings)}"
              if offs else "no events in the file")
        return 0
    if a.cmd == "topics":
        tops = bus.topics()
        print(f"bus '{a.bus}' at {where(settings)}")
        for t, n in tops.items():
            print(f"  {t:<32} {n:>8} event(s)")
        if not tops:
            print("  (no topics yet)")
        return 0
    if a.cmd == "tail":
        for e in bus.read(check_name("topic", a.topic), a.start, a.max):
            print(f"  {e['offset']:>6}  {str(e.get('key') or '-')[:20]:<20}  {e['value'][:120]}")
        return 0
    return 1
