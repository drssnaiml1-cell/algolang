"""Quantum Optimization Lab tools: the asset universe, a QAOA portfolio optimiser and the plant's job clashes.

Data in data/ is synthetic. In production, market.universe would call the market-data service and
ops.clashes the plant scheduling system; the quantum solver and the governance stay the same.
"""
import csv
import re
from pathlib import Path

import algoquantum as aq
from algoruntime import register_tool

DATA = Path(__file__).resolve().parent.parent / "data"


def _rows(name):
    with open(DATA / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _universe(query):
    rows = _rows("assets.csv")
    if not re.search(r"mid[- ]?caps?", query.lower()):
        rows = [r for r in rows if r["tier"] == "large"]
    return rows


@register_tool("market.universe", "Eligible assets with expected return and volatility (large caps; say 'mid-caps' to include them)")
def universe(query: str) -> str:
    rows = _universe(query)
    return f"{len(rows)} eligible assets: " + "; ".join(
        f"{r['symbol']} ({r['sector']}) return {r['expected_return_pct']}% vol {r['volatility_pct']}%" for r in rows)


@register_tool("quantum.portfolio", "Choose k assets with QAOA (mean–variance with a cardinality constraint), verified exactly")
def portfolio(query: str) -> str:
    q = query.lower()
    k = re.search(r"choose\s+(\d+)", q) or re.search(r"(\d+)\s+(?:of the|assets)", q)
    lam = re.search(r"risk aversion\s+(\d+(?:\.\d+)?)", q)
    rows = _universe(query)
    k = int(k.group(1)) if k else 4
    lam = float(lam.group(1)) if lam else 0.5
    if not 0 < k < len(rows):
        return f"INVALID: cannot choose {k} of {len(rows)} assets"
    mu = [float(r["expected_return_pct"]) / 100 for r in rows]
    var = [(float(r["volatility_pct"]) / 100) ** 2 for r in rows]
    try:
        Q, off = aq.portfolio_qubo(mu, var, k, risk_aversion=lam)
        r = aq.solve_qubo(Q, off, [x["symbol"] for x in rows])
    except aq.QuantumBlocked as e:
        return f"BLOCKED: {e} — the universe has {len(rows)} assets, one qubit each"
    pick = [x for x in rows if x["symbol"] in r["selection"]]
    ret = sum(float(x["expected_return_pct"]) for x in pick) / max(len(pick), 1)
    vol = sum(float(x["volatility_pct"]) for x in pick) / max(len(pick), 1)
    sectors = sorted({x["sector"] for x in pick})
    text = aq.format_solution(r, "portfolio")
    feasible = "" if len(pick) == k else f"\nWARNING: {len(pick)} assets chosen, {k} requested"
    return (text + f"\nequal-weight expected return {ret:.1f}% · average volatility {vol:.1f}% · "
            f"sectors: {', '.join(sectors)} · risk aversion {lam}{feasible}")


@register_tool("ops.clashes", "Pairs of plant jobs that clash, with weights, as edges for max-cut")
def clashes(query: str) -> str:
    rows = _rows("shift_clashes.csv")
    edges = ", ".join(f"{r['job_a']}-{r['job_b']}:{r['clash_weight']}" for r in rows)
    reasons = "; ".join(f"{r['job_a']}/{r['job_b']} {r['reason']}" for r in rows)
    return f"clash graph edges: {edges}\nreasons: {reasons}"
