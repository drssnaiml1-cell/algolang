"""algoeval — `eval` blocks and trace replay for AlgoLang (v0.3).

    algo eval program.algo                 run every eval block offline (deterministic)
    algo eval program.algo --live          run them against real models, recording traces
    algo eval program.algo --replay        re-check them from the recorded traces: no model calls, no cost
    algo replay runs/traces/x.trace.json   re-run one recorded run and report what changed

An eval block lives next to the code it tests:

    eval regression on main {
        case "small motor claim" (claim = "NS-10571: scratch, estimate INR 6,500") {
            expect status ok
            expect called PayoutEstimator
            expect not called fraud.Referral
            expect output contains "estimated payout"
            expect tokens < 2000
            expect cost < 0.05
        }
    }

Every case run with --live (or --record) saves a trace. Replaying the trace answers each agent call
from the recording, so after you change prompts, flows or policies you can see — for free — which
agents now receive different inputs (a "replay miss") and whether the expectations still hold.
"""
from __future__ import annotations

import json
import operator
import re
import sys
import time
from pathlib import Path

import algoruntime as rt

OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "==": operator.eq, "!=": operator.ne}
GREEN, RED, NAVY, GOLD, DIM, END = "\033[32m", "\033[31m", "\033[34m", "\033[33m", "\033[2m", "\033[0m"
if not sys.stdout.isatty() or __import__("os").environ.get("NO_COLOR"):
    GREEN = RED = NAVY = GOLD = DIM = END = ""


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "case"


def check(expects, res) -> list[str]:
    """Return the expectations a RunResult fails (empty list = pass)."""
    fails = []
    called = [c["agent"] for c in res.calls if c.get("status") not in ("blocked", "failed")]
    tools = {t.get("tool") for c in res.calls for t in (c.get("tool_calls") or [])}
    text = " ".join(str(rt.Runtime.value(v)) for v in res.values)
    confs = [c["confidence"] for c in res.calls if c.get("confidence") is not None]
    measured = {"tokens": res.stats.get("tokens", 0), "cost": res.stats.get("cost_usd", 0.0),
                "energy": res.stats.get("energy_wh", 0.0), "escalated": len(res.escalated),
                "confidence": min(confs) if confs else 1.0}
    for kind, op, val in expects:
        if kind == "status" and res.status != val:
            fails.append(f"status is {res.status}, expected {val}" + (f" ({res.problem})" if res.problem else ""))
        elif kind == "called" and val not in called:
            fails.append(f"{val} was not called")
        elif kind == "not_called" and val in called:
            fails.append(f"{val} was called")
        elif kind == "tool" and val not in tools:
            fails.append(f"tool {val} was not used")
        elif kind == "contains" and str(val).lower() not in text.lower():
            fails.append(f"output does not contain {val!r}")
        elif kind == "emits" and len(res.values) != val:
            fails.append(f"emitted {len(res.values)} values, expected {val}")
        elif kind in measured and not OPS[op](measured[kind], val):
            shown = f"{measured[kind]:.4f}" if isinstance(measured[kind], float) else measured[kind]
            fails.append(f"{kind} is {shown}, expected {op} {val:g}")
    return fails


def run_evals(program, live=False, replay=None, record=None, only=None, audit_dir=None):
    """Run a Program's eval blocks. Returns a list of case results (dicts)."""
    base = Path(program.base_dir)
    trace_root = Path(replay if replay else (record or base / "runs" / "traces" / "eval"))
    if replay == "":
        trace_root = base / "runs" / "traces" / "eval"
    results = []
    for ev in program.evals:
        if only and ev.name != only:
            continue
        for case in ev.cases:
            tpath = trace_root / program.name / ev.name / f"{slug(case.name)}.trace.json"
            t0 = time.time()
            replay_info = None
            if replay is not None:
                if not tpath.exists():
                    results.append(dict(eval=ev.name, case=case.name, passed=False, seconds=0, trace=str(tpath),
                                        failures=[f"no recorded trace at {tpath} — record one with "
                                                  f"`algo eval {program.name}.algo --live` (or without --live)"]))
                    continue
                backend = rt.ReplayBackend(tpath, strict=False)
                res = program.run(quiet=True, audit_dir=audit_dir, backend=backend, flow=ev.flow, **case.inputs)
                replay_info = {"hits": backend.hits, "misses": backend.misses}
            else:
                res = program.run(live=live, quiet=True, audit_dir=audit_dir, trace=str(tpath), flow=ev.flow,
                                  **case.inputs)
            fails = check(case.expects, res)
            if replay_info and replay_info["misses"]:
                fails.append("inputs changed since the trace was recorded for: "
                             + ", ".join(sorted({m["agent"] for m in replay_info["misses"]})))
            results.append(dict(eval=ev.name, case=case.name, passed=not fails, failures=fails,
                                seconds=round(time.time() - t0, 3), trace=str(tpath), stats=res.stats,
                                status=res.status, replay=replay_info))
    return results


