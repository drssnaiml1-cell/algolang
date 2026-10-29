# AlgoLang enterprise applications

Eight complete, governed multi-agent applications, one per industry. Each is a real AlgoLang project with:
- organisation policy;
- company tools over its own data;
- a knowledge base;
- programs that combine the domain packs with custom agents;
- sample batch data;
- behaviour tests.

They all run offline as they are, and with real Claude models when you add `--live`.

| Application | Sector | Programs | Company tools | Tests |
|---|---|---|---|---|
| [Claims Operations Center](claims-ops-center/) | Insurance | 2 | `policydb.lookup`, `payout.estimate` | 3 |
| [Hospital Care Coordination](hospital-care-coordination/) | Healthcare | 2 | `beds.availability` | 3 |
| [Bank Credit & Onboarding](bank-credit-onboarding/) | Banking | 2 | `bureau.score`, `dti.calc`, `sanctions.screen` | 4 |
| [University Admissions & OBE](university-admissions-obe/) | Higher education | 2 | `seats.lookup` | 2 |
| [SOC Incident Command](soc-incident-command/) | Cybersecurity & IT operations | 2 | `cmdb.lookup`, `ioc.check` | 3 |
| [Supply Chain Control Tower](supply-chain-control-tower/) | Logistics & retail | 1 | `shipment.track`, `inventory.levels` | 1 |
| [Citizen Services Desk](citizen-services-desk/) | Government & public services | 2 | `ward.directory` | 2 |
| [Legal Contract Desk](legal-contract-desk/) | Legal & compliance | 2 | `clause.library` | 2 |

**8 applications · 15 programs · 20 behaviour tests**, all run in CI on every push.

## Run every application

```bash
python enterprise-apps/run_all.py            # behaviour tests for all eight apps
python enterprise-apps/run_all.py --batch    # also batch-process each app's sample CSV and verify the audit chain
```

## Layout of every application

```
<app>/
  algo.config.json     organisation policy: forbidden inputs, human-review threshold, budgets, allowed tools
  plugins/*.py         company tools (Python functions registered with @register_tool)
  programs/*.algo      AlgoLang programs: domain packs (use pack …) plus the organisation's own agents
  kb/*.md              knowledge base searched by kb.search
  data/                CSVs and files the tools read, plus sample batch inputs
  tests/*.algotest.json  behaviour tests: path taken, agents, tools, key output, token budget
  README.md            the problem, the flow diagram, governance and run commands
```

## What each application demonstrates

- **Modules and domain packs:** `use pack insurance.fraud_screening as fraud`, then `fraud.FraudPanel(views)`.
- **Parallel agents:** `par { … }` committees and `par for` fan-out over lists.
- **Branching on confidence:** `if risk > 0.85 { … } else { … }`.
- **Company tools:** an agent gets a tool only if it declares it and the org allows it (`E115` otherwise).
- **Fairness:** protected attributes are forbidden inputs (`E108` at compile time, blocked at run time).
- **Human-in-the-loop, a hash-chained audit log, batch processing and caching**, all switched on by `algo.config.json`.

All organisations, people, policies and records here are fictional examples.
