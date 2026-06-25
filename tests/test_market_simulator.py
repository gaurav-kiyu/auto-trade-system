"""Tests for core/market_simulator.py — failure injection, scenarios, edge cases."""

from __future__ import annotations

from core.market_simulator import (
    ExchangeFailureType,
    MarketSimulator,
    RejectionType,
    SimulatedOrderResult,
    SimulatorConfig,
    run_market_simulation,
)


class TestSimulatedOrderResult:
    """Tests for the result dataclass."""

    def test_defaults(self):
        r = SimulatedOrderResult()
        assert r.status == "ACCEPTED"
        assert r.rejection_type == "NONE"
        assert r.exchange_failure == "NONE"
        assert r.latency_ms == 0.0
        assert r.gap_open_pct == 0.0
        assert r.filled_quantity == 0

    def test_to_dict_rounds_values(self):
        r = SimulatedOrderResult(
            order_id="ORD-1",
            status="ACCEPTED",
            latency_ms=123.456,
            fill_price=150.12345,
            gap_open_pct=2.56789,
            filled_quantity=50,
        )
        d = r.to_dict()
        assert d["latency_ms"] == 123.46
        assert d["fill_price"] == 150.1234
        assert d["gap_open_pct"] == 2.5679
        assert d["order_id"] == "ORD-1"

    def test_summary_rejected(self):
        r = SimulatedOrderResult(
            order_id="ORD-1", status="REJECTED",
            rejection_reason="Insufficient margin",
        )
        s = r.summary()
        assert "REJECTED" in s
        assert "Insufficient margin" in s

    def test_summary_slow_latency(self):
        r = SimulatedOrderResult(
            order_id="ORD-1", status="ACCEPTED", latency_ms=150,
        )
        s = r.summary()
        assert "SLOW" in s

    def test_summary_fast_latency(self):
        r = SimulatedOrderResult(
            order_id="ORD-1", status="ACCEPTED", latency_ms=50,
        )
        s = r.summary()
        assert "SLOW" not in s.upper()

    def test_summary_gap_open(self):
        r = SimulatedOrderResult(
            order_id="ORD-1", status="ACCEPTED",
            gap_open_pct=1.5,
        )
        s = r.summary()
        assert "+1.50%" in s

    def test_summary_fill_shown(self):
        r = SimulatedOrderResult(
            order_id="ORD-1", status="ACCEPTED",
            filled_quantity=25, fill_price=150.0,
        )
        s = r.summary()
        assert "25 @ ₹150.00" in s


class TestSimulatorConfig:
    """Tests for config dataclass defaults."""

    def test_defaults(self):
        c = SimulatorConfig()
        assert c.latency_mean_ms == 50.0
        assert c.rejection_probability == 0.05
        assert c.exchange_failure_probability == 0.01
        assert c.gap_open_probability == 0.02
        assert c.partial_fill_probability == 0.10
        assert c.seed is None
        assert "INSUFFICIENT_MARGIN" in c.rejection_types

    def test_seed_reproducible(self):
        c1 = SimulatorConfig(seed=42)
        c2 = SimulatorConfig(seed=42)
        s1 = MarketSimulator(c1)
        s2 = MarketSimulator(c2)
        r1 = s1.simulate_order("ORD-1", 100, 150.0)
        r2 = s2.simulate_order("ORD-1", 100, 150.0)
        assert r1.status == r2.status
        assert r1.latency_ms == r2.latency_ms


class TestMarketSimulatorCleanFill:
    """Tests for clean fills without failure injection."""

    def setup_method(self):
        self.sim = MarketSimulator(SimulatorConfig(seed=42))

    def test_clean_fill_returns_accepted(self):
        r = self.sim.simulate_order("ORD-1", 100, 150.0, inject_failures=False)
        assert r.status == "ACCEPTED"
        assert r.filled_quantity == 100
        assert r.fill_price == 150.0
        assert r.latency_ms >= 0

    def test_clean_fill_no_rejection(self):
        r = self.sim.simulate_order("ORD-1", 50, 200.0, inject_failures=False)
        assert r.rejection_type == "NONE"
        assert r.exchange_failure == "NONE"


