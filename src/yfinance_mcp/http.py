from __future__ import annotations

import os

from .server import mcp

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8772
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def http_settings() -> tuple[str, int]:
    """Resolve and validate the local HTTP bind settings."""
    host = os.environ.get("YFINANCE_MCP_HOST", _DEFAULT_HOST).strip() or _DEFAULT_HOST
    raw_port = os.environ.get("YFINANCE_MCP_PORT", str(_DEFAULT_PORT)).strip()

    try:
        port = int(raw_port)
    except ValueError as exc:
        raise RuntimeError("YFINANCE_MCP_PORT must be an integer") from exc

    if not 1 <= port <= 65535:
        raise RuntimeError("YFINANCE_MCP_PORT must be between 1 and 65535")

    if host not in _LOOPBACK_HOSTS and os.environ.get(
        "YFINANCE_MCP_ALLOW_NON_LOOPBACK"
    ) != "1":
        raise RuntimeError(
            "Non-loopback binding requires YFINANCE_MCP_ALLOW_NON_LOOPBACK=1"
        )

    return host, port


def main() -> None:
    """Run the same read-only MCP server over Streamable HTTP."""
    host, port = http_settings()
    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        path="/mcp",
    )
