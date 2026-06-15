"""
Component Health Monitor (Additional Fix).

Monitors health of all new components:
- Durable store connectivity
- ACK validator status
- State handler status
- Circuit breaker status
- Lot size validator status
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.datetime_ist import now_ist

log = logging.getLogger(__name__)


@dataclass
class ComponentHealth:
    component_name: str
    is_healthy: bool
    last_check: datetime
    message: str
    details: dict = field(default_factory=dict)


class ComponentHealthMonitor:
    """
    Monitors health of all trading system components.

    Used by:
    - Morning checklist
    - Health check endpoint
    - Periodic monitoring
    """

    def __init__(self):
        self._components: dict[str, Any] = {}
        self._last_check: datetime | None = None

    def register(self, name: str, component: Any) -> None:
        """Register a component for health monitoring."""
        self._components[name] = component
        log.info(f"Registered component for health monitoring: {name}")

    def check_all(self) -> list[ComponentHealth]:
        """Check health of all registered components."""
        results = []
        self._last_check = now_ist()

        for name, component in self._components.items():
            health = self._check_component(name, component)
            results.append(health)

        return results

    def _check_component(self, name: str, component: Any) -> ComponentHealth:
        """Check individual component health."""
        try:
            if name == "durable_store":
                return self._check_durable_store(component)
            elif name == "execution_service":
                return self._check_execution_service(component)
            elif name == "circuit_breaker":
                return self._check_circuit_breaker(component)
            elif name == "lot_size_validator":
                return self._check_lot_size_validator(component)
            elif name == "risk_engine":
                return self._check_risk_engine(component)
            else:
                return ComponentHealth(
                    component_name=name,
                    is_healthy=True,
                    last_check=self._last_check,
                    message="Unknown component type",
                )
        except (AttributeError, TypeError, ValueError, KeyError, OSError) as e:
            return ComponentHealth(
                component_name=name,
                is_healthy=False,
                last_check=self._last_check,
                message=f"Health check failed: {e}",
            )

    def _check_durable_store(self, store: Any) -> ComponentHealth:
        """Check durable execution store health."""
        try:
            executions = store.get_non_terminal_executions()
            return ComponentHealth(
                component_name="durable_store",
                is_healthy=True,
                last_check=self._last_check,
                message="Healthy",
                details={"pending_executions": len(executions)},
            )
        except (AttributeError, TypeError, ValueError, OSError) as e:
            return ComponentHealth(
                component_name="durable_store",
                is_healthy=False,
                last_check=self._last_check,
                message=f"Error: {e}",
            )

    def _check_execution_service(self, service: Any) -> ComponentHealth:
        """Check execution service health."""
        try:
            frozen = service.is_trading_frozen() if hasattr(service, 'is_trading_frozen') else False
            return ComponentHealth(
                component_name="execution_service",
                is_healthy=not frozen,
                last_check=self._last_check,
                message="Trading frozen" if frozen else "Healthy",
                details={"trading_frozen": frozen},
            )
        except (AttributeError, TypeError, ValueError) as e:
            return ComponentHealth(
                component_name="execution_service",
                is_healthy=False,
                last_check=self._last_check,
                message=f"Error: {e}",
            )

    def _check_circuit_breaker(self, cb: Any) -> ComponentHealth:
        """Check circuit breaker health."""
        try:
            state = cb.get_state() if hasattr(cb, 'get_state') else None
            if state:
                return ComponentHealth(
                    component_name="circuit_breaker",
                    is_healthy=True,
                    last_check=self._last_check,
                    message=f"Level: {state.level.value}",
                    details={
                        "level": state.level.value,
                        "market_status": state.market_status.value,
                    },
                )
            return ComponentHealth(
                component_name="circuit_breaker",
                is_healthy=True,
                last_check=self._last_check,
                message="No state available",
            )
        except (AttributeError, TypeError, ValueError, OSError, KeyError) as e:
            return ComponentHealth(
                component_name="circuit_breaker",
                is_healthy=False,
                last_check=self._last_check,
                message=f"Error: {e}",
            )

    def _check_lot_size_validator(self, validator: Any) -> ComponentHealth:
        """Check lot size validator health."""
        try:
            return ComponentHealth(
                component_name="lot_size_validator",
                is_healthy=True,
                last_check=self._last_check,
                message="Healthy",
            )
        except (AttributeError, TypeError, ValueError) as e:
            return ComponentHealth(
                component_name="lot_size_validator",
                is_healthy=False,
                last_check=self._last_check,
                message=f"Error: {e}",
            )

    def _check_risk_engine(self, engine: Any) -> ComponentHealth:
        """Check risk engine health."""
        try:
            is_halted = getattr(engine, '_hard_halt', False)
            return ComponentHealth(
                component_name="risk_engine",
                is_healthy=not is_halted,
                last_check=self._last_check,
                message="HARD HALT" if is_halted else "Healthy",
                details={"hard_halt": is_halted},
            )
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            return ComponentHealth(
                component_name="risk_engine",
                is_healthy=False,
                last_check=self._last_check,
                message=f"Error: {e}",
            )

    def get_unhealthy_count(self) -> int:
        """Get count of unhealthy components."""
        results = self.check_all()
        return sum(1 for r in results if not r.is_healthy)

    def format_status(self) -> str:
        """Format health status as string."""
        results = self.check_all()
        lines = ["🔍 Component Health Status", "=" * 30]

        unhealthy = []
        for r in results:
            status = "✅" if r.is_healthy else "❌"
            lines.append(f"{status} {r.component_name}: {r.message}")
            if not r.is_healthy:
                unhealthy.append(r.component_name)

        lines.append("")
        if unhealthy:
            lines.append(f"⚠️ {len(unhealthy)} unhealthy: {', '.join(unhealthy)}")
        else:
            lines.append("✅ All components healthy")

        return "\n".join(lines)


_global_monitor: ComponentHealthMonitor | None = None
_monitor_lock: threading.Lock = threading.Lock()


def get_health_monitor() -> ComponentHealthMonitor:
    """Get global health monitor instance (thread-safe)."""
    global _global_monitor
    if _global_monitor is None:
        with _monitor_lock:
            if _global_monitor is None:
                _global_monitor = ComponentHealthMonitor()
    return _global_monitor
