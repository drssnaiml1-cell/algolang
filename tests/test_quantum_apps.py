"""AlgoLang v0.3.3: `circuit` blocks, and the quantum applications (routing, Monte Carlo with QAE, PQC readiness)."""
import itertools
import json
import math
from statistics import NormalDist

import pytest

np = pytest.importorskip("numpy")

import algolang as al  # noqa: E402
import algoquantum as aq  # noqa: E402
from algoc import CompileError, compile_source  # noqa: E402

BELL = '''
circuit Bell {
    qubits 2
    h q0
    cx q0, q1
    measure
}
agent Physicist(q: text) -> text {
    goal   "Run the Bell circuit for {q}"
    uses   circuit.Bell
    policy { shots 1000 }
}
flow main(q: text) { emit Physicist(q) }
'''


def codes(src):
    with pytest.raises(CompileError) as e:
        compile_source(src, "t.algo")
    return [d.code for d in e.value.diags]


def circuit(src):
    _, prog = compile_source(src + '\nagent A(x: text) -> text { goal "do {x}" }\nflow main(x: text) { emit A(x) }', "t.algo")
    return prog.circuits


# ───────────────────────────── circuit blocks ─────────────────────────────
def test_circuit_compiles_to_openqasm_and_declares_its_tool():
    _, prog = compile_source(BELL, "t.algo")
    c = prog.circuits["Bell"]
    assert "circuit.Bell" in prog.tools and c.qubits == 2 and c.measure
    q = c.qasm()
    assert q.startswith("OPENQASM 2.0;") and "h q[0];" in q and "cx q[0], q[1];" in q and "measure q -> c;" in q
    r = aq.run_qasm(q, shots=4000)
    assert set(r["counts"]) == {"00", "11"}


def test_one_qubit_gates_spread_over_several_qubits_and_angles_parse():
    c = circuit("circuit C { qubits 3  h q0, q1, q2  rz(pi/4) q1  u3(pi/2, 0, -pi) q2  cp(0.5*pi) q0, q2 }")["C"]
    assert [op[0] for op in c.ops] == ["h", "h", "h", "rz", "u3", "cp"]
    assert "u3(pi/2, 0, -pi) q[2];" in c.qasm()


def test_circuit_errors_are_e124():
    base = '\nagent A(x: text) -> text { goal "do {x}" }\nflow main(x: text) { emit A(x) }'
    for bad in ["circuit C { h q0 }",                         # no qubit count
                "circuit C { qubits 2  hh q0 }",             # unknown gate
                "circuit C { qubits 2  cx q0, q0 }",         # same qubit twice
                "circuit C { qubits 2  rx q0 }",             # missing angle
                "circuit C { qubits 2  h q2 }",              # qubit out of range
                "circuit C { qubits 2  cx q0 }",             # wrong arity
                "circuit C { qubits 99  h q0 }",             # above the simulator limit
                "circuit C { qubits 2 }",                    # no gates
                "circuit C { qubits 1  h q0 }\ncircuit C { qubits 1  x q0 }"]:
        assert "E124" in codes(bad + base), bad


def test_agents_run_circuits_under_their_shot_policy(tmp_path):
    prog = al.compile(BELL, "bell", base_dir=tmp_path)
    res = prog.run(q="entanglement", audit_dir=str(tmp_path))
    assert res.ok
    (call,) = res.calls
    assert call["tool_calls"][0]["tool"] == "circuit.Bell"
    assert "from 1000 shots on 2 qubits" in str(res.values[0])


def test_unknown_circuit_tool_is_still_e104():
    src = BELL.replace("uses   circuit.Bell", "uses   circuit.Nope")
    assert "E104" in codes(src)


def test_exported_circuit_matches_qiskit_when_installed():
    qiskit = pytest.importorskip("qiskit")
    from qiskit.quantum_info import Statevector
    c = circuit("circuit G { qubits 3  h q0  cx q0, q1  ry(pi/3) q2  cz q1, q2  t q0  swap q0, q2 }")["G"]
    body = c.qasm().replace("measure q -> c;\n", "")
    ref = Statevector.from_instruction(qiskit.QuantumCircuit.from_qasm_str(body)).data
    sv = aq.StateVector(3)
    for g, qs, angles, _ in c.ops:
        sv.gate(g, qs, tuple(aq._num(a) for a in angles))
    assert np.allclose(sv.psi, ref, atol=1e-9)


def test_grover_circuit_in_the_lab_finds_the_marked_item():
    src = open(__import__("conftest").ROOT / "enterprise-apps/quantum-optimization-lab/programs/circuit_lab.algo").read()
    _, prog = compile_source(src, "circuit_lab.algo")
    r = aq.run_qasm(prog.circuits["Grover2"].qasm(), shots=500)
    assert r["counts"] == {"11": 500}


# ───────────────────────────── logistics routing ─────────────────────────────
def brute(Q, offset):
    n = len(Q)
    best = min(itertools.product([0, 1], repeat=n), key=lambda x: np.array(x) @ Q @ np.array(x))
    return np.array(best) @ Q @ np.array(best) + offset, best


