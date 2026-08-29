"""Tests for Unified EventStore (TD-02 consolidation).

Tests the unified EventStore from ``core.event_store`` which consolidates:
  - JSON-file-backed stream store (from core.event_sourcing)
  - SQLite-backed TradingEvent store (from core.execution.event_system)
"""

from __future__ import annotations

import gc

import pytest
from core.event_store import (
    Snapshot,
    StoredEvent,
    get_event_store,
    reset_event_store,
)


class TestUnifiedEventStore:
    """Test suite for the unified EventStore."""

    @pytest.fixture(autouse=True)
    def _reset_store(self) -> None:
        """Reset singleton before each test."""
        reset_event_store()
        gc.collect()  # Force cleanup of any lingering references

    def test_get_event_store_singleton(self):
        """get_event_store returns the same instance."""
        s1 = get_event_store()
        s2 = get_event_store()
        assert s1 is s2

    def test_reset_event_store(self):
        """reset_event_store clears the singleton."""
        s1 = get_event_store()
        reset_event_store()
        s2 = get_event_store()
        assert s1 is not s2

    def test_append_and_read_stream(self):
        """Append an event and read it back."""
        store = get_event_store()
        event = store.append("trade.executed", stream="NIFTY", data={"qty": 50})
        assert event.event_type == "trade.executed"
        assert event.stream == "NIFTY"
        assert event.version == 1
        assert event.event_hash != ""

        events = store.read_stream("NIFTY")
        assert len(events) == 1
        assert events[0].event_id == event.event_id

    def test_append_multiple_events(self):
        """Append multiple events to a stream."""
        store = get_event_store()
        store.append("signal.generated", stream="BANKNIFTY", data={"score": 75})
        store.append("risk.approved", stream="BANKNIFTY", data={"limit": 10000})
        events = store.read_stream("BANKNIFTY")
        assert len(events) == 2
        assert events[0].version == 1
        assert events[1].version == 2
        # Verify hash chain
        assert events[1].previous_event_hash == events[0].event_hash

    def test_hash_chain_integrity(self):
        """Hash chain should form an unbroken sequence."""
        store = get_event_store()
        store.append("event.a", stream="TEST", data={"n": 1})
        store.append("event.b", stream="TEST", data={"n": 2})
        store.append("event.c", stream="TEST", data={"n": 3})
        valid, count, msg = store.verify_chain("TEST")
        assert valid is True
        assert count == 3

    def test_hash_chain_detects_tamper(self):
        """Tampering with an event hash should be detected."""
        store = get_event_store()
        store.append("event.a", stream="TAMPER", data={"n": 1})
        store.append("event.b", stream="TAMPER", data={"n": 2})

        # Tamper with the second event's hash
        with store._lock:
            store._streams["TAMPER"][1].event_hash = "tampered"

        valid, count, msg = store.verify_chain("TAMPER")
        assert valid is False

    def test_read_stream_with_version_range(self):
        """read_stream with from_version and to_version returns subset."""
        store = get_event_store()
        for i in range(1, 6):
            store.append("test.event", stream="RANGE", data={"i": i})
        events = store.read_stream("RANGE", from_version=2, to_version=4)
        assert len(events) == 3
        assert [e.version for e in events] == [2, 3, 4]

    def test_stream_exists(self):
        """stream_exists returns True for existing streams."""
        store = get_event_store()
        assert store.stream_exists("NONEXISTENT") is False
        store.append("test", stream="EXISTENT", data={})
        assert store.stream_exists("EXISTENT") is True

    def test_get_stream_version(self):
        """get_stream_version returns the event count."""
        store = get_event_store()
        assert store.get_stream_version("NEW") == 0
        store.append("test", stream="NEW", data={})
        assert store.get_stream_version("NEW") == 1
        store.append("test", stream="NEW", data={})
        assert store.get_stream_version("NEW") == 2

    def test_delete_stream(self):
        """delete_stream removes the stream."""
        store = get_event_store()
        store.append("test", stream="DELETE_ME", data={})
        assert store.stream_exists("DELETE_ME") is True
        store.delete_stream("DELETE_ME")
        assert store.stream_exists("DELETE_ME") is False

    def test_delete_nonexistent_stream(self):
        """delete_stream returns False for nonexistent streams."""
        store = get_event_store()
        assert store.delete_stream("GHOST") is False

    def test_read_all_streams(self):
        """read_all_streams returns all streams."""
        store = get_event_store()
        store.append("test", stream="A", data={})
        store.append("test", stream="B", data={})
        all_s = store.read_all_streams()
        assert "A" in all_s
        assert "B" in all_s
        assert len(all_s) == 2

    def test_replay_stream(self):
        """replay_stream replays events through a handler."""
        store = get_event_store()
        store.append("evt", stream="REPLAY", data={"val": 10})
        store.append("evt", stream="REPLAY", data={"val": 20})

        results = store.replay_stream("REPLAY", lambda e: e.data.get("val"))
        assert 10 in results
        assert 20 in results

    def test_replay_all(self):
        """replay_all replays all streams."""
        store = get_event_store()
        store.append("evt", stream="S1", data={"v": 1})
        store.append("evt", stream="S2", data={"v": 2})
        results = store.replay_all(lambda e: e.data.get("v"))
        assert "S1" in results
        assert "S2" in results

    def test_snapshot_create_and_get(self):
        """create_snapshot and get_snapshot roundtrip."""
        store = get_event_store()
        store.append("evt", stream="SNAP", data={"state": "initial"})
        snap = store.create_snapshot("SNAP", {"position": 10, "pnl": 500})
        assert snap.stream == "SNAP"
        assert snap.version == 1
        assert snap.state["position"] == 10

        retrieved = store.get_snapshot("SNAP")
        assert retrieved is not None
        assert retrieved.state == snap.state

    def test_snapshot_nonexistent(self):
        """get_snapshot returns None for streams without snapshots."""
        store = get_event_store()
        assert store.get_snapshot("NO_SNAP") is None

    def test_get_stats(self):
        """get_stats returns expected fields."""
        store = get_event_store()
        store.append("evt", stream="STATS", data={})
        stats = store.get_stats()
        assert "total_events" in stats
        assert "total_streams" in stats
        assert "events_by_type" in stats
        assert stats["total_events"] >= 1

    def test_get_events_by_type(self):
        """get_events_by_type filters by event type."""
        store = get_event_store()
        store.append("type.A", stream="T", data={})
        store.append("type.B", stream="T", data={})
        store.append("type.A", stream="T", data={})
        events = store.get_events_by_type("type.A")
        assert len(events) == 2
        assert all(e.event_type == "type.A" for e in events)

    def test_clear_all(self):
        """clear_all removes all events."""
        store = get_event_store()
        store.append("evt", stream="CLR", data={})
        store.clear_all()
        assert store.get_stats()["total_events"] == 0

    def test_append_event_with_dict_like(self):
        """append_event accepts dict-like objects."""
        store = get_event_store()
        obj = type("FakeTradingEvent", (), {
            "to_dict": lambda self: {
                "event_id": "test-001",
                "event_type": "ORDER_SUBMITTED",
                "symbol": "NIFTY",
                "direction": "BUY",
                "quantity": 50,
                "price": 23500.0,
            },
        })()
        result = store.append_event(obj)
        assert result is True
        assert store.stream_exists("NIFTY")

    def test_get_events_in_range(self):
        """get_events_in_range returns events within time range."""
        store = get_event_store()
        import time
        store.append("evt", stream="RNG", data={"seq": 1})
        store.append("evt", stream="RNG", data={"seq": 2})
        ts2 = str(time.time() + 1)
        events = store.get_events_in_range("0", ts2)
        assert len(events) >= 2


