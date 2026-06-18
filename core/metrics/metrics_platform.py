"""
Metrics Platform - Item 17

Real observability for the trading system:
- order latency
- fill latency
- reject %
- stale quote %
- retry count
- reconciliation drift
- broker uptime
- PnL attribution

Enables production-grade monitoring.
"""
from __future__ import annotations

import logging
import sqlite3
import threading

from core.db_utils import get_connection
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from core.time_provider import time_provider

_log = logging.getLogger(__name__)


@dataclass
class Metric:
    """Single metric value"""
    name: str
    value: float
    timestamp: str
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class TimerMetric:
    """Timer metric for latencies"""
    name: str
    start_time: float
    end_time: float | None = None
    tags: dict[str, str] = field(default_factory=dict)

    def stop(self) -> float:
        """Stop timer and return duration"""
        self.end_time = time.time()
        return self.end_time - self.start_time


class MetricsPlatform:
    """
    Production metrics and observability platform.
    Tracks all operational metrics for monitoring and alerting.
    """

    PERSISTENCE_PATH = "metrics.db"
    MAX_IN_MEMORY = 10000

    def __init__(self):
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._timers: dict[str, TimerMetric] = {}
        self._lock = threading.RLock()
        self._start_time = time.time()
        self._init_durable_storage()

    def _init_durable_storage(self) -> None:
        """Initialize metrics storage"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT,
                        value REAL,
                        timestamp TEXT,
                        tags_json TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS latency_metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        operation TEXT,
                        duration_ms REAL,
                        timestamp TEXT,
                        success INTEGER
                    )
                """)
                conn.execute("CREATE INDEX idx_metric_name ON metrics(name)")
                conn.execute("CREATE INDEX idx_metric_time ON metrics(timestamp)")
                conn.commit()
            _log.info("MetricsPlatform: Storage initialized")
        except Exception as e:
            _log.error(f"MetricsPlatform: Failed to init storage: {e} (type: {type(e).__name__})")

    def increment(self, name: str, value: float = 1.0, tags: dict[str, str] = None) -> None:
        """Increment counter"""
        with self._lock:
            key = self._make_key(name, tags)
            self._counters[key] += value

    def decrement(self, name: str, value: float = 1.0, tags: dict[str, str] = None) -> None:
        """Decrement counter"""
        with self._lock:
            key = self._make_key(name, tags)
            self._counters[key] -= value

    def gauge(self, name: str, value: float, tags: dict[str, str] = None) -> None:
        """Set gauge value"""
        with self._lock:
            key = self._make_key(name, tags)
            self._gauges[key] = value

    def histogram(self, name: str, value: float, tags: dict[str, str] = None) -> None:
        """Add to histogram"""
        with self._lock:
            key = self._make_key(name, tags)
            self._histograms[key].append(value)

    def start_timer(self, name: str, tags: dict[str, str] = None) -> TimerMetric:
        """Start a timer"""
        timer = TimerMetric(
            name=name,
            start_time=time.time(),
            tags=tags or {},
        )
        with self._lock:
            self._timers[id(timer)] = timer
        return timer

    def stop_timer(self, timer: TimerMetric) -> float:
        """Stop timer and record"""
        duration = timer.stop()
        ms = duration * 1000

        with self._lock:
            key = self._make_key(timer.name, timer.tags)
            self._histograms[key].append(ms)

            if id(timer) in self._timers:
                del self._timers[id(timer)]

        self._record_latency(timer.name, ms, True)
        return ms

    def record_latency(self, operation: str, duration_ms: float, success: bool = True) -> None:
        """Record latency metric"""
        self._record_latency(operation, duration_ms, success)

    def _record_latency(self, operation: str, duration_ms: float, success: bool) -> None:
        """Internal latency recording"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    INSERT INTO latency_metrics (operation, duration_ms, timestamp, success)
                    VALUES (?, ?, ?, ?)
                """, (
                    operation,
                    duration_ms,
                    time_provider.format_ts(),
                    1 if success else 0,
                ))
                conn.commit()
        except Exception as e:
            _log.error(f"Failed to record latency: {e} (type: {type(e).__name__})")

    def get_counter(self, name: str, tags: dict[str, str] = None) -> float:
        """Get counter value"""
        with self._lock:
            return self._counters.get(self._make_key(name, tags), 0.0)

    def get_gauge(self, name: str, tags: dict[str, str] = None) -> float | None:
        """Get gauge value"""
        with self._lock:
            return self._gauges.get(self._make_key(name, tags))

    def get_histogram_stats(self, name: str, tags: dict[str, str] = None) -> dict[str, float]:
        """Get histogram statistics"""
        with self._lock:
            key = self._make_key(name, tags)
            values = list(self._histograms.get(key, []))

            if not values:
                return {"count": 0, "min": 0, "max": 0, "mean": 0, "p50": 0, "p95": 0, "p99": 0}

            sorted_vals = sorted(values)
            n = len(sorted_vals)

            return {
                "count": n,
                "min": sorted_vals[0],
                "max": sorted_vals[-1],
                "mean": sum(sorted_vals) / n,
                "p50": sorted_vals[n // 2],
                "p95": sorted_vals[int(n * 0.95)],
                "p99": sorted_vals[int(n * 0.99)],
            }

    def get_all_metrics(self) -> dict[str, Any]:
        """Get all current metrics"""
        with self._lock:
            uptime = time.time() - self._start_time

            return {
                "uptime_seconds": uptime,
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    name: self.get_histogram_stats(name)
                    for name in self._histograms.keys()
                },
            }

    def get_latency_stats(self, operation: str, limit: int = 1000) -> dict[str, float]:
        """Get latency statistics for operation"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                cursor = conn.execute("""
                    SELECT duration_ms FROM latency_metrics
                    WHERE operation = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (operation, limit))

                values = [row[0] for row in cursor]

                if not values:
                    return {"count": 0, "min": 0, "max": 0, "mean": 0, "p50": 0, "p95": 0, "p99": 0}

                sorted_vals = sorted(values)
                n = len(sorted_vals)

                return {
                    "count": n,
                    "min": sorted_vals[0],
                    "max": sorted_vals[-1],
                    "mean": sum(sorted_vals) / n,
                    "p50": sorted_vals[n // 2],
                    "p95": sorted_vals[int(n * 0.95)],
                    "p99": sorted_vals[min(int(n * 0.99), n - 1)],
                }
        except Exception as e:
            _log.error(f"Failed to get latency stats: {e} (type: {type(e).__name__})")
            return {}

    def get_reject_rate(self) -> float:
        """Calculate reject rate"""
        with self._lock:
            rejected = self._counters.get("orders.rejected", 0)
            submitted = self._counters.get("orders.submitted", 1)
            return rejected / submitted if submitted > 0 else 0

    def get_success_rate(self) -> float:
        """Calculate success rate"""
        return 1.0 - self.get_reject_rate()

    def reset(self) -> None:
        """Reset all metrics"""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            _log.info("Metrics reset")

    def _make_key(self, name: str, tags: dict[str, str] = None) -> str:
        """Make metric key with tags"""
        if not tags:
            return name
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name}[{tag_str}]"


_metrics_platform: MetricsPlatform | None = None
_metrics_lock = threading.RLock()


def get_metrics_platform() -> MetricsPlatform:
    """Get singleton metrics platform"""
    global _metrics_platform
    with _metrics_lock:
        if _metrics_platform is None:
            _metrics_platform = MetricsPlatform()
        return _metrics_platform
