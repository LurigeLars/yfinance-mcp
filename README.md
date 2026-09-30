# yfinance-mcp

A small, read-only MCP server for options-market data and bounded theoretical options analytics provided by the upstream `yfinance` package.

The server is intentionally narrow: it exposes option expirations, raw option chains, positioning/activity summaries, and Black-Scholes-Merton greeks, unsigned gamma concentration, and scenario analysis. It does not place orders, access brokerage accounts, or provide execution-grade quotes.

## Data source and limitations

`yfinance` is an independent open-source library that retrieves data from Yahoo Finance. This project is not affiliated with or endorsed by Yahoo or the yfinance project.

Yahoo Finance option quotes may be delayed. Treat bid/ask and last prices as analytical context, not execution data. Open interest should not be interpreted as a tick-by-tick real-time signal.

The yfinance project notes that Yahoo Finance data is intended for personal use and that users are responsible for complying with Yahoo's terms. Review the upstream yfinance documentation and Yahoo terms before using downloaded data beyond personal research.

## Tools

### `option_expirations`

Returns the available expiration dates for an optionable symbol.

### `option_chain`

Returns calls, puts, or both for one expiration, including the fields exposed by yfinance such as:

- contract symbol
- last trade date
- strike
- last price
- bid / ask
- volume
- open interest
- implied volatility
- ITM flag
- contract size
- currency

Optional filters can narrow strike, volume, and open-interest ranges. There is no default row limit. An optional `limit_per_side` is available when a caller explicitly wants a bounded response. Underlying quote metadata is normalized to a small allowlisted schema rather than forwarding Yahoo's full auxiliary payload.

### `option_positioning_summary`

Produces a compact per-expiration summary with:

- total call and put volume
- total call and put open interest
- put/call volume and OI ratios
- highest-volume strikes
- highest-OI strikes
- highest volume/OI contracts where OI is positive
- IV distribution statistics
- underlying quote metadata returned with the option chain

The summary keeps absolute volume and OI beside volume/OI ratios so a high ratio cannot hide a tiny denominator.

### `option_surface_summary`

Summarizes a bounded consecutive expiration window (default 8, maximum 12) with:

- days to expiry
- call/put volume and open interest totals
- put/call volume and OI ratios
- median IV by side
- nearest-to-spot strike with call/put IV
- highest combined-OI strikes

`start_index` pages through the expiration list and `max_expiries` is always returned in the selection metadata, so the bound is explicit.

### `option_activity_summary`

Ranks contracts across a bounded expiration window using explicit minimum volume/open-interest thresholds. It can sort by volume/OI ratio, absolute volume, or absolute open interest and returns contract-level bid/ask, IV, strike distance from spot, and last-trade timestamp.

This is activity evidence, not order-flow direction: Yahoo data does not establish sweeps, aggressor side, or whether trades opened or closed positions.

### `option_greeks`

Calculates Black-Scholes-Merton theoretical price, delta, gamma, theta/day, vega per IV point, and rho per rate point for contracts in one expiry. The annualized risk-free rate is an explicit caller input. Continuous dividend yield defaults to zero. `spot_override` lets callers use a fresher underlying price from a realtime source instead of Yahoo's potentially delayed regular-market quote.

### `option_risk_map`

Weights model gamma by open interest and the contract multiplier to rank strike-level gamma concentration. The output is deliberately **unsigned**: open interest does not reveal who is long or short, so the tool does not label the result dealer gamma or infer dealer direction. It also returns a simple one-standard-deviation ATM implied move from the available contract IVs.

### `option_scenario`

Reprices a bounded single-expiry contract set under explicit changes to underlying spot, implied volatility (absolute vol points), and time forward. Results are theoretical model changes, not executable P&L forecasts. Contracts can be ranked by open interest, absolute model-price change, or unsigned gamma concentration.

### Model limitations

The analytics use Black-Scholes-Merton with ACT/365 and assume expiry at 16:00 America/New_York. US equity and ETF options are generally American-style, so the model is an approximation: early exercise, discrete dividends, borrow constraints, and market microstructure are not modeled. Use current underlying data via `spot_override` when available and venue/broker quotes for execution.

## Install

Python 3.12 or newer is recommended. The repository commits `uv.lock` for reproducible deployments.

```bash
uv sync --locked
```

Run the MCP server over stdio:

```bash
yfinance-mcp
```

Example client configuration:

```json
{
  "mcpServers": {
    "yfinance": {
      "command": "yfinance-mcp"
    }
  }
}
```

No credentials are required.

### Loopback HTTP

The same tool surface can also run over Streamable HTTP. It binds to loopback by default:

```bash
yfinance-mcp-http
```

Standalone `yfinance-mcp-http` retains its package default endpoint at `http://127.0.0.1:8772/mcp`.
The optional environment variables `YFINANCE_MCP_HOST` and `YFINANCE_MCP_PORT` change the bind address and port. A non-loopback host is rejected unless `YFINANCE_MCP_ALLOW_NON_LOOPBACK=1` is also set explicitly.

On this local MCP stack, the Windows installer does **not** independently trust that default. When
Docker-MCP's host port registry is installed it reserves a stable port for `yfinance-mcp-http`
(preferred first allocation: 8772), adopts an already-running matching legacy listener during
migration, and writes that exact reserved port into the Scheduled Task. Normal restarts reuse the
same reservation and never silently hop to another port.

On Windows, the included installer creates a per-user, limited-privilege Scheduled Task and keeps the HTTP server on loopback:

```powershell
.\scripts\windows\install-http-task.ps1
```

A bounded live provider smoke test is available after installation:

```powershell
.\.venv\Scripts\python.exe .\scripts\smoke_options.py NVDA
```

Authentication and Internet exposure remain deployment-specific. Do not expose the unauthenticated MCP HTTP endpoint directly to the Internet.
### Protected remote gateway

A separate Node gateway is included for deployments that place Cloudflare Access in front of the MCP server. The gateway independently validates the Access JWT, strips client credentials before forwarding, exposes only the eight read-only options tools, applies request/rate limits, and keeps the Python MCP endpoint on loopback.

Copy `public/gateway.env.example` to the ignored `public/gateway.env`, fill in the deployment-specific Access values, then run:

```powershell
.\scripts\windows\install-public-gateway.ps1 -AccessAudience <audience>
```

The installer can also read the team domain and allowed identity values from an existing local gateway env file via `-TemplateGatewayEnvPath`. No real hostname, identity, audience, tunnel ID, token, or credential belongs in Git.


## Development

```bash
uv sync --locked --extra dev
uv run --no-sync ruff check .
uv run --no-sync pytest
```

Dependabot checks Python and GitHub Actions dependencies weekly. A separate scheduled upstream watch compares the locked `yfinance` and FastMCP versions with their latest GitHub releases; Dependabot remains the normal update path when a package release is available.

## License

Apache-2.0 for this MCP wrapper. The downloaded market data remains subject to the applicable upstream data terms.
