"""
Tests for core/execution/event_system.py - Event-Driven Architecture.

Covers:
- EventType and EventPriority enums
- TradingEvent dataclass (creation, to_dict, to_json, from_dict)
- EventStore (init, append, query by order/type/range)
- EventBus (subscribe, unsubscribe, publish, helper methods, replay)
- Singleton get_event_bus / get_event_store
"""

from __future__ import annotations

import json
import sqlite3
import threading
from unittest.mock import patch

import pytest
from core.execution.event_system import (
    EventBus,
    EventPriority,
    EventStore,
    EventType,
    TradingEvent,
    get_event_bus,
    get_event_store,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def event_store(tmp_path):
    """EventStore with isolated temp DB path."""
    store = EventStore()
    original_path = EventStore.PERSISTENCE_PATH
    store.PERSISTENCE_PATH = str(tmp_path / "test_events.db")
    store._init_durable_storage()
    yield store
    EventStore.PERSISTENCE_PATH = original_path


@pytest.fixture
def event_bus(event_store):
    """EventBus with isolated event store."""
    bus = EventBus(event_store=event_store)
    return bus


# ── Enum Tests ────────────────────────────────────────────────────────────────


class TestEventType:
    """EventType enum - 18 event types covering the full lifecycle."""

    def test_signal_generated(self):
        assert EventType.SIGNAL_GENERATED.value == "SIGNAL_GENERATED"

    def test_risk_approved(self):
        assert EventType.RISK_APPROVED.value == "RISK_APPROVED"

    def test_order_submitted(self):
        assert EventType.ORDER_SUBMITTED.value == "ORDER_SUBMITTED"

    def test_broker_ack_received(self):
        assert EventType.BROKER_ACK_RECEIVED.value == "BROKER_ACK_RECEIVED"

    def test_fill_received(self):
        assert EventType.FILL_RECEIVED.value == "FILL_RECEIVED"

    def test_partial_fill_received(self):
        assert EventType.PARTIAL_FILL_RECEIVED.value == "PARTIAL_FILL_RECEIVED"

    def test_position_updated(self):
        assert EventType.POSITION_UPDATED.value == "POSITION_UPDATED"

    def test_order_cancelled(self):
        assert EventType.ORDER_CANCELLED.value == "ORDER_CANCELLED"

    def test_order_rejected(self):
        assert EventType.ORDER_REJECTED.value == "ORDER_REJECTED"

    def test_risk_limit_breached(self):
        assert EventType.RISK_LIMIT_BREACHED.value == "RISK_LIMIT_BREACHED"

    def test_circuit_breaker_triggered(self):
        assert EventType.CIRCUIT_BREAKER_TRIGGERED.value == "CIRCUIT_BREAKER_TRIGGERED"

    def test_trading_session_started(self):
        assert EventType.TRADING_SESSION_STARTED.value == "TRADING_SESSION_STARTED"

    def test_trading_session_ended(self):
        assert EventType.TRADING_SESSION_ENDED.value == "TRADING_SESSION_ENDED"

    def test_strategy_initialized(self):
        assert EventType.STRATEGY_INITIALIZED.value == "STRATEGY_INITIALIZED"

    def test_strategy_updated(self):
        assert EventType.STRATEGY_UPDATED.value == "STRATEGY_UPDATED"

    def test_config_updated(self):
        assert EventType.CONFIG_UPDATED.value == "CONFIG_UPDATED"

    def test_health_check_passed(self):
        assert EventType.HEALTH_CHECK_PASSED.value == "HEALTH_CHECK_PASSED"

    def test_health_check_failed(self):
        assert EventType.HEALTH_CHECK_FAILED.value == "HEALTH_CHECK_FAILED"


class TestEventPriority:
    """EventPriority enum - 4 priority levels."""

    def test_critical_priority(self):
        assert EventPriority.CRITICAL.value == 0
        assert EventPriority.CRITICAL < EventPriority.HIGH

    def test_high_priority(self):
        assert EventPriority.HIGH.value == 1

    def test_normal_priority(self):
        assert EventPriority.NORMAL.value == 2

    def test_low_priority(self):
        assert EventPriority.LOW.value == 3


# ── TradingEvent Tests ────────────────────────────────────────────────────────


class TestTradingEvent:
    """TradingEvent dataclass - immutability, serialization, deserialization."""

    def test_default_values(self):
        """Event created with defaults should have valid fields."""
        event = TradingEvent()
        assert event.event_id is not None
        assert len(event.event_id) > 10
        assert event.event_type == EventType.SIGNAL_GENERATED
        assert event.priority == EventPriority.NORMAL
        assert event.timestamp is not None
        assert event.metadata == {}

    def test_custom_values(self):
        """Event created with custom fields."""
        event = TradingEvent(
            event_type=EventType.ORDER_SUBMITTED,
            priority=EventPriority.CRITICAL,
            source="test",
            intent_id="intent-123",
            client_order_id="OPB-intent-123",
            broker_order_id="brk-456",
            symbol="NIFTY",
            direction="BUY",
            quantity=50,
            price=150.0,
            metadata={"key": "value"},
        )
        assert event.event_type == EventType.ORDER_SUBMITTED
        assert event.priority == EventPriority.CRITICAL
        assert event.source == "test"
        assert event.intent_id == "intent-123"
        assert event.client_order_id == "OPB-intent-123"
        assert event.broker_order_id == "brk-456"
        assert event.symbol == "NIFTY"
        assert event.direction == "BUY"
        assert event.quantity == 50
        assert event.price == 150.0
        assert event.metadata == {"key": "value"}

    def test_to_dict(self):
        """to_dict should serialize all fields."""
        event = TradingEvent(
            event_type=EventType.FILL_RECEIVED,
            priority=EventPriority.HIGH,
            source="exec",
            intent_id="int-1",
            client_order_id="OPB-int-1",
            symbol="BANKNIFTY",
            direction="SELL",
            quantity=25,
            price=200.0,
        )
        d = event.to_dict()
        assert d["event_type"] == "FILL_RECEIVED"
        assert d["priority"] == 1
        assert d["source"] == "exec"
        assert d["symbol"] == "BANKNIFTY"
        assert d["direction"] == "SELL"
        assert d["quantity"] == 25
        assert d["price"] == 200.0

    def test_to_json(self):
        """to_json should produce valid JSON string."""
        event = TradingEvent(event_type=EventType.HEALTH_CHECK_PASSED)
        json_str = event.to_json()
        parsed = json.loads(json_str)
        assert parsed["event_type"] == "HEALTH_CHECK_PASSED"
        assert parsed["event_id"] == event.event_id

    def test_from_dict_roundtrip(self):
        """from_dict should reconstruct event from dict."""
        original = TradingEvent(
            event_type=EventType.RISK_LIMIT_BREACHED,
            priority=EventPriority.CRITICAL,
            source="risk",
            intent_id="int-99",
            client_order_id="OPB-int-99",
            symbol="FINNIFTY",
            direction="BUY",
            quantity=10,
            price=5000.0,
            metadata={"limit": "max_daily_loss"},
        )
        d = original.to_dict()
        reconstructed = TradingEvent.from_dict(d)
        assert reconstructed.event_type == original.event_type
        assert reconstructed.priority == original.priority
        assert reconstructed.source == original.source
        assert reconstructed.intent_id == original.intent_id
        assert reconstructed.client_order_id == original.client_order_id
        assert reconstructed.symbol == original.symbol
        assert reconstructed.direction == original.direction
        assert reconstructed.quantity == original.quantity
        assert reconstructed.price == original.price
        assert reconstructed.metadata == original.metadata

    def test_from_dict_with_defaults(self):
        """from_dict should fill defaults for missing fields."""
        reconstructed = TradingEvent.from_dict({})
        assert reconstructed.event_id is not None
        assert reconstructed.event_type == EventType.SIGNAL_GENERATED
        assert reconstructed.priority == EventPriority.NORMAL
        assert reconstructed.metadata == {}

    def test_uuid_uniqueness(self):
        """Each event should have a unique UUID."""
        e1 = TradingEvent()
        e2 = TradingEvent()
        assert e1.event_id != e2.event_id


# ── EventStore Tests ──────────────────────────────────────────────────────────


class TestEventStore:
    """EventStore - SQLite-backed event sourcing persistence."""

    def test_init_creates_table(self, event_store):
        """Init should create the events table."""
        with sqlite3.connect(event_store.PERSISTENCE_PATH) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events'")
            assert cursor.fetchone() is not None

    def test_append_event(self, event_store):
        """Append should persist event to SQLite."""
        event = TradingEvent(event_type=EventType.ORDER_SUBMITTED, source="test")
        result = event_store.append(event)
        assert result is True

        # Verify it's in DB
        with sqlite3.connect(event_store.PERSISTENCE_PATH) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM events")
            assert cursor.fetchone()[0] == 1

    def test_append_multiple_increments_sequence(self, event_store):
        """Appending multiple events should increment sequence_number."""
        for i in range(3):
            event = TradingEvent(event_type=EventType.SIGNAL_GENERATED, source=f"src-{i}")
            event_store.append(event)

        with sqlite3.connect(event_store.PERSISTENCE_PATH) as conn:
            cursor = conn.execute("SELECT sequence_number FROM events ORDER BY sequence_number")
            seqs = [row[0] for row in cursor]
        assert seqs == [1, 2, 3]

    def test_get_events_for_order(self, event_store):
        """get_events_for_order should return events for a specific client_order_id."""
        event1 = TradingEvent(
            event_type=EventType.ORDER_SUBMITTED,
            client_order_id="OPB-abc",
            source="test",
        )
        event2 = TradingEvent(
            event_type=EventType.BROKER_ACK_RECEIVED,
            client_order_id="OPB-abc",
            source="broker",
        )
        event3 = TradingEvent(
            event_type=EventType.FILL_RECEIVED,
            client_order_id="OPB-xyz",
            source="exec",
        )
        event_store.append(event1)
        event_store.append(event2)
        event_store.append(event3)

        events = event_store.get_events_for_order("OPB-abc")
        assert len(events) == 2
        assert all(e.client_order_id == "OPB-abc" for e in events)
        assert events[0].event_type == EventType.ORDER_SUBMITTED
        assert events[1].event_type == EventType.BROKER_ACK_RECEIVED

    def test_get_events_for_order_nonexistent(self, event_store):
        """Non-existent order should return empty list."""
        events = event_store.get_events_for_order("DOES_NOT_EXIST")
        assert events == []

    def test_get_events_by_type(self, event_store):
        """get_events_by_type should filter by event type."""
        for _ in range(3):
            event_store.append(TradingEvent(event_type=EventType.SIGNAL_GENERATED))
        event_store.append(TradingEvent(event_type=EventType.ORDER_SUBMITTED))

        signals = event_store.get_events_by_type(EventType.SIGNAL_GENERATED)
        assert len(signals) == 3

        orders = event_store.get_events_by_type(EventType.ORDER_SUBMITTED)
        assert len(orders) == 1

    def test_get_events_by_type_empty(self, event_store):
        """No events of a type should return empty list."""
        events = event_store.get_events_by_type(EventType.CIRCUIT_BREAKER_TRIGGERED)
        assert events == []

    def test_get_events_by_type_with_limit(self, event_store):
        """get_events_by_type should respect limit parameter."""
        for _ in range(10):
            event_store.append(TradingEvent(event_type=EventType.SIGNAL_GENERATED))
        events = event_store.get_events_by_type(EventType.SIGNAL_GENERATED, limit=3)
        assert len(events) == 3

    def test_get_events_in_range(self, event_store):
        """get_events_in_range should filter by timestamp boundary."""
        event_store.append(TradingEvent(event_type=EventType.SIGNAL_GENERATED, timestamp="2026-01-01T09:00:00", source="a"))
        event_store.append(TradingEvent(event_type=EventType.SIGNAL_GENERATED, timestamp="2026-01-01T12:00:00", source="b"))
        event_store.append(TradingEvent(event_type=EventType.SIGNAL_GENERATED, timestamp="2026-01-01T15:00:00", source="c"))

        events = event_store.get_events_in_range("2026-01-01T10:00:00", "2026-01-01T14:00:00")
        assert len(events) == 1
        assert events[0].source == "b"

    def test_get_events_in_range_empty(self, event_store):
        """No events in range should return empty list."""
        events = event_store.get_events_in_range("1990-01-01", "1990-01-02")
        assert events == []

    def test_append_error_handling(self, event_store):
        """Append should return False on error (e.g. DB locked)."""
        # Simulate DB error by closing the underlying DB
        with patch.object(sqlite3, "connect", side_effect=sqlite3.Error("mock error")):
            event = TradingEvent()
            result = event_store.append(event)
            assert result is False

    def test_get_events_for_order_error(self, event_store):
        """get_events_for_order should return [] on error."""
        with patch.object(sqlite3, "connect", side_effect=sqlite3.Error("mock")):
            events = event_store.get_events_for_order("OPB-abc")
            assert events == []

    def test_get_events_by_type_error(self, event_store):
        """get_events_by_type should return [] on error."""
        with patch.object(sqlite3, "connect", side_effect=OSError("mock")):
            events = event_store.get_events_by_type(EventType.SIGNAL_GENERATED)
            assert events == []

    def test_get_events_in_range_error(self, event_store):
        """get_events_in_range should return [] on error."""
        with patch.object(sqlite3, "connect", side_effect=KeyError("mock")):
            events = event_store.get_events_in_range("a", "b")
            assert events == []


# ── EventBus Tests ────────────────────────────────────────────────────────────


class TestEventBus:
    """EventBus - pub/sub event dispatch system."""

    def test_subscribe_and_publish(self, event_bus):
        """Subscribed handler should be called on publish."""
        received = []

        def handler(event: TradingEvent) -> None:
            received.append(event)

        event_bus.subscribe(EventType.SIGNAL_GENERATED, handler)
        event = TradingEvent(event_type=EventType.SIGNAL_GENERATED, source="test")
        event_bus.publish(event)

        assert len(received) == 1
        assert received[0].source == "test"

    def test_subscribe_multiple_handlers(self, event_bus):
        """Multiple handlers for same event type should all be called."""
        received1 = []
        received2 = []

        def handler1(e):
            received1.append(e)

        def handler2(e):
            received2.append(e)

        event_bus.subscribe(EventType.ORDER_SUBMITTED, handler1)
        event_bus.subscribe(EventType.ORDER_SUBMITTED, handler2)
        event = TradingEvent(event_type=EventType.ORDER_SUBMITTED)
        event_bus.publish(event)

        assert len(received1) == 1
        assert len(received2) == 1

    def test_unsubscribe(self, event_bus):
        """Unsubscribed handler should not be called."""
        received = []

        def handler(e):
            received.append(e)

        event_bus.subscribe(EventType.SIGNAL_GENERATED, handler)
        event_bus.unsubscribe(EventType.SIGNAL_GENERATED, handler)
        event_bus.publish(TradingEvent())

        assert len(received) == 0

    def test_publish_only_notifies_subscribed_type(self, event_bus):
        """Handler should only be called for subscribed event type."""
        received = []

        def handler(e):
            received.append(e)

        event_bus.subscribe(EventType.FILL_RECEIVED, handler)
        event_bus.publish(TradingEvent(event_type=EventType.SIGNAL_GENERATED))
        event_bus.publish(TradingEvent(event_type=EventType.FILL_RECEIVED))

        assert len(received) == 1
        assert received[0].event_type == EventType.FILL_RECEIVED

    def test_publish_is_thread_safe(self, event_bus):
        """Publishing from multiple threads should not crash."""
        received = []
        errors = []

        def handler(e):
            received.append(e)

        event_bus.subscribe(EventType.SIGNAL_GENERATED, handler)

        def publish_thread():
            try:
                for _ in range(20):
                    event_bus.publish(TradingEvent())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=publish_thread) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(received) == 100

    def test_handler_error_does_not_crash_bus(self, event_bus):
        """A handler that raises should not crash the bus."""
        calls = []

        def broken_handler(e):
            raise ValueError("broken")

        def good_handler(e):
            calls.append(e)

        event_bus.subscribe(EventType.SIGNAL_GENERATED, broken_handler)
        event_bus.subscribe(EventType.SIGNAL_GENERATED, good_handler)

        event_bus.publish(TradingEvent(source="test"))
        assert len(calls) == 1

    def test_publish_signal_generated(self, event_bus):
        """publish_signal_generated helper should create and publish correct event."""
        event = event_bus.publish_signal_generated(
            intent_id="int-1",
            symbol="NIFTY",
            direction="BUY",
            quantity=50,
            price=150.0,
            metadata={"score": 85},
        )
        assert event is not None
        assert event.event_type == EventType.SIGNAL_GENERATED
        assert event.intent_id == "int-1"
        assert event.symbol == "NIFTY"
        assert event.metadata["score"] == 85

    def test_publish_risk_approved(self, event_bus):
        """publish_risk_approved helper should create correct event."""
        event = event_bus.publish_risk_approved(
            intent_id="int-1",
            client_order_id="OPB-int-1",
            metadata={"risk_ok": True},
        )
        assert event is not None
        assert event.event_type == EventType.RISK_APPROVED
        assert event.source == "risk_engine"

    def test_publish_order_submitted(self, event_bus):
        """publish_order_submitted helper should create correct event."""
        event = event_bus.publish_order_submitted(
            intent_id="int-1",
            client_order_id="OPB-int-1",
            broker_order_id="brk-1",
            symbol="BANKNIFTY",
            direction="SELL",
            quantity=25,
            price=200.0,
        )
        assert event is not None
        assert event.event_type == EventType.ORDER_SUBMITTED
        assert event.broker_order_id == "brk-1"

    def test_publish_broker_ack(self, event_bus):
        """publish_broker_ack helper should create correct event."""
        event = event_bus.publish_broker_ack(
            client_order_id="OPB-int-1",
            broker_order_id="brk-1",
            metadata={"status": "ACK"},
        )
        assert event is not None
        assert event.event_type == EventType.BROKER_ACK_RECEIVED
        assert event.source == "broker_gateway"

    def test_publish_fill_final(self, event_bus):
        """publish_fill with is_final=True should create FILL_RECEIVED."""
        event = event_bus.publish_fill(
            client_order_id="OPB-int-1",
            broker_order_id="brk-1",
            symbol="NIFTY",
            direction="BUY",
            filled_qty=50,
            avg_price=150.0,
            is_final=True,
        )
        assert event is not None
        assert event.event_type == EventType.FILL_RECEIVED

    def test_publish_fill_partial(self, event_bus):
        """publish_fill with is_final=False should create PARTIAL_FILL_RECEIVED."""
        event = event_bus.publish_fill(
            client_order_id="OPB-int-1",
            broker_order_id="brk-1",
            symbol="NIFTY",
            direction="BUY",
            filled_qty=25,
            avg_price=150.0,
            is_final=False,
        )
        assert event is not None
        assert event.event_type == EventType.PARTIAL_FILL_RECEIVED

    def test_publish_risk_breached(self, event_bus):
        """publish_risk_breached helper should create CRITICAL event."""
        event = event_bus.publish_risk_breached(
            limit_type="max_daily_loss",
            current_value=-500.0,
            threshold=-600.0,
            metadata={"account": "test"},
        )
        assert event is not None
        assert event.event_type == EventType.RISK_LIMIT_BREACHED
        assert event.priority == EventPriority.CRITICAL
        assert event.metadata["limit_type"] == "max_daily_loss"

    def test_replay_order(self, event_bus):
        """replay_order should return stored events for order."""
        event_bus.publish_order_submitted("int-1", "OPB-int-1", "brk-1", "NIFTY", "BUY", 50, 150.0)
        event_bus.publish_broker_ack("OPB-int-1", "brk-1", {"status": "ACK"})

        events = event_bus.replay_order("OPB-int-1")
        assert len(events) == 2
        assert events[0].event_type == EventType.ORDER_SUBMITTED
        assert events[1].event_type == EventType.BROKER_ACK_RECEIVED

    def test_get_recent_events(self, event_bus):
        """get_recent_events should return recent events from in-memory history."""
        for i in range(5):
            event_bus.publish(TradingEvent(event_type=EventType.SIGNAL_GENERATED, source=f"src-{i}"))

        recent = event_bus.get_recent_events(3)
        assert len(recent) == 3
        assert recent[-1].source == "src-4"

    def test_get_recent_events_empty(self, event_bus):
        """get_recent_events with no events should return empty list."""
        recent = event_bus.get_recent_events(10)
        assert recent == []

    def test_event_history_max_size(self, event_bus):
        """In-memory history should be capped at _max_history."""
        event_bus._max_history = 10
        for i in range(15):
            event_bus.publish(TradingEvent(source=f"src-{i}"))

        recent = event_bus.get_recent_events(20)
        assert len(recent) == 10
        assert recent[0].source == "src-5"


