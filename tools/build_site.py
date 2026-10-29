"""Build the AlgoLang website (GitHub Pages) into site/.

    python tools/build_site.py            # → site/
    python -m http.server -d site 8000    # preview at http://localhost:8000

Pages: home, domain library, web playground (Pyodide), the guides rendered from Markdown, and downloads.
The home page's run output comes from really running the hero program, so it never drifts from the code.
Needs: markdown (pip install markdown). Pillow is optional (shrinks screenshots)."""
from __future__ import annotations

import html
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB, OUT = ROOT / "web", ROOT / "site"
sys.path.insert(0, str(ROOT))

import markdown  # noqa: E402

import algolang as al  # noqa: E402

REPO = "https://github.com/drssnaiml1-cell/algolang"
VERSION = al.__version__
MINOR = ".".join(VERSION.split(".")[:2])          # the manual is named per minor version: v0.2
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">')
LOGO = ('<svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="14.5" fill="none" stroke="#C9A227" stroke-width="2"/>'
        '<path d="M16 7 L25 23 L7 23 Z" fill="none" stroke="#fff" stroke-width="2" stroke-linejoin="round"/>'
        '<circle cx="16" cy="7" r="2.6" fill="#C9A227"/><circle cx="25" cy="23" r="2.6" fill="#C9A227"/><circle cx="7" cy="23" r="2.6" fill="#C9A227"/></svg>')
NAV = [("index.html", "Overview"), ("library.html", "Domain library"), ("playground.html", "Playground"),
       ("guide.html", "Run guide"), ("developers.html", "Developers"), ("downloads.html", "Downloads")]

HERO_PROGRAM = '''// A claims desk: one agent of your own, two from a domain pack.
use pack insurance.fraud_screening as fraud

agent Intake(claim: text) -> text {
    role  "Claims intake clerk"
    goal  "Extract date, place and damage from: {claim}"
    policy {
        budget tokens 2000
        require human when confidence < 0.80
    }
}

flow main(claim: text) {
    c     = Intake(claim)
    views = par { fraud.PatternAnalyst(c), fraud.DocumentExaminer(c) }
    risk  = fraud.FraudPanel(views)
    emit c, risk
}'''
HERO_INPUT = "Rear-end collision in Pune on 3 Oct, bumper damage"

EXAMPLES = [  # shown in the playground menu; every one is compiled by this script before it ships
    ("Claims desk (uses a domain pack)", HERO_PROGRAM, {"claim": HERO_INPUT}),
    ("Research brief", "examples/research_brief.algo", {"topic": "Blockchain data integrity"}),
    ("Paper review committee", "examples/paper_review.algo", {"paper": "Lesion-guided ensemble for diabetic retinopathy grading"}),
    ("Fairness guard (compile error on purpose)", '''// The compiler refuses to give a protected attribute to an agent.
agent Screener(cv: text, caste: text) -> score {
    role  "Junior recruiter"
    goal  "Score how well {cv} fits the role"
    policy { forbid caste, religion, gender }
}

flow main(cv: text, caste: text) {
    s = Screener(cv, caste)
    emit s
}''', {}),
    ("Write your own", '''// Every unit of work is an agent. Change the role and goal, then press Run.
agent Explainer(topic: text) -> text {
    role  "Patient teacher"
    goal  "Explain {topic} to a first-year student in five sentences"
}

agent Checker(draft: text) -> score {
    role  "Strict reviewer"
    goal  "Score 0 to 1 how accurate and clear this is: {draft}"
}

flow main(topic: text) {
    d = Explainer(topic)
    if Checker(d) < 0.75 {
        d = Explainer(topic)
    }
    emit d
}''', {"topic": "Neural networks"}),
]


# ═════════════════════════════════ helpers ═══════════════════════════════════
def esc(s):
    return html.escape(str(s), quote=True)


KW = set("agent flow model tool use pack as policy role goal uses budget tokens retry timeout require human when "
         "confidence forbid cache par for in if else emit seconds".split())
TY = set("text score list json bool".split())


