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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)

WAL_DB_PATH = "wal_journal.db"


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
    """Thread-safe write-ahead journal for broker intents."""

    def __init__(self, db_path: str = WAL_DB_PATH):
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()
        _log.info("WAL journal initialized at %s", self._db_path)

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
        return self._conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute("""
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
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_intents_status
                ON intents(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_intents_correlation
                ON intents(correlation_id)
            """)
            conn.commit()

    def append(self, intent: Intent) -> None:
        """Append a PENDING intent before executing the broker call."""
        if not intent.created_at:
            intent.created_at = str(now_ist())
        if not intent.correlation_id:
            import uuid
            intent.correlation_id = str(uuid.uuid4())

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
                    json.dumps(intent.params),
                    json.dumps(intent.risk_verdict) if intent.risk_verdict else None,
                    intent.config_snapshot_hash,
                    intent.correlation_id,
                    IntentStatus.PENDING,
                    intent.created_at,
                ),
            )
            conn.commit()

    def commit(self, intent_id: str) -> None:
        """Mark intent as COMPLETED (broker acknowledged)."""
        now = str(now_ist())
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE intents SET status = ?, committed_at = ? WHERE intent_id = ?",
                (IntentStatus.COMMITTED, now, intent_id),
            )
            conn.commit()

    def fail(self, intent_id: str, error: str = "") -> None:
        """Mark intent as FAILED."""
        now = str(now_ist())
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE intents SET status = ?, failed_at = ?, error_message = ? WHERE intent_id = ?",
                (IntentStatus.FAILED, now, error, intent_id),
            )
            conn.commit()

    def settle(self, intent_id: str) -> None:
        """Mark intent as SETTLED (fully reconciled with broker)."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE intents SET status = ? WHERE intent_id = ? AND status = ?",
                (IntentStatus.SETTLED, intent_id, IntentStatus.COMMITTED),
            )
            conn.commit()

    def get_intent(self, intent_id: str) -> Intent | None:
        """Retrieve a specific intent by ID."""
        with self._lock:
            conn = self._get_conn()
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
        if row:
            return self._row_to_intent(row)
        return None

    def get_pending(self) -> list[Intent]:
        """Get all PENDING intents (for crash recovery)."""
        with self._lock:
            conn = self._get_conn()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM intents WHERE status = ? ORDER BY created_at",
                (IntentStatus.PENDING,),
            ).fetchall()
        return [self._row_to_intent(r) for r in rows]

    def get_unsettled(self) -> list[Intent]:
        """Get COMMITTED intents that haven't been SETTLED (for reconciliation)."""
        with self._lock:
            conn = self._get_conn()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM intents WHERE status = ? ORDER BY created_at",
                (IntentStatus.COMMITTED,),
            ).fetchall()
        return [self._row_to_intent(r) for r in rows]

    def get_by_correlation(self, correlation_id: str) -> list[Intent]:
        with self._lock:
            conn = self._get_conn()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM intents WHERE correlation_id = ? ORDER BY created_at",
                (correlation_id,),
            ).fetchall()
        return [self._row_to_intent(r) for r in rows]

    def count_by_status(self) -> dict[str, int]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM intents GROUP BY status"
            ).fetchall()
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

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def health_check(self) -> dict:
        return {
            "db_path": str(self._db_path),
            "exists": self._db_path.exists(),
            "size_bytes": self._db_path.stat().st_size if self._db_path.exists() else 0,
            "by_status": self.count_by_status(),
        }
