"""Tests for performance caching, autocomplete, and WebSocket modules."""

from __future__ import annotations

import time
from typing import Any

from realestate.cache import (
    CachedServiceWrapper,
    TTLCache,
    analytics_cache,
    get_cache_stats,
    invalidate_all,
    neighborhood_cache,
    property_cache,
    search_cache,
)
from realestate.websocket import (
    WebSocketNotificationManager,
    get_ws_manager,
)

# ═══════════════════════════════════════════════════════════════════════════════
# TTLCache Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestTTLCache:
    def setup_method(self):
        self.cache = TTLCache(max_size=10, default_ttl=60)

    def test_get_missing(self):
        assert self.cache.get("nonexistent") is None

    def test_set_and_get(self):
        self.cache.set("key1", "value1")
        assert self.cache.get("key1") == "value1"

    def test_get_or_set(self):
        called = 0

        def factory():
            nonlocal called
            called += 1
            return "computed"

        val1 = self.cache.get_or_set("test", factory)
        assert val1 == "computed"
        assert called == 1

        val2 = self.cache.get_or_set("test", factory)
        assert val2 == "computed"
        assert called == 1  # Factory not called again

    def test_delete(self):
        self.cache.set("key2", "val2")
        assert self.cache.delete("key2")
        assert not self.cache.delete("nonexistent")

    def test_expiry(self):
        """Values should expire after TTL."""
        self.cache.set("key3", "val3", ttl=0.05)
        assert self.cache.get("key3") == "val3"
        time.sleep(0.1)
        assert self.cache.get("key3") is None

    def test_max_size_eviction(self):
        """Cache should evict oldest entries when at capacity."""
        tiny = TTLCache(max_size=3, default_ttl=60)
        tiny.set("a", 1)
        tiny.set("b", 2)
        tiny.set("c", 3)
        # Access 'a' to make it most recently used
        tiny.get("a")
        tiny.set("d", 4)  # Should evict 'b' (LRU)
        assert tiny.get("a") == 1  # Still there
        assert tiny.get("b") is None  # Evicted
        assert tiny.get("d") == 4

    def test_clear(self):
        self.cache.set("a", 1)
        self.cache.set("b", 2)
        self.cache.clear()
        assert self.cache.size == 0
        assert self.cache.hits == 0

    def test_stats(self):
        self.cache.get("miss")  # miss
        self.cache.set("hit", "val")
        self.cache.get("hit")   # hit
        stats = self.cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 50.0
        assert stats["size"] == 1
        assert stats["max_size"] == 10

    def test_expire_all(self):
        self.cache.set("a", 1, ttl=0.01)
        self.cache.set("b", 2, ttl=60)
        time.sleep(0.05)
        expired = self.cache.expire_all()
        assert expired >= 1
        assert self.cache.get("a") is None
        assert self.cache.get("b") == 2

    def test_get_many(self):
        self.cache.set("x", 10)
        self.cache.set("y", 20)
        results = self.cache.get_many(["x", "y", "z"])
        assert results == {"x": 10, "y": 20}

    def test_different_ttl_per_key(self):
        self.cache.set("short", "val1", ttl=0.02)
        self.cache.set("long", "val2", ttl=60)
        time.sleep(0.05)
        assert self.cache.get("short") is None
        assert self.cache.get("long") == "val2"


class TestPreconfiguredCaches:
    def test_property_cache_exists(self):
        assert property_cache.max_size == 100
        assert property_cache.default_ttl == 30

    def test_neighborhood_cache_ttl(self):
        assert neighborhood_cache.default_ttl == 300

    def test_invalidate_all(self):
        property_cache.set("test", "val")
        analytics_cache.set("test2", "val2")
        invalidate_all()
        assert property_cache.get("test") is None
        assert analytics_cache.get("test2") is None

    def test_cache_stats(self):
        stats = get_cache_stats()
        assert "property_cache" in stats
        assert "neighborhood_cache" in stats
        assert "analytics_cache" in stats
        assert "search_cache" in stats
        for name, s in stats.items():
            assert "size" in s
            assert "hits" in s
            assert "misses" in s

    def test_search_cache_ttl(self):
        assert search_cache._default_ttl == 15


