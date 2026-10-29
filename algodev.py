"""algo dev — the developer track: lint, test, graph and scaffolding for AlgoLang projects.

    algo dev lint [PATH ...] [--json]           compile-check every .algo file (CI friendly)
    algo dev test [PATH ...] [--json]           run *.algotest.json specs against the offline backend
    algo dev graph FILE [--format mermaid|dot]  export a flow diagram for docs and pull requests
    algo dev new-tool NAME                      scaffold a Python tool plugin and its test spec
    algo dev new-pack SECTOR.NAME [--pattern P] scaffold a domain pack (pipe | fan | committee | router)
    algo dev ci                                 write a GitHub Actions workflow that lints and tests
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from algoc import CompileError, compile_source, flow_graph, load_program  # noqa: E402

SKIP_DIRS = {"build", "runs", ".venv", "venv", "node_modules", ".git", "__pycache__"}
GOLD, NAVY, RED, GREEN, DIM, END = "\033[33m", "\033[34m", "\033[31m", "\033[32m", "\033[2m", "\033[0m"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    GOLD = NAVY = RED = GREEN = DIM = END = ""


def _files(paths, pattern):
    out = []
    for p in (paths or ["."]):
        p = Path(p)
        if p.is_file():
            out.append(p)
            continue
        for f in sorted(p.rglob(pattern)):
            if not SKIP_DIRS & set(f.relative_to(p).parts[:-1]):
                out.append(f)
    return out


# ══════════════════════════════════ lint ═════════════════════════════════════
def lint(paths=None, as_json=False, expect_fail=("bad_example.algo",)):
    """Compile-check every .algo file. Files named in expect_fail must fail (they document errors)."""
    files = _files(paths, "*.algo")
    if not files:
        where = ", ".join(map(str, paths or ["."]))
        print(f"✗ no .algo files found in {where}. Pass a folder or file: algo dev lint programs/", file=sys.stderr)
        return 1
    report, bad = [], 0
    for f in files:
        try:
            src = f.read_text(encoding="utf-8")
            if re.search(r"\bflow\s+main\b", src):
                compile_source(src, f.name, f.resolve().parent)
            else:                                   # a module meant for `use`: no entry point needed
                _p, ds = load_program(src, f.name, f.resolve().parent, stack=(str(f.resolve()),), library=True)
                if ds:
                    raise CompileError(ds)
            ok, diags = True, []
        except CompileError as e:
            ok, diags = False, [dict(code=d.code, line=d.line, msg=d.msg, file=d.file or str(f)) for d in e.diags]
        expected_bad = f.name in expect_fail
        passed = ok != expected_bad
        bad += not passed
        report.append(dict(file=str(f), ok=ok, expected_failure=expected_bad, passed=passed, diagnostics=diags))
    if as_json:
        print(json.dumps(dict(files=len(files), failed=bad, results=report), indent=2))
    else:
        for r in report:
            if r["passed"]:
                note = f" {DIM}(fails on purpose){END}" if r["expected_failure"] else ""
                print(f"  {GREEN}✓{END} {r['file']}{note}")
            else:
                print(f"  {RED}✗{END} {r['file']}")
                for d in r["diagnostics"] or [dict(code="", line="", msg="expected errors but compiled cleanly")]:
                    print(f"      line {d['line']}: {d['code']} {d['msg'].splitlines()[0]}")
        print(f"\n  {len(files) - bad}/{len(files)} files pass" + (f"  ·  {RED}{bad} failing{END}" if bad else ""))
    return 1 if bad else 0


# ══════════════════════════════════ test ═════════════════════════════════════
def _load_program(spec_file: Path, ref: str):
    import algolang as al
    if ref.startswith("pack:"):
        return al.pack(ref[5:])
    p = (spec_file.parent / ref).resolve()
    return al.load(p)


def _check(case, res):
    """Return a list of failed expectations for one case."""
    e, fails = case.get("expect", {}), []
    want_status = e.get("status", "ok")
    if res.status != want_status:
        fails.append(f"status {res.status!r} (expected {want_status!r}){': ' + res.problem if res.problem else ''}")
    if "problem_contains" in e and e["problem_contains"].lower() not in (res.problem or "").lower():
        fails.append(f"problem does not mention {e['problem_contains']!r}")
    called = [c["agent"] for c in res.calls if c.get("status") != "blocked"]
    for a in e.get("agents_called", []):
        if a not in called:
            fails.append(f"agent {a} was not called")
    for a in e.get("agents_not_called", []):
        if a in called:
            fails.append(f"agent {a} was called but should not have been")
    if "max_tokens" in e and res.stats.get("tokens", 0) > e["max_tokens"]:
        fails.append(f"used {res.stats.get('tokens')} tokens (max {e['max_tokens']})")
    if "max_calls" in e and len(called) > e["max_calls"]:
        fails.append(f"{len(called)} agent calls (max {e['max_calls']})")
    if "emits" in e and len(res.values) != e["emits"]:
        fails.append(f"emitted {len(res.values)} values (expected {e['emits']})")
    if "max_escalated" in e and len(res.escalated) > e["max_escalated"]:
        fails.append(f"{len(res.escalated)} escalated (max {e['max_escalated']})")
    if "min_escalated" in e and len(res.escalated) < e["min_escalated"]:
        fails.append(f"{len(res.escalated)} escalated (min {e['min_escalated']})")
    if "min_confidence" in e:
        low = [c for c in res.calls if c.get("confidence") is not None and c["confidence"] < e["min_confidence"]]
        if low:
            fails.append(f"{low[0]['agent']} confidence {low[0]['confidence']} < {e['min_confidence']}")
    if "output_contains" in e:
        import algoruntime
        text = " ".join(str(algoruntime.Runtime.value(v)) for v in res.values)
        if e["output_contains"].lower() not in text.lower():
            fails.append(f"output does not contain {e['output_contains']!r}")
    if "tools_used" in e:
        used = {t.get("tool") for c in res.calls for t in (c.get("tool_calls") or [])}
        for t in e["tools_used"]:
            if t not in used:
                fails.append(f"tool {t} was not used")
    return fails


def test(paths=None, as_json=False, audit_dir=None):
    """Run every *.algotest.json spec. Uses the deterministic offline backend, so results are reproducible."""
    import tempfile
    specs = _files(paths, "*.algotest.json")
    if not specs:
        print("  no *.algotest.json files found — create one with:  algo dev new-tool NAME  (writes an example)")
        return 0
    audit_dir = audit_dir or tempfile.mkdtemp(prefix="algotest-")
    results, failed, t0 = [], 0, time.time()
    for spec_file in specs:
        try:
            spec = json.loads(spec_file.read_text(encoding="utf-8"))
            prog = _load_program(spec_file, spec["program"])
        except CompileError as e:
            results.append(dict(spec=str(spec_file), case="(compile)", passed=False,
                                failures=[f"{d.code} line {d.line}: {d.msg}" for d in e.diags]))
            failed += 1
            continue
        except Exception as e:  # noqa
            results.append(dict(spec=str(spec_file), case="(load)", passed=False, failures=[f"{type(e).__name__}: {e}"]))
            failed += 1
            continue
        for i, case in enumerate(spec.get("cases", []), 1):
            name = case.get("name", f"case {i}")
            try:
                res = prog.run(quiet=True, audit_dir=audit_dir, **case.get("inputs", {}))
                fails = _check(case, res)
            except Exception as e:  # noqa
                fails = [f"{type(e).__name__}: {e}"]
            failed += bool(fails)
            results.append(dict(spec=str(spec_file), case=name, passed=not fails, failures=fails))
    secs = time.time() - t0
    if as_json:
        print(json.dumps(dict(cases=len(results), failed=failed, seconds=round(secs, 2), results=results), indent=2))
    else:
        cur = None
        for r in results:
            if r["spec"] != cur:
                cur = r["spec"]
                print(f"  {NAVY}{cur}{END}")
            mark = f"{GREEN}✓{END}" if r["passed"] else f"{RED}✗{END}"
            print(f"    {mark} {r['case']}")
            for f in r["failures"]:
                print(f"        {RED}{f}{END}")
        print(f"\n  {len(results) - failed}/{len(results)} cases pass in {secs:.2f}s"
              + (f"  ·  {RED}{failed} failing{END}" if failed else ""))
    return 1 if failed else 0


# ══════════════════════════════════ graph ════════════════════════════════════
def graph(file, fmt="mermaid"):
    f = Path(file)
    prog, _ = load_program(f.read_text(encoding="utf-8"), f.name, f.resolve().parent)
    nodes, edges = flow_graph(prog)
    if fmt == "dot":
        out = ["digraph algolang {", '  rankdir=TB; node [fontname="Helvetica", style="rounded,filled"];']
        style = {"input": 'shape=box, fillcolor="#f4ecd2"', "emit": 'shape=box, fillcolor="#f4ecd2"',
                 "par": 'shape=box, fillcolor="#0b1f3a", fontcolor=white, color="#c9a227", penwidth=2',
                 "cond": 'shape=diamond, fillcolor="#fff7e0"'}
        default = 'shape=box, fillcolor="#0b1f3a", fontcolor=white'
        for nid, label, kind, _sub in nodes:
            out.append(f'  {nid} [label="{label}", {style.get(kind, default)}];')
        for a, b, dashed in edges:
            out.append(f"  {a} -> {b}{' [style=dashed]' if dashed else ''};")
        out.append("}")
    else:
        out = ["flowchart TD"]
        shape = {"input": ("([", "])"), "emit": ("([", "])"), "cond": ("{", "}")}
        for nid, label, kind, _sub in nodes:
            o, c = shape.get(kind, ("[", "]"))
            out.append(f'    {nid}{o}"{label}"{c}')
        for a, b, dashed in edges:
            out.append(f"    {a} {'-.->' if dashed else '-->'} {b}")
        out.append("    classDef agent fill:#0b1f3a,color:#fff,stroke:#0b1f3a")
        out.append("    classDef par fill:#0b1f3a,color:#fff,stroke:#c9a227,stroke-width:3px")
        out.append("    classDef io fill:#f4ecd2,color:#0b1f3a,stroke:#c9a227")
        for kind, cls in (("agent", "agent"), ("branch", "agent"), ("par", "par"), ("input", "io"), ("emit", "io")):
            ids = [n[0] for n in nodes if n[2] == kind]
            if ids:
                out.append(f"    class {','.join(ids)} {cls}")
    print("\n".join(out))
    return 0


# ══════════════════════════════════ scaffolds ════════════════════════════════
TOOL_TEMPLATE = '''"""{name} — a company tool for AlgoLang agents.

