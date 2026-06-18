"""
AD-KIYU Telemetry - SRE-grade metrics collection.

Metric domains:
  - Execution: submit/ACK/fill latencies, retry count, reject %
  - Market: data freshness, feed gaps, stale incidents
  - Risk: throttle activations, violations, current exposure
  - AI: drift alerts, model degradation scores
  - Ops: reconciliation lag, broker uptime, incident frequency
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class MetricBucket:
    """Rolling-window metric bucket with count/sum/min/max."""
    count: int = 0
    sum: float = 0.0
    min_val: float = float("inf")
    max_val: float = float("-inf")
    last: float = 0.0

    @property
    def avg(self) -> float:
        return self.sum / self.count if self.count > 0 else 0.0

    def record(self, value: float) -> None:
        self.count += 1
        self.sum += value
        self.min_val = min(self.min_val, value)
        self.max_val = max(self.max_val, value)
        self.last = value


@dataclass
class CounterMetric:
    """Monotonically increasing counter."""
    value: int = 0
    ts: float = field(default_factory=time.time)


class MetricsCollector:
    """Thread-safe metrics collector with domain-specific buckets."""

    def __init__(self):
        self._lock = threading.RLock()
        # Execution metrics
        self.order_submit_latency = MetricBucket()
        self.order_ack_latency = MetricBucket()
        self.order_fill_latency = MetricBucket()
        self.order_retry_count = CounterMetric()
        self.order_reject_count = CounterMetric()
        self.order_submit_count = CounterMetric()
        self.order_fill_count = CounterMetric()
        # Market metrics
        self.data_freshness_lag = MetricBucket()
        self.feed_gap_count = CounterMetric()
        self.stale_data_incidents = CounterMetric()
        # Risk metrics
        self.throttle_activations = CounterMetric()
        self.risk_violations = CounterMetric()
        self.current_exposure: float = 0.0
        # AI metrics
        self.drift_alerts = CounterMetric()
        self.model_degradation_score: float = 0.0
        # Ops metrics
        self.reconciliation_lag = MetricBucket()
        self.broker_uptime: float = 100.0
        self.incident_count = CounterMetric()
        # Custom dimensioned metrics
        self._dimensioned: dict[str, MetricBucket] = {}

    # ── Execution ─────────────────────────────────────────────────────────

    def record_order_submit(self) -> None:
        with self._lock:
            self.order_submit_count.value += 1

    def record_order_ack(self, latency_ms: float) -> None:
        with self._lock:
            self.order_ack_latency.record(latency_ms)

    def record_order_fill(self, latency_ms: float) -> None:
        with self._lock:
            self.order_fill_count.value += 1
            self.order_fill_latency.record(latency_ms)

    def record_order_reject(self) -> None:
        with self._lock:
            self.order_reject_count.value += 1

    def record_retry(self) -> None:
        with self._lock:
            self.order_retry_count.value += 1

    @property
    def reject_rate(self) -> float:
        with self._lock:
            total = self.order_submit_count.value
            if total == 0:
                return 0.0
            return self.order_reject_count.value / total * 100.0

    # ── Market ─────────────────────────────────────────────────────────────

    def record_data_freshness(self, lag_seconds: float) -> None:
        with self._lock:
            self.data_freshness_lag.record(lag_seconds)

    def record_feed_gap(self) -> None:
        with self._lock:
            self.feed_gap_count.value += 1

    def record_stale_data(self) -> None:
        with self._lock:
            self.stale_data_incidents.value += 1

    # ── Risk ───────────────────────────────────────────────────────────────

    def record_throttle(self) -> None:
        with self._lock:
            self.throttle_activations.value += 1

    def record_risk_violation(self) -> None:
        with self._lock:
            self.risk_violations.value += 1

    def set_exposure(self, amount: float) -> None:
        with self._lock:
            self.current_exposure = amount

    # ── AI ─────────────────────────────────────────────────────────────────

    def record_drift_alert(self) -> None:
        with self._lock:
            self.drift_alerts.value += 1

    def set_model_degradation(self, score: float) -> None:
        with self._lock:
            self.model_degradation_score = score

    # ── Ops ────────────────────────────────────────────────────────────────

    def record_incident(self) -> None:
        with self._lock:
            self.incident_count.value += 1

    def set_broker_uptime(self, pct: float) -> None:
        with self._lock:
            self.broker_uptime = pct

    def record_reconciliation_lag(self, seconds: float) -> None:
        with self._lock:
            self.reconciliation_lag.record(seconds)

    # ── Dimensioned metrics ────────────────────────────────────────────────

    def dimensioned(self, name: str) -> MetricBucket:
        """Get or create a dimensioned metric bucket."""
        with self._lock:
            if name not in self._dimensioned:
                self._dimensioned[name] = MetricBucket()
            return self._dimensioned[name]

    # ── Snapshot ───────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Return a snapshot of all current metrics."""
        with self._lock:
            def b(m: MetricBucket) -> dict:
                return {"count": m.count, "avg": round(m.avg, 3), "min": m.min_val if m.count else 0,
                        "max": m.max_val if m.count else 0, "last": m.last}
            def c(m: CounterMetric) -> dict:
                return {"value": m.value, "ts": m.ts}
            return {
                "execution": {
                    "submit_count": c(self.order_submit_count),
                    "ack_latency_ms": b(self.order_ack_latency),
                    "fill_latency_ms": b(self.order_fill_latency),
                    "rejects": c(self.order_reject_count),
                    "retries": c(self.order_retry_count),
                    "reject_rate_pct": round(self.reject_rate, 2),
                },
                "market": {
                    "freshness_lag_s": b(self.data_freshness_lag),
                    "feed_gaps": c(self.feed_gap_count),
                    "stale_incidents": c(self.stale_data_incidents),
                },
                "risk": {
                    "throttle_activations": c(self.throttle_activations),
                    "violations": c(self.risk_violations),
                    "current_exposure": self.current_exposure,
                },
                "ai": {
                    "drift_alerts": c(self.drift_alerts),
                    "degradation_score": self.model_degradation_score,
                },
                "ops": {
                    "broker_uptime_pct": self.broker_uptime,
                    "incidents": c(self.incident_count),
                    "reconciliation_lag_s": b(self.reconciliation_lag),
                },
                "dimensioned": {k: b(v) for k, v in self._dimensioned.items()},
            }


_collector: MetricsCollector | None = None
_collector_lock = threading.RLock()


def get_metrics_collector() -> MetricsCollector:
    """Singleton accessor for the global metrics collector."""
    global _collector
    if _collector is None:
        with _collector_lock:
            if _collector is None:
                _collector = MetricsCollector()
    return _collector
