"""
Logging Utilities

This module provides structured logging capabilities for the trading system.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Thread-local storage for contextual logging context
_local = threading.local()


@dataclass
class LogContext:
    """
    Context information for structured logging.

    Attributes:
        correlation_id: Correlation ID for request tracing
        symbol: Trading symbol being processed
        strategy: Strategy name
        trade_id: Trade ID if applicable
        user_id: User ID if applicable
        session_id: Session ID if applicable
        custom_fields: Additional custom fields
    """
    correlation_id: str | None = None
    symbol: str | None = None
    strategy: str | None = None
    trade_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    custom_fields: dict[str, Any] = field(default_factory=dict)


class StructuredLogger:
    """
    A structured logger that adds contextual information to log records.

    This logger wraps Python's standard logging library and adds support
    for structured logging with context variables.
    """

    def __init__(self, name: str = "trading_bot", level: int = logging.INFO):
        """
        Initialize the structured logger.

        Args:
            name: Logger name
            level: Logging level
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)

        # Only add handler if none exists (to avoid duplicates)
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

        # Prevent propagation to root logger to avoid duplicate logs
        self.logger.propagate = False

    def _get_context(self) -> LogContext:
        """Get the current logging context from thread-local storage."""
        return getattr(_local, 'context', LogContext())

    def _set_context(self, context: LogContext) -> None:
        """Set the logging context in thread-local storage."""
        _local.context = context

    def contextualize(self, **kwargs) -> LogContextManager:
        """
        Create a context manager for adding temporary logging context.

        Returns:
            A context manager that adds the specified fields to the log context
        """
        return LogContextManager(self, kwargs)

    def _log(self, level: int, msg: str, **kwargs) -> None:
        """
        Internal method to log a message with context.

        Args:
            level: Logging level
            msg: Message to log
            **kwargs: Additional fields to include in the log
        """
        context = self._get_context()

        # Build the structured log message
        log_data = {
            'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'level': logging.getLevelName(level),
            'logger': self.logger.name,
            'message': msg,
        }

        # Add context fields
        if context.correlation_id:
            log_data['correlation_id'] = context.correlation_id
        if context.symbol:
            log_data['symbol'] = context.symbol
        if context.strategy:
            log_data['strategy'] = context.strategy
        if context.trade_id:
            log_data['trade_id'] = context.trade_id
        if context.user_id:
            log_data['user_id'] = context.user_id
        if context.session_id:
            log_data['session_id'] = context.session_id

        # Add custom fields from context
        log_data.update(context.custom_fields)

        # Add any additional fields passed in the log call
        log_data.update(kwargs)

        # Format as JSON for structured logging
        structured_msg = json.dumps(log_data)

        # Log using the underlying logger
        self.logger.log(level, structured_msg)

    def debug(self, msg: str, **kwargs) -> None:
        """Log a debug message with context."""
        self._log(logging.DEBUG, msg, **kwargs)

    def info(self, msg: str, **kwargs) -> None:
        """Log an info message with context."""
        self._log(logging.INFO, msg, **kwargs)

    def warning(self, msg: str, **kwargs) -> None:
        """Log a warning message with context."""
        self._log(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs) -> None:
        """Log an error message with context."""
        self._log(logging.ERROR, msg, **kwargs)

    def critical(self, msg: str, **kwargs) -> None:
        """Log a critical message with context."""
        self._log(logging.CRITICAL, msg, **kwargs)

    def exception(self, msg: str, **kwargs) -> None:
        """Log an exception message with context and traceback."""
        kwargs['exc_info'] = True
        self._log(logging.ERROR, msg, **kwargs)


class LogContextManager:
    """
    Context manager for temporarily adding fields to the logging context.
    """

    def __init__(self, logger: StructuredLogger, fields: dict[str, Any]):
        """
        Initialize the context manager.

        Args:
            logger: The StructuredLogger instance
            fields: Fields to add to the logging context
        """
        self.logger = logger
        self.fields = fields
        self.previous_context: LogContext | None = None

    def __enter__(self) -> LogContextManager:
        """Enter the context manager, adding the specified fields."""
        current_context = self.logger._get_context()
        self.previous_context = LogContext(
            correlation_id=current_context.correlation_id,
            symbol=current_context.symbol,
            strategy=current_context.strategy,
            trade_id=current_context.trade_id,
            user_id=current_context.user_id,
            session_id=current_context.session_id,
            custom_fields=current_context.custom_fields.copy()
        )

        # Update context with new fields
        new_context = LogContext(
            correlation_id=current_context.correlation_id,
            symbol=current_context.symbol,
            strategy=current_context.strategy,
            trade_id=current_context.trade_id,
            user_id=current_context.user_id,
            session_id=current_context.session_id,
            custom_fields={**current_context.custom_fields, **self.fields}
        )

        self.logger._set_context(new_context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit the context manager, restoring the previous context."""
        if self.previous_context is not None:
            self.logger._set_context(self.previous_context)
        else:
            # Clear context if there was none before
            self.logger._set_context(LogContext())


# Global logger instance
structured_logger = StructuredLogger()


# Convenience functions
def get_logger(name: str = "trading_bot") -> StructuredLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name

    Returns:
        A StructuredLogger instance
    """
    if name == "trading_bot":
        return structured_logger
    return StructuredLogger(name)


def log_debug(msg: str, **kwargs) -> None:
    """Log a debug message (convenience function)."""
    structured_logger.debug(msg, **kwargs)


def log_info(msg: str, **kwargs) -> None:
    """Log an info message (convenience function)."""
    structured_logger.info(msg, **kwargs)


def log_warning(msg: str, **kwargs) -> None:
    """Log a warning message (convenience function)."""
    structured_logger.warning(msg, **kwargs)


def log_error(msg: str, **kwargs) -> None:
    """Log an error message (convenience function)."""
    structured_logger.error(msg, **kwargs)


def log_critical(msg: str, **kwargs) -> None:
    """Log a critical message (convenience function)."""
    structured_logger.critical(msg, **kwargs)


def log_exception(msg: str, **kwargs) -> None:
    """Log an exception message (convenience function)."""
    structured_logger.exception(msg, **kwargs)


def with_context(**kwargs) -> LogContextManager:
    """
    Create a context manager for adding temporary logging context.

    Args:
        **kwargs: Fields to add to the logging context

    Returns:
        A context manager that adds the specified fields to the log context
    """
    return structured_logger.contextualize(**kwargs)
