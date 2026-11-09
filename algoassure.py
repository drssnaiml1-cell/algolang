"""algoassure — evidence that an AlgoLang system is trustworthy (v0.4).

    algo card program.algo [--out DIR] [--check]     AI system card (Markdown + JSON), generated from the source
    algo trust report PATH [--html FILE] [--json]     scorecard of 10 trustworthy-AI properties with evidence
    algo evidence export program.algo --out pack.zip  source, config, card, eval results, audit logs, traces and
                                                      the trust report in one signed archive
    algo evidence verify pack.zip                     check every file's hash, the signature and the audit chains

Cards and reports are generated from the code, never written by hand, so they cannot drift from what the
system does. They document safeguards and test evidence; they do not by themselves make a system compliant
with any law or standard.
"""
from __future__ import annotations

import hashlib
import html
import json
import time
import zipfile
from pathlib import Path

import algoruntime as rt

NAVY, GOLD = "#0e2140", "#c9a227"

# ───────────────────────────── system cards ─────────────────────────────
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tool_kind(name, prog):
    if name.startswith("circuit."):
        return "quantum circuit"
    if name in prog.mcp_tools:
        return f"MCP server '{prog.mcp_tools[name]}'"
    if name.startswith(("quantum.", "pqc.")):
        return "built-in quantum"
    if name in ("calc.eval", "file.read", "kb.search"):
        return "built-in"
    return "organisation plugin"


def _oversight(pol):
    if pol.get("human_always"):
        how = "every result is reviewed"
    elif pol.get("human_below") is not None:
        how = f"reviewed when confidence < {pol['human_below']}"
    elif pol.get("approvals"):
        how = "every result is reviewed"
    else:
        return None
    n = int(pol.get("approvals") or 1)
    return how + (f" by {n} different people" if n > 1 else "")


