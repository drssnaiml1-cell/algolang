"""AlgoML Model Factory™ tools: real machine learning and deep learning, written with NumPy only.

    data.profile   rows, class balance, missing values and target leakage (a feature that predicts the label
                   almost perfectly is a leak, not a signal)
    ml.train       one model family with stratified 5-fold cross-validation: logistic regression, a deep
                   neural network (2 hidden layers, ReLU, Adam, early stopping) or gradient-boosted trees
    ml.compare     all three families on the same folds; the champion has the best AUC among models whose
                   calibration error is within limits
    ml.drift       population stability index (PSI) of each feature, training data vs a production week

All data is synthetic (data/*.csv), generated from a known ground truth so results can be checked.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

from algoruntime import register_tool

DATA = Path(__file__).resolve().parent.parent / "data"
LABEL = "churned"
SEED = 7
MAX_ECE = 0.05                      # calibration limit for a champion
PSI_ALERT = 0.2                     # population stability: > 0.2 is a material shift


# ───────────────────────────── data ─────────────────────────────
@lru_cache(maxsize=8)
def load(name="customers.csv"):
    with open(DATA / name, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cols = list(rows[0])
    arr = {c: np.array([float(r[c]) if r[c] != "" else np.nan for r in rows]) for c in cols}
    return cols, arr


def dataset_of(query):
    q = query.lower()
    if "refund" in q:
        return "customers_with_refunds.csv"
    return "customers.csv"


def matrix(name):
    cols, arr = load(name)
    feats = [c for c in cols if c != LABEL]
    X = np.column_stack([arr[c] for c in feats])
    y = arr[LABEL].astype(int)
    return feats, X, y


def folds(y, k=5, seed=SEED):
    """Stratified k-fold indices."""
    rng = np.random.default_rng(seed)
    out = [[] for _ in range(k)]
    for cls in (0, 1):
        idx = np.where(y == cls)[0]
        rng.shuffle(idx)
        for i, j in enumerate(idx):
            out[i % k].append(j)
    return [np.array(sorted(f)) for f in out]


# ───────────────────────────── metrics ─────────────────────────────
def auc(y, p):
    """Area under the ROC curve (Mann–Whitney U, ties averaged)."""
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p))
    sp = p[order]
    i = 0
    while i < len(sp):
        j = i
        while j + 1 < len(sp) and sp[j + 1] == sp[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    pos = y == 1
    n1, n0 = pos.sum(), (~pos).sum()
    return float((ranks[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def ece(y, p, bins=10):
    """Expected calibration error."""
    edges = np.linspace(0, 1, bins + 1)
    e = 0.0
    for a, b in zip(edges[:-1], edges[1:]):
        m = (p >= a) & (p < b if b < 1 else p <= b)
        if m.any():
            e += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(e)


# ───────────────────────────── models ─────────────────────────────
def _std(Xtr, Xte):
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
    return (Xtr - mu) / sd, (Xte - mu) / sd


def _sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def logistic(Xtr, ytr, Xte, epochs=400, lr=0.1, l2=1e-3):
    Xtr, Xte = _std(Xtr, Xte)
    w, b = np.zeros(Xtr.shape[1]), 0.0
    for _ in range(epochs):
        p = _sigmoid(Xtr @ w + b)
        g = p - ytr
        w -= lr * (Xtr.T @ g / len(ytr) + l2 * w)
        b -= lr * g.mean()
    return _sigmoid(Xte @ w + b)


def deep_net(Xtr, ytr, Xte, hidden=(32, 16), epochs=60, lr=3e-3, batch=128, seed=SEED):
    """A deep neural network: 2 hidden ReLU layers, He initialisation, Adam, early stopping on 10% of the data."""
    Xtr, Xte = _std(Xtr, Xte)
    rng = np.random.default_rng(seed)
    n = len(ytr)
    val = rng.choice(n, n // 10, replace=False)
    trn = np.setdiff1d(np.arange(n), val)
    sizes = [Xtr.shape[1], *hidden, 1]
    W = [rng.normal(0, np.sqrt(2 / a), (a, b)) for a, b in zip(sizes[:-1], sizes[1:])]
    B = [np.zeros(b) for b in sizes[1:]]
    params = W + B
    m = [np.zeros_like(p) for p in params]
    v = [np.zeros_like(p) for p in params]
    t = 0

    def forward(X):
        acts = [X]
        for i in range(len(W) - 1):
            acts.append(np.maximum(0, acts[-1] @ W[i] + B[i]))
        return acts, _sigmoid(acts[-1] @ W[-1] + B[-1]).ravel()

    def loss(X, y):
        _, p = forward(X)
        p = np.clip(p, 1e-7, 1 - 1e-7)
        return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())
    best, best_params, patience = np.inf, None, 0
    for _epoch in range(epochs):
        rng.shuffle(trn)
        for s in range(0, len(trn), batch):
            idx = trn[s:s + batch]
            acts, p = forward(Xtr[idx])
            delta = (p - ytr[idx])[:, None] / len(idx)
            gW, gB = [None] * len(W), [None] * len(B)
            for i in range(len(W) - 1, -1, -1):
                gW[i] = acts[i].T @ delta
                gB[i] = delta.sum(0)
                if i:
                    delta = (delta @ W[i].T) * (acts[i] > 0)
            t += 1
            for j, (p_, g) in enumerate(zip(params, gW + gB)):
                m[j] = 0.9 * m[j] + 0.1 * g
                v[j] = 0.999 * v[j] + 0.001 * g * g
                p_ -= lr * (m[j] / (1 - 0.9 ** t)) / (np.sqrt(v[j] / (1 - 0.999 ** t)) + 1e-8)
        vl = loss(Xtr[val], ytr[val])
        if vl < best - 1e-5:
            best, best_params, patience = vl, [p.copy() for p in params], 0
        else:
            patience += 1
            if patience >= 6:
                break
    for p_, b_ in zip(params, best_params):
        p_[...] = b_
    return forward(Xte)[1]


def boosted_trees(Xtr, ytr, Xte, rounds=120, lr=0.15, depth=2, bins=16):
    """Gradient-boosted decision trees (logistic loss, depth-2 trees on quantile bins)."""
    qs = [np.unique(np.quantile(Xtr[:, j], np.linspace(0, 1, bins + 1)[1:-1])) for j in range(Xtr.shape[1])]
    f0 = np.log(ytr.mean() / (1 - ytr.mean()))
    Ftr, Fte = np.full(len(ytr), f0), np.full(len(Xte), f0)

    def best_split(X, g, h, idx):
        best = (0.0, None)
        G, H = g[idx].sum(), h[idx].sum()
        for j in range(X.shape[1]):
            for thr in qs[j]:
                left = idx[X[idx, j] <= thr]
                if len(left) < 20 or len(left) > len(idx) - 20:
                    continue
                gl, hl = g[left].sum(), h[left].sum()
                gain = gl * gl / (hl + 1) + (G - gl) ** 2 / (H - hl + 1) - G * G / (H + 1)
                if gain > best[0]:
                    best = (gain, (j, thr))
        return best[1]

    def grow(X, g, h, idx, d):
        split = best_split(X, g, h, idx) if d < depth else None
        if split is None:
            return ("leaf", -g[idx].sum() / (h[idx].sum() + 1))
        j, thr = split
        return ("node", j, thr, grow(X, g, h, idx[X[idx, j] <= thr], d + 1), grow(X, g, h, idx[X[idx, j] > thr], d + 1))

    def predict(tree, X):
        if tree[0] == "leaf":
            return np.full(len(X), tree[1])
        _, j, thr, a, b = tree
        out = np.empty(len(X))
        m = X[:, j] <= thr
        out[m], out[~m] = predict(a, X[m]), predict(b, X[~m])
        return out
    all_idx = np.arange(len(ytr))
    for _ in range(rounds):
        p = _sigmoid(Ftr)
        g, h = p - ytr, p * (1 - p)
        tree = grow(Xtr, g, h, all_idx, 0)
        Ftr += lr * predict(tree, Xtr)
        Fte += lr * predict(tree, Xte)
    return _sigmoid(Fte)


FAMILIES = {"logistic": ("logistic regression", logistic), "deep": ("deep neural network (32-16, Adam)", deep_net),
            "boosted": ("gradient-boosted trees (120 × depth 2)", boosted_trees)}


def family_of(query):
    q = query.lower()
    if "deep" in q or "neural" in q or "mlp" in q:
        return "deep"
    if "boost" in q or "tree" in q or "gbm" in q:
        return "boosted"
    return "logistic"


@lru_cache(maxsize=16)
def cross_validate(family, name="customers.csv"):
    _feats, X, y = matrix(name)
    fn = FAMILIES[family][1]
    aucs, eces, accs = [], [], []
    oof = np.zeros(len(y))
    for f in folds(y):
        tr = np.setdiff1d(np.arange(len(y)), f)
        p = fn(X[tr], y[tr], X[f])
        oof[f] = p
        aucs.append(auc(y[f], p))
        eces.append(ece(y[f], p))
        accs.append(float(((p >= 0.5) == y[f]).mean()))
    return dict(family=family, label=FAMILIES[family][0], auc=float(np.mean(aucs)), auc_sd=float(np.std(aucs)),
                ece=float(np.mean(eces)), acc=float(np.mean(accs)), n=len(y), oof=oof)


# ───────────────────────────── tools ─────────────────────────────
@register_tool("data.profile", "Profile a training dataset: rows, class balance, missing values, target leakage")
def data_profile(query: str) -> str:
    name = dataset_of(query)
    feats, X, y = matrix(name)
    miss = int(np.isnan(X).sum())
    leaks = []
    for j, f in enumerate(feats):
        a = auc(y, X[:, j])
        if max(a, 1 - a) > 0.97:
            leaks.append(f"{f} (AUC {max(a, 1 - a):.3f} on its own)")
    head = (f"LEAKAGE in {name}: " + ", ".join(leaks) + " predicts the label almost perfectly; remove it before training"
            if leaks else f"CLEAN dataset {name}")
    return (f"{head}\n{len(y):,} rows · {len(feats)} features ({', '.join(feats)}) · churn rate {y.mean():.1%} · "
            f"{miss} missing values")


@register_tool("ml.train", "Train one model family with stratified 5-fold cross-validation (logistic, deep network, boosted trees)")
def ml_train(query: str) -> str:
    fam = family_of(query)
    r = cross_validate(fam, dataset_of(query))
    return (f"TRAINED {r['label']}: AUC {r['auc']:.3f} ± {r['auc_sd']:.3f} · accuracy {r['acc']:.1%} · "
            f"calibration error {r['ece']:.3f} · 5-fold stratified CV on {r['n']:,} rows (seed {SEED})")


@register_tool("ml.compare", "Compare all model families on the same folds and choose a calibrated champion")
def ml_compare(query: str) -> str:
    name = dataset_of(query)
    rs = [cross_validate(f, name) for f in FAMILIES]
    ok = [r for r in rs if r["ece"] <= MAX_ECE]
    champ = max(ok or rs, key=lambda r: r["auc"])
    lines = [f"CHAMPION {champ['label']}: AUC {champ['auc']:.3f}, calibration error {champ['ece']:.3f}"
             + ("" if ok else f" (no model met the calibration limit {MAX_ECE})")]
    for r in sorted(rs, key=lambda r: -r["auc"]):
        lines.append(f"  {r['label']:<40} AUC {r['auc']:.3f} ± {r['auc_sd']:.3f}  ECE {r['ece']:.3f}  "
                     f"accuracy {r['acc']:.1%}{'' if r['ece'] <= MAX_ECE else '  (not calibrated)'}")
    base = rs[0]
    lines.append(f"lift over logistic regression: {champ['auc'] - base['auc']:+.3f} AUC · same folds, same seed")
    return "\n".join(lines)


def psi(a, b, bins=10):
    edges = np.unique(np.quantile(a, np.linspace(0, 1, bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    pa = np.histogram(a, edges)[0] / len(a) + 1e-6
    pb = np.histogram(b, edges)[0] / len(b) + 1e-6
    return float(((pb - pa) * np.log(pb / pa)).sum())


@register_tool("ml.drift", "Population stability index of every feature: training data vs a production week (WEEK-nn)")
def ml_drift(query: str) -> str:
    m = re.search(r"week[- ]?(\d+)", query.lower())
    week = m.group(1) if m else "45"
    path = f"production_week{week}.csv"
    if not (DATA / path).exists():
        return f"no production data for week {week}"
    feats, X, _ = matrix("customers.csv")
    _, P, _ = matrix(path)
    scores = sorted(((psi(X[:, j], P[:, j]), f) for j, f in enumerate(feats)), reverse=True)
    bad = [(s, f) for s, f in scores if s > PSI_ALERT]
    head = (f"DRIFT DETECTED in week {week}: " + ", ".join(f"{f} (PSI {s:.2f})" for s, f in bad) if bad
            else f"STABLE in week {week}: every feature PSI ≤ {PSI_ALERT}")
    return head + "\n" + " · ".join(f"{f} {s:.3f}" for s, f in scores)
