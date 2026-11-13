"""algowhatif — what-if audits for AlgoLang (v1.1).

    algo whatif runs/traces/loan.trace.json --set income=42000
    algo whatif runs/traces/loan.trace.json --swap "Mr.=Ms." --expect same
    algo whatif programs/loan.algo --arg "app=..." --set dti=0.62

A what-if audit answers the question an auditor, a regulator or the applicant actually asks:
"would the decision have been different if this one thing had been different?"

It re-runs a recorded decision with one or more inputs changed. Every agent whose inputs did not change is
answered from the recording, so only the part of the flow that really depends on the change is re-computed,
and the comparison is exact rather than noisy. The report lists, agent by agent, what changed (answer,
confidence, review status, contracts) and whether the final decision flipped.

`--expect same` turns this into a test: the command fails (exit 1) when the decision changes, so a
counterfactual fairness check on a real, recorded case can run in CI.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import algoruntime as rt

GREEN, RED, NAVY, GOLD, DIM, BOLD, END = "\033[32m", "\033[31m", "\033[34m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
if not sys.stdout.isatty() or __import__("os").environ.get("NO_COLOR"):
    GREEN = RED = NAVY = GOLD = DIM = BOLD = END = ""


class WhatIfError(Exception):
    pass


def parse_pairs(items, what):
    out = []
    for it in items or []:
        if "=" not in it:
            raise WhatIfError(f"{what} needs NAME=VALUE (got {it!r})")
        k, v = it.split("=", 1)
        out.append((k.strip(), v))
    return out


def apply_changes(inputs: dict, sets=(), swaps=()):
    """Return (new inputs, list of human-readable changes). `sets` replace an input; `swaps` replace a word or
    phrase inside every text input (whole words, case kept), e.g. swap 'he=she'."""
    new, changes = dict(inputs), []
    for k, v in sets:
        if k not in new:
            raise WhatIfError(f"no input named '{k}' (inputs: {', '.join(new) or 'none'})")
        if str(new[k]) != v:
            changes.append(dict(kind="set", input=k, before=new[k], after=v))
        new[k] = v
    for old, rep in swaps:
        pat = re.compile(rf"(?<!\w){re.escape(old)}(?!\w)", re.I)
        hit = False
        for k, v in new.items():
            if isinstance(v, str) and pat.search(v):
                hit = True
                new[k] = pat.sub(lambda m: rep[:1].upper() + rep[1:] if m.group(0)[:1].isupper() else rep, v)
        if not hit:
            raise WhatIfError(f"'{old}' does not appear in any text input — nothing to swap")
        changes.append(dict(kind="swap", before=old, after=rep))
    if not changes:
        raise WhatIfError("nothing changed: give --set NAME=VALUE or --swap OLD=NEW")
    return new, changes


def _j(v):
    v = rt.Runtime.value(v)
    return rt._jsonable(v)


def _calls(res):
    """[(key, call)] with key = (agent, occurrence) so repeated agents pair up in order."""
    seen, out = {}, []
    for c in res.calls:
        if c.get("status") in ("blocked", "failed") and "output" not in c:
            continue
        n = seen.get(c["agent"], 0)
        seen[c["agent"]] = n + 1
        out.append(((c["agent"], n), c))
    return out


def _short(v, n=60):
    s = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def compare(before, after):
    """Agent-by-agent comparison of two RunResults."""
    b, a = dict(_calls(before)), dict(_calls(after))
    order = [k for k, _ in _calls(before)] + [k for k, _ in _calls(after) if k not in b]
    rows = []
    for key in order:
        cb, ca = b.get(key), a.get(key)
        row = dict(agent=key[0], occurrence=key[1])
        if cb is None or ca is None:
            row["change"] = "added" if cb is None else "removed"
            c = ca or cb
            row["before" if cb else "after"] = None
            row["after" if cb is None else "before"] = dict(value=_j(c.get("output")), confidence=c.get("confidence"),
                                                           status=c.get("status"))
            rows.append(row)
            continue
        vb, va = _j(cb.get("output")), _j(ca.get("output"))
        row["before"] = dict(value=vb, confidence=cb.get("confidence"), status=cb.get("status"))
        row["after"] = dict(value=va, confidence=ca.get("confidence"), status=ca.get("status"))
        kinds = []
        if vb != va:
            kinds.append("answer")
        if cb.get("status") != ca.get("status"):
            kinds.append("review")
        if abs(float(cb.get("confidence") or 0) - float(ca.get("confidence") or 0)) >= 0.005:
            kinds.append("confidence")
        cvb = [v["contract"] for v in (cb.get("contracts") or {}).get("violated", [])]
        cva = [v["contract"] for v in (ca.get("contracts") or {}).get("violated", [])]
        if cvb != cva:
            kinds.append("contracts")
            row["contracts"] = dict(before=cvb, after=cva)
        row["change"] = ",".join(kinds) if kinds else "same"
        rows.append(row)
    return rows


def whatif(program, inputs, sets=(), swaps=(), flow="main", trace=None, live=False, audit_dir=None):
    """Run the original and the changed case and compare them. With a trace, the original is replayed exactly
    and unchanged agent calls in the changed case are answered from the recording."""
    new_inputs, changes = apply_changes(inputs, sets, swaps)
    audit_dir = audit_dir or str(Path(program.base_dir or ".") / "runs" / "whatif")
    if trace is not None:
        base_backend = rt.ReplayBackend(trace, strict=False)
        alt_backend = rt.ReplayBackend(trace, strict=False)
        if live:                                     # calls that depend on the change go to the real model
            alt_backend._mock = rt.Runtime(program="whatif", quiet=True, live=True).backend
    else:
        base_backend = alt_backend = None
    before = program.run(live=live, quiet=True, audit_dir=audit_dir, backend=base_backend, flow=flow, **inputs)
    after = program.run(live=live, quiet=True, audit_dir=audit_dir, backend=alt_backend, flow=flow, **new_inputs)
    rows = compare(before, after)
    vb = [_j(v) for v in before.values]
    va = [_j(v) for v in after.values]
    esc_b = sorted(c["agent"] for c in before.calls if c.get("status") == "escalated")
    esc_a = sorted(c["agent"] for c in after.calls if c.get("status") == "escalated")
    path_b = [k[0] for k, _ in _calls(before)]
    path_a = [k[0] for k, _ in _calls(after)]
    decision_changed = (vb != va or esc_b != esc_a or before.status != after.status)
    recomputed = len({(m["agent"], m["inputs_sha"]) for m in alt_backend.misses}) if alt_backend is not None else None
    return dict(program=program.name, flow=flow, changes=changes, inputs_before=inputs, inputs_after=new_inputs,
                status_before=before.status, status_after=after.status,
                problem_before=before.problem, problem_after=after.problem,
                emitted_before=vb, emitted_after=va, escalated_before=esc_b, escalated_after=esc_a,
                path_before=path_b, path_after=path_a, path_changed=sorted(path_b) != sorted(path_a),   # parallel calls may finish in any order
                agents=rows, decision_changed=decision_changed,
                replayed_from_trace=trace is not None,
                calls_recomputed=recomputed, calls_total=len(path_a),
                verdict="changed" if decision_changed else "same")


def load_target(target, args=(), flow=None, program_file=None):
    """A trace file or an .algo program (+ --arg inputs). Returns (Program, inputs, flow, trace-or-None)."""
    import algolang as al
    p = Path(target)
    if p.suffix == ".json":
        t = json.loads(p.read_text(encoding="utf-8"))
        src = program_file or t.get("source")
        if not src or not Path(src).exists():
            raise WhatIfError(f"cannot find the program for this trace ({src!r}); pass --program FILE")
        return al.load(src), dict(t.get("inputs") or {}), flow or t.get("flow") or "main", t
    if not p.exists():
        raise WhatIfError(f"no such file: {target}")
    prog = al.load(str(p))
    flow = flow or "main"
    inputs = dict(parse_pairs(args, "--arg"))
    missing = [n for n in prog.flow_inputs(flow) if n not in inputs]
    if missing:
        raise WhatIfError(f"missing input(s): {', '.join(missing)} — add --arg NAME=VALUE")
    return prog, inputs, flow, None


def render(r):
    out = []
    w = out.append
    w(f"  {BOLD}what-if audit{END}  {r['program']} · flow {r['flow']}"
      + (f"  {DIM}(unchanged calls replayed from the recording){END}" if r["replayed_from_trace"] else ""))
    for c in r["changes"]:
        if c["kind"] == "set":
            w(f"  {GOLD}change{END}  {c['input']}: {_short(c['before'], 50)!s}  →  {_short(c['after'], 50)}")
        else:
            w(f"  {GOLD}change{END}  every '{c['before']}' → '{c['after']}'")
    w("")
    w(f"  {'agent':<22} {'before':<30} {'after':<30} change")
    for row in r["agents"]:
        def cell(x):
            if x is None:
                return "—"
            flag = " ⚠" if x["status"] == "escalated" else (" ✔" if x["status"] == "approved" else "")
            conf = f" ({x['confidence']:.2f})" if isinstance(x.get("confidence"), (int, float)) else ""
            return _short(x["value"], 22 - len(flag)) + conf + flag
        ch = row["change"]
        col = GREEN if ch == "same" else (RED if "answer" in ch or "review" in ch or ch in ("added", "removed") else GOLD)
        w(f"  {row['agent']:<22} {cell(row['before']):<30} {cell(row['after']):<30} {col}{ch}{END}")
        if row.get("contracts"):
            w(f"  {'':<22} {DIM}contracts broken: {row['contracts']['before'] or 'none'} → "
              f"{row['contracts']['after'] or 'none'}{END}")
    w("")
    if r["path_changed"]:
        w(f"  {GOLD}path{END}     {' → '.join(r['path_before'])}")
        w(f"  {GOLD}  now{END}    {' → '.join(r['path_after'])}")
    if r["escalated_before"] != r["escalated_after"]:
        w(f"  {GOLD}review{END}   escalated before: {', '.join(r['escalated_before']) or 'none'} · "
          f"now: {', '.join(r['escalated_after']) or 'none'}")
    if r["status_before"] != r["status_after"]:
        w(f"  {GOLD}status{END}   {r['status_before']} → {r['status_after']}  {r['problem_after'] or ''}")
    if r["calls_recomputed"] is not None:
        w(f"  {DIM}{r['calls_recomputed']} of {r['calls_total']} agent call(s) re-computed; the rest came from the "
          f"recording{END}")
    if r["decision_changed"]:
        w(f"  {RED}{BOLD}✗ the decision changed{END}")
        for i, (b, a) in enumerate(zip(r["emitted_before"], r["emitted_after"]), 1):
            if b != a:
                w(f"    output {i}: {_short(b, 70)}")
                w(f"         now: {_short(a, 70)}")
        if len(r["emitted_before"]) != len(r["emitted_after"]):
            w(f"    {len(r['emitted_before'])} output(s) before, {len(r['emitted_after'])} now")
    else:
        w(f"  {GREEN}{BOLD}✓ the decision is the same{END}")
    return "\n".join(out)


def cli(target, sets=(), swaps=(), args=(), flow=None, program=None, live=False, expect=None, as_json=False):
    try:
        prog, inputs, flow, trace = load_target(target, args, flow, program)
        r = whatif(prog, inputs, parse_pairs(sets, "--set"), parse_pairs(swaps, "--swap"), flow=flow,
                   trace=trace, live=live)
    except WhatIfError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str) if as_json else render(r))
    if expect is not None and r["verdict"] != expect:
        if not as_json:
            print(f"  {RED}expected the decision to be {expect}{END}")
        return 1
    return 0
