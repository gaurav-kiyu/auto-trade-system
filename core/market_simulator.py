"""
Market Simulator — Latency, Broker Rejection, Gap Open & Exchange Failure Simulation.

Extends the core simulation capabilities with realistic failure mode injection:
  - Random latency distribution (configurable mean/std)
  - Broker rejection simulation (by type: INSUFFICIENT_MARGIN, ORDER_REJECTED, etc.)
  - Gap open simulation (overnight/weekend price jumps)
  - Exchange failure simulation (circuit breaker triggers, trading halts)
  - Combined scenario injection

All failures are configurable with probabilities, enabling stress testing
of system resilience under adverse conditions.

Usage
-----
    from core.market_simulator import MarketSimulator

    sim = MarketSimulator()
    result = sim.simulate_order(order_data, inject_failures=True)
    print(result.status, result.latency_ms)
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

MAX_LATENCY_MS = 30000  # 30 seconds max simulated latency


class RejectionType(Enum):
    """Types of broker rejection to simulate."""
    NONE = "NONE"
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    ORDER_REJECTED = "ORDER_REJECTED"
    INVALID_PRICE = "INVALID_PRICE"
    EXCEEDS_POSITION_LIMIT = "EXCEEDS_POSITION_LIMIT"
    RATE_LIMITED = "RATE_LIMITED"
    BROKER_UNAVAILABLE = "BROKER_UNAVAILABLE"
    DUPLICATE_ORDER = "DUPLICATE_ORDER"


class ExchangeFailureType(Enum):
    """Types of exchange failure to simulate."""
    NONE = "NONE"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"       # Market-wide halt
    TRADING_HALT = "TRADING_HALT"              # Single security halt
    GAP_UP = "GAP_UP"                          # Price gap up at open
    GAP_DOWN = "GAP_DOWN"                      # Price gap down at open
    NO_DATA = "NO_DATA"                        # Feed failure
    MATCHING_ENGINE_DOWN = "MATCHING_ENGINE_DOWN"  # Exchange system failure


# ── Data structures ─────────────────────────────────────────────────────────


@dataclass
class SimulatedOrderResult:
    """Result of a simulated order with potential failure injection.

    Attributes:
        order_id: The order identifier.
        status: ACCEPTED, REJECTED, TIMEOUT, or FAILED.
        latency_ms: Simulated latency in milliseconds.
        rejection_type: Type of rejection if rejected.
        rejection_reason: Human-readable rejection reason.
        filled_quantity: Quantity filled (may be partial).
        fill_price: Price at which fill occurred.
        exchange_failure: Exchange failure type if any.
        exchange_halt_duration_sec: Duration of exchange halt.
        gap_open_pct: Price gap percentage if gap open occurred.
        details: Additional metadata.
    """
    order_id: str = ""
    status: str = "ACCEPTED"
    latency_ms: float = 0.0
    rejection_type: str = "NONE"
    rejection_reason: str = ""
    filled_quantity: int = 0
    fill_price: float = 0.0
    exchange_failure: str = "NONE"
    exchange_halt_duration_sec: int = 0
    gap_open_pct: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 2),
            "rejection_type": self.rejection_type,
            "rejection_reason": self.rejection_reason,
            "filled_quantity": self.filled_quantity,
            "fill_price": round(self.fill_price, 4),
            "exchange_failure": self.exchange_failure,
            "exchange_halt_duration_sec": self.exchange_halt_duration_sec,
            "gap_open_pct": round(self.gap_open_pct, 4),
        }

    def summary(self) -> str:
        parts = [f"Order {self.order_id}: {self.status}"]
        if self.status == "REJECTED":
            parts.append(f"  Reason: {self.rejection_reason}")
        if self.latency_ms > 100:
            parts.append(f"  Latency: {self.latency_ms:.0f}ms (SLOW)")
        elif self.latency_ms > 0:
            parts.append(f"  Latency: {self.latency_ms:.0f}ms")
        if self.exchange_failure != "NONE":
            parts.append(f"  Exchange: {self.exchange_failure}")
        if self.gap_open_pct != 0.0:
            parts.append(f"  Gap Open: {self.gap_open_pct:+.2f}%")
        if self.filled_quantity > 0:
            parts.append(f"  Fill: {self.filled_quantity} @ ₹{self.fill_price:.2f}")
        return "\n".join(parts)


@dataclass
class SimulatorConfig:
    """Configuration for the market simulator.

    Attributes:
        latency_mean_ms: Mean simulated latency in ms (default 50).
        latency_std_ms: Standard deviation of latency (default 20).
        rejection_probability: Probability of broker rejection (0-1).
        rejection_types: List of RejectionType values to sample from.
        exchange_failure_probability: Probability of exchange failure (0-1).
        gap_open_probability: Probability of gap open event (0-1).
        gap_open_max_pct: Maximum gap open percentage (default 5.0).
        circuit_breaker_probability: Probability of circuit breaker (0-1).
        partial_fill_probability: Probability of partial fill (0-1).
        partial_fill_min_pct: Minimum partial fill percentage (0-1).
        partial_fill_max_pct: Maximum partial fill percentage (0-1).
        seed: Random seed for reproducibility.
    """
    latency_mean_ms: float = 50.0
    latency_std_ms: float = 20.0
    rejection_probability: float = 0.05
    rejection_types: list[str] = field(default_factory=lambda: [
        "INSUFFICIENT_MARGIN", "ORDER_REJECTED", "INVALID_PRICE",
        "RATE_LIMITED", "DUPLICATE_ORDER",
    ])
    exchange_failure_probability: float = 0.01
    gap_open_probability: float = 0.02
    gap_open_max_pct: float = 5.0
    circuit_breaker_probability: float = 0.005
    partial_fill_probability: float = 0.10
    partial_fill_min_pct: float = 0.1
    partial_fill_max_pct: float = 0.9
    seed: int | None = None


# ── Market Simulator ─────────────────────────────────────────────────────────


class MarketSimulator:
    """Simulates market conditions with configurable failure injection.

    Designed for testing system resilience under adverse conditions
    including network latency, broker rejections, exchange failures,
    gap opens, and circuit breaker events.

    Use cases:
      - Test order retry logic under broker rejection
      - Validate timeout handling with simulated latency
      - Verify gap open protection logic
      - Stress test circuit breaker responses
      - Test partial fill handling
    """

    def __init__(self, config: SimulatorConfig | None = None):
        self._config = config or SimulatorConfig()
        self._rng = random.Random(self._config.seed)
        self._rejection_reasons: dict[str, str] = {
            "INSUFFICIENT_MARGIN": "Insufficient margin available for this order",
            "ORDER_REJECTED": "Order rejected by broker compliance checks",
            "INVALID_PRICE": "Price is outside permitted range for this instrument",
            "EXCEEDS_POSITION_LIMIT": "Position limit exceeded for this instrument",
            "RATE_LIMITED": "API rate limit exceeded, please retry",
            "BROKER_UNAVAILABLE": "Broker service temporarily unavailable",
            "DUPLICATE_ORDER": "Duplicate order detected — order already submitted",
        }
        self._failure_count: int = 0
        self._total_orders: int = 0

    @property
    def failure_rate(self) -> float:
        """Current failure rate across all simulated orders."""
        if self._total_orders == 0:
            return 0.0
        return self._failure_count / self._total_orders

    def reset(self) -> None:
        """Reset statistics and re-seed the RNG."""
        self._failure_count = 0
        self._total_orders = 0
        if self._config.seed is not None:
            self._rng = random.Random(self._config.seed)

    # ── Latency simulation ─────────────────────────────────────────────

    def _simulate_latency(self) -> float:
        """Simulate network latency in milliseconds.

        Uses a truncated normal distribution. Returns a non-negative
        latency value capped at MAX_LATENCY_MS.

        Returns:
            Simulated latency in milliseconds.
        """
        latency = self._rng.gauss(self._config.latency_mean_ms, self._config.latency_std_ms)
        return max(0.0, min(latency, MAX_LATENCY_MS))

    # ── Rejection simulation ───────────────────────────────────────────

    def _simulate_rejection(self) -> tuple[str, str]:
        """Simulate broker rejection.

        Returns:
            (rejection_type, rejection_reason) tuple.
            If no rejection, returns ("NONE", "").
        """
        if self._rng.random() >= self._config.rejection_probability:
            return "NONE", ""

        rejection_type = self._rng.choice(self._config.rejection_types)
        reason = self._rejection_reasons.get(rejection_type, "Unknown rejection reason")
        return rejection_type, reason

    # ── Exchange failure simulation ────────────────────────────────────

    def _simulate_exchange_failure(self) -> tuple[str, int, float]:
        """Simulate exchange-level failure.

        Returns:
            (failure_type, halt_duration_sec, gap_open_pct) tuple.
        """
        roll = self._rng.random()

        # Circuit breaker
        if roll < self._config.circuit_breaker_probability:
            halt_duration = self._rng.randint(15, 45)  # 15-45 minute halt
            return ExchangeFailureType.CIRCUIT_BREAKER.value, halt_duration, 0.0

        # Gap open
        if roll < self._config.circuit_breaker_probability + self._config.gap_open_probability:
            gap_pct = self._rng.uniform(-self._config.gap_open_max_pct, self._config.gap_open_max_pct)
            direction = ExchangeFailureType.GAP_UP if gap_pct > 0 else ExchangeFailureType.GAP_DOWN
            return direction.value, 0, round(gap_pct, 2)

        # Exchange failure
        remaining = roll - self._config.circuit_breaker_probability - self._config.gap_open_probability
        if remaining < self._config.exchange_failure_probability:
            failure_types = [ExchangeFailureType.TRADING_HALT.value,
                             ExchangeFailureType.NO_DATA.value,
                             ExchangeFailureType.MATCHING_ENGINE_DOWN.value]
            failure = self._rng.choice(failure_types)
            return failure, self._rng.randint(5, 60), 0.0

        return ExchangeFailureType.NONE.value, 0, 0.0

    # ── Partial fill simulation ────────────────────────────────────────

    def _simulate_fill(self, quantity: int, price: float) -> tuple[int, float]:
        """Simulate order fill (full or partial).

        Args:
            quantity: Requested quantity.
            price: Expected fill price.

        Returns:
            (filled_quantity, fill_price) tuple.
        """
        if self._rng.random() < self._config.partial_fill_probability:
            fill_pct = self._rng.uniform(
                self._config.partial_fill_min_pct,
                self._config.partial_fill_max_pct,
            )
            filled = max(1, int(quantity * fill_pct))
            # Slight slippage on partial fills
            slip = self._rng.uniform(-0.001, 0.002)
            return filled, round(price * (1 + slip), 4)
        else:
            return quantity, price

    # ── Main simulation method ─────────────────────────────────────────

    def simulate_order(self, order_id: str, quantity: int, price: float,
                       symbol: str = "", side: str = "BUY",
                       inject_failures: bool = True) -> SimulatedOrderResult:
        """Simulate a single order with potential failure injection.

        Args:
            order_id: Unique order identifier.
            quantity: Requested order quantity.
            price: Expected fill price.
            symbol: Trading symbol (for context).
            side: BUY or SELL.
            inject_failures: If True, inject failures based on configured probabilities.

        Returns:
            SimulatedOrderResult with full simulation details.
        """
        self._total_orders += 1
        latency = self._simulate_latency()

        # If no failure injection, return a clean fill
        if not inject_failures:
            return SimulatedOrderResult(
                order_id=order_id,
                status="ACCEPTED",
                latency_ms=latency,
                filled_quantity=quantity,
                fill_price=price,
            )

        # Check for exchange failure (highest priority)
        failure_type, halt_duration, gap_pct = self._simulate_exchange_failure()
        if failure_type != ExchangeFailureType.NONE.value:
            self._failure_count += 1
            status = "FAILED" if failure_type in (ExchangeFailureType.NO_DATA.value,
                                                   ExchangeFailureType.MATCHING_ENGINE_DOWN.value) else "TIMEOUT"
            return SimulatedOrderResult(
                order_id=order_id,
                status=status,
                latency_ms=latency,
                exchange_failure=failure_type,
                exchange_halt_duration_sec=halt_duration,
                gap_open_pct=gap_pct,
                details={"symbol": symbol, "side": side},
            )

        # Check for broker rejection
        rejection_type, rejection_reason = self._simulate_rejection()
        if rejection_type != "NONE":
            self._failure_count += 1
            return SimulatedOrderResult(
                order_id=order_id,
                status="REJECTED",
                latency_ms=latency,
                rejection_type=rejection_type,
                rejection_reason=rejection_reason,
                details={"symbol": symbol, "side": side},
            )

        # Simulate fill (possibly partial)
        filled_qty, fill_price = self._simulate_fill(quantity, price)

        return SimulatedOrderResult(
            order_id=order_id,
            status="ACCEPTED",
            latency_ms=latency,
            filled_quantity=filled_qty,
            fill_price=fill_price,
            details={"symbol": symbol, "side": side, "requested_quantity": quantity},
        )

    def simulate_batch(self, orders: list[dict[str, Any]],
                       inject_failures: bool = True) -> list[SimulatedOrderResult]:
        """Simulate a batch of orders.

        Args:
            orders: List of order dicts, each with 'id', 'quantity', 'price',
                    and optional 'symbol' and 'side'.
            inject_failures: If True, inject failures.

        Returns:
            List of SimulatedOrderResult.
        """
        results: list[SimulatedOrderResult] = []
        for order in orders:
            result = self.simulate_order(
                order_id=order.get("id", f"BATCH-{len(results)}"),
                quantity=order.get("quantity", 1),
                price=order.get("price", 0.0),
                symbol=order.get("symbol", ""),
                side=order.get("side", "BUY"),
                inject_failures=inject_failures,
            )
            results.append(result)
        return results

    def simulate_scenario(self, scenario_name: str,
                          orders: list[dict[str, Any]]) -> list[SimulatedOrderResult]:
        """Simulate orders under a specific market scenario.

        Scenarios:
          - 'NORMAL': Low latency, low rejection rate
          - 'HIGH_LATENCY': High latency, normal rejection
          - 'BROKER_DOWN': High rejection rate, all types
          - 'EXCHANGE_HALT': Exchange circuit breaker triggered
          - 'GAP_OPEN': Gap open scenario
          - 'CHAOS': All failures at elevated probabilities

        Args:
            scenario_name: Name of the scenario to run.
            orders: List of order dicts.

        Returns:
            List of SimulatedOrderResult.
        """
        original_config = self._config
        scenario_configs: dict[str, SimulatorConfig] = {
            "NORMAL": SimulatorConfig(
                latency_mean_ms=30, latency_std_ms=10,
                rejection_probability=0.01,
                exchange_failure_probability=0.001,
                gap_open_probability=0.005,
                seed=self._config.seed,
            ),
            "HIGH_LATENCY": SimulatorConfig(
                latency_mean_ms=500, latency_std_ms=200,
                rejection_probability=0.05,
                seed=self._config.seed,
            ),
            "BROKER_DOWN": SimulatorConfig(
                latency_mean_ms=200, latency_std_ms=100,
                rejection_probability=0.50,
                rejection_types=["BROKER_UNAVAILABLE", "RATE_LIMITED"],
                seed=self._config.seed,
            ),
            "EXCHANGE_HALT": SimulatorConfig(
                circuit_breaker_probability=1.0,
                seed=self._config.seed,
            ),
            "GAP_OPEN": SimulatorConfig(
                gap_open_probability=1.0,
                gap_open_max_pct=3.0,
                seed=self._config.seed,
            ),
            "CHAOS": SimulatorConfig(
                latency_mean_ms=1000, latency_std_ms=500,
                rejection_probability=0.30,
                exchange_failure_probability=0.15,
                gap_open_probability=0.10,
                circuit_breaker_probability=0.10,
                partial_fill_probability=0.40,
                seed=self._config.seed,
            ),
        }

        scenario = scenario_configs.get(scenario_name, original_config)
        self._config = scenario
        results = self.simulate_batch(orders, inject_failures=True)
        self._config = original_config
        return results


# ── Convenience API ──────────────────────────────────────────────────────────


def run_market_simulation(
    orders: list[dict[str, Any]],
    scenario: str = "NORMAL",
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Convenience function — run market simulation and return dicts.

    Args:
        orders: List of order dicts.
        scenario: Scenario name (NORMAL, HIGH_LATENCY, BROKER_DOWN, etc.).
        seed: Random seed for reproducibility.

    Returns:
        List of result dicts suitable for JSON serialization.
    """
    sim = MarketSimulator(SimulatorConfig(seed=seed))
    results = sim.simulate_scenario(scenario, orders)
    return [r.to_dict() for r in results]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.market_simulator")
    ap.add_argument("--demo", action="store_true", help="Run with demo data")
    ap.add_argument("--scenario", default="NORMAL",
                    choices=["NORMAL", "HIGH_LATENCY", "BROKER_DOWN", "EXCHANGE_HALT", "GAP_OPEN", "CHAOS"])
    args = ap.parse_args()

    if args.demo:
        sim = MarketSimulator(SimulatorConfig(seed=42))
        orders = [
            {"id": "ORD-001", "quantity": 100, "price": 150.0, "symbol": "NIFTY", "side": "BUY"},
            {"id": "ORD-002", "quantity": 50, "price": 148.5, "symbol": "NIFTY", "side": "BUY"},
            {"id": "ORD-003", "quantity": 200, "price": 45000.0, "symbol": "BANKNIFTY", "side": "SELL"},
        ]
        results = sim.simulate_scenario(args.scenario, orders)
        print(f"Market Simulation [{args.scenario}]")
        print(f"  Failure Rate: {sim.failure_rate:.1%}")
        print()
        for r in results:
            print(r.summary())
            print()
    else:
        print("Market Simulator CLI")
        print("Run with --demo and --scenario for demonstrations")
        print("  --scenario NORMAL       Normal market conditions")
        print("  --scenario HIGH_LATENCY High latency conditions")
        print("  --scenario BROKER_DOWN  Broker unavailability")
        print("  --scenario EXCHANGE_HALT Exchange circuit breaker")
        print("  --scenario GAP_OPEN     Gap open scenario")
        print("  --scenario CHAOS        All failures at elevated rates")


__all__ = [
    "ExchangeFailureType",
    "MAX_LATENCY_MS",
    "MarketSimulator",
    "RejectionType",
    "SimulatedOrderResult",
    "SimulatorConfig",
    "run_market_simulation",
]

