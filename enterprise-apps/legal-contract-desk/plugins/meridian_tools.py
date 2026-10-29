"""Meridian legal tools: approved clause library.

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


@register_tool("clause.library", "Meridian's approved fallback wording for clauses named in the request")
def clauses(query: str) -> str:
    q = query.lower()
    hits = [r for r in _rows("clause_library.csv") if any(k in q for k in r["keywords"].split("|"))]
    if not hits:
        return "no matching clause in the library — escalate to counsel"
    return "\n".join(f"{r['clause']}: {r['approved']}" for r in hits)
