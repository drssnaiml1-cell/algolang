# Quantum computing policy (example research organisation, synthetic)

- A quantum result is used only when it is checked: VERIFIED against the exact optimum, or BOUNDED within 5% of a proven lower bound. UNCHECKED or GAP results go back to the classical optimum.
- Chemistry results must reach chemical accuracy (1.6 mHa) against exact diagonalisation for benchmark molecules before a method is used on new molecules.
- Every run on quantum hardware is budgeted: 600 QPU seconds and USD 200 per run, and each agent has its own `budget qpu`.
- Noisy devices: report the fidelity, apply readout-error mitigation and zero-noise extrapolation, and state the remaining error.
- Quantum kernels are deployed only when they beat a tuned classical kernel in cross-validation.
- Project selections above INR 10 crore need two approvals from the investment committee.
- Audit logs of quantum runs record backend, device, calibration, shots, job id, QPU time and cost.
