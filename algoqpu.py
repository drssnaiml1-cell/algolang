"""algoqpu — AlgoLang v0.6 Quantum AI: hardware backends, QPU budgets, noise, verification and provenance.

v0.3.2–v0.3.3 gave agents quantum tools on an exact simulator. v0.6 lets the same programs run on noisy
simulators and on real quantum processors, without giving up AlgoLang's guarantees:

    Q1 Backends        "quantum": {"backend": …} in algo.config.json chooses where circuits run:
                         simulator              exact state vector (default)
                         noisy:<profile>        state vector with gate (depolarising) and readout noise:
                                                superconducting · trapped-ion · low · high, or "noise": {…}
                         ibm:<device>           IBM Quantum (qiskit-ibm-runtime; IBM_QUANTUM_TOKEN)
                         braket:<device>        Amazon Braket (amazon-braket-sdk; AWS credentials; S3 bucket)
                         azure:<target>         Azure Quantum (azure-quantum; AZURE_QUANTUM_RESOURCE_ID)
    Q2 QPU budgets     `budget qpu 30 seconds` · `budget qpu 2 usd` in a policy, and per-run caps
                       ("max_qpu_seconds", "max_qpu_usd") in the config, checked before a job is submitted
    Q3 Uncertainty     every quantum tool reports a confidence from its shot statistics; agents that return
                       uncertain<T> carry it (the lower of the model's and the quantum result's confidence)
    Q4 Noise           noise models, readout-error mitigation, zero-noise extrapolation by gate folding, and
                       the Hellinger fidelity of every noisy run against the ideal result (`expect fidelity`)
    Q5 Verification    answers are VERIFIED (exact optimum), BOUNDED (within x% of a proven lower bound),
                       UNCHECKED, or GAP (worse than the known optimum); guards can require the first two
    Q6 Algorithms      quantum.vqe (ground-state energies), quantum.kernel (quantum-kernel classification
                       against a classical baseline), quantum.amplitude (amplitude estimation of a tail
                       probability), quantum.knapsack and quantum.colouring (QUBO builders, verified)
    Q7 Provenance      backend, device, calibration, depth, shots, job id, QPU time and cost of every run in the
                       audit record; counts are recorded and can be replayed with no QPU time ("replay")
    Q8 Post-quantum    ML-DSA (FIPS 204) audit signatures live in algotrust.py ("audit": {"algorithm": …})

Prices in PRICING are illustrative defaults for budgeting, not quotes: set "quantum": {"pricing": …} from your
provider's current price list. No claim of quantum speed-up is made: a quantum result is used only after it
has been checked, and a person stays accountable for the decision.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path

import algoquantum as aq

# Per-agent-call context, set by the runtime: provenance records of this call and the run's QPU ledger.
QCTX: contextvars.ContextVar[dict | None] = contextvars.ContextVar("algoqpu_ctx", default=None)

NOISE_PROFILES = {   # illustrative device classes: 1-qubit and 2-qubit depolarising error, readout P(1|0), P(0|1)
    "low": dict(p1=1e-4, p2=2e-3, readout=(0.005, 0.01)),
    "superconducting": dict(p1=3e-4, p2=8e-3, readout=(0.015, 0.03)),
    "trapped-ion": dict(p1=1e-4, p2=4e-3, readout=(0.003, 0.005)),
    "high": dict(p1=2e-3, p2=3e-2, readout=(0.03, 0.06)),
}

PRICING = {          # illustrative budgeting defaults (USD); override with "quantum": {"pricing": {...}}
    "ibm": dict(usd_per_second=1.60, seconds_per_shot=0.00025, overhead_seconds=2.0),
    "braket": dict(per_task=0.30, per_shot=0.01, seconds_per_shot=0.0005, overhead_seconds=3.0,
                   per_shot_by_device={"ionq": 0.03, "rigetti": 0.0009, "iqm": 0.00145, "quera": 0.01}),
    "azure": dict(per_task=0.0, per_shot=0.01, seconds_per_shot=0.0005, overhead_seconds=3.0),
}

INVERSE = {"h": "h", "x": "x", "y": "y", "z": "z", "s": "sdg", "sdg": "s", "t": "tdg", "tdg": "t", "id": "id",
           "cx": "cx", "cz": "cz", "cy": "cy", "ch": "ch", "swap": "swap", "ccx": "ccx",
           "rx": "rx", "ry": "ry", "rz": "rz", "p": "p", "u1": "u1", "crz": "crz", "cp": "cp", "cu1": "cu1"}
ANGLED = {"rx", "ry", "rz", "p", "u1", "crz", "cp", "cu1"}


# ═══════════════════════════════ configuration and context ═══════════════════════════════
def config():
    try:
        import algoruntime
        return dict(algoruntime.load_config().get("quantum") or {})
    except Exception:  # noqa
        return {}


def backend_name():
    return str(config().get("backend") or "simulator")


def _ctx():
    return QCTX.get()


def note(rec: dict):
    """Record a quantum run's provenance in the current agent call (and the run ledger)."""
    c = _ctx()
    rec = {k: v for k, v in rec.items() if v is not None}
    if c is not None:
        c.setdefault("records", []).append(rec)
        led = c.get("ledger")
        if led is not None:
            led["qpu_seconds"] = round(led.get("qpu_seconds", 0.0) + float(rec.get("qpu_seconds") or 0), 4)
            led["qpu_usd"] = round(led.get("qpu_usd", 0.0) + float(rec.get("cost_usd") or 0), 4)
    return rec


def confidence_of(status, fidelity=1.0, base=None):
    """Confidence of a quantum answer: from its verification status, scaled by the run's fidelity."""
    b = base if base is not None else {"VERIFIED": 0.95, "BOUNDED": 0.8, "UNCHECKED": 0.45, "GAP": 0.2}.get(status, 0.5)
    return round(max(0.0, min(1.0, b * (fidelity if fidelity is not None else 1.0))), 3)


# ═══════════════════════════════ circuits as operation lists ═══════════════════════════════
def ops_to_qasm(n, ops, measure=True):
    lines = ["OPENQASM 2.0;", 'include "qelib1.inc";', f"qreg q[{n}];"]
    if measure:
        lines.append(f"creg c[{n}];")
    for name, qs, ps in ops:
        par = f"({','.join(repr(float(p)) for p in ps)})" if ps else ""
        lines.append(f"{name}{par} " + ",".join(f"q[{q}]" for q in qs) + ";")
    if measure:
        lines += [f"measure q[{i}] -> c[{i}];" for i in range(n)]
    return "\n".join(lines) + "\n"


def fold(ops, scale):
    """Zero-noise extrapolation by unitary folding: G → G (G† G)^k, scale = 2k + 1 (odd integers)."""
    k = (int(scale) - 1) // 2
    out = []
    for name, qs, ps in ops:
        out.append((name, qs, ps))
        if name not in INVERSE:
            raise ValueError(f"cannot fold gate '{name}'")
        inv = (INVERSE[name], qs, tuple(-p for p in ps) if name in ANGLED else ps)
        for _ in range(k):
            out += [inv, (name, qs, ps)]
    return out


def statevector(n, ops):
    sv = aq.StateVector(n)
    for name, qs, ps in ops:
        sv.gate(name, qs, ps)
    return sv


def _key(index, qs):
    return "".join(str((int(index) >> q) & 1) for q in reversed(qs))


def _marginal(probs, n, qs, np):
    """Probabilities over the measured qubits `qs`, indexed by Σ bit(q_k) 2^k."""
    idx = np.arange(2 ** n)
    sub = np.zeros(len(idx), dtype=int)
    for k, q in enumerate(qs):
        sub |= ((idx >> q) & 1) << k
    return np.bincount(sub, weights=probs, minlength=2 ** len(qs))