def hl(src):
    out = []
    for m in re.finditer(r'(//[^\n]*)|("(?:[^"\\\n]|\\.)*")|(\b\d+(?:\.\d+)?\b)|([A-Za-z_]\w*)|([\s\S])', src):
        c, s, n, w, o = m.groups()
        if c:
            out.append(f'<span class="c">{esc(c)}</span>')
        elif s:
            out.append(f'<span class="s">{esc(s)}</span>')
        elif n:
            out.append(f'<span class="n">{n}</span>')
        elif w:
            out.append(f'<span class="k">{w}</span>' if w in KW else f'<span class="t">{w}</span>' if w in TY else w)
        else:
            out.append(esc(o))
    return "".join(out)


def page(name, title, body, desc, extra_head="", scripts=""):
    nav = "".join(f'<a href="{h}"{" aria-current=page" if h == name else ""}>{t}</a>' for h, t in NAV)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}">
<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
{FONTS}
<link rel="stylesheet" href="assets/site.css">
{extra_head}
</head>
<body>
<header class="bar"><div class="wrap">
  <a class="brand" href="index.html">{LOGO}<span>Algo<b>Lang</b></span></a>
  <nav class="nav" aria-label="Main">{nav}<a class="gh" href="{REPO}">GitHub</a></nav>
</div></header>
{body}
<footer><div class="wrap">
  <div><strong>AlgoLang {VERSION}</strong> · Apache License 2.0<br>Designed by Dr. S. Satyanarayana, AlgoProfessor AI R&amp;D Solutions, Hyderabad</div>
  <div><a href="{REPO}">Source on GitHub</a> · <a href="{REPO}/issues">Report a problem</a> · <a href="https://www.algoprofessor.com">algoprofessor.com</a></div>
</div></footer>
<script src="assets/algo.js"></script>
{scripts}
</body>
</html>
"""


def md_page(src_file, name, title, desc, intro_title=None):
    text = (ROOT / src_file).read_text(encoding="utf-8")
    links = {"RUN_GUIDE.md": "guide.html", "DEVELOPER_GUIDE.md": "developers.html", "CHANGELOG.md": "changelog.html",
             "README.md": "index.html"}

    def fix(m):
        target = m.group(2)
        base = target.split("#")[0]
        if base in links:
            return f"]({links[base]}{target[len(base):]})"
        if not re.match(r"[a-z]+:|#", target):
            return f"]({REPO}/blob/main/{target})"
        return m.group(0)

    text = re.sub(r"\]\(()([^)\s]+)\)", fix, text)
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"],
                           extension_configs={"toc": {"permalink": False, "toc_depth": "2-3"}})
    body = md.convert(text)
    body = re.sub(r'<pre><code class="language-algo">(.*?)</code></pre>',
                  lambda m: f'<pre><code>{hl(html.unescape(m.group(1)))}</code></pre>', body, flags=re.S)
    toc = "".join(f'<a href="#{t["id"]}">{t["name"]}</a>' + "".join(f'<a class="h3" href="#{c["id"]}">{c["name"]}</a>'
                                                                  for c in t.get("children", []))
                  for top in md.toc_tokens for t in (top.get("children") or [top]))
    return page(name, title, f'<main class="wrap doc"><nav class="toc" aria-label="On this page">{toc}</nav>'
                             f'<article class="prose">{body}</article></main>', desc)


def run_hero():
    prog = al.compile(HERO_PROGRAM, "claims_desk")
    r = prog.run(audit_dir=str(OUT / ".hero_runs"), claim=HERO_INPUT)
    short = HERO_INPUT if len(HERO_INPUT) <= 28 else HERO_INPUT[:26] + "…"
    lines = [f'<span class="dim">$</span> algo run claims_desk.algo --arg "claim={esc(short)}"']
    for c in r.calls:
        tag = '<span class="esc">escalated → human review</span>' if c["status"] == "escalated" else '<span class="ok">ok</span>'
        lines.append(f'  → {c["agent"]:<24} conf={c["confidence"]:.2f}  {tag}')
    s = r.stats
    lines.append(f'<span class="dim">■ {s.get("calls", len(r.calls))} agent calls · ~{s.get("tokens", 0)} tokens · '
                 f'{len(r.escalated)} escalated · audit chain intact</span>')
    shutil.rmtree(OUT / ".hero_runs", ignore_errors=True)
    return "\n".join(lines)


# ═════════════════════════════════ pages ═════════════════════════════════════
def home(catalog, run_out):
    n_packs, n_sectors = len(catalog["packs"]), len(catalog["sectors"])
    body = f"""
