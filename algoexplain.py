"""algoexplain: decision notices for the people AI decisions affect (v1.2).

    algo explain runs/traces/loan-3f2a9c1d.trace.json
    algo explain runs/traces/loan-3f2a9c1d.trace.json --html notice.html --contact cto@example.com
    algo explain programs/loan.algo --arg "app=APP-3101 ..." --json

Laws such as the EU AI Act (Article 86), the GDPR (Article 22) and India's DPDP Act give people affected by
automated decisions a right to a meaningful explanation and to human review. An audit log is evidence for an
auditor; it is not an explanation a customer, a patient or a student can read.

`algo explain` turns one recorded decision (its trace, and the run's records in the hash-chained audit log)
into a plain-language notice:

    the outcome                 what was decided, or that a person still has to decide
    how it was decided          each step in order: who assessed what, how sure it was, independent
                                assessments and where they disagreed, checks that held or failed,
                                and where a person reviewed or must review it
    reasons                     the reasons and evidence of agents that `explain`
    safeguards                  information the system was not allowed to use, personal data masking,
                                limits on cost, human review, consensus
    your rights                 human review, access, correction and appeal, with a contact
    integrity                   whether the audit records of this decision are intact (and signed)

Nothing is invented: the wording is fixed text, filled only from the trace, the audit log and the program's own
declarations; the answers it quotes are the agents' recorded answers.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

import algoruntime as rt


class ExplainError(Exception):
    pass


def _human(name):
    """CreditAnalyst → credit analyst; fraud.Panel → fraud panel."""
    name = name.split(".")[-1]
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).replace("_", " ").lower()


def _short(v, n=160):
    v = rt._jsonable(v)
    if isinstance(v, dict):
        s = ", ".join(f"{_human(k)}: {_short(x, 40)}" for k, x in v.items())
    elif isinstance(v, list):
        s = "; ".join(_short(x, 60) for x in v)
    elif isinstance(v, float):
        s = f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 10 else f"{v:,.2f}"
    else:
        s = str(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def _lower_first(w):
    return w[0].lower() + w[1:] if len(w) > 1 and w[1:2].islower() else w


def _sure(c):
    if c is None:
        return ""
    c = float(c)
    word = "very sure" if c >= 0.9 else "fairly sure" if c >= 0.75 else "unsure" if c < 0.6 else "moderately sure"
    return f"{word} ({c:.0%})"


def load_records(audit_path, run):
    p = Path(audit_path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("run") == run:
            out.append(r)
    return out


def _program_facts(trace, program=None):
    """Roles, risk purpose and disclosure from the program (an algolang Program, or the source file named in the
    trace when it is still available)."""
    src = trace.get("source")
    facts = {"roles": {}, "purpose": None, "risk": None, "disclosure": None}
    if program is not None:
        prog = getattr(program, "_prog", program)
    elif not src or not Path(src).exists():
        return facts
    else:
        try:
            import algoc
            prog, _ = algoc.load_program(Path(src).read_text(encoding="utf-8"), Path(src).name, Path(src).resolve().parent)
        except Exception:  # noqa: the notice is still useful without the source
            return facts
    facts["roles"] = {n: a.role for n, a in prog.agents.items() if a.role}
    if prog.risk:
        facts["risk"], facts["purpose"] = prog.risk[0], prog.risk[1]
    facts["disclosure"] = prog.disclosure
    return facts


def build(trace, audit_path=None, contact=None, organisation=None, program=None):
    source_program = program
    """The notice as a dictionary (rendered to Markdown, HTML or JSON)."""
    cfg = rt.load_config()
    notice_cfg = cfg.get("notice") or {}
    contact = contact or notice_cfg.get("contact")
    organisation = organisation or notice_cfg.get("organisation")
    run, program = trace.get("run"), trace.get("program")
    audit_path = Path(audit_path) if audit_path else rt.audit_dir() / f"{program}.audit.jsonl"
    recs = load_records(audit_path, run)
    facts = _program_facts(trace, source_program)

    # pair trace calls with audit records in order, by (agent, inputs digest)
    pool = {}
    for r in recs:
        if r.get("agent") and r.get("type") != "consensus":
            pool.setdefault((r["agent"], r.get("inputs_sha")), []).append(r)
    steps = []
    for c in trace.get("calls") or []:
        rec = (pool.get((c["agent"], c.get("inputs_sha"))) or [{}]).pop(0) if pool.get((c["agent"], c.get("inputs_sha"))) else {}
        role = facts["roles"].get(c["agent"])
        who = role or f"{_human(c['agent'])} agent"
        who = _lower_first(who)
        val = c.get("value")
        answer = (f"{float(val):.2f} out of 1" if rt.base_type(c.get("returns") or "") == "score"
                  and isinstance(val, (int, float)) and not isinstance(val, bool) else _short(val))
        step = dict(kind="agent", agent=c["agent"], who=who, answer=answer,
                    confidence=c.get("confidence"), status=rec.get("status", "ok"))
        con = rec.get("contracts") or {}
        if con.get("checked"):
            step["checks"] = dict(checked=con["checked"], held=con.get("held", 0),
                                  broken=[v.get("message") or v.get("contract") for v in con.get("violated") or []])
        ex = c.get("explanation") or {}
        if ex.get("reasons") or ex.get("evidence"):
            step["reasons"] = list(ex.get("reasons") or [])[:5]
            step["evidence"] = list(ex.get("evidence") or [])[:5]
        if rec.get("status") == "escalated":
            step["review"] = "sent to a person for review"
        elif rec.get("status") == "approved":
            step["review"] = "approved by a person"
        steps.append(step)
    for r in recs:                                    # v1.2 consensus: placed after its last member
        if r.get("type") != "consensus":
            continue
        last = max((i for i, s in enumerate(steps) if s["agent"] in r.get("agents", [])), default=len(steps) - 1)
        steps.insert(last + 1, dict(kind="consensus", agents=r.get("agents"), quorum=r.get("quorum"),
                                    agreed=r.get("agreed"), of=r.get("of"), reached=r.get("reached"),
                                    answer=(f"{r['value']:.2f} out of 1" if r.get("within") is not None and
                                            isinstance(r.get("value"), (int, float)) and 0 <= r["value"] <= 1
                                            else _short(r.get("value"))), confidence=r.get("confidence"),
                                    dissent=[dict(who=_lower_first(facts["roles"].get(m["agent"]) or _human(m["agent"])),
                                                  answer=_short(m.get("value"), 60))
                                             for m in r.get("members", []) if not m.get("agrees")]))

    blocked = trace.get("status") == "blocked"
    pending = [s for s in steps if s.get("status") == "escalated" or (s["kind"] == "consensus" and not s["reached"])]
    if blocked:
        outcome = dict(state="stopped", text="The system stopped before reaching a decision because a safeguard "
                                             f"was triggered: {trace.get('problem')}. A person will handle this case.")
    elif pending:
        outcome = dict(state="pending", text="No final decision has been made yet. Part of the assessment was "
                                             "passed to a person, who will make or confirm the decision.")
    else:
        outcome = dict(state="decided", text="The assessment was completed.")
    outcome["result"] = [_short(v, 400) for v in trace.get("values") or []]

    forbid, redact, budgets, human = set(), False, False, False
    for r in recs:
        pol = r.get("policy") or {}
        forbid.update(pol.get("forbid") or [])
        redact = redact or bool(pol.get("redact_pii"))
        budgets = budgets or any(k.startswith("budget") for k in pol)
        human = human or any(k in pol for k in ("human_below", "human_always", "approvals"))
    safeguards = []
    if forbid:
        safeguards.append("The system was not allowed to use: " + ", ".join(sorted(_human(f) for f in forbid))
                          + ". Mentions of these were withheld from the AI models.")
    if redact:
        safeguards.append("Personal data (names, phone numbers, e-mail addresses, ID and account numbers) was "
                          "masked before any AI model saw it.")
    if human:
        safeguards.append("Answers below a set level of certainty, or of a kind that always needs a person, "
                          "are reviewed by a person before they are used.")
    if any(s["kind"] == "consensus" for s in steps):
        safeguards.append("Key assessments were made independently by several AI agents, and counted only if "
                          "enough of them agreed.")
    if any(s.get("checks") for s in steps):
        safeguards.append("Every answer was checked against fixed rules before it was used.")
    if budgets:
        safeguards.append("Each step ran within fixed limits on cost and size.")

    integrity = dict(audit=str(audit_path), records=len(recs))
    if recs:
        v = rt.verify_audit(audit_path)
        integrity.update(intact=bool(v.get("ok")), signed=bool(v.get("signed")),
                         first_hash=recs[0].get("hash"), last_hash=recs[-1].get("hash"))
    rights = ["Ask for a person to review this decision.", "Ask to see the information that was used about you, "
              "and have it corrected if it is wrong.", "Contest the decision and explain your point of view."]
    return dict(title="Notice of an AI-assisted decision", reference=run, program=program,
                date=(trace.get("recorded") or "").replace("T", " "), purpose=facts["purpose"], risk=facts["risk"],
                disclosure=facts["disclosure"], organisation=organisation, contact=contact,
                inputs=sorted((trace.get("inputs") or {}).keys()), outcome=outcome, steps=steps,
                safeguards=safeguards, rights=rights, integrity=integrity)


def _step_text(s, i):
    if s["kind"] == "consensus":
        head = (f"{s['of']} independent assessments were compared; {s['agreed']} agreed, {s['quorum']} needed. "
                + (f"Agreed answer: {s['answer']}, {_sure(s['confidence'])}." if s["reached"] else
                   "Not enough agreed, so a person will decide."))
        if s["dissent"]:
            head += " Disagreed: " + "; ".join(f"{d['who']} ({d['answer']})" for d in s["dissent"]) + "."
        return head
    t = f"The {s['who']} gave {s['answer']}"
    if s.get("confidence") is not None:
        t += f", {_sure(s['confidence'])}"
    t += "."
    if s.get("checks"):
        c = s["checks"]
        t += (f" All {c['checked']} rule check(s) held." if not c["broken"] else
              f" Rule check(s) failed: {'; '.join(c['broken'])}.")
    if s.get("review"):
        t += f" This answer was {s['review']}."
    return t


def to_markdown(n):
    L = [f"# {n['title']}", "", f"**Reference** {n['reference']} · **Date** {n['date']}"
         + (f" · **Organisation** {n['organisation']}" if n["organisation"] else ""), ""]
    if n["purpose"]:
        L += [f"**Purpose:** {n['purpose']}", ""]
    if n["disclosure"]:
        L += [f"> {n['disclosure']}", ""]
    L += ["## The outcome", "", n["outcome"]["text"], ""]
    L += [f"- {r}" for r in n["outcome"]["result"]] + [""]
    if n["inputs"]:
        L += ["## Information used", "", "The information you provided for: " + ", ".join(n["inputs"]) + ".", ""]
    L += ["## How it was decided", ""] + [f"{i}. {_step_text(s, i)}" for i, s in enumerate(n["steps"], 1)] + [""]
    reasons = [(s["who"], r) for s in n["steps"] if s.get("reasons") for r in s["reasons"]]
    if reasons:
        L += ["## Reasons given", ""] + [f"- **{w}:** {r}" for w, r in reasons] + [""]
    if n["safeguards"]:
        L += ["## Safeguards", ""] + [f"- {s}" for s in n["safeguards"]] + [""]
    L += ["## Your rights", ""] + [f"- {r}" for r in n["rights"]]
    L += ["", f"Contact: **{n['contact']}**, quoting reference {n['reference']}." if n["contact"] else
          "", "Contact the organisation that made this decision, quoting the reference above." if not n["contact"] else ""]
    g = n["integrity"]
    L += ["", "## Integrity", ""]
    if g["records"]:
        L.append(f"This decision is recorded in {g['records']} audit record(s), "
                 f"{'intact' if g['intact'] else 'NOT intact'}{' and digitally signed' if g['signed'] else ''}. "
                 f"First record {g['first_hash'][:16]}…, last {g['last_hash'][:16]}….")
    else:
        L.append("No audit records were found for this decision.")
    return "\n".join(x for x in L if x is not None) + "\n"


def to_html(n):
    e = html.escape
    steps = "".join(f"<li>{e(_step_text(s, i))}</li>" for i, s in enumerate(n["steps"], 1))
    res = "".join(f"<li>{e(r)}</li>" for r in n["outcome"]["result"])
    safe = "".join(f"<li>{e(s)}</li>" for s in n["safeguards"])
    rights = "".join(f"<li>{e(r)}</li>" for r in n["rights"])
    reasons = "".join(f"<li><b>{e(s['who'])}:</b> {e(r)}</li>" for s in n["steps"] if s.get("reasons") for r in s["reasons"])
    g = n["integrity"]
    integ = (f"{g['records']} audit record(s), {'intact' if g['intact'] else 'NOT intact'}"
             f"{', digitally signed' if g['signed'] else ''}. Last record <code>{e(g['last_hash'][:24])}…</code>"
             if g["records"] else "No audit records were found for this decision.")
    state = {"decided": "#2F6B3A", "pending": "#C9A227", "stopped": "#7A1020"}[n["outcome"]["state"]]
    contact = (f"Contact <b>{e(n['contact'])}</b>, quoting reference <b>{e(n['reference'])}</b>." if n["contact"]
               else "Contact the organisation that made this decision, quoting the reference above.")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(n['title'])} · {e(n['reference'])}</title>
<style>
body{{margin:0;background:#F6F8FB;color:#1B1B1B;font:16px/1.55 Calibri,"Segoe UI",Arial,sans-serif}}
main{{max-width:760px;margin:0 auto;background:#fff;min-height:100vh}}
header{{background:#0B1F3A;color:#fff;padding:28px 32px;border-bottom:4px solid #C9A227}}
header h1{{margin:0 0 6px;font:700 26px/1.2 Cambria,Georgia,serif}} header p{{margin:0;color:#E8EDF5;font-size:14px}}
section{{padding:6px 32px}} h2{{color:#0B1F3A;font:700 19px Cambria,Georgia,serif;margin:22px 0 8px}}
.outcome{{border-left:6px solid {state};background:#F3EFE1;padding:12px 16px;border-radius:4px}}
blockquote{{margin:16px 0 0;padding:10px 14px;background:#E8EDF5;border-radius:4px;color:#1D3B66}}
li{{margin:4px 0}} code{{font-size:13px}} footer{{padding:18px 32px 30px;color:#5A6270;font-size:13px}}
</style></head><body><main>
<header><h1>{e(n['title'])}</h1><p>Reference {e(n['reference'])} · {e(n['date'])}{(' · ' + e(n['organisation'])) if n['organisation'] else ''}</p></header>
<section>{f"<p><b>Purpose:</b> {e(n['purpose'])}</p>" if n['purpose'] else ''}{f"<blockquote>{e(n['disclosure'])}</blockquote>" if n['disclosure'] else ''}
<h2>The outcome</h2><div class="outcome"><p>{e(n['outcome']['text'])}</p><ul>{res}</ul></div>
{f"<h2>Information used</h2><p>The information you provided for: {e(', '.join(n['inputs']))}.</p>" if n['inputs'] else ''}
<h2>How it was decided</h2><ol>{steps}</ol>
{f"<h2>Reasons given</h2><ul>{reasons}</ul>" if reasons else ''}
{f"<h2>Safeguards</h2><ul>{safe}</ul>" if safe else ''}
<h2>Your rights</h2><ul>{rights}</ul><p>{contact}</p>
<h2>Integrity</h2><p>{integ}</p></section>
<footer>Generated by AlgoLang from the decision's trace and its hash-chained audit log. The wording of this notice is fixed text; only the quoted answers come from the AI agents.</footer>
</main></body></html>
"""