class TestMarketSimulatorLatency:
    """Tests for latency simulation."""

    def setup_method(self):
        self.sim = MarketSimulator(SimulatorConfig(seed=99))

    def test_latency_non_negative(self):
        latencies = []
        for i in range(50):
            r = self.sim.simulate_order(f"ORD-{i}", 1, 100.0, inject_failures=False)
            latencies.append(r.latency_ms)
        assert all(l >= 0 for l in latencies)
        # Most should be within a reasonable range of the mean
        mean = sum(latencies) / len(latencies)
        assert 20 < mean < 120

    def test_latency_capped(self):
        cfg = SimulatorConfig(latency_mean_ms=50000, latency_std_ms=10000, seed=42)
        sim = MarketSimulator(cfg)
        r = sim.simulate_order("ORD-1", 1, 100.0, inject_failures=False)
        assert r.latency_ms <= 30000


class TestMarketSimulatorRejection:
    """Tests for broker rejection simulation."""

    def setup_method(self):
        # Force rejection probability to 1.0 for deterministic testing
        self.cfg = SimulatorConfig(
            rejection_probability=1.0,
            rejection_types=["INSUFFICIENT_MARGIN", "ORDER_REJECTED"],
            seed=42,
        )
        self.sim = MarketSimulator(self.cfg)

    def test_rejection_with_certainty(self):
        r = self.sim.simulate_order("ORD-1", 100, 150.0)
        assert r.status == "REJECTED"
        assert r.rejection_type != "NONE"
        assert r.rejection_reason != ""

    def test_failure_count_incremented(self):
        sim = MarketSimulator(SimulatorConfig(rejection_probability=1.0, seed=42))
        assert sim.failure_rate == 0.0
        sim.simulate_order("ORD-1", 100, 150.0)
        assert sim.failure_rate > 0

    def test_no_rejection_with_zero_probability(self):
        sim = MarketSimulator(SimulatorConfig(
            rejection_probability=0.0,
            circuit_breaker_probability=0.0,
            gap_open_probability=0.0,
            exchange_failure_probability=0.0,
            seed=42,
        ))
        for _ in range(20):
            r = sim.simulate_order(f"ORD-{_}", 100, 150.0)
            assert r.status == "ACCEPTED", f"Rejected at iteration {_}"

    def test_known_rejection_reasons(self):
        cfg = SimulatorConfig(
            rejection_probability=1.0,
            rejection_types=list(RejectionType.__members__.values()),
            seed=42,
        )
        sim = MarketSimulator(cfg)
        seen = set()
        for _ in range(100):
            r = sim.simulate_order(f"ORD-{_}", 100, 150.0)
            if r.status == "REJECTED":
                seen.add(r.rejection_type)
        # Should see at least 2 different rejection types over 100 trials
        assert len(seen) >= 2, f"Only saw rejection types: {seen}"


class TestMarketSimulatorExchangeFailure:
    """Tests for exchange failure simulation."""

    def test_no_failure_with_zero_probability(self):
        cfg = SimulatorConfig(
            circuit_breaker_probability=0.0,
            gap_open_probability=0.0,
            exchange_failure_probability=0.0,
            seed=42,
        )
        sim = MarketSimulator(cfg)
        for _ in range(20):
            r = sim.simulate_order(f"ORD-{_}", 100, 150.0)
            assert r.exchange_failure == "NONE"

    def test_circuit_breaker_deterministic(self):
        cfg = SimulatorConfig(
            circuit_breaker_probability=1.0,
            gap_open_probability=0.0,
            exchange_failure_probability=0.0,
            seed=42,
        )
        sim = MarketSimulator(cfg)
        r = sim.simulate_order("ORD-1", 100, 150.0)
        assert r.exchange_failure == ExchangeFailureType.CIRCUIT_BREAKER.value
        assert r.exchange_halt_duration_sec > 0

    def test_gap_open_deterministic(self):
        cfg = SimulatorConfig(
            circuit_breaker_probability=0.0,
            gap_open_probability=1.0,
            gap_open_max_pct=5.0,
            seed=42,
        )
        sim = MarketSimulator(cfg)
        r = sim.simulate_order("ORD-1", 100, 150.0)
        assert r.exchange_failure in (
            ExchangeFailureType.GAP_UP.value,
            ExchangeFailureType.GAP_DOWN.value,
        )
        assert r.gap_open_pct != 0.0

    def test_exchange_failure_types(self):
        cfg = SimulatorConfig(
            circuit_breaker_probability=0.0,
            gap_open_probability=0.0,
            exchange_failure_probability=1.0,
            seed=42,
        )
        sim = MarketSimulator(cfg)
        r = sim.simulate_order("ORD-1", 100, 150.0)
        assert r.exchange_failure in (
            ExchangeFailureType.TRADING_HALT.value,
            ExchangeFailureType.NO_DATA.value,
            ExchangeFailureType.MATCHING_ENGINE_DOWN.value,
        )


