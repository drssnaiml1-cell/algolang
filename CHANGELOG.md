# Changelog

All notable changes to AlgoLang are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/) (during 0.x, minor versions may change the language).

## [Unreleased]

### Documentation
- **Language manual v1.0** (`docs/AlgoLang_Documentation_v1.0.pdf`, 108 pages): new chapters for v0.5 domain applications, v0.6 Quantum AI, v0.7 Interoperability and v1.0 (typed messages, AlgoIR and the AlgoVM, packages, Studio sign-in), and error codes E131–E133. It replaces the v0.4 manual.

## [1.0.0] — 2026-11-11 · Native runtime and ecosystem

AlgoLang 1.0: every release planned since v0.1 has shipped. Agents exchange typed messages, programs ship as signed artifacts that run on AlgoLang's own virtual machine, agents are shared as signed packages, and Studio is a multi-user workspace with single sign-on and roles.

### Added
- **Typed agent-to-agent messages:** `type Name { field: type, … }` with `text`, `number`, `score`, `bool`, `list`, `json` and nested types; agents return them (`-> Claim`), flows read fields (`claim.amount`, `claim.claimant.name`) in conditions and arguments, and imported files share their types.
  - Compile time: E131 for wrong argument types, new **E132** for unknown or duplicate fields and types, reserved names, self-containing types and uncertain typed messages.
  - Run time: every answer is validated against its type (numbers and booleans gently coerced; missing fields fail and are retried under `retry`); live models are told the exact JSON shape; typed flow inputs are validated; personal data in messages is masked field by field.
  - New `number` type for parameters, inputs and fields.
- **AlgoIR and the AlgoVM** (`algoir.py`): `algo build FILE --ir [--sign]`, `algo run FILE.algoir.json`, `algo run FILE --engine vm`, `algoir.load(…).run(…)`. AlgoIR is versioned JSON with a SHA-256 digest and an optional Ed25519 (+ ML-DSA) signature; `"runtime": {"require_signed_ir": true}` refuses unsigned or altered programs. `tools/check_vm.py` (a CI job) runs all 222 shipped programs on both engines and requires identical results.
- **Packages and registries** (`algopkg.py`): `algo pkg init | build | publish | search | install | list | verify`, reproducible `.algopkg` archives with per-file SHA-256 and a signed manifest, semantic-version ranges (`^`, `~`, comparisons), dependencies with conflict detection, `algo.lock`, `use "pkg:name/file.algo"`, **E133** for missing or changed package files, and `"registry": {"url", "trusted_publishers"}`. `tools/make_registry.py` publishes the 120 domain packs as 20 packages in the public registry on the website.
- **Studio single sign-on and roles** (`algoauth.py`): `"studio": {"auth": {"mode": "oidc" | "token"}, "roles", "default_role", "tokens"}`. OpenID Connect authorization code with PKCE, state and nonce; RS256 ID tokens verified against the provider's JWKS (issuer, audience, expiry); HMAC-signed HttpOnly session cookies; API tokens stored as hashes; roles viewer, reviewer, author and admin enforced on every route; the signed-in person recorded as the reviewer; `runs/studio_access.jsonl`; `/api/me`.
- `examples/v10/`, `tests/test_v1.py`, CI job "AlgoVM gives the same results as compiled Python".

### Changed
- Package status: Production/Stable.
- `x.field` may appear wherever an expression may (arguments, `emit`), not only in conditions.


## [0.7.0] — 2026-11-11 · Interoperability

v0.7 lets any software use a governed AlgoLang flow, with no gap in its governance.

### Added
- **Flows and agents as MCP servers** (`algoserve.py`): `algo mcp serve FILE… [--agents] [--http PORT] [--live]`. One MCP tool per flow (per agent with `--agents`), with input schemas from the declared types and an output schema; each call runs under the organisation's policies, budgets, human review and audit log, and returns status, values, pending human reviews, cost, tokens and the audit file. Stdio (newline-delimited JSON-RPC) and Streamable HTTP (127.0.0.1 by default, optional bearer token `ALGO_MCP_TOKEN`). Progress notifications stream agents' output to stdio clients that send a progress token. AlgoLang programs can call each other through `tool x from mcp "…"`.
- **Argument type checking (E131):** the compiler rejects a text value passed where an agent declares `score`, `list`, `bool` or `json` (numbers and uncertain scores are accepted for scores, JSON for lists).
- **Typed flow inputs:** inputs are converted to their declared types (`"80%"` → 0.8, `"a; b; c"` → a list, `"yes"` → true, JSON text → an object) or refused with `InputTypeError` (`✗ invalid input: …` on the CLI). `par for` over a list input now fans out over its items.
- **Token-by-token streaming:** `algo run --stream`, `Program.run(on_token=…)`, `Program.call_agent(…, on_token=…)`; Claude (Messages streaming API), OpenAI-compatible local models (server-sent events) and the offline mock stream; events are `start`, `delta` and `end`.
- **`Program.call_agent(name, **inputs)`** in the SDK: one agent under the same policies and audit as a flow.
- **Cost and energy dashboard:** `algo report DIR --html FILE` and Studio's `/dashboard` (cost, energy, CO₂, tokens and QPU time by program and agent; escalations; audit-chain health). `al.audit.report` now totals QPU seconds and cost.
- `examples/v07/` with a served program and client configuration; `tests/test_interop.py`.

