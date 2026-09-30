Use this connector for options-market structure from Yahoo Finance via yfinance.

Available tools:
- option_expirations: list expirations for an optionable symbol.
- option_chain: contract-level calls/puts with strike, bid/ask, volume, open interest and implied volatility.
- option_positioning_summary: compact volume/OI, put-call ratios, IV statistics and concentration for one expiry.

Data quality:
- Yahoo option quotes may be delayed and are not execution-grade.
- Open interest is positioning data, not a tick-by-tick signal.
- Keep absolute volume and open interest beside volume/OI ratios.
- Use a realtime market source for the underlying and the broker/venue quote for execution decisions.