def _counts_from(p, qs, shots, seed, np, readout=None):
    """Sample `shots` outcomes over `qs` (p indexed by measured-bit order) with optional readout errors."""
    rng = np.random.default_rng(seed)
    p = np.clip(p, 0, None)
    draws = rng.choice(len(p), size=shots, p=p / p.sum())
    if readout:
        p10, p01 = readout                                  # P(read 1 | 0), P(read 0 | 1)
        bits = (draws[:, None] >> np.arange(len(qs))) & 1
        u = rng.random(bits.shape)
        flip = np.where(bits == 0, u < p10, u < p01)
        bits = bits ^ flip
        draws = (bits << np.arange(len(qs))).sum(axis=1)
    counts = {}
    for o, c in zip(*np.unique(draws, return_counts=True)):
        key = "".join(str((int(o) >> k) & 1) for k in reversed(range(len(qs))))
        counts[key] = counts.get(key, 0) + int(c)
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def counts_vector(counts, m, np):
    v = np.zeros(2 ** m)
    for key, c in counts.items():
        v[int(key, 2)] += c
    return v / max(1, v.sum())


def hellinger_fidelity(p, q, np):
    return float(np.sum(np.sqrt(np.clip(p, 0, None) * np.clip(q, 0, None))) ** 2)


def mitigate_readout(counts, m, readout, np):
    """Tensored readout-error mitigation: apply the inverse 2×2 confusion matrix on every measured bit."""
    p10, p01 = readout
    A = np.array([[1 - p10, p01], [p10, 1 - p01]])
    Ainv = np.linalg.inv(A)
    v = counts_vector(counts, m, np).reshape([2] * m)          # axis 0 = highest bit
    for ax in range(m):
        v = np.moveaxis(np.tensordot(Ainv, v, axes=([1], [ax])), 0, ax)
    v = np.clip(v.reshape(-1), 0, None)
    return v / (v.sum() or 1)


# ═══════════════════════════════ backends ═══════════════════════════════
class Backend:
    kind = "simulator"

    def __init__(self, spec, cfg):
        self.spec, self.cfg = spec, cfg

    @property
    def label(self):
        return self.spec

    def estimate(self, shots):
        return 0.0, 0.0                                     # (QPU seconds, USD)

    def run(self, n, ops, measured, shots, seed):
        raise NotImplementedError


class ExactSimulator(Backend):
    @property
    def label(self):
        return "simulator (exact state vector)"

    def run(self, n, ops, measured, shots, seed):
        np = aq._np()
        p = _marginal(statevector(n, ops).probabilities(), n, measured, np)
        return dict(counts=_counts_from(p, measured, shots, seed, np), device="simulator", job_id=None,
                    calibration="ideal (no noise)")


def _apply_batch(M, n, name, qubits, params, np):
    """Apply a gate to every column of M (shape 2^n × B): the batch form of StateVector.gate."""
    U = aq.gate_matrix(name, params, np)
    B = M.shape[1]
    if name in ("cx", "cz", "cy", "ch", "crz", "cp", "cu1", "ccx"):
        ctrl, tgt = qubits[:-1], qubits[-1]
        idx = np.arange(2 ** n)
        mask = np.ones(idx.shape, bool)
        for c in ctrl:
            mask &= (idx >> c) & 1 == 1
        sel = idx[mask & ((idx >> tgt) & 1 == 0)]
        par = sel | (1 << tgt)
        a, b = M[sel].copy(), M[par].copy()
        M[sel], M[par] = U[0, 0] * a + U[0, 1] * b, U[1, 0] * a + U[1, 1] * b
        return M
    if name == "swap":
        for c, t in ((qubits[0], qubits[1]), (qubits[1], qubits[0]), (qubits[0], qubits[1])):
            M = _apply_batch(M, n, "cx", [c, t], (), np)
        return M
    q = qubits[0]
    V = M.reshape(2 ** (n - q - 1), 2, 2 ** q, B)
    return np.einsum("ab,ibjk->iajk", U, V).reshape(2 ** n, B)


def _conj_apply(rho, n, name, qubits, params, np):
    """ρ → G ρ G†."""
    rho = _apply_batch(rho, n, name, qubits, params, np)
    return _apply_batch(rho.conj().T.copy(), n, name, qubits, params, np).conj().T


class NoisySimulator(Backend):
    kind = "noisy"
    """Pauli-trajectory simulation: after each gate a random Pauli error with the gate's depolarising
    probability; probabilities averaged over trajectories; readout bits flipped with the readout error."""

    def __init__(self, spec, cfg):
        super().__init__(spec, cfg)
        prof = spec.split(":", 1)[1] if ":" in spec else "superconducting"
        noise = dict(NOISE_PROFILES.get(prof) or {})
        if cfg.get("noise"):
            noise.update(cfg["noise"])
        if not noise:
            raise aq.QuantumBlocked(f"unknown noise profile '{prof}': use {', '.join(NOISE_PROFILES)} or set quantum.noise")
        self.profile, self.noise = prof, noise
        self.trajectories = int(cfg.get("trajectories", 48))

    @property
    def label(self):
        n = self.noise
        return f"noisy simulator ({self.profile}: p1={n['p1']}, p2={n['p2']}, readout={tuple(n['readout'])})"

    def probs(self, n, ops, measured, seed, scale=1.0):
        np = aq._np()
        if n <= int(self.cfg.get("density_max_qubits", 8)):       # exact depolarising channels (density matrix)
            return self.density_probs(n, ops, measured, scale, np)
        rng = np.random.default_rng(seed + 1)
        p1, p2 = self.noise["p1"] * scale, self.noise["p2"] * scale
        acc = np.zeros(2 ** len(measured))
        paulis = ["x", "y", "z"]
        for _ in range(self.trajectories):
            sv = aq.StateVector(n)
            for name, qs, ps in ops:
                sv.gate(name, qs, ps)
                p = p1 if len(qs) == 1 else p2
                if p and rng.random() < p:
                    while True:                              # a random non-identity Pauli on the gate's qubits
                        pick = [int(rng.integers(0, 4)) for _ in qs]
                        if any(pick):
                            break
                    for q, k in zip(qs, pick):
                        if k:
                            sv.gate(paulis[k - 1], [q])
            acc += _marginal(sv.probabilities(), n, measured, np)
        return acc / self.trajectories

    def density_probs(self, n, ops, measured, scale, np):
        p1, p2 = self.noise["p1"] * scale, self.noise["p2"] * scale
        rho = np.zeros((2 ** n, 2 ** n), complex)
        rho[0, 0] = 1.0
        P = ["id", "x", "y", "z"]
        for name, qs, ps in ops:
            rho = _conj_apply(rho, n, name, qs, ps, np)
            p = p1 if len(qs) == 1 else p2
            if not p:
                continue
            terms = [(a,) for a in range(1, 4)] if len(qs) == 1 else \
                [(a, b) for a in range(4) for b in range(4) if a or b]
            acc = np.zeros_like(rho)
            for t in terms:
                r = rho.copy()
                for q, k in zip(qs, t):
                    if k:
                        r = _conj_apply(r, n, P[k], [q], (), np)
                acc += r
            rho = (1 - p) * rho + p / len(terms) * acc
        return _marginal(np.real(np.diag(rho)), n, measured, np)

    def run(self, n, ops, measured, shots, seed):
        np = aq._np()
        p = self.probs(n, ops, measured, seed)
        counts = _counts_from(p, measured, shots, seed, np, readout=tuple(self.noise["readout"]))
        return dict(counts=counts, device=f"noisy-{self.profile}", job_id=None, calibration=json.dumps(self.noise))


