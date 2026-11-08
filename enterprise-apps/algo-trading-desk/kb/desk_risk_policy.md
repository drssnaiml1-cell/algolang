# QuantOracle desk risk and conduct policy (example)

A strategy may go to paper trading only if its backtest shows a profit factor of at least 1.3 and a maximum drawdown of at most 15%, over at least 100 trades.

Martingale, averaging-down on losing positions and any strategy without a stop-loss are not allowed.

Every live order needs a named human approver. Agents may prepare order tickets but never send them.

Per-order limit: 10 lots. Open-position limit: 40 lots. Daily loss limit: INR 1,50,000. After the daily loss limit is hit, trading stops for the day.

Backtests must use data at least 35 days old for NSE, NFO and BFO, and must include costs and slippage.

Algorithmic orders must follow the broker's and the exchange's rules for algo trading, including strategy approval and order tagging.