<main>
<section class="hero"><div class="wrap">
  <div>
    <h1>Every unit of work is an agent.</h1>
    <p class="lede">AlgoLang is a programming language for building AI systems out of agents instead of functions.
    Each agent states its <strong>role</strong>, its <strong>goal</strong>, the <strong>tools</strong> it may use and the
    <strong>policy</strong> it must obey. The compiler and runtime enforce those rules, so governance is part of the program rather than a document beside it.</p>
    <div class="cta">
      <a class="btn gold" href="playground.html">Try it in your browser</a>
      <a class="btn line" href="guide.html">Install and run</a>
    </div>
    <div class="install"><span>$</span><code>pip install git+{REPO}</code><button data-copy="pip install git+{REPO}">Copy</button></div>
  </div>
  <figure class="specimen" style="margin:0" aria-label="An AlgoLang program and the output of running it">
    <div class="tabs"><span class="on">claims_desk.algo</span></div>
    <pre>{hl(HERO_PROGRAM)}</pre>
    <div class="run"><pre>{run_out}</pre></div>
  </figure>
</div></section>

<section class="band white"><div class="wrap">
  <h2>One language, three ways in</h2>
  <p class="intro">Engineers script it, analysts click through it, and everyone else describes the problem in a sentence. All three use the same Python SDK, so a program behaves the same way in each.</p>

  <div class="mode">
    <div class="copy"><h3>Command line</h3>
      <p>Run programs and packs, process a CSV of thousands of records in parallel, work the human review queue, and verify audit logs. Typing <span class="cmd">algo</span> on its own opens a numbered menu.</p>
    </div>
    <pre class="term"><span class="p">$</span> algo init acme &amp;&amp; cd acme
<span class="p">$</span> algo domains "servers are down"
  itops.incident_triage    IT incident triage    pipe   high  0.5
<span class="p">$</span> algo batch programs/claims_ops.algo --input data/claims.csv --workers 16
<span class="d">■ 3 rows in 0.0s · 3 ok · 3 rows sent for human review · ~1280 tokens</span>
<span class="p">$</span> algo review approve 4becd3f4 --reviewer "Dr. S"
<span class="p">$</span> algo audit verify
  ✓ claims_ops.audit.jsonl    12 records, chain intact
  ✓ review_queue.jsonl         3 records, chain intact</pre>
  </div>

  <div class="mode flip">
    <div class="shot"><img src="img/studio-domains.png" alt="AlgoLang Studio showing an agent program in the editor and the domain library tab" loading="lazy"></div>
    <div class="copy"><h3>Studio, in your browser</h3>
      <p><span class="cmd">algo studio</span> opens an editor with live error checking, a run panel, an agent graph, and AI help that writes and repairs programs.</p>
      <p>The Domains, Batch and Governance tabs bring the library, bulk runs and the review queue into the same window. Studio runs on your own machine.</p>
    </div>
  </div>

  <div class="mode">
    <div class="copy"><h3>Prompt UI</h3>
      <p><span class="cmd">algo ui</span> is for people who will never open an editor. They describe the problem, and AlgoLang picks the closest of {n_packs} domain programs and runs it under your organisation's rules.</p>
      <p>The page shows which agents ran, what each one concluded, and which results now wait for a person to approve.</p>
    </div>
    <div class="shot"><img src="img/prompt-answer.png" alt="The Prompt UI answering an IT outage request with a multi-agent incident triage program" loading="lazy"></div>
  </div>
</div></section>

