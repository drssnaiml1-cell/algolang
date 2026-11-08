"""QuantOracle desk tools: backtest statistics, option-chain quotes, risk limits and the trading book.

All data in data/ is synthetic and for demonstration only. In production these tools would call the
backtesting engine, the broker's market-data API and the risk system; the agents and governance stay the same.
"""
import csv
import re
from pathlib import Path

from algoruntime import register_tool

DATA = Path(__file__).resolve().parent.parent / "data"


def _rows(name):
    with open(DATA / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@register_tool("backtest.stats", "Backtest statistics for a strategy id (STR-###)")
def backtest(query: str) -> str:
    m = re.search(r"STR-\d{3}", query)
    if not m:
        return "no strategy id (STR-###) in the request"
    for r in _rows("backtests.csv"):
        if r["strategy"] == m.group(0):
            flag = "PASSES" if float(r["max_drawdown_pct"]) <= 15 and float(r["profit_factor"]) >= 1.3 else "FAILS"
            return (f"{flag} desk thresholds: {r['strategy']} {r['name']} on {r['underlying']} {r['period']}: "
                    f"{r['trades']} trades, win rate {r['win_rate']}%, profit factor {r['profit_factor']}, "
                    f"max drawdown {r['max_drawdown_pct']}%, Sharpe {r['sharpe']}, worst day INR {r['worst_day']}")
    return f"{m.group(0)}: no backtest on record — run one before review"


@register_tool("market.quote", "Last price, IV and open interest for an option (e.g. NIFTY 24500 CE)")
def quote(query: str) -> str:
    m = re.search(r"(NIFTY|BANKNIFTY)\s+(\d{5})\s*(CE|PE)", query.upper())
    if not m:
        return "no option (e.g. NIFTY 24500 CE) in the request"
    for r in _rows("option_chain.csv"):
        if (r["underlying"], r["strike"], r["type"]) == m.groups():
            return (f"{m.group(1)} {m.group(2)} {m.group(3)} weekly: LTP {r['ltp']}, IV {r['iv']}%, OI {r['oi']}, "
                    f"lot size {r['lot_size']}, spot {r['spot']}")
    return f"{' '.join(m.groups())}: not in today's chain"


@register_tool("risk.limits", "Check an order (N lots, strategy STR-###) against the desk's risk limits")
def limits(query: str) -> str:
    lots = re.search(r"(\d+)\s*lots?", query.lower())
    strat = re.search(r"STR-\d{3}", query)
    lim = {r["limit"]: float(r["value"]) for r in _rows("risk_limits.csv")}
    book = _rows("positions.csv")
    open_lots = sum(int(p["lots"]) for p in book)
    day_pnl = sum(float(p["pnl"]) for p in book)
    n = int(lots.group(1)) if lots else 0
    approved = {r["strategy"] for r in _rows("backtests.csv") if r["status"] == "paper-approved"}
    problems = []
    if n > lim["max_lots_per_order"]:
        problems.append(f"{n} lots > per-order limit {lim['max_lots_per_order']:.0f}")
    if open_lots + n > lim["max_open_lots"]:
        problems.append(f"open lots would be {open_lots + n} > limit {lim['max_open_lots']:.0f}")
    if day_pnl <= -lim["max_daily_loss_inr"]:
        problems.append(f"daily loss INR {-day_pnl:,.0f} hit the limit — trading halted")
    if not strat or strat.group(0) not in approved:
        problems.append("strategy is not approved for paper trading")
    head = "BREACH: " + "; ".join(problems) if problems else "WITHIN LIMITS"
    return f"{head} (open lots {open_lots}, day P&L INR {day_pnl:,.0f}, order {n} lots)"


@register_tool("book.positions", "The desk's open positions and P&L")
def positions(query: str) -> str:
    rows = _rows("positions.csv")
    total = sum(float(p["pnl"]) for p in rows)
    lines = [f"{p['instrument']} {p['side']} {p['lots']} lots ({p['strategy']}) P&L INR {float(p['pnl']):,.0f}" for p in rows]
    return f"day P&L INR {total:,.0f}; " + "; ".join(lines)
