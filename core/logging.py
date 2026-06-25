"""
Canonical Logging Abstraction (v2.46)

Provides standardized logging for the trading system.
Replaces legacy trading_system.core.logging.service imports.

Usage:
    from core.logging import get_logger
    logger = get_logger(__name__)
"""

from __future__ import annotations

import logging
import sys

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
    Get a configured logger instance.

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


class StructuredLogger:
    """
    Structured logging wrapper with context support.
    """

    def __init__(self, name: str):
        self._logger = get_logger(name)
        self._context: dict = {}

    def set_context(self, **kwargs):
        """Set logging context."""
        self._context.update(kwargs)

    def clear_context(self):
        """Clear logging context."""
        self._context = {}

    def _format(self, msg: str) -> str:
        """Format message with context."""
        if self._context:
            ctx_str = " | ".join(f"{k}={v}" for k, v in self._context.items())
            return f"{msg} [{ctx_str}]"
        return msg

    def debug(self, msg: str, **kwargs):
        self._logger.debug(self._format(msg), **kwargs)

    def info(self, msg: str, **kwargs):
        self._logger.info(self._format(msg), **kwargs)

    def warning(self, msg: str, **kwargs):
        self._logger.warning(self._format(msg), **kwargs)

    def error(self, msg: str, **kwargs):
        self._logger.error(self._format(msg), **kwargs)

    def critical(self, msg: str, **kwargs):
        self._logger.critical(self._format(msg), **kwargs)

    def exception(self, msg: str, **kwargs):
        self._logger.exception(self._format(msg), **kwargs)


def create_logger(name: str) -> StructuredLogger:
    """Create a structured logger."""
    return StructuredLogger(name)


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
    "LoggingService",
    "StructuredLogger",
    "create_logger",
    "default_logger",
    "get_logger",
]