Agents may call it only if they declare it:   tool {name}   …   uses {name}
List this file under "plugins" in algo.config.json so every program can use it.
"""
import algoruntime as rt


@rt.register_tool("{name}", "{desc}")
def {fn}(query: str) -> str:
    """Receives the agent's request text; return a short string the agent can use."""
    # TODO: call your real system here (database, REST API, search index …)
    return f"{name}: no data yet for {{query[:60]}}"
'''

TOOL_PROGRAM = '''// Exercises the {name} tool. Run:  algo dev test
tool {name}

agent Helper(question: text) -> text {{
    role  "Assistant that uses {name}"
    goal  "Answer using {name}: {{question}}"
    uses  {name}
}}

flow main(question: text) {{
    answer = Helper(question)
    emit answer
}}
'''

PATTERNS = {
    "pipe": '''flow main({inp}: text) {{
    a = Intake({inp})
    b = Analyst(a)
    c = Writer(b)
    emit c
}}''',
    "fan": '''flow main({inp}: text) {{
    views = par {{ Intake({inp}), Analyst({inp}) }}
    c = Writer(views)
    emit c
}}''',
    "committee": '''flow main({inp}: text) {{
    views = par {{ Intake({inp}), Analyst({inp}) }}
    s = Panel(views)
    c = Writer(views)
    emit c, s
}}''',
    "router": '''flow main({inp}: text) {{
    s = Panel({inp})
    if s > 0.5 {{
        c = Analyst({inp})
        emit c
    }}
    c = Writer({inp})
    emit c
}}''',
}

PACK_TEMPLATE = '''// {title}
// AlgoLang domain pack {pid} · pattern: {pattern} · created with `algo dev new-pack`
// Use it from any program:   use pack {pid} as {alias}      (set ALGO_PACKS to this packs/ folder)

