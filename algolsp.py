"""algolsp — the AlgoLang language server (v0.3).

    algo lsp        speaks the Language Server Protocol over stdin/stdout

Editors get, for every .algo file:
  • diagnostics   every compiler error (E100–E121) as you type, including org-policy checks
  • hover         an agent's signature, role, goal, tools and policy; tools; models; keywords
  • completion    keywords, types, agents (including `alias.Agent` from packs), tools, models,
                  domain packs after `use pack`, and snippets for agent / flow / eval blocks
  • definition    jump to an agent, flow or tool — also into imported files and domain packs
  • outline       agents, flows, eval blocks, tools and models

No third-party packages: the protocol is implemented here on top of the real compiler (algoc).
"""
from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import algoc

KEYWORDS = {
    "agent": "**agent** — the only unit of work. `agent Name(p: text) -> type { role … goal … uses … policy { … } }`",
    "flow": "**flow** — orchestrates agents: assign, `par`, `par for`, `if`, `emit`. Every program has `flow main`.",
    "par": "**par** — run agent calls in parallel: `[a, b] = par { A(x), B(x) }` or `par for t in items { A(t) }`.",
    "emit": "**emit** — return values from the flow.",
    "policy": "**policy** — rules the runtime enforces: `budget tokens N`, `budget cost 0.05 usd`, "
              "`budget energy 2 wh`, `retry N`, `timeout S`, `require human when confidence < 0.8`, "
              "`forbid caste, gender`, `cache`, `samples N`.",
    "uncertain": "**uncertain<T>** — the agent is sampled several times (`samples N`, default 3); the result "
                 "carries `.confidence` from how much the samples agree. Compare it together with its "
                 "confidence: `if r > 0.8 and r.confidence >= 0.7` (otherwise E117).",
    "samples": "**samples N** — how many times an `uncertain<T>` agent is sampled (1–15, default 3).",
    "budget": "**budget** — `budget tokens 4000`, `budget cost 0.05 usd` (or inr), `budget energy 2 wh` (or kwh). "
              "Cost and energy are priced before the call; a call over budget is blocked.",
    "eval": "**eval** — tests next to the code: `eval name on main { case \"label\" (input = \"…\") { expect … } }`. "
            "Run with `algo eval file.algo`; `--replay` re-checks from recorded traces with no model calls.",
    "risk": "**risk** — the program's risk level (v0.4): `risk minimal`, `risk limited \"purpose\"` (needs `disclose`) or "
            "`risk high \"purpose\"`, which also needs human oversight, `explain with evidence`, `redact pii`, fairness "
            "and robustness evals and signed audit logs (E125–E129).",
    "disclose": "**disclose** — the notice people see: `disclose \"You are chatting with an AI assistant.\"` Required for "
                "limited- and high-risk programs.",
    "explain": "**explain** — in a policy: `explain` (reasons) or `explain with evidence` (reasons plus quotes that must "
               "appear in the agent's inputs or tool results; otherwise the result goes to a person).",
    "redact": "**redact pii** — mask names, phone numbers, emails, Aadhaar, PAN, account and card numbers before any model "
              "call. Trusted tools still receive the real values.",
    "retain": "**retain** — `retain audit 180 days` / `retain traces 30 days`: older records are removed after each run; "
              "a signed checkpoint keeps the audit chain verifiable.",
    "approvals": "**require approvals N** — N different named reviewers must approve each result (four-eyes = 2).",
    "untrusted": "**untrusted** — `tool web.fetch untrusted`: its output is size-limited, instruction-like lines are "
                 "removed, and it is wrapped as data the model must not obey.",
    "fair": "**expect fair across** attribute [values] — run the case once per value and require the same decision "
            "(scores within `fairness_tolerance`, default 0.05).",
    "robust": "**expect robust** (typos, paraphrase, reorder, case, spacing) consistency >= 0.9 — perturb the inputs and "
              "require the same decision.",
    "stream": "**stream** — real-time events: `stream name on main { from pulse \"bus\" topic \"in\"  map x = event.x  "
              "to topic \"out\"  escalate to topic \"review\"  dead letter topic \"dlq\" }`. Every event runs the flow "
              "once. Run with `algo stream file.algo --pulse` (or `--input events.jsonl` offline).",
    "shots": "**shots N**: measurements per quantum circuit for this agent's `quantum.*` tools (1–100000).",
    "qubits": "**max qubits N**: the largest circuit this agent's `quantum.*` tools may run; the stricter of this and "
              "`quantum.max_qubits` in algo.config.json applies. Bigger circuits are BLOCKED.",
    "quantum": "**quantum.*** tools: `quantum.run` (OpenQASM 2.0), `quantum.qubo`, `quantum.maxcut` and `quantum.routes` "
               "(QAOA, VERIFIED against the exact optimum), `quantum.scenarios` (Monte Carlo VaR with a QAE check), "
               "`quantum.grover`, `quantum.random`; `pqc.scan` for quantum-safe readiness. v0.6: `quantum.vqe`, "
               "`quantum.kernel`, `quantum.amplitude`, `quantum.knapsack`, `quantum.colouring`, `quantum.backend`, on a "
               "simulator, a noisy simulator or IBM, Braket and Azure hardware. Guard on `contains \"VERIFIED\"` "
               "(or `\"BOUNDED\"` beyond exact checks).",
    "qpu": "**budget qpu N seconds | minutes | usd** (v0.6) — the most QPU time or money this agent's quantum tools may "
           "use; checked before a job is submitted. `expect qpu < N` in an eval checks the run's QPU seconds.",
    "fidelity": "**expect fidelity > x** (v0.6) — the lowest Hellinger fidelity of the run's quantum jobs against the "
                "ideal result (1.0 on the exact simulator).",
    "circuit": "**circuit** — a quantum circuit written gate by gate: `circuit Bell { qubits 2  h q0  cx q0, q1  measure }`. "
               "It becomes the tool `circuit.Bell`; agents run it with `uses circuit.Bell` under their `shots` policy. "
               "`algo quantum export file.algo` prints the OpenQASM 2.0.",
    "measure": "**measure** — measure every qubit at the end of a circuit (the default when omitted).",
    "pulse": "**pulse** — `from pulse \"bus\" topic \"name\" group \"consumer-group\"`: AlgoPulse™, AlgoLang's built-in "
             "event engine. A bus is a local folder or a served bus: `\"pulse\": {\"bus\": {\"dir\": \"pulse\"}}` or "
             "`{\"url\": \"http://host:7070\", \"token_env\": \"PULSE_TOKEN\"}` in algo.config.json.",
    "case": "**case** — one eval case: `case \"label\" (input = \"value\") { expect … }`.",
    "expect": "**expect** — `status ok`, `called A`, `not called A`, `tool t`, `output contains \"…\"`, `emits N`, "
              "`tokens < N`, `cost < 0.05`, `energy < 1`, `escalated <= N`, `confidence >= 0.7`.",
    "use": "**use** — `use \"file.algo\" as x` or `use pack sector.name as x`, then call `x.Agent(…)`.",
    "tool": "**tool** — declare a capability: `tool kb.search`, or bind an MCP tool: "
            "`tool kb.search_policies from mcp \"company-kb\"`.",
    "mcp": "**from mcp \"server\"** — the tool is served by an MCP server listed in `mcp_servers` in algo.config.json.",
    "model": "**model** — `model fast = \"claude-haiku-5-5\"`, then `model fast` inside an agent.",
    "role": "**role** — who the agent is (goes into the prompt).",
    "goal": "**goal** — what the agent must do; `{param}` inserts an argument.",
    "uses": "**uses** — tools this agent may call (declared with `tool`, allowed by the org config).",
    "require": "**require human when confidence < X** — low-confidence results go to the human review queue.",
    "forbid": "**forbid a, b** — protected attributes that must never reach this agent (E108).",
    "cache": "**cache** — reuse identical answers at zero tokens.",
    "retry": "**retry N** — retry failed model calls.",
    "timeout": "**timeout S** — fail a call slower than S seconds.",
    "if": "**if** — branch on scores: `if risk > 0.8 and risk.confidence >= 0.7 { … } else { … }`.",
    "and": "**and** — both comparisons must hold.",
    "or": "**or** — either comparison may hold.",
    "confidence": "**x.confidence** — the confidence of an agent result (0–1).",
    "contains": "**x contains \"TEXT\"** — a deterministic guard: true if the result (or its tools' full answer) "
                "contains the text, case-insensitive. No model is involved, so hard rules cannot be overruled.",
}
TYPE_DOCS = {"text": "free text", "score": "a number from 0 to 1", "list": "a list of items (use with `par for`)",
             "json": "a JSON object", "bool": "true or false"}
