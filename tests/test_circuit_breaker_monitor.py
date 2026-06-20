"""Tests for core.circuit_breaker_monitor — NSE Circuit Breaker detection."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from core.circuit_breaker_monitor import (
    CircuitBreakerState,
    CircuitBreakerStateStore,
    NSECircuitBreakerMonitor,
    create_circuit_breaker_monitor,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_send() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_get_price() -> MagicMock:
    fn = MagicMock()
    fn.return_value = 10000.0  # NIFTY baseline
    return fn


@pytest.fixture
def monitor(mock_send: MagicMock, mock_get_price: MagicMock) -> NSECircuitBreakerMonitor:
    m = NSECircuitBreakerMonitor(
        send_fn=mock_send,
        get_index_price_fn=mock_get_price,
        cfg={},
    )
    # Set baseline to avoid first-tick fallback
    with m._baseline_lock:
        m._baseline_price = 10000.0
    return m


# ── CircuitBreakerState tests ────────────────────────────────────────────────

class TestCircuitBreakerState:
    """Test the CircuitBreakerState dataclass."""

    def test_default_creation(self):
        s = CircuitBreakerState(level="NONE", index_change_pct=0.0, last_update=time.time(), is_market_halted=False)
        assert s.level == "NONE"
        assert s.index_change_pct == 0.0
        assert s.is_market_halted is False

    def test_halted_state(self):
        s = CircuitBreakerState(level="10%", index_change_pct=-12.5, last_update=time.time(), is_market_halted=True)
        assert s.level == "10%"
        assert s.index_change_pct == -12.5
        assert s.is_market_halted is True


# ── CircuitBreakerStateStore tests ───────────────────────────────────────────

class TestCircuitBreakerStateStore:
    """Test thread-safe wrapper."""

    def test_get_initial(self):
        s = CircuitBreakerState(level="NONE", index_change_pct=0.0, last_update=time.time(), is_market_halted=False)
        store = CircuitBreakerStateStore(s)
        assert store.level == "NONE"
        assert store.index_change_pct == 0.0
        assert store.is_market_halted is False

    def test_set_updates_state(self):
        s1 = CircuitBreakerState(level="NONE", index_change_pct=0.0, last_update=time.time(), is_market_halted=False)
        store = CircuitBreakerStateStore(s1)
        s2 = CircuitBreakerState(level="10%", index_change_pct=-12.0, last_update=time.time(), is_market_halted=True)
        store.set(s2)
        assert store.level == "10%"
        assert store.is_market_halted is True

    def test_get_returns_latest(self):
        store = CircuitBreakerStateStore(
            CircuitBreakerState(level="NONE", index_change_pct=0.0, last_update=time.time(), is_market_halted=False)
        )
        s = store.get()
        assert s.level == "NONE"


# ── NSECircuitBreakerMonitor construction ────────────────────────────────────

class TestNSECircuitBreakerMonitorConstruction:
    """Test monitor initialization."""

    def test_default_construction(self):
        m = NSECircuitBreakerMonitor()
        assert m._running is False
        assert m._state.level == "NONE"
        assert m._state.is_market_halted is False

    def test_start_stop(self, mock_send: MagicMock, mock_get_price: MagicMock):
        m = NSECircuitBreakerMonitor(send_fn=mock_send, get_index_price_fn=mock_get_price)
        m.start()
        assert m._running is True
        assert m._thread is not None
        assert m._thread.is_alive()
        m.stop()
        assert m._running is False

    def test_start_twice_noop(self, mock_send: MagicMock, mock_get_price: MagicMock):
        m = NSECircuitBreakerMonitor(send_fn=mock_send, get_index_price_fn=mock_get_price)
        m.start()
        thread_id = id(m._thread)
        m.start()  # Should be no-op
        assert id(m._thread) == thread_id
        m.stop()

    def test_get_state_default(self):
        m = NSECircuitBreakerMonitor()
        s = m.get_state()
        assert s.level == "NONE"
        assert s.is_market_halted is False


# ── Circuit breaker detection logic ──────────────────────────────────────────

class TestCircuitBreakerDetection:
    """Test the _check_circuit_breaker logic."""

    def test_no_halt_normal_move(self, monitor: NSECircuitBreakerMonitor, mock_send: MagicMock):
        """A small positive move should not trigger circuit breaker."""
        mock_send.reset_mock()
        monitor._get_index_price = MagicMock(return_value=10050.0)  # +0.5%
        monitor._check_circuit_breaker()
        assert monitor._state.level == "NONE"
        assert monitor._state.is_market_halted is False
        mock_send.assert_not_called()

    def test_no_halt_small_decline(self, monitor: NSECircuitBreakerMonitor, mock_send: MagicMock):
        """A small decline should not trigger circuit breaker."""
        mock_send.reset_mock()
        monitor._get_index_price = MagicMock(return_value=9950.0)  # -0.5%
        monitor._check_circuit_breaker()
        assert monitor._state.level == "NONE"
        assert monitor._state.is_market_halted is False
        mock_send.assert_not_called()

    def test_10pct_halt(self, monitor: NSECircuitBreakerMonitor, mock_send: MagicMock):
        """A 10% drop should trigger circuit breaker."""
        mock_send.reset_mock()
        monitor._get_index_price = MagicMock(return_value=8950.0)  # -10.5%
        with patch("core.circuit_breaker_monitor.trip_hard_halt") as mock_trip:
            monitor._check_circuit_breaker()
        assert monitor._state.level == "10%"
        assert monitor._state.is_market_halted is True
        assert mock_send.called

    def test_15pct_halt(self, monitor: NSECircuitBreakerMonitor, mock_send: MagicMock):
        """A 15% drop should trigger circuit breaker."""
        mock_send.reset_mock()
        monitor._get_index_price = MagicMock(return_value=8400.0)  # -16%
        with patch("core.circuit_breaker_monitor.trip_hard_halt") as mock_trip:
            monitor._check_circuit_breaker()
        assert monitor._state.level == "15%"
        assert monitor._state.is_market_halted is True

    def test_20pct_halt(self, monitor: NSECircuitBreakerMonitor, mock_send: MagicMock):
        """A 20% drop should trigger circuit breaker at highest level."""
        mock_send.reset_mock()
        monitor._get_index_price = MagicMock(return_value=7900.0)  # -21%
        with patch("core.circuit_breaker_monitor.trip_hard_halt") as mock_trip:
            monitor._check_circuit_breaker()
        assert monitor._state.level == "20%"
        assert monitor._state.is_market_halted is True

    def test_halt_sends_alert(self, monitor: NSECircuitBreakerMonitor, mock_send: MagicMock):
        """Circuit breaker should send an alert message."""
        mock_send.reset_mock()
        monitor._get_index_price = MagicMock(return_value=8500.0)  # -15%
        with patch("core.circuit_breaker_monitor.trip_hard_halt"):
            monitor._check_circuit_breaker()
        assert mock_send.called
        alert_text = mock_send.call_args[0][0]
        assert "CIRCUIT BREAKER" in alert_text
        assert "15%" in alert_text

    def test_null_price_noop(self, monitor: NSECircuitBreakerMonitor, mock_send: MagicMock):
        """None price should be a no-op."""
        mock_send.reset_mock()
        monitor._get_index_price = MagicMock(return_value=None)
        monitor._check_circuit_breaker()
        assert monitor._state.level == "NONE"
        mock_send.assert_not_called()

    def test_baseline_zero_skips(self, monitor: NSECircuitBreakerMonitor, mock_send: MagicMock):
        """Zero baseline should skip check."""
        mock_send.reset_mock()
        with monitor._baseline_lock:
            monitor._baseline_price = 0.0
        monitor._get_index_price = MagicMock(return_value=9000.0)
        monitor._check_circuit_breaker()
        assert monitor._state.level == "NONE"

    def test_exact_10pct_edge(self, monitor: NSECircuitBreakerMonitor, mock_send: MagicMock):
        """Exactly -10.0% should trigger 10% halt."""
        mock_send.reset_mock()
        monitor._get_index_price = MagicMock(return_value=9000.0)  # -10.0%
        with patch("core.circuit_breaker_monitor.trip_hard_halt"):
            monitor._check_circuit_breaker()
        assert monitor._state.level == "10%"

    def test_baseline_set_on_first_tick(self):
        """First tick should set baseline and return without checking."""
        m = NSECircuitBreakerMonitor()
        m._get_index_price = MagicMock(return_value=10000.0)
        m._check_circuit_breaker()
        with m._baseline_lock:
            assert m._baseline_price == 10000.0
        assert m._state.level == "NONE"  # Not checked on first tick


# ── handle_market_halt tests ────────────────────────────────────────────────

class TestHandleMarketHalt:
    """Test the _handle_market_halt method."""

    def test_trips_hard_halt(self, mock_send: MagicMock, mock_get_price: MagicMock):
        m = NSECircuitBreakerMonitor(send_fn=mock_send, get_index_price_fn=mock_get_price)
        with patch("core.circuit_breaker_monitor.trip_hard_halt") as mock_trip:
            m._handle_market_halt("15%")
        mock_trip.assert_called_once()
        assert "circuit breaker" in mock_trip.call_args[0][0].lower()
        assert mock_trip.call_args[1]["source"] == "NSECircuitBreakerMonitor._handle_market_halt"

    def test_sends_alert(self, mock_send: MagicMock, mock_get_price: MagicMock):
        m = NSECircuitBreakerMonitor(send_fn=mock_send, get_index_price_fn=mock_get_price)
        with patch("core.circuit_breaker_monitor.trip_hard_halt"):
            m._handle_market_halt("10%")
        assert mock_send.called
        text = mock_send.call_args[0][0]
        assert "10%" in text

    def test_records_halt_time(self, mock_send: MagicMock, mock_get_price: MagicMock):
        m = NSECircuitBreakerMonitor(send_fn=mock_send, get_index_price_fn=mock_get_price)
        with patch("core.circuit_breaker_monitor.trip_hard_halt"):
            m._handle_market_halt("20%")
        assert m._last_halt_time is not None


# ── reset_baseline tests ────────────────────────────────────────────────────

class TestResetBaseline:
    """Test resetting the circuit breaker baseline."""

    def test_reset_clears_baseline(self, monitor: NSECircuitBreakerMonitor):
        with monitor._baseline_lock:
            assert monitor._baseline_price is not None
        monitor.reset_baseline()
        with monitor._baseline_lock:
            assert monitor._baseline_price is None
        assert monitor._state.level == "NONE"
        assert monitor._state.is_market_halted is False


# ── create_circuit_breaker_monitor factory ───────────────────────────────────

class TestCreateCircuitBreakerMonitor:
    def test_factory_creates_and_starts(self, mock_send: MagicMock, mock_get_price: MagicMock):
        m = create_circuit_breaker_monitor(
            send_fn=mock_send,
            get_index_price_fn=mock_get_price,
            cfg={},
        )
        assert m._running is True
        assert m._thread is not None
        m.stop()
