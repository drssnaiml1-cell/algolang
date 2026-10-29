"""University tools: programme seat matrix.

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


@register_tool("seats.lookup", "Seats and cut-offs for a programme (B.Tech AI&DS, CSE, ECE, M.Tech AI)")
def seats(query: str) -> str:
    q = query.lower()
    rows = [r for r in _rows("seat_matrix.csv") if any(k in q for k in r["keywords"].split("|"))]
    if not rows:
        return "programme not recognised — list: " + ", ".join(r["programme"] for r in _rows("seat_matrix.csv"))
    return "; ".join(f"{r['programme']}: {r['filled']}/{r['intake']} filled, merit cut-off {r['cutoff']}" for r in rows)
