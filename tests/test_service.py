from yfinance_mcp.provider import ChainSnapshot
from yfinance_mcp.service import OptionsService


class FakeProvider:
    def __init__(self, snapshot: ChainSnapshot) -> None:
        self.snapshot = snapshot

    def option_expirations(self, symbol: str) -> tuple[str, ...]:
        return ("2026-10-02", "2026-10-09")

    def option_chain(self, symbol: str, expiry: str) -> ChainSnapshot:
        return self.snapshot


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