<section class="band navy"><div class="wrap">
  <h2>Governance the compiler can enforce</h2>
  <p class="intro">Responsible-AI rules usually live in policy documents. In AlgoLang they are part of the program, and a program that breaks them does not compile or does not run.</p>
  <div class="ledger">
    <div><h3>Organisation policy</h3><p>One <code>algo.config.json</code> sets forbidden attributes, token budgets, review thresholds and allowed tools for every program. If it and a program disagree, the stricter rule wins.</p></div>
    <div><h3>Protected attributes</h3><p>An agent that takes <code>caste</code>, <code>religion</code> or any other forbidden attribute as input is a compile error (E108), not a code-review comment.</p></div>
    <div><h3>Human in the loop</h3><p>Results below an agent's confidence threshold wait in a review queue until a named person approves or rejects them.</p></div>
    <div><h3>Tamper-evident audit</h3><p>Every agent call is logged, and each record carries the hash of the one before it. <code>algo audit verify</code> finds the first edited or deleted line.</p></div>
    <div><h3>Explicit capabilities</h3><p>An agent can call only the tools it declares with <code>uses</code>, and only if the organisation allows them. Live tool-use loops refuse anything else.</p></div>
    <div><h3>Budgets and caching</h3><p>Token caps per agent and per run, a global concurrency limit, and a response cache that answers repeated calls at zero cost.</p></div>
  </div>
</div></section>

<section class="band"><div class="wrap">
  <h2>{n_packs} ready-made programs for real departments</h2>
  <p class="intro">Each domain pack is an ordinary AlgoLang file built on one of four patterns: a pipeline, a fan-out, a committee or a router. Its policy matches its risk: high-risk packs send anything below 0.90 confidence to a person.</p>
  <ul class="facts"><li><strong>{n_packs}</strong>domain packs</li><li><strong>{n_sectors}</strong>sectors</li><li><strong>4</strong>agent patterns</li><li><strong>0</strong>packs that skip human review</li></ul>
  <p style="margin:0 0 26px;color:var(--slate)">{", ".join(esc(v) for v in catalog["sectors"].values())}.</p>
  <a class="btn dark" href="library.html">Browse the library</a>
</div></section>

<section class="band white"><div class="wrap">
  <h2>Developer tracks</h2>
  <p class="intro">Choose the track that matches what you are building. The <a href="developers.html">developer guide</a> covers all three in detail.</p>
  <div class="tracks">
    <div class="track"><h3>Build applications</h3>
      <p>Use AlgoLang and the SDK inside your own services.</p>
      <ul><li><code>import algolang</code>: compile, run, batch, review</li><li>Company tools as Python plugins</li><li>Behaviour tests in <code>*.algotest.json</code></li><li><code>algo dev ci</code> writes your GitHub workflow</li></ul>
      <a href="developers.html#1-application-developer-track">Application track</a></div>
    <div class="track"><h3>Extend the language</h3>
      <p>Add syntax, error codes, runtime features and domain packs.</p>
      <ul><li>Lark grammar → AST → checker → Python</li><li>Recipes for each kind of change</li><li>82 tests, ruff, and <code>.algo</code> lint in one command</li></ul>
      <a href="developers.html#2-language-contributor-track">Contributor track</a></div>
    <div class="track"><h3>Maintain and release</h3>
      <p>Ship versions the way this project does.</p>
      <ul><li>CI on Linux, macOS and Windows, Python 3.9–3.13</li><li>Tagging <code>v*</code> publishes wheel, zip and PDFs</li><li>This site and the container image are built automatically</li></ul>
      <a href="developers.html#3-maintainer-track-releases-and-deployment">Maintainer track</a></div>
  </div>
</div></section>
</main>"""
    return page("index.html", "AlgoLang: an agent-native programming language", body,
                "AlgoLang is a programming language for governed multi-agent AI: agents instead of functions, "
                "policies the compiler enforces, and 120 ready-made domain programs.")


def library(catalog):
    sectors = catalog["sectors"]
    opts = "".join(f'<option value="{k}">{esc(v)}</option>' for k, v in sectors.items())
    body = f"""
<main>
<div class="pagehead"><div class="wrap"><h1>Domain library</h1>
<p>{len(catalog["packs"])} governed multi-agent programs across {len(sectors)} sectors. Search in plain words, read the source, or open any pack in the playground.</p></div></div>
<div class="lib-controls"><div class="wrap">
  <label class="visually-hidden" for="q" style="position:absolute;left:-9999px">Search packs</label>
  <input id="q" class="search" type="search" placeholder="Describe the work, e.g. screen CVs fairly, crop disease, fraud" autocomplete="off">
  <select id="sector" class="sector" aria-label="Sector"><option value="">All sectors</option>{opts}</select>
  <span class="count" id="count" aria-live="polite"></span>