class TestMarketSimulatorPartialFill:
    """Tests for partial fill simulation."""

    def setup_method(self):
        self.cfg = SimulatorConfig(
            partial_fill_probability=1.0,
            partial_fill_min_pct=0.3,
            partial_fill_max_pct=0.7,
            rejection_probability=0.0,
            seed=42,
        )
        self.sim = MarketSimulator(self.cfg)

    def test_partial_fill_reduces_quantity(self):
        r = self.sim.simulate_order("ORD-1", 100, 150.0)
        assert r.status == "ACCEPTED"
        assert 0 < r.filled_quantity < 100

    def test_fill_price_has_slippage(self):
        r = self.sim.simulate_order("ORD-1", 100, 150.0)
        assert r.fill_price != 150.0  # slippage applied

    def test_partial_fill_min_one_lot(self):
        cfg = SimulatorConfig(
            partial_fill_probability=1.0,
            partial_fill_min_pct=0.01,
            partial_fill_max_pct=0.05,
            rejection_probability=0.0,
            seed=42,
        )
        sim = MarketSimulator(cfg)
        r = sim.simulate_order("ORD-1", 1, 150.0)
        assert r.filled_quantity >= 1  # minimum 1


class TestMarketSimulatorReset:
    """Tests for state reset."""

    def test_reset_clears_stats(self):
        sim = MarketSimulator(SimulatorConfig(rejection_probability=1.0, seed=42))
        sim.simulate_order("ORD-1", 100, 150.0)
        assert sim.failure_rate > 0
        assert sim._total_orders > 0
        sim.reset()
        assert sim.failure_rate == 0.0
        assert sim._total_orders == 0


class TestMarketSimulatorBatch:
    """Tests for batch simulation."""

    def setup_method(self):
        self.sim = MarketSimulator(SimulatorConfig(seed=42))
        self.orders = [
            {"id": "ORD-1", "quantity": 100, "price": 150.0, "symbol": "NIFTY", "side": "BUY"},
            {"id": "ORD-2", "quantity": 50, "price": 148.0, "symbol": "BANKNIFTY", "side": "SELL"},
        ]

    def test_batch_returns_correct_count(self):
        results = self.sim.simulate_batch(self.orders)
        assert len(results) == 2

    def test_batch_inject_false(self):
        results = self.sim.simulate_batch(self.orders, inject_failures=False)
        assert all(r.status == "ACCEPTED" for r in results)
        assert all(r.filled_quantity > 0 for r in results)

    def test_batch_no_failures_with_zero_prob(self):
        cfg = SimulatorConfig(
            rejection_probability=0.0,
            exchange_failure_probability=0.0,
            seed=42,
        )
        sim = MarketSimulator(cfg)
        results = sim.simulate_batch(self.orders)
        assert all(r.status == "ACCEPTED" for r in results)

    def test_batch_with_empty_list(self):
        results = self.sim.simulate_batch([])
        assert results == []