class HardwareBackend(Backend):
    kind = "hardware"
    provider = ""

    def __init__(self, spec, cfg):
        super().__init__(spec, cfg)
        self.device = spec.split(":", 1)[1] if ":" in spec else ""
        if not self.device:
            raise aq.QuantumBlocked(f"name a device: \"{self.provider}:<device>\"")

    def price(self):
        p = dict(PRICING.get(self.provider, {}))
        p.update((self.cfg.get("pricing") or {}).get(self.provider, {}))
        return p

    def estimate(self, shots):
        p = self.price()
        secs = p.get("overhead_seconds", 2.0) + shots * p.get("seconds_per_shot", 0.0005)
        if "usd_per_second" in p:
            return secs, secs * p["usd_per_second"]
        per_shot = p.get("per_shot", 0.0)
        for k, v in (p.get("per_shot_by_device") or {}).items():
            if k in self.device.lower():
                per_shot = v
        return secs, p.get("per_task", 0.0) + shots * per_shot

    @staticmethod
    def _need(module, pip):
        try:
            return __import__(module, fromlist=["_"])
        except ImportError:
            raise aq.QuantumBlocked(f"this backend needs: pip install {pip}")

    @staticmethod
    def _env(*names):
        for n in names:
            if os.environ.get(n):
                return os.environ[n]
        raise aq.QuantumBlocked(f"set the environment variable {names[0]} (credentials are never read from a program)")

    @property
    def label(self):
        return f"{self.provider}:{self.device} (quantum hardware)"


class IBMBackend(HardwareBackend):
    provider = "ibm"

    def run(self, n, ops, measured, shots, seed):
        qk = self._need("qiskit", "qiskit qiskit-ibm-runtime")
        rt = self._need("qiskit_ibm_runtime", "qiskit-ibm-runtime")
        token = self._env("IBM_QUANTUM_TOKEN", "QISKIT_IBM_TOKEN")
        service = rt.QiskitRuntimeService(channel=self.cfg.get("channel", "ibm_quantum_platform"), token=token,
                                          instance=self.cfg.get("instance"))
        device = service.backend(self.device)
        qc = qk.QuantumCircuit.from_qasm_str(ops_to_qasm(n, ops, measure=False).replace(
            f"qreg q[{n}];", f"qreg q[{n}];\ncreg c[{len(measured)}];") + "".join(
            f"measure q[{q}] -> c[{k}];\n" for k, q in enumerate(measured)))
        isa = qk.transpile(qc, device, optimization_level=1, seed_transpiler=seed)
        job = rt.SamplerV2(mode=device).run([isa], shots=shots)
        res = job.result()
        counts = res[0].join_data().get_counts()
        used = None
        try:
            used = float(job.usage())
        except Exception:  # noqa
            pass
        cal = None
        try:
            cal = str(device.properties().last_update_date)
        except Exception:  # noqa
            pass
        return dict(counts={k.replace(" ", ""): int(v) for k, v in counts.items()}, device=self.device,
                    job_id=job.job_id(), calibration=cal, depth=isa.depth(), qpu_seconds=used)


class BraketBackend(HardwareBackend):
    provider = "braket"
    DEVICES = {"sv1": "arn:aws:braket:::device/quantum-simulator/amazon/sv1",
               "dm1": "arn:aws:braket:::device/quantum-simulator/amazon/dm1"}

    def run(self, n, ops, measured, shots, seed):
        aws = self._need("braket.aws", "amazon-braket-sdk")
        circ = self._need("braket.circuits", "amazon-braket-sdk")
        bucket = self.cfg.get("s3_bucket") or self._env("BRAKET_S3_BUCKET")
        c = circ.Circuit()
        names = {"cx": "cnot", "p": "phaseshift", "u1": "phaseshift", "cp": "cphaseshift", "cu1": "cphaseshift",
                 "sdg": "si", "tdg": "ti"}
        for name, qs, ps in ops:
            getattr(c, names.get(name, name))(*qs, *ps)
        arn = self.DEVICES.get(self.device, self.device)
        task = aws.AwsDevice(arn).run(c, shots=shots, s3_destination_folder=(bucket, self.cfg.get("s3_prefix", "algolang")))
        res = task.result()
        counts = {}
        for key, v in res.measurement_counts.items():          # Braket: character i is qubit i
            k = "".join(key[q] for q in reversed(measured))
            counts[k] = counts.get(k, 0) + int(v)
        return dict(counts=counts, device=arn, job_id=getattr(task, "id", None), depth=c.depth)


class AzureBackend(HardwareBackend):
    provider = "azure"

    def run(self, n, ops, measured, shots, seed):
        qk = self._need("qiskit", "qiskit azure-quantum[qiskit]")
        az = self._need("azure.quantum", "azure-quantum[qiskit]")
        azq = self._need("azure.quantum.qiskit", "azure-quantum[qiskit]")
        ws = az.Workspace(resource_id=self._env("AZURE_QUANTUM_RESOURCE_ID"),
                          location=self.cfg.get("location") or self._env("AZURE_QUANTUM_LOCATION"))
        device = azq.AzureQuantumProvider(ws).get_backend(self.device)
        qasm = ops_to_qasm(n, ops, measure=False).replace(f"qreg q[{n}];", f"qreg q[{n}];\ncreg c[{len(measured)}];") \
            + "".join(f"measure q[{q}] -> c[{k}];\n" for k, q in enumerate(measured))
        job = device.run(qk.QuantumCircuit.from_qasm_str(qasm), shots=shots)
        counts = job.result().get_counts()
        return dict(counts={k.replace(" ", ""): int(v) for k, v in counts.items()}, device=self.device,
                    job_id=job.id() if callable(getattr(job, "id", None)) else None)


def make_backend(spec=None, cfg=None):
    cfg = config() if cfg is None else cfg
    spec = spec or str(cfg.get("backend") or "simulator")
    if spec in ("simulator", "qiskit-aer"):
        return ExactSimulator(spec, cfg)
    if spec.startswith("noisy"):
        return NoisySimulator(spec, cfg)
    for prefix, cls in (("ibm:", IBMBackend), ("braket:", BraketBackend), ("azure:", AzureBackend)):
        if spec.startswith(prefix):
            return cls(spec, cfg)
    raise aq.QuantumBlocked(f"unknown quantum backend '{spec}': use simulator, noisy:<profile>, ibm:<device>, "
                            f"braket:<device> or azure:<target>")


# ═══════════════════════════════ budgets, recording and execution ═══════════════════════════════
def preflight(backend, shots, circuits=1):
    """Q2: block a job before submission when it would break a QPU budget."""
    secs, usd = backend.estimate(shots)
    secs, usd = secs * circuits, usd * circuits
    pol = aq.POLICY.get() or {}
    cfg = backend.cfg
    led = (_ctx() or {}).get("ledger") or {}
    checks = [(pol.get("budget_qpu_s"), secs, "QPU seconds", "the agent's `budget qpu`"),
              (pol.get("budget_qpu_usd"), usd, "USD of QPU time", "the agent's `budget qpu`"),
              (cfg.get("max_qpu_seconds") and cfg["max_qpu_seconds"] - led.get("qpu_seconds", 0), secs, "QPU seconds",
               "the organisation's per-run cap (quantum.max_qpu_seconds)"),
              (cfg.get("max_qpu_usd") and cfg["max_qpu_usd"] - led.get("qpu_usd", 0), usd, "USD of QPU time",
               "the organisation's per-run cap (quantum.max_qpu_usd)")]
    for lim, est, unit, who in checks:
        if lim is not None and lim is not False and est > lim + 1e-12:
            raise aq.QuantumBlocked(f"estimated {est:.2f} {unit} exceeds {who} ({max(lim, 0):.2f}); nothing was submitted")
    return secs, usd


def _record_dir():
    try:
        import algoruntime
        cpath = algoruntime.config_path()
        base = cpath.parent if cpath else Path.cwd()
        audit = algoruntime.load_config().get("audit_dir") or "runs"
    except Exception:  # noqa
        base, audit = Path.cwd(), "runs"
    d = Path(audit)
    return (d if d.is_absolute() else base / d) / "quantum"


