from __future__ import annotations

import yfinance_mcp.provider as provider
from yfinance_mcp.provider import _TTLCache


def test_ttl_cache_evicts_least_recently_used_entry() -> None:
    cache = _TTLCache(ttl_seconds=60, max_entries=2)

    cache.set("a", {"value": 1})
    cache.set("b", {"value": 2})
    assert cache.get("a") == {"value": 1}

    cache.set("c", {"value": 3})

    assert cache.get("a") == {"value": 1}
    assert cache.get("b") is None
    assert cache.get("c") == {"value": 3}


def test_ttl_cache_prunes_expired_entries_on_write(monkeypatch) -> None:
    now = 100.0
    monkeypatch.setattr(provider.time, "monotonic", lambda: now)
    cache = _TTLCache(ttl_seconds=10, max_entries=2)

    cache.set("expired-a", 1)
    cache.set("expired-b", 2)

    now = 111.0
    cache.set("fresh-a", 3)
    cache.set("fresh-b", 4)

    assert cache.get("expired-a") is None
    assert cache.get("expired-b") is None
    assert cache.get("fresh-a") == 3
    assert cache.get("fresh-b") == 4


def test_ttl_cache_rejects_unbounded_configuration() -> None:
    try:
        _TTLCache(ttl_seconds=60, max_entries=0)
    except ValueError as exc:
        assert "max_entries" in str(exc)
    else:
        raise AssertionError("expected ValueError")
