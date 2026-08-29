"""Prometheus Metrics / API Monitoring for the Real Estate Platform.

Provides:
  - Request counters (total, by endpoint, by status code)
  - Latency histograms (p50, p95, p99 response times)
  - Business metrics (property views, leads created, enquiries, bookings)
  - Active user tracking
  - Health check endpoint for Docker/k8s
  - Prometheus /metrics endpoint (reuses existing core.metrics_exporter pattern)

Integration with FastAPI as middleware and as a standalone router.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

_log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Metrics Registry (in-memory, suitable for single-instance deployments)
# ═══════════════════════════════════════════════════════════════════════════════

class PrometheusMetrics:
    """In-memory Prometheus-compatible metrics registry.

    Exposes counters, gauges, and histograms via a /metrics endpoint
    in Prometheus text format. Designed for single-instance deployments.
    """

    def __init__(self) -> None:
        # Counters
        self._counters: dict[str, float] = defaultdict(float)
        self._counter_labels: dict[str, dict[str, str]] = {}

        # Gauges
        self._gauges: dict[str, float] = defaultdict(float)

        # Histograms
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._histogram_buckets: dict[str, list[float]] = {}

    # ── Counter Operations ────────────────────────────────────────────────

    def inc_counter(self, name: str, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """Increment a counter metric."""
        key = self._label_key(name, labels or {})
        self._counters[key] += value
        if labels:
            self._counter_labels[key] = labels

    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> float:
        """Get current counter value."""
        return self._counters.get(self._label_key(name, labels or {}), 0.0)

    # ── Gauge Operations ──────────────────────────────────────────────────

    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge metric to a specific value."""
        self._gauges[name] = value

    def inc_gauge(self, name: str, value: float = 1.0) -> None:
        """Increment a gauge metric."""
        self._gauges[name] += value

    def dec_gauge(self, name: str, value: float = 1.0) -> None:
        """Decrement a gauge metric."""
        self._gauges[name] -= value

    def get_gauge(self, name: str) -> float:
        """Get current gauge value."""
        return self._gauges.get(name, 0.0)

    # ── Histogram Operations ──────────────────────────────────────────────

    def observe_histogram(self, name: str, value: float,
                          buckets: list[float] | None = None) -> None:
        """Observe a value for histogram tracking."""
        self._histograms[name].append(value)
        if buckets:
            self._histogram_buckets[name] = buckets

    def get_histogram(self, name: str) -> dict[str, Any]:
        """Get histogram stats (count, sum, p50, p95, p99)."""
        values = sorted(self._histograms.get(name, []))
        if not values:
            return {"count": 0, "sum": 0.0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0}

        n = len(values)
        total = sum(values)
        return {
            "count": n,
            "sum": round(total, 3),
            "avg": round(total / n, 3),
            "p50": round(self._percentile(values, 50), 3),
            "p95": round(self._percentile(values, 95), 3),
            "p99": round(self._percentile(values, 99), 3),
        }

    # ── Prometheus Text Format Export ──────────────────────────────────────

    def export_text(self) -> str:
        """Export all metrics in Prometheus text format."""
        lines: list[str] = []
        lines.append("# Real Estate Platform Metrics")
        lines.append(f"# Generated {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")

        # Counters
        for key, value in sorted(self._counters.items()):
            name, labels = self._parse_label_key(key)
            if labels:
                label_str = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
                lines.append(f"# HELP {name} Counter metric")
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name}{label_str} {value}")
            else:
                lines.append(f"# HELP {name} Counter metric")
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name} {value}")

        # Gauges
        for name, value in sorted(self._gauges.items()):
            lines.append(f"# HELP {name} Gauge metric")
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")

        # Histograms
        for name, values in sorted(self._histograms.items()):
            lines.append(f"# HELP {name} Histogram metric")
            lines.append(f"# TYPE {name} histogram")
            sorted_vals = sorted(values)
            buckets = self._histogram_buckets.get(name, [0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0])
            cum_count = 0
            for b in buckets:
                cum_count += sum(1 for v in sorted_vals if v <= b) - cum_count
                actual_count = sum(1 for v in sorted_vals if v <= b)
                lines.append(f"{name}_bucket{{le=\"{b}\"}} {actual_count}")
            lines.append(f"{name}_bucket{{le=\"+Inf\"}} {len(sorted_vals)}")
            lines.append(f"{name}_count {len(sorted_vals)}")
            lines.append(f"{name}_sum {sum(sorted_vals)}")

        return "\n".join(lines)

    # ── Utility ───────────────────────────────────────────────────────────

    @staticmethod
    def _percentile(sorted_values: list[float], percentile: float) -> float:
        """Calculate the given percentile from a sorted list."""
        if not sorted_values:
            return 0.0
        n = len(sorted_values)
        k = (percentile / 100.0) * (n - 1)
        f = int(k)
        c = f + 1
        if c >= n:
            return sorted_values[-1]
        return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])

    @staticmethod
    def _label_key(name: str, labels: dict[str, str]) -> str:
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}[{label_str}]"

    @staticmethod
    def _parse_label_key(key: str) -> tuple[str, str | None]:
        if "[" in key and key.endswith("]"):
            name = key.split("[")[0]
            labels_str = key[key.index("[") + 1:-1]
            labels_dict = {}
            for pair in labels_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    labels_dict[k] = v
            return name, ("," + ",".join(f'{k}="{v}"' for k, v in labels_dict.items())) if labels_dict else None
        return key, None


