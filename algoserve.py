"""algoserve — serve AlgoLang flows and agents as an MCP server (v0.7 Interoperability).

    algo mcp serve programs/claims_intake.algo                 # stdio: for Claude Desktop, IDEs, other agents
    algo mcp serve programs/*.algo --http 8765                 # Streamable HTTP on 127.0.0.1:8765/mcp
    algo mcp serve programs/claims_intake.algo --agents        # also expose every agent as its own tool

Every flow becomes an MCP tool whose input schema comes from the flow's typed parameters (text → string,
score → number in [0, 1], bool → boolean, list → array, json → object). A call runs the flow under exactly the
same governance as `algo run`: organisation policy, budgets, human review, signed audit log. Results carry the
run's status, emitted values, escalations, cost and the audit file; anything a person must still approve is
returned as escalated, never as a final answer.

With a progress token, a stdio client receives each agent's output token by token as MCP progress notifications.
HTTP: set ALGO_MCP_TOKEN to require "Authorization: Bearer <token>"; the server listens on 127.0.0.1 unless
--host is given. Standard library only.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import algoruntime as rt

PROTOCOL_VERSION = "2025-06-18"
SCHEMAS = {"text": {"type": "string"}, "number": {"type": "number"}, "score": {"type": "number", "minimum": 0, "maximum": 1},
           "bool": {"type": "boolean"}, "list": {"type": "array", "items": {"type": "string"}},
           "json": {"type": ["object", "array"]}}
RESULT_SCHEMA = {"type": "object", "properties": {
    "status": {"type": "string", "enum": ["ok", "blocked", "failed"]}, "values": {"type": "array"},
    "escalated": {"type": "array"}, "problem": {"type": ["string", "null"]}, "run_id": {"type": "string"},
    "audit": {"type": "string"}, "cost_usd": {"type": "number"}, "tokens": {"type": "integer"}},
    "required": ["status", "values"]}


def _schema(t):
    base = t[10:-1] if t.startswith("uncertain<") else t
    return dict(SCHEMAS.get(base, {"type": "string"}))


def _tool_name(*parts):
    return re.sub(r"[^A-Za-z0-9_-]", "_", "_".join(parts))[:64]


def _header_comment(src):
    out = []
    for line in src.splitlines():
        s = line.strip()
        if s.startswith("//"):
            out.append(s.lstrip("/ ").strip())
        elif s:
            break
    return " ".join(out)


class FlowServer:
    def __init__(self, paths, live=False, agents=False, audit_dir=None):
        import algolang as al
        self.live, self.audit_dir = live, audit_dir
        self.tools, self.out_lock = {}, threading.Lock()
        self.writer = None
        for p in paths:
            prog = al.load(p)
            src = Path(p).read_text(encoding="utf-8")
            about = _header_comment(src)
            ir = prog._prog
            risk = (ir.risk or ("minimal", "", 0))[0]
            for fname, f in ir.flows.items():
                name = _tool_name(prog.name) if fname == "main" and len(ir.flows) == 1 else _tool_name(prog.name, fname)
                desc = (f"AlgoLang flow `{fname}` of {prog.name}.algo ({risk} risk). " + (about + " " if about else "")
                        + "Runs under the organisation's policies with an audit log; results that need a person are "
                          "returned as escalated.")
                if ir.disclosure:
                    desc += f" Disclosure: {ir.disclosure}"
                self.tools[name] = dict(kind="flow", program=prog, flow=fname, spec=dict(
                    name=name, title=f"{prog.name} · {fname}", description=desc[:1000],
                    inputSchema={"type": "object", "properties": {x.name: _schema(x.type) for x in f.params},
                                 "required": [x.name for x in f.params if x.default is None]},
                    outputSchema=RESULT_SCHEMA))
            if agents:
                for aname, a in ir.agents.items():
                    name = _tool_name(prog.name, "agent", aname)
                    self.tools[name] = dict(kind="agent", program=prog, agent=aname, spec=dict(
                        name=name, title=f"{prog.name} · agent {aname}",
                        description=(f"AlgoLang agent {aname} ({a.role or 'agent'}): {a.goal}")[:1000],
                        inputSchema={"type": "object", "properties": {x.name: _schema(x.type) for x in a.params},
                                     "required": [x.name for x in a.params if x.default is None]},
                        outputSchema=RESULT_SCHEMA))

    # JSON-RPC ----------------------------------------------------------------
    def handle(self, msg, notify=None):
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if mid is None:                                   # a notification: nothing to answer
            return None
        try:
            if method == "initialize":
                result = {"protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
                          "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "algolang", "title": "AlgoLang flows", "version": rt.VERSION},
                          "instructions": "Each tool runs a governed AlgoLang flow. Treat 'escalated' results as "
                                          "pending human review, not as final answers."}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [t["spec"] for t in self.tools.values()]}
            elif method == "tools/call":
                result = self.call(params.get("name"), params.get("arguments") or {},
                                   (params.get("_meta") or {}).get("progressToken"), notify)
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except Exception as e:  # noqa
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}}

    def call(self, name, args, progress=None, notify=None):
        t = self.tools.get(name)
        if t is None:
            return {"content": [{"type": "text", "text": f"unknown tool: {name}"}], "isError": True}
        on_token = None
        if progress is not None and notify is not None:
            n = [0]

            def on_token(ev):
                if ev["type"] == "delta":
                    n[0] += 1
                    notify({"jsonrpc": "2.0", "method": "notifications/progress",
                            "params": {"progressToken": progress, "progress": n[0],
                                       "message": f"{ev['agent']}: {ev['text']}"}})
        with contextlib.redirect_stdout(sys.stderr):      # stdout belongs to the protocol
            if t["kind"] == "flow":
                res = t["program"].run(live=self.live, quiet=True, audit_dir=self.audit_dir, flow=t["flow"],
                                       on_token=on_token, **{k: v for k, v in args.items()})
            else:
                res = t["program"].call_agent(t["agent"], live=self.live, audit_dir=self.audit_dir,
                                              on_token=on_token, **args)
        values = [rt._jsonable(rt.Runtime.value(v)) for v in res.values]
        esc = [{"agent": c["agent"], "reason": c.get("review_reason")} for c in res.calls if c.get("status") == "escalated"]
        data = {"status": res.status, "values": values, "escalated": esc, "problem": res.problem, "run_id": res.run_id,
                "audit": res.audit_path, "cost_usd": res.stats.get("cost_usd", 0.0), "tokens": res.stats.get("tokens", 0)}
        text = "\n".join(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for v in values)
        if esc:
            text += "\n\nPENDING HUMAN REVIEW: " + ", ".join(e["agent"] for e in esc)
        if res.status != "ok":
            text = f"{res.status.upper()}: {res.problem}"
        return {"content": [{"type": "text", "text": text}], "structuredContent": data, "isError": res.status != "ok"}

    # transports ---------------------------------------------------------------
    def serve_stdio(self, stdin=None, stdout=None):
        stdin, stdout = stdin or sys.stdin, stdout or sys.stdout

        def write(obj):
            with self.out_lock:
                stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
                stdout.flush()
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                write({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
                continue
            batch = msg if isinstance(msg, list) else [msg]
            for m in batch:
                out = self.handle(m, notify=write)
                if out is not None:
                    write(out)
        return 0

    def http_server(self, host="127.0.0.1", port=8765):
        server, token = self, os.environ.get("ALGO_MCP_TOKEN")

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj=None):
                body = json.dumps(obj).encode() if obj is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._send(405, {"error": "use POST /mcp (Streamable HTTP, JSON responses)"})

            def do_POST(self):
                if self.path.rstrip("/") not in ("/mcp", ""):
                    return self._send(404, {"error": "not found"})
                if token and self.headers.get("Authorization") != f"Bearer {token}":
                    return self._send(401, {"error": "unauthorised"})
                try:
                    msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                except json.JSONDecodeError:
                    return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
                if isinstance(msg, list):
                    outs = [o for o in (server.handle(m) for m in msg) if o is not None]
                    return self._send(200, outs) if outs else self._send(202)
                out = server.handle(msg)
                return self._send(200, out) if out is not None else self._send(202)
        return ThreadingHTTPServer((host, port), H)


def cli(paths, http=None, host="127.0.0.1", agents=False, live=False, audit_dir=None):
    files = [p for p in paths if Path(p).is_file()]
    if not files:
        print("✗ name one or more .algo files to serve", file=sys.stderr)
        return 1
    srv = FlowServer(files, live=live, agents=agents, audit_dir=audit_dir)
    names = ", ".join(srv.tools)
    if http:
        httpd = srv.http_server(host, int(http))
        print(f"  AlgoLang MCP server on http://{host}:{http}/mcp — tools: {names}", file=sys.stderr)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    print(f"  AlgoLang MCP server (stdio) — tools: {names}", file=sys.stderr)
    return srv.serve_stdio()
