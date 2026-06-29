from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "AuditEngine",
    "AuditRecord",
]

@dataclass(frozen=True)
class AuditRecord:
    event: str
    payload: dict[str, Any]


class AuditEngine:
    """Structured JSONL audit trail for operator actions and runtime decisions.

    Thread-safe: concurrent calls to record() from multiple threads are
    serialised by an internal lock so JSONL lines are never interleaved.
    """

    # Accepted severity levels.  Unknown values fall back to "INFO".
    SEVERITIES: frozenset[str] = frozenset({"INFO", "WARN", "CRITICAL", "AUDIT"})

    def __init__(
        self,
        path: str | Path,
        *,
        enabled: bool = True,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = Path(path)
        self._enabled = bool(enabled)
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()

    def record(
        self,
        event: str,
        trace_id: str | None = None,
        severity: str = "INFO",
        **payload: Any,
    ) -> AuditRecord | None:
        """Append one JSONL event to the audit log.

        Args:
            event:    Short event identifier (e.g. "state_saved", "halt_tripped").
            trace_id: Optional token that links this event to a specific trade
                      lifecycle.  Carry the same token through TradeJournal,
                      decision_log, and Telegram messages for the same trade.
            severity: One of INFO | WARN | CRITICAL | AUDIT.  Invalid values
                      silently default to INFO.
            **payload: Arbitrary key-value fields written into the JSONL row.
        """
        if not self._enabled:
            return None
        _sev = severity if severity in self.SEVERITIES else "INFO"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        row: dict[str, Any] = {
            "ts": self._now_fn().isoformat(),
            "event": event,
            "severity": _sev,
        }
        if trace_id is not None:
            row["trace_id"] = trace_id
        row.update(payload)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=True, default=str) + "\n")
        return AuditRecord(event=event, payload=row)
