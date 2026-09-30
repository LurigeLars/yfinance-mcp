# yfinance-mcp

A small, read-only MCP server for options-market data provided by the upstream `yfinance` package.

The server is intentionally narrow: it exposes option expirations, raw option chains, and a compact positioning summary. It does not place orders, access brokerage accounts, or provide execution-grade quotes.

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

Optional filters can narrow strike, volume, and open-interest ranges. There is no default row limit. An optional `limit_per_side` is available when a caller explicitly wants a bounded response.

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

## Install

Python 3.12 or newer is recommended.

```bash
python -m venv .venv
python -m pip install -e .
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

Default endpoint:

```text
http://127.0.0.1:8772/mcp
```

The optional environment variables `YFINANCE_MCP_HOST` and `YFINANCE_MCP_PORT` change the bind address and port. A non-loopback host is rejected unless `YFINANCE_MCP_ALLOW_NON_LOOPBACK=1` is also set explicitly.

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

A separate Node gateway is included for deployments that place Cloudflare Access in front of the MCP server. The gateway independently validates the Access JWT, strips client credentials before forwarding, exposes only the three read-only options tools, applies request/rate limits, and keeps the Python MCP endpoint on loopback.

Copy `public/gateway.env.example` to the ignored `public/gateway.env`, fill in the deployment-specific Access values, then run:

```powershell
.\scripts\windows\install-public-gateway.ps1 -AccessAudience <audience>
```

The installer can also read the team domain and allowed identity values from an existing local gateway env file via `-TemplateGatewayEnvPath`. No real hostname, identity, audience, tunnel ID, token, or credential belongs in Git.


## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest
```

## License

Apache-2.0 for this MCP wrapper. The downloaded market data remains subject to the applicable upstream data terms.
