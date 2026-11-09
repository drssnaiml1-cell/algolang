<p align="center">
  <a href="https://www.algoprofessor.com"><img src="docs/images/algolang-logo.svg" alt="AlgoLang logo" width="132" height="132"></a>
</p>

<h1 align="center">AlgoLang</h1>

<h3 align="center">Write AI systems as agents, not functions. Every decision governed, explained, signed and tested before it ships. Build AI you can prove is trustworthy.</h3>

<p align="center">
  <img src="https://skillicons.dev/icons?i=py,vscode,docker,githubactions,latex,sqlite,linux,windows,apple&perline=9" alt="Python, VS Code, Docker, GitHub Actions, LaTeX, SQLite, Linux, Windows, macOS">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Claude-models-c9a227?style=for-the-badge&logo=anthropic&logoColor=white" alt="Claude models">
  <img src="https://img.shields.io/badge/MCP-tools-0e2140?style=for-the-badge" alt="Model Context Protocol tools">
  <img src="https://img.shields.io/badge/Qiskit-quantum-6929C4?style=for-the-badge&logo=qiskit&logoColor=white" alt="Qiskit">
  <img src="https://img.shields.io/badge/OpenQASM-2.0-0e2140?style=for-the-badge" alt="OpenQASM 2.0">
  <img src="https://img.shields.io/badge/Jupyter-Colab-F37626?style=for-the-badge&logo=jupyter&logoColor=white" alt="Jupyter and Colab">
  <img src="https://img.shields.io/badge/Ed25519-signed%20audit-0e2140?style=for-the-badge" alt="Ed25519 signed audit">
</p>

<p align="center">
  <a href="https://github.com/drssnaiml1-cell/algolang/actions/workflows/ci.yml"><img src="https://github.com/drssnaiml1-cell/algolang/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/drssnaiml1-cell/algolang/releases/latest"><img src="https://img.shields.io/github/v/release/drssnaiml1-cell/algolang?color=c9a227" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-0e2140" alt="License: Apache 2.0"></a>
  <a href="https://drssnaiml1-cell.github.io/algolang/"><img src="https://img.shields.io/badge/website-playground%20%C2%B7%20library-0e2140" alt="Website"></a>
  <a href="https://www.algoprofessor.com"><img src="https://img.shields.io/badge/by-algoprofessor.com-c9a227" alt="AlgoProfessor"></a>
</p>

<p align="center">
  <b>The AlgoProfessor agent-native programming language</b><br>
  AlgoProfessor AI R&amp;D Solutions, Hyderabad · Designed by Dr. S. Satyanarayana · <a href="https://www.algoprofessor.com">www.algoprofessor.com</a>
</p>

<p align="center">
  <a href="https://www.algoprofessor.com"><img src="docs/images/algolang-hero.svg" alt="AlgoLang: an order event from AlgoPulse flows through parallel Quote and Limits agents, a deterministic BREACH guard, and an uncertain RiskGate agent with a human gate; every call is written to a hash-chained audit log" width="100%"></a>
</p>

**Current version: 0.4.1** (Trustworthy AI: risk levels · fairness and robustness tests · signed audit · system cards · trust reports · LLM & SLM graph optimisation) · [Changelog](CHANGELOG.md) · [Roadmap](ROADMAP.md) · [50 Sample Programs (PDF)](docs/AlgoLang_50_Sample_Programs.pdf) · [Language manual (PDF)](docs/AlgoLang_Documentation_v0.4.pdf)

AlgoLang has **no functions**. Every unit of work is an `agent` with a role, a goal, explicit tools, a model and a policy. A `flow` is the only other construct, and it can do just four things:

- call agents
- run them in parallel
- branch on a score
- emit results

## AlgoLang at a glance

```mermaid
flowchart TB
    subgraph DOORS["① Five ways in — one engine"]
        direction LR
        CLI["⌨️ algo CLI"] ~~~ STU["🖥️ Studio"] ~~~ PUI["💬 Prompt UI"] ~~~ SDK["🐍 Python SDK"] ~~~ LSP["🧩 VS Code · LSP"]
    end
    subgraph COMPILER["② Compiler · algoc.py — unsafe programs never run"]
        direction LR
        SRC[".algo source"] --> PARSE["Lark grammar"] --> AST["AST"] --> CHK{{"Checker · E100–E130"}} --> GEN["Python code"]
    end
    subgraph RUNTIME["③ Runtime · algoruntime.py — every call governed"]
        direction LR
        POL["policies · budgets<br/>$ ₹ Wh CO₂"] --> CALL(("agent<br/>call")) --> GATE{"confidence<br/>≥ gate?"}
        GATE -- yes --> OUT["emit"]
        GATE -- no --> HUM["👤 review queue"]
        CALL --> AUD[("hash-chained<br/>audit log")]
    end
    subgraph WORLD["④ Connected systems"]
        direction LR
        LLM["Claude · mock · replay"] ~~~ MCP["MCP tool servers"] ~~~ KAF["⚡ AlgoPulse™<br/>real-time events"] ~~~ QPU["⚛️ Quantum tools<br/>simulator · Qiskit"]
    end
    DOORS ==> COMPILER ==> RUNTIME <==> WORLD

    classDef navy fill:#0e2140,stroke:#c9a227,color:#f4f1e8;
    classDef gold fill:#c9a227,stroke:#0e2140,color:#0e2140;
    class CLI,STU,PUI,SDK,LSP,SRC,PARSE,AST,GEN,POL,OUT,LLM,MCP,KAF,QPU,HUM,AUD navy;
    class CHK,CALL,GATE gold;
```

| | |
|---|---|
| **Write** agents and flows; the compiler rejects unsafe programs before anything runs (25 error codes). | **Govern** every call with budgets, forbidden attributes, allowed tools and a human gate. |
| **Prove** what happened: hash-chained audit logs, traces you can replay for free, `eval` blocks in CI. | **Scale** to real time: a `stream` block runs a flow for every event on an AlgoPulse™ topic. |
| **Optimise** with quantum tools: every QAOA answer is VERIFIED against the exact optimum before an agent acts on it. | **Connect** to Claude, MCP tool servers, AlgoPulse™ buses and quantum backends, from the CLI, Studio, SDK or your editor. |

