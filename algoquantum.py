"""algoquantum — quantum computing tools for AlgoLang agents (v0.3.2, preview).

Agents reach quantum computers the same way they reach any other system: through declared, granted,
audited tools. Five tools are built in:

    quantum.run      run an OpenQASM 2.0 circuit and return measurement counts
    quantum.qubo     solve a QUBO (quadratic binary optimisation) with QAOA, verified against the exact optimum
    quantum.maxcut   split a weighted graph into two groups with the heaviest cut (QAOA, verified)
    quantum.grover   Grover search for marked items among 2^n
    quantum.random   random bits from measuring qubits in superposition

    tool quantum.qubo
    agent Optimizer(problem: text) -> text {
        goal   "Solve {problem}"
        uses   quantum.qubo
        policy { shots 2048  max qubits 12 }
    }
    flow main(problem: text) {
        r = Optimizer(problem)
        if r contains "VERIFIED" { emit r } else { emit Review(r) }   // never trust an unverified quantum answer
    }

Trustworthy by design
    * Every optimisation result is checked against the exact classical optimum (the simulator enumerates
      every bitstring, so the check is exact up to max_qubits). The first line says VERIFIED or GAP.
    * Shots and qubit limits come from the agent's policy (`shots N`, `max qubits N`) and the organisation's
      algo.config.json ("quantum": {"max_qubits": …}); the stricter limit wins. Bigger circuits are BLOCKED.
    * Runs are seeded, so the same request gives the same answer (needed for audit and replay).
    * The backend is named in every answer. The built-in simulator is a classical computer computing the
      quantum state exactly: it shows what an ideal quantum computer would return, with no speed-up.

Backends ("quantum": {"backend": …} in algo.config.json)
    simulator    built-in NumPy state-vector simulator (default, exact, up to about 20 qubits)
    qiskit-aer   Qiskit Aer, for quantum.run (pip install qiskit qiskit-aer)
Real quantum hardware (IBM Quantum, Amazon Braket, Azure Quantum) is planned for v0.5; see ROADMAP.md.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import math
import re

# The calling agent's effective policy, set by the runtime around each model call (shots, max_qubits).
POLICY: contextvars.ContextVar[dict] = contextvars.ContextVar("algoquantum_policy", default={})
SIM_LIMIT = 24          # 2^24 amplitudes × 16 bytes = 256 MB: the hard ceiling of the built-in simulator


class QuantumBlocked(Exception):
    """A request exceeds a qubit or shot limit."""


def _np():
    try:
        import numpy as np
        return np
    except ImportError:
        raise QuantumBlocked("quantum tools need NumPy: pip install numpy   (or pip install \"algolang[quantum]\")")


def settings():
    """Merged limits: defaults ← algo.config.json "quantum" ← the agent's policy (stricter qubit limit wins)."""
    cfg = {}
    try:
        import algoruntime
        cfg = dict(algoruntime.load_config().get("quantum") or {})
    except Exception:  # noqa
        pass
    pol = POLICY.get() or {}
    max_q = min(int(cfg.get("max_qubits", 20)), SIM_LIMIT)
    if pol.get("max_qubits"):
        max_q = min(max_q, int(pol["max_qubits"]))
    shots = int(pol.get("shots") or cfg.get("shots", 1024))
    return dict(backend=cfg.get("backend", "simulator"), max_qubits=max_q, shots=shots,
                seed=int(cfg.get("seed", 7)), layers=int(cfg.get("qaoa_layers", 2)))


def _check_qubits(n, s):
    if n > s["max_qubits"]:
        raise QuantumBlocked(f"needs {n} qubits, above the limit of {s['max_qubits']} (policy `max qubits` or "
                             f"algo.config.json quantum.max_qubits)")
    if n < 1:
        raise QuantumBlocked("no qubits in the request")


