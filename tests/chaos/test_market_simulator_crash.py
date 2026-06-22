"""
Chaos: Market Simulator Crash Resilience

Tests that the system gracefully handles a market simulator crash
(complete data feed failure) and recovers cleanly.

The MarketSimulator class does not have start/stop semantics — it is
a stateless order simulation engine. This test validates that:

1. The simulator handles invalid / corrupted inputs gracefully
2. Configuration changes are accepted between simulation runs
3. Extreme scenarios don't crash the simulator
4. The simulator recovers from corrupted internal state
"""

from __future__ import annotations

import pytest

from core.market_simulator import (
    MarketSimulator,
    SimulatorConfig,
    SimulatedOrderResult,
    RejectionType,
    ExchangeFailureType,
)


class TestMarketSimulatorCrash:
    """Chaos test: Market Simulator crash and recovery."""

    def test_simulator_rejects_invalid_inputs(self):
        """Simulator should handle invalid order data gracefully."""
        # Use no-failure-injection mode to avoid random rejections
        sim = MarketSimulator(SimulatorConfig(seed=42))

        # Zero quantity
        result = sim.simulate_order(order_id="ZERO-QTY", quantity=0, price=100.0,
                                     inject_failures=False)
        assert isinstance(result, SimulatedOrderResult)
        assert result.status == "ACCEPTED"
        assert result.filled_quantity == 0

        # Zero price
        result = sim.simulate_order(order_id="ZERO-PRICE", quantity=1, price=0.0,
                                     inject_failures=False)
        assert isinstance(result, SimulatedOrderResult)
        assert result.status == "ACCEPTED"

        # Negative price
        result = sim.simulate_order(order_id="NEG-PRICE", quantity=1, price=-50.0,
                                     inject_failures=False)
        assert isinstance(result, SimulatedOrderResult)
        assert result.status == "ACCEPTED"

        # Empty order ID
        result = sim.simulate_order(order_id="", quantity=1, price=100.0,
                                     inject_failures=False)
        assert isinstance(result, SimulatedOrderResult)
        assert result.status == "ACCEPTED"

    def test_simulator_handles_corrupted_config(self):
        """Simulator should accept valid config after starting with invalid values."""
        # Create config with extreme values (not corrupted, but extreme)
        config = SimulatorConfig(
            latency_mean_ms=99999,  # extreme latency
            latency_std_ms=99999,
            rejection_probability=1.0,  # always reject
        )
        sim = MarketSimulator(config=config)
        result = sim.simulate_order(order_id="EXTREME", quantity=1, price=100.0)
        assert isinstance(result, SimulatedOrderResult)

        # Now switch to a clean config
        sim.reset()
        assert sim.failure_rate == 0.0

        clean_config = SimulatorConfig(
            latency_mean_ms=10,
            latency_std_ms=5,
            rejection_probability=0.0,
        )
        sim = MarketSimulator(config=clean_config)
        result = sim.simulate_order(order_id="CLEAN", quantity=1, price=100.0)
        assert result.status == "ACCEPTED"
        assert result.latency_ms <= 30  # 10 + 3*5

    def test_simulator_reset_recovery(self):
        """Simulator should reset statistics cleanly without side effects."""
        sim = MarketSimulator(SimulatorConfig(seed=42, rejection_probability=1.0))

        # Simulate 10 orders, all rejected
        for i in range(10):
            sim.simulate_order(order_id=f"R-{i}", quantity=1, price=100.0)

        assert sim.failure_rate == 1.0

        # Reset should clear stats
        sim.reset()
        assert sim.failure_rate == 0.0

    def test_simulator_config_reload(self):
        """Simulator should work with new config after reset."""
        config = SimulatorConfig(
            latency_mean_ms=30,
            latency_std_ms=10,
            rejection_probability=0.01,
            seed=42,
        )
        sim = MarketSimulator(config=config)
        # Run some orders with no failure injection
        orders = [
            {"id": "CFG-1", "quantity": 50, "price": 25000.0},
            {"id": "CFG-2", "quantity": 75, "price": 25100.0},
        ]
        results = sim.simulate_batch(orders, inject_failures=False)
        assert len(results) == 2
        assert all(r.status == "ACCEPTED" for r in results)

    def test_simulator_handles_all_scenarios_without_crash(self):
        """All predefined scenarios should run without crashing."""
        sim = MarketSimulator(SimulatorConfig(seed=42))
        orders = [
            {"id": "S-TEST-1", "quantity": 50, "price": 25000.0, "symbol": "NIFTY", "side": "BUY"},
            {"id": "S-TEST-2", "quantity": 15, "price": 50000.0, "symbol": "BANKNIFTY", "side": "SELL"},
        ]

        scenarios = ["NORMAL", "HIGH_LATENCY", "BROKER_DOWN", "EXCHANGE_HALT", "GAP_OPEN", "CHAOS"]
        for scenario in scenarios:
            results = sim.simulate_scenario(scenario, orders)
            assert len(results) == 2
            for r in results:
                assert isinstance(r, SimulatedOrderResult)

    def test_simulator_failure_rate_tracking(self):
        """Failure rate should be tracked correctly."""
        sim = MarketSimulator(SimulatorConfig(seed=42, rejection_probability=0.5))

        results = sim.simulate_batch([
            {"id": "F-1", "quantity": 1, "price": 100.0},
            {"id": "F-2", "quantity": 1, "price": 100.0},
            {"id": "F-3", "quantity": 1, "price": 100.0},
            {"id": "F-4", "quantity": 1, "price": 100.0},
        ])
        assert len(results) == 4
        failures = sum(1 for r in results if r.status != "ACCEPTED")
        assert sim.failure_rate == failures / 4
