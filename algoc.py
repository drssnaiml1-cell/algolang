#!/usr/bin/env python3
"""
algoc — the AlgoLang compiler  (v0.2 "Enterprise")
AlgoProfessor AI R&D Solutions

    algoc check  program.algo
    algoc build  program.algo [-o out.py]
    algoc run    program.algo [--arg name=value ...] [--live]

Pipeline:  source → parse (Lark) → AST → semantic checks → Python codegen
The generated Python imports `algoruntime`, which executes agents.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from lark import Lark, Token, Tree
from lark.exceptions import UnexpectedInput

HERE = Path(__file__).resolve().parent
GRAMMAR = (HERE / "grammar.lark").read_text()
PARSER = Lark(GRAMMAR, start="start", parser="earley", propagate_positions=True)

TYPES = {"text", "score", "list", "json", "bool"}
PACK_DIRS = [HERE / "packs"] + [Path(p) for p in os.environ.get("ALGO_PACKS", "").split(os.pathsep) if p]
BUILTIN_TOOLS = {"web.search", "file.read", "calc.eval"}
DEFAULT_MODEL = "claude-sonnet-5-5"


# ───────────────────────────── AST ─────────────────────────────
@dataclass
class Param:
    name: str
    type: str
    default: object = None
    line: int = 0


@dataclass
class Agent:
    name: str
    params: list[Param]
    returns: str
    role: str = ""
    goal: str = ""
    uses: list[str] = field(default_factory=list)
    model: str | None = None
    policy: dict = field(default_factory=dict)
    line: int = 0
    origin: str | None = None        # set for agents imported with `use`
    src: str | None = None           # absolute path of the file that defines it (for the language server)


@dataclass
class Flow:
    name: str
    params: list[Param]
    body: list
    line: int = 0


@dataclass
class Program:
    models: dict = field(default_factory=dict)
    tools: set = field(default_factory=set)
    agents: dict = field(default_factory=dict)
    flows: dict = field(default_factory=dict)
    uses: list = field(default_factory=list)      # (kind, target, alias, line)
    imports: list = field(default_factory=list)   # resolved files, for reports
    mcp_tools: dict = field(default_factory=dict) # tool name → MCP server name (`tool x from mcp "server"`)
    evals: list = field(default_factory=list)     # eval blocks: Eval objects
    tool_lines: dict = field(default_factory=dict)
    streams: list = field(default_factory=list)   # stream blocks: Stream objects (v0.3.1)


@dataclass
class EvalCase:
    name: str
    inputs: dict
    expects: list                    # (kind, op, value)
    line: int = 0


@dataclass
class Stream:
    """`stream name on flow { … }`: run a flow once for every event on a Kafka topic."""
    name: str
    flow: str
    cluster: str | None = None
    source: str | None = None
    group: str | None = None
    sink: str | None = None
    escalate: str | None = None
    dead_letter: str | None = None
    mapping: dict = field(default_factory=dict)   # flow input → event path ("event.order")
    key: str | None = None
    max_in_flight: int = 8
    line: int = 0


@dataclass
class Eval:
    name: str
    flow: str
    cases: list
    line: int = 0


@dataclass
class Diag:
    code: str
    line: int
    msg: str
    file: str | None = None          # set when the error is inside an imported file

    def __str__(self):
        where = f"{self.file} line {self.line}" if self.file else f"line {self.line}"
        return f"{where}: {self.code} {self.msg}"


class CompileError(Exception):
    def __init__(self, diags):
        self.diags = diags
        super().__init__("\n".join(map(str, diags)))


def _s(tok: Token) -> str:  # unquote STRING
    return bytes(str(tok)[1:-1], "utf-8").decode("unicode_escape")


def _line(node) -> int:
    if isinstance(node, Token):
        return node.line or 0
    return getattr(node.meta, "line", 0) if hasattr(node, "meta") else 0


# ───────────────────────── parse → AST ─────────────────────────
def literal_value(t):
    if t.data == "string":
        return _s(t.children[0])
    if t.data == "number":
        v = str(t.children[0])
        return float(v) if "." in v else int(v)
    if t.data == "true":
        return True
    if t.data == "false":
        return False
    raise ValueError(t)


def type_str(node) -> str:
    """`text` → "text";  `uncertain<score>` → "uncertain<score>"."""
    if isinstance(node, Tree) and node.data == "uncertain_type":
        return f"uncertain<{node.children[0]}>"
    return str(node)


def base_type(t: str) -> str:
    return t[10:-1] if t.startswith("uncertain<") else t


def build_params(node) -> list[Param]:
    if node is None:
        return []
    out = []
    for p in node.children:
        name, typ, *rest = p.children
        default = literal_value(rest[0]) if rest and rest[0] is not None else None
        out.append(Param(str(name), type_str(typ), default, name.line))
    return out


def parse_policy(rules) -> dict:
    pol = {}
    for r in rules:
        if r.data == "budget":
            pol["budget_tokens"] = int(str(r.children[0]))
        elif r.data == "retry":
            pol["retry"] = int(str(r.children[0]))
        elif r.data == "timeout":
            pol["timeout_s"] = float(str(r.children[0]))
        elif r.data == "human_gate":
            pol["human_below"] = float(str(r.children[0]))
        elif r.data == "forbid":
            pol.setdefault("forbid", []).extend(str(t) for t in r.children)
        elif r.data == "cache":
            pol["cache"] = True
        elif r.data == "samples":
            pol["samples"] = int(str(r.children[0]))
        elif r.data == "shots":
            pol["shots"] = int(float(str(r.children[0])))
        elif r.data == "max_qubits":
            pol["max_qubits"] = int(float(str(r.children[0])))
        elif r.data == "budget_cost":
            amount, cur = float(str(r.children[0])), str(r.children[1] or "usd").lower()
            if cur in ("usd", "inr"):
                pol[f"budget_cost_{cur}"] = amount
            else:
                pol.setdefault("_errors", []).append(f"unknown currency '{cur}' in `budget cost` (use usd or inr)")
        elif r.data == "budget_energy":
            amount, unit = float(str(r.children[0])), str(r.children[1]).lower()
            if unit in ("wh", "kwh"):
                pol["budget_energy_wh"] = amount * (1000 if unit == "kwh" else 1)
            else:
                pol.setdefault("_errors", []).append(f"unknown energy unit '{unit}' in `budget energy` (use wh or kwh)")
    return pol


def merge_policy(base: dict, own: dict) -> dict:
    """Combine two policies; the stricter rule always wins."""
    out = dict(base)
    for k, v in own.items():
        if k not in out:
            out[k] = v
        elif k in ("budget_tokens", "timeout_s", "budget_cost_usd", "budget_cost_inr", "budget_energy_wh",
                   "max_qubits"):
            out[k] = min(out[k], v)
        elif k == "_errors":
            out[k] = out[k] + [e for e in v if e not in out[k]]
        elif k == "human_below":
            out[k] = max(out[k], v)
        elif k == "forbid":
            out[k] = sorted(set(out[k]) | set(v), key=(out[k] + list(v)).index)
        elif k == "cache":
            out[k] = out[k] or v
        else:                      # retry: the agent's own value
            out[k] = v
    return out


def to_ast(tree: Tree) -> tuple[Program, list[Diag]]:
    prog, diags = Program(), []
    default_policy = {}
    for item in tree.children:
        if item.data in ("use_file", "use_pack"):
            target, alias = item.children
            target = _s(target) if item.data == "use_file" else str(target)
            prog.uses.append((item.data, target, str(alias) if alias else None, _line(item)))
        elif item.data == "policy_decl":
            default_policy = merge_policy(default_policy, parse_policy(item.children))
        elif item.data == "model_decl":
            name, s = item.children
            prog.models[str(name)] = _s(s)
        elif item.data == "tool_decl":
            tname, server = item.children
            prog.tools.add(str(tname))
            prog.tool_lines[str(tname)] = _line(item)
            if server is not None:
                prog.mcp_tools[str(tname)] = _s(server)
        elif item.data == "eval_decl":
            ename, flow, *cases = item.children
            ev = Eval(str(ename), str(flow) if flow is not None else "main", [], _line(item))
            for c in cases:
                cname, args, *exps = c.children
                inputs = {}
                for a in (args.children if args is not None else []):
                    if isinstance(a, Tree) and a.data == "kwarg" and a.children[1].data in ("string", "number", "true", "false"):
                        inputs[str(a.children[0])] = literal_value(a.children[1])
                    else:
                        diags.append(Diag("E119", _line(c), f"eval {ev.name}: case inputs must be written "
                                                             f"name = \"value\""))
                expects = []
                for e in exps:
                    kind = e.data[4:]
                    if kind in ("tokens", "cost", "energy", "escalated", "confidence"):
                        op, num = e.children
                        expects.append((kind, str(op), float(str(num))))
                    elif kind == "contains":
                        expects.append((kind, None, _s(e.children[0])))
                    elif kind == "emits":
                        expects.append((kind, "==", int(str(e.children[0]))))
                    else:
                        expects.append((kind, None, str(e.children[0])))
                ev.cases.append(EvalCase(_s(cname), inputs, expects, _line(c)))
            prog.evals.append(ev)
        elif item.data == "stream_decl":
            sname, flow, *clauses = item.children
            st = Stream(str(sname), str(flow) if flow is not None else "main", line=_line(item))
            for c in clauses:
                k = c.data
                if k == "st_source":
                    st.cluster, st.source = _s(c.children[0]), _s(c.children[1])
                    st.group = _s(c.children[2]) if c.children[2] is not None else None
                elif k == "st_sink":
                    st.sink = _s(c.children[0])
                elif k == "st_escalate":
                    st.escalate = _s(c.children[0])
                elif k == "st_dlq":
                    st.dead_letter = _s(c.children[0])
                elif k == "st_maps":
                    for m in c.children:
                        st.mapping[str(m.children[0])] = str(m.children[1])
                elif k == "st_key":
                    st.key = str(c.children[0])
                elif k == "st_inflight":
                    st.max_in_flight = int(float(str(c.children[0])))
            prog.streams.append(st)
        elif item.data == "agent_decl":
            name, params, ret, *clauses = item.children
            a = Agent(str(name), build_params(params), type_str(ret), line=name.line)
            for c in clauses:
                if c.data == "role":
                    a.role = _s(c.children[0])
                elif c.data == "goal":
                    a.goal = _s(c.children[0])
                elif c.data == "uses":
                    a.uses += [str(t) for t in c.children]
                elif c.data == "model_ref":
                    a.model = str(c.children[0])
                elif c.data == "policy":
                    a.policy = merge_policy(a.policy, parse_policy(c.children))
            if a.name in prog.agents or a.name in prog.flows:
                diags.append(Diag("E107", a.line, f"'{a.name}' is defined twice"))
            prog.agents[a.name] = a
        elif item.data == "flow_decl":
            name, params, *body = item.children
            f = Flow(str(name), build_params(params), body, line=name.line)
            if f.name in prog.agents or f.name in prog.flows:
                diags.append(Diag("E107", f.line, f"'{f.name}' is defined twice"))
            prog.flows[f.name] = f
    if default_policy:                       # file-level policy applies to every agent in the file
        for a in prog.agents.values():
            a.policy = merge_policy(default_policy, a.policy)
    return prog, diags


# ───────────────────────── semantic checks ─────────────────────
class Checker:
    """Type/effect/policy checks. Fills `diags`; returns typed var tables."""

    def __init__(self, prog: Program):
        self.p = prog
        self.diags: list[Diag] = []

    def err(self, code, line, msg):
        self.diags.append(Diag(code, line, msg))

    def run(self, library=False):
        for a in self.p.agents.values():
            if a.origin is None:             # imported agents were checked in their own file
                self.check_agent(a)
        self.check_org()
        self.check_mcp()
        if "main" not in self.p.flows and not library:
            self.err("E111", 1, "program has no `flow main(...)` entry point")
        for f in self.p.flows.values():
            env = {}
            self.inputs = {prm.name for prm in f.params}
            for prm in f.params:
                self.check_type(prm.type, prm.line)
                env[prm.name] = prm.type
            self.check_block(f.body, env)
        for ev in self.p.evals:
            self.check_eval(ev)
        seen = set()
        for st in self.p.streams:
            if st.name in seen:
                self.err("E122", st.line, f"stream {st.name} is defined twice")
            seen.add(st.name)
            self.check_stream(st)
        return self.diags

    def check_stream(self, st):
        """Stream blocks: a real flow, a source topic, inputs that exist, and no topic loops."""
        f = self.p.flows.get(st.flow)
        if f is None:
            self.err("E122", st.line, f"stream {st.name} runs flow '{st.flow}', which does not exist")
            return
        if not st.source:
            self.err("E122", st.line, f"stream {st.name} needs a source: from kafka \"cluster\" topic \"name\"")
        names = {p.name for p in f.params}
        for inp, path in st.mapping.items():
            if inp not in names:
                self.err("E122", st.line, f"stream {st.name} maps '{inp}', which is not an input of flow "
                                          f"{st.flow} (inputs: {', '.join(sorted(names)) or 'none'})")
            if path != "event" and not path.startswith("event."):
                self.err("E122", st.line, f"stream {st.name}: map {inp} = {path} must read from the event, "
                                          f"for example {inp} = event.{inp}")
        if st.key and st.key != "event" and not st.key.startswith("event."):
            self.err("E122", st.line, f"stream {st.name}: key must read from the event, for example key event.id")
        outs = {"to topic": st.sink, "escalate to topic": st.escalate, "dead letter topic": st.dead_letter}
        for label, topic in outs.items():
            if topic and topic == st.source:
                self.err("E122", st.line, f"stream {st.name}: '{label} \"{topic}\"' is the source topic, so every "
                                          f"result would be read again as a new event (an endless loop)")
        if not 1 <= st.max_in_flight <= 256:
            self.err("E122", st.line, f"stream {st.name}: max in flight must be between 1 and 256")

    def check_mcp(self):
        """`tool x from mcp "server"` needs that server in algo.config.json (mcp_servers)."""
        if not self.p.mcp_tools:
            return
        try:
            import algoruntime
            if algoruntime.config_path() is None:      # no algo.config.json here: checked when the program runs
                return
            cfg = algoruntime.load_config()
        except Exception:  # noqa
            return
        servers = cfg.get("mcp_servers") or {}
        for t, srv in self.p.mcp_tools.items():
            if srv not in servers:
                known = ", ".join(sorted(servers)) or "none configured"
                self.err("E120", self.p.tool_lines.get(t, 1), f"tool {t} comes from MCP server '{srv}', which is not in "
                                                               f"mcp_servers in algo.config.json (known: {known})")

    def check_eval(self, ev):
        """Eval blocks must name a real flow, its inputs, real agents and real tools."""
        f = self.p.flows.get(ev.flow)
        if f is None:
            self.err("E119", ev.line, f"eval {ev.name} runs flow '{ev.flow}', which does not exist")
            return
        params = [p.name for p in f.params]
        for c in ev.cases:
            for k in c.inputs:
                if k not in params:
                    self.err("E119", c.line, f"eval {ev.name}, case \"{c.name}\": flow {ev.flow} has no input '{k}'")
            for k in params:
                if k not in c.inputs:
                    self.err("E119", c.line, f"eval {ev.name}, case \"{c.name}\": missing input '{k}'")
            for kind, _op, val in c.expects:
                if kind in ("called", "not_called") and val not in self.p.agents:
                    self.err("E119", c.line, f"eval {ev.name}, case \"{c.name}\": '{val}' is not an agent in this program")
                elif kind == "tool" and val not in self.p.tools:
                    self.err("E119", c.line, f"eval {ev.name}, case \"{c.name}\": tool '{val}' is not declared")
                elif kind == "status" and val not in ("ok", "blocked", "failed"):
                    self.err("E119", c.line, f"eval {ev.name}, case \"{c.name}\": status must be ok, blocked or failed")

    def check_org(self):
        """Organisation policy (algo.config.json) is enforced before anything runs."""
        try:
            import algoruntime
            org = algoruntime.load_config().get("policy") or {}
        except Exception:  # noqa — a broken config is reported by the runtime
            return
        forbid, allowed = set(org.get("forbid") or []), org.get("allowed_tools")
        for a in self.p.agents.values():
            where = f" (imported from {a.origin})" if a.origin else ""
            for prm in a.params:
                if prm.name in forbid and prm.name not in a.policy.get("forbid", []):
                    self.err("E108", a.line, f"agent {a.name}{where} takes '{prm.name}' as an input, "
                                             f"which the organisation policy forbids")
            if allowed is not None:
                for t in a.uses:
                    if t not in allowed:
                        self.err("E115", a.line, f"agent {a.name}{where} uses tool '{t}', which the organisation "
                                                 f"policy does not allow (allowed_tools in algo.config.json)")

    def check_type(self, t, line):
        if base_type(t) not in TYPES:
            self.err("E105", line, f"unknown type '{t}' (use: {', '.join(sorted(TYPES))}, or uncertain<T>)")

    def check_agent(self, a: Agent):
        self.check_type(a.returns, a.line)
        names = set()
        for prm in a.params:
            self.check_type(prm.type, prm.line)
            names.add(prm.name)
        for ref in re.findall(r"\{(\w+)\}", a.goal):
            if ref not in names:
                self.err("E109", a.line, f"agent {a.name}: goal mentions {{{ref}}} but there is no parameter '{ref}'")
        if not a.goal:
            self.err("E112", a.line, f"agent {a.name} has no `goal` — every agent must state its work")
        for t in a.uses:  # capabilities must be declared explicitly — no ambient tools
            if t not in self.p.tools:
                self.err("E104", a.line, f"agent {a.name} uses tool '{t}', which is not declared (add `tool {t}`)")
        if a.model and a.model not in self.p.models:
            self.err("E106", a.line, f"agent {a.name}: unknown model '{a.model}'")
        for attr in a.policy.get("forbid", []):
            if attr in names:
                self.err("E108", a.line, f"agent {a.name} takes forbidden attribute '{attr}' as an input")
        for msg in a.policy.get("_errors", []):
            self.err("E121", a.line, f"agent {a.name}: {msg}")
        if a.policy.get("samples") is not None and not 1 <= a.policy["samples"] <= 15:
            self.err("E121", a.line, f"agent {a.name}: samples must be between 1 and 15")
        self.check_quantum(a)

    def check_quantum(self, a):
        """quantum.* tools (v0.3.2): sane shot counts and qubit limits."""
        try:
            from algoquantum import SIM_LIMIT
        except ImportError:                       # e.g. a minimal embedding without the quantum module
            SIM_LIMIT = 24
        shots, maxq = a.policy.get("shots"), a.policy.get("max_qubits")
        if shots is not None and not 1 <= shots <= 100_000:
            self.err("E123", a.line, f"agent {a.name}: shots must be between 1 and 100000")
        if maxq is not None and not 1 <= maxq <= SIM_LIMIT:
            self.err("E123", a.line, f"agent {a.name}: max qubits must be between 1 and {SIM_LIMIT}")

    # statements ---------------------------------------------------
    def check_block(self, stmts, env):
        for s in stmts:
            self.check_stmt(s, env)

    def check_stmt(self, s, env):
        line = _line(s)
        if s.data == "assign":
            target, expr = s.children
            t = self.expr_type(expr, env)
            names = [str(n) for n in target.children]
            if target.data == "multi_target":
                if expr.data != "par_block":
                    self.err("E113", line, "[a, b] = ... needs a `par { ... }` block on the right")
                    for n in names:
                        env[n] = "text"
                    return
                calls = expr.children
                if len(calls) != len(names):
                    self.err("E113", line, f"{len(names)} names but par block has {len(calls)} agents")
                for n, c in zip(names, calls):
                    env[n] = self.call_type(c, env)
            else:
                env[names[0]] = t
        elif s.data == "if_stmt":
            cond, *rest = s.children
            self.check_condition(cond, env)
            # body / else are lists of stmts mixed; lark gives flat children with None for missing else
            for child in rest:
                if child is None:
                    continue
                if isinstance(child, Tree):
                    self.check_stmt(child, env)
        elif s.data == "emit":
            for e in s.children:
                self.expr_type(e, env)
        elif s.data == "expr_stmt":
            self.expr_type(s.children[0], env)

    def check_condition(self, cond, env):
        """Check an if-condition. An uncertain<T> value may only be compared together with a check of its
        confidence somewhere in the same condition (E117): `if risk > 0.8 and risk.confidence >= 0.7`."""
        guarded = {str(a.children[0]).split(".")[0] for a in cond.iter_subtrees() if a.data == "attr"}
        for c in cond.iter_subtrees():
            if c.data == "cond":
                self.check_cond(c, env, guarded)
            elif c.data in ("contains_cond", "not_contains_cond"):
                self.expr_type(c.children[0], env)          # E103 if undefined; any type can be searched

    def check_cond(self, cond, env, guarded=()):
        left, op, right = cond.children
        for side in (left, right):
            if isinstance(side, Tree) and side.data == "attr":
                var, _, attr = str(side.children[0]).partition(".")
                if attr != "confidence":
                    self.err("E118", _line(cond), f"'{side.children[0]}': only `<result>.confidence` can be read "
                                                  f"in a condition")
                elif var not in env:
                    self.err("E103", _line(cond), f"undefined variable '{var}'")
                elif var in getattr(self, "inputs", set()):
                    self.err("E118", _line(cond), f"'{var}' is a flow input, not an agent result — it has no confidence")
                continue
            t = self.expr_type(side, env)
            if base_type(t) not in ("score", "number", "bool", "any"):
                name = side.children[0] if side.data == "var" else "expression"
                self.err("E110", _line(cond), f"'{name}' is {t}, not a score — only scores/numbers can be compared")
            elif t.startswith("uncertain<"):
                name = str(side.children[0]) if side.data == "var" else None
                if name is None or name not in guarded:
                    shown = name or "this uncertain value"
                    self.err("E117", _line(cond), f"'{shown}' is {t}: compare it together with its confidence, "
                                                  f"e.g. `if {shown} > 0.8 and {shown}.confidence >= 0.7` "
                                                  f"(assign the agent call to a variable first)")

    def expr_type(self, e, env):
        if isinstance(e, Token):
            return "any"
        if e.data == "call":
            return self.call_type(e, env)
        if e.data == "var":
            n = str(e.children[0])
            if n in ("true", "false"):      # boolean literals can parse as names
                return "bool"
            if n not in env:
                self.err("E103", _line(e.children[0]), f"undefined variable '{n}'")
                return "any"
            return env[n]
        if e.data == "par_block":
            for c in e.children:
                self.call_type(c, env)
            return "list"
        if e.data == "par_for":
            var, src, call = e.children
            if str(src) not in env:
                self.err("E103", src.line, f"undefined variable '{src}'")
            elif env[str(src)] not in ("list", "any"):
                self.err("E114", src.line, f"`par for` needs a list, but '{src}' is {env[str(src)]}")
            inner = dict(env)
            inner[str(var)] = "text"
            self.call_type(call, inner)
            return "list"
        if e.data in ("string",):
            return "text"
        if e.data == "number":
            return "number"
        if e.data in ("true", "false"):
            return "bool"
        if e.data == "kwarg":
            return self.expr_type(e.children[1], env)
        return "any"

    def call_type(self, c, env):
        name_tok, args = c.children
        name = str(name_tok)
        line = name_tok.line
        arg_nodes = args.children if args is not None else []
        if name not in self.p.agents:
            hint = "it is a flow; flows orchestrate and cannot be called" if name in self.p.flows else \
                   "declare it with `agent " + name + "(...) -> type { goal \"...\" }`"
            self.err("E101", line, f"'{name}' is not an agent — in AlgoLang every unit of work is an agent ({hint})")
            for a in arg_nodes:
                self.expr_type(a, env)
            return "any"
        ag = self.p.agents[name]
        pnames = [p.name for p in ag.params]
        pos = [a for a in arg_nodes if not (isinstance(a, Tree) and a.data == "kwarg")]
        kws = [a for a in arg_nodes if isinstance(a, Tree) and a.data == "kwarg"]
        if len(pos) > len(pnames):
            self.err("E102", line, f"{name} takes {len(pnames)} argument(s) ({', '.join(pnames)}), got {len(pos)} positional")
        bound = set(pnames[: len(pos)])
        for k in kws:
            kn = str(k.children[0])
            if kn not in pnames:
                self.err("E102", line, f"{name} has no parameter '{kn}'")
            elif kn in bound:
                self.err("E102", line, f"{name}: parameter '{kn}' given twice")
            bound.add(kn)
        for p in ag.params:
            if p.name not in bound and p.default is None:
                self.err("E102", line, f"{name}: missing required argument '{p.name}'")
        for a in arg_nodes:
            self.expr_type(a, env)
        return ag.returns


# ───────────────────────── code generation ─────────────────────
def pyname(name: str) -> str:
    """Agent names may be dotted after `use … as x`; make them valid Python names."""
    return name.replace(".", "__")

class CodeGen:
    def __init__(self, prog: Program, src_name: str):
        self.p, self.src, self.out = prog, src_name, []

    def w(self, line="", ind=0):
        self.out.append("    " * ind + line)

    def gen(self) -> str:
        p = self.p
        self.w(f"# Generated by algoc v{VERSION} from {self.src} — do not edit; edit the .algo source.")
        self.w("import os, sys")
        self.w(f"sys.path.insert(0, os.environ.get('ALGO_HOME') or {str(HERE)!r})")
        self.w("from algoruntime import Runtime, AgentSpec")
        self.w()
        self.w(f"rt = Runtime(program={Path(self.src).stem!r}, **globals().get('__algo_runtime__', {{}}))")
        for n, m in p.models.items():
            self.w(f"rt.model({n!r}, {m!r})")
        for t in sorted(p.tools):
            if t in p.mcp_tools:
                self.w(f"rt.mcp_tool({t!r}, {p.mcp_tools[t]!r})")
            else:
                self.w(f"rt.tool({t!r})")
        self.w()
        for a in p.agents.values():
            params = [(x.name, x.type, x.default) for x in a.params]
            self.w(f"{pyname(a.name)} = rt.agent(AgentSpec(")
            self.w(f"name={a.name!r}, params={params!r}, returns={a.returns!r},", 1)
            self.w(f"role={a.role!r},", 1)
            self.w(f"goal={a.goal!r},", 1)
            self.w(f"uses={a.uses!r}, model={a.model!r}, policy={a.policy!r}))", 1)
            self.w()
        for f in p.flows.values():
            args = ", ".join(x.name for x in f.params)
            self.w(f"def flow_{f.name}({args}):")
            self.w(f"rt.begin_flow({f.name!r}, {{{', '.join(f'{x.name!r}: {x.name}' for x in f.params)}}})", 1)
            self.block(f.body, 1)
            self.w("return rt.end_flow()", 1)
            self.w()
        main = p.flows.get("main")
        if main:
            self.w('if __name__ == "__main__":')
            self.w(f"rt.cli(flow_main, {[x.name for x in main.params]!r})", 1)
        return "\n".join(self.out) + "\n"

    def block(self, stmts, ind):
        if not stmts:
            self.w("pass", ind)
        for s in stmts:
            self.stmt(s, ind)

    def stmt(self, s, ind):
        if s.data == "assign":
            target, expr = s.children
            names = [str(n) for n in target.children]
            lhs = ", ".join(names) if len(names) > 1 else names[0]
            self.w(f"{lhs} = {self.expr(expr)}", ind)
        elif s.data == "if_stmt":
            cond, *rest = s.children
            # Lark flattens: body stmts then optional else stmts; split using meta lines is fragile,
            # so we re-walk: the grammar puts stmts of 'if' then stmts of 'else'. We recover the split
            # from the original tree via helper attached during parse.
            then_b, else_b = s._split
            self.w(f"if {self.cond(cond)}:", ind)
            self.block(then_b, ind + 1)
            if else_b:
                self.w("else:", ind)
                self.block(else_b, ind + 1)
        elif s.data == "emit":
            self.w(f"rt.emit({', '.join(self.expr(e) for e in s.children)})", ind)
        elif s.data == "expr_stmt":
            self.w(self.expr(s.children[0]), ind)

    def cond(self, c):
        if c.data == "or_cond":
            return f"({self.cond(c.children[0])}) or ({self.cond(c.children[1])})"
        if c.data == "and_cond":
            return f"({self.cond(c.children[0])}) and ({self.cond(c.children[1])})"
        if c.data in ("contains_cond", "not_contains_cond"):
            neg = "not " if c.data == "not_contains_cond" else ""
            return f"{neg}rt.contains({self.expr(c.children[0])}, {_s(c.children[1])!r})"
        l, op, r = c.children
        return f"{self.operand(l)} {op} {self.operand(r)}"

    def operand(self, e):
        if isinstance(e, Tree) and e.data == "attr":
            return f"rt.conf({str(e.children[0]).split('.')[0]})"
        return f"rt.value({self.expr(e)})"

    def expr(self, e):
        if e.data == "call":
            name, args = e.children
            ag = self.p.agents[str(name)]
            arg_nodes = args.children if args is not None else []
            parts, i = [], 0
            for a in arg_nodes:
                if isinstance(a, Tree) and a.data == "kwarg":
                    parts.append(f"{a.children[0]}={self.expr(a.children[1])}")
                else:
                    parts.append(f"{ag.params[i].name}={self.expr(a)}")
                    i += 1
            return f"{pyname(str(name))}({', '.join(parts)})"
        if e.data == "var":
            n = str(e.children[0])
            return {"true": "True", "false": "False"}.get(n, n)
        if e.data == "par_block":
            return "rt.par(" + ", ".join(f"lambda: {self.expr(c)}" for c in e.children) + ")"
        if e.data == "par_for":
            var, src, call = e.children
            return f"rt.par_map(lambda {var}: {self.expr(call)}, {src})"
        if e.data == "string":
            return repr(_s(e.children[0]))
        if e.data == "number":
            return str(e.children[0])
        if e.data == "true":
            return "True"
        if e.data == "false":
            return "False"
        raise ValueError(e.data)


def split_ifs(tree: Tree, src: str):
    """Attach (then, else) statement lists to each if_stmt.

    The grammar `"if" cond "{" stmt* "}" ["else" "{" stmt* "}"]` is flattened by Lark,
    so we locate the `else` keyword in the source text by position."""
    lines = src.splitlines(keepends=True)
    offsets = [0]
    for ln in lines:
        offsets.append(offsets[-1] + len(ln))

    for node in tree.iter_subtrees():
        if node.data != "if_stmt":
            continue
        cond, *rest = node.children
        stmts = [c for c in rest if isinstance(c, Tree)]
        # find "else" between end of cond and end of node
        seg = src[node.meta.start_pos: node.meta.end_pos]
        # brace matching to find end of then-block
        depth, i, then_end = 0, seg.index("{", cond.meta.end_pos - node.meta.start_pos), None
        while i < len(seg):
            if seg[i] == "{":
                depth += 1
            elif seg[i] == "}":
                depth -= 1
                if depth == 0:
                    then_end = node.meta.start_pos + i
                    break
            i += 1
        then_b = [s for s in stmts if s.meta.start_pos < then_end]
        else_b = [s for s in stmts if s.meta.start_pos > then_end]
        node._split = (then_b, else_b)


# ───────────────────────── flow graph (for diagrams) ───────────
def flow_graph(prog: Program, flow: str = "main"):
    """Return (nodes, edges) describing data flow between agents in a flow.

    nodes: list of (id, label, kind, sub) with kind in
           input | agent | par | cond | branch | emit
    edges: list of (from_id, to_id, dashed)"""
    f = prog.flows["main"]
    nodes, edges, src = [], [], {}
    count = [0]

    def new(label, kind, sub=""):
        count[0] += 1
        nid = f"n{count[0]}"
        nodes.append((nid, label, kind, sub))
        return nid

    def vars_in(tree):
        return [str(t.children[0]) for t in tree.iter_subtrees() if t.data == "var"]

    def link(names, nid, exclude=(), dashed=False):
        for v in names:
            if v in exclude:
                continue
            for s in src.get(v, []):
                if (s, nid, dashed) not in edges:
                    edges.append((s, nid, dashed))

    def cond_text(c):
        if c.data == "or_cond":
            return f"{cond_text(c.children[0])} or {cond_text(c.children[1])}"
        if c.data == "and_cond":
            return f"{cond_text(c.children[0])} and {cond_text(c.children[1])}"
        if c.data in ("contains_cond", "not_contains_cond"):
            neg = "not " if c.data == "not_contains_cond" else ""
            return f'{text(c.children[0])} {neg}contains "{_s(c.children[1])}"'
        l, op, r = c.children
        return f"{text(l)} {op} {text(r)}"

    def text(e):
        if e.data == "attr":
            return str(e.children[0])
        if e.data == "var":
            return str(e.children[0])
        if e.data == "number":
            return str(e.children[0])
        if e.data == "call":
            return f"{e.children[0]}(…)"
        return e.data

    for p in f.params:
        src[p.name] = [new(p.name, "input", "flow input")]

    def walk(stmts, kind, cond_id=None, merge=False):
        def bind(n, ids):
            src[n] = (src.get(n, []) + ids) if merge else ids

        for s in stmts:
            if s.data == "assign":
                target, expr = s.children
                names = [str(n) for n in target.children]
                if expr.data == "call":
                    nid = new(str(expr.children[0]), kind, f"→ {', '.join(names)}")
                    link(vars_in(expr), nid)
                    if cond_id:
                        edges.append((cond_id, nid, True))
                    for n in names:
                        bind(n, [nid])
                elif expr.data == "par_block":
                    ids = []
                    for i, c in enumerate(expr.children):
                        sub = f"→ {names[i]}" if target.data == "multi_target" and i < len(names) else "parallel"
                        nid = new(str(c.children[0]), "par" if kind == "agent" else kind, sub + " · par")
                        link(vars_in(c), nid)
                        if cond_id:
                            edges.append((cond_id, nid, True))
                        ids.append(nid)
                    if target.data == "multi_target":
                        for n, i in zip(names, ids):
                            bind(n, [i])
                    else:
                        bind(names[0], ids)
                elif expr.data == "par_for":
                    var, lst, call = expr.children
                    nid = new(f"{call.children[0]} × each", "par", f"par for {var} in {lst} → {names[0]}")
                    link([str(lst)] + vars_in(call), nid, exclude=(str(var),))
                    bind(names[0], [nid])
                elif expr.data == "var":
                    bind(names[0], list(src.get(str(expr.children[0]), [])))
            elif s.data == "if_stmt":
                cond = s.children[0]
                cid = new(f"if {cond_text(cond)}", "cond", "decision")
                for c in cond.iter_subtrees():
                    if c.data == "call":
                        nid = new(str(c.children[0]), kind, "in condition")
                        link(vars_in(c), nid)
                        edges.append((nid, cid, False))
                link([v for v in vars_in(cond)] + [str(a.children[0]).split(".")[0] for a in cond.iter_subtrees()
                                                    if a.data == "attr"], cid)
                then_b, else_b = s._split
                walk(then_b, "branch", cid, merge=True)
                walk(else_b, "branch", cid, merge=True)
            elif s.data == "emit":
                eid = new("emit", "emit", "flow output")
                for e in s.children:
                    if e.data == "call":                     # emit Agent(x): draw the agent too
                        nid = new(str(e.children[0]), kind, "→ emit")
                        link(vars_in(e), nid)
                        if cond_id:
                            edges.append((cond_id, nid, True))
                        edges.append((nid, eid, False))
                    else:
                        link(vars_in(e), eid)
            elif s.data == "expr_stmt":
                c = s.children[0]
                nid = new(str(c.children[0]), kind)
                link(vars_in(c), nid)

    walk(f.body, "agent")
    return nodes, edges


# ───────────────────────── driver ──────────────────────────────
def resolve_use(kind, target, base_dir: Path):
    """Find the file behind `use "x.algo"` or `use pack sector.name`."""
    if kind == "use_file":
        p = (base_dir / target)
        return p.resolve() if p.exists() else None
    rel = Path(*target.split(".")).with_suffix(".algo")
    for d in PACK_DIRS:
        if (d / rel).exists():
            return (d / rel).resolve()
    return None


def _parse(src, name, file_label):
    try:
        tree = PARSER.parse(src)
    except UnexpectedInput as e:
        ctx = e.get_context(src).rstrip()
        raise CompileError([Diag("E100", e.line, f"syntax error near column {e.column}\n{ctx}", file_label)])
    split_ifs(tree, src)
    return tree


def load_program(src, name, base_dir: Path, stack=(), file_label=None, library=False):
    """Parse a file and everything it `use`s. Returns (Program, diagnostics)."""
    tree = _parse(src, name, file_label)
    prog, diags = to_ast(tree)
    me = str((Path(base_dir) / name).resolve())
    for a in prog.agents.values():
        a.src = a.src or me
    for d in diags:
        d.file = file_label
    for kind, target, alias, line in prog.uses:
        path = resolve_use(kind, target, base_dir)
        shown = f'"{target}"' if kind == "use_file" else f"pack {target}"
        if path is None:
            hint = "check the path" if kind == "use_file" else "see `algo domains` for available packs"
            diags.append(Diag("E115", line, f"cannot find {shown} ({hint})", file_label))
            continue
        if str(path) in stack:
            diags.append(Diag("E116", line, f"circular use of {shown}", file_label))
            continue
        label = target if kind == "use_file" else f"pack {target}"
        try:
            sub, sub_diags = load_program(path.read_text(encoding="utf-8"), path.name, path.parent,
                                          stack + (str(path),), label, library=True)
        except CompileError as e:
            diags += e.diags
            continue
        diags += sub_diags
        prog.imports.append(str(path))
        prog.imports += [i for i in sub.imports if i not in prog.imports]
        for m, mid in sub.models.items():
            if m in prog.models and prog.models[m] != mid:
                diags.append(Diag("E107", line, f"model '{m}' is defined differently in {shown}", file_label))
            prog.models.setdefault(m, mid)
        prog.tools |= sub.tools
        for t, srv in sub.mcp_tools.items():
            prog.mcp_tools.setdefault(t, srv)
        for a in sub.agents.values():
            new_name = f"{alias}.{a.name}" if alias else a.name
            if new_name in prog.agents:
                diags.append(Diag("E107", line, f"agent '{new_name}' from {shown} is already defined — "
                                                f"import it with `as <name>` to keep both", file_label))
                continue
            a.name, a.origin = new_name, a.origin or label
            prog.agents[new_name] = a
    # local definitions come after imports, so re-check local names against imported ones
    checker = Checker(prog)
    for d in checker.run(library=library):
        d.file = d.file or file_label
        diags.append(d)
    return prog, diags


def compile_source(src: str, name: str, base_dir: Path | str | None = None):
    base = Path(base_dir) if base_dir else Path.cwd()
    me = (base / name).resolve()
    prog, diags = load_program(src, name, base, stack=(str(me),))
    if diags:
        raise CompileError(sorted(diags, key=lambda d: (d.file is not None, d.file or "", d.line)))
    return CodeGen(prog, name).gen(), prog


VERSION = "0.3.2"

TEMPLATE = '''// {name}.algo — created by `algo new`
// Run it:  algo run {name}.algo --arg "topic=Your topic here"

model smart = "claude-sonnet-5-5"
model fast  = "claude-haiku-5-5"

agent Explainer(topic: text) -> text {{
    role  "Friendly professor"
    goal  "Explain {{topic}} to a first-year student in 5 sentences"
    model fast
}}

agent QuizMaker(lesson: text) -> list {{
    role  "Exam setter"
    goal  "Write three short quiz questions on this lesson: {{lesson}}"
    model fast
}}

agent Checker(lesson: text) -> score {{
    role  "Senior reviewer"
    goal  "Score this lesson 0 to 1 for accuracy: {{lesson}}"
    model smart
    policy {{
        require human when confidence < 0.70
    }}
}}

flow main(topic: text) {{
    lesson = Explainer(topic)
    [quiz, quality] = par {{ QuizMaker(lesson), Checker(lesson) }}
    if quality < 0.75 {{
        lesson = Explainer(topic)
    }}
    emit lesson, quiz
}}
'''


def _utf8_console():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa
            pass


def doctor():
    ok = True
    def line(good, label, detail):
        nonlocal ok
        ok &= good if good is not None else True
        mark = "✓" if good else ("•" if good is None else "✗")
        print(f"  {mark} {label:<22} {detail}")
    print(f"AlgoLang {VERSION} environment check")
    v = sys.version_info
    line(v >= (3, 9), "Python", f"{v.major}.{v.minor}.{v.micro} ({sys.executable})" + ("" if v >= (3, 9) else " — need 3.9+"))
    try:
        import lark
        line(True, "lark (parser)", lark.__version__)
    except ImportError:
        line(False, "lark (parser)", "missing — run: pip install lark")
    try:
        import anthropic
        line(None, "anthropic (live mode)", anthropic.__version__)
    except ImportError:
        line(None, "anthropic (live mode)", "not installed — optional; pip install anthropic for --live")
    line(None, "ANTHROPIC_API_KEY", "set" if os.environ.get("ANTHROPIC_API_KEY") else "not set — optional; needed only for --live")
    line((HERE / "algoruntime.py").exists(), "runtime", str(HERE / "algoruntime.py"))
    try:
        compile_source((HERE / "examples" / "research_brief.algo").read_text(encoding="utf-8"), "selftest.algo")
        line(True, "compiler self-test", "examples/research_brief.algo compiles")
    except Exception as e:  # noqa
        line(False, "compiler self-test", str(e)[:80])
    print("\nReady." if ok else "\nFix the ✗ items above, then run `algo doctor` again.")
    return 0 if ok else 1


MENU = """
  AlgoLang {v} Enterprise — every unit of work is an agent

   COMMAND LINE                              ENTERPRISE
     1  Create a new program                  10  Browse 120 domain packs
     2  Run a program or domain pack          11  Batch-run a program over a CSV
     3  Check a program for errors            12  Human review queue
     4  Interactive shell                     13  Usage & governance report
     5  Environment check                     14  Verify audit chains
   GRAPHICAL                                  15  Create an enterprise project
     6  AlgoLang Studio (browser IDE)
     7  Jupyter notebook
   PROMPT-BASED
     8  Prompt UI in your browser — describe a problem, get a running solution
     9  Prompt mode in this terminal
    16  Ask AI to write a program         17  Wizard (no AI needed)
   DEVELOPER
    18  Lint every .algo file here        19  Run behaviour tests (*.algotest.json)

     0  Exit