SNIPPETS = [
    ("agent", "agent ${1:Name}(${2:input}: text) -> ${3:text} {\n    role \"${4:role}\"\n    goal \"${5:do something with} {${2:input}}\"\n}"),
    ("flow main", "flow main(${1:input}: text) {\n    ${2:result} = ${3:Agent}(${1:input})\n    emit ${2:result}\n}"),
    ("eval", "eval ${1:regression} on main {\n    case \"${2:first case}\" (${3:input} = \"${4:value}\") {\n        expect status ok\n    }\n}"),
    ("circuit", "circuit ${1:Bell} {\n    qubits ${2:2}\n    h q0\n    cx q0, q1\n    measure\n}"),
    ("risk", "risk ${1|minimal,limited,high|} \"${2:purpose}\"\ndisclose \"${3:You are using an AI system. A person reviews its decisions.}\""),
    ("trust policy", "policy { redact pii  explain with evidence  require approvals ${1:2} }"),
    ("fairness test", "expect fair across ${1:gender} [\"${2:woman}\", \"${3:man}\", \"${4:non-binary}\"]\nexpect robust consistency >= ${5:0.9}\nexpect explained"),
    ("stream", "stream ${1:events} on main {\n    from pulse \"${2:local}\" topic \"${3:events.in}\" group \"${4:algolang}\"\n    map ${5:input} = event.${5:input}\n    key event.${6:id}\n    to topic \"${7:events.out}\"\n    escalate to topic \"${8:events.review}\"\n    dead letter topic \"${9:events.dlq}\"\n}"),
    ("policy", "policy {\n    budget tokens ${1:4000}\n    budget cost ${2:0.05} usd\n    require human when confidence < ${3:0.8}\n}"),
]


