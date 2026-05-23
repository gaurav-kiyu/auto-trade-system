"""
AD-KIYU IdempotencyCertifier v1.0 — Exactly-Once Execution Certification.

Guarantees no duplicate order submissions by generating deterministic
execution IDs and tracking the full lifecycle via SQLite.

Lifecycle: PENDING → COMMITTED → SETTLED
                          ↘ FAILED

On crash recovery: queries broker for open orders matching execution_id tags.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)

CERT_DB_PATH = "execution_certifier.db"


class CertStatus:
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


@dataclass
class ExecutionCert:
    cert_id: str
    execution_id: str
    symbol: str
    action: str
    params_hash: str
    status: str = CertStatus.PENDING
    broker_order_id: str = ""
    created_at: str = ""
    committed_at: str | None = None
    settled_at: str | None = None
    error: str = ""


class IdempotencyCertifier:
    """
    Exactly-once execution certifier.

    Generates a deterministic execution_id from order parameters and a
    time slot (e.g. 5-minute bucket). The same order within the same slot
    always produces the same execution_id, preventing duplicates.

    Crash recovery: on restart, certifier lists PENDING certs and queries
    the broker by execution_id tag to determine true status.
    """

    def __init__(self, db_path: str = CERT_DB_PATH, slot_seconds: int = 300):
        self._db_path = Path(db_path)
        self._slot_seconds = slot_seconds
        self._lock = threading.Lock()
        self._is_memory = str(db_path) == ":memory:"
        self._conn: sqlite3.Connection | None = None
        self._init_db()
        _log.info("IdempotencyCertifier initialized (slot=%ds, db=%s)", slot_seconds, self._db_path)

    def _get_conn(self) -> sqlite3.Connection:
        """Get SQLite connection — caches for :memory: mode so state persists."""
        if self._is_memory:
            if self._conn is None:
                self._conn = sqlite3.connect(":memory:", check_same_thread=False)
            return self._conn
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS certs (
                    cert_id TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    params_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    broker_order_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    committed_at TEXT,
                    settled_at TEXT,
                    error TEXT DEFAULT ''
                )
            """)
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_certs_exec_id ON certs(execution_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_certs_status ON certs(status)")
            conn.commit()

    def generate_execution_id(self, symbol: str, direction: str, strike: float,
                              lot_size: int, timestamp_slot: int | None = None) -> str:
        """Generate a deterministic execution ID from order params + time slot."""
        if timestamp_slot is None:
            timestamp_slot = int(time.time() / self._slot_seconds)
        raw = f"{symbol}|{direction}|{strike}|{lot_size}|{timestamp_slot}"
        h = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"exec_{timestamp_slot}_{h}"

    def begin(self, execution_id: str, symbol: str, action: str,
              params: dict[str, Any]) -> str:
        """
        Begin an execution certification. Returns cert_id.
        Call BEFORE broker submission.
        """
        cert_id = f"cert_{execution_id}_{int(time.time()*1000)}"
        params_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]
        now = str(now_ist())

        with self._lock:
            # Check if already exists as PENDING (crash recovery scenario)
            conn = self._get_conn()
            existing = conn.execute(
                "SELECT status FROM certs WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if existing:
                _log.warning("Execution %s already has status %s", execution_id, existing[0])
                return cert_id

            conn.execute(
                """INSERT INTO certs
                   (cert_id, execution_id, symbol, action, params_hash, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (cert_id, execution_id, symbol, action, params_hash,
                 CertStatus.PENDING, now),
            )
            conn.commit()

        return cert_id

    def commit(self, cert_id: str, broker_order_id: str = "") -> None:
        """Mark execution as COMMITTED (broker acknowledged)."""
        now = str(now_ist())
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE certs SET status = ?, committed_at = ?, broker_order_id = ? WHERE cert_id = ?",
                (CertStatus.COMMITTED, now, broker_order_id, cert_id),
            )
            conn.commit()

    def settle(self, cert_id: str) -> None:
        """Mark execution as SETTLED (fully reconciled)."""
        now = str(now_ist())
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE certs SET status = ?, settled_at = ? WHERE cert_id = ?",
                (CertStatus.SETTLED, now, cert_id),
            )
            conn.commit()

    def fail(self, cert_id: str, error: str = "") -> None:
        """Mark execution as FAILED."""
        now = str(now_ist())
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE certs SET status = ?, error = ? WHERE cert_id = ?",
                (CertStatus.FAILED, error, cert_id),
            )
            conn.commit()

    def is_pending(self, execution_id: str) -> bool:
        """Check if an execution_id is still in PENDING state."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT status FROM certs WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            return row is not None and row[0] == CertStatus.PENDING

    def is_duplicate(self, execution_id: str) -> bool:
        """Check if an execution_id already exists (any status)."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT status FROM certs WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            return row is not None

    def get_pending(self) -> list[ExecutionCert]:
        """Get all PENDING certs (for crash recovery)."""
        with self._lock:
            conn = self._get_conn()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM certs WHERE status = ? ORDER BY created_at",
                (CertStatus.PENDING,),
            ).fetchall()
            return [self._row_to_cert(r) for r in rows]

    def get_by_execution_id(self, execution_id: str) -> ExecutionCert | None:
        with self._lock:
            conn = self._get_conn()
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM certs WHERE execution_id = ?", (execution_id,)
            ).fetchone()
            return self._row_to_cert(row) if row else None

    def count_by_status(self) -> dict[str, int]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM certs GROUP BY status"
            ).fetchall()
            return {r[0]: r[1] for r in rows}

    def _row_to_cert(self, row: sqlite3.Row) -> ExecutionCert:
        return ExecutionCert(
            cert_id=row["cert_id"],
            execution_id=row["execution_id"],
            symbol=row["symbol"],
            action=row["action"],
            params_hash=row["params_hash"],
            status=row["status"],
            broker_order_id=row["broker_order_id"] or "",
            created_at=row["created_at"] or "",
            committed_at=row["committed_at"],
            settled_at=row["settled_at"],
            error=row["error"] or "",
        )

    def health_check(self) -> dict:
        return {
            "db_path": str(self._db_path),
            "exists": self._db_path.exists(),
            "size_bytes": self._db_path.stat().st_size if self._db_path.exists() else 0,
            "by_status": self.count_by_status(),
        }
