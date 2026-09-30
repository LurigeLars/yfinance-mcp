Use this connector for options-market structure from Yahoo Finance via yfinance.

Available tools:
- option_expirations: list expirations for an optionable symbol.
- option_chain: contract-level calls/puts with strike, bid/ask, volume, open interest and implied volatility.
- option_positioning_summary: compact volume/OI, put-call ratios, IV statistics and concentration for one expiry.
- option_surface_summary: bounded multi-expiry term structure, ATM IV and OI concentration.
- option_activity_summary: bounded multi-expiry activity ranking with absolute volume/OI beside ratios.
- option_greeks: Black-Scholes-Merton theoretical prices and delta/gamma/theta/vega/rho for one expiry.
- option_risk_map: unsigned OI-weighted gamma concentration plus ATM implied-move context; never infer dealer sign from OI.
- option_scenario: bounded spot/IV/time stress analysis using contract IV and optional caller-supplied live spot.

Data quality:
- Yahoo option quotes may be delayed and are not execution-grade.
- Open interest is positioning data, not a tick-by-tick signal.
- Activity ranking is not order-flow direction, sweep detection, or opening/closing intent.
- Keep absolute volume and open interest beside volume/OI ratios.
- Use a realtime market source for the underlying and pass it as spot_override for model-sensitive work when available.
- Black-Scholes-Merton outputs are theoretical European-style approximations for US equity/ETF options; they do not model early exercise, discrete dividends, borrow constraints, or microstructure.
- OI-weighted gamma is an unsigned concentration measure, not dealer gamma or directional positioning.
- Use the broker/venue quote for execution decisions.
