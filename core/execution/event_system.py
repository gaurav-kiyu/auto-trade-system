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
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
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


class EventPriority(Enum):
    """Event priority levels for ordering"""
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
        """Initialize SQLite event store"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
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
                        sequence_number INTEGER
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON events(timestamp)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_event_type ON events(event_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_intent ON events(intent_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_client_order ON events(client_order_id)")
                conn.commit()
            _log.info("EventStore: Durable storage initialized")
        except Exception as e:
            _log.error(f"EventStore: Failed to init storage: {e}")

    def append(self, event: TradingEvent) -> bool:
        """Append event to store (immutable - always append)"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                cursor = conn.execute("SELECT MAX(sequence_number) FROM events")
                seq = (cursor.fetchone()[0] or 0) + 1

                conn.execute("""
                    INSERT INTO events
                    (event_id, event_type, priority, timestamp, source, intent_id,
                     client_order_id, broker_order_id, symbol, direction, quantity,
                     price, metadata_json, sequence_number)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ))
                conn.commit()
            return True
        except Exception as e:
            _log.error(f"EventStore: Failed to append event {event.event_id}: {e}")
            return False

    def get_events_for_order(self, client_order_id: str) -> list[TradingEvent]:
        """Get all events for a specific order (for replay/debugging)"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
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
        except Exception as e:
            _log.error(f"EventStore: Failed to get events for order: {e}")
            return []

    def get_events_by_type(self, event_type: EventType, limit: int = 1000) -> list[TradingEvent]:
        """Get events by type"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
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
        except Exception as e:
            _log.error(f"EventStore: Failed to get events by type: {e}")
            return []

    def get_events_in_range(self, start_time: str, end_time: str) -> list[TradingEvent]:
        """Get events in time range (for replay)"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                cursor = conn.execute("""
                    SELECT event_id, event_type, priority, timestamp, source, intent_id,
                           client_order_id, broker_order_id, symbol, direction, quantity,
                           price, metadata_json
                    FROM events
                    WHERE timestamp >= ? AND timestamp <= ?
                    ORDER BY sequence_number
                """, (start_time, end_time))

                return self._rows_to_events(cursor)
        except Exception as e:
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
        self._lock = threading.Lock()
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
            except Exception as e:
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
_event_bus_lock = threading.Lock()


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