def cli_eval(file, live=False, replay=None, record=None, only=None, as_json=False):
    import algolang as al
    from algoc import CompileError
    try:
        program = al.load(file)
    except CompileError as e:
        print(f"✗ {file}: {len(e.diags)} error(s)", file=sys.stderr)
        for d in e.diags:
            print("  " + str(d), file=sys.stderr)
        return 1
    if not program.evals:
        args = ", ".join(i + ' = "…"' for i in program.inputs)
        print(f"  {file} has no eval blocks. Add one, e.g.\n\n"
              f"  eval smoke on main {{\n      case \"first\" ({args}) {{ expect status ok }}\n  }}")
        return 0
    results = run_evals(program, live=live, replay=replay, record=record, only=only)
    failed = sum(not r["passed"] for r in results)
    if as_json:
        print(json.dumps(dict(program=file, cases=len(results), failed=failed, results=results), indent=2, default=str))
        return 1 if failed else 0
    mode = "replayed from traces" if replay is not None else ("live models" if live else "offline")
    print(f"  {NAVY}eval {Path(file).name}{END}  {DIM}({mode}){END}")
    cur = None
    for r in results:
        if r["eval"] != cur:
            cur = r["eval"]
            print(f"  {GOLD}{cur}{END}")
        mark = f"{GREEN}✓{END}" if r["passed"] else f"{RED}✗{END}"
        s = r.get("stats") or {}
        cost = f"  {DIM}{s.get('tokens', 0)} tok · ${s.get('cost_usd', 0):.4f} · {s.get('energy_wh', 0):.3f} Wh{END}" if s else ""
        rp = r.get("replay")
        rp = f"  {DIM}replayed {rp['hits']} calls{END}" if rp else ""
        print(f"    {mark} {r['case']}{cost}{rp}")
        for f in r["failures"]:
            print(f"        {RED}{f}{END}")
    print(f"\n  {len(results) - failed}/{len(results)} cases pass" + (f"  ·  {RED}{failed} failing{END}" if failed else ""))
    if replay is None:
        print(f"  {DIM}traces saved — re-check later with no model calls:  algo eval {file} --replay{END}")
    return 1 if failed else 0


def replay_trace(trace_file, program=None, strict=True):
    """Replay one trace. Returns a dict describing what happened and what changed."""
    import algolang as al
    t = json.loads(Path(trace_file).read_text(encoding="utf-8"))
    src = program or t.get("source")
    if not src or not Path(src).exists():
        raise FileNotFoundError(f"cannot find the program for this trace ({src!r}); pass --program FILE")
    prog = al.load(src)
    changed_source = None
    if t.get("source_sha") and Path(src).exists():
        import hashlib
        changed_source = hashlib.sha256(Path(src).read_bytes()).hexdigest()[:16] != t["source_sha"]
    res = prog.replay(t, strict=strict)
    before = [c["agent"] for c in t.get("calls", [])]
    after = [c["agent"] for c in res.calls if c.get("status") not in ("blocked", "failed")]
    new_values = rt._jsonable([rt.Runtime.value(v) for v in res.values])
    return dict(trace=str(trace_file), program=src, source_changed=changed_source,
                recorded_status=t.get("status"), status=res.status, problem=res.problem,
                calls_recorded=len(before), calls_replayed=res.replay["hits"],
                misses=res.replay["misses"],
                agents_added=sorted(set(after) - set(before)), agents_removed=sorted(set(before) - set(after)),
                same_outputs=new_values == t.get("values"), recorded_values=t.get("values"), values=new_values,
                saved_tokens=(t.get("stats") or {}).get("tokens", 0), saved_cost_usd=(t.get("stats") or {}).get("cost_usd", 0))


def cli_replay(trace_file, program=None, strict=True, as_json=False):
    try:
        r = replay_trace(trace_file, program, strict)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps(r, indent=2, default=str))
    else:
        same = r["status"] == "ok" and not r["misses"] and r["same_outputs"] and not r["agents_added"] and not r["agents_removed"]
        print(f"  {NAVY}replay {Path(trace_file).name}{END}  →  {r['program']}")
        if r["source_changed"]:
            print(f"  {GOLD}the program changed since this trace was recorded{END}")
        print(f"  replayed {r['calls_replayed']}/{r['calls_recorded']} recorded calls · saved ~{r['saved_tokens']} tokens "
              f"(${r['saved_cost_usd']:.4f}) · status {r['status']}")
        for m in r["misses"]:
            print(f"  {RED}✗ {m['agent']}{END} now receives different inputs: {m['goal'][:110]}")
        for a in r["agents_added"]:
            print(f"  {GOLD}+ {a}{END} is called now but was not in the recording")
        for a in r["agents_removed"]:
            print(f"  {GOLD}− {a}{END} was called in the recording but not now")
        if r["problem"]:
            print(f"  {RED}{r['problem']}{END}")
        if not r["same_outputs"] and not r["misses"]:
            print(f"  {GOLD}outputs differ from the recording{END}")
        print(f"  {GREEN}✓ identical: same path, same outputs{END}" if same else
              f"  {RED}✗ behaviour changed — see above{END}")
        return 0 if same else 1
    return 0 if r["status"] == "ok" and not r["misses"] else 1
