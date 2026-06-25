"""
Logging Port Interface

This interface defines the contract for structured logging.
It decouples the trading logic from specific logging implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LoggingPort(ABC):
    """
    Abstract base class defining the logging interface.

    All logging implementations must implement this interface.
    This enables the trading logic to remain logging provider-agnostic.
    """

    @abstractmethod
    def info(self, message: str, **kwargs) -> None:
        """
        Log an informational message.

        Args:
            message: The log message
            **kwargs: Additional context fields to include in the log
        """
        pass

    @abstractmethod
    def warning(self, message: str, **kwargs) -> None:
        """
        Log a warning message.

        Args:
            message: The log message
            **kwargs: Additional context fields to include in the log
        """
        pass

    @abstractmethod
    def error(self, message: str, **kwargs) -> None:
        """
        Log an error message.

        Args:
            message: The log message
            **kwargs: Additional context fields to include in the log
        """
        pass

    @abstractmethod
    def debug(self, message: str, **kwargs) -> None:
        """
        Log a debug message.

        Args:
            message: The log message
            **kwargs: Additional context fields to include in the log
        """
        pass

    @abstractmethod
    def critical(self, message: str, **kwargs) -> None:
        """
        Log a critical message.

        Args:
            message: The log message
            **kwargs: Additional context fields to include in the log
        """
        pass

    @abstractmethod
    def log_trade(self, trade_data: dict[str, Any]) -> None:
        """
        Log a trade execution event.

        Args:
            trade_data: Dictionary containing trade information
        """
        pass

    @abstractmethod
    def log_signal(self, signal_data: dict[str, Any]) -> None:
        """
        Log a signal generation event.

        Args:
            signal_data: Dictionary containing signal information
        """
        pass


__all__ = [
    "LoggingPort",
]

