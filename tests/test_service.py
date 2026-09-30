from dataclasses import replace

from yfinance_mcp.provider import ChainSnapshot
from yfinance_mcp.service import OptionsService


class FakeProvider:
    def __init__(self, snapshot: ChainSnapshot) -> None:
        self.snapshot = snapshot

    def option_expirations(self, symbol: str) -> tuple[str, ...]:
        return ("2026-10-02", "2026-10-09")

    def option_chain(self, symbol: str, expiry: str) -> ChainSnapshot:
        return replace(self.snapshot, expiry=expiry)


def make_snapshot() -> ChainSnapshot:
    return ChainSnapshot(
        symbol="TEST",
        expiry="2026-10-02",
        retrieved_at="2026-09-30T12:00:00+00:00",
        underlying={
            "symbol": "TEST",
            "regularMarketPrice": 105.0,
            "regularMarketTime": 1790779200,
            "currency": "USD",
            "exchange": "NMS",
            "quoteType": "EQUITY",
            "marketState": "REGULAR",
            "unexpectedUpstreamField": "must-not-leak",
        },
        calls=[
            {
                "contractSymbol": "TESTC100",
                "strike": 100.0,
                "volume": 20,
                "openInterest": 10,
                "impliedVolatility": 0.40,
                "bid": 6.0,
                "ask": 6.2,
                "lastPrice": 6.1,
                "lastTradeDate": "2026-09-30T11:59:00+00:00",
            },
            {
                "contractSymbol": "TESTC110",
                "strike": 110.0,
                "volume": 2000,
                "openInterest": 1000,
                "impliedVolatility": 0.45,
                "bid": 1.0,
                "ask": 1.1,
                "lastPrice": 1.05,
                "lastTradeDate": "2026-09-30T11:58:00+00:00",
            },
        ],
        puts=[
            {
                "contractSymbol": "TESTP100",
                "strike": 100.0,
                "volume": 300,
                "openInterest": 600,
                "impliedVolatility": 0.50,
                "bid": 0.8,
                "ask": 0.9,
                "lastPrice": 0.85,
                "lastTradeDate": "2026-09-30T11:57:00+00:00",
            },
            {
                "contractSymbol": "TESTP110",
                "strike": 110.0,
                "volume": 10,
                "openInterest": 0,
                "impliedVolatility": 0.55,
                "bid": 5.8,
                "ask": 6.0,
                "lastPrice": 5.9,
                "lastTradeDate": "2026-09-30T11:56:00+00:00",
            },
        ],
    )


def test_expirations_are_returned_without_credentials() -> None:
    service = OptionsService(FakeProvider(make_snapshot()))

    result = service.option_expirations("test")

    assert result["symbol"] == "TEST"
    assert result["expirations"] == ["2026-10-02", "2026-10-09"]


def test_chain_filters_without_hidden_default_limit() -> None:
    service = OptionsService(FakeProvider(make_snapshot()))

    result = service.option_chain(
        "TEST",
        "2026-10-02",
        min_strike=105,
        option_type="both",
    )

    assert result["counts"] == {"calls": 1, "puts": 1}
    assert result["calls"][0]["contractSymbol"] == "TESTC110"
    assert result["puts"][0]["contractSymbol"] == "TESTP110"
    assert result["filters"]["limit_per_side"] is None
    assert result["underlying"] == {
        "symbol": "TEST",
        "quote_type": "EQUITY",
        "exchange": "NMS",
        "currency": "USD",
        "market_state": "REGULAR",
        "regular_market_price": 105.0,
        "regular_market_time": 1790779200,
        "regular_market_time_utc": "2026-09-30T14:40:00+00:00",
    }
    assert "unexpectedUpstreamField" not in result["underlying"]


def test_positioning_summary_keeps_absolute_values_with_ratios() -> None:
    service = OptionsService(FakeProvider(make_snapshot()))

    result = service.option_positioning_summary("TEST", "2026-10-02", top_n=2)

    assert result["calls"]["total_volume"] == 2020
    assert result["calls"]["total_open_interest"] == 1010
    assert result["calls"]["volume_open_interest_ratio"] == 2
    assert result["puts"]["total_volume"] == 310
    assert result["puts"]["total_open_interest"] == 600
    assert result["put_call"]["volume_ratio"] == 310 / 2020
    assert result["put_call"]["ratio_convention"] == "puts divided by calls"


