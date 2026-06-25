"""
Correlation ID Port Interface

This interface defines the contract for correlation ID management.
It decouples the trading logic from specific correlation ID implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class CorrelationIdPort(ABC):
    """
    Abstract base class defining the correlation ID interface.

    All correlation ID implementations must implement this interface.
    This enables the trading logic to remain correlation ID provider-agnostic.
    """

    @abstractmethod
    def get_correlation_id(self) -> str:
        """
        Get the current correlation ID.

        Returns:
            Current correlation ID for the request/context
        """
        pass

    @abstractmethod
    def set_correlation_id(self, correlation_id: str) -> None:
        """
        Set the correlation ID for the current context.

        Args:
            correlation_id: Correlation ID to set
        """
        pass

    @abstractmethod
    def new_correlation_id(self) -> str:
        """
        Generate a new correlation ID.

        Returns:
            Newly generated correlation ID
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """
        Reset the correlation ID to None/empty.
        """
        pass


__all__ = [
    "CorrelationIdPort",
]

