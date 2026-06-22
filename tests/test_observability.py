"""Tests for core.observability - Prometheus metrics and system monitoring."""

from __future__ import annotations

from unittest.mock import patch

from core.observability.metrics import (
    BROKER_HEALTH,
    DAILY_PNL,
    ML_FALLBACK_COUNT,
    ORDER_LATENCY,
    ObservabilityManager,
    RISK_LIMIT_PROXIMITY,
    obs_manager,
)


# ── ObservabilityManager construction ───────────────────────────────────

def test_obs_manager_default_port() -> None:
    mgr = ObservabilityManager()
    assert mgr.port == 9090
    assert mgr._server_started is False


def test_obs_manager_custom_port() -> None:
    mgr = ObservabilityManager(port=8080)
    assert mgr.port == 8080


# ── start_metrics_server ─────────────────────────────────────────────────

@patch("core.observability.metrics.start_http_server")
def test_start_metrics_server(mock_start) -> None:
    mgr = ObservabilityManager(port=9999)
    mgr.start_metrics_server()
    assert mgr._server_started is True
    mock_start.assert_called_with(9999)


@patch("core.observability.metrics.start_http_server", side_effect=OSError("port in use"))
def test_start_metrics_server_failure(mock_start) -> None:
    mgr = ObservabilityManager(port=9999)
    mgr.start_metrics_server()
    assert mgr._server_started is False


# ── record_order_latency ─────────────────────────────────────────────────

@patch("core.observability.metrics.ORDER_LATENCY")
def test_record_order_latency(mock_hist) -> None:
    mgr = ObservabilityManager()
    mgr.record_order_latency(100.0)
    # Should call observe with a positive latency
    assert mock_hist.observe.called
    args = mock_hist.observe.call_args[0]
    assert args[0] > 0


# ── record_slippage ──────────────────────────────────────────────────────

@patch("core.observability.metrics.ORDER_SLIPPAGE")
def test_record_slippage(mock_gauge) -> None:
    mgr = ObservabilityManager()
    mgr.record_slippage("NIFTY", "CALL", expected=100.0, actual=101.0)
    assert mock_gauge.labels.called


@patch("core.observability.metrics.ORDER_SLIPPAGE")
def test_record_slippage_zero_expected(mock_gauge) -> None:
    mgr = ObservabilityManager()
    # Should not crash when expected is 0
    mgr.record_slippage("NIFTY", "CALL", expected=0.0, actual=101.0)
    assert not mock_gauge.labels.called


# ── update_broker_health ─────────────────────────────────────────────────

@patch("core.observability.metrics.BROKER_HEALTH")
def test_update_broker_health(mock_gauge) -> None:
    mgr = ObservabilityManager()
    mgr.update_broker_health("KITE", is_healthy=True)
    mock_gauge.labels.assert_called_with(broker_name="KITE")


@patch("core.observability.metrics.BROKER_HEALTH")
def test_update_broker_health_down(mock_gauge) -> None:
    mgr = ObservabilityManager()
    mgr.update_broker_health("KITE", is_healthy=False)
    mock_gauge.labels.assert_called_with(broker_name="KITE")


# ── increment_ml_fallback ───────────────────────────────────────────────

@patch("core.observability.metrics.ML_FALLBACK_COUNT")
def test_increment_ml_fallback(mock_counter) -> None:
    mgr = ObservabilityManager()
    mgr.increment_ml_fallback()
    mock_counter.inc.assert_called_once()


# ── update_risk_metrics ──────────────────────────────────────────────────

@patch("core.observability.metrics.DAILY_PNL")
@patch("core.observability.metrics.RISK_LIMIT_PROXIMITY")
def test_update_risk_metrics(mock_prox, mock_pnl) -> None:
    mgr = ObservabilityManager()
    mgr.update_risk_metrics(current_pnl=-1000.0, max_loss=-5000.0)
    mock_pnl.set.assert_called_with(-1000.0)
    # Proximity = (-1000 - (-5000)) / 5000 * 100 = 80%
    mock_prox.set.assert_called()


@patch("core.observability.metrics.RISK_LIMIT_PROXIMITY")
def test_update_risk_metrics_zero_max_loss(mock_prox) -> None:
    mgr = ObservabilityManager()
    # Should not crash when max_loss is 0
    mgr.update_risk_metrics(current_pnl=-1000.0, max_loss=0.0)
    assert not mock_prox.set.called  # early return


# ── ACK / Fill latency ───────────────────────────────────────────────────

@patch("core.observability.metrics.ORDER_ACK_LATENCY")
def test_record_ack_latency(mock_hist) -> None:
    mgr = ObservabilityManager()
    mgr.record_ack_latency(100.0)
    assert mock_hist.observe.called


@patch("core.observability.metrics.ORDER_FILL_LATENCY")
def test_record_fill_latency(mock_hist) -> None:
    mgr = ObservabilityManager()
    mgr.record_fill_latency(110.0)
    assert mock_hist.observe.called


# ── Reconciliation / Broker uptime ───────────────────────────────────────

@patch("core.observability.metrics.RECONCILIATION_LAG")
def test_set_reconciliation_lag(mock_gauge) -> None:
    mgr = ObservabilityManager()
    mgr.set_reconciliation_lag(5.0)
    mock_gauge.set.assert_called_with(5.0)


@patch("core.observability.metrics.BROKER_UPTIME")
def test_set_broker_uptime(mock_gauge) -> None:
    mgr = ObservabilityManager()
    mgr.set_broker_uptime("KITE", 3600.0)
    mock_gauge.labels.assert_called_with(broker_name="KITE")


# ── Singleton ────────────────────────────────────────────────────────────

def test_obs_manager_singleton() -> None:
    assert isinstance(obs_manager, ObservabilityManager)
    assert obs_manager.port == 9090
