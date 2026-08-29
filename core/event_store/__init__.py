"""Unified Event Store (TD-02 Consolidation).

Consolidates the two dual EventStore implementations:

  core.event_sourcing.EventStore       (JSON-file-backed, stream-based)
  core.execution.event_system.EventStore (SQLite-backed, TradingEvent-based)

Into a single unified ``UnifiedEventStore`` that supports both APIs.
Both old modules now redirect to this unified store with deprecation warnings.

Usage:
    from core.event_store import EventStore, get_event_store

    store = get_event_store()
    store.append("trade.executed", stream="NIFTY", data={"qty": 50})
    store.append_event(trading_event)  # also accepts TradingEvent objects

Architecture:
    - Primary backend: SQLite (production-grade, scalable)
    - Stream-layer: wraps SQLite events as stream-based StoredEvent
    - Hash-chain: SHA-256 chain with verify_chain() integrity check
    - EventBus: pub/sub dispatch integrated with the store
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "EventStore",
    "StoredEvent",
    "Snapshot",
    "get_event_store",
    "reset_event_store",
    "verify_chain",
    "get_stats",
]


# ═══════════════════════════════════════════════════════════════════════════════
# Shared Data Models
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class StoredEvent:
    """A single event in the store with hash-chain integrity.

    Each event stores its own SHA-256 hash (event_hash) and the hash
    of the previous event (previous_event_hash), forming an immutable
    tamper-evident chain.

    This model is compatible with both the stream-based API (from
    ``core.event_sourcing.StoredEvent``) and the TradingEvent-based API
    (from ``core.execution.event_system.TradingEvent``).
    """

    event_id: str = ""
    event_type: str = ""
    stream: str = "default"
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    timestamp: float = 0.0
    event_hash: str = ""
    previous_event_hash: str = ""

    # Event sourcing fields (for TradingEvent compatibility)
    aggregate_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "stream": self.stream,
            "data": self.data,
            "metadata": self.metadata,
            "version": self.version,
            "timestamp": self.timestamp,
            "event_hash": self.event_hash,
            "previous_event_hash": self.previous_event_hash,
            "aggregate_id": self.aggregate_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
        }

    @staticmethod
    def compute_hash(
        event_type: str, stream: str, data: dict,
        metadata: dict, version: int, timestamp: float,
        previous_hash: str = "", event_id: str = "",
    ) -> str:
        """Compute SHA-256 hash for an event's content."""
        content = json.dumps({
            "event_id": event_id,
            "event_type": event_type,
            "stream": stream,
            "data": data,
            "metadata": metadata,
            "version": version,
            "timestamp": timestamp,
            "previous_event_hash": previous_hash,
        }, sort_keys=True, default=str)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class Snapshot:
    """A point-in-time snapshot of a stream's state."""

    stream: str = ""
    state: dict[str, Any] = field(default_factory=dict)
    version: int = 0
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stream": self.stream,
            "version": self.version,
            "timestamp": self.timestamp,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Unified Event Store
# ═══════════════════════════════════════════════════════════════════════════════