### Changed
- The SDK passes inputs to flows with their own types instead of converting everything to text first.


## [0.6.0] — 2026-11-11 · Quantum AI

v0.6 lets agents use real quantum computers with answers that are checked, budgeted and accountable. The same program runs on the exact simulator, a noisy simulator, IBM Quantum, Amazon Braket or Azure Quantum by changing one line of `algo.config.json`.

### Added
- **`algoqpu.py`**, the v0.6 quantum layer:
  - **Q1 Backends:** `noisy:<profile>` (superconducting, trapped-ion, low, high, or a custom `"noise"`), `ibm:<device>` (Qiskit Runtime Sampler), `braket:<device>` (Amazon Braket) and `azure:<target>` (Azure Quantum). Credentials are read only from environment variables; a missing SDK or credential is reported as BLOCKED.
  - **Q2 QPU budgets:** `budget qpu N seconds | minutes | usd` in a policy, and per-run caps `quantum.max_qpu_seconds` and `quantum.max_qpu_usd`, checked before a job is submitted. QPU seconds and cost appear in run statistics (`qpu_seconds`, `qpu_usd`). The price table is illustrative and configurable (`quantum.pricing`).
  - **Q3 Uncertain results:** every quantum tool reports a confidence from its shot statistics and verification status; an agent returning `uncertain<T>` carries the lower of the model's and the quantum result's confidence.
  - **Q4 Noise:** exact density-matrix simulation of depolarising and readout noise (Pauli trajectories above 8 qubits), readout-error mitigation from calibration circuits, zero-noise extrapolation by gate folding, and the Hellinger fidelity of every noisy run.
  - **Q5 Verification:** results are `VERIFIED`, `GAP`, `BOUNDED` (within `bound_pct` of a proven block-decomposition lower bound) or `UNCHECKED`; QAOA on noisy and hardware backends samples the real circuit (angles optimised on the simulator).
  - **Q6 Algorithms:** `quantum.vqe` (H₂ to chemical accuracy, Ising and Heisenberg chains, custom Pauli Hamiltonians; Rotosolve), `quantum.kernel` (ZZ feature-map fidelity kernel against a tuned RBF kernel, 5-fold cross-validated, PSD-projected shot estimates), `quantum.amplitude`, `quantum.knapsack` (checked against dynamic programming), `quantum.colouring`, `quantum.backend`.
  - **Q7 Provenance and replay:** backend, device, calibration, depth, shots, job id, QPU seconds, cost, fidelity and a replay key in every audit record (`"quantum"`); counts of non-simulator runs are recorded under `runs/quantum/` and `"replay": "prefer" | "only"` reuses them with no QPU time.
- **Q8 Post-quantum audit signatures** (`algotrust.py`): `"audit": {"algorithm": "ml-dsa-44" | "ml-dsa-65" | "ml-dsa-87" | "hybrid"}`. Hybrid signs every record with Ed25519 and ML-DSA-65; evidence packs carry a post-quantum manifest signature; `algo audit verify` and `algo evidence verify` check both. Needs `pip install "algolang[pq]"`.
- Eval expectations `expect fidelity > x` and `expect qpu < N`.
- **AlgoQ Quantum AI Lab™** (`enterprise-apps/quantum-ai-lab/`): VQE chemistry, capital budgeting with two approvals, spectrum planning, a quantum-kernel study and tail risk on a noisy simulator; 7 evals, behaviour tests, system card and figure.
- Optional extras `pq`, `ibm`, `braket`, `azure`; CI checks the hardware path's QAOA and VQE circuits against Qiskit statevectors.

