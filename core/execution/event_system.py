"""
Event-Driven Architecture - Item 2

Implements publish-subscribe event system for loose coupling:
- SignalGenerated
- RiskApproved
- OrderSubmitted
- BrokerAckReceived
- FillReceived
- PositionUpdated
- RiskLimitBreached
- CircuitBreakerTriggered

Benefits:
- Loose coupling
- Extensibility
- Replay capability
- Auditability
- Easier multi-strategy scaling

v2.53.0 Enhancement: Hash-chained immutable event store.
Each event stores the SHA-256 hash of the previous event, creating a
cryptographic chain that makes tampering detectable.
- `verify_chain()` validates chain integrity from genesis to latest event
- `previous_hash` and `sha256` columns in the events table
- Backward-compatible: existing events without hashes are skipped
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading

from core.db_utils import get_connection
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any

from core.time_provider import time_provider

_log = logging.getLogger(__name__)


class EventType(Enum):
    """Core event types"""
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    RISK_APPROVED = "RISK_APPROVED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    BROKER_ACK_RECEIVED = "BROKER_ACK_RECEIVED"
    FILL_RECEIVED = "FILL_RECEIVED"
    PARTIAL_FILL_RECEIVED = "PARTIAL_FILL_RECEIVED"
    POSITION_UPDATED = "POSITION_UPDATED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    RISK_LIMIT_BREACHED = "RISK_LIMIT_BREACHED"
    CIRCUIT_BREAKER_TRIGGERED = "CIRCUIT_BREAKER_TRIGGERED"
    TRADING_SESSION_STARTED = "TRADING_SESSION_STARTED"
    TRADING_SESSION_ENDED = "TRADING_SESSION_ENDED"
    STRATEGY_INITIALIZED = "STRATEGY_INITIALIZED"
    STRATEGY_UPDATED = "STRATEGY_UPDATED"
    CONFIG_UPDATED = "CONFIG_UPDATED"
    HEALTH_CHECK_PASSED = "HEALTH_CHECK_PASSED"
    HEALTH_CHECK_FAILED = "HEALTH_CHECK_FAILED"


class EventPriority(IntEnum):
    """Event priority levels for ordering (IntEnum so comparison works)"""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass
class TradingEvent:
    """
    Immutable trading event - the core of event-driven architecture.
    Events are append-only and form the basis for event sourcing.
    """
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType = EventType.SIGNAL_GENERATED
    priority: EventPriority = EventPriority.NORMAL

    timestamp: str = field(default_factory=lambda: time_provider.format_ts())
    source: str = ""

    intent_id: str | None = None
    client_order_id: str | None = None
    broker_order_id: str | None = None

    symbol: str | None = None
    direction: str | None = None
    quantity: int | None = None
    price: float | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize event to dictionary"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "priority": self.priority.value,
            "timestamp": self.timestamp,
            "source": self.source,
            "intent_id": self.intent_id,
            "client_order_id": self.client_order_id,
            "broker_order_id": self.broker_order_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "quantity": self.quantity,
            "price": self.price,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Serialize event to JSON string"""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradingEvent:
        """Deserialize event from dictionary"""
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            event_type=EventType(data.get("event_type", "SIGNAL_GENERATED")),
            priority=EventPriority(data.get("priority", 2)),
            timestamp=data.get("timestamp", time_provider.format_ts()),
            source=data.get("source", ""),
            intent_id=data.get("intent_id"),
            client_order_id=data.get("client_order_id"),
            broker_order_id=data.get("broker_order_id"),
            symbol=data.get("symbol"),
            direction=data.get("direction"),
            quantity=data.get("quantity"),
            price=data.get("price"),
            metadata=data.get("metadata", {}),
        )


EventHandler = Callable[[TradingEvent], None]


