"""Metrics platform — centralized metrics collection and export."""

from core.metrics.metrics_platform import (
    Metric,
    MetricsPlatform,
    TimerMetric,
    get_metrics_platform,
)

__all__ = [
    "Metric",
    "MetricsPlatform",
    "TimerMetric",
    "get_metrics_platform",
]
