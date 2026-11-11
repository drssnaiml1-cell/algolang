"""
algocli_ext — enterprise commands for the `algo` command line (AlgoLang v0.2)
AlgoProfessor AI R&D Solutions

    algo init [DIR]                       scaffold an enterprise project (config, tools, knowledge base)
    algo domains [QUERY] [--sector S]     browse or search 120 domain packs in 20 sectors
    algo pack ID [--copy]                 show a domain pack, or copy it here to customise
    algo batch PROGRAM --input data.csv   run a program over every row, in parallel
    algo review [approve|reject ID]       the human review queue
    algo audit verify FILE|DIR            check the tamper-evident audit chain
    algo report [DIR]                     usage, cost and governance report
    algo chat                             prompt-based mode: describe the problem in plain English
"""
from __future__ import annotations

import json
import shutil
import sys
import textwrap
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import algolang as al  # noqa: E402


def resolve_program(arg: str) -> Path | None:
    """A .algo path, or pack:<id> / a bare pack id from the library."""
    if arg.startswith("pack:"):
        arg = arg[5:]
    p = Path(arg)
    if p.exists():
        return p
    try:
        return HERE / al.domains.get(arg)["path"]
    except KeyError:
        return None


def _table(rows, headers, widths=None):
    widths = widths or [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)] if rows else \
        [len(h) for h in headers]
    line = "  " + "  ".join(str(h).ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("  " + "  ".join("─" * w for w in widths))
    for r in rows:
        print("  " + "  ".join(str(c)[:w].ljust(w) for c, w in zip(r, widths)))


# ─────────────────────────────── init ───────────────────────────────
CONFIG_TEMPLATE = {
    "organisation": "My Organisation",
    "policy": {
        "forbid": ["gender", "caste", "religion"],
        "max_budget_tokens": 8000,
        "min_human_below": 0.6,
        "allowed_tools": ["kb.search", "calc.eval", "file.read", "company.directory"],
    },
    "max_concurrency": 16,
    "max_run_tokens": 200000,
    "cache": {"enabled": True},
    "audit_dir": "runs",
    "models": {"smart": "claude-sonnet-5-5", "fast": "claude-haiku-5-5"},
    "tools": {"file.read": {"root": "data"}, "kb.search": {"dir": "kb"}},
    "plugins": ["plugins/company_tools.py"],
}

PLUGIN_TEMPLATE = '''"""Company tools for AlgoLang agents. Agents get a tool only if they `uses` it
and it is in policy.allowed_tools in algo.config.json."""
from algoruntime import register_tool

DIRECTORY = {"finance": "finance-desk@example.com", "legal": "legal-desk@example.com",
             "it": "it-helpdesk@example.com", "hr": "people-team@example.com"}


@register_tool("company.directory", "Find the right internal team and contact for a request")
def company_directory(query: str) -> str:
    q = query.lower()
    hits = [f"{team}: {contact}" for team, contact in DIRECTORY.items() if team in q]
    return "; ".join(hits) or "no matching team — route to it-helpdesk@example.com"
'''

KB_TEMPLATE = """Refund policy

Customers may request a refund within 30 days of purchase. Refunds above 50,000 INR need manager approval.

Data protection

Personal data is kept for 7 years and is never shared without consent.
"""

PROGRAM_TEMPLATE = """// Combine two domain packs from the library and add your own agent.
use pack insurance.claims_triage as claims
use pack legal.compliance_gap as compliance
tool company.directory

agent Router(summary: text) -> text {
    role "Operations coordinator"
    goal "Decide which internal team should own: {summary}"
    uses company.directory
}

flow main(claim: text) {
    intake  = claims.Intake(claim)
    covered = claims.Coverage(intake)
    level   = claims.Complexity(covered)
    owner   = Router(covered)
    emit covered, level, owner
}
"""


def cmd_init(directory="."):
    d = Path(directory)
    (d / "plugins").mkdir(parents=True, exist_ok=True)
    (d / "kb").mkdir(exist_ok=True)
    (d / "data").mkdir(exist_ok=True)
    (d / "programs").mkdir(exist_ok=True)
    made = []
    for path, content in ((d / "algo.config.json", json.dumps(CONFIG_TEMPLATE, indent=2)),
                          (d / "plugins" / "company_tools.py", PLUGIN_TEMPLATE),
                          (d / "kb" / "policies.md", KB_TEMPLATE),
                          (d / "programs" / "claims_ops.algo", PROGRAM_TEMPLATE),
                          (d / "data" / "claims.csv", "claim\nRear-end collision in Pune, bumper damage\n"
                                                     "Water damage after pipe burst\nLaptop stolen from parked car\n")):
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            made.append(path)
    print(f"✓ enterprise project ready in {d.resolve()}")
    for p in made:
        print(f"    {p}")
    print("\n  next:")
    print(f"    cd {d}")
    print("    algo run programs/claims_ops.algo --arg \"claim=Rear-end collision\"")
    print("    algo batch programs/claims_ops.algo --input data/claims.csv")
    print("    algo report")
    return 0


# ─────────────────────────────── domains / pack ───────────────────────────────
def cmd_domains(query=None, sector=None, limit=10):
    if query:
        res = al.domains.search(query, k=limit)
        res = [r for r in res if r["score"] >= 0.3 * res[0]["score"]] if res else res
        if not res:
            print("  no matching domain packs")
            return 1
        _table([(r["id"], r["title"], r["pattern"], r["risk"], r["score"]) for r in res],
               ["pack", "title", "pattern", "risk", "match"])
        print(f"\n  run one:  algo run pack:{res[0]['id']} --arg \"{res[0]['input']}=...\"")
        return 0
    if sector:
        packs = al.domains.all(sector)
        if not packs:
            print(f"  unknown sector '{sector}' — run `algo domains` to list sectors")
            return 1
        _table([(p["id"], p["title"], p["pattern"], p["risk"], "yes" if p["people"] else "") for p in packs],
               ["pack", "title", "pattern", "risk", "people"])
        return 0
    secs = al.domains.sectors()
    print(f"  AlgoLang domain library — {sum(s['packs'] for s in secs)} packs in {len(secs)} sectors\n")
    _table([(s["id"], s["name"], s["packs"]) for s in secs], ["sector", "name", "packs"])
    print('\n  algo domains --sector insurance      ·      algo domains "screen CVs fairly"')
    return 0


def cmd_pack(pack_id, copy=False):
    try:
        m = al.domains.get(pack_id)
    except KeyError as e:
        print(f"✗ {e.args[0]}")
        return 1
    src = HERE / m["path"]
    print(f"  {m['id']} — {m['title']}  ({m['sector_name']})")
    print(f"  {m['description']}")
    print(f"  pattern {m['pattern']} · risk {m['risk']} · human review below {m['human_threshold']} · "
          f"budget {m['budget_tokens']} tokens" + (f" · forbids {', '.join(m['forbid'])}" if m["forbid"] else ""))
    print(f"  agents: {', '.join(m['agents'])}" + (f" · tools: {', '.join(m['tools'])}" if m["tools"] else ""))
    if copy:
        dest = Path.cwd() / f"{m['id'].split('.')[1]}.algo"
        shutil.copy(src, dest)
        print(f"\n✓ copied to {dest} — edit it, then: algo run {dest.name} --arg \"{m['input']}=...\"")
    else:
        print(f"\n  use it:   use pack {m['id']}            (in your own .algo file)")
        print(f"  run it:   algo run pack:{m['id']} --arg \"{m['input']}=...\"")
        print(f"  edit it:  algo pack {m['id']} --copy")
    return 0


# ─────────────────────────────── batch ───────────────────────────────
def cmd_batch(program, input_csv, out=None, workers=8, live=False):
    path = resolve_program(program)
    if not path:
        print(f"✗ not a file or domain pack: {program}")
        return 1
    try:
        prog = al.load(path)
    except al.CompileError as e:
        print(f"✗ {path.name}: {len(e.diags)} error(s)")
        for d in e.diags:
            print(f"  {d}")
        return 1
    out = out or str(Path(input_csv).with_name(Path(input_csv).stem + "_results.csv"))
    t0 = time.time()
    last = [0.0]

    def progress(done, total):
        if time.time() - last[0] > 0.25 or done == total:
            last[0] = time.time()
            bar = "█" * int(30 * done / total)
            print(f"\r  [{bar:<30}] {done}/{total}", end="", flush=True)

    print(f"▶ batch {prog.name} · inputs {prog.inputs} · {workers} workers · backend {'live' if live else 'mock'}")
    try:
        results = al.batch_csv(prog, input_csv, out, workers=workers, live=live, progress=progress)
    except (ValueError, FileNotFoundError) as e:
        print(f"\n✗ {e}")
        return 1
    print()
    st = {}
    for r in results:
        st[r.status] = st.get(r.status, 0) + 1
    esc = sum(1 for r in results if r.escalated)
    toks = sum(r.stats.get("tokens", 0) for r in results)
    print(f"■ {len(results)} rows in {time.time() - t0:.1f}s · " + " · ".join(f"{v} {k}" for k, v in st.items())
          + f" · {esc} rows sent for human review · ~{toks} tokens")
    print(f"  results → {out}")
    if esc:
        print("  review them:  algo review")
    return 0 if st.get("failed", 0) == 0 else 3


# ─────────────────────────────── review ───────────────────────────────
def cmd_review(action=None, item=None, reviewer="", note="", show_all=False, override=None):
    if action in ("approve", "reject"):
        if not item:
            print("  usage: algo review approve <id> --reviewer \"Name\" --note \"why\"")
            return 1
        try:
            full = al.review.approve(item, reviewer, note, override=override) if action == "approve" \
                else al.review.reject(item, reviewer, note)
        except (KeyError, ValueError) as e:
            print(f"✗ {e.args[0]}")
            return 1
        it = next((i for i in al.review.all() if i["id"] == full), {})
        left = it.get("approvals_required", 1) - len(it.get("approvals", []))
        more = f"  ({left} more approval(s) from a different reviewer needed)" if it.get("status") == "pending" else ""
        print(f"✓ {action}d {full}" + (f" by {reviewer}" if reviewer else "") + (" with an override" if override else "") + more)
        return 0
    items = al.review.all() if show_all else al.review.pending()
    if not items:
        print("  review queue is empty" if not show_all else "  no review items yet")
        return 0
    print(f"  {len(items)} item(s){' (all)' if show_all else ' waiting for a human decision'}\n")
    _table([(i["id"][:8], i["program"], i["agent"], f"{i['confidence']:.2f}",
             f"{len(i.get('approvals', []))}/{i.get('approvals_required', 1)}", i["status"],
             (i.get("reason") or (f"< {i['threshold']:.2f}" if i.get("threshold") is not None else ""))[:28],
             i["output"][:36]) for i in items[-30:]],
           ["id", "program", "agent", "conf", "approvals", "status", "why", "output"])
    if len(items) > 30:
        print(f"  … {len(items) - 30} older item(s) not shown")
    print('\n  algo review approve <id> --reviewer "Name" --note "checked"   ·   algo review reject <id>')
    return 0


# ─────────────────────────────── audit / report ───────────────────────────────
def cmd_audit_verify(target):
    t = Path(target)
    files = sorted(t.glob("*.jsonl")) if t.is_dir() else [t]
    if not files or not files[0].exists():
        print(f"✗ nothing to verify at {t}")
        return 1
    bad = 0
    for f in files:
        r = al.audit.verify(f)
        if r["ok"]:
            sig = (f", {r['signed']} signed ({'pinned key' if r.get('pinned') else 'local key'})" if r.get("signed") else "")
            drop = f", {r['dropped']} older record(s) removed by retention" if r.get("dropped") else ""
            print(f"  ✓ {f.name:<36} {r['records']} records, chain intact{sig}{drop}")
        else:
            bad += 1
            print(f"  ✗ {f.name:<36} line {r['first_bad_line']}: {r['reason']}")
    return 0 if not bad else 4


def dashboard_html(rep, title="AlgoLang cost & energy dashboard"):
    """v0.7: a self-contained navy-and-gold dashboard of cost, energy, tokens, QPU time and governance."""
    import html as _h
    t = rep["totals"]
    progs = sorted(rep["programs"].items(), key=lambda kv: -kv[1]["cost_usd"])[:12]
    agents = sorted(rep["agents"].items(), key=lambda kv: -kv[1]["tokens"])[:12]

    def bars(rows, key, fmt, empty="no runs yet"):
        top = max([v[key] for _, v in rows] + [1e-12])
        return "".join(
            f'<div class="row"><span class="lab">{_h.escape(k)}</span><span class="bar"><i style="width:'
            f'{100 * v[key] / top:.1f}%"></i></span><span class="val">{fmt(v[key])}</span></div>' for k, v in rows) or \
            f'<p class="muted">{empty}</p>'
    broken = [k for k, ok in rep["chains"].items() if not ok]
    kpis = [("Agent calls", f"{t['calls']:,}"), ("Tokens", f"{t['tokens']:,}"), ("Cost", f"${t['cost_usd']:.4f}"),
            ("Energy", f"{t['energy_wh']:.3f} Wh"), ("CO₂", f"{t['co2_g']:.2f} g"),
            ("QPU time", f"{t.get('qpu_seconds', 0):.1f} s"), ("Escalated", str(t["escalated"])),
            ("Audit chains", f"{len(rep['chains']) - len(broken)} intact" + (f" · {len(broken)} broken" if broken else ""))]
    tiles = "".join(f'<div class="kpi"><b>{v}</b><span>{k}</span></div>' for k, v in kpis)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_h.escape(title)}</title><style>