# ═══════════════════════════════ state-vector simulator ═══════════════════════════════
class StateVector:
    """n-qubit state. Qubit 0 is the least significant bit of a basis index (Qiskit's convention)."""

    def __init__(self, n):
        np = _np()
        self.n, self.np = n, np
        self.psi = np.zeros(2 ** n, dtype=complex)
        self.psi[0] = 1.0

    def _apply1(self, U, q):
        np = self.np
        psi = self.psi.reshape(2 ** (self.n - q - 1), 2, 2 ** q)
        self.psi = np.einsum("ab,ibj->iaj", U, psi).reshape(-1)

    def _apply_controlled(self, U, controls, target):
        np = self.np
        idx = np.arange(2 ** self.n)
        mask = np.ones(idx.shape, bool)
        for c in controls:
            mask &= (idx >> c) & 1 == 1
        sel = idx[mask & ((idx >> target) & 1 == 0)]
        partner = sel | (1 << target)
        a, b = self.psi[sel].copy(), self.psi[partner].copy()
        self.psi[sel] = U[0, 0] * a + U[0, 1] * b
        self.psi[partner] = U[1, 0] * a + U[1, 1] * b

    def gate(self, name, qubits, params=()):
        np = self.np
        U = gate_matrix(name, params, np)
        if name in ("cx", "cz", "cy", "ch", "crz", "cp", "cu1"):
            self._apply_controlled(U, [qubits[0]], qubits[1])
        elif name == "ccx":
            self._apply_controlled(U, [qubits[0], qubits[1]], qubits[2])
        elif name == "swap":
            a, b = qubits
            for c, t in ((a, b), (b, a), (a, b)):
                self._apply_controlled(gate_matrix("x", (), np), [c], t)
        else:
            self._apply1(U, qubits[0])

    def probabilities(self):
        return (self.psi.conj() * self.psi).real

    def sample(self, shots, seed, measured=None):
        np = self.np
        p = self.probabilities()
        p = p / p.sum()
        rng = np.random.default_rng(seed)
        outcomes = rng.choice(len(p), size=shots, p=p)
        counts = {}
        qs = measured if measured is not None else list(range(self.n))
        for o, c in zip(*np.unique(outcomes, return_counts=True)):
            key = "".join(str((int(o) >> q) & 1) for q in reversed(qs))
            counts[key] = counts.get(key, 0) + int(c)
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def gate_matrix(name, params, np):
    s2 = 1 / math.sqrt(2)
    th = params[0] if params else 0.0
    base = {
        "h": [[s2, s2], [s2, -s2]], "x": [[0, 1], [1, 0]], "y": [[0, -1j], [1j, 0]], "z": [[1, 0], [0, -1]],
        "s": [[1, 0], [0, 1j]], "sdg": [[1, 0], [0, -1j]], "t": [[1, 0], [0, np.exp(1j * math.pi / 4)]],
        "tdg": [[1, 0], [0, np.exp(-1j * math.pi / 4)]], "id": [[1, 0], [0, 1]],
        "rx": [[math.cos(th / 2), -1j * math.sin(th / 2)], [-1j * math.sin(th / 2), math.cos(th / 2)]],
        "ry": [[math.cos(th / 2), -math.sin(th / 2)], [math.sin(th / 2), math.cos(th / 2)]],
        "rz": [[np.exp(-1j * th / 2), 0], [0, np.exp(1j * th / 2)]],
        "p": [[1, 0], [0, np.exp(1j * th)]], "u1": [[1, 0], [0, np.exp(1j * th)]],
    }
    alias = {"cx": "x", "ccx": "x", "cz": "z", "cy": "y", "ch": "h", "crz": "rz", "cp": "p", "cu1": "p", "swap": "x"}
    if name in ("u", "u3"):
        t, ph, lam = (list(params) + [0, 0, 0])[:3]
        return np.array([[math.cos(t / 2), -np.exp(1j * lam) * math.sin(t / 2)],
                         [np.exp(1j * ph) * math.sin(t / 2), np.exp(1j * (ph + lam)) * math.cos(t / 2)]], dtype=complex)
    if name == "u2":
        ph, lam = (list(params) + [0, 0])[:2]
        return gate_matrix("u3", (math.pi / 2, ph, lam), np)
    key = alias.get(name, name)
    if key not in base:
        raise ValueError(f"unsupported gate '{name}'")
    return np.array(base[key], dtype=complex)


