"""
Test for DI container wiring in index_trader module.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from core.di_container import container
from core.ports.broker.health_port import BrokerHealthPort
from core.ports.circuit_breaker.circuit_breaker_port import CircuitBreakerPort
from core.ports.config import ConfigPort
from core.ports.correlation_id import CorrelationIdPort
from core.ports.execution import ExecutionPort
from core.ports.logging import LoggingPort
from core.ports.market_data import MarketDataPort
from core.ports.metrics import MetricsPort
from core.ports.ml_model import MlModelPort
from core.ports.notification import NotificationPort
from core.ports.persistence import PersistencePort
from core.ports.rate_limiting.rate_limit_port import RateLimitPort
from core.ports.risk import RiskPort
from core.ports.strategy import StrategyPort


class TestDIContainerWiring:
    """Test cases for DI container wiring."""

    def setup_method(self):
        """Clear container before each test."""
        container.clear()

    def teardown_method(self):
        """Clear container after each test."""
        container.clear()

    def test_setup_di_container_complete(self):
        """Test that setup_di_container registers all expected services."""
        # Setup mocks for external dependencies
        with patch('infrastructure.config.secure_config_adapter.SecureConfigAdapter') as mock_config_adapter, \
             patch('infrastructure.adapters.brokers.paper.adapter.PaperBrokerAdapter') as mock_broker_adapter, \
             patch('infrastructure.adapters.persistence.sqlite_adapter.SQLiteAdapter') as mock_persistence_adapter, \
             patch('infrastructure.adapters.market_data.yahoofinance.adapter.YahooFinanceAdapter') as mock_market_data_adapter, \
             patch('core.services.execution_service.ExecutionService') as mock_execution_service, \
             patch('core.services.risk_service.RiskService') as mock_risk_service, \
             patch('core.services.notification_service.NotificationService') as mock_notification_service, \
             patch('core.services.persistence_service.PersistenceService') as mock_persistence_service, \
             patch('core.services.broker_health_service.BrokerHealthService') as mock_broker_health_service, \
             patch('core.services.rate_limiting_service.RateLimitingService') as mock_rate_limiting_service, \
             patch('core.services.circuit_breaker_service.CircuitBreakerService') as mock_circuit_breaker_service, \
             patch('infrastructure.adapters.ml_model.ml_model_adapter.MLModelAdapter') as mock_ml_model_adapter, \
             patch('infrastructure.adapters.correlation_id.correlation_id_adapter.CorrelationIdAdapter') as mock_correlation_id_adapter, \
             patch('infrastructure.config.logging_adapter.StructuredLoggerAdapter') as mock_logger_adapter, \
             patch('core.metrics_exporter.MetricsAdapter') as mock_metrics_adapter:

            # Setup mock instances with proper dict-like protocol
            mock_config_instance = Mock()
            mock_config_instance.get_int.return_value = 100000
            mock_config_instance.get_bool.return_value = False
            mock_config_instance.get.return_value = 'PAPER'
            mock_config_instance.keys.return_value = []
            mock_config_instance.items.return_value = []
            mock_config_instance.get_all.return_value = {}
            mock_config_instance.get_safe_config.return_value = {}
            mock_config_adapter.return_value = mock_config_instance

            # Mock other adapters to return mock instances
            mock_broker_adapter.return_value = Mock()
            mock_persistence_adapter.return_value = Mock()
            mock_market_data_adapter.return_value = Mock()
            mock_execution_service.return_value = Mock()
            mock_risk_service.return_value = Mock()
            mock_notification_service.return_value = Mock()
            mock_persistence_service.return_value = Mock()
            mock_broker_health_service.return_value = Mock()
            mock_rate_limiting_service.return_value = Mock()
            mock_circuit_breaker_service.return_value = Mock()
            mock_ml_model_adapter.return_value = Mock()
            mock_correlation_id_adapter.return_value = Mock()
            mock_logger_adapter.return_value = Mock()
            mock_metrics_adapter.return_value = Mock()

            # Clear container and run setup
            container.clear()
            from index_app.index_trader import setup_di_container
            setup_di_container()

            # Verify all services are registered
            assert container.is_registered(ConfigPort)
            assert container.is_registered(ExecutionPort)
            assert container.is_registered(RiskPort)
            assert container.is_registered(NotificationPort)
            assert container.is_registered(PersistencePort)
            assert container.is_registered(BrokerHealthPort)
            assert container.is_registered(RateLimitPort)
            assert container.is_registered(CircuitBreakerPort)
            assert container.is_registered(MlModelPort)
            assert container.is_registered(CorrelationIdPort)
            assert container.is_registered(LoggingPort)
            assert container.is_registered(MarketDataPort)
            assert container.is_registered(MetricsPort)
            assert container.is_registered(StrategyPort)

            # Verify we can resolve instances
            config = container.resolve(ConfigPort)
            assert config is not None

            execution_service = container.resolve(ExecutionPort)
            assert execution_service is not None

            risk_service = container.resolve(RiskPort)
            assert risk_service is not None

            # Verify singleton behavior
            config1 = container.resolve(ConfigPort)
            config2 = container.resolve(ConfigPort)
            assert config1 is config2

            execution1 = container.resolve(ExecutionPort)
            execution2 = container.resolve(ExecutionPort)
            assert execution1 is execution2

    def test_container_can_resolve_services_after_manual_setup(self):
        """Test that we can manually set up and resolve services."""
        # Setup mock services
        mock_config = Mock(spec=ConfigPort)
        mock_execution = Mock(spec=ExecutionPort)
        mock_risk = Mock(spec=RiskPort)
        mock_notification = Mock(spec=NotificationPort)
        mock_persistence = Mock(spec=PersistencePort)
        mock_broker_health = Mock(spec=BrokerHealthPort)
        mock_rate_limit = Mock(spec=RateLimitPort)
        mock_circuit_breaker = Mock(spec=CircuitBreakerPort)
        mock_ml_model = Mock(spec=MlModelPort)
        mock_correlation_id = Mock(spec=CorrelationIdPort)
        mock_logging = Mock(spec=LoggingPort)
        mock_market_data = Mock(spec=MarketDataPort)
        mock_metrics = Mock(spec=MetricsPort)
        mock_strategy = Mock(spec=StrategyPort)

        # Register services using register_instance (simpler one-step pattern)
        container.register_instance(ConfigPort, mock_config)
        container.register_instance(ExecutionPort, mock_execution)
        container.register_instance(RiskPort, mock_risk)
        container.register_instance(NotificationPort, mock_notification)
        container.register_instance(PersistencePort, mock_persistence)
        container.register_instance(BrokerHealthPort, mock_broker_health)
        container.register_instance(RateLimitPort, mock_rate_limit)
        container.register_instance(CircuitBreakerPort, mock_circuit_breaker)
        container.register_instance(MlModelPort, mock_ml_model)
        container.register_instance(CorrelationIdPort, mock_correlation_id)
        container.register_instance(LoggingPort, mock_logging)
        container.register_instance(MarketDataPort, mock_market_data)
        container.register_instance(MetricsPort, mock_metrics)
        container.register_instance(StrategyPort, mock_strategy)

        # Test resolution
        assert container.resolve(ConfigPort) is mock_config
        assert container.resolve(ExecutionPort) is mock_execution
        assert container.resolve(RiskPort) is mock_risk
        assert container.resolve(NotificationPort) is mock_notification
        assert container.resolve(PersistencePort) is mock_persistence
        assert container.resolve(BrokerHealthPort) is mock_broker_health
        assert container.resolve(RateLimitPort) is mock_rate_limit
        assert container.resolve(CircuitBreakerPort) is mock_circuit_breaker
        assert container.resolve(MlModelPort) is mock_ml_model
        assert container.resolve(CorrelationIdPort) is mock_correlation_id
        assert container.resolve(LoggingPort) is mock_logging
        assert container.resolve(MarketDataPort) is mock_market_data
        assert container.resolve(MetricsPort) is mock_metrics
        assert container.resolve(StrategyPort) is mock_strategy

    def test_container_try_resolve_unregistered_returns_none(self):
        """Test that try_resolve returns None for unregistered interfaces."""
        # Clear container
        container.clear()

        # Try to resolve unregistered port
        result = container.try_resolve(ConfigPort)
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