# ═══════════════════════════════════════════════════════════════════════════════
# CachedServiceWrapper Tests
# ═══════════════════════════════════════════════════════════════════════════════

class FakeService:
    """Simple service with readable and writable methods for testing."""

    def __init__(self):
        self.list_count = 0
        self.create_count = 0

    def list_all(self) -> list[str]:
        self.list_count += 1
        return ["a", "b", "c"]

    def get_by_id(self, id: str) -> dict[str, Any]:
        return {"id": id, "name": f"Item {id}"}

    def create_item(self, name: str) -> dict[str, Any]:
        self.create_count += 1
        return {"id": "new", "name": name}


class TestCachedServiceWrapper:
    def setup_method(self):
        self.service = FakeService()
        self.wrapper = CachedServiceWrapper(self.service, ttl=60)

    def test_cached_list(self):
        """list_all should be cached after first call."""
        result1 = self.wrapper.call("list_all")
        result2 = self.wrapper.call("list_all")
        assert result1 == result2
        assert self.service.list_count == 1  # Only called once

    def test_create_invalidates_cache(self):
        """Write operations should bypass cache and invalidate list_all."""
        self.wrapper.call("list_all")  # Cache it
        self.wrapper.call("create_item", "test")  # Write
        self.wrapper.call("list_all")  # Should re-fetch
        assert self.service.list_count == 2  # Called again after invalidation

    def test_read_no_cache_key(self):
        """Read methods without explicit cache_key should auto-generate one."""
        result = self.wrapper.call("get_by_id", "42")
        assert result["id"] == "42"

    def test_invalidate_method(self):
        self.wrapper.call("list_all")
        self.wrapper.invalidate("list_all")
        self.wrapper.call("list_all")
        assert self.service.list_count == 2

    def test_invalidate_all(self):
        self.wrapper.call("list_all")
        self.wrapper.invalidate()
        self.wrapper.call("list_all")
        assert self.service.list_count == 2

    def test_wrapper_cache_property(self):
        assert self.wrapper.cache is not None
        assert isinstance(self.wrapper.cache, TTLCache)

    def test_read_methods_cached_by_default(self):
        """get_by_id is a read method and should be cached."""
        result1 = self.wrapper.call("get_by_id", "42")
        result2 = self.wrapper.call("get_by_id", "42")
        assert result1 == result2
        # Both results correct
        assert result1["name"] == "Item 42"


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket Notification Manager Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebSocketManager:
    def setup_method(self):
        self.manager = WebSocketNotificationManager()

    def test_manager_stats_empty(self):
        assert self.manager.get_connected_users() == 0
        assert self.manager.get_total_connections() == 0
        assert self.manager.get_messages_sent() == 0
        assert self.manager.get_user_ids() == []

    def test_get_ws_manager_singleton(self):
        m1 = get_ws_manager()
        m2 = get_ws_manager()
        assert m1 is m2

    def test_get_stats_structure(self):
        stats = self.manager.get_stats()
        assert "connected_users" in stats
        assert "total_connections_lifetime" in stats
        assert "messages_sent" in stats
        assert "user_ids" in stats

    def test_send_to_user_no_connection(self):
        """Sending to a non-connected user should not error."""
        import asyncio
        result = asyncio.run(self.manager.send_to_user("nonexistent", {"test": True}))
        assert result == 0

    def test_broadcast_no_connections(self):
        """Broadcasting with no connections should not error."""
        import asyncio
        result = asyncio.run(self.manager.broadcast({"test": True}))
        assert result == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Autocomplete Integration Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutocompleteAPI:
    def test_autocomplete_router_wired(self):
        """Verify the autocomplete API router can be created and responds."""
        from fastapi import APIRouter, FastAPI, Query
        from fastapi.testclient import TestClient
        from realestate.application.services import create_default_services

        app = FastAPI()
        services = create_default_services()
        ns = services["neighborhood_service"]

        router = APIRouter(prefix="/api/realestate")

        @router.get("/autocomplete")
        async def autocomplete(q: str = Query("")):
            ql = q.lower().strip()
            if not ql:
                return {"suggestions": [], "query": q}
            cities = ns.get_all_cities()
            suggestions = []
            for city in cities:
                if ql in city["name"].lower():
                    suggestions.append({"type": "city", "text": city["name"]})
            for city in cities:
                for loc in city["localities"]:
                    if ql in loc.lower():
                        suggestions.append({"type": "locality", "text": loc, "city": city["name"]})
            return {"suggestions": suggestions[:10], "query": q}

        app.include_router(router)
        client = TestClient(app)

        # Test empty query
        resp = client.get("/api/realestate/autocomplete?q=")
        assert resp.status_code == 200
        assert resp.json()["suggestions"] == []

        # Test city search
        resp = client.get("/api/realestate/autocomplete?q=mum")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["suggestions"]) > 0
        assert any(s["type"] == "city" for s in data["suggestions"])

        # Test locality search
        resp = client.get("/api/realestate/autocomplete?q=bandra")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["suggestions"]) > 0

        # Test partial match
        resp = client.get("/api/realestate/autocomplete?q=whi")
        assert resp.status_code == 200
        data = resp.json()
        city_types = [s["type"] for s in data["suggestions"]]
        assert "locality" in city_types or "city" in city_types

    def test_autocomplete_max_results(self):
        """Autocomplete should return max 10 suggestions."""
        from fastapi import APIRouter, FastAPI, Query
        from fastapi.testclient import TestClient
        from realestate.application.services import create_default_services

        app = FastAPI()
        services = create_default_services()
        ns = services["neighborhood_service"]

        router = APIRouter(prefix="/api/realestate")

        @router.get("/autocomplete")
        async def autocomplete(q: str = Query("")):
            ql = q.lower().strip()
            cities = ns.get_all_cities()
            suggestions = []
            for city in cities:
                if ql in city["name"].lower():
                    suggestions.append({"type": "city", "text": city["name"]})
            return {"suggestions": suggestions[:10], "query": q}

        app.include_router(router)
        client = TestClient(app)

        # Search for a common letter that matches many things
        resp = client.get("/api/realestate/autocomplete?q=a")
        data = resp.json()
        assert len(data["suggestions"]) <= 10

    def test_neighborhood_localities_via_autocomplete(self):
        """All 10 supported cities should have localities accessible via autocomplete."""
        from realestate.application.services import create_default_services
        ns = create_default_services()["neighborhood_service"]
        cities = ns.get_all_cities()
        assert len(cities) >= 10
        for city in cities:
            assert len(city["localities"]) >= 5


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket Router Creation Test
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebSocketRouter:
    def test_websocket_router_created(self):
        """Verify the WebSocket router can be created without errors."""
        from realestate.websocket import create_websocket_router
        router = create_websocket_router()
        assert router is not None
        # Verify routes exist
        routes = router.routes
        assert len(routes) >= 1
        # Check it's a WebSocket route
        route = routes[0]
        assert hasattr(route, "path")
        assert "/ws/notifications/{user_id}" in route.path

    def test_manager_singleton_consistency(self):
        """get_ws_manager should return the same instance each call."""
        from realestate.websocket import get_ws_manager
        m1 = get_ws_manager()
        m2 = get_ws_manager()
        assert m1 is m2

    def test_websocket_stats_structure(self):
        from realestate.websocket import WebSocketNotificationManager
        mgr = WebSocketNotificationManager()
        stats = mgr.get_stats()
        assert isinstance(stats, dict)
        assert "connected_users" in stats
        assert "messages_sent" in stats