"""


def _pick_file():
    files = sorted(Path.cwd().glob("*.algo")) + sorted((HERE / "examples").glob("*.algo"))
    if not files:
        return input("  Path to the .algo file: ").strip()
    for n, f in enumerate(files, 1):
        where = "" if f.parent == Path.cwd() else "  (example)"
        print(f"   {n}. {f.name}{where}")
    c = input("  Choose a number or type a path: ").strip()
    if c.isdigit() and 1 <= int(c) <= len(files):
        return str(files[int(c) - 1])
    return c


def menu():
    """Numbered menu shown when `algo` is typed on its own."""
    while True:
        print(MENU.format(v=VERSION))
        try:
            c = input("  Choose 0-19: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        print()
        if c == "0" or c.lower() in ("q", "exit", "quit"):
            return 0
        try:
            if c == "1":
                name = input("  Name for the new program [mylesson]: ").strip() or "mylesson"
                main(["new", name])
            elif c == "2":
                f = _pick_file()
                if f:
                    main(["run", f])
            elif c == "3":
                f = _pick_file()
                if f:
                    main(["check", f])
            elif c == "4":
                main(["shell"])
            elif c == "5":
                main(["doctor"])
            elif c == "6":
                main(["studio"])
            elif c == "7":
                main(["notebook"])
            elif c == "8":
                main(["studio", "--prompt"])
            elif c == "9":
                main(["chat"])
            elif c == "10":
                q = input("  Search (e.g. 'insurance claims') or Enter to list sectors: ").strip()
                main(["domains"] + ([q] if q else []))
            elif c == "11":
                f = _pick_file()
                csvf = input("  CSV file with one row per case: ").strip()
                if f and csvf:
                    main(["batch", f, "--input", csvf])
            elif c == "12":
                main(["review"])
            elif c == "13":
                main(["report"])
            elif c == "14":
                main(["audit", "verify", "runs"])
            elif c == "15":
                d = input("  Folder for the project [my_enterprise]: ").strip() or "my_enterprise"
                main(["init", d])
            elif c == "16":
                req = input("  Describe the AI system you want: ").strip()
                if req:
                    main(["ask", req])
            elif c == "17":
                main(["wizard"])
            elif c == "18":
                main(["dev", "lint", "."])
            elif c == "19":
                main(["dev", "test", "."])
            else:
                print("  Please type a number from 0 to 19.")
        except (EOFError, KeyboardInterrupt):
            print()
        input("\n  Press Enter to return to the menu… ")


def main(argv=None):
    _utf8_console()
    ap = argparse.ArgumentParser(prog="algo", description=f"AlgoLang {VERSION} — every unit of work is an agent")
    ap.add_argument("--version", action="version", version=f"AlgoLang {VERSION}")
    sub = ap.add_subparsers(dest="cmd", metavar="command")
    for c, h in (("check", "check a program for errors"), ("build", "compile to Python"),
                 ("run", "compile and run flow main")):
        s = sub.add_parser(c, help=h)
        s.add_argument("file")
        if c == "build":
            s.add_argument("-o", "--out")
        if c == "run":
            s.add_argument("--arg", action="append", default=[], help='flow input, e.g. --arg "topic=AI ethics"')
            s.add_argument("--live", action="store_true", help="call real Claude models (needs ANTHROPIC_API_KEY)")
            s.add_argument("--interactive", action="store_true", help="ask a human to approve low-confidence results")
            s.add_argument("--audit-dir", default=None, help="where audit logs go (default: runs/ or algo.config.json)")
            s.add_argument("--trace", nargs="?", const="1", default=None,
                           help="record a trace for `algo replay` (optionally give the file path)")
    s = sub.add_parser("new", help="create a starter program")
    s.add_argument("name")
    sub.add_parser("doctor", help="check that the environment is ready")
    sub.add_parser("notebook", help="open the AlgoLang notebook in Jupyter (installs Jupyter if needed)")
    sub.add_parser("shell", help="interactive shell: type agents line by line")
    s = sub.add_parser("studio", help="AlgoLang Studio: graphical IDE in your browser")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--prompt", action="store_true", help="open the Prompt UI page")
    s.add_argument("--host", default="127.0.0.1", help="address to bind (default 127.0.0.1; use 0.0.0.0 only in a container)")
    s = sub.add_parser("ui", help="Prompt UI in your browser (same as studio --prompt)")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--host", default="127.0.0.1", help="address to bind (default 127.0.0.1)")
    sub.add_parser("chat", help="prompt mode in the terminal: describe a problem in plain English")
    s = sub.add_parser("init", help="create an enterprise project (config, company tools, knowledge base)")
    s.add_argument("dir", nargs="?", default=".")
    s = sub.add_parser("domains", help="browse or search the 120 domain packs")
    s.add_argument("query", nargs="*")
    s.add_argument("--sector")
    s = sub.add_parser("pack", help="show a domain pack, or --copy it here to customise")
    s.add_argument("id")
    s.add_argument("--copy", action="store_true")
    s = sub.add_parser("batch", help="run a program over every row of a CSV, in parallel")
    s.add_argument("file", help="a .algo file or pack:<id>")
    s.add_argument("--input", required=True, help="CSV with a column per flow input")
    s.add_argument("--out")
    s.add_argument("--workers", type=int, default=8)
    s.add_argument("--live", action="store_true")
    s = sub.add_parser("review", help="human review queue: list, approve, reject")
    s.add_argument("action", nargs="?", choices=["list", "all", "approve", "reject"])
    s.add_argument("item", nargs="?")
    s.add_argument("--reviewer", default="")
    s.add_argument("--note", default="")
    s = sub.add_parser("audit", help="verify tamper-evident audit logs")
    s.add_argument("action", choices=["verify"])
    s.add_argument("target", nargs="?", default="runs")
    s = sub.add_parser("report", help="usage, cost and governance report from audit logs")
    s.add_argument("dir", nargs="?", default="runs")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("ask", help='agentic: AI writes a program from your description')
    s.add_argument("request", nargs="+", help='what the program should do, e.g. "review research papers"')
    s.add_argument("-o", "--out", help="file to write (default: from the request)")
    s.add_argument("--run", action="store_true", help="run the program after writing it")
    sub.add_parser("wizard", help="build a program by answering questions (no AI needed)")
    # v0.3
    s = sub.add_parser("eval", help="run the eval blocks in a program (offline, live, or replayed from traces)")
    s.add_argument("file")
    s.add_argument("--live", action="store_true", help="use real Claude models")
    s.add_argument("--replay", nargs="?", const="", default=None, metavar="DIR",
                   help="answer from traces recorded by an earlier eval run (no model calls)")
    s.add_argument("--record", default=None, metavar="DIR", help="where to save traces (default runs/traces/eval)")
    s.add_argument("--only", default=None, help="run only the eval block with this name")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("replay", help="re-run a recorded trace with no model calls and show what changed")
    s.add_argument("trace")
    s.add_argument("--program", default=None, help="the .algo file to replay (default: the one in the trace)")
    s.add_argument("--lenient", action="store_true", help="answer changed calls offline instead of stopping")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("mcp", help="MCP servers: list their tools or call one")
    s.add_argument("action", choices=["servers", "list", "call"])
    s.add_argument("server", nargs="?")
    s.add_argument("tool", nargs="?")
    s.add_argument("arguments", nargs="?", default="{}", help="JSON arguments for `call`")
    sub.add_parser("lsp", help="language server for editors (VS Code, Neovim …) over stdio")
    s = sub.add_parser("stream", help="real-time: run a flow for every event on a Kafka topic (or a file, offline)")
    s.add_argument("file")
    s.add_argument("--name", default=None, help="which stream block to run (if the program has several)")
    s.add_argument("--input", default=None, help="offline: read events from a JSON Lines file")
    s.add_argument("--kafka", action="store_true", help="use the live Kafka cluster named in the stream block")
    s.add_argument("--produce", default=None, metavar="EVENTS", help="with --kafka: publish a JSON Lines file to the source topic and exit")
    s.add_argument("--max", type=int, default=None, help="stop after this many events")
    s.add_argument("--idle", type=float, default=None, help="with --kafka: stop after this many seconds without events")
    s.add_argument("--live", action="store_true", help="call real Claude models (default: offline mock backend)")
    s.add_argument("--out", default=None, help="offline: folder for result topics (default runs/streams/<name>)")
    s.add_argument("--json", action="store_true")
    import algodev
    algodev.add_parser(sub)
    a = ap.parse_args(argv)

    if a.cmd is None:
        return menu()
    if a.cmd in ("eval", "replay"):
        import algoeval
        if a.cmd == "eval":
            return algoeval.cli_eval(a.file, live=a.live, replay=a.replay, record=a.record, only=a.only, as_json=a.json)
        return algoeval.cli_replay(a.trace, program=a.program, strict=not a.lenient, as_json=a.json)
    if a.cmd == "mcp":
        import algomcp
        return algomcp.cli(a.action, a.server, a.tool, a.arguments)
    if a.cmd == "stream":
        import algostream
        return algostream.cli(a.file, name=a.name, input_path=a.input, kafka=a.kafka, produce=a.produce,
                              max_events=a.max, idle=a.idle, live=a.live, as_json=a.json, out_dir=a.out)
    if a.cmd == "lsp":
        import algolsp
        return algolsp.main()
    if a.cmd == "dev":
        return algodev.dispatch(a)
    if a.cmd == "shell":
        import algoshell
        algoshell.main()
        return 0
    if a.cmd in ("studio", "ui"):
        import algostudio
        algostudio.serve(a.port, not a.no_browser, page="prompt" if (a.cmd == "ui" or a.prompt) else "",
                         host=a.host)
        return 0
    if a.cmd in ("chat", "init", "domains", "pack", "batch", "review", "audit", "report"):
        import algocli_ext as X
        if a.cmd == "chat":
            return X.cmd_chat()
        if a.cmd == "init":
            return X.cmd_init(a.dir)
        if a.cmd == "domains":
            return X.cmd_domains(" ".join(a.query) or None, a.sector)
        if a.cmd == "pack":
            return X.cmd_pack(a.id, a.copy)
        if a.cmd == "batch":
            return X.cmd_batch(a.file, a.input, a.out, a.workers, a.live)
        if a.cmd == "review":
            return X.cmd_review(a.action if a.action in ("approve", "reject") else None, a.item,
                                a.reviewer, a.note, show_all=a.action == "all")
        if a.cmd == "audit":
            return X.cmd_audit_verify(a.target)
        if a.cmd == "report":
            return X.cmd_report(a.dir, a.json)
    if a.cmd == "ask":
        import algoagent
        name = algoagent.ask_cli(" ".join(a.request), a.out)
        if name and a.run:
            return main(["run", name])
        if name:
            print(f'  next:  algo run {name}')
        return 0 if name else 1
    if a.cmd == "wizard":
        import algoagent
        name, inp = algoagent.wizard()
        if input("Run it now? (y/n) [y]: ").strip().lower() in ("", "y", "yes"):
            value = input(f"Value for {inp}: ").strip() or "an example"
            return main(["run", name, "--arg", f"{inp}={value}"])
        print(f'  next:  algo run {name} --arg "{inp}=..."')
        return 0
    if a.cmd == "doctor":
        return doctor()
    if a.cmd == "notebook":
        nb = HERE / "AlgoLang_Notebook.ipynb"
        try:
            import notebook  # noqa: F401
        except ImportError:
            print("→ installing Jupyter Notebook (one time, takes a minute)…")
            rc = subprocess.call([sys.executable, "-m", "pip", "install", "--quiet", "notebook", "graphviz"])
            if rc != 0:
                print("✗ could not install Jupyter — check your internet connection", file=sys.stderr)
                return rc
        print(f"→ opening {nb.name} in your browser (press Ctrl+C here to stop Jupyter)")
        return subprocess.call([sys.executable, "-m", "notebook", str(nb)], cwd=str(HERE))
    if a.cmd == "new":
        p = Path(a.name if a.name.endswith(".algo") else a.name + ".algo")
        if p.exists():
            print(f"✗ {p} already exists", file=sys.stderr)
            return 1
        p.write_text(TEMPLATE.format(name=p.stem), encoding="utf-8")
        print(f"✓ created {p}\n  next:  algo run {p} --arg \"topic=Neural networks\"")
        return 0

    path = Path(a.file)
    from_pack = False
    if not path.exists():
        import algocli_ext
        found = algocli_ext.resolve_program(a.file)
        if not found:
            print(f"✗ file not found: {path} (for a domain pack use pack:<id>, see `algo domains`)", file=sys.stderr)
            return 1
        path, from_pack = found, True
    src = path.read_text(encoding="utf-8")
    try:
        code, prog = compile_source(src, path.name, path.resolve().parent)
    except CompileError as e:
        print(f"✗ {path.name}: {len(e.diags)} error(s)", file=sys.stderr)
        for d in e.diags:
            print("  " + str(d), file=sys.stderr)
        return 1

    if a.cmd == "check":
        print(f"✓ {path.name}: {len(prog.agents)} agents, {len(prog.flows)} flow(s), "
              f"{len(prog.tools)} tool(s) — no errors")
        return 0

    build_dir = (Path.cwd() if from_pack else path.resolve().parent) / "build"
    out = Path(getattr(a, "out", None) or (build_dir / (path.stem + ".py")))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(code, encoding="utf-8")
    if a.cmd == "build":
        print(f"✓ compiled {path.name} → {out}")
        return 0

    env = dict(os.environ)
    env["ALGO_HOME"] = str(HERE)
    env["PYTHONIOENCODING"] = "utf-8"
    if a.audit_dir:
        env["ALGO_AUDIT_DIR"] = a.audit_dir
    if a.live:
        env["ALGO_LIVE"] = "1"
    if a.interactive:
        env["ALGO_INTERACTIVE"] = "1"
    if a.trace:
        env["ALGO_TRACE"] = a.trace if a.trace == "1" else str(Path(a.trace).resolve())
        env["ALGO_SOURCE"] = str(path.resolve())
    for kv in a.arg:
        if "=" not in kv:
            print(f'✗ --arg needs name=value, e.g. --arg "topic=AI"; got: {kv}', file=sys.stderr)
            return 1
    inputs = [p.name for p in prog.flows["main"].params]
    unknown = [kv.split("=", 1)[0] for kv in a.arg if kv.split("=", 1)[0] not in inputs]
    if unknown:
        hint = " ".join(f'--arg "{n}=..."' for n in inputs) or "(it takes no inputs)"
        print(f"✗ {path.name} has no input named {', '.join(unknown)}. Its inputs: {', '.join(inputs) or 'none'}\n"
              f"  try:  algo run {a.file} {hint}", file=sys.stderr)
        return 1
    cmd = [sys.executable, str(out)] + [f"--{kv}" for kv in a.arg]
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:            # output piped into `head` etc.
        try:
            sys.stdout = open(os.devnull, "w")
        finally:
            sys.exit(0)
