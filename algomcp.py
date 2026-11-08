"""algomcp — MCP (Model Context Protocol) tool bindings for AlgoLang (v0.3).

In a program:

    tool kb.search_policies from mcp "company-kb"     // the MCP tool `search_policies` on server company-kb

    agent PolicyDesk(q: text) -> text {
        goal "Answer {q} using the company policies"
        uses kb.search_policies
    }

In algo.config.json:

    "mcp_servers": {
        "company-kb": {"command": "{python}", "args": ["mcp_demo_server.py"]},
        "remote":     {"url": "https://example.com/mcp", "headers": {"Authorization": "Bearer …"}}
    }

`{python}` is replaced by the Python running AlgoLang. Relative paths are resolved from the folder of
algo.config.json. The MCP tool name is the part after the first dot of the AlgoLang tool name.

The same governance applies as for every other tool: the program must declare the tool, the agent must
list it under `uses`, the organisation's allowed_tools must include it, and every call is audited.
No third-party packages are needed: this module speaks MCP's JSON-RPC over stdio or HTTP itself.
"""
from __future__ import annotations

import atexit
import itertools
import json
import os
import queue
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import algoruntime as rt

PROTOCOL_VERSION = "2025-06-18"
TIMEOUT = float(os.environ.get("ALGO_MCP_TIMEOUT", "30"))


class MCPError(Exception):
    pass


class _Base:
    def __init__(self, name, cfg):
        self.name, self.cfg = name, cfg
        self.ids = itertools.count(1)
        self.lock = threading.Lock()
        self.server_info, self._tools = {}, None

    def initialize(self):
        res = self.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                          "clientInfo": {"name": "algolang", "version": rt.VERSION}})
        self.server_info = res.get("serverInfo") or {}
        self.notify("notifications/initialized", {})
        return res

    def tools(self, refresh=False):
        if self._tools is None or refresh:
            out, cursor = [], None
            while True:
                res = self.request("tools/list", {"cursor": cursor} if cursor else {})
                out += res.get("tools", [])
                cursor = res.get("nextCursor")
                if not cursor:
                    break
            self._tools = {t["name"]: t for t in out}
        return self._tools

    def call(self, tool, arguments):
        res = self.request("tools/call", {"name": tool, "arguments": arguments or {}})
        parts = []
        for c in res.get("content") or []:
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            elif c.get("type") == "resource":
                parts.append(json.dumps(c.get("resource", {}))[:2000])
            else:
                parts.append(f"[{c.get('type', 'content')}]")
        if not parts and res.get("structuredContent") is not None:
            parts.append(json.dumps(res["structuredContent"], ensure_ascii=False))
        text = "\n".join(parts)
        return f"tool error: {text}" if res.get("isError") else text


class StdioClient(_Base):
    """Starts the server as a subprocess and talks newline-delimited JSON-RPC over its stdin/stdout."""

    def __init__(self, name, cfg, base_dir: Path):
        super().__init__(name, cfg)
        cmd = [str(cfg["command"]).replace("{python}", sys.executable)] + \
              [str(a).replace("{python}", sys.executable) for a in cfg.get("args", [])]
        cwd = Path(cfg.get("cwd") or base_dir)
        if not cwd.is_absolute():
            cwd = base_dir / cwd
        env = dict(os.environ, **{k: str(v) for k, v in (cfg.get("env") or {}).items()})
        self.proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1)
        self.waiting: dict[int, queue.Queue] = {}
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue                      # servers may print logs; ignore anything that is not JSON-RPC
            q = self.waiting.get(msg.get("id")) if "id" in msg and ("result" in msg or "error" in msg) else None
            if q:
                q.put(msg)
        for q in list(self.waiting.values()):
            q.put({"error": {"message": f"MCP server '{self.name}' exited"}})

    def _send(self, msg):
        with self.lock:
            if self.proc.poll() is not None:
                raise MCPError(f"MCP server '{self.name}' is not running (exit code {self.proc.returncode})")
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()

    def request(self, method, params=None):
        i = next(self.ids)
        q = self.waiting[i] = queue.Queue()
        try:
            self._send({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}})
            try:
                msg = q.get(timeout=TIMEOUT)
            except queue.Empty:
                raise MCPError(f"MCP server '{self.name}' did not answer {method} within {TIMEOUT:.0f}s")
        finally:
            self.waiting.pop(i, None)
        if "error" in msg:
            raise MCPError(f"{self.name}: {msg['error'].get('message', msg['error'])}")
        return msg.get("result") or {}

    def notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=3)
        except Exception:  # noqa
            self.proc.kill()


