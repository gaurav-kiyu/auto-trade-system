"""
Broker Health Monitoring Service

Implements a comprehensive broker health monitoring service that:
- Monitors broker connectivity, latency, and error rates
- Integrates with existing broker failover mechanisms
- Provides health check scheduling and alerting
- Supports multiple broker types with unified interface
"""

from __future__ import annotations

import threading

__all__ = [
    "HealthCheckResult",
    "BrokerHealthServiceConfig",
    "BrokerHealthService",
]
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from core.broker_failover import BrokerFailoverManager
from core.datetime_ist import now_ist
from core.logging import LoggingService
from core.exceptions import BrokerConnectionError, BrokerTimeoutError
from core.ports.broker.health_port import (
    BrokerHealthMetrics,
    BrokerHealthPort,
    BrokerStatus,
    FailoverConfig,
    HealthCheckType,
)


@dataclass
class HealthCheckResult:
    """Result of a single health check."""
    broker_name: str
    check_type: HealthCheckType
    success: bool
    latency_ms: float
    timestamp: datetime
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrokerHealthServiceConfig:
    """Configuration for the broker health service."""
    # Health check intervals
    connectivity_check_interval: int = 30  # seconds
    latency_check_interval: int = 15       # seconds
    error_rate_check_interval: int = 60    # seconds
    comprehensive_check_interval: int = 300 # seconds (5 minutes)

    # Thresholds
    latency_warning_threshold: float = 1000.0  # ms
    latency_critical_threshold: float = 5000.0  # ms
    error_rate_warning_threshold: float = 0.1   # errors per minute
    error_rate_critical_threshold: float = 0.5  # errors per minute
    success_rate_warning_threshold: float = 0.95  # minimum success ratio
    success_rate_critical_threshold: float = 0.80  # minimum success ratio

    # History tracking
    max_history_size: int = 1000  # Maximum health check results to keep per broker
    history_retention_hours: int = 24  # How long to keep health history

    # Failover integration
    enable_failover_integration: bool = True
    failover_on_consecutive_failures: int = 3
    failover_recovery_delay_minutes: int = 15

    # Alerting
    enable_health_alerts: bool = True
    alert_on_status_change: bool = True
    alert_on_threshold_breach: bool = True


