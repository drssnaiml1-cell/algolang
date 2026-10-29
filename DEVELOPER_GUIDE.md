# AlgoLang Developer Guide

This guide is the **developer track**. It is for people who build *with* AlgoLang (company tools, domain packs, tested programs in CI) and for people who build *on* AlgoLang itself (the compiler, runtime, SDK and UIs).

| Track | You want to… | Start at |
|---|---|---|
| **A. Application developer** | ship governed multi-agent programs in your organisation | [§1](#1-application-developer-track) |
| **B. Language contributor** | change the compiler, runtime, SDK, Studio or Prompt UI | [§2](#2-language-contributor-track) |
| **C. Maintainer** | review, release and deploy | [§3](#3-maintainer-track-releases-and-deployment) |

---

## 1. Application developer track

### 1.1 Install

```bash
pip install "algolang @ git+https://github.com/drssnaiml1-cell/algolang"           # latest main
pip install "algolang[live] @ git+https://github.com/drssnaiml1-cell/algolang@v0.2.0"  # a release, with live Claude support
algo doctor
```

Or download the wheel from the [Releases](https://github.com/drssnaiml1-cell/algolang/releases) page: `pip install algolang-0.2.0-py3-none-any.whl`. Python 3.9 or newer is required.

### 1.2 Project layout

```bash
algo init acme && cd acme
```

```
acme/
  algo.config.json          org policy: forbid, budgets, review threshold, allowed tools, plugins
  plugins/                  your Python tools (algo dev new-tool)
  packs/                    your own domain packs (algo dev new-pack); point ALGO_PACKS here
  programs/                 your .algo programs
  tests/                    *.algotest.json behaviour specs (algo dev test)
  kb/                       documents searched by the kb.search tool
  data/                     CSVs for algo batch
  .github/workflows/        CI (algo dev ci)
```

### 1.3 The developer loop

```bash
algo dev new-tool company.payroll          # plugin + example program + test spec, registered in the config
algo dev new-pack logistics.customs_check --pattern committee --input shipment
algo dev lint .                            # compile-check every .algo file (exit 1 on any error)
algo dev test .                            # run every *.algotest.json spec, offline and deterministic
algo dev graph programs/claims_ops.algo    # Mermaid diagram for a pull request (or --format dot)
algo dev ci                                # GitHub Actions workflow running lint + test on each push
```

`lint` treats a file without `flow main` as a **module**, meant for `use "file.algo" as x`, so library files pass too. `examples/bad_example.algo` is expected to fail, because it documents the errors.

### 1.4 Writing a company tool

```python
# plugins/company_payroll.py
import algoruntime as rt

@rt.register_tool("company.payroll", "Look up payroll facts for an employee ID")
def payroll(query: str) -> str:
    return my_hr_api.lookup(query)          # return a short string; errors are caught and logged
```

Tools are capabilities. An agent can call a tool only if **all three** of these hold:

1. The program declares it with `tool company.payroll`.
2. The agent lists it under `uses company.payroll`. Otherwise the compiler reports **E104**.
3. The organisation allows it in `algo.config.json` → `policy.allowed_tools`. Otherwise the compiler reports **E115**, and the runtime blocks the call.

In live mode a model asking for an undeclared tool is refused, and the refusal is recorded (`"refused": true`) in the audit log.

### 1.5 Behaviour tests: `*.algotest.json`

Specs run against the deterministic offline backend, so they are fast, free and repeatable in CI.

```json
{
  "program": "../programs/claims_ops.algo",
  "cases": [
    {
      "name": "simple claim is routed",
      "inputs": { "claim": "Rear-end collision, bumper damage" },
      "expect": {
        "status": "ok",
        "agents_called": ["claims.Intake", "Router"],
        "tools_used": ["company.directory"],
        "max_tokens": 3000,
        "max_escalated": 1,
        "emits": 3
      }
    },
    {
      "name": "forbidden attribute never reaches an agent",
      "inputs": { "claim": "..." },
      "expect": { "status": "blocked", "problem_contains": "forbidden" }
    }
  ]
}
```

`"program"` may also be `"pack:insurance.claims_triage"`.

| Expectation | Meaning |
|---|---|
| `status` | `ok`, `blocked` (policy) or `failed` |
| `problem_contains` | text expected in the block or failure message |
| `agents_called` / `agents_not_called` | which agents ran |
| `tools_used` | tools that must have been called |
| `max_tokens`, `max_calls` | cost ceilings |
| `emits` | number of emitted values |
| `min_escalated`, `max_escalated` | how many results went to human review |
| `min_confidence` | every call at or above this confidence |
| `output_contains` | text expected in the emitted values |

### 1.6 Using the SDK in your own services

```python
import algolang as al

al.configure(policy={"forbid": ["caste", "religion"], "min_human_below": 0.8}, max_concurrency=8)
claims = al.load("programs/claims_ops.algo")

def handle(request_json):                      # e.g. inside a FastAPI / Flask route
    r = claims.run(claim=request_json["text"], live=True)
    return {"status": r.status, "values": r.to_dict()["values"], "needs_review": bool(r.escalated)}
```

`Program.run_batch(rows, workers=16)` runs many records in parallel. All model calls in the process share the `max_concurrency` limit.

---

## 2. Language contributor track

### 2.1 Set up

```bash
git clone https://github.com/drssnaiml1-cell/algolang && cd algolang
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev,live]"
make check                                               # lint + tests + .algo lint, as CI runs them
```

Without `make`, run `ruff check . && pytest && python algoc.py dev lint examples packs`.

### 2.2 Architecture

```
            ┌───────────── three modes ─────────────┐
 CLI (algoc.py, algocli_ext.py, algodev.py, algoshell.py)
 Studio (algostudio.py + algostudio.html)     Prompt UI (algoprompt.html, algocli_ext.cmd_chat)
            └──────────────┬───────────────────────┘
                     SDK  algolang/__init__.py   Program · RunResult · domains · compose · audit · review
                           │
   source ─► grammar.lark ─► Lark Earley parser ─► AST (algoc.to_ast) ─► Checker (E100–E115)
             ─► use/imports (load_program) ─► CodeGen ─► Python module ─► algoruntime.Runtime
                                                                            │
          policies · org config · tools · Mock/Claude backends · cache · hash-chained audit · review queue
```

| File | Responsibility |
|---|---|
| `grammar.lark` | The formal grammar. Every syntax change starts here |
| `algoc.py` | Parser, AST builder, `Checker`, module loader, `CodeGen`, CLI entry and menu |
| `algoruntime.py` | `Runtime`, policy merge (stricter wins), backends, tools, cache, audit chain, review queue, org config |
| `algolang/__init__.py` | Public SDK. Anything a UI does must be possible here first |
| `algocli_ext.py` | Enterprise CLI commands (`init`, `domains`, `batch`, `review`, `audit`, `report`, `chat`) |
| `algodev.py` | Developer track (`algo dev …`) |
| `algostudio.py` / `.html` | Studio HTTP API (`ROUTES`) and single-page IDE |
| `algoprompt.html` | Prompt UI page (uses `/api/compose`, `/api/run`) |
| `algoagent.py` | `algo ask` (AI writes and repairs programs) and the wizard |
| `algomagic.py` | `%%algo` Jupyter magic |
| `tools/make_packs.py` | Generator for the 120 domain packs and `packs/catalog.json` |

**Design rules:**

- **Agents are the only callable.** No functions, no ambient capabilities.
- **Governance is enforced by the compiler where possible and by the runtime always.** A rule enforced in only one place is a bug.
- **Org policy can only tighten.** `merge_policy` and `Runtime.effective_policy` must never relax a rule.
- **The offline backend stays deterministic.** Tests and lessons depend on it.
- **SDK first.** CLI, Studio and Prompt UI are thin layers over `algolang`.

### 2.3 Recipes

**Add a compile-time check (a new error code):**

1. Add the check in `Checker` (`algoc.py`) with `self.err("E116", line, "message that says how to fix it")`.
2. Add a failing example to `tests/test_compiler.py::test_each_error_code`.
3. Document it in `README.md`, `docs/chapters/09-errors.tex` (`\errhead{E116}{…}`) and `docs/chapters/B-reference.tex`.

**Add syntax:**

1. Change `grammar.lark`.
2. Handle the new tree in `to_ast`.
3. Check it in `Checker`.
4. Emit it in `CodeGen`.
5. Add compiler tests, plus a program in `examples/` that uses it.
6. Update `vscode-algolang/` highlighting if new keywords appear.

**Add a built-in tool:** `register_tool` in `algoruntime.py`, next to `calc.eval`. Keep it side-effect-free, or restricted to a configured root (see `file.read`). Add a test in `tests/test_runtime.py`.

**Add or change domain packs:** edit the `DOMAINS` table in `tools/make_packs.py` (one line per pack: `id|title|input|risk|people|shape|tools|Agent=goal;…|description`), then run:

```bash
python tools/make_packs.py          # regenerates packs/<sector>/*.algo and packs/catalog.json; every pack is compiled first
pytest tests/test_sdk.py            # includes "every pack runs" and the search battery
```

If people will describe the new domain in everyday words, add them to `_SYN` / `SECTOR_HINTS` in `algolang/__init__.py`, and add a query to `test_search_finds_the_right_domain`.

**Add a Studio / Prompt UI endpoint:**

1. Write `api_x(body)` in `algostudio.py` and add it to `ROUTES`. If it is a GET, also add it to the GET list.
2. Call the SDK; don't re-implement logic.
3. Add a test in `tests/test_studio.py`.
4. The server binds `127.0.0.1` and rejects foreign `Origin` headers. Never weaken either.

**Add a CLI command:** add the parser in `algoc.main` (or in `algodev.add_parser` for `algo dev …`), implement it in `algocli_ext.py`/`algodev.py`, add a test in `tests/test_cli.py`, and document it in `RUN_GUIDE.md`.

### 2.4 Tests

```bash
pytest                       # everything (~15 s)
pytest -m "not slow"         # skip "every pack runs"
pytest tests/test_audit.py   # one area
pytest --cov=. --cov-report=term-missing
algo dev test tests/specs    # behaviour specs for the examples and a pack from several sectors
```

`tests/specs/` holds the project's own `*.algotest.json` behaviour specs. They cover the research-brief and paper-review examples, the enterprise module program, and packs from six sectors, plus two **fairness cases** that must stay `blocked`: author nationality in paper review, and caste in a CV. CI runs them in the lint job, and a failing case fails the build. When you change a pack or the runtime, add or update a spec next to the pytest change.

The `project` fixture in `tests/conftest.py` gives each test its own temporary folder, audit directory and fresh config. Tests never touch your real `runs/`. Live-mode code is tested with fake Anthropic clients (`test_ungranted_tool_is_refused_by_live_loop`), so CI needs no API key.

### 2.5 Style

- Python 3.9+, standard library first; the only runtime dependency is `lark`.
- `ruff check .` must pass (config in `pyproject.toml`); line length 120.
- Error messages say **what is wrong and how to fix it**, in plain English.
- UI: navy `#0b1f3a` and gold `#c9a227`; no external CDNs in Studio or the Prompt UI (they work offline).

### 2.6 Pull requests

1. Branch from `main` (`feature/…`, `fix/…`, `docs/…`).
2. Keep each PR to one change, and include tests and docs.
3. Run `make check` locally. CI runs it on Linux, macOS and Windows with Python 3.9–3.13.
4. Fill in the PR template checklist, especially the **governance impact** section.

---

## 3. Maintainer track: releases and deployment

### 3.1 What the GitHub workflows do

| Workflow | Trigger | Does |
|---|---|---|
| `ci.yml` | every push and PR | ruff and `.algo` lint · behaviour specs (`tests/specs`) · pytest on Python 3.9–3.13 (Ubuntu) plus macOS and Windows · wheel build and install smoke test · notebook execution · website build |
| `release.yml` | tag `v*` | builds wheel, sdist, `AlgoLang_vX.Y.Z.zip` and the PDF manuals, then publishes a GitHub Release with them |
| `pages.yml` | push to `main` | runs `tools/build_site.py` and deploys the website to GitHub Pages: overview, domain library, browser playground, guides, downloads |
| `docker.yml` | tag `v*` / manual | builds the container and pushes it to `ghcr.io/drssnaiml1-cell/algolang` |

### 3.2 Cutting a release

```bash
# 1. bump the version in pyproject.toml, algoruntime.VERSION / algoc.VERSION, and CHANGELOG.md
# 2. make check
git commit -am "Release v0.2.1"
git tag -a v0.2.1 -m "AlgoLang v0.2.1"
git push origin main --tags        # release.yml does the rest
```

### 3.3 One-time repository settings

- **Settings → Pages → Source: GitHub Actions** (for `pages.yml`).
- **Settings → Actions → General → Workflow permissions: Read and write** (Releases and GHCR need it).
- Optional: **Settings → Secrets → `ANTHROPIC_API_KEY`**, only if you add live smoke tests. CI never needs it.
- Optional: branch protection on `main` requiring the `CI` checks.

### 3.4 The website

The site lives in `web/` (styles, scripts and the playground bridge) and is assembled by `tools/build_site.py`:

```bash
pip install markdown pillow          # pillow is optional: it shrinks screenshots
python tools/build_site.py           # → site/
python -m http.server -d site 8000   # preview at http://localhost:8000
```

- **Home page:** the hero program is run at build time. The output shown under it is a real run, so it never drifts from the code.
- **Domain library** reads `packs/catalog.json`. A new pack appears there automatically.
- **Guides** are rendered from `RUN_GUIDE.md`, `DEVELOPER_GUIDE.md` and `CHANGELOG.md`. Edit the Markdown, not the HTML.
- **Playground** runs the real compiler and runtime in the browser with [Pyodide](https://pyodide.org). The build packs `lark`, `algoc.py`, `algoruntime.py`, the SDK and all packs into `site/py/algokit.zip`, and `web/bridge.py` connects them to the page. Nothing a visitor types leaves their browser. Pyodide has no threads and no `sqlite3`: the runtime detects both (`CAN_THREAD`, and the in-memory cache fallback), and `tests/test_runtime.py` covers each case. Every example in the playground menu is compiled during the build, and the build fails if one does not behave as its title says.

### 3.5 Publishing to PyPI (optional)

The wheel on each GitHub Release is installable as it is. To publish on PyPI, set up a [trusted publisher](https://docs.pypi.org/trusted-publishers/) for this repo, then uncomment the `pypi` job in `release.yml`.
