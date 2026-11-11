"""algoir — AlgoIR and the AlgoVM: AlgoLang's portable program format and native virtual machine (v1.0).

Until v0.7 a program ran by compiling to Python source and executing it. v1.0 adds a second, native path:

    algo build claims.algo --ir                    # → claims.algoir.json  (portable, hashable, signable)
    algo build claims.algo --ir --sign             # signed with the audit key (Ed25519, ML-DSA or hybrid)
    algo run claims.algoir.json --arg "claim=…"    # runs on the AlgoVM: no compiler, no generated code
    algo run claims.algo --engine vm               # compile in memory, run on the AlgoVM

AlgoIR is a small, versioned JSON document: models, tools, typed messages, trust settings, agents (with their
effective policies) and flows as statement trees. The AlgoVM interprets it directly on the same runtime that
enforces policies, budgets, human review and audit, so the governance is identical; what changes is that no
Python is generated or exec'd. That makes a program a reviewable, signable deployment artifact:
`"runtime": {"require_signed_ir": true}` in algo.config.json refuses any IR that is unsigned or altered.

The VM is deliberately small (a few hundred lines) so that other hosts can implement the same format.
"""
from __future__ import annotations

import hashlib
import json
import operator
from pathlib import Path

from lark import Tree

IR_VERSION = 1
OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "==": operator.eq, "!=": operator.ne}


class IRError(Exception):
    pass


# ═══════════════════════════════ compiler: Program → AlgoIR ═══════════════════════════════
def _lit(tok):
    t = str(tok)
    try:
        return int(t)
    except ValueError:
        return float(t)


class ToIR:
    def __init__(self, prog):
        self.p = prog

    def expr(self, e):
        import algoc
        d = e.data
        if d == "call":
            name, args = e.children
            ag = self.p.agents[str(name)]
            out, i = {}, 0
            for a in (args.children if args is not None else []):
                if isinstance(a, Tree) and a.data == "kwarg":
                    out[str(a.children[0])] = self.expr(a.children[1])
                else:
                    out[ag.params[i].name] = self.expr(a)
                    i += 1
            return {"call": str(name), "args": out}
        if d == "var":
            n = str(e.children[0])
            return {"lit": {"true": True, "false": False}[n]} if n in ("true", "false") else {"var": n}
        if d == "attr":
            var, *path = str(e.children[0]).split(".")
            return {"attr": var, "path": path}
        if d == "par_block":
            return {"par": [self.expr(c) for c in e.children]}
        if d == "par_for":
            var, src, call = e.children
            return {"par_for": str(var), "in": str(src), "do": self.expr(call)}
        if d == "string":
            return {"lit": algoc._s(e.children[0])}
        if d == "number":
            return {"lit": _lit(e.children[0])}
        if d in ("true", "false"):
            return {"lit": d == "true"}
        raise IRError(f"cannot compile expression '{d}'")

    def cond(self, c):
        import algoc
        if c.data in ("or_cond", "and_cond"):
            return {c.data[:-5]: [self.cond(c.children[0]), self.cond(c.children[1])]}
        if c.data in ("contains_cond", "not_contains_cond"):
            return {"contains": self.expr(c.children[0]), "text": algoc._s(c.children[1]),
                    "negate": c.data == "not_contains_cond"}
        left, op, right = c.children
        return {"cmp": str(op), "left": self.expr(left), "right": self.expr(right)}

    def block(self, stmts):
        out = []
        for s in stmts:
            if s.data == "assign":
                target, expr = s.children
                out.append({"assign": [str(n) for n in target.children], "expr": self.expr(expr)})
            elif s.data == "if_stmt":
                then_b, else_b = s._split
                out.append({"if": self.cond(s.children[0]), "then": self.block(then_b), "else": self.block(else_b or [])})
            elif s.data == "emit":
                out.append({"emit": [self.expr(e) for e in s.children]})
            elif s.data == "expr_stmt":
                out.append({"do": self.expr(s.children[0])})
            else:
                raise IRError(f"cannot compile statement '{s.data}'")
        return out


def to_ir(prog, program_name, source_text=""):
    """An AlgoIR document (dict) for a checked Program."""
    import algoruntime as rt
    circuits = {c.tool: c.qasm() for c in prog.circuits.values()}
    tools = []
    for t in sorted(prog.tools):
        if t in circuits:
            tools.append({"name": t, "kind": "circuit", "qasm": circuits[t]})
        elif t in prog.mcp_tools:
            tools.append({"name": t, "kind": "mcp", "server": prog.mcp_tools[t]})
        else:
            tools.append({"name": t, "kind": "builtin"})
    c = ToIR(prog)
    doc = {
        "algoir": IR_VERSION, "algolang": rt.VERSION, "program": program_name,
        "source_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest() if source_text else None,
        "models": dict(prog.models), "tools": tools, "types": dict(prog.records),
        "trust": {"untrusted": sorted(prog.untrusted), "risk": prog.risk[0] if prog.risk else None,
                  "disclosure": prog.disclosure},
        "agents": [{"name": a.name, "params": [[x.name, x.type, x.default] for x in a.params], "returns": a.returns,
                    "role": a.role, "goal": a.goal, "uses": list(a.uses), "model": a.model, "policy": a.policy}
                   for a in prog.agents.values()],
        "flows": [{"name": f.name, "params": [[x.name, x.type] for x in f.params], "body": c.block(f.body)}
                  for f in prog.flows.values()],
    }
    doc["sha256"] = digest(doc)
    return doc


