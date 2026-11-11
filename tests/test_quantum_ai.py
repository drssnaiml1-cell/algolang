"""AlgoLang v0.6 Quantum AI: backends, QPU budgets, uncertain quantum results, noise and mitigation, bounded
verification, VQE / kernels / amplitude estimation / QUBO builders, provenance and replay, post-quantum audit."""
import json
import sys
import types
import zipfile

import pytest

np = pytest.importorskip("numpy")

import algoassure  # noqa: E402
import algoeval  # noqa: E402
import algolang as al  # noqa: E402
import algoqpu as Q  # noqa: E402
import algoquantum as aq  # noqa: E402
import algoruntime as rt  # noqa: E402
import algotrust  # noqa: E402
from algoc import CompileError, compile_source  # noqa: E402
from conftest import write  # noqa: E402

RUN = aq._guard(aq.tool_run)


def config(project, **cfg):
    write(project / "algo.config.json", json.dumps(cfg))
    rt._CONFIG = None
    rt.load_config(reload=True)
    algotrust._SIGNER.clear()
    algotrust._PQ.clear()


@pytest.fixture
def ctx():
    c = {"records": [], "ledger": {"qpu_seconds": 0.0, "qpu_usd": 0.0}}
    tok = Q.QCTX.set(c)
    yield c
    Q.QCTX.reset(tok)


# ─────────────────────────────── circuits, noise and mitigation ───────────────────────────────
def test_qaoa_circuit_reproduces_the_simulated_state():
    rng = np.random.default_rng(1)
    for n in (2, 3, 5):
        Qm = rng.normal(size=(n, n))
        costs, _ = aq.qubo_costs(Qm)
        span = costs.max() - costs.min()
        psi = aq.qaoa_state(costs, n, [0.31, 0.62], [0.4, 0.17], np)
        sv = Q.statevector(n, Q.qaoa_ops(Qm, [0.31, 0.62], [0.4, 0.17], span, np))
        assert np.allclose(np.abs(psi) ** 2, sv.probabilities())


def test_gate_folding_keeps_the_circuit_unitary():
    ops = [("h", [0], ()), ("cx", [0, 1], ()), ("rz", [1], (0.7,)), ("cp", [0, 1], (0.3,)), ("s", [0], ()),
           ("ry", [1], (1.1,)), ("t", [1], ())]
    for k in (3, 5):
        assert np.allclose(Q.statevector(2, ops).psi, Q.statevector(2, Q.fold(ops, k)).psi)
        assert len(Q.fold(ops, k)) == k * len(ops)


def test_density_matrix_noise_matches_trajectories_and_lowers_fidelity(project):
    config(project, quantum={"backend": "noisy:high", "trajectories": 600})
    be = Q.make_backend()
    ops = [("h", [0], ()), ("cx", [0, 1], ()), ("cx", [1, 2], ()), ("ry", [2], (0.4,))]
    exact = be.density_probs(3, ops, [0, 1, 2], 1.0, np)
    be.cfg["density_max_qubits"] = 0
    traj = be.probs(3, ops, [0, 1, 2], 7)
    assert np.abs(exact - traj).max() < 0.03
    ideal = Q._marginal(Q.statevector(3, ops).probabilities(), 3, [0, 1, 2], np)
    assert Q.hellinger_fidelity(ideal, exact, np) < 0.99


def test_readout_mitigation_recovers_the_distribution():
    rng_counts = Q._counts_from(np.array([0.5, 0, 0, 0.5]), [0, 1], 200_000, 3, np, readout=(0.05, 0.1))
    raw = Q.counts_vector(rng_counts, 2, np)
    fixed = Q.mitigate_readout(rng_counts, 2, (0.05, 0.1), np)
    target = np.array([0.5, 0, 0, 0.5])
    assert np.abs(fixed - target).max() < 0.01 < np.abs(raw - target).max()