def run_key(label, n, ops, measured, shots, seed):
    blob = json.dumps([label, n, [[o[0], list(o[1]), [round(float(p), 12) for p in o[2]]] for o in ops],
                       list(measured), shots, seed])
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def execute(n, ops, measured=None, shots=None, seed=None, tool="quantum.run", backend=None, ideal=True):
    """Run a circuit on the configured backend with budgets, replay, fidelity and provenance.
    Returns dict(counts, backend, device, job_id, qpu_seconds, cost_usd, fidelity, depth, key, replayed)."""
    np = aq._np()
    s = aq.settings()
    cfg = config()
    be = backend or make_backend(cfg=cfg)
    measured = list(range(n)) if measured is None else list(measured)
    shots = int(shots or s["shots"])
    seed = s["seed"] if seed is None else seed
    if be.kind != "hardware":
        aq._check_qubits(n, s)
    key = run_key(be.spec, n, ops, measured, shots, seed)
    rdir = _record_dir()
    mode = str(cfg.get("replay") or "off")
    rec_file = rdir / f"{key}.json"
    if mode in ("prefer", "only") and rec_file.exists():
        out = json.loads(rec_file.read_text())
        out["counts"] = dict(sorted(out["counts"].items(), key=lambda kv: (-kv[1], kv[0])))
        out.update(replayed=True, qpu_seconds=0.0, cost_usd=0.0)
    elif mode == "only":
        raise aq.QuantumBlocked(f"replay only: no recorded counts for this circuit ({key}); nothing was submitted")
    else:
        secs, usd = preflight(be, shots) if be.kind == "hardware" else (0.0, 0.0)
        t0 = time.time()
        out = be.run(n, ops, measured, shots, seed)
        out.setdefault("qpu_seconds", secs if be.kind == "hardware" else 0.0)
        out["qpu_seconds"] = out.get("qpu_seconds") if out.get("qpu_seconds") is not None else secs
        out["cost_usd"] = round(usd, 4)
        out["wall_seconds"] = round(time.time() - t0, 3)
        out["replayed"] = False
        if be.kind != "simulator" or cfg.get("record"):
            try:
                rdir.mkdir(parents=True, exist_ok=True)
                rec_file.write_text(json.dumps({k: v for k, v in out.items() if k != "replayed"}, sort_keys=True))
            except OSError:
                pass
    out.update(backend=be.label, key=key, qubits=n, shots=shots, depth=out.get("depth") or len(ops))
    fid = None
    if ideal and isinstance(be, NoisySimulator) or (ideal and be.kind == "hardware" and n <= s["max_qubits"]):
        try:
            p_ideal = _marginal(statevector(n, ops).probabilities(), n, measured, np)
            fid = round(hellinger_fidelity(p_ideal, counts_vector(out["counts"], len(measured), np)[_perm(len(measured), np)], np), 4)
        except Exception:  # noqa
            fid = None
    out["fidelity"] = fid
    return out


def _perm(m, np):
    """counts_vector indexes by the key read as binary (highest measured bit first) — the same order as
    _marginal's Σ bit_k 2^k with k = position in `measured`, so the permutation is the identity."""
    return np.arange(2 ** m)


def provenance(tool, out, status=None, confidence=None, **extra):
    return note(dict(tool=tool, backend=out.get("backend"), device=out.get("device"), job_id=out.get("job_id"),
                     calibration=out.get("calibration"), qubits=out.get("qubits"), depth=out.get("depth"),
                     shots=out.get("shots"), qpu_seconds=round(float(out.get("qpu_seconds") or 0), 4),
                     cost_usd=out.get("cost_usd"), fidelity=out.get("fidelity"), replayed=out.get("replayed"),
                     replay_key=out.get("key"), status=status, confidence=confidence, **extra))


# ═══════════════════════════════ QAOA circuits for QUBOs (hardware path) ═══════════════════════════════
def qaoa_ops(Q, gammas, betas, span, np):
    """The QAOA circuit that algoquantum.qaoa_state simulates, as gates: phase e^{-i 2πγ C/span} from
    p (linear) and cp (quadratic) gates, mixer rx(2β)."""
    Q = np.asarray(Q, dtype=float)
    n = Q.shape[0]
    ops = [("h", [i], ()) for i in range(n)]
    for g, b in zip(gammas, betas):
        th = 2 * math.pi * g / (span or 1.0)
        for i in range(n):
            if Q[i, i]:
                ops.append(("p", [i], (-th * Q[i, i],)))
        for i in range(n):
            for j in range(i + 1, n):
                w = Q[i, j] + Q[j, i]
                if w:
                    ops.append(("cp", [i, j], (-th * w,)))
        ops += [("rx", [i], (2 * b,)) for i in range(n)]
    return ops


def qubo_value(Q, z, offset=0.0):
    x = [(z >> i) & 1 for i in range(len(Q))]
    return float(sum(Q[i][j] * x[i] * x[j] for i in range(len(Q)) for j in range(len(Q))) + offset)


def lower_bound(Q, block=12):
    """Q5: a proven lower bound on min x^T Q x. Variables are split into blocks; each block's internal part is
    minimised exactly, and every cross-block coefficient contributes at most its negative part."""
    np = aq._np()
    Q = np.asarray(Q, dtype=float)
    n = Q.shape[0]
    S = Q + Q.T - np.diag(np.diag(Q))                       # symmetric couplings, diagonal kept once
    blocks = [list(range(i, min(n, i + block))) for i in range(0, n, block)]
    lb = 0.0
    for b in blocks:
        sub = np.triu(S[np.ix_(b, b)])
        costs, _ = aq.qubo_costs(sub)
        lb += float(costs.min())
    for bi in range(len(blocks)):
        for bj in range(bi + 1, len(blocks)):
            cross = S[np.ix_(blocks[bi], blocks[bj])]
            lb += float(np.minimum(cross, 0).sum())
    return lb


def local_search(Q, seed=7, restarts=20):
    """Classical reference: best of greedy one-flip descents from random starts."""
    np = aq._np()
    Q = np.asarray(Q, dtype=float)
    n = Q.shape[0]
    S = Q + Q.T
    rng = np.random.default_rng(seed)
    best, best_x = math.inf, None
    for _ in range(restarts):
        x = rng.integers(0, 2, n).astype(float)
        while True:
            delta = (1 - 2 * x) * (np.diag(Q) + (S @ x) - np.diag(S) * x)
            i = int(np.argmin(delta))
            if delta[i] >= -1e-12:
                break
            x[i] = 1 - x[i]
        v = float(x @ Q @ x)
        if v < best:
            best, best_x = v, x.copy()
    return best, best_x


def verify(Q, value, offset=0.0, exact_max=None, bound_pct=None):
    """Q5: VERIFIED / GAP when the exact optimum is computable, else BOUNDED / UNCHECKED against a proven bound."""
    cfg = config()
    exact_max = int(exact_max or cfg.get("verify_exact_max", 20))
    bound_pct = float(bound_pct if bound_pct is not None else cfg.get("bound_pct", 5.0))
    n = len(Q)
    if n <= exact_max:
        costs, _ = aq.qubo_costs(Q, offset)
        opt = float(costs.min())
        ok = abs(value - opt) <= 1e-9 * max(1.0, abs(opt))
        return dict(status="VERIFIED" if ok else "GAP", optimum=opt, bound=opt,
                    gap_pct=0.0 if ok else round(100 * (value - opt) / (abs(opt) or 1.0), 2))
    lb = lower_bound(Q) + offset
    heur, _ = local_search(Q)
    heur += offset
    gap = 100 * (value - lb) / (abs(lb) or 1.0)
    status = "BOUNDED" if gap <= bound_pct else "UNCHECKED"
    return dict(status=status, optimum=None, bound=round(lb, 6), heuristic=round(heur, 6), gap_pct=round(gap, 2),
                bound_pct=bound_pct)


