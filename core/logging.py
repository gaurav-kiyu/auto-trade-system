"""
Canonical Logging Abstraction (v2.53+)

Provides standardized logging for the trading system.
Delegates to ``core.common.utilities.logging.StructuredLogger`` for the
canonical implementation with JSON output and thread-local context.

Usage:
    from core.logging import get_logger
    logger = get_logger(__name__)
"""

from __future__ import annotations

import logging
import sys

# Import canonical StructuredLogger from common utilities
from core.common.utilities.logging import (
    StructuredLogger as _CanonicalStructuredLogger,
    LogContextManager,
    with_context,
)


# Singleton logging configuration
_configured = False


def _configure_root_logger():
    """Configure root logger once."""
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    _configured = True


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Get a configured logger instance (backward compat).
    For structured logging with context, use StructuredLogger from core.common.utilities.logging.

    Args:
        name: Logger name (typically __name__)
        level: Logging level

    Returns:
        Configured logger instance
    """
    _configure_root_logger()
    logger = logging.getLogger(name)
    logger.setLevel(level)
    return logger


def create_logger(name: str) -> StructuredLogger:
    """Create a structured logger (delegates to canonical implementation)."""
    return StructuredLogger(name)


class StructuredLogger:
    """
    Structured logging wrapper with context support (v2.53+).

    Backward-compatible wrapper around ``core.common.utilities.logging.StructuredLogger``.
    Delegates to the canonical implementation with JSON output and thread-local
    LogContext, while preserving the original dict-based ``_context`` / ``set_context()`` API.
    New code should use ``LogContextManager`` / ``with_context()`` directly.
    """

    def __init__(self, name: str):
        self._impl = _CanonicalStructuredLogger(name)
        self._context: dict = {}
        # Enable propagation so caplog and root handlers can capture
        self._impl.logger.propagate = True

    @property
    def _logger(self) -> logging.Logger:
        """Access underlying logger (backward compat)."""
        return self._impl.logger

    def set_context(self, **kwargs):
        """Set logging context (backward compat)."""
        self._context.update(kwargs)

    def clear_context(self):
        """Clear logging context (backward compat)."""
        self._context = {}

    def _format(self, msg: str) -> str:
        """Format message with context (backward compat)."""
        if self._context:
            ctx_str = " | ".join(f"{k}={v}" for k, v in self._context.items())
            return f"{msg} [{ctx_str}]"
        return msg

    def debug(self, msg: str, **kwargs):
        if self._context:
            kwargs.update(self._context)
        self._impl.debug(msg, **kwargs)

    def info(self, msg: str, **kwargs):
        if self._context:
            kwargs.update(self._context)
        self._impl.info(msg, **kwargs)

    def warning(self, msg: str, **kwargs):
        if self._context:
            kwargs.update(self._context)
        self._impl.warning(msg, **kwargs)

    def error(self, msg: str, **kwargs):
        if self._context:
            kwargs.update(self._context)
        self._impl.error(msg, **kwargs)

    def critical(self, msg: str, **kwargs):
        if self._context:
            kwargs.update(self._context)
        self._impl.critical(msg, **kwargs)

    def exception(self, msg: str, **kwargs):
        if self._context:
            kwargs.update(self._context)
        self._impl.exception(msg, **kwargs)


# Convenience: default logger for quick imports
default_logger = get_logger("core")


# Backward compatibility alias for existing code using LoggingService
class LoggingService:
    """
    Logging service with rotating file handler and optional JSON output.
    All new code should use get_logger() directly.
    """

    def __init__(self, log_dir: str = "logs", log_filename_prefix: str = "trader_",
                 retain_days: int = 30, json_log_file: str = "", version: str = "UNKNOWN",
                 enable_correlation_ids: bool = True, enable_contextual_logging: bool = True):
        import os as _os
        from logging.handlers import RotatingFileHandler as _RotatingFileHandler

        logger_name = f"service.{log_filename_prefix}"
        self._logger = logging.getLogger(logger_name)
        self._logger.setLevel(logging.INFO)

        # Only add file handlers if log_dir is provided and writable
        if log_dir:
            log_path = _os.path.join(log_dir, f"{log_filename_prefix}app.log")
            try:
                _os.makedirs(log_dir, exist_ok=True)
                max_bytes = 50 * 1024 * 1024  # 50 MB per file
                self._handler = _RotatingFileHandler(log_path, maxBytes=max_bytes, backupCount=retain_days)
                self._handler.setFormatter(logging.Formatter(
                    '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                ))
                self._logger.addHandler(self._handler)

                # Optional JSON log file
                if json_log_file:
                    import json as _json
                    class _JsonFormatter(logging.Formatter):
                        def format(self, record):
                            return _json.dumps({
                                "ts": self.formatTime(record),
                                "level": record.levelname,
                                "logger": record.name,
                                "message": record.getMessage(),
                                "module": record.module,
                                "line": record.lineno,
                            })
                    json_path = _os.path.join(log_dir, json_log_file)
                    self._json_handler = _RotatingFileHandler(json_path, maxBytes=max_bytes, backupCount=3)
                    self._json_handler.setFormatter(_JsonFormatter())
                    self._logger.addHandler(self._json_handler)
            except (OSError, PermissionError) as e:
                _log.debug("[LOGGING] non-critical error: %s", e)

    def log(self, level: int, message: str, **kwargs):
        self._logger.log(level, message, **kwargs)

    def debug(self, message: str, **kwargs):
        self._logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs):
        self._logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs):
        self._logger.error(message, **kwargs)

    def critical(self, message: str, **kwargs):
        self._logger.critical(message, **kwargs)

    def exception(self, message: str, **kwargs):
        self._logger.exception(message, **kwargs)


__all__ = [
    "LogContextManager",
    "LoggingService",
    "StructuredLogger",
    "create_logger",
    "default_logger",
    "get_logger",
    "with_context",
]

