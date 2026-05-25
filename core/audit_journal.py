"""
Audit Event Journal - Immutable Event Logging for Post-Mortems

Logs every important event:
- Signal generation
- Risk decisions
- Order submission
- Broker acknowledgment
- Fill/complete
- Cancel requests
- Reconciliation results
- System mode changes
- Risk breaches

Format: JSON Lines for easy parsing and grep
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist

log = logging.getLogger("audit_journal")


class AuditEventType(Enum):
    """Categories of auditable events."""
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    RISK_DECISION = "RISK_DECISION"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_ACKNOWLEDGED = "ORDER_ACKNOWLEDGED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_RECONCILED = "ORDER_RECONCILED"
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_CLOSED = "POSITION_CLOSED"
    POSITION_RECONCILED = "POSITION_RECONCILED"
    SYSTEM_MODE_CHANGE = "SYSTEM_MODE_CHANGE"
    HARD_HALT = "HARD_HALT"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    BROKER_DISCONNECT = "BROKER_DISCONNECT"
    BROKER_RECONNECT = "BROKER_RECONNECT"
    RISK_BREACH = "RISK_BREACH"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
    STALE_QUOTE = "STALE_QUOTE"
    INVALID_PRICE = "INVALID_PRICE"
    DB_WRITE_FAIL = "DB_WRITE_FAIL"
    CONFIG_CHANGE = "CONFIG_CHANGE"


class AuditSeverity(Enum):
    """Event severity levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class AuditEvent:
    """Immutable audit event record."""
    event_id: str
    timestamp: str
    event_type: str
    severity: str
    message: str
    correlation_id: str = ""
    intent_id: str = ""
    symbol: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    stack_trace: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class AuditJournal:
    """
    Thread-safe audit journal that writes events to a JSONL file.
    Events are append-only - no updates or deletes.
    """

    def __init__(
        self,
        log_dir: str = "logs",
        filename_prefix: str = "audit",
        max_file_size_mb: int = 50,
        retain_days: int = 30
    ):
        self._lock = threading.RLock()
        self._log_dir = Path(log_dir)
        self._max_file_size = max_file_size_mb * 1024 * 1024
        self._retain_days = retain_days
        self._current_file: Path | None = None
        self._current_file_size: int = 0
        self._sequence: int = 0

        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._rotate_file()

    def _get_event_id(self) -> str:
        """Generate unique event ID."""
        import uuid
        return f"{now_ist().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    def _get_timestamp(self) -> str:
        """Get ISO timestamp."""
        return now_ist().isoformat()

    def _get_current_file(self) -> Path:
        """Get current log file, rotating if needed."""
        today = now_ist().strftime("%Y%m%d")

        if self._current_file is None or self._current_file.stem != f"audit_{today}":
            self._rotate_file()

        # Check size
        if self._current_file_size >= self._max_file_size:
            self._rotate_file()

        return self._current_file

    def _rotate_file(self) -> None:
        """Rotate to a new file based on date."""
        today = now_ist().strftime("%Y%m%d")
        self._current_file = self._log_dir / f"audit_{today}.jsonl"

        # Check if file exists and get size
        if self._current_file.exists():
            self._current_file_size = self._current_file.stat().st_size
        else:
            self._current_file_size = 0

        self._sequence = 0
        log.info(f"Audit journal rotating to: {self._current_file}")

    def log_event(
        self,
        event_type: AuditEventType,
        severity: AuditSeverity,
        message: str,
        correlation_id: str = "",
        intent_id: str = "",
        symbol: str = "",
        details: dict[str, Any] | None = None,
        stack_trace: str = ""
    ) -> str:
        """
        Log an audit event.
        Returns the event_id for reference.
        """
        with self._lock:
            event = AuditEvent(
                event_id=self._get_event_id(),
                timestamp=self._get_timestamp(),
                event_type=event_type.value,
                severity=severity.value,
                message=message,
                correlation_id=correlation_id,
                intent_id=intent_id,
                symbol=symbol,
                details=details or {},
                stack_trace=stack_trace
            )

            try:
                file_path = self._get_current_file()
                with open(file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event.to_dict()) + "\n")
                    self._current_file_size += len(json.dumps(event.to_dict())) + 1

                self._sequence += 1

                # Log critical events to main logger
                if severity == AuditSeverity.CRITICAL:
                    log.critical(f"[AUDIT] {event_type.value}: {message}")
                elif severity == AuditSeverity.ERROR:
                    log.error(f"[AUDIT] {event_type.value}: {message}")
                elif severity == AuditSeverity.WARNING:
                    log.warning(f"[AUDIT] {event_type.value}: {message}")

                return event.event_id

            except Exception as e:
                log.error(f"Failed to write audit event: {e}")
                return event.event_id

    def log_signal(self, signal_data: dict, correlation_id: str = "") -> str:
        """Log signal generation."""
        return self.log_event(
            event_type=AuditEventType.SIGNAL_GENERATED,
            severity=AuditSeverity.INFO,
            message=f"Signal: {signal_data.get('direction')} {signal_data.get('symbol')} strength={signal_data.get('strength')}",
            correlation_id=correlation_id,
            symbol=signal_data.get("symbol", ""),
            details=signal_data
        )

    def log_risk_decision(
        self,
        decision: str,
        allowed: bool,
        reason: str,
        intent_id: str = "",
        symbol: str = ""
    ) -> str:
        """Log risk decision."""
        return self.log_event(
            event_type=AuditEventType.RISK_DECISION,
            severity=AuditSeverity.WARNING if not allowed else AuditSeverity.INFO,
            message=f"Risk decision: {'ALLOWED' if allowed else 'DENIED'} - {reason}",
            intent_id=intent_id,
            symbol=symbol,
            details={"decision": decision, "allowed": allowed, "reason": reason}
        )

    def log_order_submitted(
        self,
        order_data: dict,
        intent_id: str,
        correlation_id: str = ""
    ) -> str:
        """Log order submission."""
        return self.log_event(
            event_type=AuditEventType.ORDER_SUBMITTED,
            severity=AuditSeverity.INFO,
            message=f"Order submitted: {order_data.get('symbol')} {order_data.get('direction')} qty={order_data.get('qty')}",
            correlation_id=correlation_id,
            intent_id=intent_id,
            symbol=order_data.get("symbol", ""),
            details=order_data
        )

    def log_order_filled(
        self,
        order_id: str,
        fill_price: float,
        filled_qty: int,
        intent_id: str = "",
        symbol: str = ""
    ) -> str:
        """Log order fill."""
        return self.log_event(
            event_type=AuditEventType.ORDER_FILLED,
            severity=AuditSeverity.INFO,
            message=f"Order filled: {order_id} @ {fill_price} qty={filled_qty}",
            intent_id=intent_id,
            symbol=symbol,
            details={"order_id": order_id, "fill_price": fill_price, "filled_qty": filled_qty}
        )

    def log_reconciliation_mismatch(
        self,
        mismatch_type: str,
        details: dict
    ) -> str:
        """Log reconciliation mismatch."""
        return self.log_event(
            event_type=AuditEventType.RECONCILIATION_MISMATCH,
            severity=AuditSeverity.ERROR,
            message=f"Reconciliation mismatch: {mismatch_type}",
            details=details
        )

    def log_hard_halt(self, reason: str, source: str = "") -> str:
        """Log hard halt event."""
        return self.log_event(
            event_type=AuditEventType.HARD_HALT,
            severity=AuditSeverity.CRITICAL,
            message=f"HARD HALT: {reason}",
            details={"reason": reason, "source": source}
        )

    def log_system_mode_change(
        self,
        old_mode: str,
        new_mode: str,
        reason: str
    ) -> str:
        """Log system mode change."""
        return self.log_event(
            event_type=AuditEventType.SYSTEM_MODE_CHANGE,
            severity=AuditSeverity.WARNING,
            message=f"Mode: {old_mode} -> {new_mode}: {reason}",
            details={"old_mode": old_mode, "new_mode": new_mode, "reason": reason}
        )

    def log_stale_quote(self, symbol: str, quote_age: float) -> str:
        """Log stale quote detection."""
        return self.log_event(
            event_type=AuditEventType.STALE_QUOTE,
            severity=AuditSeverity.WARNING,
            message=f"Stale quote: {symbol} age={quote_age:.1f}s",
            symbol=symbol,
            details={"quote_age_seconds": quote_age}
        )

    def log_invalid_price(self, symbol: str, price: float, reason: str) -> str:
        """Log invalid price detection."""
        return self.log_event(
            event_type=AuditEventType.INVALID_PRICE,
            severity=AuditSeverity.ERROR,
            message=f"Invalid price: {symbol} price={price} reason={reason}",
            symbol=symbol,
            details={"price": price, "reason": reason}
        )

    def cleanup_old_files(self) -> int:
        """Remove audit files older than retain_days."""
        import time
        cutoff = time.time() - (self._retain_days * 86400)
        removed = 0

        for f in self._log_dir.glob("audit_*.jsonl"):
            if f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                    removed += 1
                except Exception as e:
                    log.warning(f"Failed to remove old audit file {f}: {e}")

        return removed


# Singleton
_audit_journal: AuditJournal | None = None


def get_audit_journal(config: dict | None = None) -> AuditJournal:
    """Get or create singleton audit journal."""
    global _audit_journal
    if _audit_journal is None:
        cfg = config or {}
        _audit_journal = AuditJournal(
            log_dir=cfg.get("audit_log_dir", "logs"),
            filename_prefix=cfg.get("audit_filename_prefix", "audit"),
            max_file_size_mb=cfg.get("audit_max_file_size_mb", 50),
            retain_days=cfg.get("audit_retain_days", 30)
        )
    return _audit_journal


def audit_log(
    event_type: AuditEventType,
    severity: AuditSeverity,
    message: str,
    **kwargs
) -> str:
    """Quick access to log an audit event."""
    journal = get_audit_journal()
    return journal.log_event(event_type, severity, message, **kwargs)
