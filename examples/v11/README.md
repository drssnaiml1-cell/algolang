# AlgoLang 1.1 examples: accountable decisions

`claim_contracts.algo` shows all three v1.1 features on one motor-insurance claim.

```bash
# 1. Agent contracts: every answer is checked; a broken contract → one more try → a person
algo run examples/v11/claim_contracts.algo --arg "note=Policy MTR-1182: rear bumper damage, estimate 18500" --arg cover=200000
algo run examples/v11/claim_contracts.algo --arg "note=Policy MTR-1182: rear bumper damage, estimate 18500" --arg cover=10

# 2. What-if audit: record a decision, then ask what would have changed
algo run examples/v11/claim_contracts.algo --arg "note=..." --arg cover=200000 --trace
algo whatif runs/traces/claim_contracts-XXXXXXXX.trace.json --set cover=5000
algo whatif runs/traces/claim_contracts-XXXXXXXX.trace.json --set cover=5000 --expect same   # exit 1: it changed

# 3. Governance diff: did an edit weaken a safeguard?
algo diff git:main:examples/v11/claim_contracts.algo examples/v11/claim_contracts.algo
algo diff old.algo new.algo --markdown          # for a pull-request comment
```

Offline runs use the deterministic mock model, so the numbers are simulated; add `--live` (and an API key) for real models.
