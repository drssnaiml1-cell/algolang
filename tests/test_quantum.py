"""AlgoLang v0.3.2: quantum tools (state-vector simulator, OpenQASM, QAOA with exact verification, Grover, random)."""
import math

import pytest

np = pytest.importorskip("numpy")

import algolang as al  # noqa: E402
import algoquantum as aq  # noqa: E402
import algoruntime as rt  # noqa: E402
from algoc import CompileError, compile_source  # noqa: E402

BELL = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q -> c;\n'


def codes(src):
    with pytest.raises(CompileError) as e:
        compile_source(src, "t.algo")
    return [d.code for d in e.value.diags]


# ───────────────────────────── simulator ─────────────────────────────
def test_bell_and_ghz_states():
    r = aq.run_qasm(BELL, shots=4000)
    assert set(r["counts"]) == {"00", "11"} and abs(r["counts"]["00"] - 2000) < 200
    ghz = 'OPENQASM 2.0; qreg q[3]; creg c[3]; h q[0]; cx q[0],q[1]; cx q[1],q[2]; measure q -> c;'
    assert set(aq.run_qasm(ghz)["counts"]) == {"000", "111"}


def test_bit_order_matches_qiskit_convention():
    # x on qubit 0 only: Qiskit prints the highest classical bit first → "001"
    r = aq.run_qasm('OPENQASM 2.0; qreg q[3]; creg c[3]; x q[0]; measure q -> c;', shots=10)
    assert r["counts"] == {"001": 10}


def test_rotations_interference_and_unitarity():
    sv = aq.StateVector(1)
    sv.gate("h", [0])
    sv.gate("h", [0])                                   # H·H = I
    assert np.allclose(sv.probabilities(), [1, 0])
    sv = aq.StateVector(1)
    sv.gate("ry", [0], (math.pi / 3,))
    assert np.isclose(sv.probabilities()[1], math.sin(math.pi / 6) ** 2)
    sv = aq.StateVector(3)
    for g, q, p in [("h", [0], ()), ("cx", [0, 2], ()), ("u3", [1], (0.3, 1.1, -0.4)), ("ccx", [0, 1, 2], ()),
                    ("swap", [1, 2], ()), ("crz", [2, 0], (0.7,))]:
        sv.gate(g, q, p)
    assert np.isclose(np.linalg.norm(sv.psi), 1.0)


def test_qasm_errors_are_reported_not_raised_by_the_tool():
    assert rt.run_tool("quantum.run", "no program here").startswith("INVALID")
    assert "unsupported" in rt.run_tool("quantum.run", "OPENQASM 2.0; qreg q[1]; foo q[0];")
    assert "out of range" in rt.run_tool("quantum.run", "OPENQASM 2.0; qreg q[1]; h q[3];")


def test_matches_qiskit_when_installed():
    qiskit = pytest.importorskip("qiskit")
    from qiskit.quantum_info import Statevector
    src = ('OPENQASM 2.0; include "qelib1.inc"; qreg q[3]; h q[0]; cx q[0],q[2]; rz(0.4) q[2]; '
           'cp(1.2) q[2],q[1]; u3(0.3,0.9,-1.4) q[1]; ccx q[2],q[1],q[0]; swap q[0],q[1]; sdg q[2];')
    ref = Statevector.from_instruction(qiskit.QuantumCircuit.from_qasm_str(src)).data
    _, _, ops, _ = aq.parse_qasm(src)
    sv = aq.StateVector(3)
    for g, q, p in ops:
        sv.gate(g, q, p)
    assert abs(abs(np.vdot(ref, sv.psi)) - 1) < 1e-12


# ───────────────────────────── algorithms ─────────────────────────────
def test_maxcut_is_verified_against_the_exact_optimum():
    out = rt.run_tool("quantum.maxcut", "A-B:3, B-C:1, C-D:2, A-D:1, B-D:2")
    assert out.startswith("VERIFIED") and "cut weight 7" in out


def test_qubo_from_linear_and_quadratic_terms():
    out = rt.run_tool("quantum.qubo", '{"linear": {"a": -3, "b": -1}, "quadratic": {"a,b": 5}}')
    assert out.startswith("VERIFIED") and "selected: a " in out


