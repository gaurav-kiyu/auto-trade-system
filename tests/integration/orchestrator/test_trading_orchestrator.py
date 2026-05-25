"""
Integration tests for Trading Orchestrator.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock, patch

import pytest
from core.common.kernels.correlation_id import CorrelationIdManager
from core.common.utilities.logging import StructuredLogger
from core.common.utilities.metrics import MetricsCollector
from core.common.utilities.result import Success
from core.domains.execution.model import Fill, Order, OrderResult, OrderStatus
from core.domains.ml.model import MLConfidence, MLPrediction
from core.domains.risk.model import RiskDecision
from core.domains.signal_engine.model import SignalQuality, TradingSignal
from core.domains.strategy.model import StrategyDecision
from core.ports.config import ConfigPort
from core.ports.execution import ExecutionPort
from core.ports.market_data import MarketDataPort
from core.ports.ml_model import MlModelPort
from core.ports.notification import NotificationPort
from core.ports.persistence import PersistencePort
from core.ports.risk import RiskPort
from core.services.use_cases.trading_orchestrator import OrchestratorConfig, TradingOrchestrator


class TestTradingOrchestrator:
    """Integration test cases for TradingOrchestrator."""

    def setup_method(self):
        """Set up test fixtures with mocked dependencies."""
        # Create mock ports
        self.market_data_mock = Mock(spec=MarketDataPort)
        self.ml_model_mock = Mock(spec=MlModelPort)
        self.risk_engine_mock = Mock(spec=RiskPort)
        self.execution_engine_mock = Mock(spec=ExecutionPort)
        self.persistence_mock = Mock(spec=PersistencePort)
        self.notification_mock = Mock(spec=NotificationPort)
        self.config_mock = Mock(spec=ConfigPort)
        self.correlation_id_mock = Mock(spec=CorrelationIdManager)
        self.metrics_mock = Mock(spec=MetricsCollector)
        self.logger_mock = Mock(spec=StructuredLogger)
        # Set up the logger mock to support the context manager returned by contextualize
        contextual_manager = Mock()
        contextual_manager.__enter__ = Mock(return_value=None)
        contextual_manager.__exit__ = Mock(return_value=None)
        self.logger_mock.contextualize.return_value = contextual_manager
        # Set up config mock return values for the success test
        self.config_mock.get_bool.side_effect = self._config_get_bool_side_effect
        self.config_mock.get.side_effect = self._config_get_side_effect
        self.config_mock.get_float.side_effect = self._config_get_float_side_effect
        self.config_mock.get_int.side_effect = self._config_get_int_side_effect
        # Create orchestrator config
        self.orchestrator_config = OrchestratorConfig(
            symbol="NIFTY24SepFUT",
            strategy_name="test_strategy",
            max_position_size=100,
            enable_ml_enhancement=True,
            enable_risk_checks=True,
            enable_persistence=True,
            enable_notifications=True,
            paper_trading=True
        )
        # Create orchestrator
        self.orchestrator = TradingOrchestrator(
            market_data_port=self.market_data_mock,
            ml_model_port=self.ml_model_mock,
            risk_port=self.risk_engine_mock,
            execution_port=self.execution_engine_mock,
            persistence_port=self.persistence_mock,
            notification_port=self.notification_mock,
            config_port=self.config_mock,
            correlation_id_manager=self.correlation_id_mock,
            metrics_collector=self.metrics_mock,
            logger=self.logger_mock
        )

    def _config_get_bool_side_effect(self, key, default=False):
        """Side effect function for config.get_bool mock."""
        if key == "enable_ml_enhancement":
            return True
        elif key == "notify_on_risk_reject":
            return False
        elif key == "enable_persistence":
            return True
        elif key == "enable_notifications":
            return True
        return default

    def _config_get_side_effect(self, key, default=None):
        """Side effect function for config.get mock."""
        if key == "strategy.name":
            return "test_strategy"
        return default

    def _config_get_float_side_effect(self, key, default=0.0):
        """Side effect function for config.get_float mock."""
        if key == "strategy.test_strategy.size_multiplier":
            return 1.0  # No change to size
        return default

    def _config_get_int_side_effect(self, key, default=0):
        """Side effect function for config.get_int mock."""
        if key == "max_position_size":
            return 100  # Reasonable max position size
        return default

    def test_initialization(self):
        """Test orchestrator initialization."""
        assert self.orchestrator.market_data == self.market_data_mock
        assert self.orchestrator.ml_model == self.ml_model_mock
        assert self.orchestrator.risk_engine == self.risk_engine_mock
        assert self.orchestrator.execution_engine == self.execution_engine_mock
        assert self.orchestrator.persistence == self.persistence_mock
        assert self.orchestrator.notification == self.notification_mock
        assert self.orchestrator.config == self.config_mock
        assert self.orchestrator.correlation_id == self.correlation_id_mock
        assert self.orchestrator.metrics == self.metrics_mock
        assert self.orchestrator.logger == self.logger_mock
        assert self.orchestrator._current_state is None
        assert self.orchestrator._last_signal_time is None

    def test_process_trading_cycle_success(self):
        """Test successful trading cycle execution."""
        # Setup mocks for each step
        # 1. Market data acquisition
        market_data = {"close": [22000, 22050, 22100], "volume": [100, 150, 200]}
        self.market_data_mock.get_latest_data.return_value = market_data
        self.market_data_mock.is_data_fresh.return_value = True

        # 2. Signal generation
        signal = TradingSignal(
            symbol="NIFTY24SepFUT",
            strength=0.8,
            direction="BUY",
            quality=SignalQuality.STRONG,
            timestamp=datetime.now(),
            metadata={}
        )
        # Mock the private method
        with patch.object(self.orchestrator, '_generate_trading_signal', return_value=Success(signal)):
            # 3. Signal validation
            with patch.object(self.orchestrator, '_validate_signal', return_value=Success(None)):
                # 4. ML enhancement
                ml_prediction = MLPrediction(
                    prediction_value=0.75,
                    confidence=MLConfidence.HIGH,
                    features_used=["feature1", "feature2"],
                    model_version="1.0.0",
                    prediction_timestamp=datetime.now().timestamp(),
                    metadata={}
                )
                self.ml_model_mock.predict_win_probability.return_value = ml_prediction
                with patch.object(self.orchestrator, '_enhance_with_ml', return_value=Success(signal)):
                    # 5. Strategy decision
                    strategy_decision = StrategyDecision(
                        should_trade=True,
                        direction="BUY",
                        suggested_size=50,
                        reason="Strong signal",
                        strategy_name="test_strategy",
                        metadata={}
                    )
                    with patch.object(self.orchestrator, '_make_strategy_decision', return_value=Success(strategy_decision)):
                        # 6. Risk evaluation
                        risk_decision = RiskDecision(
                            allowed=True,
                            reason="Risk checks passed",
                            suggested_size=50
                        )
                        with patch.object(self.orchestrator, '_evaluate_risk', return_value=Success(risk_decision)):
                            # 7. Order creation
                            order = Order(
                                symbol="NIFTY24SepFUT",
                                direction="BUY",
                                quantity=50,
                                order_type="MARKET",
                                price=None,
                                strategy_id="test_strategy",
                                risk_decision_id="risk_passed",
                                timestamp=datetime.now()
                            )
                            with patch.object(self.orchestrator, '_create_execution_order', return_value=Success(order)):
                                # 8. Broker routing
                                order_result = OrderResult(
                                    order_id="order_123",
                                    status=OrderStatus.FILLED,
                                    filled_quantity=50,
                                    average_price=22000.0,
                                    timestamp=datetime.now()
                                )
                                with patch.object(self.orchestrator, '_route_to_broker', return_value=Success(order_result)):
                                    # 9. Fill processing
                                    fills = [Fill(
                                        order_id="order_123",
                                        fill_id="fill_456",
                                        symbol="NIFTY24SepFUT",
                                        quantity=50,
                                        price=22000.0,
                                        timestamp=datetime.now(),
                                        commission=0.0
                                    )]
                                    with patch.object(self.orchestrator, '_process_fills', return_value=Success(fills)):
                                        # 10. State persistence
                                        with patch.object(self.orchestrator, '_persist_state', return_value=Success(None)):
                                            # 11. Analytics update
                                            with patch.object(self.orchestrator, '_update_analytics', return_value=Success(None)):
                                                # 12. Notifications
                                                with patch.object(self.orchestrator, '_send_trade_notifications', return_value=Success(None)):
                                                    # Execute
                                                    result = self.orchestrator.process_trading_cycle("NIFTY24SepFUT")

                                                    # Verify
                                                    assert result.is_success
                                                    # Verify that key methods were called
                                                    self.market_data_mock.get_latest_data.assert_called_once_with("NIFTY24SepFUT")
                                                    self.market_data_mock.is_data_fresh.assert_called_once()

    def test_process_trading_cycle_market_data_failure(self):
        """Test trading cycle when market data acquisition fails."""
        # Setup
        self.market_data_mock.get_latest_data.side_effect = Exception("Market data unavailable")

        # Execute
        result = self.orchestrator.process_trading_cycle("NIFTY24SepFUT")

        # Verify
        assert result.is_failure
        assert "Failed to acquire market data" in result.unwrap_err()

    def test_process_trading_cycle_stale_market_data(self):
        """Test trading cycle when market data is stale."""
        # Setup
        market_data = {"close": [22000], "volume": [100]}
        self.market_data_mock.get_latest_data.return_value = market_data
        self.market_data_mock.is_data_fresh.return_value = False  # Stale data

        # Execute
        result = self.orchestrator.process_trading_cycle("NIFTY24SepFUT")

        # Verify
        assert result.is_failure
        assert "Market data is stale" in result.unwrap_err()

    def test_process_trading_cycle_weak_signal(self):
        """Test trading cycle when signal is too weak."""
        # Setup
        market_data = {"close": [22000], "volume": [100]}
        self.market_data_mock.get_latest_data.return_value = market_data
        self.market_data_mock.is_data_fresh.return_value = True

        # Weak signal
        weak_signal = TradingSignal(
            symbol="NIFTY24SepFUT",
            strength=0.2,
            direction="BUY",
            quality=SignalQuality.WEAK,
            timestamp=datetime.now(),
            metadata={}
        )

        with patch.object(self.orchestrator, '_generate_trading_signal', return_value=Success(weak_signal)):
            # Execute
            result = self.orchestrator.process_trading_cycle("NIFTY24SepFUT")

            # Verify
            assert result.is_success
            # Should not proceed further with weak signal
            self.market_data_mock.get_latest_data.assert_called_once()

    def test_process_trading_cycle_risk_rejection(self):
        """Test trading cycle when risk rejects the trade."""
        # Setup
        market_data = {"close": [22000], "volume": [100]}
        self.market_data_mock.get_latest_data.return_value = market_data
        self.market_data_mock.is_data_fresh.return_value = True

        signal = TradingSignal(
            symbol="NIFTY24SepFUT",
            strength=0.8,
            direction="BUY",
            quality=SignalQuality.STRONG,
            timestamp=datetime.now(),
            metadata={}
        )

        with patch.object(self.orchestrator, '_generate_trading_signal', return_value=Success(signal)):
            with patch.object(self.orchestrator, '_validate_signal', return_value=Success(None)):
                with patch.object(self.orchestrator, '_enhance_with_ml', return_value=Success(signal)):
                    with patch.object(self.orchestrator, '_make_strategy_decision', return_value=Success(StrategyDecision(
                        should_trade=True,
                        direction="BUY",
                        suggested_size=50,
                        reason="Test",
                        strategy_name="test_strategy",
                        metadata={}
                    ))):
                        # Risk rejects
                        risk_decision = RiskDecision(
                            allowed=False,
                            reason="Daily loss limit exceeded",
                            suggested_size=0
                        )
                        with patch.object(self.orchestrator, '_evaluate_risk', return_value=Success(risk_decision)):
                            # Execute
                            result = self.orchestrator.process_trading_cycle("NIFTY24SepFUT")

                            # Verify
                            assert result.is_success
                            # Should have sent risk rejection notification if enabled
                            self.config_mock.get_bool.assert_any_call("notify_on_risk_reject", False)

    def test_process_trading_cycle_ml_enhancement_disabled(self):
        """Test trading cycle with ML enhancement disabled."""
        # Setup orchestrator with ML disabled
        orchestrator_no_ml = TradingOrchestrator(
            market_data_port=self.market_data_mock,
            ml_model_port=self.ml_model_mock,
            risk_port=self.risk_engine_mock,
            execution_port=self.execution_engine_mock,
            persistence_port=self.persistence_mock,
            notification_port=self.notification_mock,
            config_port=self.config_mock,
            correlation_id_manager=self.correlation_id_mock,
            metrics_collector=self.metrics_mock,
            logger=self.logger_mock
        )
        # Override config to disable ML for this test
        original_get_bool = self.config_mock.get_bool.side_effect
        self.config_mock.get_bool.side_effect = lambda key, default=False: False if key == "enable_ml_enhancement" else original_get_bool(key, default)

        # Setup
        market_data = {"close": [22000], "volume": [100]}
        self.market_data_mock.get_latest_data.return_value = market_data
        self.market_data_mock.is_data_fresh.return_value = True

        signal = TradingSignal(
            symbol="NIFTY24SepFUT",
            strength=0.8,
            direction="BUY",
            quality=SignalQuality.STRONG,
            timestamp=datetime.now(),
            metadata={}
        )

        with patch.object(orchestrator_no_ml, '_generate_trading_signal', return_value=Success(signal)):
            with patch.object(orchestrator_no_ml, '_validate_signal', return_value=Success(None)):
                # ML enhancement should be skipped
                with patch.object(orchestrator_no_ml, '_enhance_with_ml', return_value=Success(signal)) as mock_ml_enhance:
                    with patch.object(orchestrator_no_ml, '_make_strategy_decision', return_value=Success(StrategyDecision(
                        should_trade=True,
                        direction="BUY",
                        suggested_size=50,
                        reason="Test",
                        strategy_name="test_strategy",
                        metadata={}
                    ))):
                        with patch.object(orchestrator_no_ml, '_evaluate_risk', return_value=Success(RiskDecision(
                            allowed=True,
                            reason="Risk checks passed",
                            suggested_size=50
                        ))):
                            with patch.object(orchestrator_no_ml, '_create_execution_order', return_value=Success(Order(
                                symbol="NIFTY24SepFUT",
                                direction="BUY",
                                quantity=50,
                                order_type="MARKET",
                                price=None,
                                strategy_id="test_strategy",
                                risk_decision_id="risk_passed",
                                timestamp=datetime.now()
                            ))):
                                with patch.object(orchestrator_no_ml, '_route_to_broker', return_value=Success(OrderResult(
                                    order_id="order_123",
                                    status=OrderStatus.FILLED,
                                    filled_quantity=50,
                                    average_price=22000.0,
                                    timestamp=datetime.now()
                                ))):
                                    with patch.object(orchestrator_no_ml, '_process_fills', return_value=Success([Fill(
                                        order_id="order_123",
                                        fill_id="fill_456",
                                        symbol="NIFTY24SepFUT",
                                        quantity=50,
                                        price=22000.0,
                                        timestamp=datetime.now(),
                                        commission=0.0
                                    )])):
                                        with patch.object(orchestrator_no_ml, '_persist_state', return_value=Success(True)):
                                            with patch.object(orchestrator_no_ml, '_update_analytics', return_value=Success(None)):
                                                with patch.object(orchestrator_no_ml, '_send_trade_notifications', return_value=Success(None)):
                                                    # Execute
                                                    result = orchestrator_no_ml.process_trading_cycle("NIFTY24SepFUT")

                                                    # Verify
                                                    assert result.is_success
                                                    # ML enhancement should have been called but returned early due to config
                                                    mock_ml_enhance.assert_called_once()

                                                    # Restore original mock
                                                    self.config_mock.get_bool.side_effect = original_get_bool

    def test_process_trading_cycle_unexpected_exception(self):
        """Test trading cycle when unexpected exception occurs."""
        # Setup: make _generate_trading_signal throw an unexpected error
        with patch.object(self.orchestrator, '_generate_trading_signal') as mock_gen:
            mock_gen.side_effect = Exception("Unexpected error")

            # Execute
            result = self.orchestrator.process_trading_cycle("NIFTY24SepFUT")

            # Verify
            assert result.is_failure
            assert "Unexpected error" in result.unwrap_err()
            self.logger_mock.error.assert_called_once_with("Unexpected error in trading cycle", error="Unexpected error")
            self.metrics_mock.increment.assert_called_with("trading_cycle.errors")


    def test_helper_methods(self):
        """Test helper methods of the orchestrator."""
        # Test _get_current_portfolio_state
        state = self.orchestrator._get_current_portfolio_state()
        assert state == {}  # Simplified implementation

        # Test _get_current_market_conditions
        conditions = self.orchestrator._get_current_market_conditions()
        assert isinstance(conditions, dict)
        assert "volatility" in conditions
        assert "liquidity" in conditions
        assert "trend" in conditions

        # Test _apply_strategy_sizing
        from core.domains.risk.model import RiskDecision
        from core.domains.strategy.model import StrategyDecision

        strategy_decision = StrategyDecision(
            should_trade=True,
            direction="BUY",
            suggested_size=50,
            reason="Test",
            strategy_name="test_strategy",
            metadata={}
        )

        risk_decision = RiskDecision(
            allowed=True,
            reason="Test",
            suggested_size=50
        )

        # Save original side effects and set temporary ones
        original_get_float = self.config_mock.get_float.side_effect
        original_get_int = self.config_mock.get_int.side_effect
        self.config_mock.get_float.side_effect = lambda key, default=0.0: 1.2 if key == "strategy.test_strategy.size_multiplier" else default
        self.config_mock.get_int.side_effect = lambda key, default=0: 100 if key == "max_position_size" else default

        adjusted_size = self.orchestrator._apply_strategy_sizing(
            base_size=50,
            strategy_decision=strategy_decision,
            risk_decision=risk_decision
        )

        # Expected: 50 * 1.2 = 60, capped at max 100
        assert adjusted_size == 60

        # Test with size exceeding max
        adjusted_size_max = self.orchestrator._apply_strategy_sizing(
            base_size=90,
            strategy_decision=strategy_decision,
            risk_decision=risk_decision
        )
        # Expected: 90 * 1.2 = 108, capped at max 100
        assert adjusted_size_max == 100

        # Restore original side effects
        self.config_mock.get_float.side_effect = original_get_float
        self.config_mock.get_int.side_effect = original_get_int

    def test_extract_features_for_ml(self):
        """Test ML feature extraction."""
        from core.domains.signal_engine.model import SignalQuality, TradingSignal

        signal = TradingSignal(
            symbol="NIFTY24SepFUT",
            strength=0.7,
            direction="BUY",
            quality=SignalQuality.STRONG,
            timestamp=datetime(2026, 5, 10, 14, 30, 0),  # 2:30 PM
            metadata={"key1": "value1", "key2": "value2"}
        )

        market_data = {"some": "data"}

        features = self.orchestrator._extract_features_for_ml(signal, market_data)

        # Verify features
        assert isinstance(features, list)
        assert len(features) == 4
        assert features[0] == 0.7  # signal strength
        assert features[1] == 1.0  # direction BUY = 1.0
        assert abs(features[2] - (14.5 / 24.0)) < 0.01  # hour of day normalized
        assert abs(features[3] - (2.0 / 10.0)) < 0.01  # metadata count / 10.0

    def test_create_signal_from_data(self):
        """Test signal creation from market data."""
        # Use a close price that yields strength 0.8: (price % 100) / 100 = 0.8 => price % 100 = 80
        market_data = {"close": [22080]}  # 22080 % 100 = 80 -> strength = 0.8
        symbol = "NIFTY24SepFUT"

        signal = self.orchestrator._create_signal_from_data(market_data, symbol)

        # Verify
        assert isinstance(signal, TradingSignal)
        assert signal.symbol == symbol
        assert signal.strength == 0.8
        assert signal.direction == "BUY"
        # Strength 0.8 > 0.7, so should be STRONG
        assert signal.quality == SignalQuality.STRONG
        assert isinstance(signal.timestamp, datetime)
        assert signal.metadata == {"generated_by": "demo_orchestrator"}

    def test_full_integration_flow_with_realistic_data(self):
        """Test a more realistic integration flow."""
        # This test mimics a realistic flow without mocking every internal method

        # Setup realistic market data
        market_data = {
            "close": [21950, 22000, 22050, 22100, 22080],
            "volume": [1000, 1200, 1500, 1800, 1600],
            "timestamp": datetime.now()
        }
        self.market_data_mock.get_latest_data.return_value = market_data
        self.market_data_mock.is_data_fresh.return_value = True

        # Setup ML model to return reasonable prediction
        ml_prediction = MLPrediction(
            prediction_value=0.65,
            confidence=MLConfidence.MEDIUM,
            features_used=["signal_strength", "direction", "time_of_day", "metadata_count"],
            model_version="v2.45",
            prediction_timestamp=datetime.now().timestamp(),
            metadata={"model_type": "LightGBM"}
        )
        self.ml_model_mock.predict_win_probability.return_value = ml_prediction

        # Setup risk engine to allow trade with adjusted size
        risk_decision = RiskDecision(
            allowed=True,
            reason="All risk checks passed",
            suggested_size=25  # Reduced from suggested 50 due to risk limits
        )
        self.risk_engine_mock.evaluate_trade.return_value = risk_decision

        # Setup execution to succeed
        order_result = OrderResult(
            order_id="ord_12345",
            status=OrderStatus.FILLED,
            filled_quantity=25,
            average_price=22050.0,
            timestamp=datetime.now(),
            commission=12.50
        )
        self.execution_engine_mock.execute_order.return_value = order_result

        # Setup persistence to succeed
        self.persistence_mock.save_state.return_value = True
        self.persistence_mock.save_trade.return_value = "trade_id_123"

        # Setup notification to succeed
        self.notification_mock.send_notification.return_value = None

        # Execute the cycle
        result = self.orchestrator.process_trading_cycle("NIFTY24SepFUT")

        # Verify success
        assert result.is_success

        # Verify key interactions happened
        self.market_data_mock.get_latest_data.assert_called_once_with("NIFTY24SepFUT")
        self.market_data_mock.is_data_fresh.assert_called_once()
        self.ml_model_mock.predict_win_probability.assert_called_once()
        self.risk_engine_mock.evaluate_trade.assert_called_once()
        self.execution_engine_mock.execute_order.assert_called_once()
        self.persistence_mock.save_state.assert_called_once()
        self.persistence_mock.save_trade.assert_called_once()
        self.notification_mock.send_notification.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
