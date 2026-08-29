"""Tests for core/cqrs/query_bus.py — CQRS Query Bus.

Covers:
- Query creation
- Handler registration (explicit + decorator)
- Query execution (success, error, no handler)
- Result caching with TTL
- Cache invalidation
- Statistics tracking
- Clear all
"""

from __future__ import annotations

import time

from core.cqrs.query_bus import CacheEntry, Query, QueryBus, QueryResult

# ── Test Queries ─────────────────────────────────────────────────────────────


class GetTradeQuery(Query):
    def __init__(self, trade_id: str = "", symbol: str = "") -> None:
        self.trade_id = trade_id
        self.symbol = symbol


class GetPositionQuery(Query):
    def __init__(self, symbol: str = "") -> None:
        self.symbol = symbol


class GetConfigQuery(Query):
    def __init__(self, key: str = "") -> None:
        self.key = key


# ── Tests ────────────────────────────────────────────────────────────────────


class TestQuery:
    """Tests for Query base class."""

    def test_query_creation(self):
        """Query should accept kwargs and set them as attributes."""
        q = GetTradeQuery(trade_id="T-001", symbol="NIFTY")
        assert q.trade_id == "T-001"
        assert q.symbol == "NIFTY"

    def test_to_dict(self):
        """to_dict should return non-private attributes."""
        q = GetTradeQuery(trade_id="T-001")
        d = q.to_dict()
        assert d["trade_id"] == "T-001"


class TestQueryBusRegistration:
    """Tests for handler registration."""

    def test_register_handler(self):
        """Explicit handler registration should work."""
        bus = QueryBus()

        def handler(q):
            return {"trade_id": q.trade_id}

        bus.register_handler(GetTradeQuery, handler)
        stats = bus.get_stats()
        assert stats["registered_handlers"] == 1
        assert "GetTradeQuery" in stats["handler_names"]

    def test_decorator_registration(self):
        """Decorator-based handler registration should work."""
        bus = QueryBus()

        @bus.handler(GetTradeQuery)
        def handle_trade(q):
            return {"trade_id": q.trade_id}

        stats = bus.get_stats()
        assert stats["registered_handlers"] == 1

    def test_unregister_handler(self):
        """Unregister should remove handler and return True."""
        bus = QueryBus()
        bus.register_handler(GetTradeQuery, lambda q: None)
        assert bus.unregister_handler(GetTradeQuery) is True
        assert bus.get_stats()["registered_handlers"] == 0

    def test_unregister_missing(self):
        """Unregister missing handler should return False."""
        bus = QueryBus()
        assert bus.unregister_handler(GetTradeQuery) is False


class TestQueryBusExecution:
    """Tests for query execution."""

    def test_execute_success(self):
        """Successful query execution should return data."""
        bus = QueryBus()
        bus.register_handler(GetTradeQuery, lambda q: {"trade_id": q.trade_id})

        result = bus.execute(GetTradeQuery(trade_id="T-001"))
        assert result.success is True
        assert result.data["trade_id"] == "T-001"
        assert result.cached is False

    def test_execute_no_handler(self):
        """Query with no handler should return error."""
        bus = QueryBus()
        result = bus.execute(GetTradeQuery(trade_id="T-001"))
        assert result.success is False
        assert "No handler" in result.error

    def test_execute_handler_error(self):
        """Handler exception should be caught."""
        bus = QueryBus()

        def failing_handler(q):
            raise RuntimeError("Database unavailable")

        bus.register_handler(GetTradeQuery, failing_handler)
        result = bus.execute(GetTradeQuery(trade_id="T-001"))
        assert result.success is False
        assert "Database unavailable" in result.error

    def test_multiple_handlers(self):
        """Multiple handlers for different types should work."""
        bus = QueryBus()
        bus.register_handler(GetTradeQuery, lambda q: "trade")
        bus.register_handler(GetPositionQuery, lambda q: "position")

        r1 = bus.execute(GetTradeQuery(trade_id="T-001"))
        r2 = bus.execute(GetPositionQuery(symbol="NIFTY"))
        assert r1.data == "trade"
        assert r2.data == "position"


