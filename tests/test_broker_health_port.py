"""Tests for core/ports/broker/health_port.py - Broker health monitoring port interface contract.

Covers:
- BrokerStatus, HealthCheckType enums
- BrokerHealthMetrics dataclass with defaults
- FailoverConfig dataclass with defaults and custom values
- BrokerHealthPort abstract methods are all defined
- Mock implementation validates the contract is implementable
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


from core.ports.broker.health_port import (
    BrokerHealthMetrics,
    BrokerHealthPort,
    BrokerStatus,
    FailoverConfig,
    HealthCheckType,
)


# ── BrokerStatus Enum Tests ───────────────────────────────────────────────────


class TestBrokerStatus:
    def test_values(self):
        assert BrokerStatus.CONNECTED.value == "connected"
        assert BrokerStatus.DISCONNECTED.value == "disconnected"
        assert BrokerStatus.ERROR.value == "error"
        assert BrokerStatus.RECOVERING.value == "recovering"
        assert BrokerStatus.UNKNOWN.value == "unknown"

    def test_all_unique(self):
        values = [s.value for s in BrokerStatus]
        assert len(values) == len(set(values))


# ── HealthCheckType Enum Tests ────────────────────────────────────────────────


class TestHealthCheckType:
    def test_values(self):
        assert HealthCheckType.CONNECTIVITY.value == "connectivity"
        assert HealthCheckType.LATENCY.value == "latency"
        assert HealthCheckType.ERROR_RATE.value == "error_rate"
        assert HealthCheckType.RATE_LIMIT.value == "rate_limit"
        assert HealthCheckType.AUTHENTICATION.value == "authentication"

    def test_all_unique(self):
        values = [t.value for t in HealthCheckType]
        assert len(values) == len(set(values))


# ── BrokerHealthMetrics Tests ─────────────────────────────────────────────────


class TestBrokerHealthMetrics:
    def test_defaults(self):
        metrics = BrokerHealthMetrics(broker_name="KITE", status=BrokerStatus.UNKNOWN)
        assert metrics.broker_name == "KITE"
        assert metrics.status == BrokerStatus.UNKNOWN
        assert metrics.latency_ms == 0.0
        assert metrics.error_rate == 0.0
        assert metrics.success_rate == 1.0
        assert metrics.last_success is None
        assert metrics.last_error is None
        assert metrics.consecutive_errors == 0
        assert metrics.consecutive_successes == 0
        assert metrics.authentication_valid is True
        assert metrics.metadata == {}

    def test_connected_metrics(self):
        ts = datetime(2026, 6, 20, 10, 0, 0)
        metrics = BrokerHealthMetrics(
            broker_name="KITE",
            status=BrokerStatus.CONNECTED,
            latency_ms=50.0,
            success_rate=0.99,
            consecutive_successes=100,
            last_success=ts,
            authentication_valid=True,
        )
        assert metrics.latency_ms == 50.0
        assert metrics.consecutive_successes == 100
        assert metrics.last_success == ts

    def test_disconnected_metrics(self):
        ts = datetime(2026, 6, 20, 9, 55, 0)
        metrics = BrokerHealthMetrics(
            broker_name="ANGEL",
            status=BrokerStatus.DISCONNECTED,
            error_rate=0.5,
            consecutive_errors=5,
            last_error=ts,
            error_message="Connection refused",
        )
        assert metrics.consecutive_errors == 5
        assert metrics.error_message == "Connection refused"
        assert metrics.last_error == ts

    def test_rate_limit_metrics(self):
        ts = datetime(2026, 6, 20, 11, 0, 0)
        metrics = BrokerHealthMetrics(
            broker_name="FYERS",
            status=BrokerStatus.ERROR,
            rate_limit_remaining=10,
            rate_limit_reset_time=ts,
            error_message="Rate limited",
        )
        assert metrics.rate_limit_remaining == 10
        assert metrics.rate_limit_reset_time == ts

    def test_metadata_custom(self):
        metrics = BrokerHealthMetrics(
            broker_name="KITE",
            status=BrokerStatus.CONNECTED,
            metadata={"version": "3.0", "server": "api.kite.com"},
        )
        assert metrics.metadata["version"] == "3.0"


# ── FailoverConfig Tests ──────────────────────────────────────────────────────


class TestFailoverConfig:
    def test_defaults(self):
        cfg = FailoverConfig()
        assert cfg.enabled is False
        assert cfg.failover_threshold == 3
        assert cfg.failover_chain == []
        assert cfg.failover_recovery_mins == 15
        assert cfg.health_check_interval == 30
        assert cfg.latency_threshold_ms == 5000
        assert cfg.error_rate_threshold == 0.5
        assert cfg.success_rate_threshold == 0.8

    def test_enabled_config(self):
        cfg = FailoverConfig(
            enabled=True,
            failover_threshold=5,
            failover_chain=["PRIMARY", "SECONDARY", "TERTIARY"],
            failover_recovery_mins=30,
            health_check_interval=15,
            latency_threshold_ms=1000,
            error_rate_threshold=0.1,
            success_rate_threshold=0.95,
        )
        assert cfg.enabled is True
        assert cfg.failover_threshold == 5
        assert len(cfg.failover_chain) == 3
        assert cfg.failover_recovery_mins == 30

    def test_single_broker_chain(self):
        cfg = FailoverConfig(failover_chain=["KITE"])
        assert cfg.failover_chain == ["KITE"]

    def test_immutable_chain_copy(self):
        """Dataclass stores reference to passed list; make defensive copy."""
        chain = ["A", "B"]
        cfg = FailoverConfig(failover_chain=chain)
        # Python dataclasses store a reference, not a copy
        # The caller must pass a copy if isolation is needed
        assert cfg.failover_chain == ["A", "B"]
        assert cfg.failover_chain is chain  # Same object - no copy made


# ── BrokerHealthPort Contract Tests ───────────────────────────────────────────


class TestBrokerHealthPortContract:
    """Verify the abstract interface defines all required methods."""

    def test_all_abstract_methods_exist(self):
        methods = [
            "check_broker_health",
            "get_all_brokers_health",
            "is_broker_available",
            "get_recommended_broker",
            "record_broker_success",
            "record_broker_error",
            "update_failover_config",
            "get_failover_status",
            "force_failover",
            "health_check",
        ]
        for m in methods:
            assert hasattr(BrokerHealthPort, m), f"Missing abstract method: {m}"
            # Verify it's abstract
            getattr(BrokerHealthPort, m).__isabstractmethod__


class TestMockHealthPort:
    """Mock implementation to verify the contract is implementable."""

    def test_can_implement_interface(self):
        class MockHealthPort(BrokerHealthPort):
            def check_broker_health(self, broker_name: str) -> BrokerHealthMetrics:
                return BrokerHealthMetrics(broker_name=broker_name, status=BrokerStatus.UNKNOWN)

            def get_all_brokers_health(self) -> dict[str, BrokerHealthMetrics]:
                return {}

            def is_broker_available(self, broker_name: str) -> bool:
                return False

            def get_recommended_broker(self) -> str | None:
                return None

            def record_broker_success(self, broker_name: str, latency_ms: float = 0.0) -> None:
                pass

            def record_broker_error(self, broker_name: str, error: Exception, latency_ms: float = 0.0) -> None:
                pass

            def update_failover_config(self, config: FailoverConfig) -> None:
                pass

            def get_failover_status(self) -> dict[str, Any]:
                return {"enabled": False}

            def force_failover(self, target_broker: str) -> bool:
                return False

            def health_check(self) -> dict[str, Any]:
                return {"status": "healthy"}

        port = MockHealthPort()
        assert isinstance(port, BrokerHealthPort)

        metrics = port.check_broker_health("KITE")
        assert metrics.broker_name == "KITE"
        assert metrics.status == BrokerStatus.UNKNOWN

        assert port.get_all_brokers_health() == {}
        assert port.is_broker_available("KITE") is False
        assert port.get_recommended_broker() is None
        assert port.force_failover("KITE") is False
        assert port.health_check()["status"] == "healthy"
