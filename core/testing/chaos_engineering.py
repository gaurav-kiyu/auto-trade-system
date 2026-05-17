"""
Chaos Engineering - Item 30

Deliberately break components to test resilience:
- broker timeout
- stale feed
- gap open
- circuit breaker
- partial fill
- reconnect storm

Examples:
- kill broker feed mid-session

Massive resilience testing.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.time_provider import time_provider

_log = logging.getLogger(__name__)


class ChaosScenario(Enum):
    """Chaos testing scenarios"""
    BROKER_TIMEOUT = "BROKER_TIMEOUT"
    STALE_FEED = "STALE_FEED"
    GAP_OPEN = "GAP_OPEN"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
    PARTIAL_FILL = "PARTIAL_FILL"
    RECONNECT_STORM = "RECONNECT_STORM"
    NETWORK_LATENCY = "NETWORK_LATENCY"
    ORDER_REJECTION = "ORDER_REJECTION"


@dataclass
class ChaosConfig:
    """Chaos injection configuration"""
    scenario: ChaosScenario
    probability: float = 0.1
    delay_ms: int = 0
    failure_rate: float = 0.0
    enabled: bool = False


@dataclass
class ChaosEvent:
    """Chaos injection event"""
    event_id: str
    scenario: ChaosScenario
    timestamp: str
    description: str
    success: bool


class ChaosEngine:
    """
    Chaos engineering engine.
    Injects failures to test system resilience.
    """

    def __init__(self):
        self._configs: dict[ChaosScenario, ChaosConfig] = {}
        self._events: list[ChaosEvent] = []
        self._lock = threading.Lock()
        self._injections_enabled = False

        self._setup_default_configs()

    def _setup_default_configs(self) -> None:
        """Setup default chaos configurations"""
        scenarios = [
            (ChaosScenario.BROKER_TIMEOUT, 0.05, 5000, 0.1),
            (ChaosScenario.STALE_FEED, 0.1, 0, 0.0),
            (ChaosScenario.GAP_OPEN, 0.02, 0, 0.0),
            (ChaosScenario.CIRCUIT_BREAKER, 0.01, 0, 0.0),
            (ChaosScenario.PARTIAL_FILL, 0.15, 0, 0.0),
            (ChaosScenario.RECONNECT_STORM, 0.05, 0, 0.0),
            (ChaosScenario.NETWORK_LATENCY, 0.2, 1000, 0.0),
            (ChaosScenario.ORDER_REJECTION, 0.05, 0, 0.15),
        ]

        for scenario, prob, delay, failure in scenarios:
            self._configs[scenario] = ChaosConfig(
                scenario=scenario,
                probability=prob,
                delay_ms=delay,
                failure_rate=failure,
                enabled=False,
            )

    def enable_injections(self) -> None:
        """Enable chaos injections"""
        self._injections_enabled = True
        _log.warning("CHAOS MODE ENABLED - injections will occur")

    def disable_injections(self) -> None:
        """Disable chaos injections"""
        self._injections_enabled = False
        _log.info("Chaos mode disabled")

    def is_enabled(self) -> bool:
        """Check if chaos mode is enabled"""
        return self._injections_enabled

    def configure_scenario(
        self,
        scenario: ChaosScenario,
        probability: float = None,
        delay_ms: int = None,
        failure_rate: float = None,
    ) -> None:
        """Configure specific chaos scenario"""
        config = self._configs.get(scenario, ChaosConfig(scenario=scenario))

        if probability is not None:
            config.probability = probability
        if delay_ms is not None:
            config.delay_ms = delay_ms
        if failure_rate is not None:
            config.failure_rate = failure_rate

        self._configs[scenario] = config
        _log.info(f"Configured {scenario.value}: prob={config.probability}, delay={config.delay_ms}ms")

    def enable_scenario(self, scenario: ChaosScenario) -> None:
        """Enable specific scenario"""
        if scenario in self._configs:
            self._configs[scenario].enabled = True
            _log.info(f"Enabled chaos scenario: {scenario.value}")

    def disable_scenario(self, scenario: ChaosScenario) -> None:
        """Disable specific scenario"""
        if scenario in self._configs:
            self._configs[scenario].enabled = False
            _log.info(f"Disabled chaos scenario: {scenario.value}")

    def inject(self, scenario: ChaosScenario) -> ChaosEvent | None:
        """
        Inject chaos if conditions are met.
        Returns ChaosEvent if injection occurred.
        """
        if not self._injections_enabled:
            return None

        config = self._configs.get(scenario)
        if not config or not config.enabled:
            return None

        if random.random() > config.probability:
            return None

        event = ChaosEvent(
            event_id=f"CHAOS-{int(time_provider.get_ts())}",
            scenario=scenario,
            timestamp=time_provider.format_ts(),
            description=self._get_description(scenario),
            success=False,
        )

        if config.delay_ms > 0:
            time.sleep(config.delay_ms / 1000.0)

        if random.random() < config.failure_rate:
            event.success = False
            _log.warning(f"CHAOS INJECTED: {scenario.value} - failure")
        else:
            event.success = True
            _log.warning(f"CHAOS INJECTED: {scenario.value} - delay")

        with self._lock:
            self._events.append(event)

        return event

    def should_fail_operation(self, scenario: ChaosScenario) -> bool:
        """Check if operation should fail based on chaos config"""
        if not self._injections_enabled:
            return False

        config = self._configs.get(scenario)
        if not config or not config.enabled:
            return False

        return random.random() < config.failure_rate

    def get_delay(self, scenario: ChaosScenario) -> int:
        """Get delay for scenario"""
        config = self._configs.get(scenario)
        if not config or not config.enabled:
            return 0

        return config.delay_ms

    def _get_description(self, scenario: ChaosScenario) -> str:
        """Get description for scenario"""
        descriptions = {
            ChaosScenario.BROKER_TIMEOUT: "Broker API timeout",
            ChaosScenario.STALE_FEED: "Market data feed stale",
            ChaosScenario.GAP_OPEN: "Gap open in market",
            ChaosScenario.CIRCUIT_BREAKER: "Circuit breaker triggered",
            ChaosScenario.PARTIAL_FILL: "Only partial fill received",
            ChaosScenario.RECONNECT_STORM: "Reconnection storm",
            ChaosScenario.NETWORK_LATENCY: "Network latency spike",
            ChaosScenario.ORDER_REJECTED: "Order rejected by broker",
        }
        return descriptions.get(scenario, "Unknown chaos")

    def get_stats(self) -> dict[str, Any]:
        """Get chaos engine statistics"""
        with self._lock:
            total = len(self._events)
            failures = sum(1 for e in self._events if not e.success)

            scenario_counts = {}
            for event in self._events:
                scenario_counts[event.scenario.value] = scenario_counts.get(event.scenario.value, 0) + 1

            return {
                "enabled": self._injections_enabled,
                "total_injections": total,
                "failures": failures,
                "scenario_distribution": scenario_counts,
            }

    def get_events(self, limit: int = 100) -> list[ChaosEvent]:
        """Get recent chaos events"""
        with self._lock:
            return self._events[-limit:]

    def reset_stats(self) -> None:
        """Reset statistics"""
        with self._lock:
            self._events.clear()
            _log.info("Chaos stats reset")


_chaos_engine: ChaosEngine | None = None
_engine_lock = threading.Lock()


def get_chaos_engine() -> ChaosEngine:
    """Get singleton chaos engine"""
    global _chaos_engine
    with _engine_lock:
        if _chaos_engine is None:
            _chaos_engine = ChaosEngine()
        return _chaos_engine
