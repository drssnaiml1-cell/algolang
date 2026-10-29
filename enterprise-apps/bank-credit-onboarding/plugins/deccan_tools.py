"""Deccan Bank tools: credit bureau and sanctions screening.

Company tools for AlgoLang agents. An agent can call a tool only if its program declares it
(`tool name`), the agent lists it (`uses name`), and algo.config.json allows it (policy.allowed_tools).
Each tool receives the agent's request text and returns a short text answer.
"""
import csv
import re
from pathlib import Path

from algoruntime import register_tool

DATA = Path(__file__).resolve().parent.parent / "data"


def _rows(name):
    with open(DATA / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@register_tool("bureau.score", "Credit bureau summary for an applicant id (APP-####)")
def bureau(query: str) -> str:
    m = re.search(r"APP-\d{4}", query)
    if not m:
        return "no applicant id (APP-####) in the request"
    for r in _rows("bureau.csv"):
        if r["applicant"] == m.group(0):
            return (f"{r['applicant']}: score {r['score']}, open loans {r['open_loans']}, "
                    f"monthly EMIs INR {r['emi']}, missed payments (24m) {r['missed_24m']}")
    return f"{m.group(0)}: no bureau record (thin file) — ask for 6 months of bank statements"


@register_tool("sanctions.screen", "Screen a customer name against the bank's sanctions and PEP list")
def sanctions(query: str) -> str:
    names = [r["name"].lower() for r in _rows("watchlist.csv")]
    hits = [n for n in names if n in query.lower()]
    return f"POTENTIAL MATCH: {', '.join(hits)} — hold and refer to compliance" if hits else "no sanctions or PEP match"


def _inr(text):
    return [int(x.replace(",", "")) for x in re.findall(r"INR\s?([\d,]{4,})", text)]


@register_tool("dti.calc", "New EMI (9% p.a.) and debt-to-income ratio for an application (APP-####)")
def dti(query: str) -> str:
    m = re.search(r"APP-\d{4}", query)
    amounts = _inr(query)
    years = re.search(r"(\d+)\s*years?", query)
    income = re.search(r"income INR\s?([\d,]{4,})", query)
    if not (m and amounts and income):
        return "need an applicant id, a loan amount (INR …) and a monthly income (income INR …)"
    principal, monthly = amounts[0], int(income.group(1).replace(",", ""))
    n = 12 * int(years.group(1)) if years else 60
    r = 0.09 / 12
    emi = principal * r * (1 + r) ** n / ((1 + r) ** n - 1)
    existing = next((int(b["emi"]) for b in _rows("bureau.csv") if b["applicant"] == m.group(0)), 0)
    ratio = (emi + existing) / monthly
    flag = "DTI within policy" if ratio <= 0.5 else "DTI ABOVE the 50% policy limit"
    return (f"{flag}: {ratio:.0%} for {m.group(0)} (new EMI INR {emi:,.0f} over {n} months + existing "
            f"EMIs INR {existing:,}, monthly income INR {monthly:,})")