:root{{--navy:#0b1f3a;--navy2:#132b4f;--gold:#c9a227;--gold2:#f2d372;--ink:#e8ecf4;--muted:#9fb0c8}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--navy);color:var(--ink);font:15px/1.5 "Segoe UI",system-ui,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:28px 16px}}h1{{margin:0 0 4px;font-size:26px}}h2{{color:var(--gold);font-size:13px;
letter-spacing:3px;text-transform:uppercase;margin:28px 0 10px}}.muted{{color:var(--muted)}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:18px}}
.kpi{{background:var(--navy2);border:1px solid var(--gold);border-radius:12px;padding:14px}}.kpi b{{display:block;
font-size:22px;color:var(--gold2)}}.kpi span{{color:var(--muted);font-size:13px}}
.card{{background:var(--navy2);border-radius:12px;padding:16px;border:1px solid #23406d}}
.row{{display:grid;grid-template-columns:minmax(120px,32%) 1fr 90px;gap:10px;align-items:center;margin:6px 0}}
.lab{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.bar{{background:#0e2547;border-radius:6px;height:12px}}
.bar i{{display:block;height:100%;border-radius:6px;background:linear-gradient(90deg,var(--gold),var(--gold2))}}
.val{{text-align:right;font-variant-numeric:tabular-nums}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}}
footer{{margin-top:28px;color:var(--muted);font-size:12px}}</style></head><body><main>
<h1>{_h.escape(title)}</h1><div class="muted">From the audit logs · offline runs show the estimated live cost</div>
<div class="kpis">{tiles}</div>
<div class="grid"><section><h2>Cost by program</h2><div class="card">{bars(progs, "cost_usd", lambda x: f"${x:.4f}")}</div></section>
<section><h2>Energy by program</h2><div class="card">{bars(progs, "energy_wh", lambda x: f"{x:.3f} Wh")}</div></section>
<section><h2>Tokens by agent</h2><div class="card">{bars(agents, "tokens", lambda x: f"{x:,}")}</div></section>
<section><h2>QPU time by program</h2><div class="card">{bars([p for p in progs if p[1].get("qpu_seconds")], "qpu_seconds",
                                                             lambda x: f"{x:.1f} s", "no QPU time used")}</div></section></div>
<footer>AlgoLang {al.__version__} · AlgoProfessor AI R&amp;D Solutions</footer></main></body></html>"""


def cmd_report(directory="runs", as_json=False, html_out=None):
    rep = al.audit.report(directory)
    if html_out:
        Path(html_out).write_text(dashboard_html(rep), encoding="utf-8")
        print(f"  ✓ dashboard → {html_out}")
    if as_json:
        print(json.dumps(rep, indent=2))
        return 0
    t = rep["totals"]
    print(f"  AlgoLang usage & governance report — {directory}\n")
    print(f"  {t['calls']} agent calls · ~{t['tokens']} tokens · {t['escalated']} escalated · "
          f"{t['blocked']} blocked · {t['failed']} failed · {t['cached']} from cache · {t['tool_calls']} tool calls")
    inr = t["cost_usd"] * float(al.configure().get("usd_to_inr") or 84)
    print(f"  cost ${t['cost_usd']:.4f} (₹{inr:.2f}) · energy {t['energy_wh']:.3f} Wh · {t['co2_g']:.2f} g CO₂ "
          f"(offline runs show the estimated live cost)\n")
    if rep["programs"]:
        _table([(k, v["calls"], v["tokens"], f"${v['cost_usd']:.4f}", f"{v['energy_wh']:.3f}", v["escalated"],
                 v["blocked"], v["avg_confidence"])
                for k, v in sorted(rep["programs"].items(), key=lambda kv: -kv[1]["tokens"])],
               ["program", "calls", "tokens", "cost", "Wh", "escalated", "blocked", "avg conf"])
        print()
        _table([(k, v["calls"], v["tokens"], v["escalated"], v["avg_confidence"])
                for k, v in sorted(rep["agents"].items(), key=lambda kv: -kv[1]["tokens"])[:12]],
               ["top agents by tokens", "calls", "tokens", "escalated", "avg conf"])
    broken = [k for k, ok in rep["chains"].items() if not ok]
    print(f"\n  audit chains: {len(rep['chains']) - len(broken)} intact" + (f", {len(broken)} BROKEN: {', '.join(broken)}" if broken else ""))
    return 0


# ─────────────────────────────── chat (prompt mode) ───────────────────────────────
CHAT_HELP = """  Describe a problem in plain English — AlgoLang finds the right domain pack and runs it.
    1, 2, 3        switch to one of the alternatives shown
    :show          show the program   ·   :save NAME   save it to customise
    :ai CHANGE     ask AI to change the program (needs ANTHROPIC_API_KEY)
    :live on|off   real Claude models / offline mock   ·   :help   ·   :quit"""


def _print_run(res, prog):
    for c in res.calls:
        flag = "  ⚠ human review" if c.get("status") == "escalated" else ""
        if c.get("status") == "blocked":
            print(f"    ✗ {c['agent']}: blocked — {c.get('reason')}")
            continue
        out = c.get("output")
        out = f"[{len(out)} items]" if isinstance(out, list) else str(out)
        print(f"    → {c['agent']:<20} conf {c.get('confidence', 0):.2f}  {out[:70]}{flag}")
    if res.ok:
        print("  result:")
        for v in res.values:
            v = al._rt.Runtime.value(v)
            for line in textwrap.wrap(str(v), 96)[:4]:
                print(f"    {line}")
    else:
        print(f"  ✗ {res.problem}")
    s = res.stats
    print(f"  {s.get('calls', 0)} agent calls · ~{s.get('tokens', 0)} tokens · {s.get('escalations', 0)} sent for review"
          f" · audit {res.audit_path}")


def cmd_chat():
    print(f"AlgoLang {al.__version__} — prompt mode ({len(al.domains.all())} domain packs)")
    print(CHAT_HELP + "\n")
    live, current, alts, last_request, source = False, None, [], "", None
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in (":quit", ":q", ":exit"):
            return 0
        if line == ":help":
            print(CHAT_HELP)
            continue
        if line.startswith(":live"):
            live = line.endswith("on")
            print(f"  backend: {'live (Claude)' if live else 'mock (offline)'}")
            continue
        if line == ":show":
            print(source or "  (nothing yet — describe a problem first)")
            continue
        if line.startswith(":save"):
            if not source:
                print("  nothing to save yet")
                continue
            name = (line.split(maxsplit=1)[1:] or ["my_program"])[0]
            name = name if name.endswith(".algo") else name + ".algo"
            Path(name).write_text(source, encoding="utf-8")
            print(f"  ✓ saved {name} — run it with: algo run {name}")
            continue
        if line.startswith(":ai"):
            change = line[3:].strip()
            if not (source and change):
                print("  usage: :ai make the reviewer stricter and add a Hindi summary")
                continue
            try:
                r = al.ask(change, current=source, log=lambda m: print("  " + m))
            except Exception as e:  # noqa
                print(f"  ✗ {e}")
                continue
            if r["ok"]:
                source, current = r["source"], al.compile(r["source"], "ai_program")
                print("  ✓ program updated — running it")
                inp = {current.inputs[0]: last_request} if len(current.inputs) == 1 else {}
                if len(inp) == len(current.inputs):
                    _print_run(current.run(live=live, **inp), current)
            continue
        if line.isdigit() and alts and 1 <= int(line) <= len(alts):
            pick = alts[int(line) - 1]
            alts = [current_meta] + [a for a in alts if a["id"] != pick["id"]]  # noqa: F821
            current_meta = pick
        else:
            last_request = line
            matches = al.domains.search(line, k=4)
            if not matches:
                print("  no domain pack matches that — try describing the task differently, or use :ai")
                continue
            current_meta, alts = matches[0], matches[1:]
        current = al.load(HERE / current_meta["path"])
        source = current.source
        print(f"  ▶ {current_meta['title']} ({current_meta['id']}) · {current_meta['pattern']} pattern · "
              f"risk {current_meta['risk']} · agents: {', '.join(current_meta['agents'])}")
        if alts:
            print("    other options: " + "  ".join(f"[{n}] {a['title']}" for n, a in enumerate(alts, 1)))
        inputs = {current.inputs[0]: last_request}
        _print_run(current.run(live=live, **inputs), current)
