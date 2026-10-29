# Changelog

All notable changes to AlgoLang are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/) (during 0.x, minor versions may change the language).

## [Unreleased]

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