class TestEventBusSubscribeDuplicate:
    """Subscribing the same handler twice should not duplicate."""

    def test_duplicate_subscribe(self, event_bus):
        """Duplicate handler subscription should be idempotent."""
        received = []

        def handler(e):
            received.append(e)

        event_bus.subscribe(EventType.SIGNAL_GENERATED, handler)
        event_bus.subscribe(EventType.SIGNAL_GENERATED, handler)
        event_bus.publish(TradingEvent())

        assert len(received) == 1


# ── Singleton Tests ───────────────────────────────────────────────────────────


# ── Hash-Chain Verification Tests ────────────────────────────────────────────


class TestEventStoreHashChain:
    """
    Hash-chained immutable event store integrity verification.

    Constitution Rule #15 (Deterministic Replay) and Rule #5 (Immutable Audit Trail):
    The event store must support tamper-evident chain verification. These tests
    verify that unmodified chains pass and tampered chains are detected.
    """

    def test_verify_chain_empty_store(self, event_store):
        """Empty event store should report valid."""
        valid, count, msg = event_store.verify_chain()
        assert valid is True
        assert count == 0
        assert "Empty" in msg

    def test_verify_chain_single_event(self, event_store):
        """Single event chain should be valid."""
        event = TradingEvent(event_type=EventType.ORDER_SUBMITTED, source="test")
        event_store.append(event)
        valid, count, msg = event_store.verify_chain()
        assert valid is True
        assert count == 1

    def test_verify_chain_multiple_events(self, event_store):
        """Multiple event chain should be valid."""
        for i in range(5):
            event = TradingEvent(
                event_type=EventType.SIGNAL_GENERATED,
                source=f"src-{i}",
                symbol="NIFTY",
                quantity=50,
                price=150.0 + i,
            )
            event_store.append(event)
        valid, count, msg = event_store.verify_chain()
        assert valid is True
        assert count == 5
        assert "Chain valid" in msg

    def test_verify_chain_detects_tampered_event_type(self, event_store):
        """
        Tampering with an event's event_type should be detected.

        This simulates an attacker modifying an event in the SQLite database
        directly. The hash chain should detect that the stored hash no longer
        matches the recomputed hash for the modified event.
        """
        # Create a 3-event chain
        for i in range(3):
            event = TradingEvent(
                event_type=EventType.SIGNAL_GENERATED,
                source=f"src-{i}",
                symbol="NIFTY",
            )
            event_store.append(event)

        # Verify chain is valid before tampering
        valid, count, _ = event_store.verify_chain()
        assert valid is True
        assert count == 3

        # Tamper with the middle event - change event_type directly in SQLite
        with sqlite3.connect(event_store.PERSISTENCE_PATH) as conn:
            conn.execute(
                "UPDATE events SET event_type = ? WHERE sequence_number = ?",
                ("ORDER_SUBMITTED", 2),
            )
            conn.commit()

        # Verify chain detects the tampering
        valid, broken_seq, msg = event_store.verify_chain()
        assert valid is False
        assert "Hash mismatch" in msg
        assert broken_seq >= 2  # Should fail at or after the tampered event

    def test_verify_chain_detects_tampered_metadata(self, event_store):
        """Tampering with event metadata should be detected."""
        event = TradingEvent(
            event_type=EventType.ORDER_SUBMITTED,
            source="test",
            metadata={"original": "data"},
        )
        event_store.append(event)

        valid, count, _ = event_store.verify_chain()
        assert valid is True

        # Tamper with metadata
        with sqlite3.connect(event_store.PERSISTENCE_PATH) as conn:
            conn.execute(
                "UPDATE events SET metadata_json = ? WHERE sequence_number = ?",
                ("{\"tampered\": \"data\"}", 1),
            )
            conn.commit()

        valid, _, msg = event_store.verify_chain()
        assert valid is False
        assert "Hash mismatch" in msg

    def test_verify_chain_detects_broken_previous_hash(self, event_store):
        """Breaking the previous_hash link should be detected."""
        for i in range(3):
            event = TradingEvent(event_type=EventType.SIGNAL_GENERATED, source=f"src-{i}")
            event_store.append(event)

        # Tamper with the previous_hash of the third event
        with sqlite3.connect(event_store.PERSISTENCE_PATH) as conn:
            conn.execute(
                "UPDATE events SET previous_hash = ? WHERE sequence_number = ?",
                ("DEADBEEF", 3),
            )
            conn.commit()

        valid, _, msg = event_store.verify_chain()
        assert valid is False
        assert "Chain break" in msg

    def test_verify_chain_multiple_chains_after_append(self, event_store):
        """Chain should remain valid after multiple appends."""
        for i in range(3):
            event = TradingEvent(event_type=EventType.SIGNAL_GENERATED, source=f"src-{i}")
            event_store.append(event)

        valid, _, _ = event_store.verify_chain()
        assert valid is True

        # Append more events
        for i in range(3, 6):
            event = TradingEvent(event_type=EventType.FILL_RECEIVED, source=f"src-{i}")
            event_store.append(event)

        valid, count, msg = event_store.verify_chain()
        assert valid is True
        assert count == 6
        assert "Chain valid" in msg

    def test_canonical_hash_consistency(self, event_store):
        """
        Hash computed via _canonical_event_data + _compute_hash should match
        the hash stored in the DB. This validates that the JSON round-trip
        canonicalization produces consistent results.
        """
        event = TradingEvent(
            event_type=EventType.RISK_LIMIT_BREACHED,
            source="risk",
            metadata={"limit": "max_daily_loss", "value": -500.0},
        )
        event_store.append(event)

        # Read back the stored hash
        with sqlite3.connect(event_store.PERSISTENCE_PATH) as conn:
            cursor = conn.execute("SELECT sha256 FROM events WHERE sequence_number = 1")
            stored_hash = cursor.fetchone()[0]

        # Recompute hash using canonical method
        canonical = event_store._canonical_event_data(event)
        recomputed = event_store._compute_hash(None, canonical)

        assert stored_hash == recomputed, (
            f"Hash mismatch: stored={stored_hash}, recomputed={recomputed}"
        )


class TestSingletons:
    """Module-level singleton functions."""

    def test_get_event_bus_returns_bus(self):
        """get_event_bus should return an EventBus instance."""
        bus = get_event_bus()
        assert isinstance(bus, EventBus)

    def test_get_event_bus_singleton(self):
        """get_event_bus should return the same instance."""
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2

    def test_get_event_store_returns_store(self):
        """get_event_store should return an EventStore instance."""
        store = get_event_store()
        assert isinstance(store, EventStore)

    def test_get_event_store_singleton(self):
        """get_event_store should return the same instance."""
        store1 = get_event_store()
        store2 = get_event_store()
        assert store1 is store2

    def test_get_event_store_from_bus(self):
        """get_event_store should return the store from the singleton bus."""
        bus = get_event_bus()
        store = get_event_store()
        assert store is bus._event_store
