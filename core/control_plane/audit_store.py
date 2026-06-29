"""
Audit Store for the Admin Control Plane — extracted from server.py.

Provides ControlAction dataclass and AuditStore for thread-safe
in-memory + JSONL-persisted audit trail of control actions.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── In-memory audit ring buffer (last 500 events) - legacy compat ──────────
_AUDIT_EVENTS: deque[dict[str, Any]] = deque(maxlen=500)
_AUDIT_LOCK = threading.RLock()


@dataclass
class ControlAction:
    """Record of a single control action with full audit trail."""
    action_id: str
    action: str
    target: str
    value: str
    identity: str
    timestamp: datetime
    success: bool
    previous_state: dict[str, Any] | None = None
    new_state: dict[str, Any] | None = None
    reason: str = ""
    reversible: bool = True


class AuditStore:
    """Thread-safe in-memory + JSONL audit store for control actions."""

    def __init__(self, max_entries: int = 1000, persist_path: str = ""):
        self._lock = threading.RLock()
        self._entries: list[ControlAction] = []
        self._max_entries = max_entries
        self._persist_path = persist_path

    def append(self, action: ControlAction) -> None:
        with self._lock:
            self._entries.append(action)
            if len(self._entries) > self._max_entries:
                self._entries.pop(0)
        if self._persist_path:
            try:
                Path(self._persist_path).parent.mkdir(parents=True, exist_ok=True)
                with open(self._persist_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "action_id": action.action_id,
                        "action": action.action,
                        "target": action.target,
                        "value": action.value,
                        "identity": action.identity,
                        "timestamp": str(action.timestamp),
                        "success": action.success,
                        "reason": action.reason,
                    }, default=str) + "\n")
            except (OSError, ValueError, TypeError) as e:
                _log.warning("[CTRL] Failed to persist audit entry: %s", e)

        # Also write to legacy _AUDIT_EVENTS ring buffer
        legacy_ev = {
            "event_id": action.action_id,
            "timestamp": str(action.timestamp),
            "event_type": action.action,
            "resource": action.target,
            "action": action.action,
            "outcome": "success" if action.success else "failure",
            "details": {"value": action.value, "reason": action.reason},
            "user_id": action.identity,
            "ip_address": "local",
        }
        with _AUDIT_LOCK:
            _AUDIT_EVENTS.append(legacy_ev)

    def get_recent(self, limit: int = 100) -> list[ControlAction]:
        with self._lock:
            return list(self._entries[-limit:])

    def count(self) -> int:
        with self._lock:
            return len(self._entries)


def get_legacy_audit_events(limit: int = 100) -> list[dict[str, Any]]:
    """Get events from the legacy in-memory ring buffer."""
    with _AUDIT_LOCK:
        return list(_AUDIT_EVENTS)[-limit:]


__all__ = [
    "AuditStore",
    "ControlAction",
    "get_legacy_audit_events",
]
