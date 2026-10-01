from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from yfinance_mcp.news import NewsService, NewsUpstreamDataError, normalize_news_item


def test_normalize_news_item_handles_nested_yfinance_shape() -> None:
    item = {
        "content": {
            "id": "abc-123",
            "title": "Example raises guidance",
            "provider": {"displayName": "Reuters"},
            "pubDate": "2026-10-01T12:30:00Z",
            "canonicalUrl": {"url": "https://example.test/story"},
            "contentType": "STORY",
            "relatedTickers": ["EXM", "PEER"],
        }
    }

    result = normalize_news_item("EXM", item)

    assert result == {
        "symbol": "EXM",
        "id": "abc-123",
        "title": "Example raises guidance",
        "publisher": "Reuters",
        "published_at": "2026-10-01T12:30:00+00:00",
        "url": "https://example.test/story",
        "related_tickers": ["EXM", "PEER"],
        "content_type": "STORY",
    }


def test_news_get_is_bounded_and_preserves_provenance() -> None:
    ticker = Mock()
    ticker.get_news.return_value = [{
        "content": {
            "id": "wire-1",
            "title": "Example wins contract",
            "provider": {"displayName": "Reuters"},
            "providerPublishTime": 1790856000,
            "clickThroughUrl": {"url": "https://example.test/wire-1"},
        }
    }]
    with patch("yfinance_mcp.news.yf.Ticker", return_value=ticker):
        result = NewsService().news_get("exm", count=5, tab="all")

    ticker.get_news.assert_called_once_with(count=5, tab="all")
    assert result["symbol"] == "EXM"
    assert result["requested_count"] == 5
    assert result["items"][0]["publisher"] == "Reuters"
    assert result["data_quality"]["verification_required_for_material_claims"] is True


def test_news_batch_reports_partial_coverage_without_hiding_successes() -> None:
    good = Mock()
    good.get_news.return_value = [{"title": "Good story", "publisher": "Newswire"}]
    bad = Mock()
    bad.get_news.side_effect = RuntimeError("upstream")

    def factory(symbol: str):
        return good if symbol == "GOOD" else bad

    with patch("yfinance_mcp.news.yf.Ticker", side_effect=factory):
        result = NewsService().news_batch(["GOOD", "BAD", "GOOD"], count_per_symbol=3)

    assert result["requested_symbols"] == ["GOOD", "BAD"]
    assert result["successful_symbols"] == ["GOOD"]
    assert result["failed_symbols"] == ["BAD"]
    assert result["coverage_complete"] is False
    assert result["items"][0]["count"] == 1


@pytest.mark.parametrize("count", [0, 51])
def test_news_count_bounds(count: int) -> None:
    with pytest.raises(ValueError, match="count"):
        NewsService().news_get("TEST", count=count)


def test_news_batch_rejects_unbounded_symbol_set() -> None:
    with pytest.raises(ValueError, match="at most"):
        NewsService().news_batch([f"S{i}" for i in range(101)])


def test_news_upstream_error_is_explicit() -> None:
    ticker = Mock()
    ticker.get_news.side_effect = RuntimeError("boom")
    with patch("yfinance_mcp.news.yf.Ticker", return_value=ticker):
        with pytest.raises(NewsUpstreamDataError):
            NewsService().news_get("TEST")
