"""
Test for DI container wiring in index_trader module.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from core.di_container import get_container, reset_container
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

# Minimal config dict for setup_di_container integration test
_MINIMAL_CONFIG: dict = {
    "BASE_CAPITAL": 100000,
    "EXECUTION_MODE": "PAPER",
    "BROKER_API_ENABLED": False,
    "MANUAL_SIGNALS_ONLY": True,
    "web_dashboard_enabled": False,
}


class TestDIContainerWiring:
    """Test cases for DI container wiring."""

    def setup_method(self):
        """Clear the live global container before each test.

        NOTE: must use get_container() (not a module-level ``container``
        binding) because other test files (test_di_config_wiring.py,
        test_di_container.py) call reset_container(), which REPLACES the
        global container object mid-suite. A stale binding would clear/check
        the old instance while setup_di_container() wires the new one.
        """
        get_container().clear()

    def teardown_method(self):
        """Restore a fully-wired global container after each test.

        reset_container() (not clear()) rebuilds the default wiring, so any
        later test in any order (including pytest-randomly/xdist) sees a
        healthy global with ConfigManager/Mediator/etc. registered.
        """
        reset_container()

    def test_setup_di_container_complete(self):
        """Test that DI container can register and resolve all port interfaces.

        This test directly registers and resolves port implementations to verify
        the container wiring pattern works correctly, without needing to mock
        the 20+ external dependencies of index_trader.setup_di_container().

        A separate integration test (test_setup_di_container_integration) validates
        the actual setup_di_container() function with targeted mocking.
        """
        container = get_container()
        # Clear container first
        container.clear()

        # Create mock instances for all ports
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

        # Register all services using the same pattern as setup_di_container
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
        assert config is mock_config

        # Verify singleton behavior
        config1 = container.resolve(ConfigPort)
        config2 = container.resolve(ConfigPort)
        assert config1 is config2
        assert config1 is mock_config

    def test_setup_di_container_integration(self):
        """Integration test: verify the actual setup_di_container() function.

        Uses targeted patches for external dependencies (Telegram, NSE, broker)
        to isolate the DI wiring logic while still calling the real function.
        """
        # Patch external dependencies that are not available in test environment
        with patch('index_app.index_trader.send', return_value=None), \
             patch('index_app.index_trader.log'), \
             patch('core.news_sentinel.NewsSentinel.start'), \
             patch('core.kite_ticker_feed.KiteTickerFeedManager'), \
             patch('core.ltp_resolver.LtpResolver'), \
             patch('index_app.domains.config.loader.get_config_loader') as mock_loader, \
             patch('index_app.domains.broker.factory.make_broker') as mock_broker, \
             patch('index_app.domains.market.data.fetch_intraday_data'), \
             patch('index_app.domains.market.data.fetch_intraday_data_cached'), \
             patch('index_app.domains.market.data.fetch_vix'):

            # Setup mock loader to return minimal config
            from index_app.domains.config.loader import ConfigResult
            mock_result = ConfigResult(
                cfg=_MINIMAL_CONFIG,
                success=True,
            )
            mock_loader.return_value.load.return_value = mock_result
            mock_broker.return_value = Mock()

            # Clear the LIVE global container (the same instance that
            # setup_di_container() wires into via get_container()).
            container = get_container()
            container.clear()

            # Import and call the real setup_di_container
            from index_app.index_trader import setup_di_container
            setup_di_container()

            # Verify at least some core ports are registered
            registered_count = 0
            for port in [ConfigPort, RiskPort, ExecutionPort]:
                if container.is_registered(port):
                    registered_count += 1

            assert registered_count >= 1, (
                f"Expected >=1 core ports registered, got {registered_count}. "
                "setup_di_container may not be wiring core services correctly."
            )

    def test_container_can_resolve_services_after_manual_setup(self):
        """Test that we can manually set up and resolve services."""
        container = get_container()
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
        container = get_container()
        # Clear container
        container.clear()

        # Try to resolve unregistered port
        result = container.try_resolve(ConfigPort)
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