def solve_qubo_backend(Q, offset=0.0, labels=None, layers=None, shots=None, seed=None):
    """QAOA on the configured noisy or hardware backend: angles optimised classically on the simulator (when the
    problem fits), the circuit sampled on the backend, the best measured answer verified (Q5)."""
    np = aq._np()
    s = aq.settings()
    Q = np.asarray(Q, dtype=float)
    n = Q.shape[0]
    be = make_backend()
    shots = int(shots or s["shots"])
    seed = s["seed"] if seed is None else seed
    layers = layers or s["layers"]
    if n <= min(s["max_qubits"], aq.SIM_LIMIT):
        costs, _ = aq.qubo_costs(Q, offset)
        f = (lambda x: aq._expect(costs, n, x, np))
        grid = [(g, b) for g in np.linspace(0.02, 0.98, 16) for b in np.linspace(0.05, math.pi / 2, 12)]
        g0, b0 = min(grid, key=lambda gb: f([gb[0], gb[1]]))
        params, _ = aq._refine(f, [float(g0), float(b0)])
        for p in range(2, layers + 1):
            gam, bet = params[:p - 1], params[p - 1:]
            params, _ = aq._refine(f, gam + [gam[-1]] + bet + [bet[-1]])
        span = float(costs.max() - costs.min()) or 1.0
    elif be.kind == "hardware":
        params, span = [0.12, 0.39], float(np.abs(Q).sum()) or 1.0      # fixed p=1 angles beyond the simulator
    else:
        aq._check_qubits(n, s)
    p = len(params) // 2
    ops = qaoa_ops(Q, params[:p], params[p:], span, np)
    out = execute(n, ops, shots=shots, seed=seed, tool="quantum.qubo", backend=be)
    best_key = min(out["counts"], key=lambda k: qubo_value(Q, int(k, 2), offset))
    z = int(best_key, 2)
    val = qubo_value(Q, z, offset)
    v = verify(Q, val, offset)
    labels = labels or [f"x{i}" for i in range(n)]
    pick = [labels[i] for i in range(n) if (z >> i) & 1]
    hits = sum(c for k, c in out["counts"].items() if abs(qubo_value(Q, int(k, 2), offset) - val) < 1e-9)
    conf = confidence_of(v["status"], out.get("fidelity"))
    provenance("quantum.qubo", out, status=v["status"], confidence=conf)
    return dict(status=v["status"], verify=v, selection=pick, cost=round(val, 6), qubits=n, layers=p, shots=shots,
                backend=out["backend"], counts=out["counts"], fidelity=out.get("fidelity"), p_best=round(hits / shots, 4),
                confidence=conf, out=out)


def format_backend_solution(r, what="solution"):
    v = r["verify"]
    head = {"VERIFIED": "VERIFIED: the quantum answer equals the exact classical optimum",
            "GAP": f"GAP: the quantum answer is {v['gap_pct']}% worse than the exact classical optimum — do not use it unchecked",
            "BOUNDED": f"BOUNDED: within {v['gap_pct']}% of a proven lower bound ({v['bound']}), limit {v.get('bound_pct')}%",
            "UNCHECKED": f"UNCHECKED: {v['gap_pct']}% above the proven lower bound ({v['bound']}); a person must check it"}[r["status"]]
    fid = f" · fidelity {r['fidelity']}" if r.get("fidelity") is not None else ""
    lines = [head, f"{what}: {', '.join(r['selection']) or '(none)'}  (cost {r['cost']})"]
    if v.get("optimum") is not None:
        lines.append(f"classical optimum cost {v['optimum']}")
    elif v.get("heuristic") is not None:
        lines.append(f"classical local search {v['heuristic']} · proven bound {v['bound']}")
    lines.append(f"QAOA p={r['layers']} on {r['qubits']} qubits, {r['shots']} shots · P(best)={r['p_best']}{fid} · "
                 f"confidence {r['confidence']} · backend: {r['backend']}")
    return "\n".join(lines)


def solve(Q, offset=0.0, labels=None, what="solution"):
    """Solve a QUBO on whichever backend is configured; returns (text, status, selection)."""
    if backend_name() in ("simulator", "qiskit-aer"):
        r = aq.solve_qubo(Q, offset, labels)
        status = "VERIFIED" if r["verified"] else "GAP"
        conf = confidence_of(status, 1.0, base=None if not r["verified"] else min(0.99, 0.9 + 0.1 * r["p_optimal"]))
        note(dict(tool="quantum.qubo", backend=r["backend"], device="simulator", qubits=r["qubits"], shots=r["shots"],
                  depth=None, qpu_seconds=0.0, status=status, confidence=conf, fidelity=1.0))
        return aq.format_solution(r, what) + f"\nconfidence {conf}", status, r["selection"]
    r = solve_qubo_backend(Q, offset, labels)
    return format_backend_solution(r, what), r["status"], r["selection"]


# ═══════════════════════════════ Q6 · VQE ═══════════════════════════════
MOLECULES = {   # qubit Hamiltonians (Pauli label: rightmost character = qubit 0), energies in hartree
    "h2": dict(name="H2 at 0.735 Å (STO-3G, parity mapping, 2 qubits)", nuclear=0.7199689944489797,
               terms=[(-1.052373245772859, "II"), (0.39793742484318045, "IZ"), (-0.39793742484318045, "ZI"),
                      (-0.01128010425623538, "ZZ"), (0.18093119978423156, "XX")]),
}
CHEMICAL_ACCURACY = 0.0016


def parse_hamiltonian(query):
    """A molecule name, a model ("ising n=6 h=1.0", "heisenberg n=4"), or terms "-1.05 II + 0.39 IZ …"."""
    q = query.lower()
    for k, m in MOLECULES.items():
        if re.search(rf"\b{k}\b", q):
            return m["name"], m["terms"], m["nuclear"], True
    n = int((re.search(r"\bn\s*=\s*(\d+)", q) or re.search(r"(\d+)\s*(?:spins|sites|qubits)", q) or [None, 4])[1])
    if "ising" in q:
        h = float((re.search(r"\bh\s*=\s*([\d.]+)", q) or [None, 1.0])[1])
        J = float((re.search(r"\bj\s*=\s*([\d.]+)", q) or [None, 1.0])[1])
        terms = [(-J, "".join("Z" if k in (i, i + 1) else "I" for k in reversed(range(n)))) for i in range(n - 1)]
        terms += [(-h, "".join("X" if k == i else "I" for k in reversed(range(n)))) for i in range(n)]
        return f"transverse-field Ising chain, {n} spins, J={J}, h={h}", terms, 0.0, False
    if "heisenberg" in q:
        J = float((re.search(r"\bj\s*=\s*([\d.]+)", q) or [None, 1.0])[1])
        terms = [(J, "".join(P if k in (i, i + 1) else "I" for k in reversed(range(n)))) for i in range(n - 1) for P in "XYZ"]
        return f"Heisenberg chain, {n} spins, J={J}", terms, 0.0, False
    found = re.findall(r"([+-]?\s*\d*\.?\d+(?:e-?\d+)?)\s*\*?\s*([IXYZ]{1,12})\b", query)
    if found:
        terms = [(float(c.replace(" ", "")), p) for c, p in found]
        if len({len(p) for _, p in terms}) == 1:
            return "custom Hamiltonian", terms, 0.0, False
    raise ValueError('name a molecule (H2), a model ("ising n=6 h=1.0", "heisenberg n=4") or terms "-1.05 II + 0.39 IZ"')


def h_matrix(terms, np):
    P = {"I": np.eye(2), "X": np.array([[0, 1], [1, 0]], complex), "Y": np.array([[0, -1j], [1j, 0]]),
         "Z": np.diag([1.0, -1.0]).astype(complex)}
    n = len(terms[0][1])
    H = np.zeros((2 ** n, 2 ** n), complex)
    for c, lab in terms:
        M = np.array([[1.0]])
        for ch in lab:                       # leftmost character = highest qubit = most significant tensor factor
            M = np.kron(M, P[ch])
        H += c * M
    return H