def test_routes_qubo_minimum_is_the_cheapest_feasible_plan():
    options = [("A", "r1", 10), ("A", "r2", 7), ("B", "r1", 5), ("B", "r2", 9), ("C", "r1", 4), ("C", "r2", 3)]
    clashes = [(1, 2, 20)]                                         # A→r2 with B→r1 costs 20 more
    Q, off = aq.routes_qubo(options, clashes)
    cost, x = brute(Q, off)
    plans = []
    for pick in itertools.product([0, 1], repeat=3):
        idx = [2 * s + p for s, p in enumerate(pick)]
        plans.append(sum(options[i][2] for i in idx) + (20 if 1 in idx and 2 in idx else 0))
    assert math.isclose(cost, min(plans)) and sum(x) == 3


def test_routes_tool_on_the_supply_chain_file(monkeypatch):
    import conftest
    import algoruntime
    monkeypatch.chdir(conftest.ROOT / "enterprise-apps" / "supply-chain-control-tower")
    monkeypatch.setattr(algoruntime, "_CONFIG", None)
    out = aq.tool_routes("Choose routes for data/route_options.csv, clash cost 60000 for shared lanes")
    assert out.startswith("VERIFIED") and "FEASIBLE: every shipment has exactly one route" in out
    for ship in ("SHP-101", "SHP-102", "SHP-103", "SHP-104"):
        assert f"{ship} via" in out


def test_routes_tool_text_form_and_bad_input():
    out = aq.tool_routes("S1: R1=120, R2=95; S2: R1=80, R2=110; clash S1.R2+S2.R1=60")
    assert "plan: S1 via R1; S2 via R1" in out                     # 200 beats 95+80+60 and 95+110
    assert aq.tool_routes("nothing here").startswith("no route options")


def test_data_files_cannot_escape_the_folder(monkeypatch, tmp_path):
    import algoruntime
    (tmp_path / "data").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(algoruntime, "_CONFIG", None)
    assert aq._guard(aq.tool_routes)("routes in ../../etc/passwd.csv").startswith("INVALID: refused")


# ───────────────────────────── Monte Carlo + amplitude estimation ─────────────────────────────
def test_qae_estimate_is_within_its_error_bound():
    for p in (0.01, 0.05, 0.3):
        est, calls, bound = aq.qae_estimate(p, 8, 2000, seed=1)
        assert calls == 255 and abs(est - p) <= bound + 1e-12


def test_scenarios_var_matches_the_normal_formula():
    pos = [{"name": "A", "value": 1e6, "mu": 0.0, "sigma": 0.01}, {"name": "B", "value": 1e6, "mu": 0.0, "sigma": 0.02}]
    rho = 0.5
    out = aq.tool_scenarios(json.dumps({"positions": pos}) + " rho 0.5 scenarios 100000 confidence 0.99")
    var = float(out.splitlines()[0].split("VaR ")[1].split()[0].replace(",", ""))
    sig = math.sqrt(1e4 ** 2 + 2e4 ** 2 + 2 * rho * 1e4 * 2e4)     # one-factor model: corr(i, j) = rho
    assert abs(var - NormalDist().inv_cdf(0.99) * sig) / var < 0.03
    assert "QAE check" in out and "fault-tolerant hardware" in out


def test_scenarios_limit_guard_words():
    pos = json.dumps({"positions": [{"name": "A", "value": 1e6, "mu": 0, "sigma": 0.01}]})
    assert aq.tool_scenarios(pos + " limit 1000").startswith("BREACH")
    assert aq.tool_scenarios(pos + " limit 900000").startswith("WITHIN LIMIT")


# ───────────────────────────── quantum-safe readiness ─────────────────────────────
@pytest.mark.parametrize("alg,purpose,status", [
    ("RSA-2048", "key exchange", "QUANTUM-BROKEN"), ("ECDSA-P256", "code signing", "QUANTUM-BROKEN"),
    ("Ed25519", "", "QUANTUM-BROKEN"), ("AES-128-GCM", "", "QUANTUM-WEAKENED"), ("AES-256-GCM", "", "QUANTUM-SAFE"),
    ("SHA-1", "", "BROKEN-NOW"), ("ML-KEM-768", "", "QUANTUM-SAFE"), ("X25519MLKEM768", "", "QUANTUM-SAFE"),
    ("SHA-384", "", "QUANTUM-SAFE"), ("3DES", "", "QUANTUM-WEAKENED"), ("Blowfish", "", "UNKNOWN")])
def test_crypto_classification(alg, purpose, status):
    assert aq.classify_crypto(alg, None, purpose)[0] == status


def test_signatures_and_key_exchange_get_the_right_standard():
    assert "FIPS 204" in aq.classify_crypto("ECDSA-P256", None, "code signing")[2]
    assert "FIPS 203" in aq.classify_crypto("ECDHE-P256", None, "key exchange")[2]


def test_pqc_scan_uses_moscas_rule(monkeypatch):
    import conftest
    import algoruntime
    monkeypatch.chdir(conftest.ROOT / "enterprise-apps" / "soc-incident-command")
    monkeypatch.setattr(algoruntime, "_CONFIG", None)
    out = aq.tool_pqc("scan data/crypto_inventory.csv")
    lines = out.splitlines()
    assert lines[0].startswith("URGENT: 8 systems")
    urgent = [ln for ln in lines if ln.startswith("- URGENT")]
    # 12-year VPN and 15-year signing keys are urgent (+3 years ≥ 10); the 1-year SSO tokens and 2-year TLS are not
    assert any("Core banking VPN" in ln for ln in urgent) and any("Payments HSM" in ln for ln in urgent)
    assert not any("Employee SSO" in ln or "Customer portal" in ln for ln in urgent)
    assert any("Legacy SFTP" in ln and "BROKEN-NOW" in ln for ln in urgent)
