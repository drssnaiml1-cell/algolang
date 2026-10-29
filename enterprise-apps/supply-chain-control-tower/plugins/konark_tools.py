"""Konark logistics tools: inventory and shipment tracking.

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


@register_tool("inventory.levels", "Stock on hand and days of cover for SKUs named in the request")
def inventory(query: str) -> str:
    hits = [r for r in _rows("inventory.csv") if r["sku"] in query or r["item"].lower() in query.lower()]
    if not hits:
        return "no SKU named in the request"
    return "; ".join(f"{r['sku']}: {r['days_cover']} days of cover ({r['on_hand']} units of {r['item']} at {r['dc']})" for r in hits)


@register_tool("shipment.track", "Status, location and ETA of a shipment (SHP-#####)")
def track(query: str) -> str:
    m = re.search(r"SHP-\d{5}", query)
    if not m:
        return "no shipment id (SHP-#####) in the request"
    for r in _rows("shipments.csv"):
        if r["shipment"] == m.group(0):
            return f"{r['shipment']}: {r['status']} at {r['location']}, ETA {r['eta']}, carrier {r['carrier']}, SKU {r['sku']}"
    return f"{m.group(0)}: not found"