def test_zero_open_interest_is_not_reported_as_infinite_ratio() -> None:
    service = OptionsService(FakeProvider(make_snapshot()))

    result = service.option_positioning_summary("TEST", "2026-10-02", top_n=5)

    ratios = result["puts"]["top_volume_open_interest_ratio"]
    assert all(item["open_interest"] > 0 for item in ratios)
    assert all(item["volume_open_interest_ratio"] is not None for item in ratios)


def test_invalid_filter_range_is_rejected() -> None:
    service = OptionsService(FakeProvider(make_snapshot()))

    try:
        service.option_chain(
            "TEST",
            "2026-10-02",
            min_strike=120,
            max_strike=100,
        )
    except ValueError as exc:
        assert "min_strike" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_fastmcp_server_registers_tools() -> None:
    from yfinance_mcp.server import mcp

    assert mcp is not None


def test_missing_aggregate_fields_remain_unknown() -> None:
    snapshot = ChainSnapshot(
        symbol="TEST",
        expiry="2026-10-02",
        retrieved_at="2026-09-30T12:00:00+00:00",
        underlying={"symbol": "TEST"},
        calls=[
            {
                "contractSymbol": "TESTC100",
                "strike": 100.0,
                "volume": None,
                "openInterest": None,
                "impliedVolatility": None,
            }
        ],
        puts=[],
    )
    service = OptionsService(FakeProvider(snapshot))

    result = service.option_positioning_summary("TEST", "2026-10-02")

    assert result["calls"]["total_volume"] is None
    assert result["calls"]["total_open_interest"] is None
    assert result["calls"]["volume_open_interest_ratio"] is None
    assert result["put_call"]["volume_ratio"] is None
    assert result["put_call"]["open_interest_ratio"] is None


def test_surface_summary_compacts_multiple_expiries() -> None:
    service = OptionsService(FakeProvider(make_snapshot()))

    result = service.option_surface_summary(
        "TEST",
        max_expiries=2,
        top_n=2,
    )

    assert result["selection"] == {
        "start_index": 0,
        "max_expiries": 2,
        "available_expiration_count": 2,
        "selected_count": 2,
        "has_more": False,
    }
    assert [row["expiry"] for row in result["expiries"]] == [
        "2026-10-02",
        "2026-10-09",
    ]
    assert result["expiries"][0]["days_to_expiry"] == 2
    assert result["expiries"][0]["atm"] == {
        "strike": 100.0,
        "call_implied_volatility": 0.40,
        "put_implied_volatility": 0.50,
    }
    assert result["expiries"][0]["top_open_interest_strikes"][0] == {
        "strike": 110.0,
        "call_open_interest": 1000.0,
        "put_open_interest": 0.0,
        "total_open_interest": 1000.0,
    }


def test_surface_summary_rejects_unbounded_expiry_request() -> None:
    service = OptionsService(FakeProvider(make_snapshot()))

    try:
        service.option_surface_summary("TEST", max_expiries=13)
    except ValueError as exc:
        assert "max_expiries" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_activity_summary_ranks_with_absolute_thresholds() -> None:
    service = OptionsService(FakeProvider(make_snapshot()))

    result = service.option_activity_summary(
        "TEST",
        max_expiries=2,
        min_volume=100,
        min_open_interest=10,
        top_n=3,
    )

    assert result["candidates_considered"] == 4
    assert len(result["results"]) == 3
    first = result["results"][0]
    assert first["contract_symbol"] == "TESTC110"
    assert first["option_type"] == "call"
    assert first["volume"] == 2000.0
    assert first["open_interest"] == 1000.0
    assert first["volume_open_interest_ratio"] == 2.0
    assert first["moneyness_pct_from_spot"] == (110 / 105 - 1) * 100
    assert result["data_quality"]["activity_is_not_order_flow"] is True


def test_activity_summary_supports_explicit_volume_ranking() -> None:
    service = OptionsService(FakeProvider(make_snapshot()))

    result = service.option_activity_summary(
        "TEST",
        max_expiries=1,
        min_volume=0,
        min_open_interest=0,
        sort_by="volume",
        top_n=2,
    )

    assert [row["contract_symbol"] for row in result["results"]] == [
        "TESTC110",
        "TESTP100",
    ]


def test_activity_summary_rejects_invalid_sort() -> None:
    service = OptionsService(FakeProvider(make_snapshot()))

    try:
        service.option_activity_summary(
            "TEST",
            sort_by="not-a-sort",  # type: ignore[arg-type]
        )
    except ValueError as exc:
        assert "sort_by" in str(exc)
    else:
        raise AssertionError("expected ValueError")