# ─────────────────────────────── algorithms ───────────────────────────────
def test_vqe_reaches_chemical_accuracy_for_h2_and_spin_models(project, ctx):
    config(project)
    out = Q.tool_vqe("ground state of H2")
    assert out.startswith("CHEMICAL ACCURACY") and "-1.137306" in out
    assert Q.tool_vqe("ising n=4 h=1.0").startswith("WITHIN TOLERANCE")
    assert Q.tool_vqe("heisenberg n=4").startswith("WITHIN TOLERANCE")
    assert ctx["records"] and all(r["tool"] == "quantum.vqe" for r in ctx["records"])


def test_vqe_on_a_noisy_device_is_mitigated(project, ctx):
    config(project, quantum={"backend": "noisy:superconducting", "shots": 8192})
    out = Q.tool_vqe("H2")
    meas = float(out.splitlines()[1].split("zero-noise extrapolated ")[1].split()[0])
    assert "readout-mitigated" in out and abs(meas - (-1.137306)) < 0.03
    assert any(r.get("fidelity") is not None and r["fidelity"] < 1 for r in ctx["records"])


def test_quantum_kernel_is_compared_honestly_with_a_classical_kernel(project, ctx):
    config(project)
    out = Q.tool_kernel("moons 40 points")
    assert out.split(":")[0] in ("QUANTUM KERNEL AHEAD", "QUANTUM KERNEL ON PAR", "NO QUANTUM ADVANTAGE")
    assert "classical RBF" in out and "5-fold" in out


def test_amplitude_estimation_is_within_its_guaranteed_bound(project, ctx):
    config(project)
    out = Q.tool_amplitude("P(X below -0.25) for mean 0.05 sd 0.2")
    assert out.startswith("ESTIMATE VERIFIED") and "Monte Carlo" in out


def test_knapsack_qubo_matches_dynamic_programming(project, ctx):
    config(project)
    rng = np.random.default_rng(5)
    for _ in range(4):
        items = [(f"I{i}", float(rng.integers(1, 9)), int(rng.integers(1, 6))) for i in range(4)]
        q = "capacity 7: " + ", ".join(f"{n}={v:g}/{w}" for n, v, w in items)
        assert Q.tool_knapsack(q).startswith("KNAPSACK OPTIMAL"), q


def test_graph_colouring_is_proper_or_honestly_impossible(project, ctx):
    config(project)
    assert Q.tool_colouring("3 colours: A-B, B-C, C-A, C-D").startswith("PROPER COLOURING")
    assert Q.tool_colouring("2 colours: A-B, B-C, C-A").startswith("COLOURING FAILED")


# ─────────────────────────────── verification ───────────────────────────────
def test_lower_bound_is_valid_and_bounded_status_is_used_beyond_exact_checks(project):
    config(project, quantum={"verify_exact_max": 8, "bound_pct": 5})
    rng = np.random.default_rng(2)
    for n in (6, 10, 14):
        Qm = np.triu(rng.normal(size=(n, n)))
        costs, _ = aq.qubo_costs(Qm)
        assert Q.lower_bound(Qm, block=4) <= costs.min() + 1e-9
    n = 24                                           # block-diagonal: the bound is tight, local search finds it
    Qm = np.zeros((n, n))
    for b in range(0, n, 6):
        Qm[b:b + 6, b:b + 6] = np.triu(rng.normal(size=(6, 6)))
    best, _ = Q.local_search(Qm)
    v = Q.verify(Qm, best)
    assert v["status"] == "BOUNDED" and v["bound"] <= best + 1e-9
    assert Q.verify(Qm, best + 50)["status"] == "UNCHECKED"
    small = np.array([[-1.0, 2], [0, -1]])
    assert Q.verify(small, -1.0)["status"] == "VERIFIED" and Q.verify(small, 0.0)["status"] == "GAP"