### Changed
- `max qubits` may now be up to 1,000 (for hardware backends); the simulator's own ceiling (24) is still enforced at run time.
- `quantum.qubo`, `quantum.maxcut` and `quantum.routes` run on whichever backend is configured and add a confidence line.


## [0.5.0] — 2026-11-11 · Ten large-scale domain applications

v0.5 applies AlgoLang to ten demanding domains, one application each. Every application runs real, deterministic algorithms over large synthetic datasets as company tools; the AlgoLang program around them adds parallel agents, deterministic guards, human gates, four-eyes approvals, risk levels, evals, behaviour tests, system cards and an animated flow figure. Quantum AI, previously planned as v0.5, moves to v0.6, and Interoperability to v0.7.

### Added
- **AlgoML Model Factory™** (`ml-model-factory`): logistic regression, a deep network trained with Adam and gradient-boosted trees compared by 5-fold cross-validation on 6,000 customers; leakage detection and population-stability drift checks.
- **AlgoRL Control Room™** (`rl-control-room`): shielded Q-learning for microgrid battery dispatch, compared with value iteration and stress-tested; only avoidable safety violations count against a policy.
- **AlgoXAI Audit Studio™** (`responsible-xai-studio`): exact Shapley values, a group fairness audit and counterfactual recourse; signed audit.
- **AlgoNLP Document Intelligence™** (`nlp-document-intelligence`): Naive Bayes triage of 3,000 messages (macro-F1 0.893), entities, TextRank summaries and emerging-topic alerts.
- **AlgoBharat Bhasha Desk™** (`bharat-language-desk`): eight Indian languages and scripts: detection, transliteration, intent and approved replies, with measured coverage on unseen phrasings.
- **AlgoCare Remote Monitoring™** (`digital-health-monitor`, **risk high**): exact NEWS2 scoring, medicine checks, a 5,000-patient cohort watch and a live AlgoPulse™ vitals stream.
- **AlgoBio Network Lab™** (`network-biology-lab`): Brandes betweenness, label propagation with modularity, random walk with restart validated on hidden disease genes with a negative control, hypergeometric enrichment with Benjamini–Hochberg FDR, six-frame ORF analysis.
- **AlgoEng Predictive Maintenance™** (`predictive-engineering`): FFT vibration diagnosis (1×, 2×, bearing outer race), ISO 10816-style zones, exponential remaining-life estimates with intervals for 1,000 pumps, earliest-deadline-first crew scheduling.
- **AlgoCity Operations Centre™** (`smart-city-operations`): CPCB National AQI for 60 stations, sweep + nearest-neighbour + 2-opt waste routing, seasonal feeder-load forecasts with back-test, and a live air-sensor stream.
- **AlgoMove Transport Network Optimizer™** (`transport-network-optimizer`): Dijkstra incident detours on 1,600 junctions, Webster signal timing for 576 signals, a doubly constrained gravity model with Furness balancing, and bus headway and fleet planning.
- `algo run FILE --flow NAME` runs any flow of a program (the generated script keeps a table of flows; `ALGO_FLOW` selects one).
- Figures for every new application; the README "What's new", applications and roadmap figures are updated.

### Changed
- The offline mock model keys its sample jitter on the canonical form of a goal, so robustness tests measure the program rather than the wording of a goal.

### Fixed
- String literals with non-ASCII characters (₹, →, —, Hindi and other scripts) were garbled by the compiler: escapes were decoded as Latin-1. They now keep every character exactly as written; `\n`, `\"` and other escapes still work. Regression test in `tests/test_trust.py`.

## [0.4.1] — 2026-11-09 · LLM & SLM graph optimisation

### Added
- **AlgoGraph™ LLM & SLM Optimizer**, the eleventh enterprise application (`enterprise-apps/llm-graph-optimizer/`):
  - `cascade_router.algo`: an SLM-first cascade written with the language's own features. A deterministic guard sends clearly complex requests to a large model; otherwise a small model answers, sampled as `uncertain<text>`, and only answers it is unsure of go to the large model.
  - `graph_optimizer.algo`: reads any AlgoLang program's data-flow graph from the compiler and chooses the cheapest model for every agent that meets its quality floor (by task class) and the end-to-end latency limit (parallel agents overlap, branches at worst case). Exact branch and bound, cross-checked by brute force when the search space is small; the result says `VERIFIED` or `INFEASIBLE`. Only verified plans are reviewed, and rollout needs two approvals.
  - Tools `slm.triage`, `graph.analyze` and `graph.optimize`; an illustrative model catalog of large and small models; behaviour tests, evals, batch data, system cards and figures.
