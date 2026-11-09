# Campus microgrid operating code

- Grid import must never exceed 1.75 MW. Any controller must run behind the safety shield, which removes
  actions that would break the cap or the battery's charge limits. A policy trained without the shield is
  never deployed, even if it looks safe in simulation.
- A learned policy replaces the time-of-day rule only if it is safe on 1,000 simulated days, safe on 1,000
  heatwave days, earns more than the rule, and stays close to the exact optimum.
- Deployment starts with a supervised pilot week; operators can always switch back to the rule manually.
  Two different operations engineers approve every deployment.