model smart = "claude-sonnet-5-5"
model fast  = "claude-haiku-5-5"

policy {{
    budget tokens 4000
    retry 1
    require human when confidence < 0.80
}}

agent Intake({inp}: text) -> text {{
    role  "Intake specialist, {title}"
    goal  "Extract the key facts from: {{{inp}}}"
    model fast
}}

agent Analyst(facts: text) -> text {{
    role  "Domain analyst, {title}"
    goal  "Analyse and recommend next steps for: {{facts}}"
    model smart
}}

agent Panel(views: text) -> score {{
    role  "Review panel, {title}"
    goal  "Score 0 to 1 how strong the case is: {{views}}"
}}

agent Writer(analysis: text) -> text {{
    role  "Report writer, {title}"
    goal  "Write a short, plain-English summary of: {{analysis}}"
}}

{flow}
'''


def new_tool(name):
    if not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", name):
        print("✗ tool names look like  company.directory  (lowercase, dotted)", file=sys.stderr)
        return 1
    fn = name.replace(".", "_")
    plug = Path("plugins") / f"{fn}.py"
    prog = Path("programs") / f"use_{fn}.algo"
    spec = Path("tests") / f"{fn}.algotest.json"
    for p in (plug, prog, spec):
        if p.exists():
            print(f"✗ {p} already exists", file=sys.stderr)
            return 1
        p.parent.mkdir(parents=True, exist_ok=True)
    plug.write_text(TOOL_TEMPLATE.format(name=name, fn=fn, desc=f"Look up information in {name}"), encoding="utf-8")
    prog.write_text(TOOL_PROGRAM.format(name=name), encoding="utf-8")
    spec.write_text(json.dumps({
        "program": f"../programs/use_{fn}.algo",
        "cases": [{"name": f"Helper calls {name}", "inputs": {"question": "Who owns the payroll system?"},
                   "expect": {"status": "ok", "agents_called": ["Helper"], "tools_used": [name], "max_tokens": 1500}}],
    }, indent=2) + "\n", encoding="utf-8")
    cfg = Path("algo.config.json")
    if cfg.exists():
        data = json.loads(cfg.read_text(encoding="utf-8"))
        plugins = data.setdefault("plugins", [])
        if str(plug) not in plugins:
            plugins.append(str(plug).replace(os.sep, "/"))
        allowed = data.get("policy", {}).get("allowed_tools", data.get("allowed_tools"))
        if isinstance(allowed, list) and name not in allowed:
            allowed.append(name)
        cfg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"  ✓ registered in {cfg}")
    else:
        print(f"  • no algo.config.json here: add \"plugins\": [\"{plug.as_posix()}\"] to one (algo init makes it)")
    for p in (plug, prog, spec):
        print(f"  ✓ {p}")
    print("\n  next:  edit the plugin, then  algo dev test")
    return 0


def new_pack(pid, pattern="pipe", inp="request", out_dir="packs"):
    m = re.fullmatch(r"([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)", pid)
    if not m:
        print("✗ pack ids look like  sector.name  e.g. logistics.customs_check", file=sys.stderr)
        return 1
    if pattern not in PATTERNS:
        print(f"✗ pattern must be one of: {', '.join(PATTERNS)}", file=sys.stderr)
        return 1
    sector, name = m.groups()
    title = name.replace("_", " ").capitalize()
    src = PACK_TEMPLATE.format(title=title, pid=pid, alias=name.split("_")[0], pattern=pattern, inp=inp,
                               flow=PATTERNS[pattern].format(inp=inp))
    compile_source(src, f"{name}.algo")          # every scaffold must compile
    path = Path(out_dir) / sector / f"{name}.algo"
    if path.exists():
        print(f"✗ {path} already exists", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(src, encoding="utf-8")
    spec = Path("tests") / f"{sector}_{name}.algotest.json"
    spec.parent.mkdir(parents=True, exist_ok=True)
    rel = os.path.relpath(path, spec.parent).replace(os.sep, "/")
    spec.write_text(json.dumps({"program": rel, "cases": [
        {"name": "runs end to end", "inputs": {inp: f"Sample {title.lower()} request"},
         "expect": {"status": "ok", "max_tokens": 4000}}]}, indent=2) + "\n", encoding="utf-8")
    print(f"  ✓ {path}\n  ✓ {spec}")
    print(f"\n  use it:  ALGO_PACKS={Path(out_dir).resolve()}   then   use pack {pid} as x")
    return 0


CI_WORKFLOW = """name: AlgoLang checks
on: [push, pull_request]
jobs:
  algolang:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "algolang @ git+https://github.com/drssnaiml1-cell/algolang"
      - name: Lint every .algo file
        run: algo dev lint .
      - name: Run behaviour specs (offline, deterministic)
        run: algo dev test .
      - name: Verify audit chains
        run: algo audit verify runs || true
"""


def write_ci():
    p = Path(".github/workflows/algolang.yml")
    if p.exists():
        print(f"✗ {p} already exists", file=sys.stderr)
        return 1
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(CI_WORKFLOW, encoding="utf-8")
    print(f"  ✓ {p}  — every push and pull request now lints and tests your AlgoLang programs")
    return 0


# ══════════════════════════════════ CLI ══════════════════════════════════════
def add_parser(sub):
    s = sub.add_parser("dev", help="developer track: lint, test, graph, scaffold tools and packs, CI")
    d = s.add_subparsers(dest="dev_cmd")
    x = d.add_parser("lint", help="compile-check every .algo file")
    x.add_argument("paths", nargs="*")
    x.add_argument("--json", action="store_true")
    x = d.add_parser("test", help="run *.algotest.json behaviour specs")
    x.add_argument("paths", nargs="*")
    x.add_argument("--json", action="store_true")
    x = d.add_parser("graph", help="export a flow diagram (Mermaid or Graphviz)")
    x.add_argument("file")
    x.add_argument("--format", choices=["mermaid", "dot"], default="mermaid")
    x = d.add_parser("new-tool", help="scaffold a Python tool plugin + test spec")
    x.add_argument("name")
    x = d.add_parser("new-pack", help="scaffold a domain pack + test spec")
    x.add_argument("id")
    x.add_argument("--pattern", choices=list(PATTERNS), default="pipe")
    x.add_argument("--input", default="request")
    d.add_parser("ci", help="write a GitHub Actions workflow for this project")
    return s


def dispatch(a):
    c = a.dev_cmd
    if c == "lint":
        return lint(a.paths, a.json)
    if c == "test":
        return test(a.paths, a.json)
    if c == "graph":
        return graph(a.file, a.format)
    if c == "new-tool":
        return new_tool(a.name)
    if c == "new-pack":
        return new_pack(a.id, a.pattern, a.input)
    if c == "ci":
        return write_ci()
    print(__doc__)
    return 0
