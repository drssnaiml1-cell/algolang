# AlgoLang 1.2 examples: collective and adversarial assurance

`credit_consensus.algo` shows all three v1.2 features on one small-business loan pre-screen.

```bash
# 1. Consensus: three independent agents; the score stands only if 2 of 3 agree within 0.15
algo run examples/v12/credit_consensus.algo --arg "app=APP-7741: textile trader, 6 years trading, DSCR 1.8"
algo run examples/v12/credit_consensus.algo --engine vm --arg "app=..."        # identical on the AlgoVM

# 2. Red team: attack the program offline and see which safeguards hold
algo redteam examples/v12/credit_consensus.algo
algo redteam examples/v12/credit_consensus.algo --fail-on medium --markdown redteam.md   # for CI

# 3. Decision notice: a plain-language explanation for the applicant, from the trace and the audit log
algo run examples/v12/credit_consensus.algo --arg "app=..." --trace
algo explain runs/traces/credit_consensus-XXXXXXXX.trace.json --contact cto@algoprofessor.com --html notice.html
algo explain examples/v12/credit_consensus.algo --arg "app=..." --md notice.md    # run and explain in one step
```

Offline runs use the deterministic mock model, so the numbers are simulated; add `--live` (and an API key) for real models.