def card_data(program):
    """The AI system card of a compiled Program, as a dict. Deterministic: no timestamps."""
    p = program._prog
    src = Path(program.path)
    level, purpose = (p.risk[0], p.risk[1]) if p.risk else ("undeclared", "")
    org = (rt.load_config().get("policy") or {})
    agents = []
    for a in sorted(p.agents.values(), key=lambda a: a.name):
        pol = dict(a.policy)
        if org.get("min_human_below") is not None:              # the organisation's gate applies to every agent
            pol["human_below"] = max(pol.get("human_below", 0), org["min_human_below"])
        if org.get("redact_pii"):
            pol["redact_pii"] = True
        forbid = sorted(set(pol.get("forbid", [])) | set(org.get("forbid") or []))
        agents.append(dict(
            name=a.name, role=a.role or "", returns=a.returns, model=a.model or "default (algo.config.json)",
            tools=list(a.uses), human_oversight=_oversight(pol), explain=pol.get("explain"),
            redact_pii=bool(pol.get("redact_pii")), forbidden_attributes=forbid,
            samples=pol.get("samples") if a.returns.startswith("uncertain<") else None,
            budgets={k: pol[k] for k in ("budget_tokens", "budget_cost_usd", "budget_cost_inr", "budget_energy_wh")
                     if k in pol},
            imported_from=a.origin))
    tools = [dict(name=t, kind=_tool_kind(t, p), trusted=t not in p.untrusted,
                  description=(rt.TOOLS[t].description if t in rt.TOOLS else "")) for t in sorted(p.tools)]
    fair, robust, explained, cases = [], [], False, 0
    for ev in p.evals:
        for c in ev.cases:
            cases += 1
            for kind, op, val in c.expects:
                if kind == "fair":
                    fair.append(dict(eval=ev.name, case=c.name, attribute=op, values=val))
                elif kind == "robust":
                    robust.append(dict(eval=ev.name, case=c.name, perturbations=val[0], consistency=f"{op} {val[1]:g}"))
                elif kind == "explained":
                    explained = True
    oversight = [f"{a['name']}: {a['human_oversight']}" for a in agents if a["human_oversight"]]
    redacted = [a["name"] for a in agents if a["redact_pii"]]
    forbid_all = sorted({x for a in agents for x in a["forbidden_attributes"]})
    retention = {}
    for a in p.agents.values():
        for what in ("audit", "traces"):
            v = a.policy.get(f"retain_{what}_days")
            if v:
                retention[what] = min(retention.get(what, v), v)
    lim = ["Generated from the source code: it documents design-time safeguards and test coverage, "
           "not measured real-world performance."]
    lim.append("Offline evals use a deterministic mock model; repeat them with `algo eval --live` before deployment.")
    if forbid_all:
        lim.append("Protected attributes are withheld by keyword. Proxies such as names, postcodes or schools can "
                   "still carry them; counterfactual fairness tests measure the effect.")
    if not fair:
        lim.append("Fairness has not been tested (no `expect fair` case).")
    if not robust:
        lim.append("Robustness has not been tested (no `expect robust` case).")
    if p.untrusted:
        lim.append("Untrusted tool output is fenced and scanned by pattern; no scanner catches every injection.")
    if not oversight:
        lim.append("No person reviews this system's results.")
    if any(t.startswith(("quantum.", "circuit.")) for t in p.tools):
        lim.append("Quantum results come from a simulator unless a hardware backend is configured.")
    if redacted and len(redacted) < len(agents):
        lim.append("Personal data is masked for some agents only: " + ", ".join(redacted) + ".")
    return {
        "card": "AlgoLang AI system card", "card_version": 1,
        "program": program.name, "source": src.name, "source_sha256": _sha(src.read_bytes().replace(b"\r\n", b"\n")) if src.exists() else None,   # same on every OS
        "purpose": purpose, "risk_level": level, "disclosure": p.disclosure,
        "flows": [dict(name=f.name, inputs=[x.name for x in f.params]) for f in p.flows.values()],
        "agents": agents, "tools": tools,
        "streams": [dict(name=s.name, flow=s.flow, source=s.source, bus=s.bus) for s in p.streams],
        "circuits": [dict(name=c.name, qubits=c.qubits) for c in p.circuits.values()],
        "human_oversight": oversight,
        "data_protection": dict(redact_pii=("all agents" if redacted and len(redacted) == len(agents) else
                                            ("some agents" if redacted else "no agents")),
                                forbidden_attributes=forbid_all, retention_days=retention),
        "evaluation": dict(cases=cases, fairness=fair, robustness=robust, explanations_checked=explained),
        "limitations": lim,
    }


