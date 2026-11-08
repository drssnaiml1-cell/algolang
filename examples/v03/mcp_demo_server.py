"""A small MCP server for AlgoLang examples and tests (stdio, no dependencies).

    python examples/v03/mcp_demo_server.py   # speaks MCP JSON-RPC on stdin/stdout

Tools:
    search_policies(query)            search a tiny built-in company policy handbook
    exchange_rate(base, quote)        fixed demo exchange rates (not live market data)
    convert_to_inr(text)              find "USD 300"-style amounts in a text and convert them at demo rates
    word_count(text)                  count words and characters

Use it from AlgoLang (see examples/v03/algo.config.json):
    tool kb.search_policies from mcp "company-kb"
"""
import json
import re
import sys

POLICIES = {
    "Refunds": "Customers may request a refund within 30 days. Refunds above INR 50,000 need manager approval.",
    "Travel": "Economy class for flights under 6 hours. Hotels up to INR 8,000 per night in metro cities.",
    "Data protection": "Personal data is kept for 7 years and is never shared without consent.",
    "Remote work": "Staff may work remotely up to 3 days a week with their manager's agreement.",
    "Procurement": "Purchases above INR 2,00,000 need three quotations and approval from finance.",
}
RATES = {("USD", "INR"): 84.0, ("EUR", "INR"): 91.0, ("GBP", "INR"): 107.0, ("USD", "EUR"): 0.92}

TOOLS = [
    {"name": "search_policies", "description": "Search the company policy handbook",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "what to look for"}},
                     "required": ["query"]}},
    {"name": "exchange_rate", "description": "Demo exchange rate between two currencies (fixed, not live)",
     "inputSchema": {"type": "object", "properties": {"base": {"type": "string"}, "quote": {"type": "string"}},
                     "required": ["base", "quote"]}},
    {"name": "convert_to_inr", "description": "Find amounts like 'USD 300' or 'EUR 45.50' in a text and convert them to INR at demo rates",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "word_count", "description": "Count the words and characters in a text",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
]


def run(name, args):
    if name == "search_policies":
        words = set(re.findall(r"[a-z]{3,}", str(args.get("query", "")).lower()))
        scored = sorted(((len(words & set(re.findall(r"[a-z]{3,}", (t + " " + p).lower()))), t, p)
                         for t, p in POLICIES.items()), reverse=True)
        hits = [f"{t}: {p}" for n, t, p in scored if n]
        return "\n".join(hits[:3]) or "no matching policy"
    if name == "convert_to_inr":
        found = re.findall(r"\b(USD|EUR|GBP)\s?([\d,]+(?:\.\d+)?)", str(args.get("text", "")).upper())
        if not found:
            return "no foreign-currency amount found; amounts are already in INR"
        return "; ".join(f"{cur} {amt} = INR {float(amt.replace(',', '')) * RATES[(cur, 'INR')]:,.2f} (demo rate)"
                         for cur, amt in found)
    if name == "exchange_rate":
        b, q = str(args.get("base", "")).upper(), str(args.get("quote", "")).upper()
        if (b, q) in RATES:
            return f"1 {b} = {RATES[(b, q)]} {q} (demo rate)"
        if (q, b) in RATES:
            return f"1 {b} = {round(1 / RATES[(q, b)], 6)} {q} (demo rate)"
        raise ValueError(f"no demo rate for {b}/{q}")
    if name == "word_count":
        t = str(args.get("text", ""))
        return f"{len(t.split())} words, {len(t)} characters"
    raise KeyError(name)


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:                       # a notification: no reply
        return None
    if method == "initialize":
        result = {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "algolang-demo-kb", "version": "1.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params", {})
        try:
            result = {"content": [{"type": "text", "text": run(p.get("name"), p.get("arguments") or {})}]}
        except Exception as e:  # noqa
            result = {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            reply = handle(json.loads(line))
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