def test_gap_is_reported_when_the_measured_answer_is_not_optimal():
    Q, off = aq.portfolio_qubo([0.1, 0.2, 0.15, 0.12, 0.3, 0.05], [0.04, 0.09, 0.05, 0.03, 0.2, 0.01], 3)
    r = aq.solve_qubo(Q, off, shots=1, seed=3, layers=1)      # one measurement: usually not the optimum
    assert r["verified"] == (r["cost"] == r["optimum_cost"])
    text = aq.format_solution(r)
    assert text.startswith("VERIFIED" if r["verified"] else "GAP")
    assert 0 <= r["p_optimal"] <= 1 and r["approx_ratio"] <= 1.0001


def test_portfolio_qubo_enforces_the_cardinality():
    Q, off = aq.portfolio_qubo([0.1, 0.2, 0.15, 0.12], [0.04, 0.09, 0.05, 0.03], 2)
    costs, bits = aq.qubo_costs(Q, off)
    assert bits[int(np.argmin(costs))].sum() == 2


def test_grover_finds_the_marked_item():
    out = rt.run_tool("quantum.grover", "search 64 items for 37")
    assert out.startswith("FOUND: item 37") and "6 qubits" in out


def test_random_sampling_is_reproducible_and_in_range():
    a = rt.run_tool("quantum.random", "pick 8 of 240 vouchers")
    assert a == rt.run_tool("quantum.random", "pick 8 of 240 vouchers")
    nums = [int(x) for x in a.split(":")[1].split("(")[0].split(",")]
    assert len(set(nums)) == 8 and all(1 <= n <= 240 for n in nums)


def test_results_are_deterministic_for_audit_and_replay():
    q = "A-B:2, B-C:2, C-D:2, D-A:2, A-C:1"
    assert rt.run_tool("quantum.maxcut", q) == rt.run_tool("quantum.maxcut", q)


# ───────────────────────────── governance ─────────────────────────────
def test_policy_limits_reach_the_tool_and_block_large_circuits():
    tok = aq.POLICY.set({"max_qubits": 3, "shots": 100})
    try:
        assert rt.run_tool("quantum.grover", "n=4 marked 2").startswith("BLOCKED: needs 4 qubits")
        assert "100 shots" in rt.run_tool("quantum.run", BELL)
    finally:
        aq.POLICY.reset(tok)


def test_agent_policy_is_applied_inside_a_flow(tmp_path):
    src = ('tool quantum.grover\n'
           'agent Search(q: text) -> text { goal "n=5 marked 3 {q}"  uses quantum.grover  policy { max qubits 4 } }\n'
           'agent Fallback(q: text) -> text { goal "classical search for {q}" }\n'
           'flow main(q: text) { r = Search(q)\n if r contains "BLOCKED" { emit r, Fallback(q) } else { emit r } }')
    res = al.compile(src, "g", base_dir=tmp_path).run(audit_dir=str(tmp_path), q="x")
    assert [c["agent"] for c in res.calls] == ["Search", "Fallback"]
    assert "BLOCKED: needs 5 qubits" in str(rt.Runtime.value(res.values[0]))


def test_compile_checks_for_quantum_policies():
    base = 'tool quantum.run\nflow main(x: text) { emit A(x) }\n'
    assert "E123" in codes(base + 'agent A(x: text) -> text { goal "run {x}" uses quantum.run policy { shots 0 } }')
    assert "E123" in codes(base + 'agent A(x: text) -> text { goal "run {x}" uses quantum.run policy { max qubits 5000 } }')
    compile_source(base + 'agent A(x: text) -> text { goal "run {x}" uses quantum.run policy { shots 4096 max qubits 8 } }',
                   "t.algo")


def test_max_qubits_merge_keeps_the_stricter_limit():
    from algoc import merge_policy
    assert merge_policy({"max_qubits": 10}, {"max_qubits": 16})["max_qubits"] == 10
    assert merge_policy({"max_qubits": 10}, {"max_qubits": 6})["max_qubits"] == 6
