"""
Tests for core/circuit_breaker_monitor.py - NSE Circuit Breaker Detection.

Covers:
  - CircuitBreakerState dataclass
  - NSECircuitBreakerMonitor init with dependency injection
  - Baseline price setup from first tick
  - Circuit breaker level detection (10%, 15%, 20% drops)
  - Market halt handling with hard halt trip
  - Baseline reset at market open
  - Start/stop lifecycle
  - Factory function create_circuit_breaker_monitor
"""
from __future__ import annotations

from datetime import datetime

import pytest

from core.circuit_breaker_monitor import (
    NSECircuitBreakerMonitor,
    CircuitBreakerState,
    create_circuit_breaker_monitor,
)
from core.safety_state import _HARD_HALT, is_hard_halted


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_halt() -> None:
    _HARD_HALT.clear()


# ── CircuitBreakerState ──────────────────────────────────────────────


class TestCircuitBreakerState:
    def test_default_state(self) -> None:
        state = CircuitBreakerState(
            level="NONE", index_change_pct=0.0,
            last_update=datetime.now(), is_market_halted=False,
        )
        assert state.level == "NONE"
        assert state.index_change_pct == 0.0
        assert not state.is_market_halted

    def test_halted_state(self) -> None:
        state = CircuitBreakerState(
            level="10%", index_change_pct=-10.5,
            last_update=datetime.now(), is_market_halted=True,
        )
        assert state.level == "10%"
        assert state.index_change_pct == -10.5
        assert state.is_market_halted


# ── Monitor Init ─────────────────────────────────────────────────────


class TestMonitorInit:
    def test_initial_state_none(self) -> None:
        monitor = NSECircuitBreakerMonitor()
        state = monitor.get_state()
        assert state.level == "NONE"
        assert not state.is_market_halted

    def test_not_running_by_default(self) -> None:
        monitor = NSECircuitBreakerMonitor()
        assert not monitor._running

    def test_baseline_none_by_default(self) -> None:
        monitor = NSECircuitBreakerMonitor()
        assert monitor._baseline_price is None

    def test_custom_injections(self) -> None:
        sent: list[str] = []
        monitor = NSECircuitBreakerMonitor(
            send_fn=lambda msg: sent.append(str(msg)),
            get_index_price_fn=lambda: 23500.0,
        )
        assert monitor._baseline_price is None
        monitor._check_circuit_breaker()  # Sets baseline
        assert monitor._baseline_price == 23500.0


# ── Baseline Setup ──────────────────────────────────────────────────


class TestBaseline:
    def test_baseline_set_from_first_tick(self) -> None:
        monitor = NSECircuitBreakerMonitor(get_index_price_fn=lambda: 23500.0)
        assert monitor._baseline_price is None
        monitor._check_circuit_breaker()
        assert monitor._baseline_price == 23500.0

    def test_baseline_unchanged_on_subsequent_checks(self) -> None:
        prices: list[float] = [23500.0, 23400.0]
        idx: list[int] = [0]
        monitor = NSECircuitBreakerMonitor(
            get_index_price_fn=lambda: prices[idx[0]],
        )
        monitor._check_circuit_breaker()  # Baseline = 23500
        idx[0] = 1
        monitor._check_circuit_breaker()  # Check with 23400
        assert monitor._baseline_price == 23500.0  # Baseline unchanged

    def test_skip_if_baseline_zero(self) -> None:
        monitor = NSECircuitBreakerMonitor(get_index_price_fn=lambda: 0.0)
        monitor._check_circuit_breaker()
        # Should set baseline but return because no price movement
        assert monitor._baseline_price == 0.0
        # Second check should skip because baseline is 0
        monitor._check_circuit_breaker()
        assert monitor._state.level == "NONE"


# ── Circuit Breaker Detection ───────────────────────────────────────


class TestDetection:
    def test_no_halt_on_small_drop(self) -> None:
        prices: list[float] = [10000.0, 9500.0]  # 5% drop
        idx: list[int] = [0]
        monitor = NSECircuitBreakerMonitor(
            get_index_price_fn=lambda: prices[idx[0]],
        )
        monitor._check_circuit_breaker()  # Set baseline
        idx[0] = 1
        monitor._check_circuit_breaker()  # 5% drop
        assert monitor._state.level == "NONE"
        assert not is_hard_halted()

    def test_10_percent_halt(self) -> None:
        prices: list[float] = [10000.0, 8950.0]  # 10.5% drop
        idx: list[int] = [0]
        monitor = NSECircuitBreakerMonitor(
            get_index_price_fn=lambda: prices[idx[0]],
        )
        monitor._check_circuit_breaker()  # Set baseline
        idx[0] = 1
        monitor._check_circuit_breaker()
        assert monitor._state.level == "10%"
        assert monitor._state.is_market_halted
        assert is_hard_halted()

    def test_15_percent_halt(self) -> None:
        prices: list[float] = [10000.0, 8450.0]  # 15.5% drop
        idx: list[int] = [0]
        monitor = NSECircuitBreakerMonitor(
            get_index_price_fn=lambda: prices[idx[0]],
        )
        monitor._check_circuit_breaker()  # Set baseline
        idx[0] = 1
        monitor._check_circuit_breaker()
        assert monitor._state.level == "15%"
        assert is_hard_halted()

    def test_20_percent_halt(self) -> None:
        prices: list[float] = [10000.0, 7950.0]  # 20.5% drop
        idx: list[int] = [0]
        monitor = NSECircuitBreakerMonitor(
            get_index_price_fn=lambda: prices[idx[0]],
        )
        monitor._check_circuit_breaker()  # Set baseline
        idx[0] = 1
        monitor._check_circuit_breaker()
        assert monitor._state.level == "20%"
        assert is_hard_halted()

    def test_price_gain_does_not_trigger(self) -> None:
        prices: list[float] = [10000.0, 10500.0]  # 5% gain
        idx: list[int] = [0]
        monitor = NSECircuitBreakerMonitor(
            get_index_price_fn=lambda: prices[idx[0]],
        )
        monitor._check_circuit_breaker()  # Set baseline
        idx[0] = 1
        monitor._check_circuit_breaker()  # Gain, not drop
        assert monitor._state.level == "NONE"

    def test_none_price_returns(self) -> None:
        monitor = NSECircuitBreakerMonitor(
            get_index_price_fn=lambda: None,
        )
        monitor._check_circuit_breaker()
        assert monitor._baseline_price is None