</div></div>
<div class="wrap">
<table class="packs"><thead><tr><th>Pack</th><th class="ag">Agents</th><th>Pattern</th><th class="risk">Risk</th><th><span style="position:absolute;left:-9999px">Actions</span></th></tr></thead>
<tbody id="rows"></tbody></table>
</div>
<dialog class="src" id="dlg"><header><h3 id="dlg-t"></h3><div class="acts">
  <button id="dlg-copy">Copy</button><a class="go" id="dlg-play" href="#">Open in playground</a><button id="dlg-x" aria-label="Close">Close</button></div></header>
<pre id="dlg-src"></pre></dialog>
</main>"""
    script = """<script>
(function(){
  const {esc, highlight} = window.AlgoSite, $ = s => document.querySelector(s);
  let cat;
  // the same everyday-word expansion the SDK uses, so the website and `algo domains` agree
  const SYN = {cv:"resume hiring candidate",resume:"cv hiring candidate",crop:"farm agriculture plant",disease:"pest diagnosis symptoms",
    outage:"incident down",down:"incident outage",servers:"incident itops",fraud:"fraud screening risk",patient:"clinical hospital",
    student:"education grading",citizen:"grievance government public",contract:"legal clause nda",invoice:"payment finance",
    loan:"credit banking",claim:"insurance claims",shipment:"logistics supply",hotel:"hospitality booking",phishing:"cyber security"};
  function words(s){ return (s.toLowerCase().match(/[a-z0-9]+/g)||[]).filter(w=>w.length>1); }
  function score(p, q){
    if(!q.length) return 1;
    const hay = (p.title+" "+p.description+" "+p.sector_name+" "+p.agents.join(" ")+" "+p.id).toLowerCase();
    let s = 0;
    for(const w of q){ if(hay.includes(w)) s += 2; for(const x of (SYN[w]||"").split(" ")) if(x && hay.includes(x)) s += 1; }
    return s;
  }
  function render(){
    const q = words($("#q").value), sec = $("#sector").value;
    let list = cat.packs.filter(p => !sec || p.sector === sec).map(p => [score(p,q), p]).filter(x => x[0] > 0);
    if(q.length) list.sort((a,b) => b[0]-a[0]);
    let h = "", last = null;
    for(const [,p] of list){
      if(!q.length && p.sector !== last){ h += `<tr class="sec"><td colspan="5">${esc(p.sector_name)}</td></tr>`; last = p.sector; }
      h += `<tr><td><span class="t">${esc(p.title)}</span><span class="d">${esc(p.description)}</span><span class="id">${esc(p.id)}</span></td>
        <td class="ag">${p.agents.map(esc).join(" → ")}</td><td>${esc(p.pattern)}</td>
        <td class="risk"><span class="risk ${esc(p.risk)}">${esc(p.risk)}</span></td>
        <td><button class="view" data-id="${esc(p.id)}">View source</button></td></tr>`;
    }
    $("#rows").innerHTML = h || `<tr><td colspan="5" style="padding:30px 0;color:#46536B">No pack matches “${esc($("#q").value)}”. Try other words, or pick a sector.</td></tr>`;
    $("#count").textContent = `${list.length} of ${cat.packs.length}`;
  }
  async function view(id){
    const p = cat.packs.find(x => x.id === id), src = await (await fetch(p.path)).text();
    $("#dlg-t").textContent = p.title + "  ·  " + p.id;
    $("#dlg-src").innerHTML = highlight(src);
    $("#dlg-copy").setAttribute("data-copy", src);
    $("#dlg-play").href = "playground.html#" + encodeURIComponent("pack:" + id);
    $("#dlg").showModal();
  }
  $("#rows").addEventListener("click", e => { const b = e.target.closest("button.view"); if(b) view(b.dataset.id); });
  $("#dlg-x").addEventListener("click", () => $("#dlg").close());
  $("#q").addEventListener("input", render); $("#sector").addEventListener("change", render);
  fetch("packs/catalog.json").then(r => r.json()).then(c => { cat = c; const q = new URLSearchParams(location.search).get("q"); if(q) $("#q").value = q; render(); });
})();
</script>"""
    return page("library.html", "Domain library · AlgoLang", body,
                f"{len(catalog['packs'])} governed multi-agent AlgoLang programs across {len(sectors)} sectors.",
                scripts=script)


def playground():
    body = """