- **Small language models on your own GPUs.** `LocalBackend` talks to any OpenAI-compatible server (Ollama, vLLM, llama.cpp server, LM Studio): model ids start with `local:`, configured under `"local_models"` in `algo.config.json`. With `--live`, `local:` agents go to that server and the others to Claude; programs that use only local models run live without `ANTHROPIC_API_KEY`. Declared tools run first and their results are given to the model as context.
- **`"agent_models"`** in `algo.config.json` routes any agent to another model without editing the program (this is how an optimiser plan is applied).
- Prefix entries such as `"local:*"` in the `pricing` and `energy` tables (local models default to no API cost and lower energy).
- `tests/test_llm_graph.py`: branch and bound against brute force on 150 random graphs, the optimiser on real programs, path safety, triage, model routing, prefix pricing, and the local backend against a fake OpenAI-compatible server.

### Fixed
- Windows: LF line endings are pinned in `.gitattributes`, system-card hashes ignore line endings, and evidence packs always use forward slashes.
- System cards no longer embed the AlgoLang version, so a release does not make committed cards stale.

## [0.4.0] — 2026-11-09 · Trustworthy AI

v0.4 makes trustworthiness something a program can prove. The compiler checks that each safeguard a system needs is present, the runtime enforces it, `eval` blocks measure it, and the toolchain writes the evidence an auditor reads.

### Added
- **Risk levels.** `risk minimal | limited "purpose" | high "purpose"` and `disclose "…"`. Limited and high risk need a disclosure. High risk also needs, at compile time: human oversight in every flow (**E125**), fairness and robustness tests (**E126**), `redact pii` on every agent and `explain with evidence` on every reviewed decision (**E127**), a stated purpose and signed audit logs (**E129**). The runtime refuses to run a high-risk program whose audit log is not signed.
- **Privacy.** `redact pii` masks names, emails, phone numbers, Aadhaar, PAN, IFSC, passport, account and card numbers (Luhn-checked) and dates of birth before any prompt is built. Trusted tools still receive the real values, and their answers are masked again, including any value already seen. `forbid <attribute>` now also withholds that attribute's values (female, Hindu, married, aged 45 …), even when misspelt. `retain audit|traces N days` drops older records after each run; a signed checkpoint keeps the audit chain verifiable. An org can set `"redact_pii": true`, `"retention"` and `"protected_values"` in `algo.config.json`.
- **Explainability.** `explain` (reasons) and `explain with evidence` (reasons plus quotes). Quotes that are not in the agent's inputs or tool results are asked for again, then the result goes to a person. Reasons and evidence are stored in the audit log and returned on `Result.reasons` / `Result.evidence`.
- **Security.** `tool x untrusted` (also with `from mcp`): output is size-limited, instruction-like lines are removed and recorded, and the text is wrapped as data that live models are told never to obey. MCP servers can be pinned with `"sha256"` in `mcp_servers`; a changed server program is refused before it starts.
- **Human oversight.** `require human for always` and `require approvals N` (different named reviewers; four-eyes = 2). `algo review approve … --override "…"` records a corrected answer. Every reviewer decision is also written into the run's own audit chain. Studio shows the reason and approval progress.
- **Accountability.** `"audit": {"sign": true}` signs every audit record with Ed25519 (built-in RFC 8032 implementation; uses the `cryptography` package when installed). `algo keys init` creates the key (git-ignored); `"public_keys"` pins trusted keys; `ALGO_AUDIT_KEY` supplies a key from a secret store. `algo audit verify` checks hashes, links and signatures.
- **Fairness and robustness tests.** `expect fair across <attribute> [values]` reruns a case once per value and requires the same decision and scores within `fairness_tolerance` (default 0.05). `expect robust (typos, paraphrase, reorder, case, spacing) consistency >= x` reruns it with meaning-preserving changes; numbers, IDs and codes are never altered. `expect explained` requires every explanation to be grounded. Offline, the mock behaves like an ideal model, so these tests measure the program; with `--live` they measure the model.
- **`algo card`**: an AI system card (Markdown + JSON) generated from the source: purpose, risk level, disclosure, agents, tools, oversight, data protection, tests and known limitations. `--check` fails when a committed card is stale.
- **`algo trust report`**: ten trustworthy-AI properties per program (met, gap, fail, not tested, not required), with evidence, mapped to NIST AI RMF functions and EU AI Act articles, as text, JSON or HTML.
- **`algo evidence export | verify`**: a signed zip with the source, config, system card, eval results, audit logs, review queue, traces and trust report; verification checks every file hash, the manifest signature and every audit chain.
- **`algo retention`** applies the organisation's retention limits on demand.
- **Enterprise applications.** All 25 programs declare a risk level. Credit decisions, university admissions, ER triage and welfare eligibility are high risk and meet every rule, with four-eyes or always-on review, fairness tests across gender, religion, caste and marital status, robustness tests and signed audit logs. Six more programs are limited risk and disclose AI use. Every program ships a generated system card in its app's `cards/` folder.
- `tests/test_trust.py` (24 tests: RFC 8032 vectors, PII never reaching a backend, injection that cannot flip a guard, four-eyes approval, tampering, retention, fairness and robustness, cards, reports and evidence packs). A CI job runs them with the built-in Ed25519, builds trust reports for all ten apps, and verifies and then tampers with the evidence packs of the four high-risk programs.
- **Language manual v0.4** (`docs/AlgoLang_Documentation_v0.4.pdf`, 98 pages): a new *Trustworthy AI* chapter, a summary of the 0.3.1–0.3.4 features, and error codes E122–E130.
- Figures: a new *What's new* figure for the ten properties, updated governance, roadmap and layout figures, and risk-level chips on every application figure. Editor support: v0.4 keywords, hover help and snippets.