# Global metrics registry
_metrics = PrometheusMetrics()


# ═══════════════════════════════════════════════════════════════════════════════
# Metrics Middleware — Auto-track HTTP request metrics
# ═══════════════════════════════════════════════════════════════════════════════

class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware that records HTTP request metrics for Prometheus.

    Tracks:
      - Total requests (by endpoint, method, status)
      - Request latency (histogram)
      - Active requests (gauge)
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        path = request.url.path
        method = request.method

        # Skip /metrics itself to avoid recursion
        if path == "/metrics":
            return await call_next(request)

        # Track active requests
        _metrics.inc_gauge("re_http_active_requests", 1.0)

        start = time.time()
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception:
            status = 500
            raise
        finally:
            elapsed = time.time() - start
            labels = {"method": method, "endpoint": path, "status": str(status)}

            _metrics.inc_counter("re_http_requests_total", 1.0, labels)
            _metrics.observe_histogram("re_http_request_duration_seconds", elapsed,
                                       buckets=[0.01, 0.05, 0.1, 0.3, 0.5, 1.0, 2.0, 5.0])
            _metrics.dec_gauge("re_http_active_requests", 1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Business Metrics — Track real estate-specific KPIs
# ═══════════════════════════════════════════════════════════════════════════════

class BusinessMetrics:
    """Tracks business-specific KPIs for the real estate platform.

    Compatible with PrometheusMetrics export.
    """

    def __init__(self) -> None:
        self._metrics = _metrics

    # ── Property Metrics ──────────────────────────────────────────────────

    def record_property_view(self, property_id: str, city: str = "") -> None:
        self._metrics.inc_counter("re_property_views_total", 1.0,
                                  {"city": city or "unknown"})

    def record_property_listed(self, city: str = "", property_type: str = "") -> None:
        self._metrics.inc_counter("re_property_listings_total", 1.0,
                                  {"city": city or "unknown", "type": property_type or "unknown"})

    # ── Lead / Enquiry Metrics ────────────────────────────────────────────

    def record_enquiry(self, city: str = "") -> None:
        self._metrics.inc_counter("re_enquiries_total", 1.0, {"city": city or "unknown"})

    def record_lead_conversion(self, source: str = "") -> None:
        self._metrics.inc_counter("re_lead_conversions_total", 1.0,
                                  {"source": source or "unknown"})

    # ── User Metrics ──────────────────────────────────────────────────────

    def set_active_users(self, count: int) -> None:
        self._metrics.set_gauge("re_active_users", float(count))

    def record_user_registration(self) -> None:
        self._metrics.inc_counter("re_user_registrations_total", 1.0)

    def record_user_login(self) -> None:
        self._metrics.inc_counter("re_user_logins_total", 1.0)

    # ── Payment Metrics ───────────────────────────────────────────────────

    def record_payment(self, amount: float, status: str = "success") -> None:
        self._metrics.inc_counter("re_payments_total", 1.0, {"status": status})
        self._metrics.observe_histogram("re_payment_amount", amount)

    def record_revenue(self, amount: float) -> None:
        self._metrics.inc_counter("re_revenue_total", amount)

    # ── Notification Metrics ──────────────────────────────────────────────

    def record_notification_sent(self, channel: str = "") -> None:
        self._metrics.inc_counter("re_notifications_sent_total", 1.0,
                                  {"channel": channel or "unknown"})

    # ── Fraud Metrics ─────────────────────────────────────────────────────

    def record_fraud_check(self, result: str = "pass") -> None:
        self._metrics.inc_counter("re_fraud_checks_total", 1.0, {"result": result})

    # ── Get Active Metrics ────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get a snapshot of current business metrics."""
        return {
            "total_requests": self._metrics.get_counter("re_http_requests_total"),
            "property_views": self._metrics.get_counter("re_property_views_total"),
            "property_listings": self._metrics.get_counter("re_property_listings_total"),
            "enquiries": self._metrics.get_counter("re_enquiries_total"),
            "lead_conversions": self._metrics.get_counter("re_lead_conversions_total"),
            "payments": self._metrics.get_counter("re_payments_total"),
            "revenue": self._metrics.get_counter("re_revenue_total"),
            "active_users": self._metrics.get_gauge("re_active_users"),
            "fraud_checks": self._metrics.get_counter("re_fraud_checks_total"),
            "latency": self._metrics.get_histogram("re_http_request_duration_seconds"),
        }


# ── Singleton ───────────────────────────────────────────────────────────────

_business_metrics_instance: BusinessMetrics | None = None


def get_business_metrics() -> BusinessMetrics:
    global _business_metrics_instance
    if _business_metrics_instance is None:
        _business_metrics_instance = BusinessMetrics()
    return _business_metrics_instance


# ═══════════════════════════════════════════════════════════════════════════════
# Health Check
# ═══════════════════════════════════════════════════════════════════════════════

def get_health_status() -> dict[str, Any]:
    """Get comprehensive health status for the real estate platform.

    Used by Docker health checks, k8s liveness/readiness probes.
    """
    status = "healthy"
    checks: dict[str, Any] = {}

    # Basic system check
    checks["system"] = {"status": "ok"}

    # Memory (rough estimate)
    try:
        import psutil
        mem = psutil.virtual_memory()
        checks["memory"] = {
            "status": "ok" if mem.percent < 90 else "degraded",
            "percent_used": mem.percent,
            "available_mb": round(mem.available / 1024 / 1024, 1),
        }
    except ImportError:
        checks["memory"] = {"status": "unknown"}

    # Disk
    try:
        import os
        import shutil
        usage = shutil.disk_usage(os.getcwd())
        pct = round(usage.used / usage.total * 100, 1)
        checks["disk"] = {
            "status": "ok" if pct < 90 else "degraded",
            "percent_used": pct,
            "free_gb": round(usage.free / 1024 / 1024 / 1024, 1),
        }
    except Exception:
        checks["disk"] = {"status": "unknown"}

    if any(c.get("status") == "degraded" for c in checks.values()):
        status = "degraded"

    return {
        "status": status,
        "service": "realestate-platform",
        "timestamp": time.time(),
        "checks": checks,
        "uptime_seconds": time.time() - _START_TIME,
    }


_START_TIME = time.time()


# ═══════════════════════════════════════════════════════════════════════════════
# API Router
# ═══════════════════════════════════════════════════════════════════════════════

def create_monitoring_router() -> Any:
    """Create FastAPI router for monitoring endpoints."""
    from fastapi import APIRouter

    router = APIRouter(tags=["Real Estate Monitoring"])

    @router.get("/metrics", response_class=PlainTextResponse)
    async def prometheus_metrics():
        """Prometheus metrics endpoint in text format."""
        return PlainTextResponse(
            content=_metrics.export_text(),
            media_type="text/plain; version=0.0.4",
        )

    @router.get("/api/realestate/health")
    async def health_check():
        """Health check endpoint for Docker/k8s probes."""
        health = get_health_status()
        status_code = 200 if health["status"] == "healthy" else 503
        return JSONResponse(content=health, status_code=status_code)

    @router.get("/api/realestate/metrics/stats")
    async def metrics_stats():
        """Get current business metrics snapshot (for dashboard)."""
        return get_business_metrics().get_stats()

    return router


# ═══════════════════════════════════════════════════════════════════════════════
# Apply Monitoring to FastAPI App
# ═══════════════════════════════════════════════════════════════════════════════

def apply_monitoring(app: FastAPI) -> FastAPI:
    """Apply monitoring middleware and routes to the FastAPI app."""
    # Add metrics middleware (order: after rate limiting, before everything else)
    app.add_middleware(MetricsMiddleware)

    # Add monitoring router
    router = create_monitoring_router()
    app.include_router(router)

    _log.info("[MON] Prometheus metrics, health check, and monitoring middleware applied")
    return app