def digest(doc):
    body = {k: v for k, v in doc.items() if k not in ("sha256", "signature")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def compile_file(path):
    import algoc
    p = Path(path)
    src = p.read_text(encoding="utf-8")
    _code, prog = algoc.compile_source(src, p.name, p.parent)
    return to_ir(prog, p.stem, src)


def sign(doc):
    """Sign an AlgoIR document with the organisation's audit key (Ed25519; ML-DSA too when configured)."""
    import algotrust
    s = algotrust.signer() or _force_signer()
    msg = doc["sha256"].encode()
    sig = {"kid": s[2], "ed25519": algotrust.ed25519_sign(s[0], msg).hex(), "public": s[1].hex()}
    try:
        pq = algotrust.pq_sign(msg)
    except Exception:  # noqa
        pq = None
    if pq:
        sig.update(palg=pq[0], pkid=pq[1], pqsig=pq[2])
    return dict(doc, signature=sig)


def _force_signer():
    import algotrust
    p, kid, pub = algotrust.init_key()
    seed = bytes.fromhex(json.loads(Path(p).read_text())["private"])
    return seed, bytes.fromhex(pub), kid


def verify(doc, require_signature=False):
    """None if the document is intact (and signed by a trusted key when required); otherwise the reason."""
    if doc.get("algoir") != IR_VERSION:
        return f"unsupported AlgoIR version {doc.get('algoir')!r} (this VM runs version {IR_VERSION})"
    if doc.get("sha256") != digest(doc):
        return "the program was changed after it was built (sha256 does not match)"
    sig = doc.get("signature")
    if sig is None:
        return "the program is not signed (build it with --sign)" if require_signature else None
    import algotrust
    keys, pinned = algotrust.trusted_keys()
    pub = keys.get(sig.get("kid"))
    if pub is None:
        return f"signed by an unknown key ({sig.get('kid')})"
    if not algotrust.ed25519_verify(pub, doc["sha256"].encode(), bytes.fromhex(sig["ed25519"])):
        return "the signature does not match the program"
    if "pqsig" in sig:
        pq = algotrust.trusted_pq_keys().get(sig.get("pkid"))
        if pq is None or not algotrust.pq_verify(pq[0], pq[1], doc["sha256"].encode(), bytes.fromhex(sig["pqsig"])):
            return "the post-quantum signature does not match the program"
    return None


# ═══════════════════════════════ the AlgoVM ═══════════════════════════════
class Machine:
    """Runs an AlgoIR document on the AlgoLang runtime."""

    def __init__(self, doc, **runtime_kwargs):
        import algoruntime as rt
        cfg = rt.load_config()
        need = bool((cfg.get("runtime") or {}).get("require_signed_ir"))
        why = verify(doc, require_signature=need)
        if why:
            raise IRError(f"refusing to run {doc.get('program', 'program')}: {why}")
        self.doc, self.rt_mod = doc, rt
        self.rt = r = rt.Runtime(program=doc["program"], **runtime_kwargs)
        for n, m in doc["models"].items():
            r.model(n, m)
        for t in doc["tools"]:
            if t["kind"] == "circuit":
                r.circuit_tool(t["name"], t["qasm"])
            elif t["kind"] == "mcp":
                r.mcp_tool(t["name"], t["server"])
            else:
                r.tool(t["name"])
        if doc.get("types"):
            r.types(doc["types"])
        tr = doc.get("trust") or {}
        if tr.get("untrusted") or tr.get("risk") or tr.get("disclosure"):
            r.trust(untrusted=tr.get("untrusted") or [], risk=tr.get("risk"), disclosure=tr.get("disclosure"))
        self.agents = {}
        for a in doc["agents"]:
            spec = rt.AgentSpec(name=a["name"], params=[tuple(p) for p in a["params"]], returns=a["returns"],
                                role=a["role"], goal=a["goal"], uses=a["uses"], model=a["model"], policy=a["policy"])
            self.agents[a["name"]] = r.agent(spec)
        self.flows = {f["name"]: f for f in doc["flows"]}

    # expressions ---------------------------------------------------------------
    def ev(self, e, env):
        r = self.rt
        if "lit" in e:
            return e["lit"]
        if "var" in e:
            if e["var"] not in env:
                raise IRError(f"undefined variable '{e['var']}'")
            return env[e["var"]]
        if "call" in e:
            fn = self.agents[e["call"]]
            return fn(**{k: self.ev(v, env) for k, v in e["args"].items()})
        if "attr" in e:
            x = env[e["attr"]]
            return r.conf(x) if e["path"] == ["confidence"] else r.field(x, e["path"])
        if "par" in e:
            return r.par(*[(lambda c=c: self.ev(c, env)) for c in e["par"]])
        if "par_for" in e:
            var, body = e["par_for"], e["do"]
            return r.par_map(lambda it: self.ev(body, dict(env, **{var: it})), env[e["in"]])
        raise IRError(f"unknown expression {list(e)[:1]}")

    def test(self, c, env):
        r = self.rt
        if "or" in c:
            return self.test(c["or"][0], env) or self.test(c["or"][1], env)
        if "and" in c:
            return self.test(c["and"][0], env) and self.test(c["and"][1], env)
        if "contains" in c:
            hit = r.contains(self.ev(c["contains"], env), c["text"])
            return not hit if c.get("negate") else hit
        return OPS[c["cmp"]](r.value(self.ev(c["left"], env)), r.value(self.ev(c["right"], env)))

    def exec(self, stmts, env):
        for s in stmts:
            if "assign" in s:
                v = self.ev(s["expr"], env)
                names = s["assign"]
                if len(names) == 1:
                    env[names[0]] = v
                else:
                    if not isinstance(v, (list, tuple)) or len(v) != len(names):
                        raise IRError(f"cannot unpack into {names}")
                    env.update(zip(names, v))
            elif "if" in s:
                self.exec(s["then"] if self.test(s["if"], env) else s["else"], env)
            elif "emit" in s:
                self.rt.emit(*[self.ev(e, env) for e in s["emit"]])
            elif "do" in s:
                self.ev(s["do"], env)

    def run_flow(self, name="main", inputs=None):
        f = self.flows.get(name)
        if f is None:
            raise KeyError(f"no flow named '{name}' (flows: {', '.join(self.flows)})")
        inputs = inputs or {}
        missing = [p for p, _t in f["params"] if p not in inputs]
        if missing:
            raise TypeError(f"missing input(s): {', '.join(missing)}")
        vals = self.rt.typed_inputs(name, [(p, t, inputs[p]) for p, t in f["params"]])
        env = {p: v for (p, _t), v in zip(f["params"], vals)}
        self.rt.begin_flow(name, dict(env))
        self.exec(f["body"], env)
        return self.rt.end_flow()


class IRProgram:
    """SDK view of an AlgoIR document: the same run() as algolang.Program, executed by the AlgoVM."""

    def __init__(self, doc, path=None):
        self.doc, self.path = doc, path
        self.name = doc["program"]

    def flow_inputs(self, flow="main"):
        return [p for p, _t in next(f for f in self.doc["flows"] if f["name"] == flow)["params"]]

    def run(self, live=False, quiet=True, audit_dir=None, backend=None, flow="main", on_token=None, **inputs):
        import algolang as al
        import algoruntime as rt
        res = al.RunResult(run_id="", inputs=dict(inputs), audit_path="")
        try:
            m = Machine(self.doc, quiet=quiet, live=live, backend=backend, audit_dir_override=audit_dir,
                        source=self.path, on_token=on_token)
        except IRError as e:
            res.ok, res.status, res.problem = False, "blocked", str(e)
            return res
        res.run_id, res.audit_path = m.rt.run_id, str(m.rt.audit_path)
        try:
            res.values = m.run_flow(flow, inputs) or []
        except rt.PolicyViolation as e:
            res.ok, res.status, res.problem = False, "blocked", str(e)
            m.rt.write_trace(status="blocked", problem=str(e))
        except Exception as e:  # noqa
            res.ok, res.status, res.problem = False, "failed", f"{type(e).__name__}: {e}"
            m.rt.write_trace(status="failed", problem=res.problem)
        res.calls, res.stats = list(m.rt.calls), dict(m.rt.stats)
        return res


def load(path):
    p = Path(path)
    return IRProgram(json.loads(p.read_text(encoding="utf-8")), str(p))


def cli_run(path, args, flow="main"):
    """`algo run app.algoir.json`: run on the AlgoVM with the same CLI behaviour as a compiled program."""
    import sys

    import algoruntime as rt
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    try:
        m = Machine(doc, source=str(path))
    except IRError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2
    f = m.flows.get(flow)
    if f is None:
        print(f"✗ no flow named {flow}; flows: {', '.join(m.flows)}", file=sys.stderr)
        return 1
    inputs = dict(kv.split("=", 1) for kv in args)
    missing = [p for p, _t in f["params"] if p not in inputs]
    if missing:
        print(f'✗ missing input: add --arg "{missing[0]}=..."', file=sys.stderr)
        return 1
    try:
        m.run_flow(flow, inputs)
    except rt.InputTypeError as e:
        print(f"✗ invalid input: {e}", file=sys.stderr)
        return 1
    except rt.PolicyViolation as e:
        m.rt.write_trace(status="blocked", problem=str(e))
        print(f"✗ POLICY VIOLATION: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa
        m.rt.write_trace(status="failed", problem=f"{type(e).__name__}: {e}")
        print(f"✗ agent call failed: {type(e).__name__}: {str(e)[:300]}", file=sys.stderr)
        return 3
    return 0
