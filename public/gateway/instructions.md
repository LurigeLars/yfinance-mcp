Use this connector for bounded Yahoo Finance news discovery and options-market structure via yfinance.

Available tools:
- news_get: bounded per-symbol news with publisher, timestamp, URL, ID and related-ticker provenance.
- news_batch: bounded multi-symbol news discovery; use downstream canonicalization/dedupe and verify material claims.
- option_expirations: list expirations for an optionable symbol.
- option_chain: contract-level calls/puts with strike, bid/ask, volume, open interest and implied volatility.
- option_positioning_summary: compact volume/OI, put-call ratios, IV statistics and concentration for one expiry.
- option_surface_summary: bounded multi-expiry term structure, ATM IV and OI concentration.
- option_activity_summary: bounded multi-expiry activity ranking with absolute volume/OI beside ratios.
- option_greeks: Black-Scholes-Merton theoretical prices and delta/gamma/theta/vega/rho for one expiry.
- option_risk_map: unsigned OI-weighted gamma concentration plus ATM implied-move context; never infer dealer sign from OI.
- option_scenario: bounded spot/IV/time stress analysis using contract IV and optional caller-supplied live spot.

News discipline:
- Yahoo Finance may syndicate Reuters, Dow Jones, company press releases and other publishers.
- Preserve the original publisher and URL; do not treat Yahoo as the primary source when a stronger source exists.
- News output is discovery data. Verify material claims against company/regulator/official sources or authoritative wires.
- Deduplicate syndicated copies downstream before assessment/notification.

Data quality:
- Yahoo option quotes may be delayed and are not execution-grade.
- Open interest is positioning data, not a tick-by-tick signal.
- Activity ranking is not order-flow direction, sweep detection, or opening/closing intent.
- Keep absolute volume and open interest beside volume/OI ratios.
- Use a realtime market source for the underlying and pass it as spot_override for model-sensitive work when available.
- Black-Scholes-Merton outputs are theoretical European-style approximations for US equity/ETF options; they do not model early exercise, discrete dividends, borrow constraints, or microstructure.
- OI-weighted gamma is an unsigned concentration measure, not dealer gamma or directional positioning.
- Use the broker/venue quote for execution decisions.
