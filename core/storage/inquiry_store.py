"""Durable SQLite Inquiry Store for OPB Contact & Support Inquiries.

Provides persistent SQLite storage, migration from legacy JSONL,
status tracking, audit logging, and concurrency control.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from core.db_utils import get_connection

_log = logging.getLogger("INQUIRY_STORE")


def resolve_inquiry_db_path() -> str:
    """Resolve the authoritative path for the inquiries database."""
    env_override = os.environ.get("OPBUYING_INQUIRIES_DB")
    if env_override:
        return env_override
    if os.path.isdir("/data/db") and os.access("/data/db", os.W_OK):
        return "/data/db/inquiries.db"
    if os.path.isdir("data"):
        return "data/inquiries.db"
    return "db/inquiries.db"


class InquiryStore:
    """Thread-safe persistent storage and lifecycle manager for contact inquiries."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or resolve_inquiry_db_path()
        self._lock = threading.RLock()
        self._ensure_tables()

    def _get_conn(self) -> sqlite3.Connection:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = get_connection(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        with self._lock:
            conn = self._get_conn()
            try:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS inquiries (
                            id TEXT PRIMARY KEY,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            name TEXT NOT NULL,
                            email TEXT NOT NULL,
                            category TEXT NOT NULL,
                            subject TEXT NOT NULL,
                            message TEXT NOT NULL,
                            client_ip TEXT NOT NULL,
                            status TEXT NOT NULL DEFAULT 'NEW',
                            notification_status TEXT NOT NULL DEFAULT 'PENDING',
                            notification_error TEXT,
                            admin_notes TEXT,
                            metadata TEXT
                        )
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_inquiries_created_at
                        ON inquiries(created_at DESC)
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_inquiries_status
                        ON inquiries(status)
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_inquiries_email
                        ON inquiries(email)
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS inquiry_audit_log (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            inquiry_id TEXT NOT NULL,
                            timestamp TEXT NOT NULL,
                            actor_username TEXT NOT NULL,
                            action TEXT NOT NULL,
                            previous_status TEXT,
                            new_status TEXT,
                            notes TEXT,
                            FOREIGN KEY (inquiry_id) REFERENCES inquiries(id)
                        )
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_inquiry_audit_id
                        ON inquiry_audit_log(inquiry_id)
                    """)
            finally:
                conn.close()

    def migrate_legacy_jsonl(self, jsonl_path: str | None = None) -> int:
        """Idempotently import legacy inquiries from JSONL into SQLite."""
        target_path: Path | None = None
        if jsonl_path:
            p = Path(jsonl_path)
            if p.exists():
                target_path = p
        else:
            candidates = [
                Path("data/contact_inquiries.jsonl"),
                Path("/app/data/contact_inquiries.jsonl"),
                Path("contact_inquiries.jsonl"),
            ]
            for c in candidates:
                if c.exists():
                    target_path = c
                    break

        if not target_path or not target_path.exists():
            return 0

        imported_count = 0
        with self._lock:
            conn = self._get_conn()
            try:
                with open(target_path, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            inq_id = str(record.get("id") or f"inq_{int(time.time()*1000)}")
                            created_at = str(record.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                            name = str(record.get("name") or "Unknown")
                            email = str(record.get("email") or "")
                            category = str(record.get("category") or "General Inquiry")
                            subject = str(record.get("subject") or "Inquiry")
                            message = str(record.get("message") or "")
                            client_ip = str(record.get("client_ip") or "127.0.0.1")
                            status = str(record.get("status") or "NEW").upper()
                            if status == "PENDING_REVIEW":
                                status = "NEW"

                            with conn:
                                cur = conn.execute("""
                                    INSERT OR IGNORE INTO inquiries (
                                        id, created_at, updated_at, name, email,
                                        category, subject, message, client_ip,
                                        status, notification_status, admin_notes
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'MIGRATED', 'Imported from legacy JSONL')
                                """, (
                                    inq_id, created_at, created_at, name, email,
                                    category, subject, message, client_ip, status
                                ))
                                if cur.rowcount > 0:
                                    imported_count += 1
                        except Exception as parse_exc:
                            _log.warning("Skipping malformed legacy inquiry line: %s", parse_exc)
            finally:
                conn.close()

        if imported_count > 0:
            _log.info("Successfully migrated %d legacy inquiries from %s", imported_count, target_path)
        return imported_count

    def save_inquiry(
        self,
        *,
        name: str,
        email: str,
        subject: str,
        message: str,
        category: str = "General Inquiry",
        client_ip: str = "unknown",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persist a new inquiry record and return its unique identifier."""
        now = time.time()
        inq_id = f"inq_{int(now * 1000)}"
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        meta_json = json.dumps(metadata or {}, default=str)

        with self._lock:
            conn = self._get_conn()
            try:
                with conn:
                    conn.execute("""
                        INSERT INTO inquiries (
                            id, created_at, updated_at, name, email,
                            category, subject, message, client_ip,
                            status, notification_status, metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'NEW', 'PENDING', ?)
                    """, (
                        inq_id, now_iso, now_iso, name, email,
                        category, subject, message, client_ip, meta_json
                    ))
                    conn.execute("""
                        INSERT INTO inquiry_audit_log (
                            inquiry_id, timestamp, actor_username, action,
                            previous_status, new_status, notes
                        ) VALUES (?, ?, 'system', 'SUBMISSION', NULL, 'NEW', 'Initial submission')
                    """, (inq_id, now_iso))
            finally:
                conn.close()

        _log.info("Durable inquiry %s persisted for %s <%s>", inq_id, name, email)
        return inq_id

    def update_notification_status(
        self,
        inquiry_id: str,
        notification_status: str,
        error: str | None = None,
    ) -> None:
        """Update notification delivery status (e.g., DISPATCHED, FAILED)."""
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            conn = self._get_conn()
            try:
                with conn:
                    conn.execute("""
                        UPDATE inquiries
                        SET notification_status = ?,
                            notification_error = ?,
                            updated_at = ?
                        WHERE id = ?
                    """, (notification_status, error, now_iso, inquiry_id))
            finally:
                conn.close()

    def get_inquiry(self, inquiry_id: str) -> dict[str, Any] | None:
        """Retrieve a single inquiry by ID."""
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.execute("SELECT * FROM inquiries WHERE id = ?", (inquiry_id,))
                row = cur.fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def list_inquiries(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List inquiries with filtering, search, and pagination."""
        clauses = []
        params: list[Any] = []

        if status and status.upper() != "ALL":
            clauses.append("status = ?")
            params.append(status.upper())

        if category and category.upper() != "ALL":
            clauses.append("category = ?")
            params.append(category)

        if search:
            search_pattern = f"%{search}%"
            clauses.append("(id LIKE ? OR name LIKE ? OR email LIKE ? OR subject LIKE ? OR message LIKE ?)")
            params.extend([search_pattern, search_pattern, search_pattern, search_pattern, search_pattern])

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with self._lock:
            conn = self._get_conn()
            try:
                count_sql = f"SELECT COUNT(*) FROM inquiries {where_sql}"  # nosec B608
                cur = conn.execute(count_sql, tuple(params))
                total_count = cur.fetchone()[0]

                data_sql = f"""
                    SELECT id, created_at, updated_at, name, email, category,
                           subject, status, notification_status, client_ip
                    FROM inquiries
                    {where_sql}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """  # nosec B608
                query_params = list(params) + [limit, offset]
                cur = conn.execute(data_sql, tuple(query_params))
                items = [dict(r) for r in cur.fetchall()]
                return items, total_count
            finally:
                conn.close()

    def update_inquiry_status(
        self,
        inquiry_id: str,
        new_status: str,
        actor_username: str,
        notes: str | None = None,
    ) -> bool:
        """Update inquiry lifecycle status and write an immutable audit log entry."""
        valid_statuses = {"NEW", "IN_PROGRESS", "RESOLVED", "CLOSED"}
        norm_status = new_status.upper()
        if norm_status not in valid_statuses:
            raise ValueError(f"Invalid inquiry status '{new_status}'. Must be one of {valid_statuses}")

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.execute("SELECT status FROM inquiries WHERE id = ?", (inquiry_id,))
                row = cur.fetchone()
                if not row:
                    return False
                prev_status = row["status"]

                with conn:
                    conn.execute("""
                        UPDATE inquiries
                        SET status = ?,
                            admin_notes = COALESCE(?, admin_notes),
                            updated_at = ?
                        WHERE id = ?
                    """, (norm_status, notes, now_iso, inquiry_id))

                    conn.execute("""
                        INSERT INTO inquiry_audit_log (
                            inquiry_id, timestamp, actor_username, action,
                            previous_status, new_status, notes
                        ) VALUES (?, ?, ?, 'STATUS_CHANGE', ?, ?, ?)
                    """, (inquiry_id, now_iso, actor_username, prev_status, norm_status, notes or ""))
                return True
            finally:
                conn.close()

    def get_audit_log(self, inquiry_id: str) -> list[dict[str, Any]]:
        """Get the full audit history for an inquiry."""
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.execute("""
                    SELECT * FROM inquiry_audit_log
                    WHERE inquiry_id = ?
                    ORDER BY id ASC
                """, (inquiry_id,))
                return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

    def get_stats(self) -> dict[str, int]:
        """Get summary statistics for dashboard display."""
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'NEW' THEN 1 ELSE 0 END) as count_new,
                        SUM(CASE WHEN status = 'IN_PROGRESS' THEN 1 ELSE 0 END) as count_in_progress,
                        SUM(CASE WHEN status = 'RESOLVED' THEN 1 ELSE 0 END) as count_resolved,
                        SUM(CASE WHEN notification_status = 'FAILED' THEN 1 ELSE 0 END) as count_notif_failed
                    FROM inquiries
                """)
                row = cur.fetchone()
                return {
                    "total": row["total"] or 0,
                    "new": row["count_new"] or 0,
                    "in_progress": row["count_in_progress"] or 0,
                    "resolved": row["count_resolved"] or 0,
                    "notification_failed": row["count_notif_failed"] or 0,
                }
            finally:
                conn.close()


_global_inquiry_store: InquiryStore | None = None
_store_lock = threading.Lock()


def get_inquiry_store(db_path: str | None = None) -> InquiryStore:
    """Singleton accessor for the global InquiryStore."""
    global _global_inquiry_store
    with _store_lock:
        if _global_inquiry_store is None or (db_path and _global_inquiry_store.db_path != db_path):
            _global_inquiry_store = InquiryStore(db_path)
            # Run legacy migration on initialization
            _global_inquiry_store.migrate_legacy_jsonl()
        return _global_inquiry_store