class TestMarketSimulatorScenarios:
    """Tests for named scenarios."""

    def setup_method(self):
        self.sim = MarketSimulator(SimulatorConfig(seed=42))
        self.orders = [
            {"id": "ORD-1", "quantity": 100, "price": 150.0, "symbol": "NIFTY", "side": "BUY"},
        ]

    def test_normal_scenario(self):
        results = self.sim.simulate_scenario("NORMAL", self.orders)
        assert len(results) == 1
        assert results[0].status == "ACCEPTED"

    def test_high_latency_scenario(self):
        results = self.sim.simulate_scenario("HIGH_LATENCY", self.orders)
        # Latency should be high
        assert results[0].latency_ms > 100

    def test_broker_down_scenario(self):
        results = self.sim.simulate_scenario("BROKER_DOWN", self.orders)
        # High rejection probability
        assert len(results) == 1

    def test_exchange_halt_scenario(self):
        results = self.sim.simulate_scenario("EXCHANGE_HALT", self.orders)
        assert results[0].exchange_failure == ExchangeFailureType.CIRCUIT_BREAKER.value

    def test_gap_open_scenario(self):
        results = self.sim.simulate_scenario("GAP_OPEN", self.orders)
        assert results[0].exchange_failure in (
            ExchangeFailureType.GAP_UP.value,
            ExchangeFailureType.GAP_DOWN.value,
        )

    def test_chaos_scenario(self):
        results = self.sim.simulate_scenario("CHAOS", self.orders)
        assert len(results) == 1  # doesn't crash

    def test_unknown_scenario_falls_back_to_normal(self):
        results = self.sim.simulate_scenario("NONEXISTENT", self.orders)
        assert len(results) == 1
        assert results[0].status == "ACCEPTED"

    def test_config_restored_after_scenario(self):
        original_latency = self.sim._config.latency_mean_ms
        self.sim.simulate_scenario("HIGH_LATENCY", self.orders)
        assert self.sim._config.latency_mean_ms == original_latency

    def test_scenario_with_multiple_orders(self):
        orders = [
            {"id": "ORD-1", "quantity": 100, "price": 150.0},
            {"id": "ORD-2", "quantity": 50, "price": 200.0},
            {"id": "ORD-3", "quantity": 25, "price": 100.0},
        ]
        results = self.sim.simulate_scenario("GAP_OPEN", orders)
        assert len(results) == 3


class TestRunMarketSimulation:
    """Tests for convenience function."""

    def test_returns_dicts(self):
        orders = [{"id": "ORD-1", "quantity": 100, "price": 150.0}]
        results = run_market_simulation(orders, scenario="NORMAL", seed=42)
        assert isinstance(results, list)
        assert isinstance(results[0], dict)
        assert "status" in results[0]
        assert "latency_ms" in results[0]

    def test_scenario_parameter_respected(self):
        orders = [{"id": "ORD-1", "quantity": 100, "price": 150.0}]
        results = run_market_simulation(orders, scenario="EXCHANGE_HALT", seed=42)
        assert results[0]["exchange_failure"] == ExchangeFailureType.CIRCUIT_BREAKER.value

    def test_seed_reproducible(self):
        orders = [{"id": "ORD-1", "quantity": 100, "price": 150.0}]
        r1 = run_market_simulation(orders, seed=42)
        r2 = run_market_simulation(orders, seed=42)
        assert r1[0]["latency_ms"] == r2[0]["latency_ms"]

    def test_empty_orders(self):
        results = run_market_simulation([], seed=42)
        assert results == []


class TestMarketSimulatorEdgeCases:
    """Edge case tests."""

    def test_zero_quantity(self):
        sim = MarketSimulator(SimulatorConfig(seed=42))
        r = sim.simulate_order("ORD-1", 0, 150.0, inject_failures=False)
        assert r.filled_quantity == 0

    def test_zero_price(self):
        sim = MarketSimulator(SimulatorConfig(seed=42))
        r = sim.simulate_order("ORD-1", 100, 0.0, inject_failures=False)
        assert r.fill_price == 0.0

    def test_negative_quantity_handled(self):
        sim = MarketSimulator(SimulatorConfig(seed=42))
        r = sim.simulate_order("ORD-1", -5, 150.0, inject_failures=False)
        # Should not crash
        assert r.status == "ACCEPTED"

    def test_large_batch_does_not_crash(self):
        orders = [{"id": f"ORD-{i}", "quantity": 1, "price": 100.0} for i in range(1000)]
        sim = MarketSimulator(SimulatorConfig(seed=42))
        results = sim.simulate_batch(orders, inject_failures=False)
        assert len(results) == 1000

    def test_config_mutation_does_not_leak(self):
        cfg = SimulatorConfig(seed=42)
        sim = MarketSimulator(cfg)
        sim.simulate_scenario("CHAOS", [{"id": "ORD-1", "quantity": 1, "price": 100.0}])
        # Original config unchanged
        assert cfg.latency_mean_ms == 50.0

    def test_failure_rate_zero_with_no_orders(self):
        sim = MarketSimulator()
        assert sim.failure_rate == 0.0
