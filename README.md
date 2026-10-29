# AlgoLang v0.2 Enterprise

[![CI](https://github.com/drssnaiml1-cell/algolang/actions/workflows/ci.yml/badge.svg)](https://github.com/drssnaiml1-cell/algolang/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/drssnaiml1-cell/algolang?color=c9a227)](https://github.com/drssnaiml1-cell/algolang/releases/latest)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-0e2140)](LICENSE)
[![AlgoProfessor](https://img.shields.io/badge/AlgoProfessor-www.algoprofessor.com-0e2140)](https://www.algoprofessor.com)
[![Lab website](https://img.shields.io/badge/lab-profagentlabs.algoprofessor.com-c9a227)](https://www.profagentlabs.algoprofessor.com)
[![Website](https://img.shields.io/badge/website-playground%20%C2%B7%20library-0e2140)](https://drssnaiml1-cell.github.io/algolang/)


**The AlgoProfessor agent-native programming language.**
AlgoProfessor AI R&D Solutions, Hyderabad. Designed by Dr. S. Satyanarayana.
🌐 **[www.algoprofessor.com](https://www.algoprofessor.com)**

AlgoLang has **no functions**. Every unit of work is an `agent` with a role, a goal, explicit tools, a model and a policy. A `flow` is the only other construct, and it can do just four things:

- call agents
- run them in parallel
- branch on a score
- emit results

## What's new in v0.2 Enterprise

- **120 ready-made domain packs** cover 20 sectors: healthcare, pharma, banking, insurance, capital markets, education, research, government, legal, HR, manufacturing, supply chain, retail, IT operations, cybersecurity, energy, agriculture, media, real estate and hospitality. Each pack is a governed multi-agent program built from one of four patterns: pipeline, fan-out, committee or router.
- **Modules.** `use "file.algo" as x` and `use pack insurance.claims_triage as claims` let you compose large systems from smaller ones (`claims.Intake(...)`).
- **Org policy** lives in `algo.config.json` and applies to every program. It sets forbidden attributes, token caps, human-review thresholds, allowed tools, concurrency and a run budget. When it differs from a program's own policy, **the stricter rule wins**.
- **Governance:**
  - a SHA-256 **hash-chained audit log**, so any edit or deletion is detected;
  - a **human review queue** with approve and reject, recorded with the reviewer's name;
  - usage and cost **reports**;
  - a SQLite **response cache**.
- **Executable tools.** Register your own Python functions as tools. Built-ins: `calc.eval`, `file.read`, `kb.search`. Live mode runs a real Claude tool-use loop, and an agent can only use tools it declares.
- **Scale.** `algo batch` and `Program.run_batch` process thousands of records in parallel, under one global concurrency limit.
- **Python SDK** (`import algolang`). The same engine drives all three modes.

## Three modes, one SDK

| Mode | Start it | What you get |
|---|---|---|
| **Command line** | `algo` (menu) · `algo shell` · `algo chat` · `algo run` · `algo batch` | Scripts, CI, batch jobs, a terminal prompt mode |
| **Graphical** | `algo studio` | Browser IDE: editor, run, agent graph, ✨ Ask AI, **Domains**, **Batch**, **Governance** tabs |
| **Prompt-based UI** | `algo ui` | Chat-style page: describe a problem in plain English and get a governed multi-agent solution, with every agent's work shown |

## Try it

- **In your browser, nothing to install:** the [playground](https://drssnaiml1-cell.github.io/algolang/playground.html) runs the real compiler and runtime locally.
- **With pip:** `pip install git+https://github.com/drssnaiml1-cell/algolang`, then `algo doctor`.
- **Windows / Linux / macOS installers:** download `AlgoLang_v0.2.0.zip` from [Releases](https://github.com/drssnaiml1-cell/algolang/releases/latest) and follow [RUN_GUIDE.md](RUN_GUIDE.md).
- **Browse the 120 domain packs:** [domain library](https://drssnaiml1-cell.github.io/algolang/library.html).

## Developers

[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) has three tracks:

1. **Application developers:** the SDK, company tools, `*.algotest.json` behaviour tests, and `algo dev ci`.
2. **Language contributors:** the architecture, recipes for new syntax, error codes, tools and packs, and the test suite.
3. **Maintainers:** CI, releases, the website and the container.

Start with [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
git clone https://github.com/drssnaiml1-cell/algolang && cd algolang
pip install -e ".[dev]"
make check        # ruff + pytest + lint of every .algo file
```

## Quick start

Full step-by-step instructions are in **RUN_GUIDE.md**.

```bash
# 1. install once:  Windows → double-click install.bat   ·   Linux/macOS → bash install.sh
# 2. start an enterprise project (config, plugin tool, knowledge base, sample program + data)
algo init acme && cd acme
algo domains "triage insurance claims"         # search the 120 domain packs
algo run pack:insurance.claims_triage --arg "claim=Rear-end collision, bumper damage"
algo batch programs/claims_ops.algo --input data/claims.csv --workers 16
algo review                                     # human review queue
algo audit verify                               # check every audit chain is intact
algo report                                     # usage, cost and governance summary
algo studio                                     # graphical mode
algo ui                                         # prompt-based mode
```

## Enterprise applications

[`enterprise-apps/`](enterprise-apps/) holds eight complete, governed multi-agent applications. Each has its own org policy, company tools over its own data, a knowledge base, programs, batch data and behaviour tests:

| Application | Sector | What it automates |
|---|---|---|
| [Claims Operations Center](enterprise-apps/claims-ops-center/) | Insurance | FNOL → policy check → fraud panel → SIU referral, or routing and payout |
| [Hospital Care Coordination](enterprise-apps/hospital-care-coordination/) | Healthcare | ER triage with the bed board, and discharge summaries (decision support) |
| [Bank Credit & Onboarding](enterprise-apps/bank-credit-onboarding/) | Banking | Bureau + DTI + credit committee; KYC with sanctions screening |
| [University Admissions & OBE](enterprise-apps/university-admissions-obe/) | Education | Fair admissions panel; NBA/NAAC CO-PO matrix and question papers |
| [SOC Incident Command](enterprise-apps/soc-incident-command/) | Cybersecurity | Alert enrichment (CMDB, threat intel) → severity → incident → runbook |
| [Supply Chain Control Tower](enterprise-apps/supply-chain-control-tower/) | Logistics | Shipment exceptions → tracking + stock cover → recovery plan |
| [Citizen Services Desk](enterprise-apps/citizen-services-desk/) | Government | Grievance routing with service-level targets; welfare pre-checks |
| [Legal Contract Desk](enterprise-apps/legal-contract-desk/) | Legal | NDA triage against the playbook; clause-by-clause contract review |

```bash
python enterprise-apps/run_all.py --batch      # run every app's tests and sample batch job
cd enterprise-apps/claims-ops-center && algo batch programs/claims_intake.algo --input data/claims_batch.csv
```

## ProfAlgoLabs™ website

The lab's 3D website lives in [`lab-website/`](lab-website/). It is ready to upload to cPanel at **[www.profagentlabs.algoprofessor.com](https://www.profagentlabs.algoprofessor.com)** and includes the 10 AlgoProfessor services, a secure contact form, a visitor counter, SEO files and security headers.

## Python SDK

```python
import algolang as al

al.configure(forbid=["salary", "caste"], min_human_below=0.75)       # org policy
best = al.domains.search("our servers are down")[0]                  # → itops.incident_triage
prog = al.pack(best["id"])
r = prog.run(incident="Login API returning 500 for all users")
print(r.status, r.values, r.stats)

results = prog.run_batch([{"incident": t} for t in tickets], workers=16)

@al.tool("company.directory", "Look up an employee's team")
def directory(query): ...

plan = al.compose("screen this CV fairly for a data analyst role")   # prompt → program
al.review.pending(); al.review.approve(item_id, reviewer="Dr. S")    # human in the loop
al.audit.verify("runs/claims_triage.audit.jsonl")                    # tamper check
```

## The language in one screen

```algo
model smart = "claude-sonnet-5-5"
tool  web.search

agent Researcher(topic: text) -> text {
    role  "Senior research analyst"
    goal  "Find five verified facts about {topic}"
    uses  web.search                 // capability must be declared
    model smart
    policy {
        budget tokens 6000
        retry 2
        require human when confidence < 0.70
        forbid gender, caste, religion
    }
}

flow main(topic: text) {
    facts = Researcher(topic)
    [a, b] = par { Writer(facts), Writer(facts, tone = "simple") }
    notes  = par for c in criteria { Reviewer(c, a) }
    if Reviewer(a) < 0.8 { a = Writer(facts) }
    emit a, b
}
```

**Types:** `text`, `score` (0–1), `list`, `json`, `bool`. Every agent call returns its value together with a confidence and provenance.

## Compile-time checks

| Code | Rule |
|---|---|
| E100 | Syntax error |
| E101 | Calling something that is not an agent (the core rule) |
| E102 | Wrong number or name of arguments |
| E103 | Undefined variable |
| E104 | Agent uses a tool that was never declared (no ambient capabilities) |
| E105 | Unknown type |
| E106 | Unknown model |
| E107 | Duplicate definition |
| E108 | Agent takes a policy-forbidden attribute as an input |
| E109 | Goal mentions a `{name}` that is not a parameter |
| E110 | Comparing a non-score value |
| E111 | No `flow main` |
| E112 | Agent without a goal |
| E113 | `[a, b] =` does not match the `par` block |
| E114 | `par for` over a non-list |
| E115 | Tool not allowed by the organisation policy (`allowed_tools`) |

v0.2 also reports errors from imported modules with the file name, catches circular `use` imports, and enforces the org config at compile time: a forbidden attribute or an ungranted tool is an error before anything runs.

## Runtime guarantees (`algoruntime.py`)

- **Policy enforcement:** token budget, retries, timeout, forbidden-attribute blocking, and a human-in-the-loop gate on low confidence.
- **Concurrency:** `par` and `par for` run on a thread pool.
- **Audit trail:** one JSONL record per agent call, holding the model, input hash, confidence, tokens, status, policy and tool calls. Records are hash-chained (`prev` → `hash`) and checked with `algo audit verify`.
- **Org policy:** `algo.config.json` is merged into every agent's policy (stricter wins). It also enforces a run-wide token cap and a list of allowed tools.
- **Human review queue:** escalated calls are written to an event-sourced queue (`algo review`, the Studio Governance tab, `al.review`).
- **Cache:** identical calls are answered from SQLite at zero tokens (`cache` policy, or `"cache": true` in the config).
- **Backends:**
  - `mock` (deterministic, offline) is for teaching and CI.
  - `live` calls Claude via the `anthropic` SDK.

## Files

```
RUN_GUIDE.md                  how to install and execute, step by step
algolang/__init__.py          Python SDK (import algolang)
algocli_ext.py                enterprise commands: init, domains, pack, batch, review, audit, report, chat
algoprompt.html               Prompt-based UI (algo ui)
packs/<sector>/*.algo         120 domain packs + packs/catalog.json
tools/make_packs.py           generator for the domain packs (add your own domains here)
tools/build_site.py, web/     the website and browser playground (GitHub Pages)
algodev.py                    developer track: algo dev lint | test | graph | new-tool | new-pack | ci
tests/                        pytest suite (run with make check)
pyproject.toml                packaging: pip install builds the algo command and the SDK
.github/workflows/            CI, releases, Pages and container publishing
DEVELOPER_GUIDE.md            application, contributor and maintainer tracks
AlgoLang_Notebook.ipynb       Jupyter / Google Colab notebook (self-contained)
algomagic.py                  %%algo notebook extension
algoshell.py                  interactive shell (algo shell)
algostudio.py, .html          AlgoLang Studio graphical IDE (algo studio): Domains, Batch, Governance tabs
algoagent.py                  AI program writer and wizard (algo ask, algo wizard)
install.bat / install.sh      one-time installers (Windows / Linux, macOS)
algo.bat / algo               the `algo` command
requirements*.txt             Python dependencies (lark; anthropic for --live)
Dockerfile                    container environment
grammar.lark                  formal grammar (Lark EBNF)
algoc.py                      compiler: parse → AST → checks → Python codegen
algoruntime.py                runtime engine
examples/*.algo               source programs (bad_example.algo shows every error)
vscode-algolang/              VS Code syntax highlighting
.vscode/tasks.json            Ctrl+Shift+B to run the open .algo file
```

## Roadmap

- **v0.2 (this release):** modules, org policy, 120 domain packs, a hash-chained audit log, a review queue, executable tools, batch processing, the SDK, and a Prompt UI.
- **v0.3:** `uncertain<T>` types, `eval` blocks with trace replay, MCP tool bindings, `cost` and `energy` budgets, and an LSP.
- **v1.0:** a native runtime, agent-to-agent typed messaging, a package registry, and SSO/RBAC for the Studio.