# ─────────────────────────────── backends, budgets, replay ───────────────────────────────
def _fake_ibm(monkeypatch, calls):
    class Circ:
        def __init__(self, qasm):
            self.qasm = qasm

        @staticmethod
        def from_qasm_str(text):
            return Circ(text)

        def depth(self):
            return 7

    qiskit = types.ModuleType("qiskit")
    qiskit.QuantumCircuit = Circ
    qiskit.transpile = lambda qc, dev, **kw: qc

    class Job:
        def result(self):
            data = types.SimpleNamespace(get_counts=lambda: {"11": 480, "00": 520})
            return [types.SimpleNamespace(join_data=lambda: data)]

        def job_id(self):
            return "job-123"

        def usage(self):
            return 2.4

    class Sampler:
        def __init__(self, mode):
            pass

        def run(self, pubs, shots):
            calls.append(shots)
            return Job()

    class Service:
        def __init__(self, **kw):
            assert kw["token"] == "secret"

        def backend(self, name):
            return types.SimpleNamespace(properties=lambda: types.SimpleNamespace(last_update_date="2026-11-11"))

    rt_mod = types.ModuleType("qiskit_ibm_runtime")
    rt_mod.QiskitRuntimeService, rt_mod.SamplerV2 = Service, Sampler
    monkeypatch.setitem(sys.modules, "qiskit", qiskit)
    monkeypatch.setitem(sys.modules, "qiskit_ibm_runtime", rt_mod)


def test_ibm_hardware_backend_records_provenance(project, monkeypatch, ctx):
    config(project, quantum={"backend": "ibm:ibm_test", "shots": 1000})
    calls = []
    _fake_ibm(monkeypatch, calls)
    assert RUN('OPENQASM 2.0; qreg q[2]; creg c[2]; h q[0]; cx q[0],q[1]; measure q -> c;').startswith("BLOCKED")
    monkeypatch.setenv("IBM_QUANTUM_TOKEN", "secret")
    out = RUN('OPENQASM 2.0; qreg q[2]; creg c[2]; h q[0]; cx q[0],q[1]; measure q -> c;')
    assert "00: 520" in out and "ibm:ibm_test" in out and calls == [1000]
    rec = ctx["records"][-1]
    assert rec["job_id"] == "job-123" and rec["qpu_seconds"] == 2.4 and rec["calibration"] == "2026-11-11"
    assert rec["fidelity"] > 0.95 and rec["cost_usd"] > 0


def test_qpu_budget_blocks_before_submission(project, monkeypatch, ctx):
    config(project, quantum={"backend": "ibm:ibm_test", "shots": 1000, "max_qpu_usd": 100})
    calls = []
    _fake_ibm(monkeypatch, calls)
    monkeypatch.setenv("IBM_QUANTUM_TOKEN", "secret")
    tok = aq.POLICY.set({"budget_qpu_usd": 0.5})
    try:
        out = RUN('OPENQASM 2.0; qreg q[1]; creg c[1]; h q[0]; measure q -> c;')
    finally:
        aq.POLICY.reset(tok)
    assert out.startswith("BLOCKED") and "budget qpu" in out and calls == []
    ctx["ledger"]["qpu_usd"] = 99.9
    out = RUN('OPENQASM 2.0; qreg q[1]; creg c[1]; h q[0]; measure q -> c;')
    assert "per-run cap" in out and calls == []


def test_recorded_counts_replay_without_running(project, monkeypatch, ctx):
    config(project, quantum={"backend": "noisy:low"})
    first = RUN('OPENQASM 2.0; qreg q[2]; creg c[2]; h q[0]; cx q[0],q[1]; measure q -> c;')
    config(project, quantum={"backend": "noisy:low", "replay": "only"})
    monkeypatch.setattr(Q.NoisySimulator, "run", lambda *a, **k: pytest.fail("must not run"))
    again = RUN('OPENQASM 2.0; qreg q[2]; creg c[2]; h q[0]; cx q[0],q[1]; measure q -> c;')
    assert again == first and ctx["records"][-1]["replayed"] is True
    assert RUN('OPENQASM 2.0; qreg q[1]; creg c[1]; x q[0]; measure q -> c;').startswith("BLOCKED")


def test_unknown_backend_and_missing_sdk_are_reported(project, monkeypatch):
    config(project, quantum={"backend": "dwave:advantage"})
    assert "unknown quantum backend" in RUN('OPENQASM 2.0; qreg q[1]; h q[0];')
    config(project, quantum={"backend": "braket:sv1"})
    monkeypatch.setitem(sys.modules, "braket", None)
    assert "amazon-braket-sdk" in RUN('OPENQASM 2.0; qreg q[1]; h q[0];')


