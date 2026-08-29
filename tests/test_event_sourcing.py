"""Tests for Event Sourcing module (core/event_sourcing.py)."""

from __future__ import annotations

import pytest
from core.event_sourcing import Snapshot, StoredEvent, get_event_store, reset_event_store


@pytest.fixture(autouse=True)
def reset_store():
    reset_event_store()
    store = get_event_store()
    store.clear_all()
    yield
    reset_event_store()


class TestAppend:
    def test_append_event(self):
        store = get_event_store()
        event = store.append("trade.executed", stream="NIFTY", data={"qty": 50})
        assert event.event_type == "trade.executed"
        assert event.stream == "NIFTY"
        assert event.data["qty"] == 50
        assert event.version == 1

    def test_append_multiple_events(self):
        store = get_event_store()
        for i in range(3):
            store.append("trade.executed", stream="NIFTY", data={"id": i})
        stream = store.read_stream("NIFTY")
        assert len(stream) == 3

    def test_append_auto_increments_version(self):
        store = get_event_store()
        e1 = store.append("e1", stream="S", data={})
        e2 = store.append("e2", stream="S", data={})
        assert e1.version == 1
        assert e2.version == 2

    def test_append_creates_event_id(self):
        store = get_event_store()
        event = store.append("test", stream="S", data={})
        assert event.event_id.startswith("evt-")

    def test_append_many(self):
        store = get_event_store()
        events = store.append_many([
            ("e1", "S", {"i": 1}),
            ("e2", "S", {"i": 2}),
        ], stream="default")
        assert len(events) == 2
        assert events[0].event_type == "e1"
        assert events[1].event_type == "e2"


class TestRead:
    def test_read_stream(self):
        store = get_event_store()
        store.append("e1", stream="S", data={})
        store.append("e2", stream="S", data={})
        events = store.read_stream("S")
        assert len(events) == 2

    def test_read_stream_from_version(self):
        store = get_event_store()
        store.append("e1", stream="S", data={})
        e2 = store.append("e2", stream="S", data={})
        store.append("e3", stream="S", data={})
        events = store.read_stream("S", from_version=2)
        assert len(events) == 2
        assert events[0].event_id == e2.event_id

    def test_read_stream_to_version(self):
        store = get_event_store()
        e1 = store.append("e1", stream="S", data={})
        store.append("e2", stream="S", data={})
        store.append("e3", stream="S", data={})
        events = store.read_stream("S", to_version=1)
        assert len(events) == 1
        assert events[0].event_id == e1.event_id

    def test_read_all_streams(self):
        store = get_event_store()
        store.append("e1", stream="A", data={})
        store.append("e2", stream="B", data={})
        all_s = store.read_all_streams()
        assert "A" in all_s
        assert "B" in all_s
        assert len(all_s["A"]) == 1
        assert len(all_s["B"]) == 1

    def test_stream_exists(self):
        store = get_event_store()
        assert store.stream_exists("S") is False
        store.append("e", stream="S", data={})
        assert store.stream_exists("S") is True

    def test_get_stream_version(self):
        store = get_event_store()
        assert store.get_stream_version("S") == 0
        store.append("e1", stream="S", data={})
        store.append("e2", stream="S", data={})
        assert store.get_stream_version("S") == 2


class TestSnapshots:
    def test_create_snapshot(self):
        store = get_event_store()
        store.append("e1", stream="S", data={"v": 1})
        snapshot = store.create_snapshot("S", {"position": 1})
        assert snapshot.stream == "S"
        assert snapshot.state["position"] == 1
        assert snapshot.version == 1

    def test_get_snapshot(self):
        store = get_event_store()
        store.create_snapshot("S", {"pos": 1})
        snapshot = store.get_snapshot("S")
        assert snapshot is not None
        assert snapshot.state["pos"] == 1

    def test_snapshot_version_tracking(self):
        store = get_event_store()
        store.append("e1", stream="S", data={})
        store.append("e2", stream="S", data={})
        store.create_snapshot("S", {"pos": 2})
        assert store.get_snapshot("S").version == 2


class TestReplay:
    def test_replay_stream(self):
        store = get_event_store()
        store.append("e1", stream="S", data={"n": 1})
        store.append("e2", stream="S", data={"n": 2})
        results = store.replay_stream("S", lambda e: e.data["n"])
        # No snapshot created, so results are just the 2 event handler returns
        assert len(results) == 2  # 2 events, no snapshot

    def test_replay_all(self):
        store = get_event_store()
        store.append("e1", stream="A", data={})
        store.append("e2", stream="B", data={})
        results = store.replay_all(lambda e: e.event_type)
        assert "A" in results
        assert "B" in results