class TestStoredEvent:
    """Test suite for StoredEvent model."""

    def test_to_dict(self):
        """to_dict returns all fields."""
        event = StoredEvent(
            event_id="evt-1", event_type="test", stream="S",
            data={"key": "val"}, version=1, timestamp=123.0,
            event_hash="abc", previous_event_hash="def",
        )
        d = event.to_dict()
        assert d["event_id"] == "evt-1"
        assert d["event_type"] == "test"
        assert d["stream"] == "S"
        assert d["data"] == {"key": "val"}
        assert d["event_hash"] == "abc"

    def test_compute_hash_deterministic(self):
        """compute_hash produces the same result for same inputs."""
        h1 = StoredEvent.compute_hash("test", "S", {"a": 1}, {}, 1, 100.0)
        h2 = StoredEvent.compute_hash("test", "S", {"a": 1}, {}, 1, 100.0)
        assert h1 == h2

    def test_compute_hash_different_for_different_data(self):
        """compute_hash produces different results for different inputs."""
        h1 = StoredEvent.compute_hash("test", "S", {"a": 1}, {}, 1, 100.0)
        h2 = StoredEvent.compute_hash("test", "S", {"a": 2}, {}, 1, 100.0)
        assert h1 != h2


class TestSnapshot:
    """Test suite for Snapshot model."""

    def test_to_dict(self):
        """to_dict returns expected fields."""
        snap = Snapshot(stream="S", state={"pos": 10}, version=5, timestamp=200.0)
        d = snap.to_dict()
        assert d["stream"] == "S"
        assert d["version"] == 5
        assert d["timestamp"] == 200.0
        assert "state" not in d  # state should not be exposed in to_dict
