from __future__ import annotations

import pytest

import yfinance_mcp.http as http_runtime
from yfinance_mcp.http import http_settings


def test_http_defaults_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YFINANCE_MCP_HOST", raising=False)
    monkeypatch.delenv("YFINANCE_MCP_PORT", raising=False)
    monkeypatch.delenv("YFINANCE_MCP_ALLOW_NON_LOOPBACK", raising=False)

    assert http_settings() == ("127.0.0.1", 8772)


def test_non_loopback_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YFINANCE_MCP_HOST", "0.0.0.0")
    monkeypatch.delenv("YFINANCE_MCP_ALLOW_NON_LOOPBACK", raising=False)

    with pytest.raises(RuntimeError, match="Non-loopback"):
        http_settings()


def test_non_loopback_can_be_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YFINANCE_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("YFINANCE_MCP_ALLOW_NON_LOOPBACK", "1")
    monkeypatch.setenv("YFINANCE_MCP_PORT", "9000")

    assert http_settings() == ("0.0.0.0", 9000)


@pytest.mark.parametrize("port", ["0", "65536", "not-a-number"])
def test_invalid_http_port_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    port: str,
) -> None:
    monkeypatch.setenv("YFINANCE_MCP_PORT", port)

    with pytest.raises(RuntimeError):
        http_settings()


def test_main_uses_fastmcp4_http_path_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.delenv("YFINANCE_MCP_HOST", raising=False)
    monkeypatch.delenv("YFINANCE_MCP_PORT", raising=False)
    monkeypatch.setattr(http_runtime.mcp, "run", fake_run)

    http_runtime.main()

    assert calls == [
        {
            "transport": "streamable-http",
            "host": "127.0.0.1",
            "port": 8772,
            "path": "/mcp",
        }
    ]


def test_actual_http_transport_across_protocol_eras(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from fastmcp.utilities.tests import asgi_server

    from yfinance_mcp import server

    expected = {"symbol": "TEST", "expirations": ["2027-01-15"]}
    monkeypatch.setattr(
        server, "_service",
        SimpleNamespace(option_expirations=lambda symbol: {**expected, "symbol": symbol}),
    )

    async def run() -> None:
        # Exercise the real Streamable HTTP application without a socket,
        # external market-data requests or credentials.
        async with asgi_server(server.mcp, transport="streamable-http", path="/mcp") as http:
            baseline = None
            for mode in ("auto", "2026-07-28", "legacy"):
                async with http.client(mode=mode) as client:
                    if mode == "legacy":
                        assert client.protocol_version != "2026-07-28"
                    else:
                        assert client.protocol_version == "2026-07-28"
                    names = {tool.name for tool in await client.list_tools()}
                    assert "option_expirations" in names
                    result = await client.call_tool("option_expirations", {"symbol": "TEST"})
                    assert result.data == expected
                    if baseline is None:
                        baseline = names
                    assert names == baseline

    asyncio.run(run())