class BrokerHealthService(BrokerHealthPort):
    """
    Comprehensive broker health monitoring service.

    Features:
    - Continuous health monitoring of multiple brokers
    - Integration with existing broker failover mechanisms
    - Configurable health check intervals and thresholds
    - History tracking and trending
    - Alerting on status changes and threshold breaches
    - Thread-safe operations
    """

    def __init__(
        self,
        broker_adapters: dict[str, Any],
        failover_manager: BrokerFailoverManager | None = None,
        config: BrokerHealthServiceConfig | None = None
    ):
        """
        Initialize the broker health service.

        Args:
            broker_adapters: Dictionary mapping broker names to their adapter instances
            failover_manager: Existing broker failover manager to integrate with
            config: Health service configuration
        """
        self.broker_adapters = broker_adapters
        self.failover_manager = failover_manager or BrokerFailoverManager()
        self.config = config or BrokerHealthServiceConfig()

        # Thread safety
        self._lock = threading.RLock()
        self._health_check_lock = threading.RLock()

        # Health metrics storage
        self._health_metrics: dict[str, BrokerHealthMetrics] = {}
        self._health_history: dict[str, deque] = {}  # broker_name -> deque of results
        self._last_health_check: dict[str, datetime] = {}

        # Monitoring state
        self._monitoring = False
        self._monitor_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Initialize metrics for all known brokers
        for broker_name in self.broker_adapters.keys():
            self._initialize_broker_metrics(broker_name)

        # Initialize logger
        self._logger = LoggingService(
            log_dir="logs",
            log_filename_prefix="broker_health_service_",
            retain_days=30,
            json_log_file="",
            version="UNKNOWN",
            enable_correlation_ids=True,
            enable_contextual_logging=True
        )

        self._logger.info(f"BrokerHealthService initialized for brokers: {list(self.broker_adapters.keys())}")

    def start(self) -> bool:
        """Start the health monitoring service."""
        with self._lock:
            if self._monitoring:
                self._logger.warning("Broker health service is already running")
                return True

            self._monitoring = True
            self._stop_event.clear()

            # Start monitoring thread
            self._monitor_thread = threading.Thread(
                target=self._monitoring_loop,
                name="BrokerHealthMonitor",
                daemon=True
            )
            self._monitor_thread.start()

            self._logger.info("Broker health monitoring service started")
            return True

    def stop(self) -> bool:
        """Stop the health monitoring service."""
        with self._lock:
            if not self._monitoring:
                self._logger.warning("Broker health service is not running")
                return True

            self._monitoring = False
            self._stop_event.set()

            # Wait for monitoring thread to finish
            if self._monitor_thread and self._monitor_thread.is_alive():
                self._monitor_thread.join(timeout=5.0)

            self._logger.info("Broker health monitoring service stopped")
            return True

    def check_broker_health(self, broker_name: str) -> BrokerHealthMetrics:
        """
        Perform a comprehensive health check on a specific broker.

        Args:
            broker_name: Name of the broker to check

        Returns:
            BrokerHealthMetrics object with current health status
        """
        with self._health_check_lock:
            start_time = time.time()

            if broker_name not in self.broker_adapters:
                return BrokerHealthMetrics(
                    broker_name=broker_name,
                    status=BrokerStatus.UNKNOWN,
                    error_message=f"Broker {broker_name} not found in adapters"
                )

            adapter = self.broker_adapters[broker_name]
            metrics = BrokerHealthMetrics(
                broker_name=broker_name,
                status=BrokerStatus.UNKNOWN
            )

            try:
                # Check connectivity
                connectivity_result = self._check_connectivity(adapter, broker_name)
                if not connectivity_result.success:
                    metrics.status = BrokerStatus.DISCONNECTED
                    metrics.error_message = connectivity_result.error_message
                    self._record_check_result(broker_name, connectivity_result)
                    return metrics

                # Check latency
                latency_result = self._check_latency(adapter, broker_name)
                metrics.latency_ms = latency_result.latency_ms
                if latency_result.latency_ms > self.config.latency_critical_threshold:
                    metrics.status = BrokerStatus.ERROR
                elif latency_result.latency_ms > self.config.latency_warning_threshold:
                    if metrics.status == BrokerStatus.UNKNOWN:
                        metrics.status = BrokerStatus.CONNECTED  # Warning but still connected
                else:
                    if metrics.status == BrokerStatus.UNKNOWN:
                        metrics.status = BrokerStatus.CONNECTED

                # Check authentication (if applicable)
                auth_result = self._check_authentication(adapter, broker_name)
                if not auth_result.success:
                    metrics.authentication_valid = False
                    if metrics.status == BrokerStatus.CONNECTED:
                        metrics.status = BrokerStatus.ERROR
                else:
                    metrics.authentication_valid = True

                # Update success/error rates based on history
                self._update_error_rates(broker_name)

                # Set final metrics
                metrics.last_success = self._get_last_success_time(broker_name)
                metrics.last_error = self._get_last_error_time(broker_name)
                metrics.consecutive_errors = self._get_consecutive_errors(broker_name)
                metrics.consecutive_successes = self._get_consecutive_successes(broker_name)

                # Record the successful check
                self._record_check_result(broker_name, HealthCheckResult(
                    broker_name=broker_name,
                    check_type=HealthCheckType.CONNECTIVITY,
                    success=True,
                    latency_ms=metrics.latency_ms,
                    timestamp=now_ist()
                ))

            except (BrokerConnectionError, BrokerTimeoutError, ConnectionError, OSError, ValueError, AttributeError) as e:
                self._logger.error(f"Error checking health for broker {broker_name}: {e}", exc_info=True)
                metrics.status = BrokerStatus.ERROR
                metrics.error_message = str(e)
                self._record_check_result(broker_name, HealthCheckResult(
                    broker_name=broker_name,
                    check_type=HealthCheckType.CONNECTIVITY,
                    success=False,
                    latency_ms=(time.time() - start_time) * 1000,
                    timestamp=now_ist(),
                    error_message=str(e)
                ))

            # Update stored metrics
            self._health_metrics[broker_name] = metrics
            self._last_health_check[broker_name] = now_ist()

            return metrics

    def get_all_brokers_health(self) -> dict[str, BrokerHealthMetrics]:
        """
        Get health status for all known brokers.

        Returns:
            Dictionary mapping broker names to their health metrics
        """
        with self._lock:
            result = {}
            for broker_name in self.broker_adapters.keys():
                # Use cached results if recent enough, otherwise perform fresh check
                if self._is_cache_fresh(broker_name):
                    result[broker_name] = self._health_metrics[broker_name]
                else:
                    result[broker_name] = self.check_broker_health(broker_name)
            return result

    def get_broker_metrics(self, broker_name: str) -> BrokerHealthMetrics:
        """
        Get health metrics for a specific broker.

        Args:
            broker_name: Name of the broker to get metrics for

        Returns:
            BrokerHealthMetrics for the broker, or UNKNOWN status if not found
        """
        return self._health_metrics.get(
            broker_name,
            BrokerHealthMetrics(broker_name=broker_name, status=BrokerStatus.UNKNOWN),
        )

    def is_broker_available(self, broker_name: str) -> bool:
        """
        Check if a broker is available for trading.

        Args:
            broker_name: Name of the broker to check

        Returns:
            True if broker is available, False otherwise
        """
        metrics = self.get_broker_metrics(broker_name)
        return metrics.status in [BrokerStatus.CONNECTED, BrokerStatus.RECOVERING]

    def get_recommended_broker(self) -> str | None:
        """
        Get the recommended broker for trading based on health status.

        Returns:
            Name of the recommended broker, or None if no healthy brokers available
        """
        with self._lock:
            healthy_brokers = []

            for broker_name, metrics in self._health_metrics.items():
                # Consider a broker healthy if it's connected or recovering with good metrics
                if metrics.status == BrokerStatus.CONNECTED:
                    healthy_brokers.append((broker_name, metrics))
                elif metrics.status == BrokerStatus.RECOVERING:
                    # Allow recovering brokers if they have good recent performance
                    if metrics.error_rate < 0.1 and metrics.success_rate > 0.9:
                        healthy_brokers.append((broker_name, metrics))

            if not healthy_brokers:
                return None

            # Sort by health score (lower latency, higher success rate, lower error rate)
            def health_score(broker_tuple):
                name, metrics = broker_tuple
                # Lower is better: latency penalty + error penalty - success bonus
                latency_penalty = min(metrics.latency_ms / 1000.0, 10.0)  # Cap at 10s
                error_penalty = metrics.error_rate * 10.0
                success_bonus = (1.0 - metrics.success_rate) * 10.0
                return latency_penalty + error_penalty + success_bonus

            healthy_brokers.sort(key=health_score)
            return healthy_brokers[0][0]  # Return the healthiest broker

    def record_broker_success(self, broker_name: str, latency_ms: float = 0.0) -> None:
        """
        Record a successful broker operation.

        Args:
            broker_name: Name of the broker
            latency_ms: Latency of the operation in milliseconds
        """
        with self._lock:
            if broker_name not in self._health_metrics:
                self._initialize_broker_metrics(broker_name)

            metrics = self._health_metrics[broker_name]
            metrics.last_success = now_ist()
            metrics.consecutive_successes += 1
            metrics.consecutive_errors = 0  # Reset error streak on success

            # Update success rate (exponential moving average)
            alpha = 0.1  # Smoothing factor
            metrics.success_rate = (alpha * 1.0) + ((1 - alpha) * metrics.success_rate)

            # Update latency (exponential moving average)
            if latency_ms > 0:
                metrics.latency_ms = (alpha * latency_ms) + ((1 - alpha) * metrics.latency_ms)

            self._logger.debug(f"Recorded success for broker {broker_name} (latency: {latency_ms}ms)")

    def record_broker_error(self, broker_name: str, error: Exception, latency_ms: float = 0.0) -> None:
        """
        Record a broker error.

        Args:
            broker_name: Name of the broker
            error: The exception that occurred
            latency_ms: Latency of the operation in milliseconds (if applicable)
        """
        with self._lock:
            if broker_name not in self._health_metrics:
                self._initialize_broker_metrics(broker_name)

            metrics = self._health_metrics[broker_name]
            metrics.last_error = now_ist()
            metrics.consecutive_errors += 1
            metrics.consecutive_successes = 0  # Reset success streak on error

            # Update error rate (exponential moving average)
            alpha = 0.1  # Smoothing factor
            error_increment = 1.0  # Each error adds 1 to the rate (will be decayed over time)
            metrics.error_rate = (alpha * error_increment) + ((1 - alpha) * metrics.error_rate)

            # Update latency if provided
            if latency_ms > 0:
                metrics.latency_ms = (alpha * latency_ms) + ((1 - alpha) * metrics.latency_ms)

            self._logger.warning(f"Recorded error for broker {broker_name}: {error} (latency: {latency_ms}ms)")

            # Check if we should trigger failover
            if (self.config.enable_failover_integration and
                metrics.consecutive_errors >= self.config.failover_on_consecutive_failures):
                self._consider_failover(broker_name)

    def update_failover_config(self, config: FailoverConfig) -> None:
        """
        Update the failover configuration.

        Args:
            config: New failover configuration
        """
        if self.failover_manager:
            # Update the existing failover manager's configuration
            self.failover_manager._enabled = config.enabled
            self.failover_manager._threshold = config.failover_threshold
            self.failover_manager._chain = config.failover_chain.copy()
            self.failover_manager._rec_mins = float(config.failover_recovery_mins)
            self._logger.info("Failover configuration updated")

    def get_failover_status(self) -> dict[str, Any]:
        """
        Get current failover status and statistics.

        Returns:
            Dictionary containing failover status information
        """
        if self.failover_manager:
            return self.failover_manager.status()
        return {"enabled": False, "error": "No failover manager configured"}

    def force_failover(self, target_broker: str) -> bool:
        """
        Force a failover to a specific broker.

        Args:
            target_broker: Name of the broker to failover to

        Returns:
            True if failover was successful, False otherwise
        """
        if target_broker not in self.broker_adapters:
            self._logger.error(f"Cannot force failover to unknown broker: {target_broker}")
            return False

        if self.failover_manager:
            # Manually set the active broker in the failover manager
            try:
                with self.failover_manager._lock:
                    if target_broker in self.failover_manager._chain:
                        self.failover_manager._active_idx = self.failover_manager._chain.index(target_broker)
                        # Reset failure count for the target broker
                        if target_broker in self.failover_manager._states:
                            self.failover_manager._states[target_broker].failure_count = 0
                        self._logger.info(f"Forced failover to broker: {target_broker}")
                        return True
                    else:
                        self._logger.error(f"Target broker {target_broker} not in failover chain")
                        return False
            except (AttributeError, ValueError, KeyError, RuntimeError) as e:
                self._logger.error(f"Error forcing failover to {target_broker}: {e}")
                return False
        return False

    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the broker health monitoring service itself.

        Returns:
            Dictionary containing health check results
        """
        try:
            with self._lock:
                total_brokers = len(self.broker_adapters)
                healthy_brokers = 0
                unhealthy_brokers = 0
                unknown_brokers = 0

                for broker_name, metrics in self._health_metrics.items():
                    if metrics.status == BrokerStatus.CONNECTED:
                        healthy_brokers += 1
                    elif metrics.status == BrokerStatus.DISCONNECTED or metrics.status == BrokerStatus.ERROR:
                        unhealthy_brokers += 1
                    else:
                        unknown_brokers += 1

                return {
                    "status": "healthy" if self._monitoring else "stopped",
                    "service": "BrokerHealthService",
                    "monitoring_active": self._monitoring,
                    "broker_count": total_brokers,
                    "healthy_brokers": healthy_brokers,
                    "unhealthy_brokers": unhealthy_brokers,
                    "unknown_brokers": unknown_brokers,
                    "failover_integration": self.config.enable_failover_integration,
                    "monitored_brokers": list(self.broker_adapters.keys())
                }

        except (ValueError, AttributeError, KeyError) as e:
            self._logger.error(f"Error in broker health service health check: {e}", exc_info=True)
            return {
                "status": "unhealthy",
                "service": "BrokerHealthService",
                "error": str(e)
            }

    # Private helper methods

    def _initialize_broker_metrics(self, broker_name: str) -> None:
        """Initialize health metrics for a broker."""
        self._health_metrics[broker_name] = BrokerHealthMetrics(
            broker_name=broker_name,
            status=BrokerStatus.UNKNOWN
        )
        self._health_history[broker_name] = deque(maxlen=self.config.max_history_size)
        self._last_health_check[broker_name] = datetime.min

    def _is_cache_fresh(self, broker_name: str) -> bool:
        """Check if the cached health metrics are fresh enough."""
        if broker_name not in self._last_health_check:
            return False

        age = (now_ist() - self._last_health_check[broker_name]).total_seconds()
        return age < self.config.comprehensive_check_interval

    def _check_connectivity(self, adapter: Any, broker_name: str) -> HealthCheckResult:
        """Check broker connectivity."""
        start_time = time.time()
        try:
            # Try to ping the broker or get a simple status
            if hasattr(adapter, 'ping'):
                result = adapter.ping()
                success = bool(result)
            elif hasattr(adapter, 'get_account_info'):
                # Try to get account info as a connectivity test
                result = adapter.get_account_info()
                success = result is not None
            elif hasattr(adapter, 'check_connection'):
                result = adapter.check_connection()
                success = bool(result)
            else:
                # Fallback: assume connected if we have an adapter
                success = adapter is not None

            latency_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                broker_name=broker_name,
                check_type=HealthCheckType.CONNECTIVITY,
                success=success,
                latency_ms=latency_ms,
                timestamp=now_ist()
            )
        except (ConnectionError, OSError, ValueError, AttributeError) as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                broker_name=broker_name,
                check_type=HealthCheckType.CONNECTIVITY,
                success=False,
                latency_ms=latency_ms,
                timestamp=now_ist(),
                error_message=str(e)
            )

    def _check_latency(self, adapter: Any, broker_name: str) -> HealthCheckResult:
        """Check broker latency."""
        start_time = time.time()
        try:
            # Try to measure latency with a simple operation
            if hasattr(adapter, 'get_quote'):
                # Measure quote retrieval latency
                symbol = "NIFTY"  # Default symbol for testing
                adapter.get_quote(symbol)
            elif hasattr(adapter, 'get_latest_price'):
                symbol = "NIFTY"
                adapter.get_latest_price(symbol)
            else:
                # Fallback: just measure the time to access the adapter
                _ = adapter.__class__.__name__

            latency_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                broker_name=broker_name,
                check_type=HealthCheckType.LATENCY,
                success=True,
                latency_ms=latency_ms,
                timestamp=now_ist()
            )
        except (ConnectionError, OSError, ValueError, BrokerTimeoutError) as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                broker_name=broker_name,
                check_type=HealthCheckType.LATENCY,
                success=False,
                latency_ms=latency_ms,
                timestamp=now_ist(),
                error_message=str(e)
            )

    def _check_authentication(self, adapter: Any, broker_name: str) -> HealthCheckResult:
        """Check broker authentication."""
        start_time = time.time()
        try:
            # Try to verify authentication/token validity
            if hasattr(adapter, 'validate_token'):
                result = adapter.validate_token()
                success = bool(result)
            elif hasattr(adapter, 'check_auth'):
                result = adapter.check_auth()
                success = bool(result)
            else:
                # Fallback: assume authenticated if we have credentials
                success = hasattr(adapter, 'api_key') and bool(getattr(adapter, 'api_key', None))

            latency_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                broker_name=broker_name,
                check_type=HealthCheckType.AUTHENTICATION,
                success=success,
                latency_ms=latency_ms,
                timestamp=now_ist()
            )
        except (ConnectionError, OSError, ValueError, AttributeError) as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                broker_name=broker_name,
                check_type=HealthCheckType.AUTHENTICATION,
                success=False,
                latency_ms=latency_ms,
                timestamp=now_ist(),
                error_message=str(e)
            )

    def _record_check_result(self, broker_name: str, result: HealthCheckResult) -> None:
        """Record a health check result in the history."""
        with self._lock:
            if broker_name not in self._health_history:
                self._health_history[broker_name] = deque(maxlen=self.config.max_history_size)

            self._health_history[broker_name].append(result)

            # Trim old history based on retention time
            cutoff_time = now_ist() - timedelta(hours=self.config.history_retention_hours)
            while (self._health_history[broker_name] and
                   self._health_history[broker_name][0].timestamp < cutoff_time):
                self._health_history[broker_name].popleft()

    def _update_error_rates(self, broker_name: str) -> None:
        """Update error and success rates based on recent history."""
        if broker_name not in self._health_history:
            return

        history = self._health_history[broker_name]
        if not history:
            return

        # Calculate rates over the last 10 minutes
        cutoff_time = now_ist() - timedelta(minutes=10)
        recent_checks = [
            check for check in history
            if check.timestamp >= cutoff_time
        ]

        if not recent_checks:
            return

        total_checks = len(recent_checks)
        failed_checks = sum(1 for check in recent_checks if not check.success)
        successful_checks = total_checks - failed_checks

        # Error rate: failed checks per minute
        time_span_minutes = 10.0  # We're looking at last 10 minutes
        error_rate = (failed_checks / time_span_minutes) if time_span_minutes > 0 else 0.0
        success_rate = (successful_checks / total_checks) if total_checks > 0 else 0.0

        # Update metrics with exponential moving average
        alpha = 0.2  # More responsive to recent changes
        if broker_name in self._health_metrics:
            metrics = self._health_metrics[broker_name]
            metrics.error_rate = (alpha * error_rate) + ((1 - alpha) * metrics.error_rate)
            metrics.success_rate = (alpha * success_rate) + ((1 - alpha) * metrics.success_rate)

    def _get_last_success_time(self, broker_name: str) -> datetime | None:
        """Get the timestamp of the last successful health check."""
        if broker_name not in self._health_history:
            return None

        for check in reversed(self._health_history[broker_name]):
            if check.success:
                return check.timestamp
        return None

    def _get_last_error_time(self, broker_name: str) -> datetime | None:
        """Get the timestamp of the last failed health check."""
        if broker_name not in self._health_history:
            return None

        for check in reversed(self._health_history[broker_name]):
            if not check.success:
                return check.timestamp
        return None

    def _get_consecutive_errors(self, broker_name: str) -> int:
        """Get the number of consecutive failed health checks."""
        if broker_name not in self._health_history:
            return 0

        count = 0
        for check in reversed(self._health_history[broker_name]):
            if not check.success:
                count += 1
            else:
                break
        return count

    def _get_consecutive_successes(self, broker_name: str) -> int:
        """Get the number of consecutive successful health checks."""
        if broker_name not in self._health_history:
            return 0

        count = 0
        for check in reversed(self._health_history[broker_name]):
            if check.success:
                count += 1
            else:
                break
        return count

    def _consider_failover(self, broker_name: str) -> None:
        """Consider triggering failover for a broker with too many consecutive errors."""
        if not self.failover_manager or not self.config.enable_failover_integration:
            return

        # Check if this is the currently active broker in the failover manager
        active_broker = self.failover_manager.get_active_broker()
        if active_broker != broker_name:
            return  # Don't failover if it's not the active broker

        # Record the failure in the failover manager
        failover_triggered = self.failover_manager.record_failure(broker_name)
        if failover_triggered:
            next_broker = self.failover_manager.get_active_broker()
            self._logger.warning(f"Failover triggered for broker {broker_name} due to consecutive errors")
            # Send CRITICAL alert for failover - this goes to Telegram if configured
            alert_msg = f"🔄 BROKER FAILOVER: Switched from {broker_name} to {next_broker} due to consecutive failures"
            self._logger.critical(alert_msg)
            # Also try to send via notification service if available
            try:
                if hasattr(self, '_notification_service') and self._notification_service:
                    self._notification_service.send_alert(alert_msg, priority="CRITICAL")
            except (AttributeError, OSError):
                self._logger.debug("[BHS] Notification send failed (non-blocking)")

    def _monitoring_loop(self) -> None:
        """Main monitoring loop that runs in a separate thread."""
        self._logger.info("Broker health monitoring loop started")
        last_comprehensive_check = datetime.min

        while not self._stop_event.is_set():
            try:
                current_time = now_ist()

                # Perform health checks on all brokers
                for broker_name in self.broker_adapters.keys():
                    if not self._stop_event.is_set():
                        self.check_broker_health(broker_name)

                # Perform comprehensive check less frequently
                if (current_time - last_comprehensive_check).total_seconds() >= self.config.comprehensive_check_interval:
                    self._perform_comprehensive_health_check()
                    last_comprehensive_check = current_time

                # Sleep for a short interval before next round
                # Use the smallest interval to ensure we don't miss anything
                sleep_time = min(
                    self.config.connectivity_check_interval,
                    self.config.latency_check_interval,
                    self.config.error_rate_check_interval
                )
                self._stop_event.wait(sleep_time)  # This allows early termination

            except (ConnectionError, OSError, ValueError, AttributeError) as e:
                self._logger.error(f"Error in broker health monitoring loop: {e}", exc_info=True)
                # Sleep a bit before retrying to avoid tight error loops
                self._stop_event.wait(5.0)

        self._logger.info("Broker health monitoring loop stopped")

    def _perform_comprehensive_health_check(self) -> None:
        """Perform a comprehensive health check including rate limit checks."""
        self._logger.debug("Performing comprehensive health check")
        # This could include additional checks like rate limit status, etc.
        # For now, we rely on the regular checks which are quite comprehensive
        pass
