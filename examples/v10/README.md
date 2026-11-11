# AlgoLang v1.0 examples

**Typed messages.** `claims_typed.algo` declares `type Claim { … }` and `type Decision { … }`. Agents return them,
flows read their fields (`claim.amount < 50000`), and the compiler checks every field and argument (E131, E132).
At run time each model answer is validated against its type, so a missing or mistyped field fails loudly instead of
flowing on as text.

```bash
algo run examples/v10/claims_typed.algo --arg "note=Rear-end collision, policy MOT-77812, INR 38,000"
```

**AlgoIR and the AlgoVM.** Build the program once into a portable, signed artifact, then run it with no compiler and
no generated code:

```bash
algo keys init                                               # once: the organisation's signing key
algo build examples/v10/claims_typed.algo --ir --sign        # → build/claims_typed.algoir.json
algo run examples/v10/build/claims_typed.algoir.json --arg "note=…"
```

With `"runtime": {"require_signed_ir": true}` in algo.config.json the AlgoVM refuses anything unsigned or changed.

**Packages.** Share agents as versioned, signed packages:

```bash
algo pkg init examples/v10 --name claims-desk --version 1.0.0
algo pkg build examples/v10 && algo pkg publish dist/claims-desk-1.0.0.algopkg --registry ./registry
algo pkg install insurance@^1.0                              # from the public registry
```

```algo
use "pkg:insurance/claims_triage.algo" as triage            // locked in algo.lock; changed files are refused (E133)
```

**Studio sign-in.** Set `"studio": {"auth": {"mode": "oidc", …}, "roles": {…}}` and start `algo studio --host 0.0.0.0`:
people sign in with the organisation's identity provider and get the viewer, reviewer, author or admin role.