## Contents

1. [Objective](#1-objective)
2. [Design principles](#2-design-principles)
3. [What's new in v0.4: Trustworthy AI](#3-whats-new-in-v04-trustworthy-ai)
4. [Get started](#4-get-started)
5. [Learn by example: 50 sample programs](#5-learn-by-example-50-sample-programs)
6. [Enterprise applications](#6-enterprise-applications)
7. [Real-time events: AlgoPulse™](#7-real-time-events-algopulse)
8. [Quantum applications](#8-quantum-applications)
9. [The language](#9-the-language)
10. [Governance and runtime guarantees](#10-governance-and-runtime-guarantees)
11. [Python SDK](#11-python-sdk)
12. [For developers](#12-for-developers)
13. [Roadmap: v0.5 Quantum AI, v0.6 Interoperability, v1.0](#13-roadmap-v05-quantum-ai-v06-interoperability-v10)
14. [Repository layout](#14-repository-layout)
15. [Author and licence](#15-author-and-licence)

## 1. Objective

<p align="center"><img src="docs/images/sections/01-objective.svg" alt="Ten objectives of AlgoLang" width="100%"></p>

### Main objective

**To make AI systems built from agents safe, governed, auditable and trustworthy.** AlgoLang does this by giving them a language of their own, in which the only unit of work is an agent, the only way to combine agents is a flow, and the rules that keep people safe are part of the program text. The compiler and runtime enforce them.

### Basic objectives

| No. | Objective | What it means in the language |
|---|---|---|
| 1 | Agent-native design | There are no functions. Every task is an agent with a role, a goal, declared tools, a model and a policy. |
| 2 | Small, readable control flow | A flow can only call agents, run them in parallel, branch, and emit results. Anyone can read what happens and in what order. |
| 3 | Safety before running | The compiler finds the mistakes: calling a non-agent, using an undeclared tool, passing a forbidden attribute, or comparing an uncertain value without its confidence. |
| 4 | Governance built in | Token, cost and energy budgets, retries, forbidden attributes and human review are part of the program; an organisation file adds stricter rules for every program. |
| 5 | Accountability | Every agent call returns a value with its confidence and provenance, and is written to a hash-chained audit log that can be verified. Traces can be replayed. |
| 6 | Honest uncertainty | `uncertain<T>` agents are sampled several times. Their confidence reflects how much the samples agree, and decisions must check it. |
| 7 | Cost, speed and sustainability | Cheap models for easy steps, strong models where needed, caching, parallelism, and every call priced in money, watt-hours and CO₂. |
| 8 | Reuse at scale | 120 domain packs in 20 sectors, modules, MCP tools, AlgoPulse™ streams, quantum tools, eleven enterprise applications, and batch processing of thousands of records. |
| 9 | Access for everyone | Command line, graphical Studio, a plain-English Prompt UI, a Python SDK and editor support through a language server. |
| 10 | Teachable and testable | An offline backend runs without an API key. `eval` blocks and behaviour tests run in CI; live mode uses real Claude models. |

## 2. Design principles

<p align="center"><img src="docs/images/sections/02-principles.svg" alt="Six design principles" width="100%"></p>

- **Explicit, never ambient.** An agent has only the tools it declares. Nothing is available by default.
- **The stricter rule wins.** When the organisation policy and a program's own policy differ, the stricter one applies.
- **Hard rules are deterministic.** Limits that must never be broken are checked in code (`if limits contains "BREACH"`), not left to a model's judgement.
- **Scores drive decisions, and their confidence is shown.** Every branch has a visible reason that can be recorded.
- **People stay in the loop.** A low-confidence call goes to a human review queue instead of going out.
- **One engine, many doors.** The command line, Studio, Prompt UI, SDK and language server all run the same compiler and runtime.

## 3. What's new in v0.4: Trustworthy AI

<p align="center"><img src="docs/images/sections/03-whats-new.svg" alt="Ten trustworthy-AI properties in v0.4, each enforced in code" width="100%"></p>

**v0.4 makes trustworthiness something a program can prove, not just claim.** The compiler checks that each safeguard a system needs is present; the runtime enforces it; `eval` blocks measure it; and the toolchain writes the evidence an auditor reads.

```algo
risk high "Credit decisions about individual loan applicants"          // stricter rules for higher risk
disclose "An AI system helped assess your application. Two credit officers decide, and you can ask why."
policy { redact pii  explain with evidence  retain audit 2555 days }    // privacy, explanations, retention
tool web.rates from mcp "market" untrusted                              // fenced: its text can never give orders

agent CreditDecision(verdict: text, memo: text) -> text {
    goal   "Record the committee recommendation {verdict} for officer sign-off"
    policy { require approvals 2 }                                      // four-eyes: two different people approve
}

eval trust on main {
    case "salaried applicant" (application = "APP-3101 home loan …, a married woman") {
        expect fair across gender ["woman", "man", "non-binary"]        // same decision for every value
        expect robust (typos, paraphrase, reorder) consistency >= 0.9   // harmless rewording changes nothing
        expect explained                                                // every explanation is grounded
    }
}
```

| Property | How AlgoLang enforces it | Evidence |
|---|---|---|
| **Fairness** | `forbid gender` withholds protected values (female, Hindu, married, aged 45 …, even misspelt) before any prompt; `expect fair across` reruns the case once per value | same decision, score gap ≤ `fairness_tolerance` |
| **Robustness** | `expect robust` reruns the case with typos, paraphrases, reordering, case and spacing changes | consistency score; the input that broke it |
| **Transparency** | `algo card` writes an AI system card from the source: purpose, risk level, agents, tools, oversight, data protection, tests and known limitations; `disclose` is required for limited and high risk | `*.card.md` / `*.card.json`, checked for staleness in CI |
| **Explainability** | `explain with evidence`: the agent must give reasons and quotes; quotes not found in its inputs or tool results are asked again, then sent to a person | reasons and evidence in the audit log |
| **Privacy** | `redact pii` masks names, emails, phone, Aadhaar, PAN, account and card numbers before any model call; trusted tools still get the real values; `retain` limits how long logs live | masked counts per call; no personal data in prompts (tested) |
| **Security** | `tool … untrusted` fences tool output: instruction-like lines removed, size limited, wrapped as data; MCP servers can be pinned by `sha256` | removed lines recorded per call; red-team tests |
| **Human oversight** | `require human for always`, `require approvals N` (different named reviewers), overrides recorded | review decisions written into the run's own audit chain |
| **Accountability** | `"audit": {"sign": true}`: every record signed with Ed25519; `algo evidence export` builds a signed pack | `algo audit verify`, `algo evidence verify` detect any change |
| **Risk-based governance** | `risk high` makes the compiler require oversight, explanations, PII masking, fairness and robustness tests and signed logs (**E125–E130**) | the program compiles under its level |
| **Assurance** | `algo trust report` scores all ten properties, with evidence, mapped to NIST AI RMF functions and EU AI Act articles | HTML / JSON report |

```bash
algo eval programs/loan_decision.algo                 # fairness, robustness and explanation tests
algo card programs/*.algo --out cards                 # AI system cards
algo trust report programs --html trust.html          # ten properties with evidence
algo evidence export programs/loan_decision.algo --out loan.evidence.zip
algo evidence verify loan.evidence.zip                # every file, the signature and the audit chains
algo review approve <id> --reviewer "Priya" --override "approve INR 30 lakh instead"
algo keys init                                        # create and pin the Ed25519 audit key
```

**Risk levels in the eleven enterprise applications.** Four programs are high risk and meet every rule: credit decisions, university admissions, ER triage and welfare eligibility. Seven are limited risk and disclose AI use. The other sixteen are internal minimal-risk tools. Every program ships a generated system card in its app's `cards/` folder.

> These features **produce evidence** for frameworks such as the NIST AI RMF, the EU AI Act and ISO/IEC 42001. Using AlgoLang does not by itself make a system compliant: that still needs your organisation's own risk management, legal review and, where required, a conformity assessment. Offline tests use an ideal mock model, so they test the program (its guards, tools and masking); run `algo eval --live` to test the real model.

**v0.4.1 adds LLM & SLM graph optimisation:** small models on your own GPUs (`model slm = "local:phi-4-mini"`, any OpenAI-compatible server), SLM-first cascades written with `uncertain<T>` and guards, and an exact optimiser that picks the cheapest model for every agent of a program within quality floors and a latency limit, then applies it with `"agent_models"`. See the [AlgoGraph™ LLM & SLM Optimizer](enterprise-apps/llm-graph-optimizer/).

### Earlier releases: v0.3 to v0.3.4

```algo
tool kb.search_policies from mcp "company-kb"        // 1. tools from any MCP server

agent Compliance(claim: text, rules: text) -> uncertain<score> {   // 2. uncertainty in the type system
    goal   "Score how well {claim} complies with {rules}"
    policy { samples 5  budget cost 0.05 usd  budget energy 2 wh }  // 3. money and energy budgets
}

flow main(claim: text) {
    rules = PolicyFinder(claim)
    ok    = Compliance(claim, rules)
    if ok > 0.6 and ok.confidence >= 0.7 { emit Approve(claim) }   // E117 without the confidence check
    else { emit Query(claim, rules) }
}

eval regression on main {                                    // 4. tests next to the code, replayable
    case "hotel within policy" (claim = "Hotel, 2 nights at INR 7,500") {
        expect called Compliance   expect cost < 0.05   expect output contains "Travel"
    }
}
```

| Feature | What it gives you | Try it |
|---|---|---|
| **`uncertain<T>` types** | The agent is sampled several times (`samples N`). The result carries `.confidence`, computed from how much the samples agree. The compiler rejects comparing an uncertain value without checking its confidence (**E117**). | `if risk > 0.8 and risk.confidence >= 0.7` |
| **`eval` blocks + trace replay** | Behaviour tests written in AlgoLang. Every run can record a trace. Replaying it answers each agent from the recording: zero tokens, zero cost, and it shows exactly which agents now receive different inputs after you change the program. | `algo eval x.algo` · `algo eval x.algo --replay` · `algo run x.algo --trace` · `algo replay trace.json` |
| **MCP tool bindings** | `tool a.b from mcp "server"` binds a tool on any Model Context Protocol server (stdio or HTTP) listed in `algo.config.json`. Declaration, `uses` grants, `allowed_tools` and the audit log apply as for every other tool. | `algo mcp list company-kb` |
| **`cost` and `energy` budgets** | Every call is priced in USD/INR, Wh and g CO₂. Budgets are checked before each call, and run-level caps live in `algo.config.json`. Reports show money and energy per program. | `budget cost 5 inr` · `budget energy 0.5 wh` · `algo report` |
| **Deterministic guards** | `if limits contains "BREACH"` checks text, including a tool's full answer, with no model involved. Hard limits cannot be overruled by a model. | `if x not contains "FAILS"` |
| **Language server** | `algo lsp` gives any editor live errors, hover, completion, go-to-definition (including into domain packs) and an outline. The VS Code extension starts it automatically. | `vscode-algolang/` |

**v0.3.2 adds quantum tools (preview):** QAOA optimisation verified against the exact optimum, OpenQASM circuits, Grover search and `shots` / `max qubits` policies. See [§8](#8-quantum-applications).

**v0.3.3 adds quantum circuits to the language** (`circuit Bell { qubits 2  h q0  cx q0, q1  measure }`) and four quantum applications: portfolio optimisation, quantum-safe security, Monte Carlo risk with amplitude estimation, and logistics routing.

**v0.3.1 adds real-time streams:** a `stream` block runs a flow for every event on a topic. **v0.3.4 adds AlgoPulse™**, AlgoLang's own durable event engine, so streams need nothing outside AlgoLang. See [§7](#7-real-time-events-algopulse).

A runnable tour lives in [`examples/v03/`](examples/v03/): an expense desk that uses an MCP server, an `uncertain<score>` reviewer, budgets and an eval block.

### Earlier: v0.2 Enterprise

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

## 4. Get started

<p align="center"><img src="docs/images/sections/04-get-started.svg" alt="Quick start in a terminal" width="100%"></p>

### Three modes, one SDK

| Mode | Start it | What you get |
|---|---|---|
| **Command line** | `algo` (menu) · `algo shell` · `algo chat` · `algo run` · `algo batch` | Scripts, CI, batch jobs, a terminal prompt mode |
| **Graphical** | `algo studio` | Browser IDE: editor, run, agent graph, ✨ Ask AI, **Domains**, **Batch**, **Governance** tabs |
| **Prompt-based UI** | `algo ui` | Chat-style page: describe a problem in plain English and get a governed multi-agent solution, with every agent's work shown |

### Try it

- **In your browser, nothing to install:** the [playground](https://drssnaiml1-cell.github.io/algolang/playground.html) runs the real compiler and runtime locally.
- **With pip:** `pip install git+https://github.com/drssnaiml1-cell/algolang`, then `algo doctor`.
- **Windows / Linux / macOS installers:** download `AlgoLang_v0.3.0.zip` from [Releases](https://github.com/drssnaiml1-cell/algolang/releases/latest) and follow [RUN_GUIDE.md](RUN_GUIDE.md).
- **Browse the 120 domain packs:** [domain library](https://drssnaiml1-cell.github.io/algolang/library.html).


### Quick start

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

## 5. Learn by example: 50 sample programs

<p align="center"><img src="docs/images/sections/05-50-programs.svg" alt="50 sample programs by pattern" width="100%"></p>

**[AlgoLang: 50 Sample Programs](docs/AlgoLang_50_Sample_Programs.pdf)** (PDF, 106 pages) teaches the language through 50 small programs in 20 sectors. Each one shows its input, the code, and the output in the command line, Studio and Prompt UI. It also sets out the language's objectives and design principles and summarises its syntax.

The runnable source of every program is in [`examples/50-programs/`](examples/50-programs/), and CI runs all 50 on every push.

| Pattern | Programs | Example |
|---|---|---|
| single | 4 | [P01 Hello Greeter](examples/50-programs/P01_hello_greeter.algo) |
| pipeline | 15 | [P15 KYC Onboarding](examples/50-programs/P15_kyc_onboarding.algo) |
| fan-out | 9 | [P12 Drug Interaction Check](examples/50-programs/P12_drug_interaction_check.algo) |
| committee | 4 | [P14 Credit Committee](examples/50-programs/P14_credit_committee.algo) |
| router | 13 | [P17 Claims Triage](examples/50-programs/P17_claims_triage.algo) |
| par for | 5 | [P24 Literature Review](examples/50-programs/P24_literature_review.algo) |

## 6. Enterprise applications

<p align="center"><img src="docs/images/sections/06-enterprise-apps.svg" alt="Eleven enterprise applications" width="100%"></p>

[`enterprise-apps/`](enterprise-apps/) holds eleven complete, governed multi-agent applications. Each has its own org policy, company tools over its own data, a knowledge base, programs, batch data, behaviour tests and (v0.4) a risk level and a generated AI system card for every program:

| Application | Sector | What it automates | Risk (v0.4) |
|---|---|---|---|
| [Claims Operations Center](enterprise-apps/claims-ops-center/) | Insurance | FNOL → policy check → fraud panel → SIU referral, or routing and payout | limited |
| [Hospital Care Coordination](enterprise-apps/hospital-care-coordination/) | Healthcare | ER triage with the bed board, and discharge summaries (decision support) | **high** (ER triage) · limited |
| [Bank Credit & Onboarding](enterprise-apps/bank-credit-onboarding/) | Banking | Bureau + DTI + credit committee; KYC with sanctions screening | **high** (credit) · limited |
| [University Admissions & OBE](enterprise-apps/university-admissions-obe/) | Education | Fair admissions panel; NBA/NAAC CO-PO matrix and question papers | **high** (admissions) · minimal |
| [SOC Incident Command](enterprise-apps/soc-incident-command/) | Cybersecurity | Alert enrichment (CMDB, threat intel) → severity → incident → runbook; real-time SIEM alerts on AlgoPulse™ | limited · minimal |
| [Supply Chain Control Tower](enterprise-apps/supply-chain-control-tower/) | Logistics | Shipment exceptions → tracking + stock cover → recovery plan | minimal |
| [Citizen Services Desk](enterprise-apps/citizen-services-desk/) | Government | Grievance routing with service-level targets; welfare pre-checks | **high** (welfare) · limited |
| [Legal Contract Desk](enterprise-apps/legal-contract-desk/) | Legal | NDA triage against the playbook; clause-by-clause contract review | minimal |
| [Algo Trading Desk (QuantOracle™)](enterprise-apps/algo-trading-desk/) | Capital markets | Strategy review board → pre-trade risk gate with hard limits → end-of-day risk and surveillance (paper trading, human approval of every order) | minimal |
| [Quantum Optimization Lab](enterprise-apps/quantum-optimization-lab/) | Quantum computing | QAOA portfolio selection and max-cut shift planning, each VERIFIED against the exact optimum, then risk review and human approval; quantum-random audit sampling | minimal |
| [AlgoGraph™ LLM & SLM Optimizer](enterprise-apps/llm-graph-optimizer/) | AI platform · MLOps | SLM-first cascades (small model first, large model when unsure); exact graph optimisation of every agent's model within quality floors and a latency limit, VERIFIED by brute force; two-person rollout | limited · minimal |

```bash
python enterprise-apps/run_all.py --batch      # every app's tests, batch job, streams and system cards
cd enterprise-apps/bank-credit-onboarding && algo trust report programs --html trust.html
cd enterprise-apps/claims-ops-center && algo batch programs/claims_intake.algo --input data/claims_batch.csv
```

## 7. Real-time events: AlgoPulse™

<p align="center"><img src="docs/images/sections/07-realtime.svg" alt="AlgoPulse: producers, bus, stream block and routed result topics" width="100%"></p>

A `stream` block turns any flow into a real-time service. Every event on a topic runs the flow once, with the same policies, budgets, human gate and audit log as any other run. The agents and the flow stay exactly as they are.

Events travel on **AlgoPulse™**, AlgoLang's own event engine. A bus is a folder of durable, append-only topic logs with numbered offsets and consumer groups, so it needs nothing outside AlgoLang. Programs on one machine share it directly. `algo pulse serve` puts it on the network behind a bearer token.

```algo
// enterprise-apps/algo-trading-desk/programs/pre_trade_check.algo
stream order_flow on main {
    from pulse "market" topic "orders.intent" group "quantoracle-risk-gate"
    map order = event.order               // flow input ← field of the JSON event
    key event.order_id                    // used for de-duplication
    to topic "orders.decisions"           // ok
    escalate to topic "orders.review"     // a person must decide
    dead letter topic "orders.dlq"        // unreadable events, blocked or failed runs
    max in flight 8                       // events processed in parallel
}
```

```bash
cd enterprise-apps/algo-trading-desk
algo stream programs/pre_trade_check.algo --input data/order_events.jsonl               # offline, from a file
algo stream programs/pre_trade_check.algo --pulse --produce data/order_events.jsonl     # publish to the bus
algo stream programs/pre_trade_check.algo --pulse                                        # run the risk gate live
algo pulse topics --bus market                                                           # events per topic
ALGO_PULSE_TOKEN=change-me algo pulse serve --dir pulse/market --host 0.0.0.0           # share the bus
```

**How one event is handled**

```mermaid
sequenceDiagram
    autonumber
    participant P as Order system
    participant B as AlgoPulse bus (orders.intent)
    participant S as algo stream
    participant F as flow main (agents)
    participant R as Result topics
    participant A as Audit log
    P->>B: JSON event ORD-1001 (SELL 2 lots NIFTY …)
    B->>S: read from the group's committed offset
    S->>S: decode JSON · map inputs · skip duplicate keys
    S->>F: run flow (policies, budgets, sampling)
    F->>A: one hash-chained record per agent call
    F-->>S: outputs · confidence · escalations · cost
    alt ok
        S->>R: orders.decisions
    else escalated (human gate)
        S->>R: orders.review
    else invalid, blocked or failed
        S->>R: orders.dlq
    end
    S->>B: commit the group's offset (only after results are written)
```

| Guarantee | How |
|---|---|
| **Checked before it runs** | E122: the flow and its inputs exist, mappings read from `event`, no result topic equals the source topic (no endless loops) |
| **Nothing is dropped** | Every event ends in exactly one result topic; a route you do not declare falls back to `to topic` |
| **Durable, at-least-once** | Every event is written and fsync'd before it is acknowledged. A group's offset moves only after results are written, so a restart resumes exactly where it stopped |
| **Many writers, one order** | File locks keep offsets gap-free and unique when several programs write to a local bus at once |
| **Governed like any run** | Each event gets its own run ID, audit chain, budget checks and review-queue entry |
| **Observable** | Per-stream metrics: events/s, latency p50/p95, ok / escalated / dead-letter counts, tokens, $ and Wh (`runs/streams/<name>/metrics.json`); `algo pulse tail` shows any topic |
| **Secure** | Topic and group names cannot escape the bus folder. A served bus requires a bearer token (`ALGO_PULSE_TOKEN`) and refuses to listen beyond localhost without one |

`algo.config.json` names each bus: `"pulse": {"market": {"dir": "pulse/market"}}` for a local folder, or `{"url": "http://10.0.0.5:7070", "token_env": "PULSE_TOKEN"}` for a served bus. Two enterprise applications ship with streams: the **Algo Trading Desk** (order intents → pre-trade risk gate) and the **SOC Incident Command** (SIEM alerts → incidents). CI starts a real AlgoPulse server on every push and runs the trading desk through it.

## 8. Quantum applications

<p align="center"><img src="docs/images/algolang-quantum.svg" alt="A portfolio problem becomes a QUBO, runs as a QAOA circuit with one qubit per asset, is measured 2,048 times and checked against the exact classical optimum; only a VERIFIED answer reaches the risk review and the human approver" width="100%"></p>

Quantum computers are suited to hard combinatorial choices: which assets to hold, which jobs share a shift, which route a van takes. Their answers are probabilistic and today's devices are noisy, so a quantum result should never drive a decision unchecked. AlgoLang treats a quantum computer like any other system: agents reach it only through **declared, granted, audited tools**, under **limits written in the policy**, and every optimisation result is **checked against the exact classical optimum** before an agent may act on it.

```algo
tool quantum.portfolio                         // a company tool built on algoquantum.solve_qubo

agent QuantumOptimizer(request: text, universe: text) -> text {
    role   "Quantum optimisation engineer"
    goal   "Choose the portfolio for {request} with QAOA, from {universe}"
    uses   quantum.portfolio
    policy { shots 2048  max qubits 12 }       // a 16-asset universe is BLOCKED before it runs (E123 checks the limits)
}

flow main(request: text) {
    universe  = Universe(request)
    portfolio = QuantumOptimizer(request, universe)
    if portfolio contains "VERIFIED" {         // deterministic guard: an unverified quantum answer is never used
        fit = RiskReview(request, portfolio)   // uncertain<score>, sampled 5×
        if fit > 0.7 and fit.confidence >= 0.75 { emit portfolio, fit, Proposal(request, portfolio) }   // 👤 approves
        else { emit portfolio, fit, ClassicalFallback(request, portfolio) }
    } else {
        emit portfolio, ClassicalFallback(request, portfolio)
    }
}
```

| Built-in tool | What it does | Typical use |
|---|---|---|
| `quantum.run` | Runs an OpenQASM 2.0 circuit and returns measurement counts (built-in simulator or Qiskit Aer) | Teaching, circuit experiments, Qiskit interoperability |
| `quantum.qubo` | Solves a QUBO with QAOA; the answer is `VERIFIED` or reported with its `GAP` to the exact optimum | Portfolio selection, feature selection, facility location |
| `quantum.maxcut` | Splits a weighted graph (`"A-B:3, B-C:1"`) into two groups with QAOA max-cut, verified | Shift and crew scheduling, network partitioning, load balancing |
| `quantum.grover` | Grover search for marked items among 2ⁿ, with the classical query count for comparison | Search and constraint-satisfaction teaching |
| `quantum.random` | Random bits, or "pick k of n" sampling, from measured qubits | Unpredictable audit sampling, randomised controls |
| `quantum.routes` *(v0.3.3)* | One route per shipment at the lowest total cost, with shared-lane clash costs; a QUBO solved by QAOA, `VERIFIED` and checked `FEASIBLE` | Logistics, fleet and crew assignment |
| `quantum.scenarios` *(v0.3.3)* | Monte Carlo value at risk and expected shortfall, plus a quantum amplitude estimation (QAE) of the tail probability with its error bound and oracle-call count | Market and credit risk, limit monitoring |
| `pqc.scan` *(v0.3.3)* | Reads a cryptography inventory and flags what Shor's and Grover's algorithms would break or weaken, with Mosca's harvest-now-decrypt-later test and the NIST FIPS 203/204/205 replacement | Quantum-safe migration planning |
| `circuit.Name` *(v0.3.3)* | Every `circuit` block in the program | Your own algorithms, teaching, OpenQASM export |

### Write circuits in AlgoLang (v0.3.3)

```algo
// Grover search over 4 items for item 3 (|11⟩)
circuit Grover2 {
    qubits 2
    h q0, q1                     // one-qubit gates can list several qubits
    cz q0, q1                    // oracle
    h q0, q1   x q0, q1   cz q0, q1   x q0, q1   h q0, q1     // diffusion
    measure
}

agent Search(question: text) -> text {
    goal   "Run Grover's search and report which item was found, for {question}"
    uses   circuit.Grover2          // the circuit is a tool: declared, granted, audited
    policy { shots 1000  max qubits 4 }
}

flow main(question: text) {
    found = Search(question)
    if found contains "11: 1000 (100%)" { emit found, Verified(found) }    // check the quantum result exactly
    else { emit found, Investigate(found) }
}
```

The compiler checks every circuit (**E124**): known gates (`h x y z s t rx ry rz p u1 u2 u3 cx cy cz ch crz cp swap ccx …`), the right number of qubits and angles, qubits that exist, and angles such as `pi/4`. Then:

```bash
algo quantum list   circuit_lab.algo           # circuits and their sizes
algo quantum run    circuit_lab.algo Grover2   # counts as a histogram
algo quantum export circuit_lab.algo --out qasm/   # OpenQASM 2.0 for Qiskit, IBM Quantum, Braket …
```

### Four quantum applications

```mermaid
flowchart LR
    P["Business problem"] --> M["Quantum model<br/>QUBO · circuit · amplitude estimation"]
    M --> Q["Quantum tool<br/>shots · max qubits"]
    Q --> V{{"Classical check<br/>exact optimum · feasibility · error bound"}}
    V -- "VERIFIED" --> R["Agent review<br/>uncertain&lt;score&gt;"] --> H(["👤 human approves"])
    V -- "GAP · INFEASIBLE · BREACH" --> F["Classical fallback<br/>or escalation"]
    Q --> A[("audit log")]
    classDef navy fill:#0e2140,stroke:#c9a227,color:#f4f1e8;
    classDef gold fill:#c9a227,stroke:#0e2140,color:#0e2140;
    class P,M,Q,R,F navy; class V gold;
```

| Application | Program | Quantum method | The governed decision |
|---|---|---|---|
| **Portfolio optimisation** | [`quantum-optimization-lab/programs/portfolio_optimizer.algo`](enterprise-apps/quantum-optimization-lab/programs/portfolio_optimizer.algo) | QAOA on a portfolio QUBO, one qubit per asset | VERIFIED portfolio → risk review (sampled 5×) → paper proposal for a person to approve |
| **Quantum-safe security** | [`soc-incident-command/programs/pqc_readiness.algo`](enterprise-apps/soc-incident-command/programs/pqc_readiness.algo) | Shor/Grover threat model, Mosca's rule | broken-today crypto opens an incident; URGENT systems need the CISO's sign-off on a migration plan to ML-KEM / ML-DSA / SLH-DSA |
| **Monte Carlo risk** | [`algo-trading-desk/programs/risk_scenarios.algo`](enterprise-apps/algo-trading-desk/programs/risk_scenarios.algo) | One-factor Monte Carlo from qubit draws, plus quantum amplitude estimation of the tail probability | VaR above the desk limit goes to the risk committee (a person decides); otherwise a risk note |
| **Logistics routing** | [`supply-chain-control-tower/programs/route_optimizer.algo`](enterprise-apps/supply-chain-control-tower/programs/route_optimizer.algo) | QAOA on a one-hot routing QUBO with lane-clash costs | VERIFIED and FEASIBLE plan → dispatch (human gate); otherwise the classical optimum |
| Circuit lab | [`quantum-optimization-lab/programs/circuit_lab.algo`](enterprise-apps/quantum-optimization-lab/programs/circuit_lab.algo) | Bell, GHZ and Grover circuits written in AlgoLang | the Grover result is checked exactly before it is reported |

Each program has an `eval` block and behaviour tests that run in CI.

**What makes it trustworthy**

- **Exact verification.** The simulator holds every amplitude, so the true optimum is known up to the qubit limit. The tool reports `VERIFIED`, or `GAP: … % worse`, plus P(optimal) and the approximation ratio.
- **Limits in the policy.** `shots N` and `max qubits N` per agent, `"quantum": {"max_qubits": …}` for the whole organisation; the stricter limit wins. Bigger circuits are `BLOCKED`.
- **Reproducible.** Runs are seeded, so the same request gives the same answer, as audit and `algo replay` require.
- **Honest about the hardware.** Every answer names its backend. The built-in simulator is checked against Qiskit on every CI run (fidelity error below 10⁻¹²). It computes what an ideal quantum computer would return, on a classical computer, so it is correct but not faster. Amplitude estimation is simulated exactly from its phase-estimation statistics; its quadratic speed-up over Monte Carlo needs fault-tolerant hardware. `pqc.scan` applies published rules (it is not a penetration test), and its time-to-quantum-threat is an assumption you set. Real quantum hardware arrives in v0.5.

The [**Quantum Optimization Lab**](enterprise-apps/quantum-optimization-lab/) also has a max-cut shift scheduler and quantum-random audit sampling. Install with `pip install "algolang[quantum]"` (NumPy). For Qiskit Aer, also `pip install qiskit qiskit-aer` and set `"backend": "qiskit-aer"`.

## 9. The language

<p align="center"><img src="docs/images/sections/09-language.svg" alt="From .algo source to a governed run" width="100%"></p>

### The language in one screen

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

### Compile-time checks

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
| E116 | Circular `use` import |
| E117 | `uncertain<T>` value compared without checking its `.confidence` in the same condition |
| E118 | `.confidence` read on something that is not an agent result, or another attribute read |
| E119 | `eval` block error: unknown flow, input, agent, tool or status |
| E120 | `tool … from mcp "server"` names a server missing from `mcp_servers` in `algo.config.json` |
| E121 | Bad policy value: unknown currency or energy unit, or `samples` outside 1–15 |
| E122 | `stream` block error: unknown flow or input, mapping not read from `event`, a result topic equal to the source topic, or `max in flight` outside 1–256 |
| E123 | Quantum policy or tool error: `shots` outside 1–100000, or `max qubits` outside 1–24 |
| E124 | `circuit` block error: no or too many qubits, unknown gate, wrong number of qubits or angles, a qubit that does not exist, a bad angle, or a duplicate circuit |
| E125 | High-risk flow without human oversight (`require human when …`, `require human for always` or `require approvals N`) |
| E126 | High-risk program without a fairness test (`expect fair across …`) or a robustness test (`expect robust …`) |
| E127 | High-risk program: an agent does not mask personal data (`redact pii`), or a reviewed decision is not explained (`explain with evidence`) |
| E128 | A forbidden attribute reaches an agent through one of its tools |
| E129 | Risk declaration error: unknown level, no `disclose` for limited or high risk, no purpose, or high risk without signed audit logs |
| E130 | Trust value error: `require approvals` outside 1–5, `retain` outside 1–3650 days or not audit/traces, `expect fair` with fewer than two values, unknown perturbation or consistency outside 0–1 |

Errors from imported modules are reported with the file name, and the org config is enforced at compile time: a forbidden attribute or an ungranted tool is an error before anything runs.

## 10. Governance and runtime guarantees

<p align="center"><img src="docs/images/sections/10-governance.svg" alt="Defence in depth for every agent call" width="100%"></p>

**The life of one agent call**

```mermaid
flowchart LR
    A(["call Agent(x)"]) --> B{"forbidden<br/>attribute?"}
    B -- yes --> X1["⛔ blocked<br/>(policy violation)"]
    B -- no --> C{"tool allowed<br/>and granted?"}
    C -- no --> X1
    C -- yes --> D{"tokens · $ · Wh<br/>within budget?"}
    D -- no --> X1
    D -- yes --> E{"cached?"}
    E -- yes --> H
    E -- no --> F["model call<br/>(samples N for uncertain types)"]
    F --> G["confidence =<br/>model × agreement"]
    G --> H{"confidence<br/>≥ human gate?"}
    H -- yes --> I(["✅ value + provenance"])
    H -- no --> J(["👤 review queue"])
    X1 --> L[("audit log<br/>prev → hash")]
    I --> L
    J --> L
    classDef ok fill:#0e2140,stroke:#6cc28a,color:#f4f1e8;
    classDef bad fill:#3a1414,stroke:#e0705c,color:#f4f1e8;
    classDef gate fill:#c9a227,stroke:#0e2140,color:#0e2140;
    class I ok; class X1 bad; class B,C,D,E,H gate;
```

- **Policy enforcement:** token budget, retries, timeout, forbidden-attribute blocking, and a human-in-the-loop gate on low confidence.
- **Concurrency:** `par` and `par for` run on a thread pool.
- **Audit trail:** one JSONL record per agent call, holding the model, input hash, confidence, tokens, status, policy and tool calls. Records are hash-chained (`prev` → `hash`) and checked with `algo audit verify`.
- **Org policy:** `algo.config.json` is merged into every agent's policy (stricter wins). It also enforces a run-wide token cap and a list of allowed tools.
- **Human review queue:** escalated calls are written to an event-sourced queue (`algo review`, the Studio Governance tab, `al.review`).
- **Cache:** identical calls are answered from SQLite at zero tokens (`cache` policy, or `"cache": true` in the config).
- **Uncertainty (v0.3):** `uncertain<T>` agents are sampled `samples N` times; scores are averaged, other types are decided by majority vote, and confidence blends the model's own confidence with how much the samples agree. Every audit record shows the number of samples and their spread.
- **Money and energy (v0.3):** each call is priced from the `pricing` table (USD per million input/output tokens, convertible to INR) and the `energy` table (Wh per 1,000 tokens, grid CO₂ intensity). Per-agent budgets and run caps are checked before the call. The default prices and energy figures are placeholders: set your own in `algo.config.json`. Offline runs show the *estimated* live cost.
- **Traces and replay (v0.3):** `--trace` records every call's inputs and outputs, and `ReplayBackend` answers from them.
- **Backends:**
  - `mock` (deterministic, offline) is for teaching and CI.
  - `live` calls Claude via the `anthropic` SDK.
  - `replay` answers from a recorded trace (v0.3).

## 11. Python SDK

<p align="center"><img src="docs/images/sections/11-sdk.svg" alt="The Python SDK workflow" width="100%"></p>

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

## 12. For developers

<p align="center"><img src="docs/images/sections/12-developers.svg" alt="Three developer tracks" width="100%"></p>

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

## 13. Roadmap: v0.5 Quantum AI, v0.6 Interoperability, v1.0

<p align="center"><img src="docs/images/sections/13-roadmap.svg" alt="Roadmap timeline" width="100%"></p>

**v0.4 Trustworthy AI is released** (see [§3](#3-whats-new-in-v04-trustworthy-ai)). The releases below are built one at a time, each with tests, CI, documentation and figures. The full plan is in **[ROADMAP.md](ROADMAP.md)**.

**v0.5 — Quantum AI (next).** The quantum preview becomes a full release: real quantum hardware (IBM Quantum, Amazon Braket, Azure Quantum) behind the same tool interface, with QPU-time and cost budgets; noise models and error mitigation; quantum results as `uncertain<T>` values whose confidence comes from shot statistics; VQE for chemistry and materials, quantum kernels for classification, amplitude estimation for financial risk; verified bounds beyond the simulator's reach; and post-quantum signatures for the audit chain. Details in [ROADMAP.md](ROADMAP.md#5-v05-quantum-ai).

**v0.6 — Interoperability.** Agents served as MCP servers, argument type checking, and token-by-token output streaming. **v1.0** adds a native runtime, typed agent-to-agent messaging, a package registry and SSO/RBAC for Studio.

| Version | Theme | Status |
|---|---|---|
| v0.1 | The language: agents, flows, policies, compiler, runtime | Released |
| v0.2 | Enterprise: modules, org policy, 120 domain packs, audit, review queue, SDK, three modes | Released |
| v0.3 | Uncertainty, evals and replay, MCP, cost and energy budgets, language server, deterministic guards | Released |
| v0.3.1 | Real-time `stream` blocks | Released |
| v0.3.2 | Quantum tools preview: QAOA verified exactly, OpenQASM, Grover, quantum policies | Released |
| v0.3.3 | Quantum circuits in the language; quantum-safe security, Monte Carlo with amplitude estimation, logistics routing | Released |
| v0.3.4 | AlgoPulse™, AlgoLang's own real-time event engine; animated figures for every section and every application | Released |
| v0.4 | Trustworthy AI: risk levels, privacy, explanations, untrusted tools, four-eyes review, signed audit, fairness and robustness tests, system cards, evidence packs, trust reports | Released |
| v0.4.1 | LLM & SLM graph optimisation: SLM-first cascades, exact model assignment over the agent graph, local small models, `agent_models` routing | **Current** |
| v0.5 | Quantum AI: hardware backends, noise, uncertain quantum results, chemistry and risk algorithms | Next |
| v0.6 | Interoperability: agents as MCP servers, argument types, output streaming | Planned |
| v1.0 | Native runtime and ecosystem | Planned |

## 14. Repository layout

<p align="center"><img src="docs/images/sections/14-layout.svg" alt="Repository layout" width="100%"></p>

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
requirements*.txt             Python dependencies (lark; anthropic for --live; numpy for quantum tools)
Dockerfile                    container environment
grammar.lark                  formal grammar (Lark EBNF)
algoc.py                      compiler: parse → AST → checks → Python codegen
algoruntime.py                runtime engine
algoeval.py                   eval blocks, traces and replay (algo eval, algo replay)        — v0.3
algomcp.py                    MCP client and tool bindings (algo mcp)                         — v0.3
algolsp.py                    language server (algo lsp)                                      — v0.3
algotrust.py                  privacy, untrusted-tool fencing, Ed25519 signing, retention, perturbations — v0.4
algoassure.py                 system cards, trust reports, evidence packs (algo card / trust / evidence) — v0.4
algostream.py                 stream blocks: routing, metrics, at-least-once (algo stream)    — v0.3.1
algopulse.py                  AlgoPulse™ event engine: durable topics, groups, server (algo pulse) — v0.3.4
algoquantum.py                quantum tools: simulator, OpenQASM, QAOA + exact check, Grover — v0.3.2;
                              circuit blocks, routing, Monte Carlo + QAE, PQC readiness — v0.3.3
docs/images/                  animated SVG figures: sections/, apps/ (drawn from the programs), Studio screenshots
tools/make_figures.py         regenerates every figure (CI checks they match the code)
examples/v03/                 tour of v0.3: MCP demo server, uncertain<T>, budgets, eval
examples/50-programs/          the 50 programs from "AlgoLang: 50 Sample Programs" + inputs.json
docs/                         language manual (LaTeX + PDF) and AlgoLang_50_Sample_Programs.pdf
enterprise-apps/              eleven governed enterprise applications (incl. Algo Trading Desk, Quantum Optimization Lab, AlgoGraph™ LLM & SLM Optimizer)
ROADMAP.md                    v0.4 Trustworthy AI and v0.5 Quantum AI plans, later releases
examples/*.algo               source programs (bad_example.algo shows every error)
vscode-algolang/              VS Code extension: highlighting + the language server
.vscode/tasks.json            Ctrl+Shift+B to run the open .algo file
```

## 15. Author and licence

<p align="center"><img src="docs/images/sections/15-author.svg" alt="Author and licence" width="100%"></p>

AlgoLang is designed by **Dr. S. Satyanarayana, Ph.D., PDF (AI)**, Founder, CEO & Chief Agentic AI Scientist of **AlgoProfessor AI R&D Solutions**, Hyderabad.

- 🌐 [www.algoprofessor.com](https://www.algoprofessor.com)
- Contact: ceo@algoprofessor.com

### Licence

Apache License 2.0. See [LICENSE](LICENSE). Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).
