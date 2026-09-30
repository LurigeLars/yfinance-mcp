from __future__ import annotations

import math
import statistics
from datetime import UTC, datetime
from typing import Any, Literal

from .provider import QUOTE_DELAY_NOTICE, SOURCE, ChainSnapshot, YFinanceProvider

OptionType = Literal["calls", "puts", "both"]


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sum_field(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [
        value for row in rows if (value := _number(row.get(field))) is not None
    ]
    return sum(values) if values else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _contract_view(row: dict[str, Any]) -> dict[str, Any]:
    volume = _number(row.get("volume"))
    open_interest = _number(row.get("openInterest"))
    return {
        "contract_symbol": row.get("contractSymbol"),
        "strike": _number(row.get("strike")),
        "volume": volume,
        "open_interest": open_interest,
        "volume_open_interest_ratio": (
            volume / open_interest
            if volume is not None and open_interest is not None and open_interest > 0
            else None
        ),
        "implied_volatility": _number(row.get("impliedVolatility")),
        "bid": _number(row.get("bid")),
        "ask": _number(row.get("ask")),
        "last_price": _number(row.get("lastPrice")),
        "last_trade_date": row.get("lastTradeDate"),
    }


def _top(
    rows: list[dict[str, Any]],
    field: str,
    top_n: int,
    *,
    require_positive_oi: bool = False,
) -> list[dict[str, Any]]:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        if require_positive_oi:
            volume = _number(row.get("volume"))
            open_interest = _number(row.get("openInterest"))
            if volume is None or open_interest is None or open_interest <= 0:
                continue
            value = volume / open_interest
        else:
            value = _number(row.get(field))
            if value is None:
                continue
        candidates.append((value, row))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [_contract_view(row) for _, row in candidates[:top_n]]


def _iv_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [
        value
        for row in rows
        if (value := _number(row.get("impliedVolatility"))) is not None and value >= 0
    ]
    if not values:
        return {"count": 0, "min": None, "median": None, "max": None}
    return {
        "count": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
    }


def _summarize_side(rows: list[dict[str, Any]], top_n: int) -> dict[str, Any]:
    total_volume = _sum_field(rows, "volume")
    total_open_interest = _sum_field(rows, "openInterest")
    return {
        "contracts": len(rows),
        "contracts_with_volume": sum(_number(row.get("volume")) is not None for row in rows),
        "contracts_with_open_interest": sum(
            _number(row.get("openInterest")) is not None for row in rows
        ),
        "total_volume": total_volume,
        "total_open_interest": total_open_interest,
        "volume_open_interest_ratio": _ratio(total_volume, total_open_interest),
        "iv": _iv_stats(rows),
        "top_volume": _top(rows, "volume", top_n),
        "top_open_interest": _top(rows, "openInterest", top_n),
        "top_volume_open_interest_ratio": _top(
            rows,
            "volume",
            top_n,
            require_positive_oi=True,
        ),
    }


def _filter_rows(
    rows: list[dict[str, Any]],
    *,
    min_strike: float | None,
    max_strike: float | None,
    min_volume: int | None,
    min_open_interest: int | None,
    limit_per_side: int | None,
) -> list[dict[str, Any]]:
    if min_strike is not None and max_strike is not None and min_strike > max_strike:
        raise ValueError("min_strike must not be greater than max_strike")
    if min_volume is not None and min_volume < 0:
        raise ValueError("min_volume must be non-negative")
    if min_open_interest is not None and min_open_interest < 0:
        raise ValueError("min_open_interest must be non-negative")
    if limit_per_side is not None and limit_per_side <= 0:
        raise ValueError("limit_per_side must be positive")

    filtered: list[dict[str, Any]] = []
    for row in rows:
        strike = _number(row.get("strike"))
        volume = _number(row.get("volume"))
        open_interest = _number(row.get("openInterest"))

        if min_strike is not None and (strike is None or strike < min_strike):
            continue
        if max_strike is not None and (strike is None or strike > max_strike):
            continue
        if min_volume is not None and (volume is None or volume < min_volume):
            continue
        if min_open_interest is not None and (
            open_interest is None or open_interest < min_open_interest
        ):
            continue
        filtered.append(row)

    if limit_per_side is not None:
        return filtered[:limit_per_side]
    return filtered


def _underlying_summary(underlying: dict[str, Any]) -> dict[str, Any]:
    market_time = underlying.get("regularMarketTime")
    market_time_utc = None
    market_timestamp = _number(market_time)
    if market_timestamp is not None:
        try:
            market_time_utc = datetime.fromtimestamp(
                market_timestamp, tz=UTC
            ).isoformat()
        except (OverflowError, OSError, ValueError):
            market_time_utc = None

    return {
        "symbol": underlying.get("symbol"),
        "quote_type": underlying.get("quoteType"),
        "exchange": underlying.get("exchange"),
        "currency": underlying.get("currency"),
        "market_state": underlying.get("marketState"),
        "regular_market_price": _number(underlying.get("regularMarketPrice")),
        "regular_market_time": market_time,
        "regular_market_time_utc": market_time_utc,
    }


class OptionsService:
    def __init__(self, provider: YFinanceProvider | None = None) -> None:
        self._provider = provider or YFinanceProvider()

    @staticmethod
    def _metadata(snapshot: ChainSnapshot) -> dict[str, Any]:
        return {
            "source": SOURCE,
            "retrieved_at": snapshot.retrieved_at,
            "symbol": snapshot.symbol,
            "expiry": snapshot.expiry,
            "data_quality": {
                "quote_may_be_delayed": True,
                "execution_grade": False,
                "notice": QUOTE_DELAY_NOTICE,
            },
        }

    def option_expirations(self, symbol: str) -> dict[str, Any]:
        expirations = list(self._provider.option_expirations(symbol))
        return {
            "source": SOURCE,
            "symbol": symbol.strip().upper(),
            "count": len(expirations),
            "expirations": expirations,
            "data_quality": {
                "quote_may_be_delayed": True,
                "execution_grade": False,
                "notice": QUOTE_DELAY_NOTICE,
            },
        }

    def option_chain(
        self,
        symbol: str,
        expiry: str,
        *,
        option_type: OptionType = "both",
        min_strike: float | None = None,
        max_strike: float | None = None,
        min_volume: int | None = None,
        min_open_interest: int | None = None,
        limit_per_side: int | None = None,
    ) -> dict[str, Any]:
        if option_type not in {"calls", "puts", "both"}:
            raise ValueError("option_type must be calls, puts, or both")

        snapshot = self._provider.option_chain(symbol, expiry)
        calls = _filter_rows(
            snapshot.calls,
            min_strike=min_strike,
            max_strike=max_strike,
            min_volume=min_volume,
            min_open_interest=min_open_interest,
            limit_per_side=limit_per_side,
        )
        puts = _filter_rows(
            snapshot.puts,
            min_strike=min_strike,
            max_strike=max_strike,
            min_volume=min_volume,
            min_open_interest=min_open_interest,
            limit_per_side=limit_per_side,
        )

        result = self._metadata(snapshot)
        result["filters"] = {
            "option_type": option_type,
            "min_strike": min_strike,
            "max_strike": max_strike,
            "min_volume": min_volume,
            "min_open_interest": min_open_interest,
            "limit_per_side": limit_per_side,
        }
        result["underlying"] = snapshot.underlying
        result["counts"] = {
            "calls": len(calls) if option_type in {"calls", "both"} else 0,
            "puts": len(puts) if option_type in {"puts", "both"} else 0,
        }
        if option_type in {"calls", "both"}:
            result["calls"] = calls
        if option_type in {"puts", "both"}:
            result["puts"] = puts
        return result

    def option_positioning_summary(
        self,
        symbol: str,
        expiry: str,
        *,
        min_strike: float | None = None,
        max_strike: float | None = None,
        top_n: int = 10,
    ) -> dict[str, Any]:
        if top_n <= 0 or top_n > 50:
            raise ValueError("top_n must be between 1 and 50")

        snapshot = self._provider.option_chain(symbol, expiry)
        calls = _filter_rows(
            snapshot.calls,
            min_strike=min_strike,
            max_strike=max_strike,
            min_volume=None,
            min_open_interest=None,
            limit_per_side=None,
        )
        puts = _filter_rows(
            snapshot.puts,
            min_strike=min_strike,
            max_strike=max_strike,
            min_volume=None,
            min_open_interest=None,
            limit_per_side=None,
        )

        call_summary = _summarize_side(calls, top_n)
        put_summary = _summarize_side(puts, top_n)

        result = self._metadata(snapshot)
        result["filters"] = {
            "min_strike": min_strike,
            "max_strike": max_strike,
            "top_n": top_n,
        }
        result["underlying"] = _underlying_summary(snapshot.underlying)
        result["calls"] = call_summary
        result["puts"] = put_summary
        result["put_call"] = {
            "volume_ratio": _ratio(
                put_summary["total_volume"],
                call_summary["total_volume"],
            ),
            "open_interest_ratio": _ratio(
                put_summary["total_open_interest"],
                call_summary["total_open_interest"],
            ),
            "ratio_convention": "puts divided by calls",
        }
        return result