class EventStore:
    """
    Event Store - Item 3 (Event Sourcing)

    Persists all events for:
    - Perfect replay
    - Debugging
    - Recovery
    - Simulation reuse
    """

    PERSISTENCE_PATH = "event_store.db"

    def __init__(self):
        self._init_durable_storage()

    def _init_durable_storage(self) -> None:
        """Initialize SQLite event store with hash-chained integrity."""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS events (
                        event_id TEXT PRIMARY KEY,
                        event_type TEXT NOT NULL,
                        priority INTEGER,
                        timestamp TEXT NOT NULL,
                        source TEXT,
                        intent_id TEXT,
                        client_order_id TEXT,
                        broker_order_id TEXT,
                        symbol TEXT,
                        direction TEXT,
                        quantity INTEGER,
                        price REAL,
                        metadata_json TEXT,
                        sequence_number INTEGER,
                        previous_hash TEXT,
                        sha256 TEXT
                    )
                """)
                # Add hash columns to existing tables (safe for backward compat)
                for col in ("previous_hash", "sha256"):
                    try:
                        conn.execute(f"ALTER TABLE events ADD COLUMN {col} TEXT")
                    except sqlite3.OperationalError:
                        pass  # column already exists
                conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON events(timestamp)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_event_type ON events(event_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_intent ON events(intent_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_client_order ON events(client_order_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sha256 ON events(sha256)")
                conn.commit()
            _log.info("EventStore: Durable storage initialized (hash-chained)")
        except (sqlite3.Error, OSError) as e:
            _log.error(f"EventStore: Failed to init storage: {e}")

    def _compute_hash(self, previous_hash: str | None, event_data: dict[str, Any]) -> str:
        """
        Compute SHA-256 hash for an event, chained to the previous event's hash.

        The hash is computed over:
        1. previous_hash (or empty string for genesis event)
        2. All event fields (sorted for deterministic output)
        3. The JSON-serialized metadata

        This creates a tamper-evident chain: modifying any event in the chain
        changes ALL subsequent hashes, making the tampering detectable via
        verify_chain().
        """
        h = hashlib.sha256()
        h.update((previous_hash or "").encode("utf-8"))
        # Serialize event data deterministically
        serialized = json.dumps(event_data, sort_keys=True, default=str).encode("utf-8")
        h.update(serialized)
        return h.hexdigest()

    def _canonical_event_data(self, event: TradingEvent) -> dict[str, Any]:
        """
        Produce canonical event data for deterministic hashing.

        All values are round-tripped through JSON so that the hash computed
        in append() matches the hash recomputed in verify_chain() regardless
        of Python object identity (tuples, custom types, etc.).
        """
        raw = event.to_dict()
        # Round-trip metadata through JSON for canonical representation
        raw["metadata"] = json.loads(json.dumps(raw.get("metadata", {}), default=str))
        return raw

    def append(self, event: TradingEvent) -> bool:
        """Append event to store with hash-chain integrity.

        Each event stores the SHA-256 hash of:
        - The previous event's hash (previous_hash)
        - This event's own data (sha256)

        The read (SELECT MAX) and write (INSERT) are wrapped in an EXCLUSIVE
        transaction so that concurrent callers cannot read the same
        previous_hash and create a chain fork. See "EventStore append()
        race condition" in THREADING_AUDIT_REPORT.md.

        This creates an immutable, tamper-evident chain. To verify integrity,
        call verify_chain() which recomputes all hashes and compares.
        """
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                # EXCLUSIVE transaction prevents concurrent reads/writes
                conn.execute("BEGIN EXCLUSIVE")
                try:
                    cursor = conn.execute(
                        "SELECT MAX(sequence_number), sha256 FROM events "
                        "ORDER BY sequence_number DESC LIMIT 1"
                    )
                    row = cursor.fetchone()
                    if row and row[0] is not None:
                        seq = row[0] + 1
                        prev_hash = row[1]
                    else:
                        seq = 1
                        prev_hash = None

                    event_data = self._canonical_event_data(event)
                    sha256 = self._compute_hash(prev_hash, event_data)

                    conn.execute("""
                        INSERT INTO events
                        (event_id, event_type, priority, timestamp, source, intent_id,
                         client_order_id, broker_order_id, symbol, direction, quantity,
                         price, metadata_json, sequence_number, previous_hash, sha256)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        event.event_id,
                        event.event_type.value,
                        event.priority.value,
                        event.timestamp,
                        event.source,
                        event.intent_id,
                        event.client_order_id,
                        event.broker_order_id,
                        event.symbol,
                        event.direction,
                        event.quantity,
                        event.price,
                        json.dumps(event.metadata, default=str),
                        seq,
                        prev_hash,
                        sha256,
                    ))
                    conn.commit()
                except (sqlite3.Error, OSError):
                    conn.rollback()
                    raise
            return True
        except (sqlite3.Error, OSError, json.JSONDecodeError) as e:
            _log.error(f"EventStore: Failed to append event {event.event_id}: {e}")
            return False

    def verify_chain(self) -> tuple[bool, int, str]:
        """
        Verify the integrity of the entire hash chain.

        Re-computes the SHA-256 hash for every event in sequence and compares
        it against the stored sha256 value. Also verifies that each event's
        previous_hash matches the sha256 of the preceding event.

        Uses sqlite3.Row for named column access, avoiding fragile positional
        unpacking (column-order assumption).

        Returns:
            (is_valid: bool, events_checked: int, message: str)

        Constitution Rule #15 (Deterministic Replay):
        Calls verify_chain() before any replay to ensure the event stream
        has not been tampered with.

        Constitution Rule #5 (Immutable Audit Trail):
        Any chain verification failure immediately alerts operators.
        """
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT event_id, event_type, priority, timestamp, source, intent_id, "
                    "client_order_id, broker_order_id, symbol, direction, quantity, "
                    "price, metadata_json, sequence_number, previous_hash, sha256 "
                    "FROM events ORDER BY sequence_number"
                )
                rows = cursor.fetchall()
        except (sqlite3.Error, OSError) as e:
            return False, 0, f"DB error: {e}"

        if not rows:
            return True, 0, "Empty event store - nothing to verify"

        expected_prev: str | None = None
        for row in rows:
            stored_hash = row["sha256"]
            # Skip events without hashes (pre-upgrade records)
            if not stored_hash:
                expected_prev = None
                continue

            # Reconstruct event data from named columns for deterministic hash
            event_data = {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "priority": row["priority"],
                "timestamp": row["timestamp"],
                "source": row["source"],
                "intent_id": row["intent_id"],
                "client_order_id": row["client_order_id"],
                "broker_order_id": row["broker_order_id"],
                "symbol": row["symbol"],
                "direction": row["direction"],
                "quantity": row["quantity"],
                "price": row["price"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
            }
            stored_prev = row["previous_hash"]
            seq = row["sequence_number"]
            event_id = row["event_id"]

            # Verify previous_hash matches
            if stored_prev != expected_prev:
                return False, seq, (
                    f"Chain break at event {event_id} (seq {seq}): "
                    f"expected previous_hash={expected_prev}, got {stored_prev}"
                )

            # Recompute hash and verify
            recomputed = self._compute_hash(expected_prev, event_data)
            if recomputed != stored_hash:
                return False, seq, (
                    f"Hash mismatch at event {event_id} (seq {seq}): "
                    f"expected {stored_hash}, recomputed {recomputed}"
                )

            expected_prev = stored_hash

        total = len(rows)
        hashed = sum(1 for r in rows if r["sha256"])
        return True, total, f"Chain valid: {total} events checked, {hashed} with hashes"

    def get_events_for_order(self, client_order_id: str) -> list[TradingEvent]:
        """Get all events for a specific order (for replay/debugging)"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                cursor = conn.execute("""
                    SELECT event_id, event_type, priority, timestamp, source, intent_id,
                           client_order_id, broker_order_id, symbol, direction, quantity,
                           price, metadata_json
                    FROM events
                    WHERE client_order_id = ?
                    ORDER BY sequence_number
                """, (client_order_id,))

                events = []
                for row in cursor:
                    events.append(TradingEvent(
                        event_id=row[0],
                        event_type=EventType(row[1]),
                        priority=EventPriority(row[2]),
                        timestamp=row[3],
                        source=row[4],
                        intent_id=row[5],
                        client_order_id=row[6],
                        broker_order_id=row[7],
                        symbol=row[8],
                        direction=row[9],
                        quantity=row[10],
                        price=row[11],
                        metadata=json.loads(row[12] or "{}"),
                    ))
                return events
        except (sqlite3.Error, OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            _log.error(f"EventStore: Failed to get events for order: {e}")
            return []

    def get_events_by_type(self, event_type: EventType, limit: int = 1000) -> list[TradingEvent]:
        """Get events by type"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                cursor = conn.execute("""
                    SELECT event_id, event_type, priority, timestamp, source, intent_id,
                           client_order_id, broker_order_id, symbol, direction, quantity,
                           price, metadata_json
                    FROM events
                    WHERE event_type = ?
                    ORDER BY sequence_number DESC
                    LIMIT ?
                """, (event_type.value, limit))

                return self._rows_to_events(cursor)
        except (sqlite3.Error, OSError, KeyError, ValueError) as e:
            _log.error(f"EventStore: Failed to get events by type: {e}")
            return []

    def get_events_in_range(self, start_time: str, end_time: str) -> list[TradingEvent]:
        """Get events in time range (for replay)"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                cursor = conn.execute("""
                    SELECT event_id, event_type, priority, timestamp, source, intent_id,
                           client_order_id, broker_order_id, symbol, direction, quantity,
                           price, metadata_json
                    FROM events
                    WHERE timestamp >= ? AND timestamp <= ?
                    ORDER BY sequence_number
                """, (start_time, end_time))

                return self._rows_to_events(cursor)
        except (sqlite3.Error, OSError, KeyError, ValueError) as e:
            _log.error(f"EventStore: Failed to get events in range: {e}")
            return []

    def _rows_to_events(self, cursor) -> list[TradingEvent]:
        """Convert DB rows to TradingEvent objects"""
        events = []
        for row in cursor:
            events.append(TradingEvent(
                event_id=row[0],
                event_type=EventType(row[1]),
                priority=EventPriority(row[2]),
                timestamp=row[3],
                source=row[4],
                intent_id=row[5],
                client_order_id=row[6],
                broker_order_id=row[7],
                symbol=row[8],
                direction=row[9],
                quantity=row[10],
                price=row[11],
                metadata=json.loads(row[12] or "{}"),
            ))
        return events


class EventBus:
    """
    Event Bus - pub/sub messaging for event-driven architecture.
    Handles event dispatch to registered handlers.
    """

    def __init__(self, event_store: EventStore | None = None):
        self._subscribers: dict[EventType, list[EventHandler]] = {}
        self._lock = threading.RLock()
        self._event_store = event_store or EventStore()
        self._event_history: list[TradingEvent] = []
        self._max_history = 10000

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe to specific event type"""
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            if handler not in self._subscribers[event_type]:
                self._subscribers[event_type].append(handler)
                _log.debug(f"Subscribed handler to {event_type.value}")

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Unsubscribe from event type"""
        with self._lock:
            if event_type in self._subscribers:
                self._subscribers[event_type].remove(handler)

    def publish(self, event: TradingEvent) -> bool:
        """
        Publish event to all subscribers.
        Events are also persisted to event store (event sourcing).
        """
        self._event_store.append(event)

        with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history = self._event_history[-self._max_history:]

        handlers = []
        with self._lock:
            handlers = self._subscribers.get(event.event_type, []).copy()

        for handler in handlers:
            try:
                handler(event)
            except (ValueError, TypeError, KeyError, AttributeError, OSError) as e:
                _log.error(f"Event handler failed for {event.event_type.value}: {e}")

        return True

    def publish_signal_generated(
        self,
        intent_id: str,
        symbol: str,
        direction: str,
        quantity: int,
        price: float,
        metadata: dict[str, Any],
    ) -> TradingEvent:
        """Helper: publish SIGNAL_GENERATED event"""
        event = TradingEvent(
            event_type=EventType.SIGNAL_GENERATED,
            source="signal_generator",
            intent_id=intent_id,
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            price=price,
            metadata=metadata,
        )
        return event if self.publish(event) else None

    def publish_risk_approved(
        self,
        intent_id: str,
        client_order_id: str,
        metadata: dict[str, Any],
    ) -> TradingEvent:
        """Helper: publish RISK_APPROVED event"""
        event = TradingEvent(
            event_type=EventType.RISK_APPROVED,
            source="risk_engine",
            intent_id=intent_id,
            client_order_id=client_order_id,
            metadata=metadata,
        )
        return event if self.publish(event) else None

    def publish_order_submitted(
        self,
        intent_id: str,
        client_order_id: str,
        broker_order_id: str,
        symbol: str,
        direction: str,
        quantity: int,
        price: float,
    ) -> TradingEvent:
        """Helper: publish ORDER_SUBMITTED event"""
        event = TradingEvent(
            event_type=EventType.ORDER_SUBMITTED,
            source="execution_service",
            intent_id=intent_id,
            client_order_id=client_order_id,
            broker_order_id=broker_order_id,
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            price=price,
        )
        return event if self.publish(event) else None

    def publish_broker_ack(
        self,
        client_order_id: str,
        broker_order_id: str,
        metadata: dict[str, Any],
    ) -> TradingEvent:
        """Helper: publish BROKER_ACK_RECEIVED event"""
        event = TradingEvent(
            event_type=EventType.BROKER_ACK_RECEIVED,
            source="broker_gateway",
            client_order_id=client_order_id,
            broker_order_id=broker_order_id,
            metadata=metadata,
        )
        return event if self.publish(event) else None

    def publish_fill(
        self,
        client_order_id: str,
        broker_order_id: str,
        symbol: str,
        direction: str,
        filled_qty: int,
        avg_price: float,
        is_final: bool,
    ) -> TradingEvent:
        """Helper: publish FILL_RECEIVED or PARTIAL_FILL_RECEIVED"""
        event_type = EventType.FILL_RECEIVED if is_final else EventType.PARTIAL_FILL_RECEIVED
        event = TradingEvent(
            event_type=event_type,
            source="execution_service",
            client_order_id=client_order_id,
            broker_order_id=broker_order_id,
            symbol=symbol,
            direction=direction,
            quantity=filled_qty,
            price=avg_price,
            metadata={"is_final": is_final},
        )
        return event if self.publish(event) else None

    def publish_risk_breached(
        self,
        limit_type: str,
        current_value: float,
        threshold: float,
        metadata: dict[str, Any],
    ) -> TradingEvent:
        """Helper: publish RISK_LIMIT_BREACHED event"""
        event = TradingEvent(
            event_type=EventType.RISK_LIMIT_BREACHED,
            priority=EventPriority.CRITICAL,
            source="risk_engine",
            metadata={
                "limit_type": limit_type,
                "current_value": current_value,
                "threshold": threshold,
                **metadata,
            },
        )
        return event if self.publish(event) else None

    def replay_order(self, client_order_id: str) -> list[TradingEvent]:
        """Replay all events for an order (event sourcing)"""
        return self._event_store.get_events_for_order(client_order_id)

    def get_recent_events(self, count: int = 100) -> list[TradingEvent]:
        """Get recent events from in-memory history"""
        return self._event_history[-count:]


_event_bus: EventBus | None = None
_event_bus_lock = threading.RLock()


def get_event_bus() -> EventBus:
    """Get singleton event bus"""
    global _event_bus
    with _event_bus_lock:
        if _event_bus is None:
            _event_bus = EventBus()
        return _event_bus


def get_event_store() -> EventStore:
    """Get singleton event store"""
    return get_event_bus()._event_store