class HttpClient(_Base):
    """Streamable-HTTP transport: JSON-RPC over POST; answers may come as JSON or as server-sent events."""

    def __init__(self, name, cfg, base_dir=None):
        super().__init__(name, cfg)
        self.url, self.session = cfg["url"], None

    def _post(self, msg):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": PROTOCOL_VERSION, **(self.cfg.get("headers") or {})}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, data=json.dumps(msg).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            self.session = r.headers.get("Mcp-Session-Id") or self.session
            body = r.read().decode("utf-8", errors="replace")
            ctype = r.headers.get("Content-Type", "")
        if not body.strip():
            return None
        if "text/event-stream" in ctype:
            for line in body.splitlines():
                if line.startswith("data:"):
                    try:
                        m = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if m.get("id") == msg.get("id"):
                        return m
            return None
        return json.loads(body)

    def request(self, method, params=None):
        msg = self._post({"jsonrpc": "2.0", "id": next(self.ids), "method": method, "params": params or {}})
        if msg is None:
            raise MCPError(f"{self.name}: no answer to {method}")
        if "error" in msg:
            raise MCPError(f"{self.name}: {msg['error'].get('message', msg['error'])}")
        return msg.get("result") or {}

    def notify(self, method, params=None):
        self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self):
        pass


_CLIENTS: dict[str, _Base] = {}
_CLIENTS_LOCK = threading.Lock()


def client(server, cfg=None):
    """A connected, initialised client for a configured server (one per process, reused)."""
    with _CLIENTS_LOCK:
        if server in _CLIENTS:
            return _CLIENTS[server]
        cfg = cfg or (rt.load_config().get("mcp_servers") or {}).get(server)
        if not cfg:
            raise MCPError(f"MCP server '{server}' is not configured (mcp_servers in algo.config.json)")
        p = rt.config_path()
        base = p.resolve().parent if p else Path.cwd()
        c = HttpClient(server, cfg, base) if cfg.get("url") else StdioClient(server, cfg, base)
        try:
            c.initialize()
        except Exception:
            c.close()
            raise
        _CLIENTS[server] = c
        return c


@atexit.register
def close_all():
    for c in list(_CLIENTS.values()):
        c.close()
    _CLIENTS.clear()


def _arguments(schema, query):
    """Turn an agent's request into tool arguments. Dicts pass through (live tool use fills the schema);
    text goes to the only/required string property, or to `query`, or is parsed as JSON."""
    if isinstance(query, dict):
        return query
    props = (schema or {}).get("properties") or {}
    required = [r for r in (schema or {}).get("required", []) if props.get(r, {}).get("type", "string") == "string"]
    strings = [k for k, v in props.items() if v.get("type", "string") == "string"]
    if len(required) == 1:
        return {required[0]: query}
    if "query" in props:
        return {"query": query}
    s = str(query).strip()
    if s.startswith("{"):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
    return {strings[0]: query} if strings else {}


def bind_tool(name, server, cfg=None):
    """Register AlgoLang tool `name` as MCP tool (part after the first dot) on `server`."""
    remote = name.split(".", 1)[1] if "." in name else name
    try:
        c = client(server, cfg)
        spec = c.tools().get(remote)
        if spec is None:
            raise MCPError(f"MCP server '{server}' has no tool '{remote}' (it has: {', '.join(c.tools()) or 'none'})")
        schema = spec.get("inputSchema") or {"type": "object", "properties": {}}

        def call(query):
            return c.call(remote, _arguments(schema, query))

        rt.TOOLS[name] = rt.Tool(name, call, spec.get("description") or f"{remote} (MCP server {server})", schema)
    except Exception as e:  # noqa — the agent sees the problem as the tool's answer; the run is audited
        msg = f"MCP server '{server}' unavailable: {e}"

        def broken(_query, _msg=msg):
            return f"tool error: {_msg}"

        rt.TOOLS[name] = rt.Tool(name, broken, msg)


def cli(action, server=None, tool=None, arguments="{}"):
    servers = rt.load_config().get("mcp_servers") or {}
    if action == "servers":
        if not servers:
            print('  no MCP servers configured. Add them to algo.config.json, e.g.\n'
                  '  "mcp_servers": {"company-kb": {"command": "{python}", "args": ["mcp_demo_server.py"]}}')
            return 0
        for n, c in servers.items():
            how = c.get("url") or " ".join([c.get("command", "")] + list(c.get("args", [])))
            print(f"  {n:<20} {how}")
        return 0
    if not server:
        print("✗ name the server, e.g.  algo mcp list company-kb", file=sys.stderr)
        return 1
    try:
        c = client(server)
        if action == "list":
            info = c.server_info
            print(f"  {server}: {info.get('name', '')} {info.get('version', '')}".rstrip())
            for t in c.tools().values():
                props = ", ".join((t.get("inputSchema") or {}).get("properties", {}))
                print(f"    {t['name']}({props})  {t.get('description', '')[:90]}")
                print(f"      use it:  tool {server.replace('-', '_')}.{t['name']} from mcp \"{server}\"")
            return 0
        if not tool:
            print("✗ name the tool, e.g.  algo mcp call company-kb search_policies '{\"query\": \"refund\"}'",
                  file=sys.stderr)
            return 1
        print(c.call(tool, json.loads(arguments or "{}")))
        return 0
    except (MCPError, json.JSONDecodeError, OSError) as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
