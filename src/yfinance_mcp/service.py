from __future__ import annotations

import math
import statistics
from datetime import UTC, datetime
from typing import Any, Literal

from .provider import QUOTE_DELAY_NOTICE, SOURCE, ChainSnapshot, YFinanceProvider

OptionType = Literal["calls", "puts", "both"]
ActivitySort = Literal["volume_open_interest_ratio", "volume", "open_interest"]


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



def _compact_side_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_volume = _sum_field(rows, "volume")
    total_open_interest = _sum_field(rows, "openInterest")
    return {
        "contracts": len(rows),
        "total_volume": total_volume,
        "total_open_interest": total_open_interest,
        "volume_open_interest_ratio": _ratio(total_volume, total_open_interest),
        "median_implied_volatility": _iv_stats(rows)["median"],
    }


def _days_to_expiry(expiry: str, retrieved_at: str) -> int | None:
    try:
        expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
        retrieved_date = datetime.fromisoformat(
            retrieved_at.replace("Z", "+00:00")
        ).date()
    except ValueError:
        return None
    return (expiry_date - retrieved_date).days


def _top_open_interest_strikes(
    calls: list[dict[str, Any]],
    puts: list[dict[str, Any]],
    top_n: int,
) -> list[dict[str, Any]]:
    buckets: dict[float, dict[str, float | None]] = {}
    for side, rows in (("call", calls), ("put", puts)):
        key = f"{side}_open_interest"
        for row in rows:
            strike = _number(row.get("strike"))
            open_interest = _number(row.get("openInterest"))
            if strike is None or open_interest is None:
                continue
            bucket = buckets.setdefault(
                strike,
                {
                    "call_open_interest": None,
                    "put_open_interest": None,
                },
            )
            previous = bucket[key]
            bucket[key] = open_interest + (previous or 0.0)

    ranked: list[dict[str, Any]] = []
    for strike, bucket in buckets.items():
        values = [
            value
            for value in (
                bucket["call_open_interest"],
                bucket["put_open_interest"],
            )
            if value is not None
        ]
        ranked.append(
            {
                "strike": strike,
                **bucket,
                "total_open_interest": sum(values) if values else None,
            }
        )

    ranked.sort(
        key=lambda row: (
            row["total_open_interest"] is not None,
            row["total_open_interest"] or 0.0,
            -row["strike"],
        ),
        reverse=True,
    )
    return ranked[:top_n]


def _atm_summary(
    calls: list[dict[str, Any]],
    puts: list[dict[str, Any]],
    underlying_price: float | None,
) -> dict[str, Any]:
    strikes = sorted(
        {
            strike
            for row in calls + puts
            if (strike := _number(row.get("strike"))) is not None
        }
    )
    if underlying_price is None or underlying_price <= 0 or not strikes:
        return {
            "strike": None,
            "call_implied_volatility": None,
            "put_implied_volatility": None,
        }

    strike = min(strikes, key=lambda value: (abs(value - underlying_price), value))

    def iv_for(rows: list[dict[str, Any]]) -> float | None:
        for row in rows:
            if _number(row.get("strike")) == strike:
                return _number(row.get("impliedVolatility"))
        return None

    return {
        "strike": strike,
        "call_implied_volatility": iv_for(calls),
        "put_implied_volatility": iv_for(puts),
    }


def _activity_view(
    row: dict[str, Any],
    *,
    expiry: str,
    option_type: Literal["call", "put"],
    underlying_price: float | None,
) -> dict[str, Any]:
    view = _contract_view(row)
    strike = view["strike"]
    moneyness_pct = None
    if (
        strike is not None
        and underlying_price is not None
        and underlying_price > 0
    ):
        moneyness_pct = ((strike / underlying_price) - 1.0) * 100.0

    return {
        "expiry": expiry,
        "option_type": option_type,
        **view,
        "moneyness_pct_from_spot": moneyness_pct,
        "in_the_money": row.get("inTheMoney"),
    }


