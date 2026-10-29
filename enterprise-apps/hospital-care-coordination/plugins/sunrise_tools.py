"""Sunrise Hospital tools: live bed board.

Company tools for AlgoLang agents. An agent can call a tool only if its program declares it
(`tool name`), the agent lists it (`uses name`), and algo.config.json allows it (policy.allowed_tools).
Each tool receives the agent's request text and returns a short text answer.
"""
import csv
from pathlib import Path

from algoruntime import register_tool

DATA = Path(__file__).resolve().parent.parent / "data"


def _rows(name):
    with open(DATA / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@register_tool("beds.availability", "Free beds by ward (ICU, HDU, cardiac, general, paediatric)")
def beds(query: str) -> str:
    q = query.lower()
    rows = _rows("beds.csv")
    wanted = [r for r in rows if r["ward"].lower() in q or any(k in q for k in r["keywords"].split("|"))]
    pick = wanted or rows
    return "; ".join(f"{r['ward']}: {int(r['total']) - int(r['occupied'])} free of {r['total']}" for r in pick)