def card_markdown(c):
    L = [f"# AI system card: {c['program']}", "",
         f"_Generated by AlgoLang from `{c['source']}` (sha256 `{(c['source_sha256'] or '')[:16]}`). "
         "Do not edit: run `algo card` again._", "",
         "| | |", "|---|---|",
         f"| **Purpose** | {c['purpose'] or '—'} |",
         f"| **Risk level** | {c['risk_level']} |",
         f"| **AI disclosure** | {c['disclosure'] or '—'} |",
         f"| **Flows** | {', '.join(f['name'] + '(' + ', '.join(f['inputs']) + ')' for f in c['flows'])} |", ""]
    L += ["## Agents", "", "| Agent | Role | Returns | Tools | Human oversight | Explains | Masks PII | Withholds |",
          "|---|---|---|---|---|---|---|---|"]
    for a in c["agents"]:
        L.append(f"| {a['name']} | {a['role'] or '—'} | `{a['returns']}`"
                 + (f" ×{a['samples']}" if a['samples'] else "")
                 + f" | {', '.join(a['tools']) or '—'} | {a['human_oversight'] or '—'} | {a['explain'] or '—'} | "
                 f"{'yes' if a['redact_pii'] else 'no'} | {', '.join(a['forbidden_attributes']) or '—'} |")
    L += ["", "## Tools", "", "| Tool | Kind | Trusted | Description |", "|---|---|---|---|"]
    for t in c["tools"]:
        L.append(f"| {t['name']} | {t['kind']} | {'yes' if t['trusted'] else '**no** (fenced)'} | {t['description'] or '—'} |")
    dp = c["data_protection"]
    L += ["", "## Data protection", "",
          f"- Personal data masked before model calls: **{dp['redact_pii']}**",
          f"- Protected attributes withheld: {', '.join(dp['forbidden_attributes']) or 'none'}",
          f"- Retention: {', '.join(f'{k} {v} days' for k, v in dp['retention_days'].items()) or 'organisation default'}",
          "", "## Human oversight", ""]
    L += [f"- {h}" for h in c["human_oversight"]] or ["- none"]
    ev = c["evaluation"]
    L += ["", "## Evaluation", "", f"- {ev['cases']} eval case(s)"]
    L += [f"- Fairness: `{f['eval']}` / \"{f['case']}\" across {f['attribute']} ({', '.join(f['values'])})" for f in ev["fairness"]]
    L += [f"- Robustness: `{r['eval']}` / \"{r['case']}\" to {', '.join(r['perturbations'])}, consistency {r['consistency']}"
          for r in ev["robustness"]]
    if ev["explanations_checked"]:
        L.append("- Explanations are checked for grounding (`expect explained`)")
    L += ["", "## Known limitations", ""] + [f"- {x}" for x in c["limitations"]] + [""]
    return "\n".join(L)