### Changed
- A program's `policy { }` block now also applies its trust rules (`redact pii`, `forbid`, `explain`, `retain`) to agents imported with `use`.
- Eval runs keep their own audit log and review queue (`runs/eval/`), so they no longer fill the real review queue.
- `ROADMAP.md`: v0.4 is released; v0.5 Quantum AI is next.

## [0.3.4] — 2026-11-09

### Added
- **AlgoPulse™, AlgoLang's own real-time event engine** (`algopulse.py`). A bus is a folder of durable, append-only topic logs with numbered offsets and consumer groups. Every event is fsync'd before it is acknowledged, and file locks keep offsets gap-free when several programs write at once. `algo pulse serve` shares a bus over HTTP behind a bearer token (`ALGO_PULSE_TOKEN`), and refuses to listen beyond localhost without one. Topic and group names are validated so they can never escape the bus folder.
- **`algo pulse serve | publish | topics | tail`**, and `algo stream FILE --pulse` to run a `stream` block on the bus named in it. A stream resumes from its consumer group's committed offset. `"pulse"` in `algo.config.json` names each bus: a local folder (`{"dir": …}`) or a served bus (`{"url": …, "token_env": …}`). `ALGO_PULSE_URL` points every bus at one server.
- **Animated figures for every README section and every application.** `tools/make_figures.py` draws the section figures, plus one figure per program for all 25 programs in the ten enterprise applications. Application figures are laid out from each program's real data-flow graph, with parallel agents, decisions, uncertain agents and human gates marked, so a figure always matches its code. CI fails if a committed figure is out of date. The figures are pure SVG (CSS and SMIL animation, no scripts) and stand still for readers who prefer reduced motion.
- CI job **Real-time streams · AlgoPulse server**: it starts a real server, runs the stream tests (including a served-bus round trip) and streams the trading desk's order flow through it.

### Changed
- `stream` blocks read from AlgoPulse: `from pulse "bus" topic "t" group "g"`. The trading desk and SOC applications, their configs, docs and editor support are updated to match.

### Removed
- The external message-broker adapter from 0.3.1, with its client dependency, deploy files and CI job. Streams now need nothing outside AlgoLang.
- The lab website (`lab-website/`), with its README section and badge. The package homepage is now www.algoprofessor.com.

## [0.3.3] — 2026-11-08

