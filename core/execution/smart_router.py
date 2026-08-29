"""Multi-Broker Smart Router (v2.55).

Routes orders to the best available broker based on configurable criteria:
  - Fee structure (broker with lowest per-lot fees)
  - Availability (brokers that are currently connected/healthy)
  - Execution quality (based on historical fill rates and slippage)

Designed to work with the existing broker adapter layer
(core/adapters/broker_adapters.py).

Usage:
    router = SmartRouter(routers={"KITE": adapter1, "ANGEL": adapter2}, config={})
    best = router.select_broker("NIFTY", "CALL", 23600)
    order_id = router.route_order(best, "NIFTY", "CALL", 1, 23600)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

_DEFAULT_FEES: dict[str, float] = {
    "KITE": 20.0,   # Zerodha: Rs20 per order (or 0.03% for options)
    "ANGEL": 15.0,  # Angel One: Rs15 per order
    "PAPER": 0.0,   # Paper trading: zero fees
}

_DEFAULT_STRATEGY: str = "lowest_fee"  # lowest_fee | round_robin | weighted


@dataclass
class BrokerScore:
    """Scoring result for broker selection."""

    broker: str
    score: float          # Composite score (higher = better)
    fee_score: float      # Normalized fee component
    health_score: float   # Normalized health component
    latency_score: float  # Normalized latency component
    execution_score: float  # Normalized execution quality component
    is_available: bool     # Whether broker is currently connected


@dataclass
class RouterConfig:
    """Configuration for the Smart Router.

    Attributes:
        strategy: Selection strategy (lowest_fee, round_robin, weighted)
        preferred_broker: Broker to prefer (empty = auto-select)
        min_fill_rate: Minimum acceptable fill rate (0.0-1.0)
        blacklisted_brokers: Brokers to never route to
        fee_weights: Per-broker fee overrides (broker_name -> fee_per_lot)
        broker_timeout: Seconds before marking broker as unavailable
        round_robin_prefix: Key prefix for round-robin state persistence
    """

    strategy: str = _DEFAULT_STRATEGY
    preferred_broker: str = ""
    min_fill_rate: float = 0.5
    blacklisted_brokers: set[str] = field(default_factory=set)
    fee_weights: dict[str, float] = field(default_factory=dict)
    broker_timeout: float = 30.0
    round_robin_prefix: str = "smart_router_rr"


@dataclass
class RouteResult:
    """Result of routing an order to a broker.

    Attributes:
        success: Whether the order was accepted by the broker
        broker: Broker that was used
        order_id: Order ID returned by the broker (empty on failure)
        fee_charged: Fee charged by the broker for this order
        latency_ms: Time taken to route and execute
        error: Error message (empty on success)
    """

    success: bool
    broker: str
    order_id: str
    fee_charged: float = 0.0
    latency_ms: float = 0.0
    error: str = ""


# ── Smart Router ─────────────────────────────────────────────────────────

class SmartRouter:
    """Routes orders to the best available broker.

    Maintains per-broker state for health, latency, and execution quality.
    Thread-safe via internal lock.
    """

    def __init__(
        self,
        routers: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the Smart Router.

        Args:
            routers: Dict mapping broker names (e.g., "KITE", "ANGEL") to
                     their BrokerAdapter instances.
            config: Configuration dict (RouterConfig.from_dict will be applied).
        """
        self._routers: dict[str, Any] = dict(routers)
        self._cfg = RouterConfig(**{
            k: v for k, v in (config or {}).items()
            if k in RouterConfig.__dataclass_fields__
        }) if config else RouterConfig()

        # Merge fee config and strategy overrides
        if config:
            if "fee_weights" in config and isinstance(config["fee_weights"], dict):
                self._cfg.fee_weights.update(config["fee_weights"])
            if "BROKER_FEES" in config and isinstance(config["BROKER_FEES"], dict):
                self._cfg.fee_weights.update(config["BROKER_FEES"])
            if "SMART_ROUTER_STRATEGY" in config:
                self._cfg.strategy = str(config["SMART_ROUTER_STRATEGY"])
            if "SMART_ROUTER_TIMEOUT_SEC" in config:
                self._cfg.broker_timeout = float(config["SMART_ROUTER_TIMEOUT_SEC"])

        # Per-broker state
        self._health: dict[str, bool] = {name: True for name in routers}
        self._latency: dict[str, list[float]] = {name: [] for name in routers}
        self._fill_rates: dict[str, list[bool]] = {name: [] for name in routers}
        self._last_healthy: dict[str, float] = {
            name: time.time() for name in routers
        }
        # Round-robin state for compatible strategies
        self._rr_index: int = 0
        # Thread safety — protects all mutable shared state
        self._lock = threading.RLock()

    @classmethod
    def from_broker_adapters(
        cls,
        primary_adapter: Any,
        secondary_adapter: Any | None = None,
        config: dict[str, Any] | None = None,
    ) -> SmartRouter:
        """Construct a SmartRouter from primary and optional secondary adapters."""
        routers: dict[str, Any] = {}
        primary_name = getattr(primary_adapter, "name", "PRIMARY") or "PRIMARY"
        routers[str(primary_name).upper()] = primary_adapter
        if secondary_adapter is not None:
            secondary_name = getattr(secondary_adapter, "name", "SECONDARY") or "SECONDARY"
            routers[str(secondary_name).upper()] = secondary_adapter
        return cls(routers=routers, config=config)

    # ── Broker selection ─────────────────────────────────────────────────

    def available_brokers(self) -> list[str]:
        """Return list of currently available (connected) broker names.

        Thread-safe: acquires internal lock.
        """
        now = time.time()
        available: list[str] = []
        with self._lock:
            for name, adapter in self._routers.items():
                if name in self._cfg.blacklisted_brokers:
                    continue
                is_available = self._health.get(name, True)
                # Check timeout
                last = self._last_healthy.get(name, 0)
                if not is_available and (now - last) < self._cfg.broker_timeout:
                    continue
                if not is_available:
                    # Re-check health after timeout
                    try:
                        h = getattr(adapter, "health_check", lambda: {})(9999)
                        if isinstance(h, dict) and h.get("status") == "healthy":
                            self._health[name] = True
                            self._last_healthy[name] = now
                            is_available = True
                    except (AttributeError, TypeError, OSError, ConnectionError):
                        pass
                # Verify availability via the adapter
                if is_available:
                    try:
                        status = str(getattr(adapter, "get_order_status", lambda _: "UNKNOWN")("_test_"))
                        if status in ("COMPLETE", "UNKNOWN", "PENDING", "REJECTED"):
                            is_available = True
                    except (AttributeError, TypeError, OSError, ConnectionError):
                        pass
                if is_available:
                    available.append(name)
        return available

    def score_broker(self, broker: str) -> BrokerScore | None:
        """Compute a composite score for a broker.

        Higher score = better choice for routing.

        Returns None if the broker is unavailable.

        Thread-safe: acquires internal lock.
        """
        if broker in self._cfg.blacklisted_brokers:
            return None

        adapter = self._routers.get(broker)
        if adapter is None:
            return None

        is_available = broker in self.available_brokers()

        with self._lock:
            # Fee score (lower fee = higher score, normalized 0-1)
            all_fees = dict(_DEFAULT_FEES)
            all_fees.update(self._cfg.fee_weights)
            actual_fee = all_fees.get(broker, 20.0)
            max_fee = max(all_fees.values()) if all_fees else 20.0
            fee_score = 1.0 - (actual_fee / max_fee) if max_fee > 0 else 1.0

            # Health score
            health_score = 0.0 if not is_available else 1.0

            # Latency score (lower latency = higher score)
            latencies = self._latency.get(broker, [])
            if latencies:
                avg_lat = sum(latencies) / len(latencies)
                latency_score = max(0.0, 1.0 - (avg_lat / 1000.0))  # normalize to 1s
            else:
                latency_score = 0.5  # neutral for no data

            # Execution quality score
            fills = self._fill_rates.get(broker, [])
            if fills:
                exec_score = sum(fills) / len(fills)
            else:
                exec_score = 0.5  # neutral for no data

        # Composite: weighted average
        weights = {"fee": 0.35, "health": 0.30, "latency": 0.15, "execution": 0.20}
        score = (
            fee_score * weights["fee"]
            + health_score * weights["health"]
            + latency_score * weights["latency"]
            + exec_score * weights["execution"]
        )

        return BrokerScore(
            broker=broker,
            score=round(score, 4),
            fee_score=round(fee_score, 4),
            health_score=round(health_score, 4),
            latency_score=round(latency_score, 4),
            execution_score=round(exec_score, 4),
            is_available=is_available,
        )

    def select_broker(
        self,
        symbol: str = "",
        direction: str = "",
        strike: int = 0,
    ) -> str | None:
        """Select the best broker for a given order.

        Args:
            symbol: Index or symbol name (optional, for future routing rules)
            direction: CALL or PUT (optional)
            strike: Strike price (optional)

        Returns:
            Broker name (e.g., "KITE") or None if no broker available.
        """
        available = self.available_brokers()
        if not available:
            _log.warning("[SMART_ROUTER] No brokers available for routing")
            return None

        # Check preferred broker
        if self._cfg.preferred_broker and self._cfg.preferred_broker in available:
            return self._cfg.preferred_broker

        strategy = self._cfg.strategy

        if strategy == "lowest_fee":
            return self._select_lowest_fee(available)
        elif strategy == "round_robin":
            return self._select_round_robin(available)
        elif strategy == "weighted":
            return self._select_weighted(available)
        else:
            return available[0]  # fallback: first available

    def _select_lowest_fee(self, available: list[str]) -> str:
        """Select broker with lowest fees.

        Merges DEFAULT_FEES with any configured fee_weights overrides.
        """
        all_fees = dict(_DEFAULT_FEES)
        all_fees.update(self._cfg.fee_weights)
        best = min(available, key=lambda b: all_fees.get(b, 20.0))
        best_fee = all_fees.get(best, 20.0)
        _log.debug("[SMART_ROUTER] Lowest-fee selection: %s (fee=%s)", best, best_fee)
        return best

    def _select_round_robin(self, available: list[str]) -> str:
        """Select broker using round-robin.

        Thread-safe: acquires internal lock for index mutation.
        """
        with self._lock:
            idx = self._rr_index % len(available)
            self._rr_index = (self._rr_index + 1) % 1000
        broker = available[idx]
        _log.debug("[SMART_ROUTER] Round-robin selection: %s (idx=%s)", broker, idx)
        return broker

    def _select_weighted(self, available: list[str]) -> str:
        """Select broker with highest composite score."""
        best = available[0]
        best_score = -1.0
        for broker in available:
            score_data = self.score_broker(broker)
            if score_data and score_data.score > best_score:
                best = broker
                best_score = score_data.score
        _log.debug("[SMART_ROUTER] Weighted selection: %s (score=%s)", best, best_score)
        return best

    # ── Order routing ───────────────────────────────────────────────────

    def route_order(
        self,
        broker: str,
        symbol: str,
        direction: str,
        qty: int,
        strike: int,
    ) -> RouteResult:
        """Route an order to a specific broker.

        Args:
            broker: Target broker name (e.g., "KITE")
            symbol: Index or symbol name (e.g., "NIFTY")
            direction: "CALL" or "PUT"
            qty: Number of lots
            strike: Strike price

        Returns:
            RouteResult with success status and order ID.

        Thread-safe: acquires internal lock for state mutations.
        """
        start = time.time()
        adapter = self._routers.get(broker)
        if adapter is None:
            return RouteResult(
                success=False, broker=broker, order_id="",
                error=f"Broker '{broker}' not registered",
            )

        try:
            order_id = adapter.place_order(symbol, direction, qty, strike)
            elapsed = (time.time() - start) * 1000  # ms

            with self._lock:
                # Record latency
                self._latency.setdefault(broker, []).append(elapsed)
                # Keep only last 50 measurements
                if len(self._latency[broker]) > 50:
                    self._latency[broker] = self._latency[broker][-50:]

                if order_id:
                    self._health[broker] = True
                    self._last_healthy[broker] = time.time()
                    fee = self._cfg.fee_weights.get(broker, _DEFAULT_FEES.get(broker, 0.0))
                    return RouteResult(
                        success=True, broker=broker, order_id=order_id,
                        fee_charged=fee, latency_ms=round(elapsed, 1),
                    )
                else:
                    self._fill_rates.setdefault(broker, []).append(False)
                    return RouteResult(
                        success=False, broker=broker, order_id="",
                        error="Broker returned no order ID",
                        latency_ms=round(elapsed, 1),
                    )

        except (ValueError, TypeError, OSError, ConnectionError, RuntimeError) as exc:
            elapsed = (time.time() - start) * 1000
            with self._lock:
                self._health[broker] = False
                self._fill_rates.setdefault(broker, []).append(False)
            return RouteResult(
                success=False, broker=broker, order_id="",
                error=f"Order placement failed: {exc}",
                latency_ms=round(elapsed, 1),
            )

    def route_to_best(
        self,
        symbol: str,
        direction: str,
        qty: int,
        strike: int,
    ) -> RouteResult:
        """Automatically select the best broker and route the order.

        Args:
            symbol: Index or symbol name
            direction: "CALL" or "PUT"
            qty: Number of lots
            strike: Strike price

        Returns:
            RouteResult from the selected broker.
        """
        broker = self.select_broker(symbol, direction, strike)
        if broker is None:
            return RouteResult(
                success=False, broker="", order_id="",
                error="No available broker found",
            )
        return self.route_order(broker, symbol, direction, qty, strike)

    # ── Health & metrics ───────────────────────────────────────────────

    def health_check(self) -> dict[str, Any]:
        """Return health status of all registered brokers.

        Thread-safe: acquires internal lock.
        """
        available = self.available_brokers()
        result: dict[str, Any] = {
            "status": "healthy" if available else "degraded",
            "total_brokers": len(self._routers),
            "available": len(available),
            "strategy": self._cfg.strategy,
        }
        with self._lock:
            for name in self._routers:
                score_data = self.score_broker(name)
                result[name] = {
                    "available": name in available,
                    "score": score_data.score if score_data else 0.0,
                    "avg_latency_ms": (
                        round(sum(self._latency.get(name, [])) / max(len(self._latency.get(name, [])), 1), 1)
                    ),
                    "fill_rate": (
                        round(sum(self._fill_rates.get(name, [])) / max(len(self._fill_rates.get(name, [])), 1), 3)
                        if self._fill_rates.get(name) else 0.5
                    ),
                }
        return result

    def record_fill(self, broker: str, success: bool) -> None:
        """Record a fill result for execution quality tracking.

        Args:
            broker: Broker that filled the order
            success: Whether the fill was successful

        Thread-safe: acquires internal lock.
        """
        with self._lock:
            self._fill_rates.setdefault(broker, []).append(success)
            if len(self._fill_rates[broker]) > 100:
                self._fill_rates[broker] = self._fill_rates[broker][-100:]


__all__ = [
    "BrokerScore",
    "RouteResult",
    "RouterConfig",
    "SmartRouter",
]
