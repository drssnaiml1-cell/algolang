# AlgoLang roadmap

**Current release: v0.4.0 — Trustworthy AI** · **Next: v0.5 — Quantum AI** · **Then: v0.6 — Interoperability, v1.0 — native runtime**

AlgoProfessor AI R&D Solutions, Hyderabad. Designed by Dr. S. Satyanarayana. [www.algoprofessor.com](https://www.algoprofessor.com)

---

## 1. v0.4 Trustworthy AI (released in 0.4.0)

**Make trustworthiness something an AlgoLang program can prove, not just claim.**

> **Status: released in v0.4.0.** All ten work packages below shipped, with tests (`tests/test_trust.py`), a CI job that builds and tamper-tests evidence packs, and four high-risk enterprise programs that compile under `risk high`. Where the shipped syntax differs from the sketch, the sketch has been updated. The compiler errors are **E125–E130** (E122–E124 were taken by streams, quantum tools and circuits).

v0.1–v0.3 made agentic AI *governed*: policies, audit chains, human review, uncertainty and budgets. v0.4 makes it *trustworthy by evidence*. The compiler will check that each safeguard a system needs is present, and the runtime and `eval` blocks will produce evidence that it worked. An auditor, regulator or customer can then read that evidence.

### Specific objectives

| No. | Objective | Measured by |
|---|---|---|
| 1 | **Fairness:** decisions do not change when only a protected attribute changes | Counterfactual `eval` tests pass; fairness gap reported per program |
| 2 | **Robustness:** decisions are stable under harmless changes to the input | Perturbation tests pass; consistency score ≥ threshold |
| 3 | **Transparency:** every system documents itself | `algo card` produces an AI system card from the source |
| 4 | **Explainability:** important decisions come with reasons and evidence | `explain` policy enforced; reasons stored in the audit log |
| 5 | **Privacy:** personal data is minimised and masked | `redact pii` enforced before any model call; retention limits applied |
| 6 | **Security:** tools and MCP servers cannot hijack agents | Untrusted-tool mode fences tool output; injection tests pass |
| 7 | **Human oversight:** people decide what matters | `require human for`, four-eyes approval and logged overrides |
| 8 | **Accountability:** evidence cannot be altered unnoticed | Signed audit chains; exportable evidence packs |
| 9 | **Risk-based governance:** stricter rules for higher-risk systems | `risk high` header triggers compile-time requirements |
| 10 | **Assurance:** one report shows how the system meets each trustworthy-AI property | `algo trust report` scorecard with links to the evidence |

---

## 2. Frameworks we align with

AlgoLang features are designed to *produce evidence* for these frameworks. Using AlgoLang does not by itself make a system compliant or certified: that needs an organisation's own risk management, legal review and, where required, a conformity assessment.

| Framework | What it asks for | Where AlgoLang helps |
|---|---|---|
| **NIST AI Risk Management Framework (AI RMF 1.0)**: Govern, Map, Measure, Manage | Policies, context and risk mapping, measurement, risk treatment | `algo.config.json` org policy (Govern); `risk` header and system cards (Map); `eval`, fairness and robustness tests (Measure); guards, human review and budgets (Manage) |
| **EU AI Act**: risk-based obligations for high-risk AI systems | Risk management, data governance, technical documentation, record-keeping, transparency, human oversight, accuracy, robustness and cybersecurity | `risk high` requirements, system cards, hash-chained and signed logs, `require human`, `uncertain<T>`, eval evidence, untrusted-tool mode |
| **ISO/IEC 42001**: AI management system | A managed process with controls, records and continual improvement | Org config as controls, audit and trace records, `algo trust report` as management-review input |
| **OECD AI Principles** | Human-centred values, transparency, robustness, accountability | The language's design principles |

---

## 3. v0.4 work packages

Each package lists its syntax (a sketch; final syntax may change), what the compiler and runtime do, and how we will know it is done.

### WP1 · Fairness testing

```algo
eval fairness on main {
    case "same CV, different gender" (cv = "Asha Rao, Python, SQL, 3 years") {
        expect fair across gender ["female", "male", "non-binary"]
        expect fair across religion ["Hindu", "Muslim", "Christian", "Sikh"]
    }
}
```

- The runtime rewrites the input once per attribute value, runs every variant, and compares the decisions and scores.
- `expect fair` fails if the decision changes or a score moves by more than `fairness_tolerance` (default 0.05).
- **Done when:** counterfactual results appear in `algo eval` output, `--json`, and the trust report.

### WP2 · Robustness testing

```algo
expect robust (typos, paraphrase, reorder) consistency >= 0.9
```

- Generated perturbations of each case input are run, and the share of unchanged decisions is measured. This builds on `uncertain<T>` sampling.
- **Done when:** the consistency score is reported per case, and failing cases show the perturbation that broke them.

### WP3 · Transparency: AI system cards

```bash
algo card programs/loan_decision.algo        # → loan_decision.card.md / .json
```

- Generated from the source and config, never hand-written: purpose, agents and models, tools and MCP servers, forbidden attributes, human-oversight points, budgets, risk level, eval coverage and known limitations.
- **Done when:** every enterprise application ships a generated card, and CI fails if a card is stale.

### WP4 · Explainability

```algo
agent CreditChair(application: text, views: list) -> text {
    goal "Recommend approve, refer or decline for {application}"
    policy { explain with evidence }          // reasons + cited evidence are required
}
```

- The model must return `reasons` and `evidence` (tool results, inputs) with its answer. The runtime checks that the cited evidence exists in the call's inputs or tool outputs, and stores it in the audit log.
- **Done when:** a missing or ungrounded explanation is retried, then escalated to a human.

### WP5 · Privacy

```algo
policy { redact pii  retain audit 180 days  retain traces 30 days }
```

- Personal data (names, phone numbers, emails, Aadhaar/PAN-style identifiers, account numbers) is detected and masked before a prompt is built. Masks are reversible only inside approved tools.
- Retention limits are enforced on audit logs, traces and caches.
- **Done when:** a test suite of synthetic personal data shows nothing unmasked reaches a backend.

### WP6 · Security for tools and MCP

```algo
tool web.fetch from mcp "browser" untrusted
```

- Shipped: fencing of untrusted output (instruction-like lines removed and recorded, size limit, data markers), live-model instructions never to follow fenced text, and MCP server pinning with `"sha256"` in `mcp_servers`. Network sandboxing of tool code stays the job of the host (containers, firewalls).

- Output from untrusted tools is fenced as data, scanned for prompt-injection patterns and size-limited. Instructions inside it are never followed.
- Tools are deny-by-default for network and file access. MCP servers can be pinned to a version and a hash.
- **Done when:** a red-team suite of injection payloads cannot change a flow's decision.

### WP7 · Human oversight

```algo
policy { require human for always }           // every call, e.g. order tickets
policy { require approvals 2 }                // four-eyes for high-impact actions
```

- Reviewer identity, decision, reason and any override of the model are recorded in the audit chain.
- **Done when:** Studio's Governance tab and `algo review` support two-person approval.

### WP8 · Accountability

- Audit chains are signed (Ed25519) with an organisation key. `algo audit verify` checks both the signatures and the hash chain.
- `algo evidence export` bundles the audit log, traces, eval results, system card and config into one verifiable archive.
- **Done when:** tampering with any file in an evidence pack is detected.

### WP9 · Risk-based governance

```algo
risk high "Credit decisions about individuals"     // program header
```

| Level | The compiler requires |
|---|---|
| `minimal` | nothing extra |
| `limited` | a system card and a disclosure that users are talking to AI |
| `high` | everything above, plus human oversight on every decision, `explain`, `redact pii`, fairness and robustness evals, signed audit logs |

- Errors (as shipped): **E125** high-risk flow without human oversight · **E126** without fairness or robustness evals · **E127** an agent without `redact pii`, or a reviewed decision without `explain with evidence` · **E128** forbidden attribute reachable through a tool · **E129** risk declaration problems (unknown level, missing `disclose` or purpose, high risk without signed audit) · **E130** trust value errors.
- **Done:** all 25 programs in the ten enterprise applications declare a risk level and compile under it; four are high risk.

### WP10 · Assurance reporting

```bash
algo trust report enterprise-apps/bank-credit-onboarding
```

- A scorecard per program: each trustworthy-AI property, the evidence for it (tests, logs, cards) and gaps to fix, mapped to NIST AI RMF functions and EU AI Act duties.
- Available as HTML, JSON and in Studio.
- **Done when:** an auditor can trace every claim in the report to a file in the evidence pack.

---

## 4. Foundations from v0.1 – v0.3.4

| Trustworthy-AI property | Shipped |
|---|---|
| Accountability | SHA-256 hash-chained audit log, `algo audit verify` (v0.2) |
| Human oversight | `require human when confidence < x`, review queue with named reviewers (v0.1–v0.2) |
| Fairness (by construction) | `forbid` attributes, compile-time **E108**, org-wide forbidden list (v0.1–v0.2) |
| Honest uncertainty | `uncertain<T>` sampling, `.confidence`, **E117** (v0.3) |
| Deterministic hard rules | `if x contains "…"` guards that no model can overrule (v0.3) |
| Reproducibility | Traces, `algo replay`, `eval --replay` (v0.3) |
| Tool governance | declared tools, `uses` grants, `allowed_tools`, MCP bindings under the same rules (v0.2–v0.3) |
| Sustainability and cost control | cost and energy budgets, CO₂ reporting (v0.3) |
| Oversight in real time | `stream` blocks: every event governed, routed to review or dead-letter topics, nothing dropped (v0.3.1) |
| Verified quantum results | `quantum.*` tools check every optimisation against the exact optimum; `shots` / `max qubits` policies, **E123** (v0.3.2) |

---

## 5. v0.5 Quantum AI

**Objective: let agents use real quantum computers for real business problems, with results that are verified, bounded and accountable.**

The v0.3.2 preview already gives agents five quantum tools (`quantum.run`, `quantum.qubo`, `quantum.maxcut`, `quantum.grover`, `quantum.random`) on an exact simulator. Every optimisation is VERIFIED against the exact optimum, `shots` and `max qubits` live in the policy, and the Quantum Optimization Lab enterprise application uses them in governed flows. v0.5 takes this to quantum hardware without giving up any of those guarantees.

### Specific objectives

| No. | Objective | Measured by |
|---|---|---|
| 1 | **Hardware access:** run the same program on a simulator or a real quantum processor (QPU) by changing one config line | Backends for IBM Quantum (Qiskit Runtime), Amazon Braket and Azure Quantum pass the same eval blocks |
| 2 | **Budgets for QPU time:** quantum hardware is scarce and expensive | `budget qpu 30 seconds` and `budget cost 2 usd` checked before a job is submitted; QPU cost in `algo report` |
| 3 | **Honest uncertainty:** a quantum answer is a distribution, not a fact | Quantum tools can return `uncertain<T>`; confidence comes from shot statistics and P(optimal); **E117** applies |
| 4 | **Noise awareness:** results from noisy devices are labelled and mitigated | Noise models in the simulator; readout-error mitigation and zero-noise extrapolation; `expect fidelity > x` in evals |
| 5 | **Verification beyond the simulator:** what if the problem is too big to check exactly? | Classical solvers give bounds: answers are `VERIFIED`, `BOUNDED` (within x% of a proven bound) or `UNCHECKED`, and guards can require the first two |
| 6 | **More algorithms:** cover the main families of near-term applications | VQE (molecular energies), quantum kernels (classification), amplitude estimation (risk), QAOA for routing and scheduling |
| 7 | **Provenance:** an auditor can see exactly what ran where | Device name, calibration snapshot, transpiled depth, shots and job ID in every audit record |
| 8 | **Quantum-safe accountability:** audit evidence that outlives today's cryptography | Post-quantum signatures (ML-DSA, FIPS 204) for audit chains and evidence packs |

### Target applications

| Sector | Problem | Quantum method |
|---|---|---|
| Finance | Portfolio selection, index tracking, Value-at-Risk | QAOA on QUBOs; amplitude estimation |
| Pharma and materials | Ground-state energies of small molecules, binding screens | VQE |
| Logistics and manufacturing | Vehicle routing, job-shop and shift scheduling | QAOA, max-cut, constrained QUBOs |
| Energy and utilities | Unit commitment, grid partitioning | QUBO formulations with verified bounds |
| Telecom | Frequency and channel assignment | Graph colouring as a QUBO |
| Cybersecurity | Inventory and migration to post-quantum cryptography | Agents that scan, plan and verify the migration (classical) |

### Work packages

- **Q1 · Hardware backends.** `"quantum": {"backend": "ibm:<device>" | "braket:<device>" | "azure:<target>"}` with credentials from environment variables, job submission, queue handling and timeouts.
- **Q2 · QPU budgets and pricing.** A per-backend price table, pre-flight estimates, and run caps, as for model tokens in v0.3.
- **Q3 · `uncertain<T>` quantum results.** Shot counts become samples; the runtime's existing aggregation and confidence guards apply.
- **Q4 · Noise and mitigation.** Simulator noise models, readout mitigation, zero-noise extrapolation and fidelity expectations in evals.
- **Q5 · Bounded verification.** Classical bounds (LP relaxations, heuristics) for problems past the exact-check limit; new guard words `BOUNDED` and `UNCHECKED`.
- **Q6 · Algorithm library.** `quantum.vqe`, `quantum.kernel`, `quantum.amplitude`, plus QUBO builders for routing, colouring and knapsack.
- **Q7 · Provenance and replay.** Hardware job metadata in audit records; replay answers from recorded counts with no QPU time.
- **Q8 · Post-quantum audit signatures.** ML-DSA signing of audit chains; verification in `algo audit verify`.

As in the rest of AlgoLang, the guarantees come from the language and runtime, not from a promise of quantum speed-up. A quantum result is used only when it has been checked, and a person stays accountable for the decision.

---

## 6. Later releases

| Version | Theme | Highlights |
|---|---|---|
| **v0.6** | Interoperability | Publish a flow as an MCP server; argument type checking; token-by-token output streaming; cost and energy dashboards in Studio |
| **v1.0** | Platform | Native runtime; typed agent-to-agent messaging; package registry for domain packs; SSO and role-based access for Studio |

---

## 7. How to contribute

Pick a work package, open an issue titled `v0.4 WPn: …` (or `v0.5 Qn: …` for quantum), and read the [developer guide](DEVELOPER_GUIDE.md). Each package needs grammar changes (if any), compiler checks with error codes, runtime enforcement, tests, documentation, and an example in an enterprise application. Domain experts in law, finance, health and education are especially welcome to review the fairness and risk rules.
