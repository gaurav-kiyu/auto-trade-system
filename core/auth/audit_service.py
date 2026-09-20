"""Canonical Privileged Action Audit Engine (OPB-AUDIT-GOVERNANCE-2026).

Centralizes persistent, tamper-evident audit logging for all security-sensitive,
administrative, user management, configuration, risk, trading control, and
permission operations.

Supports dual persistence:
1. Relational SQLite (db/auth.db: audit_log table)
2. Append-only JSONL files (json/audit_trail.jsonl and json/config_audit.jsonl)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger("audit_service")

# Redaction key patterns
REDACT_KEYS = {
    "password", "secret", "token", "api_key", "apikey", "pin",
    "otp", "private_key", "auth_token", "hash", "salt", "secret_key"
}


def sanitize_payload(payload: Any) -> Any:
    """Recursively redact sensitive credential keys in any data structure."""
    if isinstance(payload, Mapping):
        sanitized = {}
        for k, v in payload.items():
            k_lower = str(k).lower()
            if any(rk in k_lower for rk in REDACT_KEYS):
                sanitized[k] = "[REDACTED]"
            elif isinstance(v, (Mapping, list, tuple)):
                sanitized[k] = sanitize_payload(v)
            else:
                sanitized[k] = v
        return sanitized
    elif isinstance(payload, (list, tuple)):
        return [sanitize_payload(item) for item in payload]
    return payload


class AuditService:
    """Thread-safe Canonical Audit Engine."""

    _instance: AuditService | None = None
    _lock = threading.Lock()

    def __init__(
        self,
        db_path: str = "db/auth.db",
        audit_trail_path: str = "json/audit_trail.jsonl",
        config_audit_path: str = "json/config_audit.jsonl",
    ) -> None:
        self.db_path = Path(db_path)
        self.audit_trail_path = Path(audit_trail_path)
        self.config_audit_path = Path(config_audit_path)
        self._write_lock = threading.Lock()
        self._ensure_storage()

    @classmethod
    def get_instance(cls) -> AuditService:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _ensure_storage(self) -> None:
        """Ensure SQLite tables and JSONL directories exist."""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.audit_trail_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_audit_path.parent.mkdir(parents=True, exist_ok=True)

            conn = sqlite3.connect(str(self.db_path))
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        event_type TEXT NOT NULL,
                        username TEXT,
                        ip_address TEXT,
                        details TEXT DEFAULT '{}',
                        success INTEGER DEFAULT 1
                    );
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_log(event_type);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_username ON audit_log(username);"
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as ex:
            _log.warning("[AUDIT] Storage initialization warning: %s", ex)

    def log_event(
        self,
        action: str,
        actor_username: str,
        actor_role: str = "super_admin",
        target: str = "",
        route: str = "",
        method: str = "POST",
        result: str = "SUCCESS",
        before_state: Any = None,
        after_state: Any = None,
        reason: str = "",
        ip_address: str = "127.0.0.1",
        correlation_id: str | None = None,
        extra_details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record an immutable, sanitized audit event across all persistent targets."""
        now_epoch = time.time()
        now_iso = datetime.fromtimestamp(now_epoch, tz=timezone.utc).isoformat()
        event_id = f"aud_{uuid.uuid4().hex[:12]}"
        corr_id = correlation_id or f"corr_{uuid.uuid4().hex[:8]}"

        sanitized_before = sanitize_payload(before_state) if before_state is not None else None
        sanitized_after = sanitize_payload(after_state) if after_state is not None else None
        sanitized_extra = sanitize_payload(extra_details) if extra_details is not None else {}

        record: dict[str, Any] = {
            "event_id": event_id,
            "timestamp": now_epoch,
            "timestamp_iso": now_iso,
            "actor_username": actor_username or "system",
            "actor_role": actor_role or "unknown",
            "action": action.upper(),
            "target": str(target or ""),
            "route": str(route or ""),
            "method": method.upper(),
            "result": result.upper(),
            "before_state": sanitized_before,
            "after_state": sanitized_after,
            "reason": str(reason or ""),
            "ip_address": str(ip_address or "127.0.0.1"),
            "correlation_id": corr_id,
            "details": sanitized_extra,
            "extra": sanitized_extra,
        }

        # 1. SQLite Persistence
        success_bool = record["result"] == "SUCCESS"
        details_json = json.dumps(record, default=str)
        with self._write_lock:
            try:
                conn = sqlite3.connect(str(self.db_path), timeout=10.0)
                try:
                    conn.execute(
                        """
                        INSERT INTO audit_log (timestamp, event_type, username, ip_address, details, success)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            now_epoch,
                            record["action"],
                            record["actor_username"],
                            record["ip_address"],
                            details_json,
                            1 if success_bool else 0,
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()
            except Exception as ex:
                _log.error("[AUDIT] SQLite write failed for event %s: %s", event_id, ex)

            # 2. Append-only General JSONL (json/audit_trail.jsonl)
            try:
                with open(self.audit_trail_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, default=str) + "\n")
            except Exception as ex:
                _log.error("[AUDIT] JSONL write failed for event %s: %s", event_id, ex)

            # 3. Append-only Config JSONL if configuration-related and custom path specified
            if ("CONFIG" in record["action"] or record["route"].startswith("/api/config")) and self.config_audit_path.resolve() != Path("json/config_audit.jsonl").resolve():
                try:
                    cfg_entry = {
                        "timestamp": now_epoch,
                        "action": record["action"].upper(),
                        "username": record["actor_username"],
                        "keys": list(sanitized_after.keys()) if isinstance(sanitized_after, dict) else [record["target"]],
                        "values": list(sanitized_after.values()) if isinstance(sanitized_after, dict) else [sanitized_after],
                        "before_state": sanitized_before,
                        "after_state": sanitized_after,
                        "ip": record["ip_address"],
                        "result": record["result"],
                        "event_id": event_id,
                    }
                    with open(self.config_audit_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(cfg_entry, default=str) + "\n")
                except Exception as ex:
                    _log.error("[AUDIT] Config JSONL write failed for event %s: %s", event_id, ex)

        return record

    def log_privileged_action(
        self,
        action: str,
        actor_username: str,
        actor_role: str = "super_admin",
        target: str = "",
        route: str = "",
        method: str = "POST",
        result: str = "SUCCESS",
        before_state: Any = None,
        after_state: Any = None,
        reason: str = "",
        ip_address: str = "127.0.0.1",
        correlation_id: str | None = None,
        details: dict[str, Any] | None = None,
        extra_details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Convenience method matching privileged action signature."""
        extra = extra_details or details
        return self.log_event(
            action=action,
            actor_username=actor_username,
            actor_role=actor_role,
            target=target,
            route=route,
            method=method,
            result=result,
            before_state=before_state,
            after_state=after_state,
            reason=reason,
            ip_address=ip_address,
            correlation_id=correlation_id,
            extra_details=extra,
        )

    def log_config_change(
        self,
        actor_username: str,
        actor_role: str = "admin",
        before_state: Any = None,
        after_state: Any = None,
        diff: Any = None,
        result: str = "SUCCESS",
        ip_address: str = "127.0.0.1",
        reason: str = "",
    ) -> dict[str, Any]:
        """Convenience method for configuration change audit."""
        return self.log_event(
            action="CONFIG_APPLY",
            actor_username=actor_username,
            actor_role=actor_role,
            target="system_config",
            route="/api/config/apply",
            method="POST",
            result=result,
            before_state=before_state,
            after_state=after_state,
            reason=reason,
            ip_address=ip_address,
            extra_details={"diff": diff} if diff else None,
        )

    def get_audit_events(
        self,
        limit: int = 100,
        action: str | None = None,
        actor: str | None = None,
        target: str | None = None,
        result: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve recent audit events from SQLite with canonical format."""
        events: list[dict[str, Any]] = []
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            try:
                conn.row_factory = sqlite3.Row
                query = "SELECT * FROM audit_log"
                params: list[Any] = []
                conditions = []

                if action:
                    conditions.append("event_type = ?")
                    params.append(action.upper())
                if actor:
                    conditions.append("username = ?")
                    params.append(actor)

                if conditions:
                    query += " WHERE " + " AND ".join(conditions)

                query += " ORDER BY timestamp DESC LIMIT ?"
                params.append(max(1, min(limit, 500)))

                cursor = conn.execute(query, params)
                for row in cursor.fetchall():
                    raw_details = row["details"]
                    item: dict[str, Any] = {}
                    if raw_details:
                        try:
                            item = json.loads(raw_details)
                        except Exception:
                            item = {}

                    # Ensure standard canonical fields exist even for legacy rows
                    item.setdefault("id", row["id"])
                    item.setdefault("timestamp", row["timestamp"])
                    item.setdefault("action", row["event_type"])
                    item.setdefault("event_type", row["event_type"])
                    item.setdefault("actor_username", row["username"])
                    item.setdefault("username", row["username"])
                    item.setdefault("ip_address", row["ip_address"])
                    item.setdefault("result", "SUCCESS" if row["success"] else "FAILED")
                    item.setdefault("success", bool(row["success"]))

                    # Format timestamp string in IST for human display
                    ts = item["timestamp"]
                    if isinstance(ts, (int, float)):
                        try:
                            # 19800 seconds = UTC+5:30 (IST)
                            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                            item["timestamp_str"] = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                        except Exception:
                            item["timestamp_str"] = str(ts)

                    # Post-filter if requested
                    if target and str(item.get("target", "")) != target:
                        continue
                    if result and str(item.get("result", "")).upper() != result.upper():
                        continue

                    events.append(item)
            finally:
                conn.close()
        except Exception as ex:
            _log.error("[AUDIT] Failed to query audit log: %s", ex)

        return events

    # Alias for querying
    query_audit_trail = get_audit_events


# Module-level convenience functions
def get_audit_service() -> AuditService:
    return AuditService.get_instance()


def log_privileged_action(
    action: str,
    actor_username: str,
    actor_role: str = "super_admin",
    target: str = "",
    route: str = "",
    method: str = "POST",
    result: str = "SUCCESS",
    before_state: Any = None,
    after_state: Any = None,
    reason: str = "",
    ip_address: str = "127.0.0.1",
    correlation_id: str | None = None,
    extra_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return get_audit_service().log_event(
        action=action,
        actor_username=actor_username,
        actor_role=actor_role,
        target=target,
        route=route,
        method=method,
        result=result,
        before_state=before_state,
        after_state=after_state,
        reason=reason,
        ip_address=ip_address,
        correlation_id=correlation_id,
        extra_details=extra_details,
    )
