"""
AD-KIYU Write-Ahead Intent Journal v1.0

Before ANY broker side-effect, persist the intent to a durable SQLite WAL.
On crash recovery: replay uncommitted intents and reconcile with broker.

No broker call should proceed without a corresponding WAL entry.

Schema:
  intents: intent_id, action, params_json, risk_verdict_json,
           config_snapshot_hash, correlation_id, status, created_at,
           committed_at, failed_at

Status flow: PENDING → COMMITTED → SETTLED
                                → FAILED
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

from core.db_utils import AsyncDbWriter, get_connection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist

__all__ = [
    "Intent",
    "IntentStatus",
    "WAL_DB_PATH",
    "WriteAheadJournal",
]

_log = logging.getLogger(__name__)

WAL_DB_PATH = "wal_journal.db"

# DDL propagated to the AsyncDbWriter connection so in-memory and file-based
# databases always have the correct schema (DEBT-009).
_WAL_DDL = """
CREATE TABLE IF NOT EXISTS intents (
    intent_id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    params_json TEXT NOT NULL,
    risk_verdict_json TEXT,
    config_snapshot_hash TEXT,
    correlation_id TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    created_at TEXT NOT NULL,
    committed_at TEXT,
    failed_at TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_intents_status ON intents(status);
CREATE INDEX IF NOT EXISTS idx_intents_correlation ON intents(correlation_id);
"""


class IntentStatus:
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


@dataclass
class Intent:
    intent_id: str
    action: str
    params: dict[str, Any]
    risk_verdict: dict[str, Any] | None = None
    config_snapshot_hash: str = ""
    correlation_id: str = ""
    status: str = IntentStatus.PENDING
    created_at: str = ""
    committed_at: str | None = None
    failed_at: str | None = None
    error_message: str = ""


class WriteAheadJournal:
    """Thread-safe write-ahead journal for broker intents.

    Uses AsyncDbWriter (queue-based) for high-frequency append/update operations
    to avoid blocking the trading loop on SQLite write contention (DEBT-009).
    Read operations (get_intent, get_pending, etc.) remain synchronous.
    """

    def __init__(self, db_path: str = WAL_DB_PATH):
        self._db_path = Path(db_path)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._async_writer: AsyncDbWriter | None = None
        self._init_db()
        _log.info("WAL journal initialized at %s", self._db_path)

    def _get_conn(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                self._conn = get_connection(self._db_path)
            return self._conn

    def _get_async_writer(self) -> AsyncDbWriter:
        with self._lock:
            if self._async_writer is None:
                self._async_writer = AsyncDbWriter(
                    self._db_path,
                    max_queue_size=512,
                    wal=True,
                    busy_timeout_ms=5000,
                    init_sql=_WAL_DDL,
                )
            return self._async_writer

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
            # Use the shared DDL constant as single source of truth
            conn.executescript(_WAL_DDL)
            conn.commit()

    def append(self, intent: Intent) -> None:
        """Append a PENDING intent via AsyncDbWriter (non-blocking)."""
        if not intent.created_at:
            intent.created_at = str(now_ist())
        if not intent.correlation_id:
            import uuid
            intent.correlation_id = str(uuid.uuid4())

        params_json = json.dumps(intent.params)
        risk_json = (
            json.dumps(intent.risk_verdict) if intent.risk_verdict else None
        )

        writer = self._get_async_writer()
        queued = writer.submit(
            """INSERT OR REPLACE INTO intents
               (intent_id, action, params_json, risk_verdict_json,
                config_snapshot_hash, correlation_id, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                intent.intent_id,
                intent.action,
                params_json,
                risk_json,
                intent.config_snapshot_hash,
                intent.correlation_id,
                IntentStatus.PENDING,
                intent.created_at,
            ),
        )
        if not queued:
            # Async queue saturated — fall back to synchronous write to
            # guarantee persistence (DEBT-009 safety net)
            _log.warning("[WAL] Async queue full, falling back to sync append")
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    """INSERT OR REPLACE INTO intents
                       (intent_id, action, params_json, risk_verdict_json,
                        config_snapshot_hash, correlation_id, status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        intent.intent_id,
                        intent.action,
                        params_json,
                        risk_json,
                        intent.config_snapshot_hash,
                        intent.correlation_id,
                        IntentStatus.PENDING,
                        intent.created_at,
                    ),
                )
                conn.commit()

    def _fallback_execute(self, sql: str, params: tuple) -> None:
        """Synchronous fallback when async queue is saturated."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(sql, params)
            conn.commit()

    def commit(self, intent_id: str) -> None:
        """Mark intent as COMMITTED via AsyncDbWriter (non-blocking)."""
        now = str(now_ist())
        writer = self._get_async_writer()
        queued = writer.submit(
            "UPDATE intents SET status = ?, committed_at = ? WHERE intent_id = ?",
            (IntentStatus.COMMITTED, now, intent_id),
        )
        if not queued:
            _log.warning("[WAL] Async queue full, falling back to sync commit")
            self._fallback_execute(
                "UPDATE intents SET status = ?, committed_at = ? WHERE intent_id = ?",
                (IntentStatus.COMMITTED, now, intent_id),
            )

    def fail(self, intent_id: str, error: str = "") -> None:
        """Mark intent as FAILED via AsyncDbWriter (non-blocking)."""
        now = str(now_ist())
        writer = self._get_async_writer()
        queued = writer.submit(
            "UPDATE intents SET status = ?, failed_at = ?, error_message = ? WHERE intent_id = ?",
            (IntentStatus.FAILED, now, error, intent_id),
        )
        if not queued:
            _log.warning("[WAL] Async queue full, falling back to sync fail")
            self._fallback_execute(
                "UPDATE intents SET status = ?, failed_at = ?, error_message = ? WHERE intent_id = ?",
                (IntentStatus.FAILED, now, error, intent_id),
            )

    def settle(self, intent_id: str) -> None:
        """Mark intent as SETTLED via AsyncDbWriter (non-blocking)."""
        writer = self._get_async_writer()
        queued = writer.submit(
            "UPDATE intents SET status = ? WHERE intent_id = ? AND status = ?",
            (IntentStatus.SETTLED, intent_id, IntentStatus.COMMITTED),
        )
        if not queued:
            _log.warning("[WAL] Async queue full, falling back to sync settle")
            self._fallback_execute(
                "UPDATE intents SET status = ? WHERE intent_id = ? AND status = ?",
                (IntentStatus.SETTLED, intent_id, IntentStatus.COMMITTED),
            )

    def _sync_read(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """
        Read from the async writer's connection (which has the latest writes)
        when available, falling back to the primary connection.
        This ensures read-after-write consistency even with async writes
        (DEBT-009).
        """
        # If the async writer is alive, use execute_sync for consistency
        if self._async_writer is not None:
            try:
                return self._async_writer.execute_sync(sql, params)
            except (sqlite3.Error, OSError, ValueError) as exc:
                _log.debug("[WAL] Async read failed, falling back to primary: %s", exc)
        with self._lock:
            conn = self._get_conn()
            conn.row_factory = sqlite3.Row
            return conn.execute(sql, params).fetchall()

    def get_intent(self, intent_id: str) -> Intent | None:
        """Retrieve a specific intent by ID."""
        rows = self._sync_read(
            "SELECT * FROM intents WHERE intent_id = ?", (intent_id,)
        )
        if rows:
            return self._row_to_intent(rows[0])
        return None

    def get_pending(self) -> list[Intent]:
        """Get all PENDING intents (for crash recovery)."""
        rows = self._sync_read(
            "SELECT * FROM intents WHERE status = ? ORDER BY created_at",
            (IntentStatus.PENDING,),
        )
        return [self._row_to_intent(r) for r in rows]

    def get_unsettled(self) -> list[Intent]:
        """Get COMMITTED intents that haven't been SETTLED (for reconciliation)."""
        rows = self._sync_read(
            "SELECT * FROM intents WHERE status = ? ORDER BY created_at",
            (IntentStatus.COMMITTED,),
        )
        return [self._row_to_intent(r) for r in rows]

    def get_by_correlation(self, correlation_id: str) -> list[Intent]:
        rows = self._sync_read(
            "SELECT * FROM intents WHERE correlation_id = ? ORDER BY created_at",
            (correlation_id,),
        )
        return [self._row_to_intent(r) for r in rows]

    def count_by_status(self) -> dict[str, int]:
        rows = self._sync_read(
            "SELECT status, COUNT(*) as cnt FROM intents GROUP BY status"
        )
        return {r[0]: r[1] for r in rows}

    def cleanup(self, max_age_hours: float = 168) -> int:
        """Remove SETTLED intents older than max_age_hours."""
        from datetime import timedelta
        cutoff = str(now_ist() - timedelta(hours=max_age_hours))
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "DELETE FROM intents WHERE status = ? AND created_at < ?",
                (IntentStatus.SETTLED, cutoff),
            )
            conn.commit()
            deleted = conn.total_changes
        return deleted

    def _row_to_intent(self, row: sqlite3.Row) -> Intent:
        return Intent(
            intent_id=row["intent_id"],
            action=row["action"],
            params=json.loads(row["params_json"]) if row["params_json"] else {},
            risk_verdict=json.loads(row["risk_verdict_json"]) if row["risk_verdict_json"] else None,
            config_snapshot_hash=row["config_snapshot_hash"] or "",
            correlation_id=row["correlation_id"] or "",
            status=row["status"],
            created_at=row["created_at"] or "",
            committed_at=row["committed_at"],
            failed_at=row["failed_at"],
            error_message=row["error_message"] or "",
        )

    def flush(self) -> None:
        """Wait for all pending async writes to complete.

        Polls the async writer's queue until it is empty. This is useful
        for tests and for ensuring read-after-write consistency after
        bulk write operations.
        """
        if self._async_writer is not None:
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if self._async_writer.stats["queue_size"] == 0:
                    return
                time.sleep(0.05)
            _log.warning("[WAL] Flush timed out after 5s")

    def close(self) -> None:
        """Close the AsyncDbWriter and underlying SQLite connection."""
        with self._lock:
            if self._async_writer is not None:
                self._async_writer.stop(block=True, timeout=5.0)
                self._async_writer = None
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def health_check(self) -> dict:
        result = {
            "db_path": str(self._db_path),
            "exists": self._db_path.exists(),
            "size_bytes": self._db_path.stat().st_size if self._db_path.exists() else 0,
            "by_status": self.count_by_status(),
        }
        if self._async_writer is not None:
            result["async_writer"] = {
                "queue_size": self._async_writer.stats["queue_size"],
                "written": self._async_writer.stats["written"],
                "errors": self._async_writer.stats["errors"],
            }
        return result
