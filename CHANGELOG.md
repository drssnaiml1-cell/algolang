# Changelog

All notable changes to AlgoLang are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/) (during 0.x, minor versions may change the language).

## [Unreleased]

## [0.3.1] — 2026-11-08

### Added
- **Real-time streams.** A new `stream name on flow { … }` block binds a flow to a Kafka topic: `from kafka "cluster" topic "t" group "g"`, `map input = event.path`, `key event.id`, `to topic`, `escalate to topic`, `dead letter topic` and `max in flight N`. Every event runs the flow once, under the same policies, budgets, human gate and audit log as any other run.
- **`algo stream`** runs a stream offline (`--input events.jsonl`) or on Apache Kafka (`--kafka`), publishes sample events (`--produce`), stops after `--max` events or `--idle` seconds, and writes per-stream metrics: events/s, latency p50/p95, ok / escalated / dead-letter counts, tokens, cost and energy.
- **Delivery and routing.** At-least-once delivery: offsets are committed only after results are written and flushed. Keys already seen in the session are skipped. Each result goes to exactly one topic: ok → `to`, escalated → `escalate to`, invalid, blocked or failed → `dead letter`. Undeclared routes fall back to `to`.
- **Kafka configuration** in `algo.config.json` (`"kafka": {"cluster": {"bootstrap_servers": …}}`), with SASL/SSL settings passed to the client and secrets read from environment variables (`…_env`). `ALGO_KAFKA_BOOTSTRAP` overrides the address.
- **E122**: stream errors (unknown flow or input, a mapping that does not read from `event`, a result topic equal to the source topic, `max in flight` outside 1–256).
- **`deploy/kafka/`**: Docker Compose for ZooKeeper + Kafka with the topics created, plus a KRaft variant for Kafka 4.x.
- **Streams in two enterprise apps**: Algo Trading Desk (`orders.intent` → pre-trade risk gate) and SOC Incident Command (`soc.alerts` → incidents), with sample event files. `enterprise-apps/run_all.py --batch` replays them offline.
- **CI**: a new job tests every push against real ZooKeeper and Kafka service containers. `requirements-stream.txt` and the `algolang[stream]` extra install the `kafka-python` client.
- **README**: an animated hero banner, a real-time pipeline diagram and Mermaid diagrams for the architecture, the life of an agent call and the handling of one event.
- Editor support: `stream` and `kafka` keywords in the VS Code grammar, plus hover help and a `stream` snippet in the language server.

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
