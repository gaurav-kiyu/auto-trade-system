"""
Broker Health Monitoring Port Interface

This interface defines the contract that all broker health monitoring implementations must implement.
It provides a unified way to monitor broker connectivity, latency, error rates, and implement
automatic failover mechanisms.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class BrokerStatus(Enum):
    """Broker connection status."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    RECOVERING = "recovering"
    UNKNOWN = "unknown"


class HealthCheckType(Enum):
    """Types of health checks."""
    CONNECTIVITY = "connectivity"
    LATENCY = "latency"
    ERROR_RATE = "error_rate"
    RATE_LIMIT = "rate_limit"
    AUTHENTICATION = "authentication"


@dataclass
class BrokerHealthMetrics:
    """Broker health metrics."""
    broker_name: str
    status: BrokerStatus
    latency_ms: float = 0.0
    error_rate: float = 0.0  # Errors per minute
    success_rate: float = 1.0  # Success ratio (0.0 to 1.0)
    last_success: datetime | None = None
    last_error: datetime | None = None
    consecutive_errors: int = 0
    consecutive_successes: int = 0
    rate_limit_remaining: int | None = None
    rate_limit_reset_time: datetime | None = None
    error_message: str | None = None
    authentication_valid: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FailoverConfig:
    """Configuration for broker failover."""
    enabled: bool = False
    failover_threshold: int = 3  # Consecutive failures before failover
    failover_chain: list[str] = field(default_factory=list)  # Ordered list of brokers
    failover_recovery_mins: int = 15  # Minutes before attempting recovery
    health_check_interval: int = 30  # Seconds between health checks
    latency_threshold_ms: int = 5000  # Max acceptable latency
    error_rate_threshold: float = 0.5  # Max error rate (errors/minute)
    success_rate_threshold: float = 0.8  # Min success ratio


class BrokerHealthPort(ABC):
    """
    Abstract base class for broker health monitoring services.

    All broker health monitoring implementations must inherit from this class
    and implement the required methods.
    """

    @abstractmethod
    def check_broker_health(self, broker_name: str) -> BrokerHealthMetrics:
        """
        Perform a health check on a specific broker.

        Args:
            broker_name: Name of the broker to check

        Returns:
            BrokerHealthMetrics object with current health status
        """
        pass

    @abstractmethod
    def get_all_brokers_health(self) -> dict[str, BrokerHealthMetrics]:
        """
        Get health status for all known brokers.

        Returns:
            Dictionary mapping broker names to their health metrics
        """
        pass

    @abstractmethod
    def is_broker_available(self, broker_name: str) -> bool:
        """
        Check if a broker is available for trading.

        Args:
            broker_name: Name of the broker to check

        Returns:
            True if broker is available, False otherwise
        """
        pass

    @abstractmethod
    def get_recommended_broker(self) -> str | None:
        """
        Get the recommended broker for trading based on health status.

        Returns:
            Name of the recommended broker, or None if no healthy brokers available
        """
        pass

    @abstractmethod
    def record_broker_success(self, broker_name: str, latency_ms: float = 0.0) -> None:
        """
        Record a successful broker operation.

        Args:
            broker_name: Name of the broker
            latency_ms: Latency of the operation in milliseconds
        """
        pass

    @abstractmethod
    def record_broker_error(self, broker_name: str, error: Exception, latency_ms: float = 0.0) -> None:
        """
        Record a broker error.

        Args:
            broker_name: Name of the broker
            error: The exception that occurred
            latency_ms: Latency of the operation in milliseconds (if applicable)
        """
        pass

    @abstractmethod
    def update_failover_config(self, config: FailoverConfig) -> None:
        """
        Update the failover configuration.

        Args:
            config: New failover configuration
        """
        pass

    @abstractmethod
    def get_failover_status(self) -> dict[str, Any]:
        """
        Get current failover status and statistics.

        Returns:
            Dictionary containing failover status information
        """
        pass

    @abstractmethod
    def force_failover(self, target_broker: str) -> bool:
        """
        Force a failover to a specific broker.

        Args:
            target_broker: Name of the broker to failover to

        Returns:
            True if failover was successful, False otherwise
        """
        pass

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the broker health monitoring service itself.

        Returns:
            Dictionary containing health check results
        """
        pass


__all__ = [
    "BrokerHealthMetrics",
    "BrokerHealthPort",
    "BrokerStatus",
    "FailoverConfig",
    "HealthCheckType",
]

