"""algodiff — governance diff for AlgoLang (v1.1).

    algo diff old/loan.algo loan.algo
    algo diff git:main:programs/loan.algo programs/loan.algo --markdown
    algo diff v1.algo v2.algo --fail-on any

A code diff shows which lines changed. A governance diff shows what those lines *mean*: a budget that was
raised, a forbidden attribute that was removed, a reviewer that is no longer required, a contract that was
dropped, an eval case that no longer runs, a tool that an agent can now use.

Every change is classed as

    ▼ loosened   — the program is now allowed to do more, or is checked less
    ▲ tightened  — the program is now allowed to do less, or is checked more
    ● changed    — neither (a new model, a reworded goal, a new agent)

By default the command fails (exit 1) when anything is loosened, so a pull request that weakens a
safeguard cannot be merged without someone looking at it on purpose.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import algoc

GREEN, RED, GOLD, DIM, BOLD, END = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
if not sys.stdout.isatty() or __import__("os").environ.get("NO_COLOR"):
    GREEN = RED = GOLD = DIM = BOLD = END = ""

LOOSE, TIGHT, CHANGED = "loosened", "tightened", "changed"
RISK_ORDER = {"minimal": 0, "limited": 1, "high": 2}

# policy limits where a larger number allows more
UPPER = {"budget_tokens": "token budget", "budget_cost_usd": "cost budget (USD)", "budget_cost_inr": "cost budget (INR)",
         "budget_energy_wh": "energy budget (Wh)", "budget_qpu_s": "QPU budget (seconds)",
         "budget_qpu_usd": "QPU budget (USD)", "timeout_s": "timeout (s)", "max_qubits": "max qubits",
         "retry": "retries"}
# checks where a larger number means more checking
LOWER = {"human_below": "human review below confidence", "approvals": "required approvals",
         "samples": "samples for uncertain answers"}
FLAGS = {"human_always": "every result reviewed by a person", "redact_pii": "PII redaction"}


class DiffError(Exception):
    pass


def read_source(spec):
    """A path, or git:REV:path for a version from git history."""
    if spec.startswith("git:"):
        try:
            _, rev, path = spec.split(":", 2)
        except ValueError:
            raise DiffError("use git:REV:path, e.g. git:main:programs/loan.algo")
        p = Path(path)
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=p.parent if p.parent.exists() else ".",
                             capture_output=True, text=True)
        if top.returncode:
            raise DiffError("not inside a git repository")
        rel = p.resolve().relative_to(Path(top.stdout.strip()))
        r = subprocess.run(["git", "show", f"{rev}:{rel.as_posix()}"], cwd=top.stdout.strip(), capture_output=True,
                           text=True, encoding="utf-8")
        if r.returncode:
            raise DiffError(f"git cannot find {rel} at {rev}: {r.stderr.strip()}")
        return r.stdout, p.name, p.resolve().parent, f"{rev}:{rel.as_posix()}"
    p = Path(spec)
    if not p.exists():
        raise DiffError(f"no such file: {spec}")
    return p.read_text(encoding="utf-8"), p.name, p.resolve().parent, str(spec)


def load(spec):
    src, name, base, label = read_source(spec)
    try:
        prog, diags = algoc.load_program(src, name, base, file_label=label)
    except algoc.CompileError as e:
        raise DiffError(f"{label} does not compile:\n" + "\n".join(f"  {d}" for d in e.diags))
    return prog, label


def _num(x):
    return f"{x:g}" if isinstance(x, (int, float)) and not isinstance(x, bool) else str(x)


def compare_policy(where, old: dict, new: dict, out):
    def add(kind, what, before, after):
        out.append(dict(kind=kind, where=where, what=what, before=before, after=after))
    for k, label in UPPER.items():
        b, a = old.get(k), new.get(k)
        if b == a:
            continue
        if a is None:
            add(LOOSE, f"{label} removed", _num(b), None)
        elif b is None:
            add(TIGHT, f"{label} added", None, _num(a))
        else:
            add(LOOSE if a > b else TIGHT, f"{label} {'raised' if a > b else 'lowered'}", _num(b), _num(a))
    for k, label in LOWER.items():
        b, a = old.get(k), new.get(k)
        if b == a:
            continue
        if a is None:
            add(LOOSE, f"{label} removed", _num(b), None)
        elif b is None:
            add(TIGHT, f"{label} added", None, _num(a))
        else:
            add(LOOSE if a < b else TIGHT, f"{label} {'lowered' if a < b else 'raised'}", _num(b), _num(a))
    for k, label in FLAGS.items():
        b, a = bool(old.get(k)), bool(new.get(k))
        if b != a:
            add(LOOSE if b else TIGHT, f"{label} {'removed' if b else 'added'}", b, a)
    fb, fa = set(old.get("forbid", [])), set(new.get("forbid", []))
    for attr in sorted(fb - fa):
        add(LOOSE, f"forbidden attribute '{attr}' allowed again", "forbid", None)
    for attr in sorted(fa - fb):
        add(TIGHT, f"attribute '{attr}' now forbidden", None, "forbid")
    rank = {None: 0, "reasons": 1, "evidence": 2}
    eb, ea = old.get("explain"), new.get("explain")
    if eb != ea:
        add(LOOSE if rank.get(ea, 0) < rank.get(eb, 0) else TIGHT, "explanations " + (
            "no longer required" if ea is None else f"now '{ea}'"), eb, ea)
    cb = {c["text"]: c for c in old.get("ensure", [])}
    ca = {c["text"]: c for c in new.get("ensure", [])}
    for t in cb:
        if t not in ca:
            add(LOOSE, "contract removed", f"ensure {t}", None)
    for t in ca:
        if t not in cb:
            add(TIGHT, "contract added", None, f"ensure {t}")
    for k in ("retain_audit_days", "retain_traces_days", "shots", "cache"):
        if old.get(k) != new.get(k):
            add(CHANGED, k.replace("_", " "), old.get(k), new.get(k))


def diff(old_prog, new_prog):
    out = []

    def add(kind, where, what, before=None, after=None):
        out.append(dict(kind=kind, where=where, what=what, before=before, after=after))

    rb, ra = old_prog.risk[0] if old_prog.risk else None, new_prog.risk[0] if new_prog.risk else None
    if rb != ra:
        lb, la = RISK_ORDER.get(rb, -1), RISK_ORDER.get(ra, -1)
        add(LOOSE if la < lb else TIGHT, "program", f"risk level {'lowered' if la < lb else 'raised'}", rb, ra)
    if old_prog.disclosure and not new_prog.disclosure:
        add(LOOSE, "program", "AI disclosure removed", old_prog.disclosure, None)
    elif new_prog.disclosure and not old_prog.disclosure:
        add(TIGHT, "program", "AI disclosure added", None, new_prog.disclosure)
    elif old_prog.disclosure != new_prog.disclosure:
        add(CHANGED, "program", "AI disclosure reworded", old_prog.disclosure, new_prog.disclosure)
    for t in sorted(new_prog.tools - old_prog.tools):
        add(CHANGED, "program", f"tool '{t}' declared", None, "declared")
    for t in sorted(old_prog.tools - new_prog.tools):
        add(CHANGED, "program", f"tool '{t}' no longer declared", "declared", None)
    for t in sorted((old_prog.untrusted - new_prog.untrusted) & new_prog.tools):
        add(LOOSE, "program", f"tool '{t}' is no longer treated as untrusted", "untrusted", "trusted")
    for t in sorted(new_prog.untrusted - old_prog.untrusted):
        add(TIGHT, "program", f"tool '{t}' is now treated as untrusted", "trusted", "untrusted")
    for t in sorted(set(old_prog.mcp_tools) & set(new_prog.mcp_tools)):
        if old_prog.mcp_tools[t] != new_prog.mcp_tools[t]:
            add(CHANGED, "program", f"tool '{t}' comes from another MCP server", old_prog.mcp_tools[t],
                new_prog.mcp_tools[t])

    oa, na = old_prog.agents, new_prog.agents
    for n in sorted(set(na) - set(oa)):
        a = na[n]
        add(CHANGED, f"agent {n}", "new agent", None, f"-> {a.returns}" + (f", uses {', '.join(a.uses)}" if a.uses else ""))
    for n in sorted(set(oa) - set(na)):
        add(CHANGED, f"agent {n}", "agent removed", oa[n].returns, None)
    for n in sorted(set(oa) & set(na)):
        a, b = oa[n], na[n]
        where = f"agent {n}"
        for t in sorted(set(b.uses) - set(a.uses)):
            add(LOOSE, where, f"can now use tool '{t}'", None, t)
        for t in sorted(set(a.uses) - set(b.uses)):
            add(TIGHT, where, f"no longer uses tool '{t}'", t, None)
        if a.returns != b.returns:
            unc_b, unc_a = a.returns.startswith("uncertain<"), b.returns.startswith("uncertain<")
            kind = LOOSE if unc_b and not unc_a else (TIGHT if unc_a and not unc_b else CHANGED)
            add(kind, where, "return type changed" + (" (no longer sampled for confidence)" if kind == LOOSE else ""),
                a.returns, b.returns)
        pb, pa = [(p.name, p.type) for p in a.params], [(p.name, p.type) for p in b.params]
        if pb != pa:
            add(CHANGED, where, "inputs changed", ", ".join(f"{x}: {t}" for x, t in pb), ", ".join(f"{x}: {t}" for x, t in pa))
        if a.model != b.model:
            add(CHANGED, where, "model changed", a.model, b.model)
        if a.goal != b.goal:
            add(CHANGED, where, "goal reworded", a.goal, b.goal)
        if a.role != b.role:
            add(CHANGED, where, "role reworded", a.role, b.role)
        compare_policy(where, a.policy, b.policy, out)

    def cases(p):
        return {(e.name, c.name): c for e in p.evals for c in e.cases}
    cb, ca = cases(old_prog), cases(new_prog)
    for k in sorted(set(cb) - set(ca)):
        add(LOOSE, f"eval {k[0]}", f"case '{k[1]}' removed", f"{len(cb[k].expects)} expectation(s)", None)
    for k in sorted(set(ca) - set(cb)):
        add(TIGHT, f"eval {k[0]}", f"case '{k[1]}' added", None, f"{len(ca[k].expects)} expectation(s)")
    for k in sorted(set(cb) & set(ca)):
        eb = {json.dumps(x, default=str) for x in cb[k].expects}
        ea = {json.dumps(x, default=str) for x in ca[k].expects}
        for x in sorted(eb - ea):
            add(LOOSE, f"eval {k[0]}", f"case '{k[1]}': expectation removed", _expect_text(json.loads(x)), None)
        for x in sorted(ea - eb):
            add(TIGHT, f"eval {k[0]}", f"case '{k[1]}': expectation added", None, _expect_text(json.loads(x)))
    order = {LOOSE: 0, TIGHT: 1, CHANGED: 2}
    out.sort(key=lambda d: order[d["kind"]])
    return out


def _expect_text(e):
    kind, op, val = e
    if kind in ("fair",):
        return f"expect fair across {op} {val}"
    if kind == "robust":
        return f"expect robust consistency {op} {val[1]}"
    if op:
        return f"expect {kind} {op} {_num(val)}"
    return f"expect {kind} {val}" if val is not True else f"expect {kind}"


def summarise(changes):
    return {k: sum(1 for c in changes if c["kind"] == k) for k in (LOOSE, TIGHT, CHANGED)}


def render(old_label, new_label, changes):
    out = [f"  {BOLD}governance diff{END}  {old_label}  →  {new_label}"]
    if not changes:
        out.append(f"  {GREEN}✓ no governance changes{END}")
        return "\n".join(out)
    mark = {LOOSE: f"{RED}▼ loosened {END}", TIGHT: f"{GREEN}▲ tightened{END}", CHANGED: f"{GOLD}● changed  {END}"}
    for c in changes:
        ba = ""
        if c["before"] is not None or c["after"] is not None:
            b = "—" if c["before"] is None else str(c["before"])
            a = "—" if c["after"] is None else str(c["after"])
            ba = f"  {DIM}{b[:48]} → {a[:48]}{END}"
        out.append(f"  {mark[c['kind']]}  {c['where']:<22} {c['what']}{ba}")
    s = summarise(changes)
    out.append("")
    out.append(f"  {s[LOOSE]} loosened · {s[TIGHT]} tightened · {s[CHANGED]} other change(s)")
    return "\n".join(out)


def to_markdown(old_label, new_label, changes):
    s = summarise(changes)
    head = "⚠️ **Governance loosened**" if s[LOOSE] else "✅ **No safeguards loosened**"
    lines = [f"### AlgoLang governance diff", f"`{old_label}` → `{new_label}`", "",
             f"{head} · {s[LOOSE]} loosened · {s[TIGHT]} tightened · {s[CHANGED]} other", ""]
    if changes:
        lines += ["| | Where | Change | Before | After |", "|:--|:--|:--|:--|:--|"]
        icon = {LOOSE: "🔻 loosened", TIGHT: "🔺 tightened", CHANGED: "● changed"}
        for c in changes:
            esc = lambda v: "—" if v is None else str(v).replace("|", "\\|")[:80]  # noqa: E731
            lines.append(f"| {icon[c['kind']]} | {c['where']} | {c['what']} | {esc(c['before'])} | {esc(c['after'])} |")
    return "\n".join(lines)


def cli(old, new, fail_on="loosened", as_json=False, markdown=False):
    try:
        po, lo = load(old)
        pn, ln = load(new)
    except DiffError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2
    changes = diff(po, pn)
    if as_json:
        print(json.dumps(dict(old=lo, new=ln, summary=summarise(changes), changes=changes), indent=2, default=str))
    elif markdown:
        print(to_markdown(lo, ln, changes))
    else:
        print(render(lo, ln, changes))
    s = summarise(changes)
    if fail_on == "loosened" and s[LOOSE]:
        return 1
    if fail_on == "any" and changes:
        return 1
    return 0