### Added
- **Quantum circuits in the language.** `circuit Name { qubits n  gate qi, qj  measure }` with the standard gates (`h x y z s sdg t tdg id rx ry rz p u1 u2 u3 cx cy cz ch crz cp cu1 swap ccx`) and angles such as `pi/4`. One-qubit gates can list several qubits. Each circuit compiles to OpenQASM 2.0 and becomes the tool `circuit.Name`, which agents use under their `shots` and `max qubits` policy. The compiler checks every circuit (**E124**).
- **`algo quantum list | export | run FILE [NAME]`**: list a program's circuits, export them as `.qasm` files for Qiskit, IBM Quantum, Braket and others, or run one and see a histogram.
- **`quantum.routes`**: logistics routing as a one-hot QUBO (one route per shipment, plus shared-lane clash costs) solved by QAOA, `VERIFIED` against the exact optimum and checked `FEASIBLE`. Reads a CSV (shipment, route, cost, lane) or inline text.
- **`quantum.scenarios`**: one-factor Monte Carlo value at risk and expected shortfall from qubit draws, with a quantum amplitude estimation of the tail probability: its estimate, oracle calls and error bound, next to the Monte Carlo sample count needed for the same error. `BREACH` / `WITHIN LIMIT` against a stated limit.
- **`pqc.scan`**: quantum-safe readiness of a cryptography inventory. It flags what Shor's algorithm breaks and what Grover's search weakens, applies Mosca's harvest-now-decrypt-later rule (`pqc.quantum_threat_years`, `pqc.migration_years`) and names the NIST FIPS 203 / 204 / 205 replacement (ML-KEM, ML-DSA, SLH-DSA).
- **Four quantum applications**: `pqc_readiness.algo` (SOC Incident Command), `risk_scenarios.algo` (Algo Trading Desk), `route_optimizer.algo` (Supply Chain Control Tower) and `circuit_lab.algo` (Quantum Optimization Lab), each with an `eval` block, behaviour tests and sample data.
- Tests: circuits against Qiskit, routing against brute force, Monte Carlo VaR against the normal formula, QAE within its error bound, the crypto rules and Mosca's test.
- Editor support for `circuit`, `qubits` and `measure`, with hover help and a snippet.

## [0.3.2] — 2026-11-08

### Added
- **Quantum tools (preview).** Five built-in tools that agents can declare and use like any other: `quantum.run` (OpenQASM 2.0 circuits → measurement counts), `quantum.qubo` (QAOA on a QUBO), `quantum.maxcut` (QAOA max-cut on a weighted graph), `quantum.grover` (Grover search) and `quantum.random` (random bits or "pick k of n" sampling).
- **Exact verification of every optimisation.** QAOA answers are compared with the exact classical optimum. The first line of the result says `VERIFIED` or `GAP: … % worse`, so a deterministic guard (`if r contains "VERIFIED"`) decides whether an agent may use it. Results also report P(optimal), the approximation ratio, the most frequent bitstrings and the backend.
- **Quantum policies.** `shots N` and `max qubits N` in agent policies, and a `"quantum"` section in `algo.config.json` (`backend`, `max_qubits`, `shots`, `seed`, `qaoa_layers`). The stricter qubit limit wins, and bigger circuits are `BLOCKED` before they run. Runs are seeded, so audits and replays reproduce.
- **E123**: `shots` outside 1–100000, or `max qubits` outside 1–24.
- **`algoquantum.py`**: a NumPy state-vector simulator (Qiskit bit order, checked against Qiskit to a fidelity error below 10⁻¹²), an OpenQASM 2.0 reader, QAOA with layer-by-layer warm starts, QUBO builders for portfolios (with a cardinality penalty) and max-cut, Grover search, and an optional Qiskit Aer backend for `quantum.run`.
- **Quantum Optimization Lab** enterprise application: a QAOA portfolio optimiser with risk review and human approval, a max-cut shift scheduler and quantum-random audit sampling, with eval blocks, behaviour tests and batch data.
- **CI**: a quantum job runs the quantum tests with the Qiskit cross-check and the lab's evals, and compares a Bell circuit on the simulator and on Qiskit Aer. The `algolang[quantum]` extra and `requirements-quantum.txt` install NumPy.
- **README**: an animated quantum pipeline diagram and a Quantum applications section. **ROADMAP**: the v0.5 Quantum AI plan, covering hardware backends, QPU budgets, noise mitigation, uncertain quantum results, bounded verification, an algorithm library, provenance and post-quantum audit signatures.

### Changed
- The planned v0.4 risk-governance errors move to E124–E127, because E122 and E123 are now in use. Interoperability moves from v0.5 to v0.6.

## [0.3.1] — 2026-11-08

_The first real-time version ran on an external message broker; 0.3.4 replaced it with AlgoPulse™, AlgoLang's own event engine._

