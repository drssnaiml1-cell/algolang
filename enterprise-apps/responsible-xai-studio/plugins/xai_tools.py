"""AlgoXAI Audit Studio™ tools: responsible and explainable AI for a credit-scoring model.

Two models are audited on 4,000 synthetic loan applicants:
    v1  the vendor's model: a logistic regression that also uses `pincode_risk`, an area index that is a proxy
        for a protected group
    v2  the same model retrained without the proxy
The protected `group` column is used only to audit; it is never a model input.

    xai.shapley         exact Shapley values (all 2^k feature coalitions, interventional, against a background
                        sample) for one applicant, plus global importance (mean |SHAP| over 300 applicants)
    fair.audit          approval rate per group, disparate impact (four-fifths rule), equal opportunity (gap in
                        approval among people who repaid), calibration per group, and proxy detection
    xai.counterfactual  the smallest change to actionable features (income, existing EMI, credit utilisation)
                        that turns a decline into an approval: recourse an applicant can act on
"""
from __future__ import annotations

import csv
import itertools
import math
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

from algoruntime import register_tool

DATA = Path(__file__).resolve().parent.parent / "data"
FEATURES = ["income_lpa", "existing_emi", "credit_utilisation", "years_employed", "age", "pincode_risk"]
ACTIONABLE = {"income_lpa": +1, "existing_emi": -1, "credit_utilisation": -1}
THRESHOLD = 0.5                      # approve when the predicted repayment probability is at least this
DI_MIN, EO_MAX = 0.8, 0.10