# ─────────────────────────────── the language ───────────────────────────────
QPROG = '''
tool quantum.maxcut
agent Cut(graph: text) -> uncertain<text> {
    goal  "Split {graph}"
    uses  quantum.maxcut
    policy { samples 3  budget qpu 30 seconds  budget qpu 2 usd  max qubits 200 }
}
flow main(graph: text) {
    r = Cut(graph)
    emit r
}
eval quantum on main {
    case "four nodes" (graph = "A-B:3, B-C:1, A-C:2, C-D:2") {
        expect output contains "VERIFIED"
        expect fidelity > 0.8
        expect qpu < 1
    }
}
'''


def test_budget_qpu_and_quantum_expectations_compile():
    prog = compile_source(QPROG, "q.algo")
    pol = prog.agents["Cut"].policy if hasattr(prog, "agents") else None
    if pol is not None:
        assert pol["budget_qpu_s"] == 30 and pol["budget_qpu_usd"] == 2 and pol["max_qubits"] == 200
    with pytest.raises(CompileError):
        compile_source(QPROG.replace("budget qpu 30 seconds", "budget qpu 30 parsecs"), "q.algo")
    with pytest.raises(CompileError):
        compile_source(QPROG.replace("max qubits 200", "max qubits 5000"), "q.algo")


def test_uncertain_quantum_results_carry_quantum_confidence_and_provenance(project):
    config(project, quantum={"backend": "noisy:superconducting"})
    p = al.compile(QPROG, "q")
    res = p.run(graph="A-B:3, B-C:1, A-C:2, C-D:2")
    call = [c for c in res.calls if c["agent"] == "Cut"][0]
    q = call["quantum"]
    assert q and q[0]["tool"] == "quantum.qubo" and q[0]["fidelity"] < 1
    assert call["confidence"] <= min(r["confidence"] for r in q)
    results = algoeval.run_evals(p, audit_dir=str(project / "ev"))
    assert results and all(r["passed"] for r in results), [r["failures"] for r in results]


# ─────────────────────────────── post-quantum audit signatures ───────────────────────────────
SIMPLE = 'agent G(name: text) -> text { goal "Greet {name}" }\nflow main(name: text) { emit G(name) }\n'


@pytest.mark.parametrize("alg", ["ml-dsa-44", "hybrid"])
def test_post_quantum_audit_signatures_verify_and_detect_tampering(project, alg):
    pytest.importorskip("dilithium_py")
    config(project, audit={"sign": True, "algorithm": alg})
    write(project / "g.algo", SIMPLE)
    al.load(project / "g.algo").run(name="Asha")
    log = next((project / "runs").glob("*.jsonl"))
    assert rt.verify_audit(log)["ok"]
    rec = json.loads(log.read_text().splitlines()[-1])
    assert "pqsig" in rec and (("sig" in rec) == (alg == "hybrid"))
    rec["pqsig"] = ("00" if rec["pqsig"][:2] != "00" else "11") + rec["pqsig"][2:]
    log.write_text(json.dumps(rec) + "\n")
    r = rt.verify_audit(log)
    assert not r["ok"] and "post-quantum" in r["reason"]


def test_evidence_pack_carries_a_post_quantum_manifest_signature(project):
    pytest.importorskip("dilithium_py")
    config(project, audit={"sign": True, "algorithm": "hybrid"})
    write(project / "g.algo", SIMPLE)
    al.load(project / "g.algo").run(name="Asha")
    pack = project / "g.zip"
    algoassure.export(str(project / "g.algo"), pack)
    ok, findings = algoassure.verify(pack)
    assert ok and any("post-quantum signature" in f for f in findings), findings
    bad = project / "bad.zip"
    with zipfile.ZipFile(pack) as zin, zipfile.ZipFile(bad, "w") as zout:
        for n in zin.namelist():
            data = zin.read(n)
            if n == "manifest.pqsig":
                d = json.loads(data)
                d["sig"] = ("00" if d["sig"][:2] != "00" else "11") + d["sig"][2:]
                data = json.dumps(d).encode()
            zout.writestr(n, data)
    ok, findings = algoassure.verify(bad)
    assert not ok and any("post-quantum signature is not valid" in f for f in findings)
