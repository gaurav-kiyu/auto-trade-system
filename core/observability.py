import time
import logging
from typing import Dict, Any, Optional

try:
    from prometheus_client import start_http_server, Counter, Gauge, Histogram, Summary
    _prometheus_available = True
except ImportError:
    _prometheus_available = False

    def start_http_server(port: int):
        return None

    class _NoOpMetric:
        def __init__(self, *args, **kwargs):
            pass

        def labels(self, *args, **kwargs):
            return self

        def set(self, value):
            return None

        def inc(self, amount: int = 1):
            return None

        def observe(self, value):
            return None

    Counter = Gauge = Histogram = Summary = _NoOpMetric

log = logging.getLogger("observability")

# ═══════════════════════════════════════════════════════════════
# METRICS DEFINITIONS
# ═══════════════════════════════════════════════════════════════

# Execution Latency: Signal -> Order Submission
ORDER_LATENCY = Histogram(
    "opb_order_latency_seconds", 
    "Time from signal generation to broker submission",
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0)
)

# Slippage: Expected Price vs Actual Fill Price
ORDER_SLIPPAGE = Gauge(
    "opb_order_slippage_pct", 
    "Percentage slippage on last filled order",
    ["symbol", "direction"]
)

# System Health
BROKER_HEALTH = Gauge(
    "opb_broker_health_status", 
    "Broker connectivity status (1=Healthy, 0=Down)",
    ["broker_name"]
)

ML_FALLBACK_COUNT = Counter(
    "opb_ml_fallback_total", 
    "Number of times ML engine triggered fallback logic"
)

# Risk Metrics
DAILY_PNL = Gauge(
    "opb_daily_pnl_amount", 
    "Current realized + unrealized daily PnL"
)

RISK_LIMIT_PROXIMITY = Gauge(
    "opb_risk_limit_proximity_pct", 
    "How close the system is to the daily loss limit (0-100%)"
)

class ObservabilityManager:
    """
    Central hub for system monitoring.
    Integrates Prometheus metrics and structured logging.
    """
    
    def __init__(self, port: int = 9090):
        self.port = port
        self._server_started = False

    def start_metrics_server(self):
        """Starts the Prometheus HTTP server."""
        try:
            start_http_server(self.port)
            self._server_started = True
            log.info(f"Prometheus metrics server started on port {self.port}")
        except Exception as e:
            log.error(f"Failed to start Prometheus server: {e}")

    def record_order_latency(self, start_time: float):
        """Records the time taken to execute an order."""
        latency = time.time() - start_time
        ORDER_LATENCY.observe(latency)

    def record_slippage(self, symbol: str, direction: str, expected: float, actual: float):
        """Calculates and records slippage percentage."""
        if expected == 0: return
        slip = abs(actual - expected) / expected * 100
        ORDER_SLIPPAGE.labels(symbol=symbol, direction=direction).set(slip)

    def update_broker_health(self, broker_name: str, is_healthy: bool):
        BROKER_HEALTH.labels(broker_name=broker_name).set(1 if is_healthy else 0)

    def increment_ml_fallback(self):
        ML_FALLBACK_COUNT.inc()

    def update_risk_metrics(self, current_pnl: float, max_loss: float):
        DAILY_PNL.set(current_pnl)
        # Calculate proximity: (Current PnL - Max Loss) / |Max Loss|
        # If PnL is -1000 and Max Loss is -5000, proximity is 80%
        if max_loss == 0: return
        proximity = (current_pnl - max_loss) / abs(max_loss) * 100
        RISK_LIMIT_PROXIMITY.set(max(0, min(100, proximity)))

# Singleton instance
obs_manager = ObservabilityManager()
