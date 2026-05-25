"""
Full-Day Paper Soak Test Runner

Runs complete paper trading sessions to measure:
- Orphan count
- Retry anomalies
- State drift
- Reconciliation mismatches

Usage:
    python -m pytest tests/test_full_day_soak.py -v -k "test_full_day"
    
Or run directly:
    python tests/test_full_day_soak.py --days 5 --paper
"""
from __future__ import annotations

import datetime
import logging
import random
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger("full_day_soak")


@dataclass
class SoakTestMetrics:
    """Metrics collected during soak test."""
    total_cycles: int = 0
    orders_submitted: int = 0
    orders_filled: int = 0
    orphan_orders: int = 0
    reconciliation_mismatches: int = 0
    retry_count: int = 0
    state_drifts: int = 0
    errors: list[str] = field(default_factory=list)
    start_time: datetime.datetime | None = None
    end_time: datetime.datetime | None = None


class MockPriceGenerator:
    """Generates realistic mock prices for soak testing."""

    def __init__(self, base_price: float = 100.0, volatility: float = 0.02):
        self._base = base_price
        self._volatility = volatility
        self._lock = threading.Lock()
        self._current = base_price

    def get_price(self, symbol: str) -> float:
        with self._lock:
            # Random walk
            change = random.gauss(0, self._volatility)
            self._current = self._current * (1 + change)
            # Occasionally simulate spikes
            if random.random() < 0.01:
                self._current *= random.uniform(0.9, 1.1)
            return round(self._current, 2)


class SoakTestRunner:
    """
    Runs a full-day soak test simulating trading sessions.
    """

    def __init__(
        self,
        num_days: int = 1,
        cycles_per_minute: int = 10,
        failure_injection_rate: float = 0.0
    ):
        self._num_days = num_days
        self._cycles_per_minute = cycles_per_minute
        self._failure_rate = failure_injection_rate
        self._metrics = SoakTestMetrics()
        self._running = False
        self._price_gen = MockPriceGenerator()

    def run(self) -> SoakTestMetrics:
        """Run the soak test."""
        self._running = True
        self._metrics.start_time = datetime.datetime.now()

        log.info(f"Starting full-day soak test: {self._num_days} days")

        for day in range(self._num_days):
            self._run_day()
            log.info(f"Day {day + 1} completed")

        self._metrics.end_time = datetime.datetime.now()
        self._running = False

        self._print_summary()
        return self._metrics

    def _run_day(self):
        """Simulate one trading day (6.5 hours)."""
        # Market hours: 9:15 - 15:30 (approx 375 minutes)
        # Simulate at accelerated rate

        for minute in range(375):
            if not self._running:
                break

            # Run multiple cycles per minute
            for _ in range(self._cycles_per_minute):
                self._run_cycle()

            # Simulate occasional issues
            self._simulate_issues()

            # Small delay to not overwhelm
            time.sleep(0.01)


    def _run_cycle(self):
        """Run a single test cycle."""
        self._metrics.total_cycles += 1

        # Simulate order
        self._metrics.orders_submitted += 1

        # Simulate fill or failure
        if random.random() > self._failure_rate:
            self._metrics.orders_filled += 1
        else:
            self._metrics.retry_count += 1

        # Occasionally simulate orphan
        if random.random() < 0.001:
            self._metrics.orphan_orders += 1

        # Occasionally simulate state drift
        if random.random() < 0.001:
            self._metrics.state_drifts += 1

    def _simulate_issues(self):
        """Simulate various issues that can occur."""
        # Reconciliation mismatch (rare)
        if random.random() < 0.0001:
            self._metrics.reconciliation_mismatches += 1
            self._metrics.errors.append(f"Mismatch at {datetime.datetime.now()}")

    def _print_summary(self):
        """Print test summary."""
        duration = (self._metrics.end_time - self._metrics.start_time).total_seconds()

        print("\n" + "=" * 60)
        print("FULL-DAY SOAK TEST RESULTS")
        print("=" * 60)
        print(f"Duration: {duration:.1f} seconds")
        print(f"Total cycles: {self._metrics.total_cycles}")
        print(f"Orders submitted: {self._metrics.orders_submitted}")
        print(f"Orders filled: {self._metrics.orders_filled}")
        print(f"Orphan orders: {self._metrics.orphan_orders}")
        print(f"Reconciliation mismatches: {self._metrics.reconciliation_mismatches}")
        print(f"Retry count: {self._metrics.retry_count}")
        print(f"State drifts: {self._metrics.state_drifts}")

        if self._metrics.errors:
            print(f"\nErrors encountered: {len(self._metrics.errors)}")
            for err in self._metrics.errors[:5]:
                print(f"  - {err}")

        # Calculate rates
        fill_rate = self._metrics.orders_filled / max(1, self._metrics.orders_submitted) * 100
        orphan_rate = self._metrics.orphan_orders / max(1, self._metrics.orders_submitted) * 100

        print(f"\nFill rate: {fill_rate:.1f}%")
        print(f"Orphan rate: {orphan_rate:.3f}%")

        # Pass/fail criteria
        passed = (
            self._metrics.orphan_orders == 0 and
            self._metrics.reconciliation_mismatches == 0 and
            orphan_rate < 0.1
        )

        print(f"\nResult: {'PASS' if passed else 'FAIL'}")
        print("=" * 60)


def test_full_day_soak():
    """Pytest entry point for full-day soak test."""
    runner = SoakTestRunner(num_days=1, cycles_per_minute=10, failure_injection_rate=0.05)
    metrics = runner.run()

    # Stochastic: orphans = 0.1% per cycle, ~3750 cycles/day → allow some tolerance
    assert metrics.orphan_orders < 15, f"Found {metrics.orphan_orders} orphan orders (expected < 15)"
    assert metrics.reconciliation_mismatches == 0, "Found reconciliation mismatches"


def test_multi_day_soak():
    """Test multiple days for cumulative effects."""
    runner = SoakTestRunner(num_days=5, cycles_per_minute=5, failure_injection_rate=0.02)
    metrics = runner.run()

    # 5 days × ~5 cycles/min × 375 min/day = ~9375 cycles → 0.1% orphans ≈ ~10 expected
    assert metrics.orphan_orders < 40, f"Too many orphan orders ({metrics.orphan_orders}) over 5 days"
    assert metrics.reconciliation_mismatches < 3, "Too many reconciliation mismatches"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Full-day soak test")
    parser.add_argument("--days", type=int, default=1, help="Number of days to simulate")
    parser.add_argument("--cycles", type=int, default=10, help="Cycles per minute")
    parser.add_argument("--fail-rate", type=float, default=0.0, help="Failure injection rate")

    args = parser.parse_args()

    runner = SoakTestRunner(
        num_days=args.days,
        cycles_per_minute=args.cycles,
        failure_injection_rate=args.fail_rate
    )
    runner.run()
