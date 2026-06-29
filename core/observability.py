import logging
import time

__all__ = [
    "BROKER_HEALTH",
    "BROKER_UPTIME",
    "DAILY_PNL",
    "ML_FALLBACK_COUNT",
    "ORDER_ACK_LATENCY",
    "ORDER_FILL_LATENCY",
    "ORDER_LATENCY",
    "ORDER_SLIPPAGE",
    "ObservabilityManager",
    "RECONCILIATION_LAG",
    "RISK_LIMIT_PROXIMITY",
    "log",
    "obs_manager",
]

try:
    from prometheus_client import Counter, Gauge, Histogram, Summary, start_http_server
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

# Order Lifecycle Latency: Submission -> ACK
ORDER_ACK_LATENCY = Histogram(
    "opb_order_ack_latency_seconds",
    "Time from order submission to broker ACK",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0)
)

# Order Lifecycle Latency: ACK -> Fill
ORDER_FILL_LATENCY = Histogram(
    "opb_order_fill_latency_seconds",
    "Time from broker ACK to fill confirmation",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)
)

# Reconciliation Lag
RECONCILIATION_LAG = Gauge(
    "opb_reconciliation_lag_seconds",
    "How far behind reconciliation is (seconds since last reconciliation)"
)

# Broker Uptime (seconds since last disconnect or session start)
BROKER_UPTIME = Gauge(
    "opb_broker_uptime_seconds",
    "Seconds since broker last disconnected or session started",
    ["broker_name"]
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
            log.error(f"Failed to start Prometheus server: {e} (type: {type(e).__name__})")

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

    def record_ack_latency(self, start_time: float):
        """Records time from order submission to broker ACK."""
        latency = time.time() - start_time
        ORDER_ACK_LATENCY.observe(latency)

    def record_fill_latency(self, ack_time: float):
        """Records time from broker ACK to fill confirmation."""
        latency = time.time() - ack_time
        ORDER_FILL_LATENCY.observe(latency)

    def set_reconciliation_lag(self, lag_seconds: float):
        """Sets the reconciliation lag gauge."""
        RECONCILIATION_LAG.set(lag_seconds)

    def set_broker_uptime(self, broker_name: str, uptime_seconds: float):
        """Sets broker uptime (seconds since last disconnect)."""
        BROKER_UPTIME.labels(broker_name=broker_name).set(uptime_seconds)

# Singleton instance
obs_manager = ObservabilityManager()