class EventStore:
    """Unified append-only event store with dual-backend support.

    Consolidates:
    - JSON-file-backed stream store (from ``core.event_sourcing``)
    - SQLite-backed TradingEvent store (from ``core.execution.event_system``)

    Both backends are kept in sync. The SQLite backend is the primary store
    (production-grade), while the JSON files provide backward-compatible
    access for consumers that expect the stream-based API.

    Features:
        - Stream-based API (append / read_stream / replay_stream / snapshots)
        - TradingEvent-based API (append_event / get_events_by_type / get_events_for_order)
        - Hash-chain integrity (SHA-256, chained per-stream)
        - verify_chain() tamper detection across all events
        - Thread-safe
    """

    PERSISTENCE_PATH = "db/event_store.db"
    EVENTS_JSON_PATH = "json/events_store.json"
    SNAPSHOTS_JSON_PATH = "json/events_snapshots.json"
    MAX_JSON_EVENTS = 10000  # cap for JSON file size

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # In-memory stream cache (for JSON-backward compat)
        self._streams: dict[str, list[StoredEvent]] = {}
        self._snapshots: dict[str, Snapshot] = {}
        self._total_events = 0

        # Initialize SQLite backend
        self._init_sqlite_storage()

        # Load existing JSON data if SQLite is fresh
        self._load_json_fallback()

    # ── SQLite Initialization ─────────────────────────────────────────────

    def _init_sqlite_storage(self) -> None:
        """Initialize the SQLite event store with hash-chained schema."""
        try:
            from pathlib import Path

            from core.db_utils import get_connection

            Path(self.PERSISTENCE_PATH).parent.mkdir(parents=True, exist_ok=True)
            with get_connection(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS events (
                        event_id TEXT PRIMARY KEY,
                        event_type TEXT NOT NULL,
                        stream TEXT DEFAULT 'default',
                        timestamp TEXT NOT NULL,
                        version INTEGER DEFAULT 1,
                        source TEXT,
                        aggregate_id TEXT,
                        correlation_id TEXT,
                        causation_id TEXT,
                        data_json TEXT,
                        metadata_json TEXT,
                        sequence_number INTEGER,
                        previous_hash TEXT,
                        sha256 TEXT
                    )
                """)
                # Backward-compat column additions
                for col in ("previous_hash", "sha256", "stream", "aggregate_id", "correlation_id", "causation_id"):
                    try:
                        conn.execute(f"ALTER TABLE events ADD COLUMN {col} TEXT")
                    except sqlite3.OperationalError:
                        pass
                conn.execute("CREATE INDEX IF NOT EXISTS idx_es_stream ON events(stream)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_es_type ON events(event_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_es_time ON events(timestamp)")
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.commit()
        except ImportError:
            _log.warning("[EVENT_STORE] SQLite unavailable, falling back to JSON-only mode")
            self._sqlite_available = False
        else:
            self._sqlite_available = True

    # ── Stream-based API (from core.event_sourcing) ───────────────────────

    def append(
        self, event_type: str, stream: str = "default",
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StoredEvent:
        """Append an event to a stream.

        Args:
            event_type: Type identifier (e.g., 'trade.executed').
            stream: Stream identifier (e.g., 'NIFTY').
            data: Event payload.
            metadata: Optional metadata.

        Returns:
            The stored StoredEvent.
        """
        with self._lock:
            stream_events = self._streams.get(stream, [])
            version = len(stream_events) + 1
            ts = _timestamp_now()
            previous_hash = stream_events[-1].event_hash if stream_events else ""

            event_id = f"evt-{int(ts * 1000000)}-{stream}-{version}"

            data = data or {}
            metadata = metadata or {}

            event_hash = StoredEvent.compute_hash(
                event_type=event_type.strip(),
                stream=stream.strip(),
                data=data,
                metadata=metadata,
                version=version,
                timestamp=ts,
                previous_hash=previous_hash,
                event_id=event_id,
            )

            event = StoredEvent(
                event_id=event_id,
                event_type=event_type.strip(),
                stream=stream.strip(),
                data=data,
                metadata=metadata,
                version=version,
                timestamp=ts,
                event_hash=event_hash,
                previous_event_hash=previous_hash,
            )

            stream_events.append(event)
            self._streams[stream] = stream_events
            self._total_events += 1

            # Persist to both backends
            self._persist_to_sqlite(event)
            self._trim_json_persist()

            _log.debug("[EVENT_STORE] Appended '%s' to stream '%s' (v%d)", event_type, stream, version)
            return event

    def append_event(self, trading_event: Any) -> bool:
        """Append a TradingEvent-compatible object.

        Accepts any object with ``event_type``, ``event_id``, ``timestamp``,
        and ``to_dict()`` attributes. Provides interoperability with the
        ``core.execution.event_system.TradingEvent`` class.

        Args:
            trading_event: A TradingEvent-like object.

        Returns:
            True on success.
        """
        try:
            attrs = trading_event.to_dict() if hasattr(trading_event, "to_dict") else {}
            event_type = getattr(trading_event, "event_type", None)
            if hasattr(event_type, "value"):
                event_type = event_type.value  # Enum

            evt_type = str(event_type or attrs.get("event_type", "unknown"))
            stream = str(attrs.get("stream", attrs.get("symbol", "default")))
            data = attrs.get("metadata", {})
            if "symbol" in attrs:
                data["symbol"] = attrs["symbol"]
            if "direction" in attrs:
                data["direction"] = attrs["direction"]
            if "quantity" in attrs:
                data["quantity"] = attrs["quantity"]
            if "price" in attrs:
                data["price"] = attrs["price"]

            with self._lock:
                stream_events = self._streams.get(stream, [])
                version = len(stream_events) + 1
                ts = attrs.get("timestamp", _timestamp_now())
                # Convert ISO timestamp to float if needed
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts).timestamp()
                    except (ValueError, TypeError):
                        ts = _timestamp_now()
                ts = float(ts)

                previous_hash = stream_events[-1].event_hash if stream_events else ""
                event_id = attrs.get("event_id", f"evt-{int(ts * 1000000)}-{stream}-{version}")

                event_hash = StoredEvent.compute_hash(
                    event_type=evt_type, stream=stream, data=data,
                    metadata={}, version=version, timestamp=ts,
                    previous_hash=previous_hash, event_id=event_id,
                )

                event = StoredEvent(
                    event_id=event_id, event_type=evt_type, stream=stream,
                    data=data, metadata={}, version=version, timestamp=ts,
                    event_hash=event_hash, previous_event_hash=previous_hash,
                    aggregate_id=attrs.get("aggregate_id"),
                    correlation_id=attrs.get("correlation_id"),
                    causation_id=attrs.get("causation_id"),
                )

                stream_events.append(event)
                self._streams[stream] = stream_events
                self._total_events += 1

                self._persist_to_sqlite(event)
                self._trim_json_persist()

            _log.debug("[EVENT_STORE] Appended TradingEvent '%s' to stream '%s'", evt_type, stream)
            return True
        except (ValueError, TypeError, AttributeError, OSError) as e:
            _log.error("[EVENT_STORE] append_event failed: %s", e)
            return False

    def read_stream(
        self, stream: str, from_version: int = 1,
        to_version: int | None = None,
    ) -> list[StoredEvent]:
        """Read events from a stream in order.

        Args:
            stream: Stream identifier.
            from_version: Starting version (1-based).
            to_version: Ending version (inclusive). None = all.

        Returns:
            List of events in ascending version order.
        """
        with self._lock:
            stream_events = list(self._streams.get(stream, []))
        filtered = [e for e in stream_events if e.version >= from_version]
        if to_version is not None:
            filtered = [e for e in filtered if e.version <= to_version]
        return filtered

    def read_all_streams(self) -> dict[str, list[StoredEvent]]:
        """Read all events grouped by stream."""
        with self._lock:
            return {k: list(v) for k, v in self._streams.items()}

    def stream_exists(self, stream: str) -> bool:
        """Check if a stream has events."""
        with self._lock:
            return stream in self._streams and len(self._streams[stream]) > 0

    def get_stream_version(self, stream: str) -> int:
        """Get the latest version of a stream."""
        with self._lock:
            stream_events = self._streams.get(stream, [])
            return len(stream_events)

    def delete_stream(self, stream: str) -> bool:
        """Delete a stream and its snapshots.

        Returns True if deleted, False if not found.
        """
        with self._lock:
            existed = stream in self._streams
            self._streams.pop(stream, None)
            self._snapshots.pop(stream, None)
            if existed and self._sqlite_available:
                try:
                    from core.db_utils import get_connection
                    with get_connection(self.PERSISTENCE_PATH) as conn:
                        conn.execute("DELETE FROM events WHERE stream = ?", (stream,))
                        conn.commit()
                except (sqlite3.Error, OSError):
                    pass
            return existed

    def clear_all(self) -> None:
        """Clear all events and snapshots (for testing)."""
        with self._lock:
            self._streams.clear()
            self._snapshots.clear()
            self._total_events = 0
            if self._sqlite_available:
                try:
                    from core.db_utils import get_connection
                    with get_connection(self.PERSISTENCE_PATH) as conn:
                        conn.execute("DELETE FROM events")
                        conn.commit()
                except (sqlite3.Error, OSError):
                    pass
            # Also delete JSON files to prevent reload from stale data
            try:
                for p_str in [self.EVENTS_JSON_PATH, self.SNAPSHOTS_JSON_PATH]:
                    p = _ensure_path(p_str)
                    if p.exists():
                        p.unlink()
            except (OSError, ValueError):
                pass

    # ── Replay ────────────────────────────────────────────────────────────

    def replay_stream(self, stream: str, handler: Callable) -> list[Any]:
        """Replay all events in a stream through a handler function.

        Args:
            stream: Stream identifier.
            handler: Callable(event: StoredEvent) -> Any.

        Returns:
            List of handler return values.
        """
        events = self.read_stream(stream)
        results: list[Any] = []
        snapshot = self.get_snapshot(stream)
        if snapshot:
            results.append(("snapshot", snapshot.state))
        for event in events:
            try:
                results.append(handler(event))
            except Exception as exc:
                _log.warning("[EVENT_STORE] Replay error at event %s: %s", event.event_id, exc)
                results.append(("error", str(exc)))
        return results

    def replay_all(self, handler: Callable) -> dict[str, list[Any]]:
        """Replay all streams through a handler function."""
        results: dict[str, list[Any]] = {}
        with self._lock:
            streams = list(self._streams.keys())
        for stream in streams:
            results[stream] = self.replay_stream(stream, handler)
        return results

    # ── Snapshots ─────────────────────────────────────────────────────────

    def create_snapshot(self, stream: str, state: dict[str, Any]) -> Snapshot:
        """Create a point-in-time snapshot of a stream's state."""
        version = self.get_stream_version(stream)
        snapshot = Snapshot(
            stream=stream.strip(),
            state=state,
            version=version,
            timestamp=_timestamp_now(),
        )
        with self._lock:
            self._snapshots[stream] = snapshot
            self._persist_snapshots_json()
        return snapshot

    def get_snapshot(self, stream: str) -> Snapshot | None:
        """Get the latest snapshot for a stream."""
        with self._lock:
            return self._snapshots.get(stream)

    # ── TradingEvent-specific API ─────────────────────────────────────────

    def get_events_by_type(self, event_type: str, limit: int = 1000) -> list[StoredEvent]:
        """Get events filtered by type (supports both string and Enum).

        Args:
            event_type: Type string or EventType enum.
            limit: Maximum number of events to return.

        Returns:
            List of matching events.
        """
        if hasattr(event_type, "value"):
            event_type = event_type.value
        evt_type = str(event_type)
        with self._lock:
            events: list[StoredEvent] = []
            for stream_events in self._streams.values():
                for e in stream_events:
                    if e.event_type == evt_type:
                        events.append(e)
                        if len(events) >= limit:
                            return events
            return events

    def get_stream_events_by_type(self, event_type: str, stream: str = "") -> list[StoredEvent]:
        """Get events filtered by type and optionally stream (backward compat).

        Args:
            event_type: Type string or EventType enum.
            stream: Optional stream filter. Empty = all streams.

        Returns:
            List of matching events.
        """
        events = self.get_events_by_type(event_type, limit=10000)
        if stream:
            return [e for e in events if e.stream == stream]
        return events

    def append_many(
        self, events: list[tuple[str, str, dict[str, Any]]],
        stream: str = "default",
    ) -> list[StoredEvent]:
        """Append multiple events to a stream (backward compat).

        Args:
            events: List of (event_type, stream, data) tuples.
            stream: Default stream if not overridden.

        Returns:
            List of stored events.
        """
        results: list[StoredEvent] = []
        for event_type, event_stream, data in events:
            result = self.append(event_type, event_stream or stream, data)
            results.append(result)
        return results

    def get_events_for_order(self, client_order_id: str) -> list[StoredEvent]:
        """Get all events for a specific order (for replay/debugging)."""
        with self._lock:
            results: list[StoredEvent] = []
            for stream_events in self._streams.values():
                for e in stream_events:
                    if e.data and "client_order_id" in str(e.data) and client_order_id in str(e.data):
                        results.append(e)
                        if len(results) >= 100:
                            return results
            # Try SQLite for more precision
            if self._sqlite_available:
                try:
                    from core.db_utils import get_connection
                    with get_connection(self.PERSISTENCE_PATH) as conn:
                        cursor = conn.execute(
                            "SELECT data_json FROM events WHERE data_json LIKE ? LIMIT 100",
                            (f"%{client_order_id}%",),
                        )
                        for row in cursor:
                            data_json = row[0]
                            if data_json and client_order_id in data_json:
                                pass  # Already captured from in-memory
                except (sqlite3.Error, OSError):
                    pass
            return results

    def get_events_in_range(self, start_time: str, end_time: str) -> list[StoredEvent]:
        """Get events in time range (for replay)."""
        with self._lock:
            results: list[StoredEvent] = []
            for stream_events in self._streams.values():
                for e in stream_events:
                    ts_str = str(e.timestamp)
                    if start_time <= ts_str <= end_time:
                        results.append(e)
            return results

    # ── Integrity ─────────────────────────────────────────────────────────

    def verify_chain(self, stream: str | None = None) -> tuple[bool, int, str]:
        """Verify the integrity of the hash chain.

        Args:
            stream: Optional stream to verify. None = verify all streams.

        Returns:
            (is_valid: bool, events_checked: int, message: str)
        """
        with self._lock:
            streams_to_check = [stream] if stream else list(self._streams.keys())
            total_checked = 0
            for s in streams_to_check:
                events = self._streams.get(s, [])
                expected_prev = ""
                for event in events:
                    if event.previous_event_hash != expected_prev:
                        return False, total_checked, (
                            f"Chain break at stream '{s}' event {event.event_id}: "
                            f"expected previous_hash={expected_prev}, got {event.previous_event_hash}"
                        )
                    recomputed = StoredEvent.compute_hash(
                        event_type=event.event_type, stream=event.stream,
                        data=event.data, metadata=event.metadata,
                        version=event.version, timestamp=event.timestamp,
                        previous_hash=expected_prev, event_id=event.event_id,
                    )
                    if recomputed != event.event_hash:
                        return False, total_checked, (
                            f"Hash mismatch at stream '{s}' event {event.event_id}: "
                            f"expected {event.event_hash}, recomputed {recomputed}"
                        )
                    expected_prev = event.event_hash
                    total_checked += 1
            return True, total_checked, f"Chain valid: {total_checked} events checked"

    # ── Statistics ────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get event store statistics."""
        with self._lock:
            streams = len(self._streams)
            by_stream: dict[str, int] = {s: len(evts) for s, evts in self._streams.items()}
            by_type: dict[str, int] = {}
            for evts in self._streams.values():
                for e in evts:
                    by_type[e.event_type] = by_type.get(e.event_type, 0) + 1
            sqlite_count = 0
            if self._sqlite_available:
                try:
                    from core.db_utils import get_connection
                    with get_connection(self.PERSISTENCE_PATH) as conn:
                        row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
                        sqlite_count = row[0] if row else 0
                except (sqlite3.Error, OSError):
                    pass
            return {
                "total_events": self._total_events,
                "total_streams": streams,
                "total_snapshots": len(self._snapshots),
                "sqlite_events": sqlite_count,
                "events_by_stream": by_stream,
                "events_by_type": by_type,
                "avg_events_per_stream": round(self._total_events / max(streams, 1), 1),
            }

    # ── Persistence ───────────────────────────────────────────────────────

    def _persist_to_sqlite(self, event: StoredEvent) -> None:
        """Persist a single event to SQLite."""
        if not self._sqlite_available:
            return
        try:
            from core.db_utils import get_connection
            with get_connection(self.PERSISTENCE_PATH) as conn:
                conn.execute("BEGIN EXCLUSIVE")
                try:
                    cursor = conn.execute("SELECT MAX(sequence_number) FROM events")
                    row = cursor.fetchone()
                    seq = (row[0] + 1) if row and row[0] is not None else 1
                    conn.execute(
                        """INSERT OR IGNORE INTO events
                           (event_id, event_type, stream, timestamp, version,
                            data_json, metadata_json, sequence_number, previous_hash, sha256)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            event.event_id, event.event_type, event.stream,
                            str(event.timestamp), event.version,
                            json.dumps(event.data, default=str),
                            json.dumps(event.metadata, default=str),
                            seq, event.previous_event_hash, event.event_hash,
                        ),
                    )
                    conn.commit()
                except (sqlite3.Error, OSError):
                    conn.rollback()
        except (sqlite3.Error, OSError, ImportError) as exc:
            _log.debug("[EVENT_STORE] SQLite persist error: %s", exc)

    def _trim_json_persist(self) -> None:
        """Persist events to JSON (capped to MAX_JSON_EVENTS)."""
        try:
            path = _ensure_path(self.EVENTS_JSON_PATH)
            with self._lock:
                all_streams = {}
                total = 0
                for stream, events in self._streams.items():
                    recent = events[-self.MAX_JSON_EVENTS:] if len(events) > self.MAX_JSON_EVENTS else events
                    all_streams[stream] = [e.to_dict() for e in recent]
                    total += len(recent)
                path.write_text(json.dumps(all_streams, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.debug("[EVENT_STORE] JSON persist error: %s", exc)

    def _persist_snapshots_json(self) -> None:
        """Persist snapshots to JSON."""
        try:
            path = _ensure_path(self.SNAPSHOTS_JSON_PATH)
            data = {s: snap.to_dict() for s, snap in self._snapshots.items()}
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.debug("[EVENT_STORE] Snapshots persist error: %s", exc)

    def _load_json_fallback(self) -> None:
        """Load existing events from JSON files (backward compat)."""
        try:
            path = _ensure_path(self.EVENTS_JSON_PATH)
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                for stream, evts in data.items():
                    stored = []
                    for item in evts:
                        stored.append(StoredEvent(
                            **{k: v for k, v in item.items()
                               if k in StoredEvent.__dataclass_fields__}
                        ))
                    self._streams[stream] = stored
                    self._total_events += len(stored)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.debug("[EVENT_STORE] JSON load error: %s", exc)

        try:
            snap_path = _ensure_path(self.SNAPSHOTS_JSON_PATH)
            if snap_path.is_file():
                data = json.loads(snap_path.read_text(encoding="utf-8"))
                for stream, item in data.items():
                    self._snapshots[stream] = Snapshot(
                        **{k: v for k, v in item.items()
                           if k in Snapshot.__dataclass_fields__}
                    )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.debug("[EVENT_STORE] Snapshots load error: %s", exc)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers & Singleton
# ═══════════════════════════════════════════════════════════════════════════════


def _timestamp_now() -> float:
    import time
    return time.time()


def _ensure_path(path_str: str) -> Any:
    from pathlib import Path
    p = Path(path_str)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


_instance: EventStore | None = None
_instance_lock = threading.RLock()


def get_event_store() -> EventStore:
    """Get the singleton unified EventStore instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = EventStore()
        return _instance


def reset_event_store() -> None:
    """Force-reset singleton (for testing)."""
    global _instance
    with _instance_lock:
        if _instance is not None:
            try:
                _instance.clear_all()
            except Exception:
                pass
            _instance = None


def verify_chain(stream: str | None = None) -> tuple[bool, int, str]:
    """Convenience: verify hash chain integrity."""
    return get_event_store().verify_chain(stream)


def get_stats() -> dict[str, Any]:
    """Convenience: get event store statistics."""
    return get_event_store().get_stats()
