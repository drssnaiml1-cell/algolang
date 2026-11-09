# SOC Incident Command

**Sector:** Cybersecurity & IT operations · **Organisation:** Helix Cloud Services (an example organisation; all data is synthetic)

**The problem.** Security operations centres drown in alerts. Analysts need assets, owners and threat intelligence in seconds, a severity call, and, for serious incidents, an IT runbook straight away.

**What this AlgoLang application does**

- Enriches alerts with the CMDB (asset tier, owner, dependencies) and checks every IP and domain against threat intel, in parallel
- Splits the alert batch, analyses each part in parallel and scores severity
- Severe → hands the incident to IT operations for classification, diagnosis, priority and a first-response runbook
- A phishing desk checks forwarded emails against the blocklist and advises staff and the SOC


## How it works: live figures
Each figure is drawn from the program itself by `tools/make_figures.py`, so it always matches the code. Moving dots show data flowing between agents; dashed blue lines are decisions; gold badges mark human gates and blue badges mark `uncertain<T>` agents that are sampled several times.

**Helix SOC** · [`programs/alert_to_incident.algo`](programs/alert_to_incident.algo)

<p align="center"><img src="../../docs/images/apps/soc-incident-command--alert_to_incident.svg" alt="Helix SOC: alerts to an incident: batch & analyse, enrich (CMDB, IOC), severity, IT incident runbook." width="100%"></p>

**Helix phishing desk** · [`programs/phishing_desk.algo`](programs/phishing_desk.algo)

<p align="center"><img src="../../docs/images/apps/soc-incident-command--phishing_desk.svg" alt="Helix phishing desk: staff forward a suspicious email, the desk checks indicators and advises." width="100%"></p>

**Quantum-safe readiness** · [`programs/pqc_readiness.algo`](programs/pqc_readiness.algo)

<p align="center"><img src="../../docs/images/apps/soc-incident-command--pqc_readiness.svg" alt="Quantum-safe readiness: which cryptography a large quantum computer could break, and what to move to." width="100%"></p>

## How the agents work together (`alert_to_incident.algo`)

```mermaid
flowchart TD
    n1(["alerts"])
    n2["Enrich"]
    n3["ThreatCheck"]
    n4["soc.Batcher"]
    n5["soc.Analyst × each"]
    n6["soc.Severity"]
    n7["soc.Incident"]
    n8{"if severity > 0.7"}
    n9["ops.Classifier"]
    n10["ops.Diagnosis"]
    n11["ops.Priority"]
    n12["ops.Runbook"]
    n13(["emit"])
    n14(["emit"])
    n1 --> n2
    n1 --> n3
    n1 --> n4
    n4 --> n5
    n1 --> n5
    n5 --> n6
    n5 --> n7
    n6 --> n7
    n6 --> n8
    n7 --> n9
    n8 -.-> n9
    n9 --> n10
    n8 -.-> n10
    n10 --> n11
    n8 -.-> n11
    n10 --> n12
    n11 --> n12
    n8 -.-> n12
    n2 --> n13
    n3 --> n13
    n6 --> n13
    n7 --> n13
    n12 --> n13
    n2 --> n14
    n3 --> n14
    n6 --> n14
    n7 --> n14
    classDef agent fill:#0b1f3a,color:#fff,stroke:#0b1f3a
    classDef par fill:#0b1f3a,color:#fff,stroke:#c9a227,stroke-width:3px
    classDef io fill:#f4ecd2,color:#0b1f3a,stroke:#c9a227
    class n4,n6,n7 agent
    class n9,n10,n11,n12 agent
    class n2,n3,n5 par
    class n1 io
    class n13,n14 io
```

## Programs

| Program | Input | Flow |
|---|---|---|
| `programs/alert_to_incident.algo` | `alerts` | Enrich ∥ threat intel → batch → analysts (parallel) → severity → incident → runbook |
| `programs/phishing_desk.algo` | `email` | Link check → indicators → assessment → likelihood → advice |
| `programs/pqc_readiness.algo` *(quantum-safe, v0.3.3)* | `scope` | `pqc.scan` over `data/crypto_inventory.csv` (Shor / Grover rules, Mosca's harvest-now-decrypt-later test) → BROKEN-NOW? incident → migration plan to ML-KEM / ML-DSA / SLH-DSA → URGENT? CISO approval |

## Company tools (`plugins/`)

Agents can call a tool only if the program declares it, the agent lists it under `uses`, and `algo.config.json` allows it.

| Tool | What it does |
|---|---|
| `cmdb.lookup` | Configuration management database (data/cmdb.csv) |
| `ioc.check` | Indicator-of-compromise blocklist (data/iocs.csv) |
| `kb.search` | Runbooks (kb/runbooks.md) |

## Governance (`algo.config.json`)

| Rule | Setting |
|---|---|
| Forbidden inputs (checked when the program compiles and again when it runs) | gender, caste, religion |
| Human review below confidence | 0.8 (each agent's own threshold applies if it is stricter) |
| Max token budget per agent | 8,000 |
| Max tokens per run | 100,000 |
| Allowed tools | `kb.search`, `cmdb.lookup`, `ioc.check` |
| Audit | SHA-256 hash-chained log in `runs/`, checked with `algo audit verify` |

## Real-time (AlgoPulse™)

`programs/alert_to_incident.algo` ends with a `stream` block: SIEM alerts on `soc.alerts` → incident decision → `soc.incidents` / `soc.dlq`. Every event runs the flow once under the same governance, on AlgoPulse, AlgoLang's built-in event engine.

```bash
algo stream programs/alert_to_incident.algo --input data/alert_events.jsonl             # offline, from a file
algo stream programs/alert_to_incident.algo --pulse --produce data/alert_events.jsonl   # publish to the local bus (pulse/soc/)
algo stream programs/alert_to_incident.algo --pulse                        # process; re-runs resume where they stopped
algo pulse topics --bus soc
```

The sample file includes a malformed event (and, for the trading desk, a re-delivered duplicate) so you can see dead-letter routing and de-duplication at work.


## Run it

Run these from this folder, so `algo.config.json` and the plugins load.

```bash
algo run programs/alert_to_incident.algo --arg "alerts=auth-api: 4,200 failed logins in 5 minutes from 185.220.101.7; payments-gw latency up 300%"
algo batch programs/alert_to_incident.algo --input data/alerts.csv --workers 8      # every row, in parallel
algo review                     # approve or reject what was sent to a human
algo audit verify               # prove the audit log was not edited
algo report                     # usage, escalations and confidence per program
algo dev test tests             # 3 behaviour tests (offline, deterministic)
algo studio                     # open it in the graphical Studio
```

Add `--live` and set `ANTHROPIC_API_KEY` to use real Claude models instead of the offline agents.
