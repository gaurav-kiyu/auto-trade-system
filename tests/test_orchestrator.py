"""Tests for TradingOrchestrator (core.services.use_cases.trading_orchestrator)."""

from __future__ import annotations

from unittest.mock import MagicMock


# ── Shared helper ─────────────────────────────────────────────────────────


def _make_mock_ports() -> dict:
    """Create mock port interfaces for TradingOrchestrator construction."""
    # ConfigPort: needs get_bool, get_int, get_float, get
    config = MagicMock()
    config.get_bool.return_value = True
    config.get_int.return_value = 100
    config.get_float.return_value = 1.0
    config.get.return_value = "default"

    return {
        "market_data": MagicMock(),
        "ml_model": MagicMock(),
        "risk": MagicMock(),
        "execution": MagicMock(),
        "persistence": MagicMock(),
        "notification": MagicMock(),
        "config": config,
        "correlation_id": MagicMock(),
        "metrics": MagicMock(),
        "logger": MagicMock(),
    }


# ═════════════════════════════════════════════════════════════════════════
# TradingOrchestrator Tests (v2.54 — modern replacement)
# ═════════════════════════════════════════════════════════════════════════


class TestTradingOrchestrator:
    """Tests for TradingOrchestrator (core.services.use_cases.trading_orchestrator)."""

    def test_init_with_all_ports(self) -> None:
        """TradingOrchestrator accepts all required port interfaces."""
        from core.services.use_cases.trading_orchestrator import TradingOrchestrator
        ports = _make_mock_ports()
        orch = TradingOrchestrator(
            market_data_port=ports["market_data"],
            ml_model_port=ports["ml_model"],
            risk_port=ports["risk"],
            execution_port=ports["execution"],
            persistence_port=ports["persistence"],
            notification_port=ports["notification"],
            config_port=ports["config"],
            correlation_id_manager=ports["correlation_id"],
            metrics_collector=ports["metrics"],
            logger=ports["logger"],
        )
        assert orch.market_data is ports["market_data"]
        assert orch.ml_model is ports["ml_model"]
        assert orch.risk_engine is ports["risk"]
        assert orch.config is ports["config"]

    def test_process_trading_cycle_market_data_failure(self) -> None:
        """When market data acquisition fails, cycle returns Failure."""
        from core.services.use_cases.trading_orchestrator import TradingOrchestrator

        ports = _make_mock_ports()
        ports["market_data"].get_latest_data.side_effect = ValueError("API timeout")

        orch = TradingOrchestrator(
            market_data_port=ports["market_data"],
            ml_model_port=ports["ml_model"],
            risk_port=ports["risk"],
            execution_port=ports["execution"],
            persistence_port=ports["persistence"],
            notification_port=ports["notification"],
            config_port=ports["config"],
            correlation_id_manager=ports["correlation_id"],
            metrics_collector=ports["metrics"],
            logger=ports["logger"],
        )
        result = orch.process_trading_cycle("NIFTY")
        assert result.is_failure
        assert "API timeout" in result.unwrap_err()

    def test_process_trading_cycle_weak_signal_skips(self) -> None:
        """When signal quality is WEAK, cycle returns Success(None) (skips trade)."""
        from core.services.use_cases.trading_orchestrator import TradingOrchestrator

        ports = _make_mock_ports()
        # last=100, strength = (100 % 100) / 100.0 = 0.0 → quality=WEAK
        ports["market_data"].get_latest_data.return_value = {"close": [50, 75, 100]}
        ports["market_data"].is_data_fresh.return_value = True

        orch = TradingOrchestrator(
            market_data_port=ports["market_data"],
            ml_model_port=ports["ml_model"],
            risk_port=ports["risk"],
            execution_port=ports["execution"],
            persistence_port=ports["persistence"],
            notification_port=ports["notification"],
            config_port=ports["config"],
            correlation_id_manager=ports["correlation_id"],
            metrics_collector=ports["metrics"],
            logger=ports["logger"],
        )
        result = orch.process_trading_cycle("NIFTY")
        assert result.is_success
        assert result.unwrap() is None

    def test_process_trading_cycle_success_callback(self) -> None:
        """Full successful cycle invokes all port methods in sequence."""
        from core.services.use_cases.trading_orchestrator import TradingOrchestrator

        ports = _make_mock_ports()
        # last=23450, strength = (23450 % 100) / 100.0 = 0.50 → quality=MODERATE (passes signal gate)
        ports["market_data"].get_latest_data.return_value = {"close": [23000, 23500, 23450]}
        ports["market_data"].is_data_fresh.return_value = True

        # Mock ML to return medium confidence
        mock_ml_pred = MagicMock()
        mock_ml_pred.confidence = MagicMock()
        mock_ml_pred.confidence.value = "MEDIUM"
        mock_ml_pred.confidence.name = "MEDIUM"
        mock_ml_pred.prediction_value = 0.6
        ports["ml_model"].predict_win_probability.return_value = mock_ml_pred

        # Mock risk to approve
        mock_risk = MagicMock()
        mock_risk.allowed = True
        mock_risk.reason = "OK"
        mock_risk.suggested_size = 1
        ports["risk"].evaluate_trade.return_value = mock_risk

        # Mock execution
        mock_order_result = MagicMock()
        mock_order_result.status = MagicMock()
        mock_order_result.status.name = "FILLED"
        mock_order_result.order_id = "ORD123"
        mock_order_result.filled_quantity = 50
        mock_order_result.average_price = 23500.0
        mock_order_result.commission = 0.0
        ports["execution"].execute_order.return_value = mock_order_result

        # All config bools return True
        ports["config"].get_bool.return_value = True
        ports["config"].get_int.return_value = 100
        ports["config"].get_float.return_value = 1.0
        ports["config"].get.return_value = "default"

        orch = TradingOrchestrator(
            market_data_port=ports["market_data"],
            ml_model_port=ports["ml_model"],
            risk_port=ports["risk"],
            execution_port=ports["execution"],
            persistence_port=ports["persistence"],
            notification_port=ports["notification"],
            config_port=ports["config"],
            correlation_id_manager=ports["correlation_id"],
            metrics_collector=ports["metrics"],
            logger=ports["logger"],
        )
        result = orch.process_trading_cycle("BANKNIFTY")

        assert result.is_success
        ports["market_data"].get_latest_data.assert_called_once_with("BANKNIFTY")
        ports["ml_model"].predict_win_probability.assert_called()
        ports["risk"].evaluate_trade.assert_called_once()
        ports["execution"].execute_order.assert_called_once()

    def test_process_trading_cycle_risk_rejection(self) -> None:
        """When risk rejects the trade, cycle returns Success(None) and notifies."""
        from core.services.use_cases.trading_orchestrator import TradingOrchestrator

        ports = _make_mock_ports()
        # last=23450, strength=0.50 → quality=MODERATE (passes signal gate)
        ports["market_data"].get_latest_data.return_value = {"close": [23000, 23500, 23450]}
        ports["market_data"].is_data_fresh.return_value = True

        # Mock ML
        mock_ml_pred = MagicMock()
        mock_ml_pred.confidence = MagicMock()
        mock_ml_pred.confidence.value = "HIGH"
        mock_ml_pred.prediction_value = 0.8
        ports["ml_model"].predict_win_probability.return_value = mock_ml_pred

        # Mock risk to REJECT
        mock_risk = MagicMock()
        mock_risk.allowed = False
        mock_risk.reason = "Max drawdown exceeded"
        mock_risk.suggested_size = 0
        ports["risk"].evaluate_trade.return_value = mock_risk

        # Enable all features
        ports["config"].get_int.return_value = 100
        ports["config"].get_float.return_value = 1.0
        ports["config"].get.return_value = "default"
        ports["config"].get_bool.return_value = True  # All bools enabled

        orch = TradingOrchestrator(
            market_data_port=ports["market_data"],
            ml_model_port=ports["ml_model"],
            risk_port=ports["risk"],
            execution_port=ports["execution"],
            persistence_port=ports["persistence"],
            notification_port=ports["notification"],
            config_port=ports["config"],
            correlation_id_manager=ports["correlation_id"],
            metrics_collector=ports["metrics"],
            logger=ports["logger"],
        )
        result = orch.process_trading_cycle("NIFTY")

        assert result.is_success
        # Risk rejection notification was sent (notify_on_risk_reject enabled by get_bool)
        ports["notification"].send_notification.assert_called_once()

    def test_process_trading_cycle_execution_error(self) -> None:
        """When broker execution fails, cycle returns Failure."""
        from core.services.use_cases.trading_orchestrator import TradingOrchestrator

        ports = _make_mock_ports()
        # last=23450, strength=0.50 → quality=MODERATE (passes signal gate)
        ports["market_data"].get_latest_data.return_value = {"close": [23000, 23500, 23450]}
        ports["market_data"].is_data_fresh.return_value = True

        # Mock ML
        mock_ml_pred = MagicMock()
        mock_ml_pred.confidence = MagicMock()
        mock_ml_pred.confidence.value = "HIGH"
        mock_ml_pred.prediction_value = 0.8
        ports["ml_model"].predict_win_probability.return_value = mock_ml_pred

        # Mock risk to approve
        mock_risk = MagicMock()
        mock_risk.allowed = True
        mock_risk.reason = "OK"
        mock_risk.suggested_size = 1
        ports["risk"].evaluate_trade.return_value = mock_risk

        # Mock execution to FAIL
        ports["execution"].execute_order.side_effect = ConnectionError("Broker unreachable")

        # All config bools True
        ports["config"].get_bool.return_value = True
        ports["config"].get_int.return_value = 100
        ports["config"].get_float.return_value = 1.0
        ports["config"].get.return_value = "default"

        orch = TradingOrchestrator(
            market_data_port=ports["market_data"],
            ml_model_port=ports["ml_model"],
            risk_port=ports["risk"],
            execution_port=ports["execution"],
            persistence_port=ports["persistence"],
            notification_port=ports["notification"],
            config_port=ports["config"],
            correlation_id_manager=ports["correlation_id"],
            metrics_collector=ports["metrics"],
            logger=ports["logger"],
        )
        result = orch.process_trading_cycle("NIFTY")

        assert result.is_failure
        assert "Broker unreachable" in result.unwrap_err()
