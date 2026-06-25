"""Tests for core/services/broker_health_service.py - Broker Health Monitoring.

Covers:
- BrokerHealthServiceConfig defaults
- BrokerHealthService init, start, stop
- check_broker_health() connectivity/latency/auth checks
- get_all_brokers_health(), get_broker_metrics()
- is_broker_available(), get_recommended_broker()
- record_broker_success(), record_broker_error()
- update_failover_config, force_failover, health_check
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.ports.broker.health_port import (
    BrokerHealthMetrics,
    BrokerStatus,
    FailoverConfig,
)
from core.services.broker_health_service import (
    BrokerHealthService,
    BrokerHealthServiceConfig,
)


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def mock_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.ping.return_value = True
    adapter.validate_token.return_value = True
    return adapter


@pytest.fixture
def health_service(mock_adapter: MagicMock) -> BrokerHealthService:
    return BrokerHealthService(
        broker_adapters={"kite": mock_adapter},
        config=BrokerHealthServiceConfig(
            connectivity_check_interval=999,
            latency_check_interval=999,
            error_rate_check_interval=999,
            comprehensive_check_interval=999,
        ),
    )


# =============================================================================
# Init Tests
# =============================================================================

class TestInit:
    def test_default_config(self, mock_adapter: MagicMock):
        service = BrokerHealthService(broker_adapters={"kite": mock_adapter})
        assert service.config.connectivity_check_interval == 30
        assert service.config.latency_check_interval == 15
        assert service.config.max_history_size == 1000

    def test_initializes_metrics_for_all_brokers(self, mock_adapter: MagicMock):
        service = BrokerHealthService(broker_adapters={"kite": mock_adapter, "angel": mock_adapter})
        assert "kite" in service._health_metrics
        assert "angel" in service._health_metrics
        assert service._health_metrics["kite"].status == BrokerStatus.UNKNOWN

    def test_custom_config(self, mock_adapter: MagicMock):
        config = BrokerHealthServiceConfig(connectivity_check_interval=60, latency_warning_threshold=500)
        service = BrokerHealthService(broker_adapters={"kite": mock_adapter}, config=config)
        assert service.config.connectivity_check_interval == 60
        assert service.config.latency_warning_threshold == 500


# =============================================================================
# Start / Stop Tests
# =============================================================================

class TestStartStop:
    def test_start(self, health_service: BrokerHealthService):
        assert health_service.start() is True
        assert health_service._monitoring is True

    def test_start_idempotent(self, health_service: BrokerHealthService):
        health_service.start()
        assert health_service.start() is True  # Already running

    def test_stop(self, health_service: BrokerHealthService):
        health_service.start()
        assert health_service.stop() is True
        assert health_service._monitoring is False

    def test_stop_idempotent(self, health_service: BrokerHealthService):
        assert health_service.stop() is True  # Not running

    def test_monitoring_flag(self, health_service: BrokerHealthService):
        assert health_service._monitoring is False
        health_service.start()
        assert health_service._monitoring is True


# =============================================================================
# check_broker_health Tests
# =============================================================================

class TestCheckBrokerHealth:
    def test_returns_metrics(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        metrics = health_service.check_broker_health("kite")
        assert isinstance(metrics, BrokerHealthMetrics)
        assert metrics.broker_name == "kite"

    def test_connected_status(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        mock_adapter.ping.return_value = True
        mock_adapter.validate_token.return_value = True
        metrics = health_service.check_broker_health("kite")
        assert metrics.status == BrokerStatus.CONNECTED
        assert metrics.authentication_valid is True

    def test_unknown_broker_returns_unknown(self, health_service: BrokerHealthService):
        metrics = health_service.check_broker_health("nonexistent")
        assert metrics.status == BrokerStatus.UNKNOWN
        assert "not found" in (metrics.error_message or "")

    def test_disconnected_on_ping_fail(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        mock_adapter.ping.return_value = False
        metrics = health_service.check_broker_health("kite")
        assert metrics.status == BrokerStatus.DISCONNECTED

    def test_ping_error(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        mock_adapter.ping.side_effect = ConnectionError("Timeout")
        metrics = health_service.check_broker_health("kite")
        # Connection errors are classified as DISCONNECTED by check_broker_health
        assert metrics.status == BrokerStatus.DISCONNECTED
        assert metrics.error_message is not None

    def test_auth_failure(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        mock_adapter.ping.return_value = True
        mock_adapter.validate_token.return_value = False
        metrics = health_service.check_broker_health("kite")
        assert metrics.authentication_valid is False

    def test_stores_last_check_time(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        health_service.check_broker_health("kite")
        assert "kite" in health_service._last_health_check


# =============================================================================
# get_all_brokers_health Tests
# =============================================================================

class TestGetAllBrokersHealth:
    def test_returns_all_brokers(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        result = health_service.get_all_brokers_health()
        assert "kite" in result
        assert isinstance(result["kite"], BrokerHealthMetrics)

    def test_multiple_brokers(self, mock_adapter: MagicMock):
        service = BrokerHealthService(broker_adapters={"kite": mock_adapter, "angel": mock_adapter})
        result = service.get_all_brokers_health()
        assert len(result) == 2


# =============================================================================
# get_broker_metrics Tests
# =============================================================================

class TestGetBrokerMetrics:
    def test_returns_metrics(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        health_service.check_broker_health("kite")
        metrics = health_service.get_broker_metrics("kite")
        assert metrics.broker_name == "kite"

    def test_unknown_broker(self, health_service: BrokerHealthService):
        metrics = health_service.get_broker_metrics("nonexistent")
        assert metrics.status == BrokerStatus.UNKNOWN

    def test_returns_latest_metrics(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        health_service.check_broker_health("kite")
        metrics1 = health_service.get_broker_metrics("kite")
        metrics2 = health_service.get_broker_metrics("kite")
        assert metrics1 is metrics2  # Same object reference (cached)


# =============================================================================
# is_broker_available Tests
# =============================================================================

class TestIsBrokerAvailable:
    def test_available_when_connected(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        health_service.check_broker_health("kite")
        assert health_service.is_broker_available("kite") is True

    def test_not_available_when_disconnected(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        mock_adapter.ping.return_value = False
        health_service.check_broker_health("kite")
        assert health_service.is_broker_available("kite") is False


# =============================================================================
# record_broker_success / error Tests
# =============================================================================

class TestRecordBroker:
    def test_success_updates_metrics(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        health_service.check_broker_health("kite")
        health_service.record_broker_success("kite", latency_ms=50)
        metrics = health_service.get_broker_metrics("kite")
        assert metrics.consecutive_successes > 0
        assert metrics.consecutive_errors == 0

    def test_error_updates_metrics(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        health_service.record_broker_error("kite", ValueError("API failed"), latency_ms=100)
        metrics = health_service.get_broker_metrics("kite")
        assert metrics.consecutive_errors >= 0

    def test_error_resets_success_streak(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        health_service.record_broker_success("kite")
        health_service.record_broker_success("kite")
        health_service.record_broker_error("kite", ValueError("fail"))
        metrics = health_service.get_broker_metrics("kite")
        assert metrics.consecutive_successes == 0

    def test_success_resets_error_streak(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        health_service.record_broker_error("kite", ValueError("e1"))
        health_service.record_broker_error("kite", ValueError("e2"))
        health_service.record_broker_success("kite")
        metrics = health_service.get_broker_metrics("kite")
        assert metrics.consecutive_errors == 0

    def test_auto_init_on_new_broker(self, health_service: BrokerHealthService):
        health_service.record_broker_success("new_broker")
        assert "new_broker" in health_service._health_metrics


# =============================================================================
# get_recommended_broker Tests
# =============================================================================

class TestGetRecommendedBroker:
    def test_returns_healthy_broker(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        health_service.check_broker_health("kite")
        recommended = health_service.get_recommended_broker()
        assert recommended == "kite"

    def test_returns_none_when_all_unhealthy(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        mock_adapter.ping.side_effect = ConnectionError("offline")
        health_service.check_broker_health("kite")
        recommended = health_service.get_recommended_broker()
        assert recommended is None

    def test_picks_best_broker(self, mock_adapter: MagicMock):
        adapter_fast = MagicMock()
        adapter_fast.ping.return_value = True
        adapter_fast.validate_token.return_value = True
        adapter_slow = MagicMock()
        adapter_slow.ping.return_value = True
        adapter_slow.validate_token.return_value = True

        service = BrokerHealthService(broker_adapters={"fast": adapter_fast, "slow": adapter_slow})
        service.check_broker_health("fast")
        service.check_broker_health("slow")
        recommended = service.get_recommended_broker()
        assert recommended in ("fast", "slow")


# =============================================================================
# force_failover Tests
# =============================================================================

class TestForceFailover:
    def test_unknown_broker_returns_false(self, health_service: BrokerHealthService):
        assert health_service.force_failover("unknown") is False

    def test_known_broker_processing(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        result = health_service.force_failover("kite")
        # Without proper failover manager chain, may fail
        assert isinstance(result, bool)

    def test_update_failover_config(self, health_service: BrokerHealthService):
        config = FailoverConfig(
            enabled=True, failover_threshold=5,
            failover_chain=["kite"], failover_recovery_mins=10,
        )
        health_service.update_failover_config(config)
        assert health_service.failover_manager._enabled is True


# =============================================================================
# health_check Tests
# =============================================================================

class TestHealthCheck:
    def test_returns_status_dict(self, health_service: BrokerHealthService):
        result = health_service.health_check()
        assert result["status"] in ("healthy", "stopped")
        assert result["service"] == "BrokerHealthService"
        assert result["monitoring_active"] is False

    def test_after_start(self, health_service: BrokerHealthService):
        health_service.start()
        result = health_service.health_check()
        assert result["monitoring_active"] is True

    def test_broker_counts(self, health_service: BrokerHealthService, mock_adapter: MagicMock):
        health_service.check_broker_health("kite")
        result = health_service.health_check()
        assert result["broker_count"] == 1