class TestDelete:
    def test_delete_stream(self):
        store = get_event_store()
        store.append("e", stream="S", data={})
        store.create_snapshot("S", {})
        assert store.delete_stream("S") is True
        assert store.stream_exists("S") is False
        assert store.get_snapshot("S") is None

    def test_delete_nonexistent_stream(self):
        store = get_event_store()
        assert store.delete_stream("nonexistent") is False


class TestStats:
    def test_get_stats_empty(self):
        store = get_event_store()
        stats = store.get_stats()
        assert stats["total_events"] == 0

    def test_get_stats_after_events(self):
        store = get_event_store()
        store.append("e1", stream="A", data={})
        store.append("e2", stream="A", data={})
        store.append("e3", stream="B", data={})
        store.create_snapshot("A", {})
        stats = store.get_stats()
        assert stats["total_events"] == 3
        assert stats["total_streams"] == 2
        assert stats["total_snapshots"] == 1


class TestHashChain:
    """Hash chain integrity tests (Constitution v4.0 Phase 5)."""

    def test_event_has_sha256_hash(self):
        """Every stored event should have a 64-char SHA-256 event_hash."""
        store = get_event_store()
        event = store.append("trade.executed", stream="NIFTY", data={"qty": 50})
        assert len(event.event_hash) == 64
        assert event.event_hash != ""

    def test_first_event_no_previous_hash(self):
        """First event in a stream should have empty previous_event_hash."""
        store = get_event_store()
        event = store.append("first", stream="S", data={})
        assert event.previous_event_hash == ""

    def test_second_event_links_to_first(self):
        """Second event should reference first event's hash."""
        store = get_event_store()
        e1 = store.append("e1", stream="S", data={"n": 1})
        e2 = store.append("e2", stream="S", data={"n": 2})
        assert e2.previous_event_hash == e1.event_hash
        assert e1.previous_event_hash == ""

    def test_three_event_chain(self):
        """Three events should form a verifiable chain."""
        store = get_event_store()
        e1 = store.append("e1", stream="S", data={"n": 1})
        e2 = store.append("e2", stream="S", data={"n": 2})
        e3 = store.append("e3", stream="S", data={"n": 3})
        assert e1.previous_event_hash == ""
        assert e2.previous_event_hash == e1.event_hash
        assert e3.previous_event_hash == e2.event_hash

    def test_deterministic_hash(self):
        """Hash computation should be deterministic."""
        store = get_event_store()
        e1 = store.append("e1", stream="S", data={"n": 1})
        hash1 = StoredEvent.compute_hash(
            event_type="e1", stream="S", data={"n": 1},
            metadata={}, version=1, timestamp=e1.timestamp,
            previous_hash="", event_id=e1.event_id,
        )
        assert hash1 == e1.event_hash

    def test_independent_stream_chains(self):
        """Different streams should have independent hash chains."""
        store = get_event_store()
        a1 = store.append("a1", stream="A", data={})
        b1 = store.append("b1", stream="B", data={})
        a2 = store.append("a2", stream="A", data={})
        assert a1.previous_event_hash == ""
        assert b1.previous_event_hash == ""
        assert a2.previous_event_hash == a1.event_hash
        assert b1.event_hash != a1.event_hash

    def test_hash_in_dict_serialization(self):
        """to_dict should include hash fields."""
        store = get_event_store()
        event = store.append("test", stream="S", data={})
        d = event.to_dict()
        assert "event_hash" in d
        assert "previous_event_hash" in d
        assert d["event_hash"] == event.event_hash


class TestEventModel:
    def test_stored_event_to_dict(self):
        e = StoredEvent(event_id="e1", event_type="test", stream="S", data={"k": "v"}, version=1, timestamp=100.0)
        d = e.to_dict()
        assert d["event_id"] == "e1"
        assert d["event_type"] == "test"
        assert d["version"] == 1
        assert "event_hash" in d
        assert "previous_event_hash" in d

    def test_snapshot_to_dict(self):
        s = Snapshot(stream="S", state={"k": "v"}, version=1, timestamp=100.0)
        d = s.to_dict()
        assert d["stream"] == "S"
        assert d["version"] == 1


class TestSingleton:
    def test_singleton(self):
        s1 = get_event_store()
        s2 = get_event_store()
        assert s1 is s2

    def test_reset(self):
        s1 = get_event_store()
        reset_event_store()
        s2 = get_event_store()
        assert s1 is not s2
