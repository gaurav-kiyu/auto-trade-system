"""
Logging Adapter

Adapter that implements the LoggingPort interface using the existing StructuredLogger class.
"""

from __future__ import annotations

from typing import Any

# Import the port interface
from core.ports.logging import LoggingPort

# Import the existing logger implementation
try:
    from core.common.utilities.logging import StructuredLogger
except ImportError:
    # Fallback for development
    StructuredLogger = None  # type: ignore


class StructuredLoggerAdapter(LoggingPort):
    """
    Adapter that implements LoggingPort using the existing StructuredLogger class.

    This follows the Dependency Inversion Principle - high-level modules (trading logic)
    depend on abstractions (LoggingPort), not concretions (StructuredLogger).
    """

    def __init__(self, logger: StructuredLogger | None = None):
        """
        Initialize the logging adapter.

        Args:
            logger: An existing StructuredLogger instance. If None, a new one is created.
        """
        if logger is None and StructuredLogger is not None:
            self._logger = StructuredLogger()
        else:
            self._logger = logger

    def info(self, message: str, **kwargs) -> None:
        """Log an informational message."""
        if self._logger:
            self._logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        """Log a warning message."""
        if self._logger:
            self._logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs) -> None:
        """Log an error message."""
        if self._logger:
            self._logger.error(message, **kwargs)

    def debug(self, message: str, **kwargs) -> None:
        """Log a debug message."""
        if self._logger:
            self._logger.debug(message, **kwargs)

    def critical(self, message: str, **kwargs) -> None:
        """Log a critical message."""
        if self._logger:
            self._logger.critical(message, **kwargs)

    def log_trade(self, trade_data: dict[str, Any]) -> None:
        """Log a trade execution event."""
        if self._logger and hasattr(self._logger, 'log_trade'):
            self._logger.log_trade(trade_data)
        else:
            # Fallback: log as info with trade data
            self.info("Trade executed", **trade_data)

    def log_signal(self, signal_data: dict[str, Any]) -> None:
        """Log a signal generation event."""
        if self._logger and hasattr(self._logger, 'log_signal'):
            self._logger.log_signal(signal_data)
        else:
            # Fallback: log as info with signal data
            self.info("Signal generated", **signal_data)