### Added
- **Real-time streams.** A new `stream name on flow { … }` block binds a flow to an event topic, with `map input = event.path`, `key event.id`, `to topic`, `escalate to topic`, `dead letter topic` and `max in flight N`. Every event runs the flow once, under the same policies, budgets, human gate and audit log as any other run.
- **`algo stream`** runs a stream offline (`--input events.jsonl`) or live, stops after `--max` events or `--idle` seconds, and writes per-stream metrics: events/s, latency p50/p95, ok / escalated / dead-letter counts, tokens, cost and energy.
- **Delivery and routing.** At-least-once delivery: offsets are committed only after results are written and flushed. Keys already seen in the session are skipped. Each result goes to exactly one topic: ok → `to`, escalated → `escalate to`, invalid, blocked or failed → `dead letter`. Undeclared routes fall back to `to`.
- **E122**: stream errors (unknown flow or input, a mapping that does not read from `event`, a result topic equal to the source topic, `max in flight` outside 1–256).
- **Streams in two enterprise apps**: Algo Trading Desk (`orders.intent` → pre-trade risk gate) and SOC Incident Command (`soc.alerts` → incidents), with sample event files. `enterprise-apps/run_all.py --batch` replays them offline.
- **README**: an animated hero banner, a real-time pipeline diagram and Mermaid diagrams for the architecture, the life of an agent call and the handling of one event.
- Editor support: the `stream` keyword in the VS Code grammar, plus hover help and a `stream` snippet in the language server.

## [0.3.0] — 2026-10-29

### Added
- **`uncertain<T>` types.** An agent can return `uncertain<score>` (or any type). The runtime samples it `samples N` times (default 3, at most 15). Scores are averaged and other types decided by majority vote. Confidence blends the model's own confidence with how much the samples agree. Conditions can read `x.confidence` and combine comparisons with `and` / `or`.
- **`eval` blocks.** `eval name on main { case "label" (input = "…") { expect … } }` with `expect status`, `called`, `not called`, `tool`, `output contains`, `emits`, `tokens`, `cost`, `energy`, `escalated` and `confidence`. Run them with `algo eval file.algo`.
- **Traces and replay.** `algo run --trace`, `Program.run(trace=True)` and every eval case record a trace: inputs, each call's prompt hash, outputs and samples. `algo replay trace.json` and `algo eval --replay` answer every agent from the recording with zero tokens and zero cost, and report which agents now receive different inputs ("replay misses") after a change. New `ReplayBackend` and `Program.replay()`.
- **MCP tool bindings.** `tool kb.search_policies from mcp "company-kb"` binds a tool on a Model Context Protocol server (stdio or streamable HTTP) configured under `mcp_servers` in `algo.config.json`. Live mode passes the server's own input schema to the model. New `algo mcp servers | list | call`. A demo server ships in `examples/v03/`. No extra dependencies.
- **Cost and energy budgets.** `budget cost 0.05 usd` (or `inr`) and `budget energy 2 wh` (or `kwh`) per agent; org caps `max_budget_cost_usd` / `max_budget_energy_wh` and run caps `max_run_cost_usd` / `max_run_energy_wh`. Calls are priced before they run and blocked when over budget. Every audit record carries `cost_usd` and `energy_wh`; run stats add `co2_g`; `algo report` shows money (USD and ₹) and energy per program. Prices and energy factors live in the `pricing` and `energy` tables in the config; the defaults are placeholders.
- **Language server.** `algo lsp` (stdio) provides diagnostics, hover, completion (including packs after `use pack` and snippets), go to definition (including into imported files and domain packs) and document symbols. The VS Code extension (v0.3.0) starts it automatically; other editors can run the same command.
- New compile errors: **E117** (uncertain value compared without its confidence), **E118** (bad `.confidence` read), **E119** (eval block errors), **E120** (unknown MCP server), **E121** (bad policy value).
- `examples/v03/`: an expense desk touring every v0.3 feature, with an MCP demo server and an eval block.
- **Deterministic guards.** `if x contains "TEXT"` and `if x not contains "TEXT"` check an agent's result and its tools' full answers with no model involved, so hard rules (risk limits, failed thresholds) cannot be overruled by a model.
- **Algo Trading Desk (QuantOracle™)** enterprise application: strategy review board, pre-trade risk gate with hard limits and human approval of every paper order ticket, and an end-of-day risk and surveillance report. It uses `uncertain<score>`, `contains` guards, cost and energy budgets and `eval` blocks, and is for research and paper trading only.
- **AlgoLang: 50 Sample Programs** (`docs/AlgoLang_50_Sample_Programs.pdf`, 106 pages) with the runnable source of all 50 programs in `examples/50-programs/`, run in CI on every push. The PDF is published with each release and on the website.
- `ROADMAP.md`: v0.4 is dedicated to trustworthy AI (fairness and robustness tests, system cards, explainability, PII redaction, untrusted-tool security, four-eyes oversight, signed audit, risk levels, trust reports).