def ansatz_ops(n, theta, layers):
    ops, k = [], 0
    for q in range(n):
        ops.append(("ry", [q], (theta[k],)))
        k += 1
    for _ in range(layers):
        ops += [("cx", [q, q + 1], ()) for q in range(n - 1)]
        for q in range(n):
            ops.append(("ry", [q], (theta[k],)))
            k += 1
    return ops


def rotosolve(energy, theta, sweeps=40, tol=1e-10):
    """Exact one-parameter minimisation along each angle (Rotosolve), sweeping until converged."""
    e = energy(theta)
    for _ in range(sweeps):
        old = e
        for k in range(len(theta)):
            t = theta[k]
            ep = energy(theta[:k] + [t + math.pi / 2] + theta[k + 1:])
            em = energy(theta[:k] + [t - math.pi / 2] + theta[k + 1:])
            theta[k] = t - math.pi / 2 - math.atan2(2 * e - ep - em, ep - em)
            e = energy(theta)
        if old - e < tol:
            break
    return theta, e


def measure_groups(terms):
    """Group Pauli terms that can be measured together (qubit-wise commuting)."""
    groups = []
    for c, lab in terms:
        for g in groups:
            if all(a == "I" or b == "I" or a == b for a, b in zip(g["basis"], lab)):
                g["basis"] = "".join(b if a == "I" else a for a, b in zip(g["basis"], lab))
                g["terms"].append((c, lab))
                break
        else:
            groups.append(dict(basis=lab, terms=[(c, lab)]))
    return groups


def readout_calibration(n, shots, seed):
    """Measure the backend's readout error with two calibration circuits (all 0, all 1); averaged over qubits."""
    zero = execute(n, [("id", [q], ()) for q in range(n)], shots=shots, seed=seed + 7001, tool="quantum.calibration", ideal=False)
    one = execute(n, [("x", [q], ()) for q in range(n)], shots=shots, seed=seed + 7002, tool="quantum.calibration", ideal=False)
    tot0, tot1 = sum(zero["counts"].values()), sum(one["counts"].values())
    p10 = sum(k.count("1") * c for k, c in zero["counts"].items()) / (n * tot0)
    p01 = sum(k.count("0") * c for k, c in one["counts"].items()) / (n * tot1)
    return (min(p10, 0.45), min(p01, 0.45)), [zero, one]


def measured_energy(n, ops, terms, shots, seed, scale=1, readout=None):
    """Energy estimated from shots on the configured backend, with its standard error and provenance list.
    With `readout` (P(1|0), P(0|1)) the counts are corrected by readout-error mitigation first."""
    np = aq._np()
    e, var, outs = 0.0, 0.0, []
    for gi, g in enumerate(measure_groups(terms)):
        rot = []
        for q in range(n):
            b = g["basis"][n - 1 - q]
            if b == "X":
                rot.append(("h", [q], ()))
            elif b == "Y":
                rot += [("sdg", [q], ()), ("h", [q], ())]
        circ = fold(ops, scale) + rot if scale > 1 else ops + rot
        out = execute(n, circ, shots=shots, seed=seed + 31 * gi + 1000 * scale, tool="quantum.vqe")
        outs.append(out)
        tot = sum(out["counts"].values())
        pv = mitigate_readout(out["counts"], n, readout, np) if readout else counts_vector(out["counts"], n, np)
        idx = np.arange(2 ** n)
        for c, lab in g["terms"]:
            qs = [q for q in range(n) if lab[n - 1 - q] != "I"]
            if not qs:
                e += c
                continue
            par = np.zeros(2 ** n, dtype=int)
            for q in qs:
                par ^= (idx >> q) & 1
            mean = float(((1 - 2 * par) * pv).sum())
            e += c * mean
            var += c * c * (1 - mean * mean) / tot
    return e, math.sqrt(var), outs


def tool_vqe(query: str) -> str:
    """Ground-state energy of a molecule or spin model with VQE, checked against exact diagonalisation."""
    np = aq._np()
    s = aq.settings()
    name, terms, nuclear, molecule = parse_hamiltonian(query)
    n = len(terms[0][1])
    aq._check_qubits(n, s)
    H = h_matrix(terms, np)
    exact = float(np.linalg.eigvalsh(H)[0])
    layers = int((re.search(r"(\d+)\s*layers?", query.lower()) or [None, 3 if n <= 4 else 4])[1])
    rng = np.random.default_rng(s["seed"])
    theta = [float(x) for x in rng.uniform(-0.3, 0.3, n * (layers + 1))]

    def energy(th):
        psi = statevector(n, ansatz_ops(n, th, layers)).psi
        return float(np.real(psi.conj() @ H @ psi))
    theta, e_opt = rotosolve(energy, theta)
    ops = ansatz_ops(n, theta, layers)
    tol = CHEMICAL_ACCURACY if molecule else max(1e-3, 0.01 * abs(exact))
    noisy = backend_name() not in ("simulator", "qiskit-aer")
    readout, cal = (readout_calibration(n, s["shots"], s["seed"]) if noisy and "no mitigation" not in query.lower()
                    else (None, []))
    e_meas, se, outs = measured_energy(n, ops, terms, s["shots"], s["seed"], readout=readout)
    zne, extra_runs = None, list(cal)
    if noisy and "no zne" not in query.lower():
        pts = [(1, e_meas)]
        for k in (3, 5):
            ek, _se, outs_k = measured_energy(n, ops, terms, s["shots"], s["seed"], scale=k, readout=readout)
            pts.append((k, ek))
            extra_runs += outs_k
        xs, ys = np.array([p[0] for p in pts], float), np.array([p[1] for p in pts])
        zne = float(np.polyval(np.polyfit(xs, ys, 1), 0.0))      # linear Richardson fit: stable under shot noise
        se *= 1.6                                               # extrapolation amplifies the statistical error
    best = zne if zne is not None else e_meas
    z = tol / max(se, 1e-9)
    conf = round(math.erf(z / math.sqrt(2)) * (0.95 if abs(best - exact) <= tol + 2 * se else 0.5), 3)
    ok = abs(e_opt - exact) <= tol
    unit = "Ha" if molecule else "(model units)"
    head = (("CHEMICAL ACCURACY" if ok else "NOT CHEMICALLY ACCURATE") if molecule else
            ("WITHIN TOLERANCE" if ok else "OUTSIDE TOLERANCE"))
    fid = [o["fidelity"] for o in outs if o.get("fidelity") is not None]
    for o in outs:
        provenance("quantum.vqe", o, status="VERIFIED" if ok else "GAP", confidence=conf)
    for o in extra_runs:                       # calibration and folded (ZNE) circuits cost QPU time too
        provenance("quantum.vqe", o, purpose="readout calibration" if o in cal else "zero-noise extrapolation")
    lines = [f"{head}: VQE {e_opt + nuclear:.6f} vs exact {exact + nuclear:.6f} {unit} for {name} "
             f"(error {1000 * abs(e_opt - exact):.3f} m{'Ha' if molecule else 'units'}, limit {1000 * tol:.1f})",
             f"measured with {s['shots']} shots per basis on {outs[0]['backend']}: {e_meas + nuclear:.4f} ± {se:.4f}"
             + (f" · readout-mitigated (P(1|0)={readout[0]:.3f}, P(0|1)={readout[1]:.3f})" if readout else "")
             + (f" · zero-noise extrapolated {zne + nuclear:.4f}" if zne is not None else "")
             + (f" · fidelity {min(fid)}" if fid else ""),
             f"ansatz: RY layers with CX ladders, {n} qubits, {len(theta)} parameters (Rotosolve) · "
             f"{len(measure_groups(terms))} measurement bases · confidence {conf}"]
    return "\n".join(lines)


