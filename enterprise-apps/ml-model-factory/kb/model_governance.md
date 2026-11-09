# Model governance standard

A model may be deployed only when:
- it was compared with a simple baseline on the same cross-validation folds, and its lift is reported honestly;
- its calibration error is at most 0.05, because retention budgets are set from predicted probabilities;
- no feature leaks the label, and production data is stable (population stability index at most 0.2 per feature);
- a model risk officer scores it fit, and two different MLOps engineers approve the deployment plan.

New models run in shadow for one week before they affect any customer. A drifted production week stops
deployment and starts a retraining review. Simpler models are preferred when they perform as well.
