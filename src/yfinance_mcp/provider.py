from __future__ import annotations

import math
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import yfinance as yf

SOURCE = "yahoo_finance_via_yfinance"
QUOTE_DELAY_NOTICE = (
    "Yahoo Finance option quotes may be delayed and should not be treated as execution-grade."
)

_EXPIRATIONS_TTL_SECONDS = 15 * 60
_CHAIN_TTL_SECONDS = 60


class UpstreamDataError(RuntimeError):
    """Raised when the upstream provider cannot return usable options data."""


@dataclass(frozen=True, slots=True)
class ChainSnapshot:
    symbol: str
    expiry: str
    calls: list[dict[str, Any]]
    puts: list[dict[str, Any]]
    underlying: dict[str, Any]
    retrieved_at: str


class _TTLCache:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._values: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any | None:
        now = time.monotonic()
        with self._lock:
            item = self._values.get(key)
            if item is None:
                return None
            stored_at, value = item
            if now - stored_at >= self._ttl_seconds:
                self._values.pop(key, None)
                return None
            return deepcopy(value)

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            self._values[key] = (time.monotonic(), deepcopy(value))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("symbol must not be empty")
    if len(normalized) > 64:
        raise ValueError("symbol is too long")
    return normalized


def _normalize_expiry(expiry: str) -> str:
    normalized = expiry.strip()
    try:
        parsed = datetime.strptime(normalized, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("expiry must use YYYY-MM-DD format") from exc
    return parsed.strftime("%Y-%m-%d")


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]

    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass

    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except (TypeError, ValueError):
            pass

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    return value


def _records(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    rows = frame.to_dict(orient="records")
    return [{str(key): _jsonable(value) for key, value in row.items()} for row in rows]


class YFinanceProvider:
    """Small provider boundary around the yfinance options surface."""

    def __init__(self) -> None:
        self._expirations_cache = _TTLCache(_EXPIRATIONS_TTL_SECONDS)
        self._chain_cache = _TTLCache(_CHAIN_TTL_SECONDS)

    def option_expirations(self, symbol: str) -> tuple[str, ...]:
        normalized_symbol = _normalize_symbol(symbol)
        cached = self._expirations_cache.get(normalized_symbol)
        if cached is not None:
            return tuple(cached)

        try:
            expirations = tuple(str(value) for value in yf.Ticker(normalized_symbol).options)
        except Exception as exc:
            raise UpstreamDataError("options expirations are unavailable") from exc

        self._expirations_cache.set(normalized_symbol, expirations)
        return expirations

    def option_chain(self, symbol: str, expiry: str) -> ChainSnapshot:
        normalized_symbol = _normalize_symbol(symbol)
        normalized_expiry = _normalize_expiry(expiry)
        cache_key = (normalized_symbol, normalized_expiry)

        cached = self._chain_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            chain = yf.Ticker(normalized_symbol).option_chain(normalized_expiry)
        except ValueError as exc:
            raise ValueError(
                "expiry is not available for this symbol; call option_expirations first"
            ) from exc
        except Exception as exc:
            raise UpstreamDataError("option chain is unavailable") from exc

        snapshot = ChainSnapshot(
            symbol=normalized_symbol,
            expiry=normalized_expiry,
            calls=_records(chain.calls),
            puts=_records(chain.puts),
            underlying=_jsonable(chain.underlying or {}),
            retrieved_at=_utc_now(),
        )
        self._chain_cache.set(cache_key, snapshot)
        return snapshot