def uri_to_path(uri):
    p = urlparse(uri)
    return Path(url2pathname(unquote(p.path))) if p.scheme == "file" else Path(uri)


def path_to_uri(path):
    return Path(path).resolve().as_uri()


class Server:
    def __init__(self, rfile=None, wfile=None):
        self.rfile = rfile or sys.stdin.buffer
        self.wfile = wfile or sys.stdout.buffer
        self.docs: dict[str, str] = {}
        self.progs: dict[str, object] = {}
        self.lock = threading.Lock()
        self.running = True

    # ── transport ───────────────────────────────────────────────────────────
    def read(self):
        headers = {}
        while True:
            line = self.rfile.readline()
            if not line:
                return None
            line = line.decode("ascii", errors="replace").strip()
            if not line:
                break
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()
        n = int(headers.get("content-length", 0))
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else None

    def send(self, msg):
        body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        with self.lock:
            self.wfile.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
            self.wfile.flush()

    def reply(self, mid, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": mid}
        msg["error" if error else "result"] = error or result
        self.send(msg)

    def notify(self, method, params):
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    # ── loop ────────────────────────────────────────────────────────────────
    def serve(self):
        while self.running:
            msg = self.read()
            if msg is None:
                break
            method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
            try:
                handler = getattr(self, "on_" + (method or "").replace("/", "_").replace("$", "S"), None)
                if handler is None:
                    if mid is not None:
                        self.reply(mid, error={"code": -32601, "message": f"not supported: {method}"})
                    continue
                result = handler(params)
                if mid is not None:
                    self.reply(mid, result)
            except Exception as e:  # noqa — never crash the editor's server
                if mid is not None:
                    self.reply(mid, error={"code": -32603, "message": f"{type(e).__name__}: {e}"})
        return 0

    # ── lifecycle ───────────────────────────────────────────────────────────
    def on_initialize(self, _p):
        return {"capabilities": {"textDocumentSync": {"openClose": True, "change": 1, "save": True},
                                 "hoverProvider": True, "definitionProvider": True, "documentSymbolProvider": True,
                                 "completionProvider": {"triggerCharacters": [".", " "]}},
                "serverInfo": {"name": "algolang-lsp", "version": algoc.VERSION}}

    def on_initialized(self, _p):
        return None

    def on_shutdown(self, _p):
        return None

    def on_exit(self, _p):
        self.running = False

    # ── documents ───────────────────────────────────────────────────────────
    def on_textDocument_didOpen(self, p):
        d = p["textDocument"]
        self.docs[d["uri"]] = d["text"]
        self.check(d["uri"])

    def on_textDocument_didChange(self, p):
        uri = p["textDocument"]["uri"]
        changes = p.get("contentChanges") or []
        if changes:
            self.docs[uri] = changes[-1]["text"]
        self.check(uri)

    def on_textDocument_didSave(self, p):
        uri = p["textDocument"]["uri"]
        if p.get("text") is not None:
            self.docs[uri] = p["text"]
        self.check(uri)

    def on_textDocument_didClose(self, p):
        uri = p["textDocument"]["uri"]
        self.docs.pop(uri, None)
        self.notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": []})

    def compile(self, uri):
        """Compile the open document. Returns (program or None, diagnostics)."""
        path = uri_to_path(uri)
        src = self.docs.get(uri, "")
        try:
            prog, diags = algoc.load_program(src, path.name, path.parent, stack=(str(path.resolve()),))
            self.progs[uri] = prog
        except algoc.CompileError as e:
            prog, diags = self.progs.get(uri), e.diags
        return prog, diags

    def check(self, uri):
        _prog, diags = self.compile(uri)
        lines = self.docs.get(uri, "").splitlines() or [""]
        out = []
        for d in diags:
            msg = str(d.msg).split("\n")[0]
            if d.file:                                   # error inside an imported file
                line = self._use_line(lines, d.file)
                msg = f"in {d.file} (line {d.line}): {msg}"
            else:
                line = max(0, (d.line or 1) - 1)
            line = min(line, len(lines) - 1)
            text = lines[line]
            start = len(text) - len(text.lstrip())
            out.append({"range": {"start": {"line": line, "character": start},
                                  "end": {"line": line, "character": max(start + 1, len(text))}},
                        "severity": 1, "code": d.code, "source": "algolang", "message": msg})
        self.notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": out})
        return out

    @staticmethod
    def _use_line(lines, label):
        target = label.replace("pack ", "")
        for i, ln in enumerate(lines):
            if ln.strip().startswith("use") and target in ln:
                return i
        return 0

    # ── language features ───────────────────────────────────────────────────
    def word_at(self, uri, pos):
        lines = self.docs.get(uri, "").splitlines()
        if pos["line"] >= len(lines):
            return "", ""
        line, ch = lines[pos["line"]], pos["character"]
        for m in re.finditer(r"[A-Za-z_][\w.]*", line):
            if m.start() <= ch <= m.end():
                return m.group(0).rstrip("."), line
        return "", line

    def on_textDocument_hover(self, p):
        uri = p["textDocument"]["uri"]
        word, _line = self.word_at(uri, p["position"])
        if not word:
            return None
        prog = self.progs.get(uri) or self.compile(uri)[0]
        md = None
        if prog is not None and word in prog.agents:
            a = prog.agents[word]
            sig = f"agent {a.name}({', '.join(f'{x.name}: {x.type}' for x in a.params)}) -> {a.returns}"
            parts = [f"```algo\n{sig}\n```"]
            if a.role:
                parts.append(f"**role** {a.role}")
            if a.goal:
                parts.append(f"**goal** {a.goal}")
            if a.uses:
                parts.append("**tools** " + ", ".join(f"`{t}`" for t in a.uses))
            pol = {k: v for k, v in a.policy.items() if not k.startswith("_")}
            if pol:
                parts.append("**policy** " + ", ".join(f"{k}={v}" for k, v in pol.items()))
            if a.origin:
                parts.append(f"_from {a.origin}_")
            md = "\n\n".join(parts)
        elif prog is not None and word in prog.tools:
            src = prog.mcp_tools.get(word)
            md = f"**tool** `{word}`" + (f" — served by MCP server `{src}`" if src else "")
        elif prog is not None and word in prog.models:
            md = f"**model** `{word}` = `{prog.models[word]}`"
        elif word.split(".")[-1] == "confidence":
            md = KEYWORDS["confidence"]
        elif word in KEYWORDS:
            md = KEYWORDS[word]
        elif word in TYPE_DOCS:
            md = f"**{word}** — {TYPE_DOCS[word]}"
        return {"contents": {"kind": "markdown", "value": md}} if md else None

    def on_textDocument_completion(self, p):
        uri = p["textDocument"]["uri"]
        lines = self.docs.get(uri, "").splitlines()
        pos = p["position"]
        prefix = lines[pos["line"]][: pos["character"]] if pos["line"] < len(lines) else ""
        items = []
        if re.search(r"\buse\s+pack\s+[\w.]*$", prefix):
            try:
                cat = json.loads((algoc.HERE / "packs" / "catalog.json").read_text(encoding="utf-8"))
                items = [{"label": x["id"], "kind": 9, "detail": x["title"], "documentation": x.get("desc", "")}
                         for x in cat["packs"]]
            except Exception:  # noqa
                items = []
            return {"isIncomplete": False, "items": items}
        prog = self.progs.get(uri) or self.compile(uri)[0]
        if prog is not None:
            for n, a in prog.agents.items():
                items.append({"label": n, "kind": 3, "detail": f"-> {a.returns}" + (f"  ({a.origin})" if a.origin else ""),
                              "documentation": a.goal,
                              "insertText": f"{n}(" + ", ".join(x.name for x in a.params) + ")"})
            items += [{"label": t, "kind": 7, "detail": "tool"} for t in sorted(prog.tools)]
            items += [{"label": m, "kind": 21, "detail": f"model {v}"} for m, v in prog.models.items()]
        items += [{"label": k, "kind": 14, "documentation": {"kind": "markdown", "value": v}} for k, v in KEYWORDS.items()]
        items += [{"label": t, "kind": 22, "detail": d} for t, d in TYPE_DOCS.items()]
        items.append({"label": "uncertain<score>", "kind": 22, "detail": "sampled, with confidence"})
        items += [{"label": k, "kind": 15, "insertText": body, "insertTextFormat": 2, "detail": "snippet"}
                  for k, body in SNIPPETS]
        return {"isIncomplete": False, "items": items}

    def on_textDocument_definition(self, p):
        uri = p["textDocument"]["uri"]
        word, _ = self.word_at(uri, p["position"])
        prog = self.progs.get(uri) or self.compile(uri)[0]
        if prog is None or not word:
            return None
        line, target = None, None
        if word in prog.agents:
            a = prog.agents[word]
            target, line = a.src, a.line
        elif word in prog.flows:
            target, line = None, prog.flows[word].line
        elif word in prog.tool_lines:
            target, line = None, prog.tool_lines[word]
        if line is None:
            return None
        here = uri if not target or Path(target) == uri_to_path(uri).resolve() else path_to_uri(target)
        rng = {"start": {"line": max(0, line - 1), "character": 0}, "end": {"line": max(0, line - 1), "character": 0}}
        return {"uri": here, "range": rng}

    def on_textDocument_documentSymbol(self, p):
        uri = p["textDocument"]["uri"]
        prog = self.progs.get(uri) or self.compile(uri)[0]
        if prog is None:
            return []
        me = uri_to_path(uri).resolve()
        lines = self.docs.get(uri, "").splitlines() or [""]

        def sym(name, kind, line, detail=""):
            ln = max(0, min(line - 1, len(lines) - 1))
            r = {"start": {"line": ln, "character": 0}, "end": {"line": ln, "character": len(lines[ln])}}
            return {"name": name, "kind": kind, "detail": detail, "range": r, "selectionRange": r}

        out = [sym(n, 12, a.line, f"-> {a.returns}") for n, a in prog.agents.items()
               if not a.origin and (not a.src or Path(a.src) == me)]
        out += [sym(f"flow {n}", 12, f.line) for n, f in prog.flows.items()]
        out += [sym(f"eval {e.name}", 3, e.line, f"{len(e.cases)} case(s)") for e in prog.evals]
        out += [sym(t, 7, ln, "tool") for t, ln in prog.tool_lines.items()]
        return out


def main():
    return Server().serve()


if __name__ == "__main__":
    sys.exit(main())
