"""Helix SOC tools: CMDB and indicator-of-compromise lookups.

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


@register_tool("cmdb.lookup", "Owner, tier and dependencies of a host or service named in the request")
def cmdb(query: str) -> str:
    q = query.lower()
    hits = [r for r in _rows("cmdb.csv") if r["asset"].lower() in q]
    if not hits:
        return "no CMDB asset named in the request"
    return "; ".join(f"{r['asset']}: tier {r['tier']}, owner {r['owner']}, depends on {r['depends_on']}" for r in hits)


@register_tool("ioc.check", "Check IPs, domains and hashes against the threat-intel blocklist")
def ioc(query: str) -> str:
    found = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b|[a-z0-9-]+\.(?:ru|xyz|top|biz)\b", query.lower())
    bad = {r["indicator"]: r["note"] for r in _rows("iocs.csv")}
    if not found:
        return "no indicators found in the request"
    return "; ".join(f"{i}: {'KNOWN BAD — ' + bad[i] if i in bad else 'not on blocklist'}" for i in found)
