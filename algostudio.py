"""
algostudio — AlgoLang Studio (graphical IDE) and the Prompt UI, served from your own computer
AlgoProfessor AI R&D Solutions · AlgoLang v0.2 "Enterprise"

    algo studio            Studio: editor, run, agent graph, domain library, batch, governance
    algo ui                Prompt UI: describe a problem in plain English, get a running solution
    algo studio --port 9000 --no-browser

Everything runs on your own computer; the server listens only on 127.0.0.1.
Programs are saved in the folder you start Studio from (the workspace).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
os.environ.setdefault("ALGO_HOME", str(HERE))

import algoagent  # noqa: E402
import algolang as al  # noqa: E402
import algoruntime  # noqa: E402
from algoc import VERSION, CompileError, compile_source, flow_graph  # noqa: E402

RUN_LOCK = threading.Lock()
WORKSPACE = Path.cwd()


def _diag_list(e: CompileError):
    return [{"code": d.code, "line": d.line if not d.file else 0,
             "msg": (f"in {d.file} line {d.line}: " if d.file else "") + d.msg} for d in e.diags]


def _compile(src):
    try:
        code, prog = compile_source(src, "studio.algo", WORKSPACE)
        return code, prog, []
    except CompileError as e:
        return None, None, _diag_list(e)


def _summary(prog):
    main = prog.flows.get("main")
    return {"agents": sorted(prog.agents), "flows": sorted(prog.flows), "tools": sorted(prog.tools),
            "inputs": [p.name for p in main.params] if main else []}


def _jsonable(v):
    v = algoruntime.Runtime.value(v)
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def api_check(body):
    code, prog, diags = _compile(body.get("source", ""))
    if diags:
        return {"ok": False, "diagnostics": diags}
    return {"ok": True, "summary": _summary(prog)}


def api_graph(body):
    code, prog, diags = _compile(body.get("source", ""))
    if diags:
        return {"ok": False, "diagnostics": diags}
    nodes, edges = flow_graph(prog)
    return {"ok": True, "nodes": [dict(id=a, label=b, kind=c, sub=d) for a, b, c, d in nodes],
            "edges": [dict(src=a, dst=b, dashed=c) for a, b, c in edges]}


def api_python(body):
    code, prog, diags = _compile(body.get("source", ""))
    return {"ok": not diags, "python": code, "diagnostics": diags}


def api_run(body):
    src = body.get("source", "")
    name = re.sub(r"\W+", "_", body.get("name") or "studio").strip("_") or "studio"
    code, prog, diags = _compile(src)
    if diags:
        return {"ok": False, "diagnostics": diags}
    args = {k: str(v) for k, v in (body.get("args") or {}).items()}
    missing = [p.name for p in prog.flows["main"].params if not args.get(p.name)]
    if missing:
        return {"ok": False, "problem": f"Fill in the input(s): {', '.join(missing)}"}
    code = code.replace("Runtime(program='studio',", f"Runtime(program={name!r},")
    buf = io.StringIO()
    result, problem, rt = None, None, None
    with RUN_LOCK:
        os.environ["ALGO_HOME"] = str(HERE)
        os.environ.pop("ALGO_INTERACTIVE", None)
        os.environ.pop("ALGO_NOTEBOOK", None)
        ns = {"__name__": "algo_studio", "__algo_runtime__": {"live": bool(body.get("live")), "quiet": False}}
        with contextlib.redirect_stdout(buf):
            try:
                exec(compile(code, "<algo studio>", "exec"), ns)
                rt = ns["rt"]
                result = ns["flow_main"](**args)
            except SystemExit as e:
                problem = str(e.code)
            except algoruntime.PolicyViolation as e:
                problem = f"Policy violation: {e}"
            except Exception as e:  # noqa
                problem = f"{type(e).__name__}: {e}"
    calls = []
    if rt:
        for c in rt.calls:
            c = dict(c)
            c["output"] = _jsonable(c.get("output"))
            calls.append(c)
    return {"ok": problem is None, "problem": problem, "log": buf.getvalue(),
            "result": _jsonable(result) if result is not None else None, "calls": calls,
            "stats": rt.stats if rt else {}, "backend": rt.backend.name if rt else None,
            "audit": str(rt.audit_path) if rt else None}


def api_files(_body=None):
    files = []
    for base, label in ((WORKSPACE, "workspace"), (HERE / "examples", "example")):
        for p in sorted(base.glob("*.algo")):
            files.append({"name": p.name, "kind": label,
                          "path": str(p.relative_to(WORKSPACE)) if label == "workspace" else f"examples/{p.name}"})
    seen, out = set(), []
    for f in files:
        if f["name"] not in seen or f["kind"] == "example":
            out.append(f)
            seen.add(f["name"])
    return {"files": out, "workspace": str(WORKSPACE)}


def api_open(body):
    rel = body.get("path", "")
    p = (HERE / rel) if rel.startswith("examples/") else (WORKSPACE / rel)
    p = p.resolve()
    if p.suffix != ".algo" or not (str(p).startswith(str(WORKSPACE.resolve())) or str(p).startswith(str(HERE.resolve()))):
        return {"ok": False, "problem": "Only .algo files in the workspace or examples can be opened."}
    if not p.exists():
        return {"ok": False, "problem": "File not found."}
    return {"ok": True, "name": p.name, "source": p.read_text(encoding="utf-8")}


def api_save(body):
    name = Path(body.get("name", "")).name
    if not name:
        return {"ok": False, "problem": "Give the program a file name."}
    if not name.endswith(".algo"):
        name += ".algo"
    p = WORKSPACE / name
    p.write_text(body.get("source", ""), encoding="utf-8")
    return {"ok": True, "name": name, "path": str(p)}


def api_templates(_body=None):
    return {"patterns": [{"id": k, "title": v} for k, v in algoagent.PATTERNS.items()]}


def api_template(body):
    try:
        src = algoagent.template(body.get("pattern", "fanout"), body.get("purpose") or "the user's request",
                                 re.sub(r"\W+", "_", body.get("input") or "request").strip("_").lower() or "request",
                                 0.75, ["gender", "caste", "religion", "nationality"], 4000)
        return {"ok": True, "source": src}
    except Exception as e:  # noqa
        return {"ok": False, "problem": str(e)}


def api_ask(body):
    lines = []
    try:
        res = algoagent.write_program(body.get("request", ""), current=body.get("current") or None,
                                      log=lines.append)
    except algoagent.AskError as e:
        return {"ok": False, "problem": str(e), "log": lines}
    except Exception as e:  # noqa
        return {"ok": False, "problem": f"{type(e).__name__}: {e}", "log": lines}
    return {"ok": res["ok"], "source": res["source"], "attempts": res["attempts"],
            "diagnostics": res["diagnostics"], "log": lines}


def api_status(_body=None):
    try:
        import anthropic  # noqa: F401
        sdk = True
    except ImportError:
        sdk = False
    return {"version": VERSION, "live_ready": sdk and bool(os.environ.get("ANTHROPIC_API_KEY")),
            "sdk": sdk, "key": bool(os.environ.get("ANTHROPIC_API_KEY")), "workspace": str(WORKSPACE)}


# ─────────────────────────── enterprise endpoints ───────────────────────────
def api_domains(body):
    q, sector = (body.get("q") or "").strip(), body.get("sector") or None
    packs = al.domains.search(q, k=24) if q else al.domains.all(sector)
    return {"sectors": al.domains.sectors(), "packs": packs, "total": len(al.domains.all())}


def api_pack(body):
    try:
        m = al.domains.get(body.get("id", ""))
    except KeyError as e:
        return {"ok": False, "problem": e.args[0]}
    return {"ok": True, "meta": m, "source": al.domains.source(m["id"])}


def api_batch(body):
    import csv
    src, text = body.get("source", ""), body.get("csv", "")
    code, prog, diags = _compile(src)
    if diags:
        return {"ok": False, "diagnostics": diags}
    try:
        p = al.compile(src, re.sub(r"\W+", "_", body.get("name") or "batch"), WORKSPACE)
    except CompileError as e:
        return {"ok": False, "diagnostics": _diag_list(e)}
    rows_in = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    if not rows_in:
        return {"ok": False, "problem": "The CSV has no rows. The first line must be the column names."}
    cols = list(rows_in[0].keys())
    rows = []
    for r in rows_in[:5000]:
        if all(i in r for i in p.inputs):
            rows.append({i: r[i] for i in p.inputs})
        elif len(p.inputs) == 1:
            rows.append({p.inputs[0]: r[cols[0]]})
        else:
            return {"ok": False, "problem": f"The CSV needs columns named: {', '.join(p.inputs)}"}
    import time as _t
    t0 = _t.time()
    res = p.run_batch(rows, workers=int(body.get("workers") or 8), live=bool(body.get("live")))
    out_rows, width = [], max((len(r.values) for r in res), default=0)
    for n, r in enumerate(res, 1):
        vals = [_jsonable(v) for v in r.values]
        vals = ["; ".join(map(str, v)) if isinstance(v, list) else v for v in vals]
        out_rows.append({"row": n, "inputs": r.inputs, "status": r.status, "escalated": len(r.escalated),
                         "tokens": r.stats.get("tokens", 0), "problem": r.problem, "outputs": vals})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["row", *p.inputs, "status", "escalated", "tokens", "problem", *[f"output_{i + 1}" for i in range(width)]])
    for r in out_rows:
        w.writerow([r["row"], *[r["inputs"].get(i, "") for i in p.inputs], r["status"], r["escalated"], r["tokens"],
                    r["problem"] or "", *r["outputs"]])
    st = {}
    for r in res:
        st[r.status] = st.get(r.status, 0) + 1
    return {"ok": True, "rows": out_rows, "inputs": p.inputs, "csv": buf.getvalue(), "seconds": round(_t.time() - t0, 2),
            "summary": {"rows": len(res), "status": st, "escalated_rows": sum(1 for r in res if r.escalated),
                        "tokens": sum(r.stats.get("tokens", 0) for r in res)}}


def api_reviews(body=None):
    body = body or {}
    items = al.review.all() if body.get("all") else al.review.pending()
    return {"items": list(reversed(items))[:200], "pending": len(al.review.pending())}


def api_review(body):
    try:
        fn = al.review.approve if body.get("decision") == "approved" else al.review.reject
        fn(body.get("id", ""), body.get("reviewer", ""), body.get("note", ""))
        return {"ok": True, "pending": len(al.review.pending())}
    except Exception as e:  # noqa
        return {"ok": False, "problem": str(e)}


def api_report(body=None):
    d = algoruntime.audit_dir()
    rep = al.audit.report(d) if Path(d).exists() else {"totals": {}, "programs": {}, "agents": {}, "chains": {}}
    rq = algoruntime.review_queue_path()
    if rq.exists():
        rep["chains"][rq.name] = algoruntime.verify_audit(rq)["ok"]
    return dict(rep, audit_dir=str(d))


def api_config(body=None):
    cfg = algoruntime.load_config()
    p = algoruntime.config_path()
    return {"path": str(p) if p else None, "organisation": cfg.get("organisation"), "policy": cfg.get("policy"),
            "max_concurrency": cfg.get("max_concurrency"), "max_run_tokens": cfg.get("max_run_tokens"),
            "cache": cfg.get("cache"), "models": cfg.get("models"),
            "tools": sorted(algoruntime.TOOLS)}


def api_compose(body):
    """Prompt UI: plain-English request → best domain pack → run it."""
    req = (body.get("request") or "").strip()
    if not req:
        return {"ok": False, "problem": "Describe what you need."}
    matches = al.domains.search(req, k=4)
    if not matches:
        return {"ok": False, "problem": "No domain pack matches that yet. Try different words, or ask AI to write a program."}
    best = matches[0]
    if body.get("pick"):
        best = next((m for m in matches if m["id"] == body["pick"]), None) or dict(al.domains.get(body["pick"]), score=0)
    alts = [m for m in matches if m["id"] != best["id"]][:3]
    source = body.get("source") or al.domains.source(best["id"])
    try:
        prog = al.compile(source, best["id"].split(".")[1], WORKSPACE)
    except CompileError as e:
        return {"ok": False, "diagnostics": _diag_list(e)}
    value = body.get("input") or req
    res = prog.run(live=bool(body.get("live")), **{prog.inputs[0]: value})
    d = res.to_dict()
    return {"ok": True, "pack": best, "alternatives": alts, "source": source, "graph": prog.graph(),
            "inputs": prog.inputs, "policies": prog.policies(), "run": d}


ROUTES = {"/api/check": api_check, "/api/graph": api_graph, "/api/python": api_python,
          "/api/run": api_run, "/api/files": api_files, "/api/open": api_open, "/api/save": api_save,
          "/api/templates": api_templates, "/api/template": api_template, "/api/ask": api_ask,
          "/api/status": api_status, "/api/domains": api_domains, "/api/pack": api_pack,
          "/api/batch": api_batch, "/api/reviews": api_reviews, "/api/review": api_review,
          "/api/report": api_report, "/api/config": api_config, "/api/compose": api_compose}


class Handler(BaseHTTPRequestHandler):
    server_version = "AlgoLangStudio/" + VERSION

    def log_message(self, fmt, *args):  # keep the terminal quiet
        pass

    def _send(self, status, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if "json" in ctype or "html" in ctype else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._send(200, (HERE / "algostudio.html").read_bytes(), "text/html")
        if path in ("/prompt", "/prompt.html"):
            return self._send(200, (HERE / "algoprompt.html").read_bytes(), "text/html")
        if path in ("/api/files", "/api/templates", "/api/status", "/api/reviews", "/api/report", "/api/config"):
            return self._send(200, ROUTES[path]())
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if path not in ROUTES:
            return self._send(404, {"error": "not found"})
        # only accept requests from Studio's own page (protects against other websites calling it)
        origin = self.headers.get("Origin")
        if origin and not re.match(r"^http://(127\.0\.0\.1|localhost):\d+$", origin):
            return self._send(403, {"error": "forbidden origin"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad json"})
        try:
            self._send(200, ROUTES[path](body))
        except Exception as e:  # noqa
            self._send(500, {"ok": False, "problem": f"{type(e).__name__}: {e}"})


def _free_port(start):
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def serve(port=8765, open_browser=True, page="", host="127.0.0.1"):
    global WORKSPACE
    WORKSPACE = Path.cwd()
    port = _free_port(port)
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://127.0.0.1:{port}"
    if host not in ("127.0.0.1", "localhost"):
        print(f"⚠ Studio is listening on {host}:{port}. It has no login: expose it only inside a container "
              "or behind an authenticating proxy. Browsers must open it as http://localhost:PORT.")
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa
            pass
    print(f"AlgoLang Studio {VERSION} running at {url}")
    print(f"Workspace: {WORKSPACE}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url + ("/" + page if page else ""))).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStudio stopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    serve()