# ═══════════════════════════════ OpenQASM 2.0 (subset) ═══════════════════════════════
GATES = {"h": 1, "x": 1, "y": 1, "z": 1, "s": 1, "sdg": 1, "t": 1, "tdg": 1, "id": 1, "rx": 1, "ry": 1, "rz": 1,
         "p": 1, "u1": 1, "u2": 1, "u3": 1, "u": 1, "cx": 2, "cz": 2, "cy": 2, "ch": 2, "crz": 2, "cp": 2, "cu1": 2,
         "swap": 2, "ccx": 3}


def _num(expr):
    expr = expr.strip().replace("pi", str(math.pi))
    if not re.fullmatch(r"[\d\.\s\+\-\*/\(\)e]+", expr):
        raise ValueError(f"bad parameter '{expr}'")
    return float(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 — digits and arithmetic only (checked above)


def parse_qasm(text):
    """Parse an OpenQASM 2.0 program (one or more qreg/creg, the standard gates above, measure, barrier)."""
    m = re.search(r"OPENQASM\s+2(\.0)?\s*;", text)
    if not m:
        raise ValueError("expected an OpenQASM 2.0 program starting with 'OPENQASM 2.0;'")
    body = re.sub(r"//[^\n]*", "", text[m.start():])
    qregs, cregs, ops, measures = {}, {}, [], []
    nq = nc = 0
    for stmt in (s.strip() for s in body.split(";")):
        if not stmt or stmt.startswith(("OPENQASM", "include", "barrier")):
            continue
        if stmt.startswith("qreg"):
            name, size = re.fullmatch(r"qreg\s+(\w+)\s*\[\s*(\d+)\s*\]", stmt).groups()
            qregs[name] = (nq, int(size))
            nq += int(size)
            continue
        if stmt.startswith("creg"):
            name, size = re.fullmatch(r"creg\s+(\w+)\s*\[\s*(\d+)\s*\]", stmt).groups()
            cregs[name] = (nc, int(size))
            nc += int(size)
            continue

        def qubit(ref, regs=qregs):
            r = re.fullmatch(r"(\w+)\s*\[\s*(\d+)\s*\]", ref.strip())
            if not r or r.group(1) not in regs:
                raise ValueError(f"unknown register reference '{ref.strip()}'")
            off, size = regs[r.group(1)]
            if int(r.group(2)) >= size:
                raise ValueError(f"index out of range: '{ref.strip()}'")
            return off + int(r.group(2))

        if stmt.startswith("measure"):
            mm = re.fullmatch(r"measure\s+(.+?)\s*->\s*(.+)", stmt)
            if not mm:
                raise ValueError(f"bad measure: '{stmt}'")
            src, dst = mm.groups()
            if "[" in src:
                measures.append((qubit(src), qubit(dst, cregs)))
            else:                                    # measure q -> c (whole registers)
                (qo, qs), (co, _) = qregs[src.strip()], cregs[dst.strip()]
                measures += [(qo + i, co + i) for i in range(qs)]
            continue
        g = re.fullmatch(r"(\w+)\s*(?:\(([^)]*)\))?\s+(.+)", stmt)
        if not g or g.group(1) not in GATES:
            raise ValueError(f"unsupported statement: '{stmt}'")
        name, params, args = g.groups()
        refs = [a for a in args.split(",")]
        ps = tuple(_num(p) for p in params.split(",")) if params else ()
        if all("[" in r for r in refs):
            ops.append((name, [qubit(r) for r in refs], ps))
        else:                                        # h q;  → apply to every qubit of the register
            (off, size) = qregs[refs[0].strip()]
            ops += [(name, [off + i], ps) for i in range(size)]
        if len(ops[-1][1]) != GATES[name]:
            raise ValueError(f"gate {name} takes {GATES[name]} qubit(s)")
    return nq, nc, ops, measures


def run_qasm(text, shots=None, seed=None):
    s = settings()
    shots = shots or s["shots"]
    seed = s["seed"] if seed is None else seed
    nq, nc, ops, measures = parse_qasm(text)
    _check_qubits(nq, s)
    if s["backend"] == "qiskit-aer":
        try:
            from qiskit import QuantumCircuit, transpile
            from qiskit_aer import AerSimulator
        except ImportError:
            raise QuantumBlocked("backend qiskit-aer needs: pip install qiskit qiskit-aer")
        qc = QuantumCircuit.from_qasm_str(text[re.search(r"OPENQASM", text).start():])
        sim = AerSimulator(seed_simulator=seed)
        counts = sim.run(transpile(qc, sim), shots=shots).result().get_counts()
        counts = {k.replace(" ", ""): v for k, v in sorted(counts.items(), key=lambda kv: -kv[1])}
        return dict(qubits=nq, depth=len(ops), shots=shots, counts=counts, backend="qiskit-aer")
    sv = StateVector(nq)
    for name, qs, ps in ops:
        sv.gate(name, qs, ps)
    if measures:
        order = [q for q, _ in sorted(measures, key=lambda m: m[1])]
    else:
        order = list(range(nq))
    counts = sv.sample(shots, seed, measured=order)
    return dict(qubits=nq, depth=len(ops), shots=shots, counts=counts, backend="simulator (exact state vector)")


# ═══════════════════════════════ QAOA for QUBO problems ═══════════════════════════════
def qubo_costs(Q, offset=0.0):
    """Cost of every bitstring z (index = Σ z_i 2^i) for x^T Q x + offset."""
    np = _np()
    Q = np.asarray(Q, dtype=float)
    n = Q.shape[0]
    idx = np.arange(2 ** n)
    bits = ((idx[:, None] >> np.arange(n)) & 1).astype(float)
    return np.einsum("ki,ij,kj->k", bits, Q, bits) + offset, bits


def _mixer(psi, n, beta, np):
    c, s = math.cos(beta), -1j * math.sin(beta)
    for q in range(n):
        v = psi.reshape(2 ** (n - q - 1), 2, 2 ** q)
        a, b = v[:, 0, :].copy(), v[:, 1, :].copy()
        v[:, 0, :] = c * a + s * b
        v[:, 1, :] = s * a + c * b
    return psi


def qaoa_state(costs, n, gammas, betas, np):
    span = (costs.max() - costs.min()) or 1.0
    norm = (costs - costs.min()) / span                          # scale costs to [0, 1] so angles are portable
    psi = np.full(2 ** n, 1 / math.sqrt(2 ** n), dtype=complex)
    for g, b in zip(gammas, betas):
        psi = psi * np.exp(-1j * g * norm * math.pi * 2)
        psi = _mixer(psi, n, b, np)
    return psi


def _expect(costs, n, params, np):
    p = len(params) // 2
    psi = qaoa_state(costs, n, params[:p], params[p:], np)
    return float(((psi.conj() * psi).real * costs).sum())


def _refine(f, x, step=0.2, iters=60):
    """Small derivative-free coordinate search (deterministic, no SciPy needed)."""
    best = f(x)
    for _ in range(iters):
        improved = False
        for i in range(len(x)):
            for d in (step, -step):
                y = list(x)
                y[i] += d
                v = f(y)
                if v < best - 1e-12:
                    x, best, improved = y, v, True
        if not improved:
            step /= 2
            if step < 1e-3:
                break
    return x, best


def solve_qubo(Q, offset=0.0, labels=None, layers=None, shots=None, seed=None):
    """QAOA on the simulator, then an exact classical check. Returns a dict (see `format_solution`)."""
    np = _np()
    s = settings()
    Q = np.asarray(Q, dtype=float)
    n = Q.shape[0]
    _check_qubits(n, s)
    layers = layers or s["layers"]
    shots = shots or s["shots"]
    seed = s["seed"] if seed is None else seed
    costs, bits = qubo_costs(Q, offset)
    f = (lambda x: _expect(costs, n, x, np))
    # p = 1 by grid search, then grow the circuit one layer at a time with warm starts
    grid = [(g, b) for g in np.linspace(0.02, 0.98, 16) for b in np.linspace(0.05, math.pi / 2, 12)]
    g0, b0 = min(grid, key=lambda gb: f([gb[0], gb[1]]))
    gam, bet = [float(g0)], [float(b0)]
    params, val = _refine(f, gam + bet)
    for p in range(2, layers + 1):
        gam, bet = params[:p - 1], params[p - 1:]
        params, val = _refine(f, gam + [gam[-1]] + bet + [bet[-1]])
    p = len(params) // 2
    psi = qaoa_state(costs, n, params[:p], params[p:], np)
    probs = (psi.conj() * psi).real
    rng = np.random.default_rng(seed)
    draws = rng.choice(len(probs), size=shots, p=probs / probs.sum())
    uniq, cnt = np.unique(draws, return_counts=True)
    best_q = int(min(uniq, key=lambda z: costs[z]))              # best bitstring the quantum run actually measured
    opt = int(np.argmin(costs))
    opt_cost, q_cost = float(costs[opt]), float(costs[best_q])
    worst = float(costs.max())
    ok = abs(q_cost - opt_cost) <= 1e-9 * max(1.0, abs(opt_cost))
    labels = labels or [f"x{i}" for i in range(n)]
    pick = (lambda z: [labels[i] for i in range(n) if (z >> i) & 1])
    top = sorted(zip(uniq.tolist(), cnt.tolist()), key=lambda t: -t[1])[:5]
    return dict(
        verified=ok, qubits=n, layers=p, shots=shots, backend="simulator (exact state vector)",
        selection=pick(best_q), bitstring=format(best_q, f"0{n}b")[::-1], cost=round(q_cost, 6),
        optimum=pick(opt), optimum_cost=round(opt_cost, 6),
        gap_pct=0.0 if ok else round(100 * (q_cost - opt_cost) / (abs(opt_cost) or 1.0), 2),
        p_optimal=round(float(probs[np.isclose(costs, opt_cost)].sum()), 4),
        approx_ratio=round(1 - (float((probs * costs).sum()) - opt_cost) / ((worst - opt_cost) or 1.0), 4),
        top=[(format(z, f"0{n}b")[::-1], c, round(float(costs[z]), 4)) for z, c in top],
        angles=[round(float(a), 4) for a in params])


def format_solution(r, what="solution"):
    head = ("VERIFIED: the quantum answer equals the exact classical optimum" if r["verified"] else
            f"GAP: the quantum answer is {r['gap_pct']}% worse than the exact classical optimum — do not use it unchecked")
    lines = [head,
             f"{what}: {', '.join(r['selection']) or '(none)'}  (cost {r['cost']})",
             f"classical optimum: {', '.join(r['optimum']) or '(none)'}  (cost {r['optimum_cost']})",
             f"QAOA p={r['layers']} on {r['qubits']} qubits, {r['shots']} shots · P(optimal)={r['p_optimal']} · "
             f"approximation ratio {r['approx_ratio']} · backend: {r['backend']}",
             "most frequent bitstrings (qubit 0 first): " + ", ".join(f"{b}×{c}" for b, c, _ in r["top"])]
    return "\n".join(lines)


def portfolio_qubo(returns, risk, k, risk_aversion=0.5, penalty=None, cov=None):
    """Pick exactly k assets: minimise risk_aversion·risk − return, with a penalty for choosing ≠ k.
    `risk` is a per-asset variance (diagonal) unless a covariance matrix `cov` is given."""
    np = _np()
    mu = np.asarray(returns, float)
    n = len(mu)
    S = np.asarray(cov, float) if cov is not None else np.diag(np.asarray(risk, float))
    A = penalty if penalty is not None else 2.0 * (np.abs(mu).sum() + np.abs(S).sum() * risk_aversion + 1.0)
    Q = risk_aversion * S - np.diag(mu)
    Q = Q + A * (np.ones((n, n)) - np.eye(n)) + np.diag([A * (1 - 2 * k)] * n)   # A(Σx − k)² expanded (x² = x)
    return Q, A * k * k


def maxcut_qubo(nodes, edges):
    """Max-cut as a QUBO: maximise Σ w (x_i + x_j − 2 x_i x_j)  →  minimise its negative."""
    np = _np()
    pos = {v: i for i, v in enumerate(nodes)}
    n = len(nodes)
    Q = np.zeros((n, n))
    for a, b, w in edges:
        i, j = pos[a], pos[b]
        Q[i, i] -= w
        Q[j, j] -= w
        Q[i, j] += w
        Q[j, i] += w
    return Q


# ═══════════════════════════════ Grover search ═══════════════════════════════
def grover(n, marked, shots=None, seed=None):
    np = _np()
    s = settings()
    _check_qubits(n, s)
    N = 2 ** n
    marked = sorted({m for m in marked if 0 <= m < N})
    if not marked:
        raise ValueError(f"no marked items in 0…{N - 1}")
    iters = max(1, int(math.floor(math.pi / 4 * math.sqrt(N / len(marked)))))
    psi = np.full(N, 1 / math.sqrt(N), dtype=complex)
    for _ in range(iters):
        psi[marked] *= -1                       # oracle: flip the phase of the marked items
        psi = 2 * psi.mean() - psi              # diffusion: inversion about the mean
    probs = (psi.conj() * psi).real
    rng = np.random.default_rng(s["seed"] if seed is None else seed)
    draws = rng.choice(N, size=shots or s["shots"], p=probs / probs.sum())
    uniq, cnt = np.unique(draws, return_counts=True)
    found = int(uniq[np.argmax(cnt)])
    return dict(found=found, success=found in marked, iterations=iters, p_success=round(float(probs[marked].sum()), 4),
                classical_queries=N / 2, qubits=n, shots=int(cnt.sum()),
                counts={int(z): int(c) for z, c in sorted(zip(uniq, cnt), key=lambda t: -t[1])[:5]})


# ═══════════════════════════════ text interfaces (the registered tools) ═══════════════════════════════
def _seed(s, text):
    """Deterministic per-request seed (Python's hash() changes between processes, which would break replay)."""
    return s["seed"] + int(hashlib.sha256(text.encode()).hexdigest(), 16) % 100_000


def _json_in(text):
    for m in re.finditer(r"\{", text):
        depth = 0
        for j in range(m.start(), len(text)):
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            if depth == 0:
                try:
                    return json.loads(text[m.start():j + 1])
                except ValueError:
                    break
    return None


def tool_run(query: str) -> str:
    r = run_qasm(query)
    top = ", ".join(f"{k}: {v}" for k, v in list(r["counts"].items())[:8])
    return (f"COUNTS from {r['shots']} shots on {r['qubits']} qubits ({r['depth']} gates, backend: {r['backend']}): "
            f"{top}\nbitstrings are written with the highest classical bit first (Qiskit convention)")


def tool_qubo(query: str) -> str:
    """Input: JSON {"Q": [[…]], "offset": 0, "labels": […]} or {"linear": {"a": -1}, "quadratic": {"a,b": 2}}."""
    data = _json_in(query)
    if not data:
        return 'no QUBO found: give JSON such as {"Q": [[-1, 2], [2, -1]]} or {"linear": {"a": -1}, "quadratic": {"a,b": 2}}'
    if "Q" in data:
        Q, labels = data["Q"], data.get("labels")
    else:
        names = sorted({v for k in data.get("quadratic", {}) for v in k.split(",")} | set(data.get("linear", {})))
        pos = {v: i for i, v in enumerate(names)}
        np = _np()
        Q = np.zeros((len(names), len(names)))
        for v, w in data.get("linear", {}).items():
            Q[pos[v], pos[v]] += float(w)
        for k, w in data.get("quadratic", {}).items():
            a, b = k.split(",")
            Q[pos[a], pos[b]] += float(w) / 2
            Q[pos[b], pos[a]] += float(w) / 2
        labels = names
    return format_solution(solve_qubo(Q, float(data.get("offset", 0.0)), labels), "selected")


def tool_maxcut(query: str) -> str:
    """Input: edges such as "A-B:3, B-C:1, A-C" (weight 1 when omitted)."""
    edges = [(a, b, float(w) if w else 1.0) for a, b, w in
             re.findall(r"([A-Za-z0-9_]+)\s*[-–]\s*([A-Za-z0-9_]+)(?:\s*:\s*(\d+(?:\.\d+)?))?", query)]
    if not edges:
        return 'no edges found: write them like "A-B:3, B-C:1, A-C"'
    nodes = sorted({v for a, b, _ in edges for v in (a, b)})
    r = solve_qubo(maxcut_qubo(nodes, edges), 0.0, nodes)
    side_b = [v for v in nodes if v not in r["selection"]]
    text = format_solution(r, "group A")
    return text + f"\ngroup B: {', '.join(side_b)} · cut weight {-r['cost']:g} of total {sum(w for *_, w in edges):g}"


def tool_grover(query: str) -> str:
    """Input: "search 16 items for 11" or "n=5 marked 3, 17"."""
    q = query.lower()
    m = re.search(r"n\s*=\s*(\d+)", q)
    if m:
        n = int(m.group(1))
    else:
        size = re.search(r"(\d+)\s*(?:items|entries|records|states)", q)
        n = max(1, math.ceil(math.log2(int(size.group(1))))) if size else 4
    tail = re.split(r"marked|for|target", q, maxsplit=1)
    nums = [int(x) for x in re.findall(r"\d+", tail[1])] if len(tail) > 1 else []
    r = grover(n, nums)
    head = "FOUND" if r["success"] else "NOT FOUND"
    return (f"{head}: item {r['found']} after {r['iterations']} Grover iteration(s) on {n} qubits "
            f"(P(success)={r['p_success']}; a classical search needs about {r['classical_queries']:g} checks on average)\n"
            f"most frequent results: {r['counts']} · backend: simulator (exact state vector)")


def tool_random(query: str) -> str:
    """Input: how many bits ("32 bits"), or "pick 5 of 120" for random sampling without replacement."""
    np = _np()
    s = settings()
    m = re.search(r"pick\s+(\d+)\s+(?:of|from)\s+(\d+)", query.lower())
    if m:
        k, n = int(m.group(1)), int(m.group(2))
        if not 0 < k <= n:
            return "pick k of n needs 0 < k ≤ n"
        q = max(1, math.ceil(math.log2(n)))
        _check_qubits(q, s)
        rng = np.random.default_rng(_seed(s, query))
        chosen, draws = [], 0
        while len(chosen) < k and draws < 100 * k:
            z = int(rng.integers(0, 2 ** q))                  # measuring q qubits in uniform superposition
            draws += 1
            if z < n and z + 1 not in chosen:
                chosen.append(z + 1)
        return (f"SAMPLE: {', '.join(map(str, sorted(chosen)))} (pick {k} of {n}, {q}-qubit uniform superposition, "
                f"rejection sampling) · backend: simulator — for certified randomness use a hardware backend (v0.5)")
    b = re.search(r"(\d+)\s*bits?", query.lower())
    nbits = min(int(b.group(1)) if b else 32, 4096)
    rng = np.random.default_rng(_seed(s, query))
    bits = "".join(map(str, rng.integers(0, 2, nbits)))
    return f"BITS: {bits} ({nbits} bits from qubits in superposition) · backend: simulator (pseudo-random)"


def _guard(fn):
    def run(query):
        try:
            return fn(query)
        except QuantumBlocked as e:
            return f"BLOCKED: {e}"
        except ValueError as e:
            return f"INVALID: {e}"
    run.__doc__ = fn.__doc__
    return run


def register(register_tool):
    """Called by algoruntime at import time (keeps NumPy optional until a quantum tool is used)."""
    register_tool("quantum.run", "Run an OpenQASM 2.0 circuit and return measurement counts")(_guard(tool_run))
    register_tool("quantum.qubo", "Solve a QUBO with QAOA; checked against the exact classical optimum")(_guard(tool_qubo))
    register_tool("quantum.maxcut", "Split a weighted graph (\"A-B:3, B-C:1\") into two groups with QAOA max-cut")(_guard(tool_maxcut))
    register_tool("quantum.grover", "Grover search: \"search 16 items for 11\"")(_guard(tool_grover))
    register_tool("quantum.random", "Random bits (\"64 bits\") or a random sample (\"pick 5 of 120\") from qubits")(_guard(tool_random))
