"""
Logging Service - Structured logging with JSON and file outputs.
Replaces global logging functions with proper dependency injection.
Enhanced with correlation IDs and contextual logging.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Import our isolated datetime service and log helpers to avoid pulling in the full core package
from trading_system.core.datetime_ist import now_ist
from trading_system.core.log_helpers import cleanup_old_prefixed_logs


# Context variables for correlation ID and logging context
_correlation_id: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)
_logging_context: ContextVar[Dict[str, Any]] = ContextVar('logging_context', default={})


class LoggingService:
    """
    Structured logging service that replaces global log() function.

    Features:
    - Console output with timestamps
    - File logging with rotation
    - JSON structured logging
    - Thread-safe operations
    - Configurable log levels
    - Exception tracking integration
    - Correlation IDs for request tracing
    - Contextual logging for better traceability
    """

    def __init__(
        self,
        log_dir: str = "logs",
        log_filename_prefix: str = "stock_trader_",
        retain_days: int = 30,
        json_log_file: Optional[str] = "",
        version: str = "UNKNOWN",
        enable_correlation_ids: bool = True,
        enable_contextual_logging: bool = True
    ):
        """
        Initialize logging service.

        Args:
            log_dir: Directory for log files
            log_filename_prefix: Prefix for log filenames
            retain_days: Number of days to retain log files
            json_log_file: Path for JSON structured log file (empty to disable)
            version: Application version for log headers
            enable_correlation_ids: Whether to enable correlation IDs
            enable_contextual_logging: Whether to enable contextual logging
        """
        self._log_dir = log_dir
        self._log_filename_prefix = log_filename_prefix
        self._retain_days = retain_days
        self._json_log_file = json_log_file
        self._version = version
        self._enable_correlation_ids = enable_correlation_ids
        self._enable_contextual_logging = enable_contextual_logging

        # Thread safety
        self._lock = threading.RLock()

        # Logger instances
        self._file_logger: Optional[logging.Logger] = None
        self._json_logger: Optional[logging.Logger] = None

        # Initialize logging
        self._setup_logging()

    def _setup_logging(self) -> None:
        """Set up file and JSON logging."""
        with self._lock:
            try:
                # Clean up old logs
                self._cleanup_old_logs()

                # Create logs directory if it doesn't exist
                os.makedirs(self._log_dir, exist_ok=True)

                # Set up file logger
                log_path = os.path.join(
                    self._log_dir,
                    f"{self._log_filename_prefix}{now_ist().strftime('%Y%m%d')}.log"
                )

                self._file_logger = logging.getLogger("stock_trader")
                self._file_logger.setLevel(logging.INFO)

                # Clear any existing handlers to avoid duplicates
                self._file_logger.handlers.clear()

                # Add file handler
                fh = logging.FileHandler(log_path, encoding="utf-8")
                fh.setFormatter(
                    logging.Formatter(
                        f"%(asctime)s [v{self._version}] %(message)s",
                        datefmt="%H:%M:%S"
                    )
                )
                self._file_logger.addHandler(fh)

                # Set up JSON logger if requested
                if self._json_log_file:
                    self._json_logger = logging.getLogger("json_structured_stock")
                    self._json_logger.setLevel(logging.INFO)
                    self._json_logger.handlers.clear()

                    jh = logging.FileHandler(
                        self._json_log_file,
                        encoding="utf-8"
                    )
                    jh.setFormatter(logging.Formatter('%(message)s'))
                    self._json_logger.addHandler(jh)

                # Log startup message
                self._file_logger.info(f"=== STOCK TRADER v{self._version} START ===")

            except Exception as e:
                # Fallback to basic logging if setup fails
                print(f"[LOGGING SETUP ERROR] {e}")

    def _cleanup_old_logs(self) -> None:
        """Clean up old log files based on retention policy."""
        try:
            cleanup_old_prefixed_logs(
                self._log_dir,
                self._log_filename_prefix,
                retain_days=self._retain_days,
                delete_rotated_variants=True
            )
        except Exception:
            # Ignore cleanup errors to avoid breaking logging
            pass

    def _get_correlation_id(self) -> Optional[str]:
        """Get the current correlation ID."""
        if not self._enable_correlation_ids:
            return None
        return _correlation_id.get()

    def _set_correlation_id(self, correlation_id: Optional[str] = None) -> str:
        """
        Set the correlation ID.

        Args:
            correlation_id: Optional correlation ID to set (generates new one if None)

        Returns:
            The correlation ID that was set
        """
        if not self._enable_correlation_ids:
            return None
        if correlation_id is None:
            correlation_id = str(uuid.uuid4())
        _correlation_id.set(correlation_id)
        return correlation_id

    def _get_logging_context(self) -> Dict[str, Any]:
        """Get the current logging context."""
        if not self._enable_contextual_logging:
            return {}
        return _logging_context.get()

    def _set_logging_context(self, context: Dict[str, Any]) -> None:
        """
        Set the logging context.

        Args:
            context: Dictionary of context key-value pairs
        """
        if not self._enable_contextual_logging:
            return
        current_context = self._get_logging_context()
        current_context.update(context)
        _logging_context.set(current_context)

    def _clear_logging_context(self) -> None:
        """Clear the logging context."""
        if self._enable_contextual_logging:
            _logging_context.set({})

    def log(self, msg: str, **extra: Any) -> None:
        """
        Log a message to console, file, and JSON (if configured).

        Args:
            msg: Message to log
            **extra: Additional fields for JSON logging
        """
        with self._lock:
            try:
                # Format timestamp
                timestamp = now_ist().strftime('%H:%M:%S')
                formatted_msg = f"[{timestamp}] {msg}"

                # Add correlation ID and context if enabled
                correlation_id = self._get_correlation_id()
                context = self._get_logging_context()

                # Prepare extra data for JSON logging
                payload_extra = dict(extra)  # Copy extra to avoid modifying caller's dict
                if correlation_id and self._enable_correlation_ids:
                    payload_extra["correlation_id"] = correlation_id
                if context and self._enable_contextual_logging:
                    payload_extra.update(context)

                # Print to console with correlation ID and context if enabled
                console_msg = formatted_msg
                if correlation_id and self._enable_correlation_ids:
                    console_msg += f" [cid:{correlation_id[:8]}]"
                if context and self._enable_contextual_logging:
                    # Add brief context to console
                    context_str = ", ".join(f"{k}={v}" for k, v in list(context.items())[:3])
                    if len(context) > 3:
                        context_str += f",+{len(context)-3}more"
                    console_msg += f" [{context_str}]"

                print(console_msg)

                # Log to file
                if self._file_logger:
                    self._file_logger.info(msg, extra=payload_extra if payload_extra else None)

                # Log to JSON (if configured)
                if self._json_logger:
                    try:
                        payload = {
                            "ts": now_ist().isoformat(),
                            "msg": msg
                        }
                        if payload_extra:
                            payload.update(payload_extra)
                        self._json_logger.info(
                            json.dumps(payload, ensure_ascii=False, default=str)
                        )
                    except Exception:
                        # Silently ignore JSON logging errors to avoid breaking main logging
                        pass

            except Exception as e:
                # Last resort fallback to prevent logging errors from crashing the app
                print(f"[LOGGING ERROR] {e}")
                print(f"[ORIGINAL MSG] {msg}")

    def info(self, msg: str, **extra: Any) -> None:
        """Log an info message."""
        self.log(msg, **extra)

    def warning(self, msg: str, **extra: Any) -> None:
        """Log a warning message."""
        self.log(f"WARNING: {msg}", **extra)

    def error(self, msg: str, **extra: Any) -> None:
        """Log an error message."""
        self.log(f"ERROR: {msg}", **extra)

    def debug(self, msg: str, **extra: Any) -> None:
        """Log a debug message."""
        self.log(f"DEBUG: {msg}", **extra)

    def critical(self, msg: str, **extra: Any) -> None:
        """Log a critical message."""
        self.log(f"CRITICAL: {msg}", **extra)

    def exception(self, msg: str, exc_info: bool = True, **extra: Any) -> None:
        """
        Log an exception with traceback.

        Args:
            msg: Message to log
            exc_info: Whether to include exception info
            **extra: Additional fields for JSON logging
        """
        import traceback

        with self._lock:
            try:
                timestamp = now_ist().strftime('%H:%M:%S')
                formatted_msg = f"[{timestamp}] EXCEPTION: {msg}"

                # Add correlation ID and context if enabled
                correlation_id = self._get_correlation_id()
                context = self._get_logging_context()

                # Prepare extra data for JSON logging
                payload_extra = dict(extra)  # Copy extra to avoid modifying caller's dict
                if correlation_id and self._enable_correlation_ids:
                    payload_extra["correlation_id"] = correlation_id
                if context and self._enable_contextual_logging:
                    payload_extra.update(context)

                # Print to console with traceback
                console_msg = formatted_msg
                if correlation_id and self._enable_correlation_ids:
                    console_msg += f" [cid:{correlation_id[:8]}]"
                if context and self._enable_contextual_logging:
                    context_str = ", ".join(f"{k}={v}" for k, v in list(context.items())[:3])
                    if len(context) > 3:
                        context_str += f",+{len(context)-3}more"
                    console_msg += f" [{context_str}]"

                print(console_msg)
                if exc_info:
                    traceback.print_exc()

                # Log to file
                if self._file_logger:
                    if exc_info:
                        self._file_logger.exception(msg, extra=payload_extra if payload_extra else None)
                    else:
                        self._file_logger.error(msg, extra=payload_extra if payload_extra else None)

                # Log to JSON (if configured)
                if self._json_logger:
                    try:
                        payload = {
                            "ts": now_ist().isoformat(),
                            "msg": msg,
                            "level": "EXCEPTION"
                        }
                        if payload_extra:
                            payload.update(payload_extra)
                        self._json_logger.info(
                            json.dumps(payload, ensure_ascii=False, default=str)
                        )
                    except Exception:
                        pass

            except Exception as e:
                print(f"[LOGGING EXCEPTION ERROR] {e}")

    def track_exception(self, fn: str, exc: Exception) -> None:
        """
        Track exceptions for alerting (replaces _track_exception from monolith).

        This is a simplified version - the full implementation would integrate
        with the state management and alerting systems.

        Args:
            fn: Function name where exception occurred
            exc: Exception object
        """
        # For now, just log it - full implementation would integrate with state
        self.error(f"Exception in {fn}: {exc}", function=fn, exception_type=type(exc).__name__)

    def shutdown(self) -> None:
        """Clean up logging resources."""
        with self._lock:
            try:
                if self._file_logger:
                    self._file_logger.info(f"=== STOCK TRADER v{self._version} SHUTDOWN ===")
                    # Close file handlers
                    for handler in self._file_logger.handlers[:]:
                        handler.close()
                        self._file_logger.removeHandler(handler)

                if self._json_logger:
                    # Close JSON handlers
                    for handler in self._json_logger.handlers[:]:
                        handler.close()
                        self._json_logger.removeHandler(handler)

            except Exception:
                pass  # Best effort cleanup


# Global logger instance (can be replaced with dependency injection)
_default_logger: Optional[LoggingService] = None


def get_logger() -> LoggingService:
    """
    Get the default logger instance, creating it if necessary.

    Returns:
        LoggingService instance
    """
    global _default_logger
    if _default_logger is None:
        # Create with default values - in practice these would come from config
        _default_logger = LoggingService()
    return _default_logger


def setup_logging(
    log_dir: str = "logs",
    log_filename_prefix: str = "stock_trader_",
    retain_days: int = 30,
    json_log_file: str = "",
    version: str = "UNKNOWN",
    enable_correlation_ids: bool = True,
    enable_contextual_logging: bool = True
) -> LoggingService:
    """
    Set up and return a logging service instance.

    Args:
        log_dir: Directory for log files
        log_filename_prefix: Prefix for log filenames
        retain_days: Number of days to retain log files
        json_log_file: Path for JSON structured log file (empty to disable)
        version: Application version for log headers
        enable_correlation_ids: Whether to enable correlation IDs
        enable_contextual_logging: Whether to enable contextual logging

    Returns:
        Configured LoggingService instance
    """
    global _default_logger
    _default_logger = LoggingService(
        log_dir=log_dir,
        log_filename_prefix=log_filename_prefix,
        retain_days=retain_days,
        json_log_file=json_log_file,
        version=version,
        enable_correlation_ids=enable_correlation_ids,
        enable_contextual_logging=enable_contextual_logging
    )
    return _default_logger


# Convenience functions that mirror the original log() function signature
def log(msg: str, **extra: Any) -> None:
    """
    Log a message - mirrors the original global log() function.

    This maintains backward compatibility while using the new LoggingService.
    """
    get_logger().log(msg, **extra)


def log_csv(ts: str, stock: str, direction: str, entry: float, exit_p: float,
           gross_pnl: float, net_pnl: float, reason: str, **kw: Any) -> None:
    """
    Log CSV trade data - mirrors the original log_csv function.
    """
    logger = get_logger()
    # In a full implementation, this would write to a CSV file
    # For now, we'll log it as structured data
    logger.info(
        f"TRADE: {stock} {direction} Entry:{entry} Exit:{exit_p} "
        f"PnL:{gross_pnl} Net:{net_pnl} Reason:{reason}",
        timestamp=ts,
        stock=stock,
        direction=direction,
        entry=entry,
        exit=exit_p,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        reason=reason,
        **kw
    )


# Context manager for correlation IDs
class correlation_id:
    """Context manager for setting correlation ID."""

    def __init__(self, cid: Optional[str] = None):
        self.cid = cid
        self.token = None

    def __enter__(self):
        self.token = _correlation_id.set(self.cid if self.cid is not None else str(uuid.uuid4()))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token is not None:
            _correlation_id.reset(self.token)


# Context manager for logging context
class logging_context:
    """Context manager for setting logging context."""

    def __init__(self, **context):
        self.context = context
        self.token = None

    def __enter__(self):
        current_context = _logging_context.get()
        new_context = {**current_context, **self.context}
        self.token = _logging_context.set(new_context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token is not None:
            _logging_context.reset(self.token)


# Convenience functions for managing correlation ID and context
def set_correlation_id(correlation_id: Optional[str] = None) -> str:
    """Set the correlation ID and return it."""
    return get_logger()._set_correlation_id(correlation_id)


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID."""
    return get_logger()._get_correlation_id()


def set_logging_context(**context) -> None:
    """Set logging context key-value pairs."""
    get_logger()._set_logging_context(context)


def get_logging_context() -> Dict[str, Any]:
    """Get the current logging context."""
    return get_logger()._get_logging_context()


def clear_logging_context() -> None:
    """Clear the logging context."""
    get_logger()._clear_logging_context()