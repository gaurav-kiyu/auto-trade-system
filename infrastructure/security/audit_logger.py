"""
Audit Logging System

This module provides secure audit logging for sensitive operations to enable
security monitoring, compliance, and forensic analysis.
Enhanced with comprehensive audit trail from signal to fill.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone

from core.datetime_ist import now_ist
from pathlib import Path
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, asdict, field

log = logging.getLogger(__name__)


@dataclass
class AuditEvent:
    """Represents a single audit event."""
    event_id: str
    timestamp: str  # ISO format timestamp
    event_type: str
    user_id: Optional[str]
    session_id: Optional[str]
    ip_address: Optional[str]
    resource: str
    action: str
    outcome: str  # success, failure, error
    details: Dict[str, Any]
    severity: str  # info, warning, error, critical
    correlation_id: Optional[str] = None  # For tracing related events

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), separators=(',', ':'))


@dataclass
class TradeAuditTrail:
    """Complete audit trail for a trade from signal to fill."""
    trade_id: str
    signal_generated: Optional[AuditEvent] = None
    signal_validated: Optional[AuditEvent] = None
    risk_approved: Optional[AuditEvent] = None
    order_submitted: Optional[AuditEvent] = None
    order_filled: Optional[AuditEvent] = None
    position_updated: Optional[AuditEvent] = None
    trade_closed: Optional[AuditEvent] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class AuditLogger:
    """
    Secure audit logger that writes events to a protected log file.

    Features:
    - Thread-safe logging
    - JSON format for easy parsing
    - Configurable output (file, syslog, external service)
    - Protection against log injection
    - Automatic log rotation (basic implementation)
    - Comprehensive audit trail tracking for trades
    """

    def __init__(self,
                 log_file: Optional[Path] = None,
                 max_file_size: int = 10 * 1024 * 1024,  # 10 MB
                 backup_count: int = 5,
                 enable_console_output: bool = False):
        """
        Initialize the audit logger.

        Args:
            log_file: Path to the audit log file. If None, uses default location.
            max_file_size: Maximum size of log file before rotation (in bytes).
            backup_count: Number of backup files to keep.
            enable_console_output: Whether to also output to console (for development).
        """
        self.log_file = log_file or (Path.home() / ".opb" / "audit.log")
        self.max_file_size = max_file_size
        self.backup_count = backup_count
        self.enable_console_output = enable_console_output
        self._lock = threading.RLock()

        # Trade audit trail tracking
        self._trade_trails: Dict[str, TradeAuditTrail] = {}
        self._trade_trail_lock = threading.RLock()

        # Ensure the log directory exists
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        # Initialize logging
        self._setup_logger()

    def _setup_logger(self):
        """Set up the internal logging configuration."""
        self._logger = logging.getLogger(f"audit.{id(self)}")
        self._logger.setLevel(logging.INFO)

        # Prevent adding multiple handlers if already configured
        if not self._logger.handlers:
            # File handler
            file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
            file_handler.setLevel(logging.INFO)

            # JSON formatter
            formatter = logging.Formatter('%(message)s')
            file_handler.setFormatter(formatter)

            self._logger.addHandler(file_handler)

            # Console handler for development
            if self.enable_console_output:
                console_handler = logging.StreamHandler()
                console_handler.setLevel(logging.INFO)
                console_handler.setFormatter(formatter)
                self._logger.addHandler(console_handler)

    def _rotate_log_if_needed(self):
        """Rotate the log file if it exceeds the maximum size."""
        try:
            if self.log_file.exists() and self.log_file.stat().st_size >= self.max_file_size:
                # Simple rotation: rename current file and create new one
                for i in range(self.backup_count - 1, 0, -1):
                    old_file = self.log_file.with_suffix(f'.log.{i}')
                    new_file = self.log_file.with_suffix(f'.log.{i + 1}')
                    if old_file.exists():
                        if new_file.exists():
                            new_file.unlink()
                        old_file.rename(new_file)

                # Rotate the current log file
                if self.log_file.exists():
                    backup_file = self.log_file.with_suffix('.log.1')
                    if backup_file.exists():
                        backup_file.unlink()
                    self.log_file.rename(backup_file)

                # Reinitialize the file handler with the new log file
                for handler in self._logger.handlers:
                    if isinstance(handler, logging.FileHandler):
                        handler.close()
                        self._logger.removeHandler(handler)

                file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
                file_handler.setLevel(logging.INFO)
                formatter = logging.Formatter('%(message)s')
                file_handler.setFormatter(formatter)
                self._logger.addHandler(file_handler)

        except Exception as e:
            # If we can't rotate, log the error but don't break audit logging
            print(f"Audit log rotation failed: {e}")

    def _sanitize_for_json(self, obj: Any) -> Any:
        """
        Sanitize an object for safe JSON serialization.
        Prevents injection of malicious content into the audit log.
        """
        if isinstance(obj, str):
            # Remove control characters except newline and tab
            # Also escape quotes and backslashes for JSON safety
            obj = ''.join(char for char in obj if ord(char) >= 32 or char in '\n\t')
            obj = obj.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t')
            return obj
        elif isinstance(obj, dict):
            return {key: self._sanitize_for_json(value) for key, value in obj.items()}
        elif isinstance(obj, (list, tuple, set)):
            return [self._sanitize_for_json(item) for item in obj]
        elif isinstance(obj, (int, float, bool)) or obj is None:
            return obj
        else:
            # For other types, convert to string and sanitize
            return self._sanitize_for_json(str(obj))

    def log_event(self,
                  event_type: str,
                  resource: str,
                  action: str,
                  outcome: str = "success",
                  details: Optional[Dict[str, Any]] = None,
                  severity: str = "info",
                  user_id: Optional[str] = None,
                  session_id: Optional[str] = None,
                  ip_address: Optional[str] = None,
                  correlation_id: Optional[str] = None) -> str:
        """
        Log an audit event.

        Args:
            event_type: Type of event (e.g., "signal_generated", "order_submitted")
            resource: The resource being accessed or modified
            action: The action performed (e.g., "generate", "validate", "execute")
            outcome: Result of the action ("success", "failure", "error")
            details: Additional details about the event
            severity: Severity level ("info", "warning", "error", "critical")
            user_id: ID of the user performing the action
            session_id: Session identifier
            ip_address: IP address of the client
            correlation_id: Correlation ID for tracing related events

        Returns:
            The event ID of the logged event
        """
        with self._lock:
            try:
                # Rotate log if needed
                self._rotate_log_if_needed()

                # Create the audit event
                event = AuditEvent(
                    event_id=str(uuid.uuid4()),
                    timestamp=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    event_type=event_type,
                    user_id=user_id,
                    session_id=session_id,
                    ip_address=ip_address,
                    resource=resource,
                    action=action,
                    outcome=outcome,
                    details=self._sanitize_for_json(details or {}),
                    severity=severity,
                    correlation_id=correlation_id
                )

                # Log the event as JSON
                self._logger.info(event.to_json())

                return event.event_id

            except Exception as e:
                # If audit logging fails, we don't want to break the application
                # but we should at least notify someone
                print(f"Audit logging failed: {e}")
                # Generate a fallback event ID
                return str(uuid.uuid4())

    def log_signal_generated(self,
                           signal_data: Dict[str, Any],
                           user_id: Optional[str] = None,
                           session_id: Optional[str] = None,
                           ip_address: Optional[str] = None) -> str:
        """Log a signal generation event."""
        correlation_id = str(uuid.uuid4())
        event_id = self.log_event(
            event_type="signal_generated",
            resource=f"signal:{signal_data.get('symbol', 'UNKNOWN')}",
            action="generate",
            outcome="success",
            details=signal_data,
            severity="info",
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            correlation_id=correlation_id
        )

        # Initialize trade audit trail
        trade_id = f"trade_{signal_data.get('symbol', 'UNKNOWN')}_{int(now_ist().timestamp())}"
        with self._trade_trail_lock:
            self._trade_trails[trade_id] = TradeAuditTrail(
                trade_id=trade_id,
                signal_generated=AuditEvent(
                    event_id=event_id,
                    timestamp=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    event_type="signal_generated",
                    user_id=user_id,
                    session_id=session_id,
                    ip_address=ip_address,
                    resource=f"signal:{signal_data.get('symbol', 'UNKNOWN')}",
                    action="generate",
                    outcome="success",
                    details=signal_data,
                    severity="info",
                    correlation_id=correlation_id
                )
            )

        return event_id

    def log_signal_validated(self,
                           signal_data: Dict[str, Any],
                           validation_result: Dict[str, Any],
                           correlation_id: str,
                           user_id: Optional[str] = None,
                           session_id: Optional[str] = None,
                           ip_address: Optional[str] = None) -> str:
        """Log a signal validation event."""
        event_id = self.log_event(
            event_type="signal_validated",
            resource=f"signal:{signal_data.get('symbol', 'UNKNOWN')}",
            action="validate",
            outcome="success" if validation_result.get("is_valid", False) else "failure",
            details={
                "signal_data": signal_data,
                "validation_result": validation_result
            },
            severity="info" if validation_result.get("is_valid", False) else "warning",
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            correlation_id=correlation_id
        )

        # Update trade audit trail
        trade_id = f"trade_{signal_data.get('symbol', 'UNKNOWN')}_{int(now_ist().timestamp())}"
        with self._trade_trail_lock:
            if trade_id in self._trade_trails:
                self._trade_trails[trade_id].signal_validated = AuditEvent(
                    event_id=event_id,
                    timestamp=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    event_type="signal_validated",
                    user_id=user_id,
                    session_id=session_id,
                    ip_address=ip_address,
                    resource=f"signal:{signal_data.get('symbol', 'UNKNOWN')}",
                    action="validate",
                    outcome="success" if validation_result.get("is_valid", False) else "failure",
                    details={
                        "signal_data": signal_data,
                        "validation_result": validation_result
                    },
                    severity="info" if validation_result.get("is_valid", False) else "warning",
                    correlation_id=correlation_id
                )

        return event_id

    def log_risk_approved(self,
                        signal_data: Dict[str, Any],
                        risk_evaluation: Dict[str, Any],
                        correlation_id: str,
                        user_id: Optional[str] = None,
                        session_id: Optional[str] = None,
                        ip_address: Optional[str] = None) -> str:
        """Log a risk approval event."""
        event_id = self.log_event(
            event_type="risk_approved",
            resource=f"signal:{signal_data.get('symbol', 'UNKNOWN')}",
            action="approve",
            outcome="success" if risk_evaluation.get("allowed", False) else "failure",
            details={
                "signal_data": signal_data,
                "risk_evaluation": risk_evaluation
            },
            severity="info" if risk_evaluation.get("allowed", False) else "warning",
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            correlation_id=correlation_id
        )

        # Update trade audit trail
        trade_id = f"trade_{signal_data.get('symbol', 'UNKNOWN')}_{int(now_ist().timestamp())}"
        with self._trade_trail_lock:
            if trade_id in self._trade_trails:
                self._trade_trails[trade_id].risk_approved = AuditEvent(
                    event_id=event_id,
                    timestamp=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    event_type="risk_approved",
                    user_id=user_id,
                    session_id=session_id,
                    ip_address=ip_address,
                    resource=f"signal:{signal_data.get('symbol', 'UNKNOWN')}",
                    action="approve",
                    outcome="success" if risk_evaluation.get("allowed", False) else "failure",
                    details={
                        "signal_data": signal_data,
                        "risk_evaluation": risk_evaluation
                    },
                    severity="info" if risk_evaluation.get("allowed", False) else "warning",
                    correlation_id=correlation_id
                )

        return event_id

    def log_order_submitted(self,
                          order_data: Dict[str, Any],
                          correlation_id: str,
                          user_id: Optional[str] = None,
                          session_id: Optional[str] = None,
                          ip_address: Optional[str] = None) -> str:
        """Log an order submission event."""
        event_id = self.log_event(
            event_type="order_submitted",
            resource=f"order:{order_data.get('symbol', 'UNKNOWN')}",
            action="submit",
            outcome="success",
            details=order_data,
            severity="info",
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            correlation_id=correlation_id
        )

        # Update trade audit trail
        trade_id = f"trade_{order_data.get('symbol', 'UNKNOWN')}_{int(now_ist().timestamp())}"
        with self._trade_trail_lock:
            if trade_id in self._trade_trails:
                self._trade_trails[trade_id].order_submitted = AuditEvent(
                    event_id=event_id,
                    timestamp=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    event_type="order_submitted",
                    user_id=user_id,
                    session_id=session_id,
                    ip_address=ip_address,
                    resource=f"order:{order_data.get('symbol', 'UNKNOWN')}",
                    action="submit",
                    outcome="success",
                    details=order_data,
                    severity="info",
                    correlation_id=correlation_id
                )

        return event_id

    def log_order_filled(self,
                       order_data: Dict[str, Any],
                       fill_data: Dict[str, Any],
                       correlation_id: str,
                       user_id: Optional[str] = None,
                       session_id: Optional[str] = None,
                       ip_address: Optional[str] = None) -> str:
        """Log an order fill event."""
        event_id = self.log_event(
            event_type="order_filled",
            resource=f"order:{order_data.get('symbol', 'UNKNOWN')}",
            action="fill",
            outcome="success",
            details={
                "order_data": order_data,
                "fill_data": fill_data
            },
            severity="info",
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            correlation_id=correlation_id
        )

        # Update trade audit trail
        trade_id = f"trade_{order_data.get('symbol', 'UNKNOWN')}_{int(now_ist().timestamp())}"
        with self._trade_trail_lock:
            if trade_id in self._trade_trails:
                self._trade_trails[trade_id].order_filled = AuditEvent(
                    event_id=event_id,
                    timestamp=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    event_type="order_filled",
                    user_id=user_id,
                    session_id=session_id,
                    ip_address=ip_address,
                    resource=f"order:{order_data.get('symbol', 'UNKNOWN')}",
                    action="fill",
                    outcome="success",
                    details={
                        "order_data": order_data,
                        "fill_data": fill_data
                    },
                    severity="info",
                    correlation_id=correlation_id
                )

                # Also log as traditional trade_execution event for backward compatibility
                self.log_trade_execution(
                    user_id=user_id or "system",
                    symbol=order_data.get('symbol', 'UNKNOWN'),
                    action="fill",
                    quantity=fill_data.get('quantity', 0),
                    order_id=order_data.get('order_id', 'UNKNOWN'),
                    outcome="success",
                    details=fill_data,
                    session_id=session_id,
                    ip_address=ip_address
                )

        return event_id

    def log_position_updated(self,
                           position_data: Dict[str, Any],
                           correlation_id: str,
                           user_id: Optional[str] = None,
                           session_id: Optional[str] = None,
                           ip_address: Optional[str] = None) -> str:
        """Log a position update event."""
        event_id = self.log_event(
            event_type="position_updated",
            resource=f"position:{position_data.get('symbol', 'UNKNOWN')}",
            action="update",
            outcome="success",
            details=position_data,
            severity="info",
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            correlation_id=correlation_id
        )

        # Update trade audit trail
        trade_id = f"trade_{position_data.get('symbol', 'UNKNOWN')}_{int(now_ist().timestamp())}"
        with self._trade_trail_lock:
            if trade_id in self._trade_trails:
                self._trade_trails[trade_id].position_updated = AuditEvent(
                    event_id=event_id,
                    timestamp=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    event_type="position_updated",
                    user_id=user_id,
                    session_id=session_id,
                    ip_address=ip_address,
                    resource=f"position:{position_data.get('symbol', 'UNKNOWN')}",
                    action="update",
                    outcome="success",
                    details=position_data,
                    severity="info",
                    correlation_id=correlation_id
                )

        return event_id

    def log_trade_closed(self,
                       trade_data: Dict[str, Any],
                       correlation_id: str,
                       user_id: Optional[str] = None,
                       session_id: Optional[str] = None,
                       ip_address: Optional[str] = None) -> str:
        """Log a trade closure event."""
        event_id = self.log_event(
            event_type="trade_closed",
            resource=f"trade:{trade_data.get('symbol', 'UNKNOWN')}",
            action="close",
            outcome="success",
            details=trade_data,
            severity="info",
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            correlation_id=correlation_id
        )

        # Update trade audit trail
        trade_id = f"trade_{trade_data.get('symbol', 'UNKNOWN')}_{int(now_ist().timestamp())}"
        with self._trade_trail_lock:
            if trade_id in self._trade_trails:
                self._trade_trails[trade_id].trade_closed = AuditEvent(
                    event_id=event_id,
                    timestamp=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    event_type="trade_closed",
                    user_id=user_id,
                    session_id=session_id,
                    ip_address=ip_address,
                    resource=f"trade:{trade_data.get('symbol', 'UNKNOWN')}",
                    action="close",
                    outcome="success",
                    details=trade_data,
                    severity="info",
                    correlation_id=correlation_id
                )

        return event_id

    def get_trade_audit_trail(self, trade_id: str) -> Optional[TradeAuditTrail]:
        """
        Get the complete audit trail for a trade.

        Args:
            trade_id: The trade ID to retrieve audit trail for

        Returns:
            TradeAuditTrail if found, None otherwise
        """
        with self._trade_trail_lock:
            return self._trade_trails.get(trade_id)

    def log_trade_execution(self, user_id: str, symbol: str, action: str, quantity: int,
                           order_id: str, outcome: str, details: Optional[Dict[str, Any]] = None,
                           session_id: Optional[str] = None, ip_address: Optional[str] = None) -> str:
        """Log a trade execution event (backward compatibility)."""
        return self.log_event(
            event_type="trade_execution",
            resource=f"trade:{symbol}",
            action=action,
            outcome=outcome,
            details={
                "symbol": symbol,
                "quantity": quantity,
                "order_id": order_id,
                **(details or {})
            },
            severity="info",
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address
        )

    def log_authentication(self, user_id: str, outcome: str, details: Optional[Dict[str, Any]] = None,
                          session_id: Optional[str] = None, ip_address: Optional[str] = None) -> str:
        """Log an authentication event."""
        return self.log_event(
            event_type="authentication",
            resource="user_account",
            action="login",
            outcome=outcome,
            details=details,
            severity="info" if outcome == "success" else "warning",
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address
        )

    def log_config_change(self, user_id: str, config_key: str, old_value: Any, new_value: Any,
                         session_id: Optional[str] = None, ip_address: Optional[str] = None) -> str:
        """Log a configuration change event."""
        # Sanitize values for logging (don't log secrets in plaintext)
        sanitized_old = "[REDACTED]" if self._is_secret_key(config_key) else old_value
        sanitized_new = "[REDACTED]" if self._is_secret_key(config_key) else new_value

        return self.log_event(
            event_type="config_change",
            resource=f"config:{config_key}",
            action="update",
            outcome="success",
            details={
                "old_value": sanitized_old,
                "new_value": sanitized_new,
                "config_key": config_key
            },
            severity="info",
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address
        )

    def log_security_violation(self, event_type: str, resource: str, action: str,
                              details: Optional[Dict[str, Any]] = None,
                              user_id: Optional[str] = None,
                              session_id: Optional[str] = None,
                              ip_address: Optional[str] = None) -> str:
        """Log a security violation event."""
        return self.log_event(
            event_type=f"security:{event_type}",
            resource=resource,
            action=action,
            outcome="blocked",
            details=details,
            severity="critical",
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address
        )

    def _is_secret_key(self, key: str) -> bool:
        """Check if a configuration key is likely to contain a secret."""
        secret_indicators = ['token', 'key', 'secret', 'password', 'credential', 'auth']
        key_lower = key.lower()
        return any(indicator in key_lower for indicator in secret_indicators)

    def cleanup_old_trails(self, max_age_hours: int = 24) -> int:
        """
        Clean up old trade audit trails to prevent memory buildup.

        Args:
            max_age_hours: Maximum age in hours to keep trails

        Returns:
            Number of trails cleaned up
        """
        cutoff_time = now_ist() - timedelta(hours=max_age_hours)
        cleaned_count = 0

        with self._trade_trail_lock:
            trails_to_remove = []
            for trade_id, trail in self._trade_trails.items():
                # Check if the trail is old based on the first event timestamp
                oldest_time = None
                for event_field in ['signal_generated', 'signal_validated', 'risk_approved',
                                  'order_submitted', 'order_filled', 'position_updated', 'trade_closed']:
                    event = getattr(trail, event_field)
                    if event and event.timestamp:
                        event_time = datetime.fromisoformat(event.timestamp.replace('Z', '+00:00'))
                        if oldest_time is None or event_time < oldest_time:
                            oldest_time = event_time

                if oldest_time and oldest_time < cutoff_time:
                    trails_to_remove.append(trade_id)

            for trade_id in trails_to_remove:
                del self._trade_trails[trade_id]
                cleaned_count += 1

        if cleaned_count > 0:
            log.info(f"Cleaned up {cleaned_count} old trade audit trails")

        return cleaned_count


# Module-level globals for singleton access
_audit_logger_lock: threading.Lock = threading.Lock()
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        with _audit_logger_lock:
            if _audit_logger is None:
                _audit_logger = AuditLogger()
    return _audit_logger


def init_audit_logger(log_file: Optional[Path] = None,
                     max_file_size: int = 10 * 1024 * 1024,
                     backup_count: int = 5,
                     enable_console_output: bool = False) -> AuditLogger:
    """Initialize the global audit logger."""
    global _audit_logger
    with _audit_logger_lock:
        _audit_logger = AuditLogger(
            log_file=log_file,
            max_file_size=max_file_size,
            backup_count=backup_count,
            enable_console_output=enable_console_output
        )
    return _audit_logger


# Convenience functions for common audit events
def log_authentication(user_id: str, outcome: str, details: Optional[Dict[str, Any]] = None,
                      session_id: Optional[str] = None, ip_address: Optional[str] = None) -> str:
    """Log an authentication event using the global audit logger."""
    return get_audit_logger().log_authentication(user_id, outcome, details, session_id, ip_address)


def log_config_change(user_id: str, config_key: str, old_value: Any, new_value: Any,
                     session_id: Optional[str] = None, ip_address: Optional[str] = None) -> str:
    """Log a configuration change event using the global audit logger."""
    return get_audit_logger().log_config_change(user_id, config_key, old_value, new_value, session_id, ip_address)


def log_trade_execution(user_id: str, symbol: str, action: str, quantity: int,
                       order_id: str, outcome: str, details: Optional[Dict[str, Any]] = None,
                      session_id: Optional[str] = None, ip_address: Optional[str] = None) -> str:
    """Log a trade execution event using the global audit logger."""
    return get_audit_logger().log_trade_execution(user_id, symbol, action, quantity, order_id, outcome, details, session_id, ip_address)


def log_security_violation(event_type: str, resource: str, action: str,
                          details: Optional[Dict[str, Any]] = None,
                          user_id: Optional[str] = None,
                          session_id: Optional[str] = None,
                          ip_address: Optional[str] = None) -> str:
    """Log a security violation event using the global audit logger."""
    return get_audit_logger().log_security_violation(event_type, resource, action, details, user_id, session_id, ip_address)


# Convenience functions for signal-to-fill audit trail
def log_signal_generated(signal_data: Dict[str, Any],
                        user_id: Optional[str] = None,
                        session_id: Optional[str] = None,
                        ip_address: Optional[str] = None) -> str:
    """Log a signal generation event using the global audit logger."""
    return get_audit_logger().log_signal_generated(signal_data, user_id, session_id, ip_address)


def log_signal_validated(signal_data: Dict[str, Any],
                        validation_result: Dict[str, Any],
                        correlation_id: str,
                        user_id: Optional[str] = None,
                        session_id: Optional[str] = None,
                        ip_address: Optional[str] = None) -> str:
    """Log a signal validation event using the global audit logger."""
    return get_audit_logger().log_signal_validated(signal_data, validation_result, correlation_id, user_id, session_id, ip_address)


def log_risk_approved(signal_data: Dict[str, Any],
                     risk_evaluation: Dict[str, Any],
                     correlation_id: str,
                     user_id: Optional[str] = None,
                     session_id: Optional[str] = None,
                     ip_address: Optional[str] = None) -> str:
    """Log a risk approval event using the global audit logger."""
    return get_audit_logger().log_risk_approved(signal_data, risk_evaluation, correlation_id, user_id, session_id, ip_address)


def log_order_submitted(order_data: Dict[str, Any],
                       correlation_id: str,
                       user_id: Optional[str] = None,
                       session_id: Optional[str] = None,
                       ip_address: Optional[str] = None) -> str:
    """Log an order submission event using the global audit logger."""
    return get_audit_logger().log_order_submitted(order_data, correlation_id, user_id, session_id, ip_address)


def log_order_filled(order_data: Dict[str, Any],
                    fill_data: Dict[str, Any],
                    correlation_id: str,
                    user_id: Optional[str] = None,
                    session_id: Optional[str] = None,
                    ip_address: Optional[str] = None) -> str:
    """Log an order fill event using the global audit logger."""
    return get_audit_logger().log_order_filled(order_data, fill_data, correlation_id, user_id, session_id, ip_address)


def log_position_updated(position_data: Dict[str, Any],
                        correlation_id: str,
                        user_id: Optional[str] = None,
                        session_id: Optional[str] = None,
                        ip_address: Optional[str] = None) -> str:
    """Log a position update event using the global audit logger."""
    return get_audit_logger().log_position_updated(position_data, correlation_id, user_id, session_id, ip_address)


def log_trade_closed(trade_data: Dict[str, Any],
                    correlation_id: str,
                    user_id: Optional[str] = None,
                    session_id: Optional[str] = None,
                    ip_address: Optional[str] = None) -> str:
    """Log a trade closure event using the global audit logger."""
    return get_audit_logger().log_trade_closed(trade_data, correlation_id, user_id, session_id, ip_address)


def get_trade_audit_trail(trade_id: str) -> Optional[TradeAuditTrail]:
    """Get the complete audit trail for a trade using the global audit logger."""
    return get_audit_logger().get_trade_audit_trail(trade_id)


# Export public interface
__all__ = [
    'AuditLogger',
    'AuditEvent',
    'TradeAuditTrail',
    'get_audit_logger',
    'init_audit_logger',
    'log_authentication',
    'log_config_change',
    'log_trade_execution',
    'log_security_violation',
    # Signal-to-fill audit trail functions
    'log_signal_generated',
    'log_signal_validated',
    'log_risk_approved',
    'log_order_submitted',
    'log_order_filled',
    'log_position_updated',
    'log_trade_closed',
    'get_trade_audit_trail'
]