class OptionsService:
    def __init__(self, provider: YFinanceProvider | None = None) -> None:
        self._provider = provider or YFinanceProvider()

    def _expiration_window(
        self,
        symbol: str,
        *,
        start_index: int,
        max_expiries: int,
    ) -> tuple[list[str], list[str]]:
        if start_index < 0:
            raise ValueError("start_index must be non-negative")
        if max_expiries <= 0 or max_expiries > 12:
            raise ValueError("max_expiries must be between 1 and 12")

        available = list(self._provider.option_expirations(symbol))
        if available and start_index >= len(available):
            raise ValueError("start_index is beyond available expirations")
        return available, available[start_index : start_index + max_expiries]

    def option_surface_summary(
        self,
        symbol: str,
        *,
        start_index: int = 0,
        max_expiries: int = 8,
        top_n: int = 3,
    ) -> dict[str, Any]:
        if top_n <= 0 or top_n > 10:
            raise ValueError("top_n must be between 1 and 10")

        available, selected = self._expiration_window(
            symbol,
            start_index=start_index,
            max_expiries=max_expiries,
        )
        rows: list[dict[str, Any]] = []
        first_underlying: dict[str, Any] | None = None
        latest_retrieved_at: str | None = None

        for expiry in selected:
            snapshot = self._provider.option_chain(symbol, expiry)
            underlying = _underlying_summary(snapshot.underlying)
            if first_underlying is None:
                first_underlying = underlying
            latest_retrieved_at = snapshot.retrieved_at

            calls = snapshot.calls
            puts = snapshot.puts
            call_summary = _compact_side_summary(calls)
            put_summary = _compact_side_summary(puts)
            spot = underlying["regular_market_price"]

            rows.append(
                {
                    "expiry": snapshot.expiry,
                    "days_to_expiry": _days_to_expiry(
                        snapshot.expiry,
                        snapshot.retrieved_at,
                    ),
                    "retrieved_at": snapshot.retrieved_at,
                    "calls": call_summary,
                    "puts": put_summary,
                    "put_call": {
                        "volume_ratio": _ratio(
                            put_summary["total_volume"],
                            call_summary["total_volume"],
                        ),
                        "open_interest_ratio": _ratio(
                            put_summary["total_open_interest"],
                            call_summary["total_open_interest"],
                        ),
                        "ratio_convention": "puts divided by calls",
                    },
                    "atm": _atm_summary(calls, puts, spot),
                    "top_open_interest_strikes": _top_open_interest_strikes(
                        calls,
                        puts,
                        top_n,
                    ),
                }
            )

        return {
            "source": SOURCE,
            "retrieved_at": latest_retrieved_at,
            "symbol": symbol.strip().upper(),
            "data_quality": {
                "quote_may_be_delayed": True,
                "execution_grade": False,
                "notice": QUOTE_DELAY_NOTICE,
            },
            "selection": {
                "start_index": start_index,
                "max_expiries": max_expiries,
                "available_expiration_count": len(available),
                "selected_count": len(selected),
                "has_more": start_index + len(selected) < len(available),
            },
            "underlying": first_underlying,
            "expiries": rows,
        }

    def option_activity_summary(
        self,
        symbol: str,
        *,
        start_index: int = 0,
        max_expiries: int = 8,
        min_volume: int = 100,
        min_open_interest: int = 10,
        sort_by: ActivitySort = "volume_open_interest_ratio",
        top_n: int = 20,
    ) -> dict[str, Any]:
        if min_volume < 0:
            raise ValueError("min_volume must be non-negative")
        if min_open_interest < 0:
            raise ValueError("min_open_interest must be non-negative")
        if sort_by not in {
            "volume_open_interest_ratio",
            "volume",
            "open_interest",
        }:
            raise ValueError(
                "sort_by must be volume_open_interest_ratio, volume, or open_interest"
            )
        if top_n <= 0 or top_n > 100:
            raise ValueError("top_n must be between 1 and 100")

        available, selected = self._expiration_window(
            symbol,
            start_index=start_index,
            max_expiries=max_expiries,
        )
        candidates: list[dict[str, Any]] = []
        first_underlying: dict[str, Any] | None = None
        latest_retrieved_at: str | None = None

        for expiry in selected:
            snapshot = self._provider.option_chain(symbol, expiry)
            underlying = _underlying_summary(snapshot.underlying)
            if first_underlying is None:
                first_underlying = underlying
            latest_retrieved_at = snapshot.retrieved_at
            spot = underlying["regular_market_price"]

            for option_type, source_rows in (
                ("call", snapshot.calls),
                ("put", snapshot.puts),
            ):
                filtered = _filter_rows(
                    source_rows,
                    min_strike=None,
                    max_strike=None,
                    min_volume=min_volume,
                    min_open_interest=min_open_interest,
                    limit_per_side=None,
                )
                candidates.extend(
                    _activity_view(
                        row,
                        expiry=snapshot.expiry,
                        option_type=option_type,
                        underlying_price=spot,
                    )
                    for row in filtered
                )

        def sort_key(row: dict[str, Any]) -> tuple[bool, float, float, float]:
            primary = _number(row.get(sort_by))
            volume = _number(row.get("volume"))
            open_interest = _number(row.get("open_interest"))
            return (
                primary is not None,
                primary or 0.0,
                volume or 0.0,
                open_interest or 0.0,
            )

        candidates.sort(key=sort_key, reverse=True)
        results = candidates[:top_n]

        return {
            "source": SOURCE,
            "retrieved_at": latest_retrieved_at,
            "symbol": symbol.strip().upper(),
            "data_quality": {
                "quote_may_be_delayed": True,
                "execution_grade": False,
                "notice": QUOTE_DELAY_NOTICE,
                "activity_is_not_order_flow": True,
                "activity_notice": (
                    "Volume/open-interest activity does not reveal trade direction, "
                    "sweeps, or opening/closing intent."
                ),
            },
            "selection": {
                "start_index": start_index,
                "max_expiries": max_expiries,
                "available_expiration_count": len(available),
                "selected_count": len(selected),
                "has_more": start_index + len(selected) < len(available),
            },
            "filters": {
                "min_volume": min_volume,
                "min_open_interest": min_open_interest,
                "sort_by": sort_by,
                "top_n": top_n,
            },
            "underlying": first_underlying,
            "candidates_considered": len(candidates),
            "results": results,
        }

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
        result["underlying"] = _underlying_summary(snapshot.underlying)
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
