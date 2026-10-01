from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

import yfinance as yf

SOURCE = "yahoo_finance_via_yfinance"
NewsTab = Literal["news", "all", "press releases"]

_MAX_NEWS_COUNT = 50
_MAX_BATCH_SYMBOLS = 100


class NewsUpstreamDataError(RuntimeError):
    """Raised when Yahoo/yfinance news cannot return usable data."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        raise ValueError("symbol must not be empty")
    if len(normalized) > 64:
        raise ValueError("symbol is too long")
    return normalized


def _validate_count(count: int) -> int:
    if count <= 0 or count > _MAX_NEWS_COUNT:
        raise ValueError(f"count must be between 1 and {_MAX_NEWS_COUNT}")
    return int(count)


def _validate_tab(tab: str) -> NewsTab:
    if tab not in {"news", "all", "press releases"}:
        raise ValueError("tab must be news, all, or press releases")
    return tab  # type: ignore[return-value]


def _published_at(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC).isoformat()
        except ValueError:
            return None
    return None


def _related_tickers(item: dict[str, Any]) -> list[str]:
    values = item.get("relatedTickers") or item.get("related_tickers") or []
    if not isinstance(values, list):
        return []
    return [str(value).strip().upper() for value in values if str(value).strip()]


def _content(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("content")
    return value if isinstance(value, dict) else item


def _provider_name(content: dict[str, Any]) -> str | None:
    provider = content.get("provider")
    if isinstance(provider, dict):
        value = provider.get("displayName") or provider.get("name") or provider.get("id")
        return str(value).strip() if value else None
    publisher = content.get("publisher")
    return str(publisher).strip() if publisher else None


def _canonical_url(content: dict[str, Any]) -> str | None:
    for key in ("canonicalUrl", "clickThroughUrl"):
        value = content.get(key)
        if isinstance(value, dict):
            url = value.get("url")
            if url:
                return str(url)
        elif isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("link", "url"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def normalize_news_item(symbol: str, item: dict[str, Any]) -> dict[str, Any] | None:
    content = _content(item)
    title = content.get("title") or item.get("title")
    if not isinstance(title, str) or not title.strip():
        return None

    uuid = (
        content.get("id")
        or content.get("uuid")
        or item.get("id")
        or item.get("uuid")
    )
    published = (
        content.get("pubDate")
        or content.get("providerPublishTime")
        or content.get("published_at")
        or item.get("providerPublishTime")
        or item.get("published_at")
    )
    content_type = content.get("contentType") or content.get("type") or item.get("type")

    return {
        "symbol": symbol,
        "id": str(uuid).strip() if uuid else None,
        "title": title.strip(),
        "publisher": _provider_name(content),
        "published_at": _published_at(published),
        "url": _canonical_url(content),
        "related_tickers": _related_tickers(content) or _related_tickers(item),
        "content_type": str(content_type).strip() if content_type else None,
    }


class NewsService:
    """Bounded read-only Yahoo Finance news discovery via yfinance."""

    def news_get(
        self,
        symbol: str,
        *,
        count: int = 20,
        tab: NewsTab = "all",
    ) -> dict[str, Any]:
        normalized_symbol = _normalize_symbol(symbol)
        count = _validate_count(count)
        tab = _validate_tab(tab)

        try:
            raw = yf.Ticker(normalized_symbol).get_news(count=count, tab=tab)
        except Exception as exc:
            raise NewsUpstreamDataError("news is unavailable") from exc

        if raw is None:
            raw = []
        if not isinstance(raw, list):
            raise NewsUpstreamDataError("news payload is malformed")

        items = [
            normalized
            for item in raw
            if isinstance(item, dict)
            and (normalized := normalize_news_item(normalized_symbol, item)) is not None
        ]
        return {
            "source": SOURCE,
            "retrieved_at": _utc_now(),
            "symbol": normalized_symbol,
            "tab": tab,
            "requested_count": count,
            "count": len(items),
            "items": items,
            "data_quality": {
                "discovery_only": True,
                "verification_required_for_material_claims": True,
                "notice": (
                    "Yahoo Finance may syndicate wire stories and press releases. "
                    "Preserve publisher provenance and verify material claims against "
                    "primary or authoritative wire sources."
                ),
            },
        }

    def news_batch(
        self,
        symbols: list[str],
        *,
        count_per_symbol: int = 10,
        tab: NewsTab = "all",
    ) -> dict[str, Any]:
        if not isinstance(symbols, list) or not symbols:
            raise ValueError("symbols must be a non-empty array")
        if len(symbols) > _MAX_BATCH_SYMBOLS:
            raise ValueError(f"symbols may contain at most {_MAX_BATCH_SYMBOLS} entries")
        count_per_symbol = _validate_count(count_per_symbol)
        tab = _validate_tab(tab)

        normalized_symbols = list(dict.fromkeys(_normalize_symbol(value) for value in symbols))
        results: list[dict[str, Any]] = []
        failed_symbols: list[str] = []
        for symbol in normalized_symbols:
            try:
                result = self.news_get(symbol, count=count_per_symbol, tab=tab)
            except NewsUpstreamDataError:
                failed_symbols.append(symbol)
                continue
            results.append({
                "symbol": symbol,
                "count": result["count"],
                "items": result["items"],
            })

        return {
            "source": SOURCE,
            "retrieved_at": _utc_now(),
            "tab": tab,
            "count_per_symbol": count_per_symbol,
            "requested_symbols": normalized_symbols,
            "successful_symbols": [item["symbol"] for item in results],
            "failed_symbols": failed_symbols,
            "items": results,
            "coverage_complete": not failed_symbols,
            "data_quality": {
                "discovery_only": True,
                "verification_required_for_material_claims": True,
                "notice": (
                    "Batch results are bounded per symbol and may contain syndicated duplicates "
                    "across publishers or upstream sources. Canonicalize downstream."
                ),
            },
        }
