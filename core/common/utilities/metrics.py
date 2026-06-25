"""
Metrics Collection Utilities

This module provides utilities for collecting and reporting metrics
throughout the trading system.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricPoint:
    """
    A single metric data point.

    Attributes:
        value: The metric value
        timestamp: When the metric was recorded
        tags: Additional tags/dimensions for the metric
    """
    value: float
    timestamp: float = field(default_factory=time.time)
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class MetricSummary:
    """
    Summary statistics for a metric over a time period.

    Attributes:
        count: Number of data points
        sum: Sum of all values
        min: Minimum value
        max: Maximum value
        mean: Average value
        latest: Most recent value
        timestamp: When this summary was calculated
    """
    count: int = 0
    sum: float = 0.0
    min: float = float('inf')
    max: float = float('-inf')
    mean: float = 0.0
    latest: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        """Calculate derived fields after initialization."""
        if self.count > 0:
            self.mean = self.sum / self.count
        else:
            self.min = 0.0
            self.max = 0.0
            self.mean = 0.0
            self.latest = 0.0


class MetricsCollector:
    """
    Collects and manages metrics for the trading system.

    Provides functionality to:
    - Increment counters
    - Record gauges
    - Record timings
    - Get metric summaries
    - Reset metrics
    """

    def __init__(self):
        """Initialize the metrics collector."""
        self._lock = threading.RLock()
        self._counters: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = defaultdict(float)
        self._histograms: dict[str, list[MetricPoint]] = defaultdict(list)
        self._timings: dict[str, list[float]] = defaultdict(list)

    def increment(self, metric_name: str, value: int = 1, tags: dict[str, str] | None = None) -> None:
        """
        Increment a counter metric.

        Args:
            metric_name: Name of the metric
            value: Amount to increment by (default: 1)
            tags: Optional tags for the metric
        """
        with self._lock:
            self._counters[metric_name] += value

    def gauge(self, metric_name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """
        Set a gauge metric to a specific value.

        Args:
            metric_name: Name of the metric
            value: Value to set the gauge to
            tags: Optional tags for the metric
        """
        with self._lock:
            self._gauges[metric_name] = value

    def record(self, metric_name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """
        Record a histogram metric value.

        Args:
            metric_name: Name of the metric
            value: Value to record
            tags: Optional tags for the metric
        """
        with self._lock:
            self._histograms[metric_name].append(
                MetricPoint(value=value, tags=tags or {})
            )

    def timing(self, metric_name: str, value: float) -> None:
        """
        Record a timing metric.

        Args:
            metric_name: Name of the metric
            value: Time value in milliseconds
        """
        with self._lock:
            self._timings[metric_name].append(value)

    @contextmanager
    def timer(self, metric_name: str):
        """
        Context manager for timing a block of code.

        Args:
            metric_name: Name of the timing metric

        Example:
            with metrics.timer("database.query"):
                # Execute database query
                pass
        """
        start_time = time.time()
        try:
            yield
        finally:
            elapsed_ms = (time.time() - start_time) * 1000
            self.timing(metric_name, elapsed_ms)

    def get_counter(self, metric_name: str) -> int:
        """
        Get the current value of a counter.

        Args:
            metric_name: Name of the metric

        Returns:
            Current counter value
        """
        with self._lock:
            return self._counters.get(metric_name, 0)

    def get_gauge(self, metric_name: str) -> float:
        """
        Get the current value of a gauge.

        Args:
            metric_name: Name of the metric

        Returns:
            Current gauge value
        """
        with self._lock:
            return self._gauges.get(metric_name, 0.0)

    def get_histogram_summary(self, metric_name: str) -> MetricSummary:
        """
        Get summary statistics for a histogram metric.

        Args:
            metric_name: Name of the metric

        Returns:
            Summary statistics for the metric
        """
        with self._lock:
            points = self._histograms.get(metric_name, [])
            if not points:
                return MetricSummary()

            values = [p.value for p in points]
            return MetricSummary(
                count=len(values),
                sum=sum(values),
                min=min(values),
                max=max(values),
                latest=values[-1] if values else 0.0
            )

    def get_timing_summary(self, metric_name: str) -> MetricSummary:
        """
        Get summary statistics for a timing metric.

        Args:
            metric_name: Name of the metric

        Returns:
            Summary statistics for the timing
        """
        with self._lock:
            times = self._timings.get(metric_name, [])
            if not times:
                return MetricSummary()

            return MetricSummary(
                count=len(times),
                sum=sum(times),
                min=min(times),
                max=max(times),
                latest=times[-1] if times else 0.0
            )

    def get_all_metrics(self) -> dict[str, Any]:
        """
        Get all current metrics.

        Returns:
            Dictionary containing all metrics by type
        """
        with self._lock:
            return {
                'counters': dict(self._counters),
                'gauges': dict(self._gauges),
                'histograms': {
                    name: self.get_histogram_summary(name)
                    for name in self._histograms.keys()
                },
                'timings': {
                    name: self.get_timing_summary(name)
                    for name in self._timings.keys()
                }
            }

    def reset(self) -> None:
        """Reset all metrics to their initial state."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._timings.clear()

    # Decorator for timing functions
    def timed(self, metric_name: str):
        """
        Decorator to time a function.

        Args:
            metric_name: Name of the timing metric

        Returns:
            Decorated function
        """
        def decorator(func: Callable) -> Callable:
            def wrapper(*args, **kwargs):
                with self.timer(metric_name):
                    return func(*args, **kwargs)
            return wrapper
        return decorator


# Global metrics collector instance
metrics_collector = MetricsCollector()


# Convenience functions
def increment_counter(metric_name: str, value: int = 1) -> None:
    """Increment a counter metric (convenience function)."""
    metrics_collector.increment(metric_name, value)


def set_gauge(metric_name: str, value: float) -> None:
    """Set a gauge metric (convenience function)."""
    metrics_collector.gauge(metric_name, value)


def record_metric(metric_name: str, value: float) -> None:
    """Record a histogram metric (convenience function)."""
    metrics_collector.record(metric_name, value)


def time_operation(metric_name: str, value: float) -> None:
    """Record a timing metric (convenience function)."""
    metrics_collector.timing(metric_name, value)


def get_metric(metric_name: str) -> Any:
    """
    Get a metric value (convenience function).

    Args:
        metric_name: Name of the metric

    Returns:
        The metric value (type depends on metric type)
    """
    # Try as counter first
    value = metrics_collector.get_counter(metric_name)
    if value != 0 or metric_name in metrics_collector._counters:
        return value

    # Try as gauge
    value = metrics_collector.get_gauge(metric_name)
    if value != 0.0 or metric_name in metrics_collector._gauges:
        return value

    # Try as histogram
    summary = metrics_collector.get_histogram_summary(metric_name)
    if summary.count > 0:
        return summary

    # Try as timing
    summary = metrics_collector.get_timing_summary(metric_name)
    if summary.count > 0:
        return summary

    return None


__all__ = [
    "MetricPoint",
    "MetricSummary",
    "MetricsCollector",
    "get_metric",
    "increment_counter",
    "metrics_collector",
    "record_metric",
    "set_gauge",
    "time_operation",
]

