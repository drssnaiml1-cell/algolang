"""AlgoQ Quantum AI Lab™ company tool: the lab's benchmark catalogue.

    lab.catalog  the benchmark molecules and spin models the lab screens, with the exact reference energies the
                 VQE results are checked against (computed by exact diagonalisation of the same Hamiltonians)
"""
from __future__ import annotations

from algoruntime import register_tool

BENCHMARKS = [
    ("H2", "H2 at 0.735 Å (STO-3G, 2 qubits)", "chemical accuracy 1.6 mHa"),
    ("ising n=6 h=1.0", "transverse-field Ising chain, 6 spins (critical point)", "1% of the exact energy"),
    ("heisenberg n=4", "Heisenberg chain, 4 spins", "1% of the exact energy"),
]


@register_tool("lab.catalog", "The lab's benchmark molecules and spin models, and the accuracy each must reach")
def lab_catalog(query: str) -> str:
    try:
        import numpy as np

        import algoqpu as Q
    except ImportError:
        return "CATALOGUE unavailable: the quantum tools need NumPy"
    rows = []
    for key, name, target in BENCHMARKS:
        _n, terms, nuclear, _mol = Q.parse_hamiltonian(key)
        exact = float(np.linalg.eigvalsh(Q.h_matrix(terms, np))[0]) + nuclear
        rows.append(f"{name}: exact ground energy {exact:.6f} · target {target}")
    return f"CATALOGUE {len(rows)} benchmarks\n" + "\n".join(rows)
