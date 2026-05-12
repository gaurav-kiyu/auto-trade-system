"""
Metrics Port Interface

This interface defines the contract for metrics collection.
It decouples the trading logic from specific metrics implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class MetricsPort(ABC):
    """
    Abstract base class defining the metrics interface.

    All metrics implementations must implement this interface.
    This enables the trading logic to remain metrics provider-agnostic.
    """

    @abstractmethod
    def increment_counter(self, name: str, value: int = 1, tags: dict[str, str] | None = None) -> None:
        """
        Increment a counter metric.

        Args:
            name: Metric name
            value: Value to increment by
            tags: Optional tags for dimensional metrics
        """
        pass

    @abstractmethod
    def set_gauge(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """
        Set a gauge metric.

        Args:
            name: Metric name
            value: Current value
            tags: Optional tags for dimensional metrics
        """
        pass

    @abstractmethod
    def record_timer(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """
        Record a timing metric.

        Args:
            name: Metric name
            value: Elapsed time in seconds
            tags: Optional tags for dimensional metrics
        """
        pass

    @abstractmethod
    def record_histogram(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """
        Record a histogram metric.

        Args:
            name: Metric name
            value: Value to record
            tags: Optional tags for dimensional metrics
        """
        pass
