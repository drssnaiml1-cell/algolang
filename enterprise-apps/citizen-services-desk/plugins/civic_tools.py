"""Citizen services tools: ward and department directory.

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


@register_tool("ward.directory", "Department, officer desk and service-level target for a ward and issue")
def ward(query: str) -> str:
    q = query.lower()
    m = re.search(r"ward\s*(\d+)", q)
    rows = [r for r in _rows("departments.csv") if any(k in q for k in r["keywords"].split("|"))]
    dept = rows[0] if rows else None
    where = f"ward {m.group(1)}" if m else "ward not stated"
    if not dept:
        return f"{where}: issue type not recognised — send to the Citizen Facilitation Centre"
    return f"{where}: {dept['department']} — {dept['desk']}, target {dept['sla_hours']} hours"
