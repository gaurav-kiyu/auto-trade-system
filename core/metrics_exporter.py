"""
Prometheus Metrics Exporter (v2.45 Item 19).

Exposes bot performance metrics in Prometheus text format on a configurable
HTTP port.  Uses prometheus_client if installed; silently no-ops if not.

Metrics exported
----------------
  opb_trades_total          — counter: total trades since start
  opb_wins_total            — counter: winning trades since start
  opb_pnl_today             — gauge:   today's net P&L
  opb_active_positions      — gauge:   current open positions
  opb_signal_score_last     — gauge:   last signal score
  opb_daily_loss_pct        — gauge:   today's loss as % of capital
  opb_token_refresh_count   — gauge:   cumulative token refresh count
  opb_token_valid           — gauge:   broker token validity (1=valid)
  opb_warmup_active         — gauge:   warm-up mode active (1=active)
  opb_warmup_entries        — gauge:   entries in current warm-up period
  opb_ws_connected          — gauge:   WebSocket connected (1=connected)
  opb_ws_reconnect_count    — gauge:   cumulative WebSocket reconnects

Public API
----------
    start_metrics_server(cfg)                   — start HTTP server in thread
    update_metrics(metrics_dict)                — update gauge/counter values
    get_metrics_text()                          → str  (Prometheus text format)

Config keys
-----------
    metrics_enabled : bool  default false
    metrics_port    : int   default 9090
    metrics_host    : str   default "0.0.0.0"
"""
from __future__ import annotations

import logging
import threading
from typing import Any

_log = logging.getLogger(__name__)

_REGISTRY_LOCK = threading.Lock()
_gauges:   dict[str, Any] = {}
_counters: dict[str, Any] = {}
_prom_ok   = False
_server_started = False


def _init_prometheus() -> bool:
    global _prom_ok, _gauges, _counters
    if _prom_ok:
        return True
    try:
        from prometheus_client import Counter, Gauge
        with _REGISTRY_LOCK:
            if not _prom_ok:
                _gauges = {
                    "pnl_today":          Gauge("opb_pnl_today",          "Today net P&L"),
                    "active_positions":   Gauge("opb_active_positions",   "Open positions"),
                    "signal_score":       Gauge("opb_signal_score_last",  "Last signal score"),
                    "daily_loss_pct":     Gauge("opb_daily_loss_pct",     "Daily loss pct"),
                    "token_refresh_count":Gauge("opb_token_refresh_count","Cumulative token refreshes"),
                    "token_valid":        Gauge("opb_token_valid",        "Broker token validity (1=valid)"),
                    "warmup_active":      Gauge("opb_warmup_active",      "Warm-up mode active (1=active)"),
                    "warmup_entries":     Gauge("opb_warmup_entries",     "Entries in warm-up"),
                    "ws_connected":       Gauge("opb_ws_connected",       "WebSocket connected (1=connected)"),
                    "ws_reconnect_count": Gauge("opb_ws_reconnect_count", "Cumulative WebSocket reconnects"),
                    "reconciliation_lag": Gauge("opb_reconciliation_lag_seconds", "Reconciliation lag in seconds"),
                    "broker_uptime":      Gauge("opb_broker_uptime_seconds",      "Broker uptime in seconds", ["broker_name"]),
                }
                _counters = {
                    "trades_total": Counter("opb_trades_total", "Total trades"),
                    "wins_total":   Counter("opb_wins_total",   "Winning trades"),
                }
                _prom_ok = True
        return True
    except Exception as e:
        _log.debug("[METRICS] prometheus_client not available: %s", e)
        return False


def start_metrics_server(cfg: dict[str, Any] | None = None) -> bool:
    """
    Start the Prometheus HTTP metrics server in a daemon thread.

    Args:
        cfg: config dict.

    Returns:
        True if started, False if disabled or import failure.
    """
    global _server_started
    c = cfg or {}
    if not c.get("metrics_enabled", False):
        return False
    if _server_started:
        return True
    if not _init_prometheus():
        return False

    port = int(c.get("metrics_port", 9090))
    try:
        from prometheus_client import start_http_server
        t = threading.Thread(
            target=start_http_server, args=(port,), daemon=True, name="metrics_server"
        )
        t.start()
        _server_started = True
        _log.info("[METRICS] Prometheus metrics server started on :%d", port)
        return True
    except Exception as e:
        _log.warning("[METRICS] start failed: %s", e)
        return False


