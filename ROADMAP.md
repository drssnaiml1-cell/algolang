# AlgoLang roadmap

**Current release: v0.3.0** · **Next: v0.4 — Trustworthy AI**

AlgoProfessor AI R&D Solutions, Hyderabad. Designed by Dr. S. Satyanarayana. [www.algoprofessor.com](https://www.algoprofessor.com)

---

## 1. Objective of v0.4

**Make trustworthiness something an AlgoLang program can prove, not just claim.**

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

- New errors: **E122** (high-risk program without human oversight), **E123** (without fairness evals), **E124** (without explain), **E125** (forbidden attribute reachable through a tool).
- **Done when:** all nine enterprise applications declare a risk level and compile under it.

### WP10 · Assurance reporting

```bash
algo trust report enterprise-apps/bank-credit-onboarding
```

- A scorecard per program: each trustworthy-AI property, the evidence for it (tests, logs, cards) and gaps to fix, mapped to NIST AI RMF functions and EU AI Act duties.
- Available as HTML, JSON and in Studio.
- **Done when:** an auditor can trace every claim in the report to a file in the evidence pack.

---

## 4. Already in place (v0.1 – v0.3)

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

---

## 5. Later releases

| Version | Theme | Highlights |
|---|---|---|
| **v0.5** | Interoperability | Publish a flow as an MCP server; argument type checking; streaming outputs; cost and energy dashboards in Studio |
| **v1.0** | Platform | Native runtime; typed agent-to-agent messaging; package registry for domain packs; SSO and role-based access for Studio |

---

## 6. How to contribute

Pick a work package, open an issue titled `v0.4 WPn: …`, and read the [developer guide](DEVELOPER_GUIDE.md). Each package needs grammar changes (if any), compiler checks with error codes, runtime enforcement, tests, documentation, and an example in an enterprise application. Domain experts in law, finance, health and education are especially welcome to review the fairness and risk rules.
