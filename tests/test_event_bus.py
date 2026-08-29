"""Tests for Event Bus module (core/event_bus.py)."""

from __future__ import annotations

import pytest
from core.event_bus import Event, get_event_bus, reset_event_bus


@pytest.fixture(autouse=True)
def reset_bus():
    reset_event_bus()
    yield
    reset_event_bus()


# ── Subscription ─────────────────────────────────────────────────────────


class TestSubscription:
    def test_subscribe_sync(self):
        bus = get_event_bus()
        results = []

        def handler(event):
            results.append(event.name)

        bus.subscribe("test.event", handler)
        bus.publish("test.event", {"key": "value"})
        assert len(results) == 1
        assert results[0] == "test.event"

    def test_subscribe_decorator(self):
        bus = get_event_bus()
        results = []

        @bus.on("decorated.event")
        def handle(event):
            results.append(event.name)

        bus.publish("decorated.event")
        assert len(results) == 1

    def test_subscribe_async(self):
        bus = get_event_bus()
        results = []

        async def handler(event):
            results.append(event.name)

        bus.subscribe_async("async.event", handler)
        bus.publish("async.event")
        # Sync handlers run immediately, async handlers need await
        assert len(results) == 0  # async not awaited in sync publish

    def test_subscribe_wildcard(self):
        bus = get_event_bus()
        results = []

        @bus.on("trade.*")
        def handle(event):
            results.append(event.name)

        bus.publish("trade.executed")
        bus.publish("trade.settled")
        bus.publish("other.event")
        assert len(results) == 2
        assert "trade.executed" in results
        assert "trade.settled" in results

    def test_subscribe_wildcard_all(self):
        bus = get_event_bus()
        results = []

        @bus.on("*")
        def handle_all(event):
            results.append(event.name)

        bus.publish("anything")
        bus.publish("everything")
        assert len(results) == 2

    def test_unsubscribe(self):
        bus = get_event_bus()
        results = []

        def handler(event):
            results.append(event.name)

        bus.subscribe("test.event", handler)
        bus.publish("test.event")
        bus.unsubscribe("test.event", handler)
        bus.publish("test.event")
        assert len(results) == 1  # Only first publish triggered handler


# ── Publishing ────────────────────────────────────────────────────────────


class TestPublishing:
    def test_publish_returns_handler_count(self):
        bus = get_event_bus()
        results = []

        @bus.on("event1")
        def h1(e):
            results.append(1)

        @bus.on("event1")
        def h2(e):
            results.append(2)

        count = bus.publish("event1")
        assert count == 2

    def test_publish_with_data(self):
        bus = get_event_bus()
        results = []

        @bus.on("data.event")
        def handler(event):
            results.append(event.data)

        bus.publish("data.event", {"symbol": "NIFTY", "price": 23500})
        assert len(results) == 1
        assert results[0]["symbol"] == "NIFTY"

    def test_publish_with_source(self):
        bus = get_event_bus()
        results = []

        @bus.on("sourced.event")
        def handler(event):
            results.append(event.source)

        bus.publish("sourced.event", source="test_module")
        assert results[0] == "test_module"

    def test_publish_generates_event_id(self):
        bus = get_event_bus()
        results = []

        @bus.on("id.event")
        def handler(event):
            results.append(event.event_id)

        bus.publish("id.event")
        assert results[0].startswith("evt-")

    def test_publish_multiple_handlers_error_isolation(self):
        bus = get_event_bus()
        results = []

        @bus.on("fail.event")
        def good_handler(e):
            results.append("ok")

        @bus.on("fail.event")
        def bad_handler(e):
            raise ValueError("handler error")

        bus.publish("fail.event")
        # Good handler should still run despite bad handler
        assert len(results) == 1


# ── Async Publishing ─────────────────────────────────────────────────────


@pytest.mark.skipif(not hasattr(pytest, 'mark') or not hasattr(pytest.mark, 'asyncio'),
                    reason="pytest-asyncio not installed")
@pytest.mark.asyncio
async def test_publish_async():
    bus = get_event_bus()
    results = []

    @bus.on("async.event")
    def sync_handler(e):
        results.append("sync")

    async def async_handler(e):
        results.append("async")

    bus.subscribe_async("async.event", async_handler)
    count = await bus.publish_async("async.event")
    assert count == 2
    assert "sync" in results
    assert "async" in results


# ── History ───────────────────────────────────────────────────────────────


class TestHistory:
    def test_get_history(self):
        bus = get_event_bus()
        bus.publish("event_a")
        bus.publish("event_b")
        history = bus.get_history()
        assert len(history) == 2

    def test_get_history_filtered(self):
        bus = get_event_bus()
        bus.publish("event_a")
        bus.publish("event_b")
        bus.publish("event_a")
        history = bus.get_history(name="event_a")
        assert len(history) == 2
        assert all(e.name == "event_a" for e in history)

    def test_clear_history(self):
        bus = get_event_bus()
        bus.publish("test")
        bus.clear_history()
        assert len(bus.get_history()) == 0


# ── Statistics ────────────────────────────────────────────────────────────


class TestStats:
    def test_get_stats_empty(self):
        bus = get_event_bus()
        stats = bus.get_stats()
        assert stats["total_published"] == 0

    def test_get_stats_after_publish(self):
        bus = get_event_bus()

        @bus.on("stat.event")
        def handler(e):
            pass

        bus.publish("stat.event")
        stats = bus.get_stats()
        assert stats["total_published"] == 1
        assert stats["sync_handlers"] >= 1

    def test_get_stats_subscription(self):
        bus = get_event_bus()

        @bus.on("sub.event")
        def handler(e):
            pass

        bus.publish("sub.event")
        stats = bus.get_stats()
        subs = stats["subscriptions"]
        assert any("sub.event" in k for k in subs)


# ── Event Model ──────────────────────────────────────────────────────────


class TestEventModel:
    def test_event_to_dict(self):
        event = Event(name="test", data={"key": "val"}, source="src", timestamp=123.0, event_id="evt-1")
        d = event.to_dict()
        assert d["name"] == "test"
        assert d["data"]["key"] == "val"
        assert d["source"] == "src"


# ── Singleton ─────────────────────────────────────────────────────────────


class TestSingleton:
    def test_singleton(self):
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2

    def test_reset(self):
        bus1 = get_event_bus()
        reset_event_bus()
        bus2 = get_event_bus()
        assert bus1 is not bus2
