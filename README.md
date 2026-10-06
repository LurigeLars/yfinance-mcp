# yfinance-mcp

[![CI](https://github.com/LurigeLars/yfinance-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/LurigeLars/yfinance-mcp/actions/workflows/ci.yml)
[![CodeQL](https://github.com/LurigeLars/yfinance-mcp/actions/workflows/codeql.yml/badge.svg)](https://github.com/LurigeLars/yfinance-mcp/actions/workflows/codeql.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-Apache--2.0-green)

A small, read-only Model Context Protocol (MCP) server for Yahoo Finance news and
options-market research through the upstream `yfinance` package.

It gives AI clients a bounded, typed way to inspect option chains, positioning/activity
summaries, theoretical greeks, gamma concentration, scenario analysis and Yahoo Finance
news without turning the MCP into a generic market-data or brokerage interface.

> **Not execution infrastructure.** Yahoo Finance data can be delayed or incomplete.
> Quotes, open interest and model outputs are analytical context, not broker-grade or
> execution-grade data.

## Why this project exists

The upstream [yfinance](https://github.com/ranaroussi/yfinance) package is useful for
Python applications, but an AI agent needs a different interface:

- a small set of explicit tools rather than arbitrary library access;
- bounded responses so option chains and news cannot grow without control;
- normalized output with predictable semantics;
- deterministic summaries that do not depend on free-form model interpretation;
- clear separation between observed market data and theoretical calculations;
- no brokerage login, account access or order execution.

This server is intentionally narrow. It exists primarily to fill two research gaps:

1. **Options-market structure** — expirations, chains, volume/open-interest structure,
   IV summaries, theoretical greeks, unsigned gamma concentration and bounded scenarios.
2. **Yahoo Finance news discovery** — compact per-symbol and batch discovery with source
   provenance preserved.

It is not intended to become a general Yahoo Finance MCP for quotes, fundamentals,
portfolio management or trading.

## What it can do

| Area | Capability |
|---|---|
| News | Discover recent Yahoo Finance news for one symbol or a bounded symbol batch |
| Expirations | List available option expiration dates |
| Chains | Read calls, puts or both for one expiration |
| Positioning | Summarize call/put volume, OI, ratios, IV and notable strikes |
| Surface | Compare a bounded sequence of expirations |
| Activity | Rank contracts by volume/OI, volume or open interest |
| Greeks | Calculate Black-Scholes-Merton theoretical greeks |
| Risk map | Rank unsigned gamma concentration by strike |
| Scenarios | Reprice contracts under explicit spot, IV and time changes |

Everything is read-only.

## What it deliberately does not do

- brokerage authentication;
- portfolio or account access;
- order placement or execution;
- realtime streaming;
- generic Yahoo quote/fundamental coverage;
- claims about trade aggressor side, sweeps or opening/closing flow;
- inference of dealer long/short gamma from open interest alone.

Those boundaries are deliberate. New tools should solve a concrete research gap rather
than merely expose another upstream endpoint.

## Architecture

```text
MCP client
   |
   v
yfinance-mcp
   |
   +--> bounded news normalization
   |
   +--> options service / deterministic analytics
   |
   v
upstream yfinance package
   |
   v
Yahoo Finance
```

For remote deployments, an optional gateway can sit in front of the loopback MCP server:

```text
remote MCP client
   -> Cloudflare Access
   -> yfinance gateway
   -> loopback yfinance-mcp HTTP server
   -> yfinance / Yahoo Finance
```

The public gateway exposes only the reviewed tool allowlist and does not add credentials
or brokerage capability.

## Data source and limitations

`yfinance` is an independent open-source library that retrieves data from Yahoo Finance.
This project is not affiliated with Yahoo, Yahoo Finance or the yfinance project.

Important limitations:

- Yahoo Finance option quotes may be delayed.
- Open interest is not a tick-by-tick realtime signal.
- A high volume/OI ratio does not by itself establish unusual institutional flow.
- Yahoo data does not reveal aggressor side or reliably distinguish opening from closing
  option trades.
- Missing values remain unknown; they are not silently converted to zero.
- Retrieval time is not the same thing as market timestamp.

Use venue or broker data when execution quality matters.

The yfinance project notes that Yahoo Finance data is intended for personal use and that
users are responsible for complying with Yahoo's terms. Review the upstream yfinance
documentation and Yahoo terms before using downloaded data beyond personal research.

## Quick start

### Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- no API key or account credentials

Clone and install the locked environment:

```bash
git clone https://github.com/LurigeLars/yfinance-mcp.git
cd yfinance-mcp
uv sync --locked
```

Run over stdio:

```bash
uv run yfinance-mcp
```

Example MCP configuration:

```json
{
  "mcpServers": {
    "yfinance": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/yfinance-mcp",
        "--locked",
        "yfinance-mcp"
      ]
    }
  }
}
```

## Tool catalog

The server exposes ten bounded read-only tools.

### `news_get`

Returns up to 50 Yahoo Finance news items for one symbol.

Output is normalized to fields such as publisher, publication timestamp, canonical URL,
upstream ID, related tickers and content type. Treat this as discovery data: material
claims should be verified against primary sources or authoritative wires.

### `news_batch`

Queries up to 100 unique symbols with an explicit per-symbol bound.

Partial upstream failures are returned explicitly in `failed_symbols`; successful
symbols are retained. Syndicated duplicates are intentionally left for downstream
canonicalization.

### `option_expirations`

Returns the expiration dates Yahoo Finance currently exposes for an optionable symbol.

### `option_chain`

Returns calls, puts or both for one expiration, including available upstream fields such
as:

- contract symbol;
- last trade date;
- strike;
- last price;
- bid / ask;
- volume;
- open interest;
- implied volatility;
- in-the-money flag;
- contract size;
- currency.

Optional filters can narrow strike, volume and open-interest ranges. There is no hidden
default row limit. `limit_per_side` is available when the caller explicitly wants a
bounded response.

Underlying quote metadata is projected into a small allowlisted schema rather than
forwarding Yahoo's full auxiliary payload.

### `option_positioning_summary`

Produces a compact per-expiration summary with:

- total call and put volume;
- total call and put open interest;
- put/call volume and OI ratios;
- highest-volume strikes;
- highest-OI strikes;
- highest volume/OI contracts where OI is positive;
- IV distribution statistics;
- underlying quote metadata.

Absolute volume and OI are retained beside ratios so a large ratio cannot hide a tiny
denominator.

### `option_surface_summary`

Summarizes a bounded consecutive expiration window (default 8, maximum 12), including:

- days to expiry;
- call/put volume and OI totals;
- put/call ratios;
- median IV by side;
- nearest-to-spot strike with call/put IV;
- highest combined-OI strikes.

`start_index` pages through the expiration list and the response preserves the explicit
selection bound.

### `option_activity_summary`

Ranks contracts across a bounded expiration window using explicit minimum volume and
open-interest thresholds.

Ranking can use:

- volume/OI ratio;
- absolute volume;
- absolute open interest.

The output includes contract-level bid/ask, IV, strike distance from spot and last-trade
timestamp.

This is activity evidence, not directional order flow.

### `option_greeks`

Calculates Black-Scholes-Merton theoretical:

- price;
- delta;
- gamma;
- theta per day;
- vega per IV point;
- rho per rate point.

The annualized risk-free rate is an explicit input. Continuous dividend yield defaults
to zero.

`spot_override` lets callers supply a fresher underlying price from another source
instead of relying on Yahoo's potentially delayed regular-market quote.

### `option_risk_map`

Weights model gamma by open interest and contract multiplier to rank strike-level gamma
concentration.

The result is deliberately **unsigned**. Open interest does not reveal who is long or
short, so the server does not label this "dealer gamma" or infer dealer direction.

The tool also returns a simple one-standard-deviation ATM implied move from available
contract IVs.

### `option_scenario`

Reprices a bounded single-expiration contract set under explicit changes to:

- underlying spot;
- implied volatility, expressed as absolute volatility points;
- time forward.

Contracts can be ranked by open interest, absolute model-price change or unsigned gamma
concentration.

These are theoretical model changes, not executable P&L forecasts.

## Model assumptions

The theoretical options analytics use Black-Scholes-Merton with ACT/365 and assume
expiry at 16:00 America/New_York.

US equity and ETF options are generally American-style, so this is an approximation.
The model does not capture, among other things:

- early exercise;
- discrete dividend timing;
- borrow constraints;
- full volatility-surface dynamics;
- market microstructure.

Use `spot_override` with a fresher underlying price when available, and use venue or
broker quotes for execution decisions.

## HTTP mode

The same tool surface can run over Streamable HTTP:

```bash
uv run yfinance-mcp-http
```

Default endpoint:

```text
http://127.0.0.1:8772/mcp
```

Environment variables:

- `YFINANCE_MCP_HOST` — bind host;
- `YFINANCE_MCP_PORT` — bind port;
- `YFINANCE_MCP_ALLOW_NON_LOOPBACK=1` — explicit opt-in required for a non-loopback
  bind.

A non-loopback host is rejected unless that opt-in is set.

### Windows background task

The included installer creates a per-user, limited-privilege Scheduled Task and keeps
the HTTP server on loopback:

```powershell
.\scripts\windows\install-http-task.ps1
```

When the local Docker-MCP host-port registry is present, the installer reserves a stable
port for `yfinance-mcp-http` rather than silently moving the service between ports.

A bounded live provider smoke test is available after installation:

```powershell
.\.venv\Scripts\python.exe .\scripts\smoke_options.py NVDA
```

## Protected remote gateway

Do not expose the unauthenticated Python MCP HTTP endpoint directly to the Internet.

A separate Node gateway is included for deployments protected by Cloudflare Access. It:

- validates the Access JWT independently;
- strips client credentials before forwarding;
- exposes only the ten reviewed read-only tools;
- applies request/rate limits;
- compacts MCP schemas/results for model use;
- keeps the Python MCP endpoint on loopback.

Copy the example environment file:

```powershell
Copy-Item public\gateway.env.example public\gateway.env
```

Fill in deployment-specific Access values, keep the real file ignored, then install the
gateway:

```powershell
.\scripts\windows\install-public-gateway.ps1 -AccessAudience <audience>
```

No real hostname, identity, audience, tunnel ID, token or credential belongs in Git.

## Development

Install development dependencies:

```bash
uv sync --locked --extra dev
```

Run lint and tests:

```bash
uv run --no-sync ruff check .
uv run --no-sync pytest
node --test tests/gateway/*.test.mjs
```

The repository runs:

- CI on Python 3.12 and 3.13;
- gateway tests;
- static analysis;
- CodeQL;
- Dependabot;
- a scheduled upstream watch for locked yfinance and FastMCP releases.

Dependency updates should continue through normal review rather than by vendoring
upstream yfinance code into this repository.

## Security and privacy

This repository is public.

Do not commit:

- credentials or access tokens;
- cookies;
- personal identifiers or email addresses;
- workstation-specific paths;
- private domains/endpoints;
- Cloudflare tunnel identifiers;
- brokerage or account data.

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## License

Apache-2.0 for this MCP wrapper. Market data retrieved from Yahoo Finance remains subject
to the applicable upstream data terms.
