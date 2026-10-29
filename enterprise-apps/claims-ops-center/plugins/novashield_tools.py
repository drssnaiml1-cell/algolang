"""NovaShield claims tools: policy database and payout calculator.

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


@register_tool("policydb.lookup", "Look up a motor or home policy by its number (NS-12345)")
def policy_lookup(query: str) -> str:
    m = re.search(r"NS-\d{5}", query)
    if not m:
        return "no policy number (NS-#####) found in the claim"
    for r in _rows("policies.csv"):
        if r["policy_no"] == m.group(0):
            return (f"{r['policy_no']}: {r['product']} cover, sum insured INR {r['sum_insured']}, "
                    f"deductible INR {r['deductible']}, status {r['status']}, renewal {r['renewal']}")
    return f"{m.group(0)}: policy not found — route to Policy Services"


@register_tool("payout.estimate", "Estimate payout = claimed amount − deductible, capped at sum insured")
def payout_estimate(query: str) -> str:
    amounts = [int(a.replace(",", "")) for a in re.findall(r"INR\s?([\d,]{3,})", query)]
    m = re.search(r"NS-\d{5}", query)
    pol = next((r for r in _rows("policies.csv") if m and r["policy_no"] == m.group(0)), None)
    if not amounts or not pol:
        return "need a claimed amount (INR …) and a policy number to estimate the payout"
    claimed = amounts[0]
    payout = max(0, min(claimed - int(pol["deductible"]), int(pol["sum_insured"])))
    return f"estimated payout INR {payout:,} (claimed INR {claimed:,} − deductible INR {int(pol['deductible']):,})"