### Changed
- README restructured around the language's objective, design principles and a numbered table of contents.
- Live backends report input and output tokens separately, so they are priced correctly.
- Run summaries show the estimated live cost, energy and CO₂, labelled as estimates for offline runs.
- The language manual is now `docs/AlgoLang_Documentation_v0.3.pdf` (91 pages) with a new chapter on v0.3; the v0.2 PDF is removed.

### Fixed
- Cached agent calls now keep their tool results, so `contains` guards and traces see tool output on a cache hit. Cache keys are versioned, so older entries without tool results are not reused.

### Also in this release
- **Eight enterprise applications** (`enterprise-apps/`): claims operations, hospital care coordination, bank credit & KYC onboarding, university admissions & OBE, SOC incident command, supply chain control tower, citizen services and legal contract review. Each ships with org policy, company tools over its own data, a knowledge base, 14 programs in total, sample batch data and 20 behaviour tests, all run in CI with `enterprise-apps/run_all.py --batch`.
- **ProfAlgoLabs™ website** (`lab-website/`): a 3D branded site for www.profagentlabs.algoprofessor.com with 10 services, a lab console, a visitor counter, a hardened contact form, CSP/HSTS security headers and full SEO (schema.org, sitemap, Open Graph).
- The project homepage is now www.profagentlabs.algoprofessor.com (README badge and package metadata).

## [0.2.0] — 2026-10-29 · Enterprise

### Added
- **Modules:** `use "file.algo" as x` and `use pack sector.name as x`, aliased agent calls (`x.Agent(...)`), file-level `policy { }` defaults, and circular-import detection.
- **Organisation policy:** `algo.config.json` sets forbid, `max_budget_tokens`, `min_human_below`, `allowed_tools`, `max_concurrency`, `max_run_tokens`, cache, models, tools and plugins. When it conflicts with a program's policy, the stricter rule wins.
- **Compile-time org checks:** an org-forbidden input is reported as **E108**; a tool outside `allowed_tools` is reported as the new **E115**.
- **120 domain packs** in 20 sectors (`packs/`, `packs/catalog.json`), with offline plain-English search.
- **Governance:**
  - SHA-256 hash-chained audit logs (`algo audit verify`);
  - an event-sourced human review queue (`algo review`);
  - usage reports (`algo report`);
  - a SQLite response cache.
- **Executable tools:** built-in `calc.eval`, `file.read` and `kb.search`, plus plugin tools. Live mode runs a Claude tool-use loop, and refused tool requests are recorded.
- **Behaviour specs:** `tests/specs/*.algotest.json` cover the examples, the enterprise module program, packs from six sectors and two fairness block cases. CI runs them with `algo dev test`.
- **Scale:** `algo batch`, `Program.run_batch`, and a global concurrency limit.
- **Python SDK** `import algolang`: `compile`, `load`, `pack`, `Program`, `RunResult`, `domains`, `compose`, `ask`, `audit`, `review`, `tool`, `configure` and `batch_csv`.
- **Three modes on one SDK:**
  - CLI, including `algo chat` and the enterprise commands;
  - Studio, with Domains, Batch and Governance tabs;
  - the new **Prompt UI** (`algo ui`).
- **Developer track:**
  - `algo dev lint | test | graph | new-tool | new-pack | ci`;
  - `*.algotest.json` behaviour specs;
  - pip packaging: a wheel on every release, and `pip install git+https://github.com/drssnaiml1-cell/algolang`;
  - an 80+ test pytest suite;
  - GitHub Actions for CI, releases, Pages and Docker;
  - a website on GitHub Pages: overview, a searchable domain library, a browser playground (Pyodide) and the guides;
  - `DEVELOPER_GUIDE.md`.

### Changed
- Domain search understands everyday wording across all 20 sectors (for example *"cotton leaves have yellow spots"* → `agriculture.pest_diagnosis`).
- The Dockerfile now ships the full toolchain, packs and UIs.

## [0.1.0] — 2026-10
### Added
- First release: agents, flows, `par` / `par for`, policies (budget, retry, timeout, human gate, forbid), compiler checks E100–E114, mock and live backends, audit log, `algo` CLI and menu, shell, Studio, `algo ask` / wizard, the Jupyter `%%algo` magic, the documentation book and the slide deck.

[Unreleased]: https://github.com/drssnaiml1-cell/algolang/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/drssnaiml1-cell/algolang/releases/tag/v0.2.0
