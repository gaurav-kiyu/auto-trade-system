"""
Durable Execution State Persistence.

Persists execution state to SQLite to survive restarts/crashes.
Critical for preventing duplicate orders on crash/restart scenarios.
"""

from __future__ import annotations

import logging
import sqlite3
import threading

from core.db_utils import get_connection
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist
from core.exceptions import DatabaseError

log = logging.getLogger(__name__)

# Whitelist of allowed column names for dynamic SQL updates
_ALLOWED_UPDATE_COLS = {
    "state", "updated_at", "broker_order_id", "filled_quantity", "average_price", "reject_reason",
}


class ExecutionState(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass
class DurableExecutionRecord:
    intent_id: str
    client_order_id: str
    symbol: str
    direction: str
    quantity: int
    strike_price: float
    state: ExecutionState
    broker_order_id: str | None = None
    filled_quantity: int = 0
    average_price: float = 0.0
    reject_reason: str | None = None
    created_at: datetime = field(default_factory=now_ist)
    updated_at: datetime = field(default_factory=now_ist)
    retry_count: int = 0


class DurableExecutionStore:
    """
    Thread-safe durable execution state store using SQLite.

    Persists order execution state to survive crashes/restarts.
    Provides atomic operations to prevent race conditions.
    """

    _TERMINAL_STATES = {
        ExecutionState.FILLED,
        ExecutionState.CANCELLED,
        ExecutionState.REJECTED,
        ExecutionState.FAILED,
    }

    def __init__(self, db_path: str = "execution_state.db"):
        self._db_path = Path(db_path)
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite schema for execution state."""
        try:
            with self._lock:
                with get_connection(self._db_path) as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS execution_state (
                            intent_id TEXT PRIMARY KEY,
                            client_order_id TEXT NOT NULL,
                            symbol TEXT NOT NULL,
                            direction TEXT NOT NULL,
                            quantity INTEGER NOT NULL,
                            strike_price REAL NOT NULL,
                            state TEXT NOT NULL,
                            broker_order_id TEXT,
                            filled_quantity INTEGER DEFAULT 0,
                            average_price REAL DEFAULT 0.0,
                            reject_reason TEXT,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            retry_count INTEGER DEFAULT 0
                        )
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_exec_state
                        ON execution_state(state)
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_exec_updated
                        ON execution_state(updated_at)
                    """)
                    conn.commit()
            log.info(f"Durable execution store initialized: {self._db_path}")
        except (DatabaseError, sqlite3.Error, OSError) as e:
            log.error(f"Failed to initialize execution state DB: {e}")
            raise

    def save_execution(self, record: DurableExecutionRecord) -> bool:
        """Save or update execution state atomically."""
        try:
            with self._lock:
                with get_connection(self._db_path) as conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO execution_state (
                            intent_id, client_order_id, symbol, direction,
                            quantity, strike_price, state, broker_order_id,
                            filled_quantity, average_price, reject_reason,
                            created_at, updated_at, retry_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        record.intent_id,
                        record.client_order_id,
                        record.symbol,
                        record.direction,
                        record.quantity,
                        record.strike_price,
                        record.state.value,
                        record.broker_order_id,
                        record.filled_quantity,
                        record.average_price,
                        record.reject_reason,
                        record.created_at.isoformat(),
                        record.updated_at.isoformat(),
                        record.retry_count,
                    ))
                    conn.commit()
            return True
        except (DatabaseError, sqlite3.Error, OSError) as e:
            log.error(f"Failed to save execution state for {record.intent_id}: {e}")
            return False

    def get_execution(self, intent_id: str) -> DurableExecutionRecord | None:
        """Get execution state by intent_id."""
        try:
            with self._lock:
                with get_connection(self._db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute(
                        "SELECT * FROM execution_state WHERE intent_id = ?",
                        (intent_id,)
                    )
                    row = cursor.fetchone()
                    if row:
                        return self._row_to_record(row)
                    return None
        except (DatabaseError, sqlite3.Error, OSError) as e:
            log.error(f"Failed to get execution state for {intent_id}: {e}")
            return None

    def get_non_terminal_executions(self) -> list[DurableExecutionRecord]:
        """Get all non-terminal executions for reconciliation."""
        try:
            with self._lock:
                with get_connection(self._db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute("""
                        SELECT * FROM execution_state
                        WHERE state NOT IN (?, ?, ?, ?)
                        ORDER BY updated_at ASC
                    """, tuple(s.value for s in self._TERMINAL_STATES))
                    return [self._row_to_record(row) for row in cursor.fetchall()]
        except (DatabaseError, sqlite3.Error, OSError) as e:
            log.error(f"Failed to get non-terminal executions: {e}")
            return []

    def is_duplicate(self, intent_id: str) -> bool:
        """Check if intent_id exists and is non-terminal (would cause duplicate)."""
        record = self.get_execution(intent_id)
        if record is None:
            return False
        return record.state not in self._TERMINAL_STATES

    def update_state(
        self,
        intent_id: str,
        state: ExecutionState,
        broker_order_id: str | None = None,
        filled_quantity: int = 0,
        average_price: float = 0.0,
        reject_reason: str | None = None,
    ) -> bool:
        """Update execution state atomically."""
        try:
            with self._lock:
                with get_connection(self._db_path) as conn:
                    updates = ["state = ?", "updated_at = ?"]
                    params = [state.value, now_ist().isoformat()]

                    if broker_order_id is not None:
                        updates.append("broker_order_id = ?")
                        params.append(broker_order_id)
                    if filled_quantity > 0:
                        updates.append("filled_quantity = ?")
                        params.append(filled_quantity)
                    if average_price > 0:
                        updates.append("average_price = ?")
                        params.append(average_price)
                    if reject_reason is not None:
                        updates.append("reject_reason = ?")
                        params.append(reject_reason)

                    # Validate column names against whitelist (defense-in-depth)
                    for u in updates:
                        col = u.split(" = ")[0].strip()
                        if col not in _ALLOWED_UPDATE_COLS:
                            raise ValueError(f"Invalid column: {col}")
                    params.append(intent_id)

                    conn.execute(
                        f"UPDATE execution_state SET {', '.join(updates)} WHERE intent_id = ?",
                        params
                    )
                    conn.commit()
            return True
        except (DatabaseError, sqlite3.Error, OSError, ValueError) as e:
            log.error(f"Failed to update execution state for {intent_id}: {e}")
            return False

    def increment_retry(self, intent_id: str) -> int:
        """Increment retry count and return new count."""
        try:
            with self._lock:
                with get_connection(self._db_path) as conn:
                    cursor = conn.execute(
                        "UPDATE execution_state SET retry_count = retry_count + 1, updated_at = ? WHERE intent_id = ?",
                        (now_ist().isoformat(), intent_id)
                    )
                    conn.commit()
                    if cursor.rowcount > 0:
                        result = conn.execute(
                            "SELECT retry_count FROM execution_state WHERE intent_id = ?",
                            (intent_id,)
                        ).fetchone()
                        return result[0] if result else 0
                    return 0
        except (DatabaseError, sqlite3.Error, OSError) as e:
            log.error(f"Failed to increment retry for {intent_id}: {e}")
            return 0

    def clear_in_flight(self, intent_id: str) -> bool:
        """Clear in-flight state after execution failure (allows retry)."""
        return self.update_state(intent_id, ExecutionState.FAILED, reject_reason="Cleared for retry")

    def cleanup_old_records(self, hours: int = 24) -> int:
        """Clean up old terminal records to prevent DB bloat."""
        try:
            with self._lock:
                with get_connection(self._db_path) as conn:
                    cursor = conn.execute("""
                        DELETE FROM execution_state
                        WHERE state IN (?, ?, ?, ?)
                        AND updated_at < datetime('now', ?)
                    """, tuple(s.value for s in self._TERMINAL_STATES) + (f"-{hours} hours",))
                    conn.commit()
                    deleted = cursor.rowcount
                    if deleted > 0:
                        log.info(f"Cleaned up {deleted} old execution records")
                    return deleted
        except (DatabaseError, sqlite3.Error, OSError) as e:
            log.error(f"Failed to cleanup old records: {e}")
            return 0

    def get_stats(self) -> dict[str, Any]:
        """Get execution state statistics."""
        try:
            with self._lock:
                with get_connection(self._db_path) as conn:
                    result = {}
                    for state in ExecutionState:
                        cursor = conn.execute(
                            "SELECT COUNT(*) FROM execution_state WHERE state = ?",
                            (state.value,)
                        )
                        result[state.value] = cursor.fetchone()[0]
                    return result
        except (DatabaseError, sqlite3.Error, OSError) as e:
            log.error(f"Failed to get execution stats: {e}")
            return {}

    def reconcile_with_broker(self, broker_port: Any) -> dict[str, Any]:
        """
        Reconcile in-memory/durable state with broker.

        Returns:
            dict with reconciliation results
        """
        non_terminal = self.get_non_terminal_executions()
        results = {
            "checked": len(non_terminal),
            "filled": 0,
            "still_pending": 0,
            "unknown": 0,
            "repaired": 0,
        }

        for record in non_terminal:
            if not record.broker_order_id:
                results["still_pending"] += 1
                continue

            try:
                if hasattr(broker_port, 'get_order_status'):
                    broker_status = broker_port.get_order_status(record.broker_order_id)
                    if broker_status in ("FILLED", "COMPLETE"):
                        self.update_state(
                            record.intent_id,
                            ExecutionState.FILLED,
                            filled_quantity=record.quantity,
                        )
                        results["filled"] += 1
                    elif broker_status in ("CANCELLED", "REJECTED"):
                        self.update_state(record.intent_id, ExecutionState(broker_status))
                        results["repaired"] += 1
            except (DatabaseError, sqlite3.Error, OSError, ConnectionError) as e:
                log.warning(f"Failed to reconcile {record.intent_id}: {e}")
                results["unknown"] += 1

        return results

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> DurableExecutionRecord:
        return DurableExecutionRecord(
            intent_id=row["intent_id"],
            client_order_id=row["client_order_id"],
            symbol=row["symbol"],
            direction=row["direction"],
            quantity=row["quantity"],
            strike_price=row["strike_price"],
            state=ExecutionState(row["state"]),
            broker_order_id=row["broker_order_id"],
            filled_quantity=row["filled_quantity"],
            average_price=row["average_price"],
            reject_reason=row["reject_reason"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            retry_count=row["retry_count"],
        )


def get_durable_store(db_path: str = "execution_state.db") -> DurableExecutionStore:
    """Get singleton durable execution store."""
    global _durable_store_instance
    if _durable_store_instance is None:
        _durable_store_instance = DurableExecutionStore(db_path)
    return _durable_store_instance


_durable_store_instance: DurableExecutionStore | None = None