def write_card(program, out_dir=None):
    c = card_data(program)
    out = Path(out_dir) if out_dir else Path(program.base_dir)
    out.mkdir(parents=True, exist_ok=True)
    jp, mp = out / f"{program.name}.card.json", out / f"{program.name}.card.md"
    jp.write_text(json.dumps(c, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    mp.write_text(card_markdown(c), encoding="utf-8")
    return jp, mp


def cli_card(files, out=None, check=False):
    import algolang as al
    stale = 0
    for f in files:
        prog = al.load(f)
        c = card_data(prog)
        out_dir = Path(out) if out else Path(f).resolve().parent
        jp = out_dir / f"{prog.name}.card.json"
        if check:
            old = json.loads(jp.read_text(encoding="utf-8")) if jp.exists() else None
            if old != json.loads(json.dumps(c, ensure_ascii=False)):
                stale += 1
                print(f"  ✗ {jp} is {'missing' if old is None else 'out of date'}: run  algo card {f}" + (f" --out {out}" if out else ""))
            else:
                print(f"  ✓ {jp.name} matches {Path(f).name}")
            continue
        jp, mp = write_card(prog, out_dir)
        print(f"  ✓ {mp}  ·  {jp.name}  ({c['risk_level']} risk, {len(c['agents'])} agents)")
    return 1 if stale else 0


# ───────────────────────────── trust report ─────────────────────────────
PROPERTIES = [
    # key, title, NIST AI RMF function, EU AI Act articles
    ("fairness", "Fairness", "Measure", "Art. 10"),
    ("robustness", "Robustness", "Measure", "Art. 15"),
    ("transparency", "Transparency", "Map", "Art. 11, 13, 50"),
    ("explainability", "Explainability", "Measure", "Art. 13, 86"),
    ("privacy", "Privacy", "Manage", "Art. 10"),
    ("security", "Security", "Manage", "Art. 15"),
    ("oversight", "Human oversight", "Manage", "Art. 14"),
    ("accountability", "Accountability", "Govern", "Art. 12"),
    ("risk", "Risk-based governance", "Govern", "Art. 9"),
    ("assurance", "Assurance", "Measure", "Art. 17"),
]


def _status(ok, required=False, tested=True):
    if not tested:
        return "gap" if required else "not tested"
    return "met" if ok else "fail"


def assess(program, run_evals=True, audit_dir=None):
    """Evaluate one program against the ten properties. Returns a dict with evidence for each."""
    import algoeval
    c = card_data(program)
    p = program._prog
    high = c["risk_level"] == "high"
    results = algoeval.run_evals(program, audit_dir=audit_dir) if (run_evals and p.evals) else []
    fair = [f for r in results for f in ((r.get("trust") or {}).get("fairness") or [])]
    rob = [(r.get("trust") or {}).get("robustness") for r in results if (r.get("trust") or {}).get("robustness")]
    cfg = rt.load_config()
    out = {}

    out["fairness"] = dict(status=_status(all(f["passed"] for f in fair), high, bool(fair)),
                           detail=(f"{sum(f['passed'] for f in fair)}/{len(fair)} counterfactual tests keep the same "
                                   f"decision (largest score gap {max([f['score_gap'] for f in fair] or [0]):.3f})"
                                   if fair else "no `expect fair` test"),
                           evidence=[f"{f['attribute']}: {', '.join(f['values'])}" for f in fair])
    out["robustness"] = dict(status=_status(all(r["passed"] for r in rob), high, bool(rob)),
                             detail=(f"consistency {min(r['consistency'] for r in rob):.2f} (lowest) over "
                                     f"{sum(r['variants'] for r in rob)} perturbed inputs" if rob else "no `expect robust` test"),
                             evidence=[f"{', '.join(r['perturbations'])}: {r['consistency']:.2f} {r['required']}" for r in rob])
    disclosed = bool(c["disclosure"]) or c["risk_level"] in ("minimal", "undeclared")
    out["transparency"] = dict(status="met" if disclosed else "fail",
                               detail="system card generated from source" + ("; AI use disclosed" if c["disclosure"] else ""),
                               evidence=[f"{program.name}.card.md"] + ([c["disclosure"]] if c["disclosure"] else []))
    exp_agents = [a["name"] for a in c["agents"] if a["explain"]]
    exp_bad = [f for r in results for f in r["failures"] if "explanation" in f]
    out["explainability"] = dict(status=("fail" if exp_bad else ("met" if exp_agents else ("gap" if high else "not required"))),
                                 detail=(f"{len(exp_agents)} agent(s) explain their results"
                                         + ("; grounding checked" if c["evaluation"]["explanations_checked"] else "")
                                         if exp_agents else "no agent explains its results"),
                                 evidence=exp_agents)
    red = c["data_protection"]["redact_pii"]
    out["privacy"] = dict(status="met" if red == "all agents" else ("gap" if high else ("partial" if red == "some agents" else "not required")),
                          detail=f"personal data masked for {red}; withheld attributes: "
                                 f"{', '.join(c['data_protection']['forbidden_attributes']) or 'none'}",
                          evidence=[f"retain {k} {v} days" for k, v in c["data_protection"]["retention_days"].items()])
    pinned = [s for s, v in (cfg.get("mcp_servers") or {}).items() if v.get("sha256")]
    sec_ev = [f"untrusted (fenced): {t}" for t in sorted(p.untrusted)]
    if (cfg.get("policy") or {}).get("allowed_tools") is not None:
        sec_ev.append("organisation tool allow-list")
    sec_ev += [f"MCP server pinned: {s}" for s in pinned]
    unpinned = [s for s in set(p.mcp_tools.values()) if s not in pinned]
    out["security"] = dict(status="fail" if unpinned and high else ("met" if sec_ev else "not required"),
                           detail=("MCP servers not pinned: " + ", ".join(unpinned)) if unpinned else
                           ("tool output from untrusted sources is fenced" if p.untrusted else "only trusted tools"),
                           evidence=sec_ev)
    out["oversight"] = dict(status="met" if c["human_oversight"] else ("fail" if high else "not required"),
                            detail=f"{len(c['human_oversight'])} oversight point(s)", evidence=c["human_oversight"])
    signing = bool((cfg.get("audit") or {}).get("sign"))
    adir = Path(audit_dir) if audit_dir else rt.audit_dir()
    log = adir / f"{program.name}.audit.jsonl"
    v = rt.verify_audit(log) if log.exists() else None
    acc_ok = signing and (v is None or v["ok"])
    out["accountability"] = dict(status="met" if acc_ok else ("fail" if (v and not v["ok"]) or high else "partial"),
                                 detail=("audit records signed with Ed25519" if signing else "hash-chained audit (unsigned)")
                                 + (f"; {log.name}: {v['records']} records verified" if v and v["ok"] else
                                    (f"; {log.name}: {v['reason']}" if v else "")),
                                 evidence=[str(log)] if log.exists() else [])
    out["risk"] = dict(status="met" if p.risk else "gap",
                       detail=(f"declared {c['risk_level']} risk and compiles under its rules" if p.risk else "risk level not declared"),
                       evidence=[c["purpose"]] if c["purpose"] else [])
    passed = sum(r["passed"] for r in results)
    out["assurance"] = dict(status="met" if results and passed == len(results) else ("fail" if results else "gap"),
                            detail=f"{passed}/{len(results)} eval cases pass" if results else "no eval cases",
                            evidence=[f"{r['eval']} / {r['case']}: {'pass' if r['passed'] else 'FAIL'}" for r in results])
    applicable = [k for k, *_ in PROPERTIES if out[k]["status"] not in ("not required",)]
    met = [k for k in applicable if out[k]["status"] == "met"]
    return dict(program=program.name, source=str(program.path), risk_level=c["risk_level"], purpose=c["purpose"],
                properties=out, met=len(met), applicable=len(applicable),
                score=round(len(met) / len(applicable), 3) if applicable else 1.0)


def report(paths, run_evals=True):
    import algolang as al
    files = []
    for p in paths:
        p = Path(p)
        files += sorted(p.rglob("*.algo")) if p.is_dir() else [p]
    files = [f for f in files if "runs" not in f.parts and "build" not in f.parts]
    progs = []
    for f in files:
        prog = al.load(f)
        if "main" not in prog._prog.flows:
            continue
        progs.append(assess(prog, run_evals=run_evals, audit_dir=str(Path(f).resolve().parent / "runs" / "eval")))
    return dict(report="AlgoLang trust report", algolang=rt.VERSION, generated=time.strftime("%Y-%m-%d %H:%M"),
                programs=progs,
                frameworks="Evidence is mapped to NIST AI RMF functions and EU AI Act articles. It supports, but does "
                           "not replace, an organisation's own risk management and conformity assessment.")


ICON = {"met": "✓", "fail": "✗", "gap": "!", "partial": "◐", "not tested": "–", "not required": "·"}
COLOR = {"met": "#2f9e62", "fail": "#d14b3c", "gap": "#d99a1e", "partial": "#d99a1e", "not tested": "#8a93a8",
         "not required": "#8a93a8"}


def report_html(rep):
    e = html.escape
    cards = []
    for pr in rep["programs"]:
        rows = []
        for key, title, nist, eu in PROPERTIES:
            r = pr["properties"][key]
            ev = "".join(f"<li>{e(str(x))}</li>" for x in r["evidence"][:6])
            rows.append(f"<tr><td><span class='pill' style='background:{COLOR[r['status']]}'>{ICON[r['status']]} "
                        f"{e(r['status'])}</span></td><td><b>{e(title)}</b><div class='d'>{e(r['detail'])}</div>"
                        f"{'<ul>' + ev + '</ul>' if ev else ''}</td><td class='m'>{e(nist)}</td><td class='m'>{e(eu)}</td></tr>")
        pct = int(pr["score"] * 100)
        cards.append(f"""<section class="card"><header><div><h2>{e(pr['program'])}</h2>
<div class="sub">{e(pr['purpose'] or 'purpose not stated')}</div></div>
<div class="score"><div class="ring" style="--p:{pct}"><span>{pr['met']}/{pr['applicable']}</span></div>
<div class="lvl lvl-{e(pr['risk_level'])}">{e(pr['risk_level'])} risk</div></div></header>
<table><thead><tr><th>Status</th><th>Property and evidence</th><th>NIST AI RMF</th><th>EU AI Act</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></section>""")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AlgoLang trust report</title><style>
:root{{--navy:{NAVY};--gold:{GOLD};--ink:#1b2333;--muted:#5b6478;--line:#e3e6ee;--bg:#f6f4ee}}
*{{box-sizing:border-box}}body{{margin:0;font:15px/1.5 "Segoe UI",Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}}
.top{{background:linear-gradient(120deg,#081428,var(--navy) 60%,#163363);color:#f4f1e8;padding:36px 20px 28px;border-bottom:4px solid var(--gold)}}
.top h1{{margin:0;font-size:28px}}.top p{{margin:6px 0 0;color:#c9cfe0;max-width:900px}}.wrap{{max-width:1080px;margin:0 auto;padding:0 16px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:14px;margin:22px 0;overflow:hidden}}
.card header{{display:flex;justify-content:space-between;gap:16px;align-items:center;padding:18px 20px;border-bottom:1px solid var(--line)}}
h2{{margin:0;font-size:20px;color:var(--navy)}}.sub{{color:var(--muted)}}.score{{display:flex;align-items:center;gap:12px}}
.ring{{--p:0;width:64px;height:64px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(var(--gold) calc(var(--p)*1%),#e8e3d2 0)}}
.ring span{{background:#fff;border-radius:50%;width:48px;height:48px;display:grid;place-items:center;font-weight:700;color:var(--navy)}}
.lvl{{padding:4px 10px;border-radius:99px;font-size:12px;font-weight:700;text-transform:uppercase;background:#eef0f5;color:var(--navy)}}
.lvl-high{{background:#fbe3df;color:#a33024}}.lvl-limited{{background:#fbf0d8;color:#8a5a00}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:10px 14px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);background:#fafaf7}}
.pill{{display:inline-block;color:#fff;border-radius:99px;padding:2px 10px;font-size:12px;font-weight:700;white-space:nowrap}}
.d{{color:var(--muted)}}ul{{margin:4px 0 0;padding-left:18px;color:var(--muted);font-size:13px}}.m{{white-space:nowrap;color:var(--navy);font-size:13px}}
footer{{color:var(--muted);font-size:13px;padding:10px 0 40px}}
@media (max-width:700px){{.card header{{flex-direction:column;align-items:flex-start}}th:nth-child(3),td:nth-child(3),th:nth-child(4),td:nth-child(4){{display:none}}}}
</style></head><body><div class="top"><div class="wrap"><h1>AlgoLang trust report</h1>
<p>{len(rep['programs'])} program(s) · AlgoLang {e(rep['algolang'])} · generated {e(rep['generated'])}. {e(rep['frameworks'])}</p></div></div>
<div class="wrap">{''.join(cards)}<footer>AlgoProfessor AI R&amp;D Solutions · www.algoprofessor.com</footer></div></body></html>"""


def cli_report(paths, html_out=None, as_json=False, no_evals=False):
    rep = report(paths, run_evals=not no_evals)
    if as_json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        for pr in rep["programs"]:
            print(f"\n  {pr['program']}  ({pr['risk_level']} risk)  {pr['met']}/{pr['applicable']} properties met")
            for key, title, nist, eu in PROPERTIES:
                r = pr["properties"][key]
                print(f"    {ICON[r['status']]} {title:<22} {r['status']:<13} {r['detail'][:70]}")
    if html_out:
        Path(html_out).write_text(report_html(rep), encoding="utf-8")
        if not as_json:
            print(f"\n  report → {html_out}")
    bad = sum(1 for pr in rep["programs"] for r in pr["properties"].values() if r["status"] == "fail")
    return 1 if bad else 0


# ───────────────────────────── evidence packs ─────────────────────────────
def export(file, out, run_evals=True):
    """Bundle everything an auditor needs for one program into a signed zip. Returns the manifest."""
    import algolang as al
    import algotrust
    prog = al.load(file)
    base = Path(prog.base_dir)
    files: dict[str, bytes] = {}
    src = Path(prog.path)
    files[f"source/{src.name}"] = src.read_bytes()
    for imp in prog._prog.imports:
        ip = Path(imp)
        if ip.exists():
            files[f"source/imports/{ip.name}"] = ip.read_bytes()
    cp = rt.config_path()
    if cp:
        files["config/algo.config.json"] = Path(cp).read_bytes()
    c = card_data(prog)
    files[f"card/{prog.name}.card.json"] = (json.dumps(c, indent=2, ensure_ascii=False) + "\n").encode()
    files[f"card/{prog.name}.card.md"] = card_markdown(c).encode()
    eval_dir = base / "runs" / "eval"
    rep = dict(report="AlgoLang trust report", algolang=rt.VERSION, generated=time.strftime("%Y-%m-%d %H:%M"),
               programs=[assess(prog, run_evals=run_evals, audit_dir=str(eval_dir))],
               frameworks="Evidence mapped to NIST AI RMF functions and EU AI Act articles.")
    files["trust/report.json"] = json.dumps(rep, indent=2, ensure_ascii=False).encode()
    files["trust/report.html"] = report_html(rep).encode()
    for d, label in ((rt.audit_dir(), "audit"), (eval_dir, "audit/eval")):
        log = Path(d) / f"{prog.name}.audit.jsonl"
        if log.exists():
            files[f"{label}/{log.name}"] = log.read_bytes()
        q = Path(d) / "review_queue.jsonl"
        if q.exists():
            files[f"{label}/review_queue.jsonl"] = q.read_bytes()
    tr = base / "runs" / "traces" / "eval" / prog.name
    for t in sorted(tr.rglob("*.trace.json")) if tr.exists() else []:
        files[f"traces/{t.relative_to(tr).as_posix()}"] = t.read_bytes()
    keys, pinned = algotrust.trusted_keys()
    s = algotrust.signer()
    if s:
        files["keys/public.json"] = json.dumps({"algorithm": "Ed25519", "kid": s[2], "public": s[1].hex(),
                                                "pinned_in_config": pinned}, indent=1).encode()
    manifest = {"pack": "AlgoLang evidence pack", "pack_version": 1, "algolang": rt.VERSION, "program": prog.name,
                "risk_level": c["risk_level"], "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "files": {k: _sha(v) for k, v in sorted(files.items())}}
    mbytes = json.dumps(manifest, indent=1, sort_keys=True).encode()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in sorted(files.items()):
            z.writestr(k, v)
        z.writestr("manifest.json", mbytes)
        if s:
            z.writestr("manifest.sig", json.dumps({"kid": s[2], "sig": algotrust.ed25519_sign(s[0], mbytes).hex()}))
    return manifest


def verify(pack):
    """Check an evidence pack. Returns (ok, list of findings)."""
    import algotrust
    findings, ok = [], True
    with zipfile.ZipFile(pack) as z:
        names = set(z.namelist())
        if "manifest.json" not in names:
            return False, ["no manifest.json"]
        mbytes = z.read("manifest.json")
        man = json.loads(mbytes)
        for name, digest in man["files"].items():
            if name not in names:
                ok = False
                findings.append(f"✗ missing {name}")
            elif _sha(z.read(name)) != digest:
                ok = False
                findings.append(f"✗ {name} was changed after the pack was made")
        extra = names - set(man["files"]) - {"manifest.json", "manifest.sig"}
        for name in sorted(extra):
            ok = False
            findings.append(f"✗ {name} was added after the pack was made")
        keys = {}
        if "keys/public.json" in names:
            k = json.loads(z.read("keys/public.json"))
            keys[k["kid"]] = bytes.fromhex(k["public"])
        pinned, is_pinned = algotrust.trusted_keys()
        if is_pinned:
            keys = {kid: pub for kid, pub in keys.items() if kid in pinned} or pinned
        if "manifest.sig" in names:
            sig = json.loads(z.read("manifest.sig"))
            pub = keys.get(sig["kid"])
            if pub is None or not algotrust.ed25519_verify(pub, mbytes, bytes.fromhex(sig["sig"])):
                ok = False
                findings.append("✗ manifest signature is not valid" + ("" if pub else " (unknown key)"))
            else:
                findings.append(f"✓ manifest signed by key {sig['kid']}" + (" (pinned)" if is_pinned else ""))
        else:
            findings.append("! pack is not signed (turn on \"audit\": {\"sign\": true})")
        for name in sorted(n for n in names if n.endswith(".jsonl") and n.startswith("audit/")):
            data = z.read(name)
            import tempfile
            with tempfile.NamedTemporaryFile("wb", suffix=".jsonl", delete=False) as fh:
                fh.write(data)
                tmp = Path(fh.name)
            try:
                r = rt.verify_audit(tmp, keys=keys)
            finally:
                tmp.unlink(missing_ok=True)
            if r["ok"]:
                findings.append(f"✓ {name}: {r['records']} records, chain intact" + (f", {r['signed']} signed" if r["signed"] else ""))
            else:
                ok = False
                findings.append(f"✗ {name}: line {r['first_bad_line']}: {r['reason']}")
        if ok:
            findings.insert(0, f"✓ {len(man['files'])} files match the manifest ({man['program']}, {man['risk_level']} risk, "
                               f"made {man['created']})")
    return ok, findings


def cli_evidence(action, target, out=None, no_evals=False):
    if action == "export":
        out = out or f"{Path(target).stem}.evidence.zip"
        man = export(target, out, run_evals=not no_evals)
        print(f"  ✓ evidence pack → {out}  ({len(man['files'])} files, {man['risk_level']} risk)")
        print(f"    check it with:  algo evidence verify {out}")
        return 0
    ok, findings = verify(target)
    for f in findings:
        print("  " + f)
    print(f"\n  {'✓ evidence pack verified' if ok else '✗ evidence pack FAILED verification'}")
    return 0 if ok else 5


def cli_keys(action="show"):
    import algotrust
    if action == "init":
        p, kid, pub = algotrust.init_key()
        print(f"  ✓ Ed25519 audit key {kid} → {p} (private: keep it secret; it is git-ignored)")
        print(f"    pin the public key in algo.config.json so verifiers trust only it:\n"
              f'    "audit": {{"sign": true, "public_keys": ["{pub}"]}}')
        return 0
    keys, pinned = algotrust.trusted_keys()
    if not keys:
        print("  no audit key yet: run  algo keys init")
        return 1
    for kid, pub in keys.items():
        print(f"  {kid}  {pub.hex()}  {'(pinned in algo.config.json)' if pinned else '(local key file)'}")
    return 0


def cli_retention(dry_run=False):
    import algotrust
    cfg = rt.load_config()
    ret = cfg.get("retention") or {}
    days = ret.get("audit_days")
    if not days:
        print('  no organisation retention set. In algo.config.json:  "retention": {"audit_days": 180, "traces_days": 30}\n'
              "  (programs can also set  policy { retain audit 180 days }; it is applied after each run)")
        return 0
    n = 0
    for f in sorted(rt.audit_dir().glob("*.audit.jsonl")):
        k = algotrust.apply_retention(f, days, dry_run=dry_run)
        n += k
        if k:
            print(f"  {'would drop' if dry_run else 'dropped'} {k} record(s) older than {days} days from {f.name}")
    t = algotrust.prune_traces(rt.audit_dir() / "traces", ret.get("traces_days") or 10 ** 6, dry_run=dry_run)
    print(f"  {n} audit record(s) and {t} trace(s) {'would be ' if dry_run else ''}removed")
    return 0