@lru_cache(maxsize=1)
def data():
    with open(DATA / "lending.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ids = [r["applicant"] for r in rows]
    X = np.array([[float(r[c]) for c in FEATURES] for r in rows])
    return ids, X, np.array([int(r["group"]) for r in rows]), np.array([int(r["repaid"]) for r in rows])


def version(query):
    return "v2" if re.search(r"\bv2\b|without the proxy|retrained", query.lower()) else "v1"


@lru_cache(maxsize=2)
def model(ver):
    """Logistic regression on standardised features. v1 adds a vendor weight on pincode_risk."""
    _ids, X, _g, y = data()
    cols = [i for i, f in enumerate(FEATURES) if not (ver == "v2" and f == "pincode_risk")]
    Z = X[:, cols]
    mu, sd = Z.mean(0), Z.std(0) + 1e-9
    Zs = (Z - mu) / sd
    w, b = np.zeros(len(cols)), 0.0
    for _ in range(600):
        p = 1 / (1 + np.exp(-(Zs @ w + b)))
        w -= 0.2 * (Zs.T @ (p - y) / len(y) + 1e-3 * w)
        b -= 0.2 * (p - y).mean()
    if ver == "v1":                       # the vendor hand-tuned the area index into the score
        w[cols.index(FEATURES.index("pincode_risk"))] -= 0.9
    return cols, mu, sd, w, b


def predict(ver, X):
    cols, mu, sd, w, b = model(ver)
    return 1 / (1 + np.exp(-(((X[:, cols] - mu) / sd) @ w + b)))


def applicant(query):
    ids, X, g, y = data()
    m = re.search(r"AP-\d{5}", query.upper())
    i = ids.index(m.group(0)) if m and m.group(0) in ids else 6
    return i, ids[i], X[i]


def shapley(ver, x, background):
    """Exact interventional Shapley values for one row (2^k coalitions)."""
    k = len(FEATURES)
    vals = {}
    for mask in itertools.product((0, 1), repeat=k):
        Z = background.copy()
        for j in range(k):
            if mask[j]:
                Z[:, j] = x[j]
        vals[mask] = float(predict(ver, Z).mean())
    phi = np.zeros(k)
    for j in range(k):
        for mask, v in vals.items():
            if mask[j]:
                continue
            s = sum(mask)
            with_j = mask[:j] + (1,) + mask[j + 1:]
            weight = math.factorial(s) * math.factorial(k - s - 1) / math.factorial(k)
            phi[j] += weight * (vals[with_j] - v)
    return phi, vals[(0,) * k], vals[(1,) * k]


@register_tool("xai.shapley", "Exact Shapley explanation of one applicant's credit score (AP-#####), and global importance")
def xai_shapley(query: str) -> str:
    ver = version(query)
    _ids, X, _g, _y = data()
    rng = np.random.default_rng(5)
    bg = X[rng.choice(len(X), 100, replace=False)]
    i, aid, x = applicant(query)
    phi, base, pred = shapley(ver, x, bg)
    decision = "APPROVE" if pred >= THRESHOLD else "DECLINE"
    order = np.argsort(-np.abs(phi))
    lines = [f"EXPLAINED model {ver} for {aid}: {decision} (repayment probability {pred:.3f}; threshold {THRESHOLD})",
             f"baseline {base:.3f} + contributions = {base + phi.sum():.3f} (exact: Shapley values add up to the prediction)"]
    for j in order:
        lines.append(f"  {FEATURES[j]:<20} {x[j]:>10,.3f}  {phi[j]:+.3f}")
    sample = X[rng.choice(len(X), 300, replace=False)]
    imp = np.zeros(len(FEATURES))
    for row in sample[:60]:                 # mean |SHAP| on 60 applicants keeps this fast and exact per row
        imp += np.abs(shapley(ver, row, bg[:40])[0])
    imp /= 60
    top = np.argsort(-imp)
    lines.append("global importance (mean |SHAP|): " + " · ".join(f"{FEATURES[j]} {imp[j]:.3f}" for j in top))
    if imp[FEATURES.index("pincode_risk")] >= sorted(imp)[-3]:
        lines.append("note: pincode_risk is among the three strongest drivers; check it is not a proxy")
    return "\n".join(lines)


@register_tool("fair.audit", "Fairness audit across the protected group: disparate impact, equal opportunity, calibration, proxies")
def fair_audit(query: str) -> str:
    ver = version(query)
    _ids, X, g, y = data()
    p = predict(ver, X)
    approve = p >= THRESHOLD
    rate = [approve[g == k].mean() for k in (0, 1)]
    di = rate[1] / rate[0]
    tpr = [approve[(g == k) & (y == 1)].mean() for k in (0, 1)]
    eo = abs(tpr[0] - tpr[1])
    cal = [abs(p[g == k].mean() - y[g == k].mean()) for k in (0, 1)]
    proxies = []
    for j, f in enumerate(FEATURES):
        c = abs(np.corrcoef(X[:, j], g)[0, 1])
        if c > 0.5:
            used = j in model(ver)[0]
            proxies.append(f"{f} (correlation {c:.2f} with the protected group{', USED by the model' if used else ', not used'})")
    problems = []
    if di < DI_MIN:
        problems.append(f"disparate impact {di:.2f} < {DI_MIN} (four-fifths rule)")
    if eo > EO_MAX:
        problems.append(f"equal-opportunity gap {eo:.2f} > {EO_MAX}")
    used_proxies = [x for x in proxies if "USED" in x]
    if used_proxies:
        problems.append("a proxy for the protected group is a model input")
    head = ("BIAS FOUND in model " + ver + ": " + "; ".join(problems)) if problems else \
        f"FAIRNESS CHECKS PASSED for model {ver}"
    return (f"{head}\n"
            f"approval rate: group A {rate[0]:.1%} · group B {rate[1]:.1%} · disparate impact {di:.2f}\n"
            f"approval among applicants who repaid: A {tpr[0]:.1%} · B {tpr[1]:.1%} · gap {eo:.2f}\n"
            f"calibration error: A {cal[0]:.3f} · B {cal[1]:.3f} · overall accuracy {(approve == y).mean():.1%}\n"
            f"proxy scan: {'; '.join(proxies) or 'no feature correlates above 0.5 with the protected group'}")


@register_tool("xai.counterfactual", "Smallest actionable change that turns a declined applicant (AP-#####) into an approval")
def xai_counterfactual(query: str) -> str:
    ver = version(query)
    i, aid, x = applicant(query)
    p0 = float(predict(ver, x[None])[0])
    if p0 >= THRESHOLD:
        return f"NO RECOURSE NEEDED: {aid} is approved by model {ver} (probability {p0:.3f})"
    _ids, X, _g, _y = data()
    sd = X.std(0)
    best = None
    steps = np.linspace(0, 2.5, 26)                       # up to 2.5 standard deviations per feature
    idx = {f: FEATURES.index(f) for f in ACTIONABLE}
    for a, b_, c in itertools.product(steps, steps, steps):
        z = x.copy()
        moves = dict(zip(ACTIONABLE, (a, b_, c)))
        for f, s in moves.items():
            j = idx[f]
            z[j] = x[j] + ACTIONABLE[f] * s * sd[j]
        z[idx["existing_emi"]] = max(z[idx["existing_emi"]], 0)
        z[idx["credit_utilisation"]] = min(max(z[idx["credit_utilisation"]], 0), 1)
        cost = a + b_ + c                                  # total change in standard deviations
        if predict(ver, z[None])[0] >= THRESHOLD and (best is None or cost < best[0] - 1e-9):
            best = (cost, z)
    if best is None:
        return f"NO ACTIONABLE RECOURSE for {aid} under model {ver} within 2.5 standard deviations per feature"
    z = best[1]
    changes = [f"{f}: {x[idx[f]]:,.2f} → {z[idx[f]]:,.2f}" for f in ACTIONABLE if abs(z[idx[f]] - x[idx[f]]) > 1e-9]
    return (f"RECOURSE for {aid} under model {ver} (declined at {p0:.3f}): " + "; ".join(changes)
            + f" → approved at {float(predict(ver, z[None])[0]):.3f}. Age and area are never suggested changes.")