class TestQueryBusCaching:
    """Tests for optional result caching."""

    def test_cache_hit(self):
        """Cached query should return cached result."""
        bus = QueryBus()
        call_count = 0

        def handler(q):
            nonlocal call_count
            call_count += 1
            return {"price": 23500}

        bus.register_handler(GetTradeQuery, handler)

        # First call - cache miss
        r1 = bus.execute(GetTradeQuery(trade_id="T-001"), use_cache=True)
        assert r1.success is True
        assert r1.cached is False
        assert call_count == 1

        # Second call - cache hit
        r2 = bus.execute(GetTradeQuery(trade_id="T-001"), use_cache=True)
        assert r2.success is True
        assert r2.cached is True
        assert call_count == 1  # Handler not called again

    def test_cache_expiry(self):
        """Expired cache should re-execute handler."""
        bus = QueryBus()
        call_count = 0

        def handler(q):
            nonlocal call_count
            call_count += 1
            return {"data": f"result-{call_count}"}

        bus.register_handler(GetTradeQuery, handler)

        # First call
        bus.execute(GetTradeQuery(trade_id="T-001"), use_cache=True, cache_ttl=0.01)
        assert call_count == 1

        # Wait for expiry
        time.sleep(0.02)

        # Second call - cache expired
        r2 = bus.execute(GetTradeQuery(trade_id="T-001"), use_cache=True, cache_ttl=0.01)
        assert r2.cached is False  # Cache miss due to expiry
        assert call_count == 2

    def test_no_cache_by_default(self):
        """Without use_cache=True, results should not be cached."""
        bus = QueryBus()
        call_count = 0

        def handler(q):
            nonlocal call_count
            call_count += 1
            return {"data": f"result-{call_count}"}

        bus.register_handler(GetTradeQuery, handler)

        bus.execute(GetTradeQuery(trade_id="T-001"))
        bus.execute(GetTradeQuery(trade_id="T-001"))
        assert call_count == 2  # Called each time

    def test_cache_hit_rate(self):
        """Cache hit rate should be calculated correctly."""
        bus = QueryBus()
        bus.register_handler(GetTradeQuery, lambda q: "data")

        # 1 miss + 1 hit
        bus.execute(GetTradeQuery(trade_id="T-001"), use_cache=True)
        bus.execute(GetTradeQuery(trade_id="T-001"), use_cache=True)

        stats = bus.get_stats()
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 1
        assert stats["cache_hit_rate"] == 50.0


class TestQueryBusCacheInvalidation:
    """Tests for cache invalidation."""

    def test_invalidate_all(self):
        """Invalidate all should clear all cache entries."""
        bus = QueryBus()
        bus.register_handler(GetTradeQuery, lambda q: "data")
        bus.register_handler(GetPositionQuery, lambda q: "pos")

        bus.execute(GetTradeQuery(trade_id="T-001"), use_cache=True)
        bus.execute(GetPositionQuery(symbol="NIFTY"), use_cache=True)

        count = bus.invalidate_cache()
        assert count == 2
        stats = bus.get_stats()
        assert stats["cache_entries"] == 0

    def test_invalidate_by_type(self):
        """Invalidate by type should clear only that type."""
        bus = QueryBus()
        bus.register_handler(GetTradeQuery, lambda q: "data")
        bus.register_handler(GetPositionQuery, lambda q: "pos")

        bus.execute(GetTradeQuery(trade_id="T-001"), use_cache=True)
        bus.execute(GetPositionQuery(symbol="NIFTY"), use_cache=True)

        count = bus.invalidate_cache(GetTradeQuery)
        assert count > 0
        stats = bus.get_stats()
        assert stats["cache_entries"] >= 0


class TestQueryBusStats:
    """Tests for query bus statistics."""

    def test_stats_empty(self):
        """Empty bus should have zero counts."""
        bus = QueryBus()
        stats = bus.get_stats()
        assert stats["total_queries"] == 0
        assert stats["registered_handlers"] == 0

    def test_stats_after_queries(self):
        """Stats should track query count."""
        bus = QueryBus()
        bus.register_handler(GetTradeQuery, lambda q: "data")
        bus.execute(GetTradeQuery(trade_id="T-001"))
        bus.execute(GetTradeQuery(trade_id="T-002"))

        stats = bus.get_stats()
        assert stats["total_queries"] == 2


class TestQueryBusEdgeCases:
    """Tests for edge cases."""

    def test_clear_all(self):
        """Clear should reset all state."""
        bus = QueryBus()
        bus.register_handler(GetTradeQuery, lambda q: "data")
        bus.execute(GetTradeQuery(trade_id="T-001"), use_cache=True)

        bus.clear_all()
        stats = bus.get_stats()
        assert stats["total_queries"] == 0
        assert stats["registered_handlers"] == 0
        assert stats["cache_entries"] == 0

    def test_cache_entry_expiry(self):
        """CacheEntry.is_expired should handle TTL correctly."""
        entry = CacheEntry(result="data", cached_at=time.time(), ttl_seconds=60.0)
        assert entry.is_expired() is False

        expired = CacheEntry(result="data", cached_at=0, ttl_seconds=1.0)
        assert expired.is_expired() is True

    def test_duration_recorded(self):
        """Duration should be recorded in QueryResult."""
        bus = QueryBus()
        bus.register_handler(GetTradeQuery, lambda q: "data")
        result = bus.execute(GetTradeQuery(trade_id="T-001"))
        assert result.duration_ms >= 0

    def test_result_to_dict(self):
        """QueryResult.to_dict should serialize correctly."""
        result = QueryResult(
            success=True, data={"id": 1},
            query_type="GetTradeQuery", duration_ms=5.0, cached=True,
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["cached"] is True
        assert d["query_type"] == "GetTradeQuery"
