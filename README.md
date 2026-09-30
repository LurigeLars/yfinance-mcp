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

No credentials or environment variables are required.

Remote transport, authentication, and network exposure are deliberately deployment-specific and are not part of this repository's V1.

## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest
```

## License

Apache-2.0 for this MCP wrapper. The downloaded market data remains subject to the applicable upstream data terms.