# ═══════════════════════════════ Q6 · quantum kernel ═══════════════════════════════
def feature_ops(x, reps=2):
    n = len(x)
    ops = []
    for _ in range(reps):
        ops += [("h", [q], ()) for q in range(n)]
        ops += [("p", [q], (2 * x[q],)) for q in range(n)]
        for i in range(n - 1):
            ops += [("cx", [i, i + 1], ()), ("p", [i + 1], (2 * (math.pi - x[i]) * (math.pi - x[i + 1]),)),
                    ("cx", [i, i + 1], ())]
    return ops


def _dataset(query):
    """A CSV (features…, label) named in the query, or a built-in synthetic set: circles, xor or moons."""
    np = aq._np()
    path = aq._data_file(query, "quantum.kernel") if re.search(r"\S+\.csv", query) else None
    if path:
        rows = aq._csv_rows(path)
        cols = [c for c in rows[0] if c != "label"]
        X = np.array([[float(r[c]) for c in cols] for r in rows])
        y = np.array([1 if str(r["label"]).strip() in ("1", "yes", "true", "positive") else -1 for r in rows])
        return Path(path).name, X, y
    rng = np.random.default_rng(11)
    m = int((re.search(r"(\d+)\s*(?:points|samples)", query.lower()) or [None, 60])[1])
    q = query.lower()
    if "xor" in q:
        X = rng.uniform(-1, 1, (m, 2))
        y = np.where(X[:, 0] * X[:, 1] > 0, 1, -1)
        kind = "xor"
    elif "moon" in q:
        t = rng.uniform(0, math.pi, m)
        lab = rng.integers(0, 2, m)
        X = np.c_[np.where(lab, 1 - np.cos(t), np.cos(t)), np.where(lab, 0.5 - np.sin(t), np.sin(t))] + rng.normal(0, 0.1, (m, 2))
        y = np.where(lab, 1, -1)
        kind = "moons"
    else:
        r = np.r_[rng.uniform(0, 0.5, m // 2), rng.uniform(0.8, 1.2, m - m // 2)]
        t = rng.uniform(0, 2 * math.pi, m)
        X = np.c_[r * np.cos(t), r * np.sin(t)]
        y = np.r_[np.ones(m // 2), -np.ones(m - m // 2)].astype(int)
        kind = "circles"
    return f"synthetic {kind} ({m} points)", X, y


def kernel_ridge_cv(K, y, folds=5, lam=1e-2):
    np = aq._np()
    idx = np.arange(len(y))
    acc = []
    for f in range(folds):
        te = idx[f::folds]
        tr = np.setdiff1d(idx, te)
        a = np.linalg.solve(K[np.ix_(tr, tr)] + lam * np.eye(len(tr)), y[tr])
        pred = np.sign(K[np.ix_(te, tr)] @ a)
        acc.append(float((pred == y[te]).mean()))
    return float(np.mean(acc)), float(np.std(acc))


def tool_kernel(query: str) -> str:
    """Quantum-kernel classification (ZZ feature map, fidelity kernel) against a classical RBF kernel."""
    np = aq._np()
    s = aq.settings()
    name, X, y = _dataset(query)
    d = X.shape[1]
    aq._check_qubits(d, s)
    lo, hi = X.min(axis=0), X.max(axis=0)
    unit = (X - lo) / np.where(hi > lo, hi - lo, 1)
    m = len(y)

    def qkernel(scale):
        G = np.array([statevector(d, feature_ops(x)).psi for x in unit * math.pi * scale])
        return np.abs(G.conj() @ G.T) ** 2
    # the feature-map bandwidth is a hyperparameter, chosen by cross-validation exactly as the classical one is
    scale = max((0.25, 0.5, 1.0), key=lambda sc: kernel_ridge_cv(qkernel(sc), y)[0])
    Xs = unit * math.pi * scale
    K = qkernel(scale)
    shots = s["shots"]
    rng = np.random.default_rng(s["seed"])
    if backend_name() == "simulator":
        Kh = rng.binomial(shots, np.clip(np.triu(K, 1), 0, 1)) / shots      # compute-uncompute estimate with shots
        Kh = Kh + Kh.T + np.eye(m)
        circuits = m * (m - 1) // 2
        out = dict(backend="simulator (exact state vector)", device="simulator", qubits=d, shots=shots, qpu_seconds=0.0)
    else:
        cap = int(config().get("max_kernel_circuits", 400))
        circuits = m * (m - 1) // 2
        if circuits > cap:
            raise aq.QuantumBlocked(f"{circuits} kernel circuits exceed quantum.max_kernel_circuits ({cap}); use fewer points")
        be = make_backend()
        preflight(be, shots, circuits)
        Kh = np.eye(m)
        for i in range(m):
            for j in range(i + 1, m):
                inv = [(INVERSE[g], q, tuple(-p for p in ps) if g in ANGLED else ps) for g, q, ps in reversed(feature_ops(Xs[j]))]
                out = execute(d, feature_ops(Xs[i]) + inv, shots=shots, seed=s["seed"] + i * m + j, tool="quantum.kernel",
                              backend=be, ideal=False)
                Kh[i, j] = Kh[j, i] = out["counts"].get("0" * d, 0) / shots
    w, V = np.linalg.eigh((Kh + Kh.T) / 2)                    # shot noise makes the estimate indefinite:
    Kh = (V * np.clip(w, 0, None)) @ V.T                       # project it back onto valid (PSD) kernels
    qa, qs = max((kernel_ridge_cv(Kh, y, lam=lm) for lm in (1e-2, 1e-1, 1.0)), key=lambda r: r[0])
    D = ((X[:, None, :] - X[None, :, :]) ** 2).sum(-1)
    g0 = 1 / (np.median(D[D > 0]) or 1.0)
    gamma = max((g0 / 4, g0, g0 * 4), key=lambda g: kernel_ridge_cv(np.exp(-g * D), y)[0])
    ca, cs = max((kernel_ridge_cv(np.exp(-gamma * D), y, lam=lm) for lm in (1e-2, 1e-1, 1.0)), key=lambda r: r[0])
    verdict = ("QUANTUM KERNEL AHEAD" if qa > ca + max(qs, cs) else
               "NO QUANTUM ADVANTAGE" if qa < ca - max(qs, cs) else "QUANTUM KERNEL ON PAR")
    conf = round(max(0.0, min(1.0, qa - qs)), 3)
    provenance("quantum.kernel", out, status="VERIFIED", confidence=conf, circuits=circuits)
    return (f"{verdict}: quantum kernel accuracy {qa:.3f} ± {qs:.3f} vs classical RBF {ca:.3f} ± {cs:.3f} "
            f"(5-fold cross-validation, kernel ridge) on {name}\n"
            f"ZZ feature map, {d} qubits, 2 repetitions, bandwidth {scale}π (both kernels tuned by cross-validation) · {circuits} kernel entries estimated with {shots} shots each "
            f"(compute-uncompute) · confidence {conf}")


# ═══════════════════════════════ Q6 · amplitude estimation ═══════════════════════════════
def tool_amplitude(query: str) -> str:
    """Tail probability of a normal variable by quantum amplitude estimation, against Monte Carlo."""
    from statistics import NormalDist
    np = aq._np()
    s = aq.settings()
    q = query.lower()
    mean = float((re.search(r"mean\s*=?\s*(-?[\d.]+)", q) or [None, 0.0])[1])
    sd = float((re.search(r"(?:sd|sigma|std)\s*=?\s*([\d.]+)", q) or [None, 1.0])[1])
    m = re.search(r"(below|under|<|above|over|>)\s*(-?[\d.]+)", q)
    if not m:
        raise ValueError('give a threshold: "P(X below -0.25) for mean 0.05 sd 0.2"')
    above = m.group(1) in ("above", "over", ">")
    t = float(m.group(2))
    bits = int((re.search(r"(\d+)\s*(?:evaluation|counting)\s*qubits", q) or [None, 7])[1])
    aq._check_qubits(bits, s)
    p = 1 - NormalDist(mean, sd).cdf(t) if above else NormalDist(mean, sd).cdf(t)
    est, calls, bound = aq.qae_estimate(p, bits, s["shots"], s["seed"])
    rng = np.random.default_rng(s["seed"])
    mc = float(np.mean((rng.normal(mean, sd, calls) > t) if above else (rng.normal(mean, sd, calls) < t)))
    mc_se = math.sqrt(max(p * (1 - p), 1e-12) / calls)
    ok = abs(est - p) <= bound
    status = "VERIFIED" if ok else "GAP"
    conf = confidence_of(status)
    note(dict(tool="quantum.amplitude", backend="simulator (exact phase-estimation statistics)", device="simulator",
              qubits=bits + 1, shots=s["shots"], qpu_seconds=0.0, status=status, confidence=conf, fidelity=1.0))
    side = "above" if above else "below"
    return (f"ESTIMATE {status}: P(X {side} {t}) = {est:.5f} by amplitude estimation (exact {p:.5f}, error "
            f"{abs(est - p):.5f}, guaranteed bound {bound:.5f}) with {calls} oracle calls\n"
            f"Monte Carlo with the same {calls} samples: {mc:.5f} (standard error {mc_se:.5f}) · quadratic speed-up in "
            f"oracle calls on an ideal device; no speed-up on this classical simulator · confidence {conf}")


# ═══════════════════════════════ Q6 · QUBO builders: knapsack and graph colouring ═══════════════════════════════
def knapsack_qubo(items, capacity, penalty=None):
    """maximise Σ v_i x_i with Σ w_i x_i ≤ W:  min −Σ v x + P (Σ w x + Σ 2^k s_k − W)², binary slack s."""
    np = aq._np()
    nb = max(1, math.ceil(math.log2(capacity + 1)))
    coef = [w for _, _, w in items] + [2 ** k for k in range(nb)]
    n = len(coef)
    P = penalty or (sum(v for _, v, _ in items) + 1)
    Q = np.zeros((n, n))
    for i, (_, v, _) in enumerate(items):
        Q[i, i] -= v
    for i in range(n):
        Q[i, i] += P * (coef[i] ** 2 - 2 * capacity * coef[i])
        for j in range(i + 1, n):
            Q[i, j] += 2 * P * coef[i] * coef[j]
    return Q, P * capacity ** 2, nb


def knapsack_dp(items, capacity):
    best = [(0, [])] * (capacity + 1)
    for name, v, w in items:
        for c in range(capacity, w - 1, -1):
            if best[c - w][0] + v > best[c][0]:
                best[c] = (best[c - w][0] + v, best[c - w][1] + [name])
    return best[capacity]


def tool_knapsack(query: str) -> str:
    """Knapsack as a QUBO: "capacity 10: A=6/5, B=5/4, C=4/3" (value/weight)."""
    cap = re.search(r"capacity\s*=?\s*(\d+)", query.lower())
    items = [(n, float(v), int(w)) for n, v, w in re.findall(r"([A-Za-z][\w-]*)\s*=\s*([\d.]+)\s*/\s*(\d+)", query)]
    if not cap or len(items) < 2:
        raise ValueError('write "capacity 10: A=6/5, B=5/4, C=4/3" (name = value / weight)')
    W = int(cap.group(1))
    Q, off, nb = knapsack_qubo(items, W)
    labels = [n for n, _, _ in items] + [f"slack{k}" for k in range(nb)]
    text, status, sel = solve(Q, off, labels, "packed")
    chosen = [s for s in sel if not s.startswith("slack")]
    val = sum(v for n, v, _ in items if n in chosen)
    wt = sum(w for n, _, w in items if n in chosen)
    dp_val, dp_items = knapsack_dp(items, W)
    agree = abs(val - dp_val) < 1e-9 and wt <= W
    return (f"KNAPSACK {'OPTIMAL' if agree else 'NOT OPTIMAL'}: {', '.join(chosen) or '(none)'} · value {val:g} · "
            f"weight {wt}/{W} · dynamic programming optimum {dp_val:g} ({', '.join(dp_items)})\n" + text)


def tool_colouring(query: str) -> str:
    """Graph colouring as a QUBO: "3 colours: A-B, B-C, C-A, C-D" (one-hot encoding)."""
    np = aq._np()
    k = int((re.search(r"(\d+)\s*colou?rs?", query.lower()) or [None, 3])[1])
    edges = re.findall(r"([A-Za-z]\w*)\s*-\s*([A-Za-z]\w*)", query)
    nodes = sorted({a for e in edges for a in e})
    if not edges:
        raise ValueError('write "3 colours: A-B, B-C, C-A, C-D"')
    n = len(nodes) * k
    idx = {(v, c): i for i, (v, c) in enumerate((v, c) for v in nodes for c in range(k))}
    Q = np.zeros((n, n))
    A = 2.0
    for v in nodes:                                   # A (1 − Σ_c x_vc)²: exactly one colour per node
        for c in range(k):
            Q[idx[v, c], idx[v, c]] -= A
            for c2 in range(c + 1, k):
                Q[idx[v, c], idx[v, c2]] += 2 * A
    for a, b in edges:                                # neighbours never share a colour
        for c in range(k):
            i, j = sorted((idx[a, c], idx[b, c]))
            Q[i, j] += 1.0
    labels = [f"{v}:c{c + 1}" for v in nodes for c in range(k)]
    text, status, sel = solve(Q, A * len(nodes), labels, "colouring")
    colour = {}
    for lab in sel:
        v, c = lab.split(":")
        colour.setdefault(v, []).append(c)
    proper = all(len(colour.get(v, [])) == 1 for v in nodes) and all(colour[a] != colour[b] for a, b in edges
                                                                      if a in colour and b in colour)
    clashes = sum(1 for a, b in edges if colour.get(a) and colour.get(a) == colour.get(b))
    head = (f"PROPER COLOURING with {k} colours: " + ", ".join(f"{v}={colour[v][0]}" for v in nodes)
            if proper else f"COLOURING FAILED with {k} colours: the best assignment leaves {clashes} clash(es); try more colours")
    return head + "\n" + text


def tool_backend(query: str) -> str:
    """Describe the configured quantum backend, its noise, prices and remaining QPU budget."""
    be = make_backend()
    secs, usd = be.estimate(aq.settings()["shots"])
    led = (_ctx() or {}).get("ledger") or {}
    cfg = config()
    return (f"BACKEND {be.label} · {aq.settings()['shots']} shots ≈ {secs:.1f} QPU s, ${usd:.2f} (illustrative prices) · "
            f"this run so far: {led.get('qpu_seconds', 0):.1f} s, ${led.get('qpu_usd', 0):.2f} · caps: "
            f"{cfg.get('max_qpu_seconds', 'none')} s, ${cfg.get('max_qpu_usd', 'none')}")


def _guard(fn):
    return aq._guard(fn)


def register(register_tool):
    register_tool("quantum.vqe", "Ground-state energy of a molecule (H2) or spin model with VQE, checked exactly")(_guard(tool_vqe))
    register_tool("quantum.kernel", "Quantum-kernel classification against a classical RBF kernel (cross-validated)")(_guard(tool_kernel))
    register_tool("quantum.amplitude", "Tail probability by quantum amplitude estimation, against Monte Carlo")(_guard(tool_amplitude))
    register_tool("quantum.knapsack", "Knapsack as a QUBO: \"capacity 10: A=6/5, B=5/4\" (value/weight), verified")(_guard(tool_knapsack))
    register_tool("quantum.colouring", "Graph colouring as a QUBO: \"3 colours: A-B, B-C, C-A\", verified")(_guard(tool_colouring))
    register_tool("quantum.backend", "The configured quantum backend, its noise, prices and QPU budget")(_guard(tool_backend))