<main class="pg">
  <section class="left" aria-label="Program">
    <div class="tool">
      <label for="pick">Program</label><select id="pick"></select>
      <button class="btn gold" id="run" disabled>Run</button>
      <span class="status" id="status">Loading…</span>
    </div>
    <div class="ed"><pre class="gut" id="gut" aria-hidden="true"></pre><pre id="hl" aria-hidden="true"></pre>
      <textarea id="src" spellcheck="false" autocapitalize="off" autocomplete="off" aria-label="AlgoLang source code"></textarea></div>
    <div class="inputs" id="inputs" aria-label="Inputs to flow main"></div>
  </section>
  <section class="right" aria-label="Output">
    <div class="rtabs" role="tablist"><button data-tab="results" aria-selected="true">Results</button><button data-tab="python" aria-selected="false">Generated Python</button><button data-tab="audit" aria-selected="false">Audit log</button>
      <span id="ver" style="margin-left:auto;align-self:center;font-size:13px;color:#7A869C"></span></div>
    <div class="rpane" id="p-results"></div>
    <div class="rpane pypane" id="p-python" hidden><p class="empty">Run a program to see the Python the compiler generates.</p></div>
    <div class="rpane pypane" id="p-audit" hidden><p class="empty">Run a program to see its audit records.</p></div>
  </section>
</main>"""
    html_ = page("playground.html", "Playground · AlgoLang", body,
                 "Write and run AlgoLang in your browser: the real compiler and runtime, running locally with Pyodide.",
                 scripts='<script src="assets/playground.js"></script>')
    return html_.replace("<footer>", '<footer style="display:none">', 1)   # the playground fills the window


def downloads():
    rel = f"{REPO}/releases/latest"
    rows = [
        ("Python package", f'<code>pip install git+{REPO}</code>, or the wheel from <a href="{rel}">the latest release</a>', "The SDK, CLI, Studio, Prompt UI and all 120 packs"),
        ("Full source zip", f'<a href="{rel}">AlgoLang_v{VERSION}.zip on GitHub Releases</a>', "Installers for Windows, Linux and macOS, examples, notebook and VS Code highlighting"),
        ("Language manual (PDF)", f'<a href="downloads/AlgoLang_Documentation_v{MINOR}.pdf">AlgoLang_Documentation_v{MINOR}.pdf</a>', "85 pages: language, runtime, enterprise edition, patterns, responsible AI"),
        ("Presentation (PDF)", '<a href="downloads/AlgoLang_Presentation.pdf">AlgoLang_Presentation.pdf</a>', "Slides comparing AlgoLang with other languages, with real applications"),
        ("Notebook", '<a href="downloads/AlgoLang_Notebook.ipynb">AlgoLang_Notebook.ipynb</a>', "Self-contained: upload to Google Colab and choose Run all"),
        ("Container", '<code>docker run --rm ghcr.io/drssnaiml1-cell/algolang doctor</code>', "The same toolchain on any machine"),
    ]
    trs = "".join(f"<tr><td>{a}</td><td>{b}</td><td class='small'>{c}</td></tr>" for a, b, c in rows)
    body = f"""<main><div class="pagehead"><div class="wrap"><h1>Downloads</h1><p>Version {VERSION}. See the <a href="changelog.html" style="color:#E2C25A">changelog</a> for what changed.</p></div></div>