# ── Market Halt Handler ─────────────────────────────────────────────


class TestMarketHaltHandler:
    def test_halt_sends_alert(self) -> None:
        sent: list[str] = []
        monitor = NSECircuitBreakerMonitor(
            send_fn=lambda msg: sent.append(str(msg)),
            get_index_price_fn=lambda: 10000.0,
        )
        # Trigger 10% halt
        monitor._baseline_price = 10000.0
        monitor._get_index_price = lambda: 8950.0
        monitor._check_circuit_breaker()
        assert len(sent) >= 1
        assert "CIRCUIT BREAKER" in sent[0].upper()

    def test_halt_resets_timestamp(self) -> None:
        monitor = NSECircuitBreakerMonitor(get_index_price_fn=lambda: 10000.0)
        assert monitor._last_halt_time is None
        # Cannot call _handle_market_halt directly without a halt
        # But we can trigger it via price drop
        monitor._baseline_price = 10000.0
        monitor._get_index_price = lambda: 8000.0
        monitor._check_circuit_breaker()
        assert monitor._last_halt_time is not None

    def test_halt_trips_hard_halt(self) -> None:
        monitor = NSECircuitBreakerMonitor(get_index_price_fn=lambda: 10000.0)
        assert not is_hard_halted()
        monitor._baseline_price = 10000.0
        monitor._get_index_price = lambda: 8500.0  # 15% drop
        monitor._check_circuit_breaker()
        assert is_hard_halted()
        assert "circuit breaker" in str(_HARD_HALT.is_set()).lower() or is_hard_halted()


# ── Baseline Reset ──────────────────────────────────────────────────


class TestBaselineReset:
    def test_reset_clears_baseline(self) -> None:
        monitor = NSECircuitBreakerMonitor(get_index_price_fn=lambda: 23500.0)
        monitor._check_circuit_breaker()
        assert monitor._baseline_price == 23500.0
        monitor.reset_baseline()
        assert monitor._baseline_price is None

    def test_reset_clears_state(self) -> None:
        monitor = NSECircuitBreakerMonitor(get_index_price_fn=lambda: 10000.0)
        monitor._baseline_price = 10000.0
        monitor._get_index_price = lambda: 8000.0
        monitor._check_circuit_breaker()
        assert monitor._state.level != "NONE"
        monitor.reset_baseline()
        assert monitor._state.level == "NONE"
        assert not monitor._state.is_market_halted


# ── Start / Stop ────────────────────────────────────────────────────


class TestStartStop:
    def test_start_sets_running(self) -> None:
        monitor = NSECircuitBreakerMonitor()
        monitor.start()
        assert monitor._running
        monitor.stop()

    def test_double_start_idempotent(self) -> None:
        monitor = NSECircuitBreakerMonitor()
        monitor.start()
        monitor.start()  # Should not crash
        assert monitor._running
        monitor.stop()

    def test_stop_sets_not_running(self) -> None:
        monitor = NSECircuitBreakerMonitor()
        monitor.start()
        monitor.stop()
        assert not monitor._running

    def test_stop_without_start(self) -> None:
        monitor = NSECircuitBreakerMonitor()
        monitor.stop()  # Should not crash


# ── Factory Function ────────────────────────────────────────────────


class TestFactory:
    def test_create_and_start(self) -> None:
        sent: list[str] = []
        monitor = create_circuit_breaker_monitor(
            send_fn=lambda msg: sent.append(str(msg)),
            get_index_price_fn=lambda: 23500.0,
        )
        assert isinstance(monitor, NSECircuitBreakerMonitor)
        assert monitor._running
        monitor.stop()

    def test_factory_with_defaults(self) -> None:
        monitor = create_circuit_breaker_monitor()
        assert isinstance(monitor, NSECircuitBreakerMonitor)
        assert monitor._running
        monitor.stop()


# ── CB Levels ───────────────────────────────────────────────────────


class TestCBLevels:
    def test_levels_defined(self) -> None:
        assert "10%" in NSECircuitBreakerMonitor.CB_LEVELS
        assert "15%" in NSECircuitBreakerMonitor.CB_LEVELS
        assert "20%" in NSECircuitBreakerMonitor.CB_LEVELS

    def test_levels_values(self) -> None:
        assert NSECircuitBreakerMonitor.CB_LEVELS["10%"] == -10.0
        assert NSECircuitBreakerMonitor.CB_LEVELS["15%"] == -15.0
        assert NSECircuitBreakerMonitor.CB_LEVELS["20%"] == -20.0