def update_hardening_metrics(
    token_refresh_count: int = 0,
    token_valid: bool = False,
    warmup_active: bool = False,
    warmup_entries: int = 0,
    ws_connected: bool = False,
    ws_reconnect_count: int = 0,
) -> None:
    """Update hardening-related Prometheus metrics in one call."""
    if not _prom_ok and not _init_prometheus():
        return
    try:
        _gauges["token_refresh_count"].set(float(token_refresh_count))
        _gauges["token_valid"].set(1.0 if token_valid else 0.0)
        _gauges["warmup_active"].set(1.0 if warmup_active else 0.0)
        _gauges["warmup_entries"].set(float(warmup_entries))
        _gauges["ws_connected"].set(1.0 if ws_connected else 0.0)
        _gauges["ws_reconnect_count"].set(float(ws_reconnect_count))
    except Exception as e:
        _log.debug("[METRICS] update_hardening_metrics failed: %s", e)


def update_metrics(metrics: dict[str, float]) -> None:
    """
    Update Prometheus metrics from a dict.

    Args:
        metrics: dict with keys matching gauge/counter names.
                 e.g. {"pnl_today": 5000.0, "trades_total_inc": 1}
    """
    if not _prom_ok and not _init_prometheus():
        return

    try:
        if "pnl_today" in metrics:
            _gauges["pnl_today"].set(float(metrics["pnl_today"]))
        if "active_positions" in metrics:
            _gauges["active_positions"].set(float(metrics["active_positions"]))
        if "signal_score" in metrics:
            _gauges["signal_score"].set(float(metrics["signal_score"]))
        if "daily_loss_pct" in metrics:
            _gauges["daily_loss_pct"].set(float(metrics["daily_loss_pct"]))
        if "trades_total_inc" in metrics:
            _counters["trades_total"].inc(float(metrics["trades_total_inc"]))
        if "wins_total_inc" in metrics:
            _counters["wins_total"].inc(float(metrics["wins_total_inc"]))
        if "reconciliation_lag" in metrics:
            _gauges["reconciliation_lag"].set(float(metrics["reconciliation_lag"]))
        if "broker_uptime" in metrics:
            value = metrics["broker_uptime"]
            if isinstance(value, (int, float)):
                _gauges["broker_uptime"].labels(broker_name="default").set(float(value))
            elif isinstance(value, dict):
                for broker, uptime in value.items():
                    _gauges["broker_uptime"].labels(broker_name=broker).set(float(uptime))
    except Exception as e:
        _log.debug("[METRICS] update failed: %s", e)


def get_metrics_text() -> str:
    """
    Return current metrics in Prometheus text exposition format.
    Falls back to a plain-text summary if prometheus_client is unavailable.
    """
    try:
        from prometheus_client import generate_latest
        return generate_latest().decode("utf-8")
    except Exception:
        lines = []
        for name, g in _gauges.items():
            try:
                lines.append(f"opb_{name} {g._value.get()}")
            except Exception:
                lines.append(f"opb_{name} 0")
        return "\n".join(lines) or "# no metrics"


# ── MetricsAdapter (Ports/Adapters pattern) ──────────────────────────────────


class MetricsAdapter:
    """Adapter implementing the MetricsPort contract using prometheus_client.

    Wraps the module-level gauge/counter functions in a class that complies
    with the ``core.ports.metrics.MetricsPort`` abstract interface.

    Falls back to no-op silently if prometheus_client is not installed.
    """

    def increment_counter(self, name: str, value: int = 1, tags: dict | None = None) -> None:
        update_metrics({f"{name}_inc": float(value)})

    def set_gauge(self, name: str, value: float, tags: dict | None = None) -> None:
        update_metrics({name: value})

    def record_timer(self, name: str, value: float, tags: dict | None = None) -> None:
        update_metrics({f"{name}_timer": value})

    def record_histogram(self, name: str, value: float, tags: dict | None = None) -> None:
        update_metrics({f"{name}_hist": value})
