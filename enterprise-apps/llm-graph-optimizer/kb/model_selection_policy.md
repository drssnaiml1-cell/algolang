# Model selection policy (example organisation)

Small language models (SLMs) run on our own GPUs. They cost no API fees, keep data inside the network
and use far less energy, but they are weaker at multi-step reasoning.

1. Every agent must meet the quality floor for its task class: extraction 0.80, classification 0.80,
   writing 0.75, review 0.75, reasoning 0.85. Agents that make or recommend a decision need +0.05.
2. A request is answered by a small model first. If its answer is not confident enough, or the request is
   complex, a large model answers instead (the cascade).
3. Changes to the models used in production need two approvals: an ML engineer and the system owner.
4. Benchmark scores in data/model_catalog.csv are illustrative. Replace them with your own eval results
   (algo eval --live) before relying on the optimiser.