<section class="band" style="padding-top:48px"><div class="wrap"><table class="dl"><thead><tr><th>What</th><th>Get it</th><th>Contains</th></tr></thead><tbody>{trs}</tbody></table>
<p style="margin-top:30px;color:var(--slate)">Live mode with real Claude models is optional: install the <code>anthropic</code> package (<code>pip install anthropic</code>) and set <code>ANTHROPIC_API_KEY</code>. Everything else runs offline.</p></div></section></main>"""
    return page("downloads.html", "Downloads · AlgoLang", body, "Download AlgoLang: Python package, source, manuals and notebook.")


# ═════════════════════════════════ build ═════════════════════════════════════
def build_playground_bundle(dst):
    import lark
    z = zipfile.ZipFile(dst / "algokit.zip", "w", zipfile.ZIP_DEFLATED)
    lark_dir = Path(lark.__file__).parent
    for f in lark_dir.rglob("*"):
        if f.is_file() and "__pycache__" not in f.parts and f.suffix in (".py", ".lark", ".typed"):
            z.write(f, "lark/" + f.relative_to(lark_dir).as_posix())
    for name in ("algoc.py", "algoruntime.py", "grammar.lark", "algolang/__init__.py", "algoagent.py"):
        z.write(ROOT / name, name)
    for f in (ROOT / "packs").rglob("*"):
        if f.is_file():
            z.write(f, f.relative_to(ROOT).as_posix())
    z.close()
    shutil.copy(WEB / "bridge.py", dst / "bridge.py")
    ex = []
    for title, src, inputs in EXAMPLES:
        source = (ROOT / src).read_text(encoding="utf-8") if src.endswith(".algo") else src
        ex.append(dict(title=title, source=source, inputs=inputs))
    (dst / "examples.json").write_text(json.dumps(ex, indent=1), encoding="utf-8")


def check_examples():
    """Every example must behave as labelled: compile cleanly, or fail on purpose."""
    for title, src, _ in EXAMPLES:
        source = (ROOT / src).read_text(encoding="utf-8") if src.endswith(".algo") else src
        try:
            al.compile(source, "example")
            ok = True
        except al.CompileError:
            ok = False
        if ok == ("on purpose" in title):
            raise SystemExit(f"example '{title}' does not behave as its title says")


def shrink(src, dst, width=1600):
    try:
        from PIL import Image
        im = Image.open(src)
        if im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        im.save(dst, optimize=True)
    except ImportError:
        shutil.copy(src, dst)


def main():
    check_examples()
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True)
    for f in (WEB / "assets").iterdir():
        shutil.copy(f, OUT / "assets" / f.name)
    (OUT / "assets" / "favicon.svg").write_text(LOGO.replace('aria-hidden="true"', 'xmlns="http://www.w3.org/2000/svg"')
                                                .replace("<svg ", '<svg style="background:#0E2140;border-radius:6px" ', 1),
                                                encoding="utf-8")
    shutil.copytree(ROOT / "packs", OUT / "packs")
    catalog = json.loads((ROOT / "packs" / "catalog.json").read_text(encoding="utf-8"))
    (OUT / "img").mkdir()
    for name in ("studio-domains", "prompt-answer", "studio-governance", "studio-run"):
        shrink(ROOT / "docs" / "images" / f"{name}.png", OUT / "img" / f"{name}.png")
    (OUT / "py").mkdir()
    build_playground_bundle(OUT / "py")
    dl = OUT / "downloads"
    dl.mkdir()
    for f in (ROOT / "docs" / f"AlgoLang_Documentation_v{MINOR}.pdf", ROOT / "slides" / "AlgoLang_Presentation.pdf",
              ROOT / "AlgoLang_Notebook.ipynb"):
        if f.exists():
            shutil.copy(f, dl / f.name)
        else:
            print(f"  ! missing {f.relative_to(ROOT)} (download link will be broken)")

    pages = {
        "index.html": home(catalog, run_hero()),
        "library.html": library(catalog),
        "playground.html": playground(),
        "downloads.html": downloads(),
        "guide.html": md_page("RUN_GUIDE.md", "guide.html", "Run guide · AlgoLang", "Install AlgoLang and run it in all three modes."),
        "developers.html": md_page("DEVELOPER_GUIDE.md", "developers.html", "Developer guide · AlgoLang",
                                   "Build with AlgoLang, extend the language, and release it."),
        "changelog.html": md_page("CHANGELOG.md", "changelog.html", "Changelog · AlgoLang", "What changed in each AlgoLang release."),
    }
    for name, content in pages.items():
        (OUT / name).write_text(content, encoding="utf-8")
    (OUT / "404.html").write_text(page("404.html", "Page not found · AlgoLang",
                                       '<main class="wrap" style="padding:90px 24px"><h1>That page is not here</h1>'
                                       '<p>Go to the <a href="index.html">overview</a> or the <a href="library.html">domain library</a>.</p></main>',
                                       "Page not found"), encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"✓ site built in {OUT.relative_to(ROOT)}/ — {len(pages) + 1} pages, {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
