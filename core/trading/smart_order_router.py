"""Multi-Broker Smart Order Router (SOR) & Failover Engine.

Monitors multiple broker endpoints, evaluates latency, commission rates, and real-time health,
routing orders dynamically to the optimal broker with automatic failover fallback.

SUPERSEDED (2026-08-21): this module only ever picks between static, in-memory
``BrokerEndpoint`` dataclass state seeded with hardcoded latency/commission
numbers -- it never calls a real broker adapter. The genuinely wired, live
router is `core/execution/smart_router.py` (4 real routing strategies,
`health_check()`/`place_order()` against real broker adapters), which is
called from `core/services/execution_service.py::ExecutionService.
_attempt_order_execution()` via an opt-in `self._smart_router` path (see
`tests/test_execution_service.py::TestSmartRouterWiring`). This module is
kept only for backward compatibility with its existing direct tests
(`tests/test_competitor_features.py`, `tests/test_strategy_catalog.py`) --
do not add new call sites for it.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("smart_order_router")


@dataclass
class BrokerEndpoint:
    name: str
    is_active: bool = True
    latency_ms: float = 15.0
    commission_per_order: float = 20.0
    error_count: int = 0
    max_errors_before_disable: int = 3
    last_health_check: float = field(default_factory=time.time)

    def record_success(self, latency_ms: float) -> None:
        self.latency_ms = latency_ms
        self.error_count = max(0, self.error_count - 1)
        self.last_health_check = time.time()

    def record_failure(self) -> None:
        self.error_count += 1
        self.last_health_check = time.time()
        if self.error_count >= self.max_errors_before_disable:
            self.is_active = False
            log.warning(f"[SOR] Broker {self.name} disabled due to {self.error_count} consecutive errors")


class SmartOrderRouter:
    """Smart Order Router for multi-broker routing and failover handling."""

    def __init__(self, brokers: list[BrokerEndpoint] | None = None) -> None:
        self.brokers: dict[str, BrokerEndpoint] = {}
        if brokers:
            for b in brokers:
                self.brokers[b.name] = b
        else:
            # Default institutional broker fleet
            self.brokers["zerodha"] = BrokerEndpoint("zerodha", latency_ms=12.0, commission_per_order=20.0)
            self.brokers["angel_one"] = BrokerEndpoint("angel_one", latency_ms=18.0, commission_per_order=20.0)
            self.brokers["iifl"] = BrokerEndpoint("iifl", latency_ms=25.0, commission_per_order=15.0)
            self.brokers["paper_broker"] = BrokerEndpoint("paper_broker", latency_ms=1.0, commission_per_order=0.0)

    def select_best_broker(self, symbol: str, order_type: str = "LIMIT") -> BrokerEndpoint:
        """Select the optimal active broker based on latency and health status."""
        active = [b for b in self.brokers.values() if b.is_active and b.name != "paper_broker"]
        if not active:
            log.warning("[SOR] No active live brokers available! Falling back to paper_broker")
            fallback = self.brokers.get("paper_broker") or BrokerEndpoint("paper_broker")
            fallback.is_active = True
            return fallback

        # Sort by latency and low error count
        active.sort(key=lambda b: (b.latency_ms, b.error_count, b.commission_per_order))
        best = active[0]
        log.info(f"[SOR] Routed order for {symbol} to best broker: {best.name} (latency: {best.latency_ms}ms)")
        return best


    def execute_with_failover(self, order_details: dict[str, Any], execute_fn: Any) -> dict[str, Any]:
        """Execute an order with automatic failover across active brokers."""
        tried: list[str] = []

        while True:
            active_untried = [
                b for b in self.brokers.values()
                if b.is_active and b.name not in tried and b.name != "paper_broker"
            ]
            if not active_untried:
                log.critical(f"[SOR] All live brokers failed for order {order_details}. Falling back to paper_broker")
                paper = self.brokers.get("paper_broker")
                if paper:
                    paper.is_active = True
                    return {"status": "SUCCESS", "broker": "paper_broker", "failover": True, "tried": tried}
                return {"status": "FAILED", "reason": "ALL_BROKERS_DISABLED", "tried": tried}


            active_untried.sort(key=lambda b: (b.latency_ms, b.error_count))
            target_broker = active_untried[0]
            tried.append(target_broker.name)

            try:
                start_t = time.monotonic()
                res = execute_fn(target_broker.name, order_details)
                latency = (time.monotonic() - start_t) * 1000.0
                target_broker.record_success(latency)
                return {
                    "status": "SUCCESS",
                    "broker": target_broker.name,
                    "latency_ms": round(latency, 2),
                    "tried": tried,
                    "result": res,
                }
            except Exception as err:
                log.warning(f"[SOR] Broker {target_broker.name} failed execution ({err}). Triggering failover...")
                target_broker.record_failure()

    def get_router_status(self) -> dict[str, Any]:
        """Return the health and routing status of all managed broker endpoints."""
        return {
            "total_brokers": len(self.brokers),
            "active_brokers": [b.name for b in self.brokers.values() if b.is_active],
            "endpoints": {
                name: {
                    "active": b.is_active,
                    "latency_ms": b.latency_ms,
                    "error_count": b.error_count,
                    "commission": b.commission_per_order,
                }
                for name, b in self.brokers.items()
            },
        }