def cli(target, args=(), flow=None, audit=None, contact=None, organisation=None, as_json=False, html_out=None,
        md_out=None):
    import tempfile
    p = Path(target)
    if not p.exists():
        print(f"✗ no such file: {target}")
        return 2
    try:
        if p.suffix == ".algo":                         # run it now, traced, then explain that run
            import algolang as al
            prog = al.load(str(p))
            inputs = {}
            for a in args or []:
                if "=" not in a:
                    raise ExplainError(f"--arg needs NAME=VALUE (got {a!r})")
                k, v = a.split("=", 1)
                inputs[k.strip()] = v
            tmp = Path(tempfile.mkdtemp(prefix="algo-explain-"))
            res = prog.run(quiet=True, audit_dir=str(tmp), trace=True, flow=flow or "main", **inputs)
            trace = json.loads(Path(res.trace_path).read_text(encoding="utf-8"))
            audit = audit or res.audit_path
            program = prog
        else:
            program = None
            trace = json.loads(p.read_text(encoding="utf-8"))
            if "calls" not in trace or "run" not in trace:
                raise ExplainError(f"{target} is not an AlgoLang trace (record one with `algo run … --trace`)")
            if audit is None:                            # a trace normally sits in <audit_dir>/traces/
                guess = p.resolve().parent.parent / f"{trace.get('program')}.audit.jsonl"
                audit = guess if guess.exists() else None
        notice = build(trace, audit, contact=contact, organisation=organisation, program=program)
    except (ExplainError, TypeError, KeyError) as e:
        print(f"✗ {e}")
        return 2
    if as_json:
        print(json.dumps(notice, indent=1, ensure_ascii=False, default=str))
    elif not html_out and not md_out:
        print(to_markdown(notice))
    if html_out:
        Path(html_out).write_text(to_html(notice), encoding="utf-8")
        print(f"✓ notice → {html_out}")
    if md_out:
        Path(md_out).write_text(to_markdown(notice), encoding="utf-8")
        print(f"✓ notice → {md_out}")
    return 0
