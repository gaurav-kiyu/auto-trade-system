"""Tests for CircuitBreakerDetector — NSE market halt and circuit breaker detection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from datetime import datetime

from core.circuit_breaker_detector import (
    CircuitBreakerDetector,
    CircuitBreakerLevel,
    CircuitBreakerState,
    MarketStatus,
    NseHalts,
    create_circuit_breaker_detector,
)


class TestCircuitBreakerLevel:
    """CircuitBreakerLevel enum."""

    def test_values(self):
        assert CircuitBreakerLevel.NONE.value == "NONE"
        assert CircuitBreakerLevel.LEVEL_1.value == "LEVEL_1"
        assert CircuitBreakerLevel.LEVEL_2.value == "LEVEL_2"
        assert CircuitBreakerLevel.LEVEL_3.value == "LEVEL_3"
        assert CircuitBreakerLevel.MARKET_HALT.value == "MARKET_HALT"


class TestMarketStatus:
    """MarketStatus enum."""

    def test_values(self):
        assert MarketStatus.OPEN.value == "OPEN"
        assert MarketStatus.CLOSED.value == "CLOSED"
        assert MarketStatus.PRE_OPEN.value == "PRE_OPEN"
        assert MarketStatus.POST_CLOSE.value == "POST_CLOSE"
        assert MarketStatus.HALTED.value == "HALTED"
        assert MarketStatus.UNKNOWN.value == "UNKNOWN"


class TestCircuitBreakerDetector:
    """CircuitBreakerDetector — circuit breaker logic."""

    def setup_method(self):
        self.detector = CircuitBreakerDetector(
            price_getter=lambda x: 25000.0,
            index_name="NIFTY",
        )

    def test_initial_state(self):
        state = self.detector.get_state()
        assert state.level == CircuitBreakerLevel.NONE
        assert state.market_status == MarketStatus.UNKNOWN
        assert state.trigger_price is None
        assert state.current_price is None

    def test_set_price_getter(self):
        getter = lambda x: 26000.0
        self.detector.set_price_getter(getter)
        price = self.detector._get_current_price()
        assert price == 26000.0

    def test_get_price_no_getter(self):
        d = CircuitBreakerDetector()
        assert d._get_current_price() is None

    def test_check_market_status_weekend(self):
        # Saturday = 5
        with patch("core.circuit_breaker_detector.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 13, 10, 0)
            assert self.detector.check_market_status() == MarketStatus.CLOSED

    def test_check_market_status_pre_open(self):
        with patch("core.circuit_breaker_detector.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 11, 9, 10)
            status = self.detector.check_market_status()
            assert status == MarketStatus.PRE_OPEN

    def test_check_market_status_closed_morning(self):
        with patch("core.circuit_breaker_detector.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 11, 8, 0)
            assert self.detector.check_market_status() == MarketStatus.CLOSED

    def test_check_market_status_open(self):
        with patch("core.circuit_breaker_detector.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 11, 11, 0)
            assert self.detector.check_market_status() == MarketStatus.OPEN

    def test_check_market_status_post_close(self):
        with patch("core.circuit_breaker_detector.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 11, 15, 31)
            assert self.detector.check_market_status() == MarketStatus.POST_CLOSE

    @patch("core.circuit_breaker_detector.now_ist", return_value=datetime(2026, 6, 11, 11, 0))
    def test_check_now_no_price(self, mock_now):
        d = CircuitBreakerDetector()
        state = d.check_now()
        assert state.level == CircuitBreakerLevel.NONE

    @patch("core.circuit_breaker_detector.now_ist", return_value=datetime(2026, 6, 11, 11, 0))
    def test_check_now_no_level_change(self, mock_now):
        state = self.detector.check_now()
        assert state.level == CircuitBreakerLevel.NONE
        assert state.current_price == 25000.0
        assert state.reference_price == 25000.0

    @patch("core.circuit_breaker_detector.now_ist", return_value=datetime(2026, 6, 11, 11, 0))
    def test_cb_level_1_triggered(self, mock_now):
        d = CircuitBreakerDetector(price_getter=lambda x: 22000.0)
        d._reference_price = 25000.0
        d._last_trading_date = datetime(2026, 6, 11).date()
        state = d.check_now()
        assert state.level == CircuitBreakerLevel.LEVEL_1
        assert state.trigger_price == 22000.0

    @patch("core.circuit_breaker_detector.now_ist", return_value=datetime(2026, 6, 11, 11, 0))
    def test_cb_level_2_triggered(self, mock_now):
        d = CircuitBreakerDetector(price_getter=lambda x: 21000.0)
        d._reference_price = 25000.0
        d._last_trading_date = datetime(2026, 6, 11).date()
        state = d.check_now()
        assert state.level == CircuitBreakerLevel.LEVEL_2

    @patch("core.circuit_breaker_detector.now_ist", return_value=datetime(2026, 6, 11, 11, 0))
    def test_cb_level_3_triggered(self, mock_now):
        d = CircuitBreakerDetector(price_getter=lambda x: 19000.0)
        d._reference_price = 25000.0
        d._last_trading_date = datetime(2026, 6, 11).date()
        state = d.check_now()
        assert state.level == CircuitBreakerLevel.LEVEL_3

    @patch("core.circuit_breaker_detector.now_ist", return_value=datetime(2026, 6, 11, 11, 0))
    def test_positive_change_no_level(self, mock_now):
        d = CircuitBreakerDetector(price_getter=lambda x: 26000.0)
        d._reference_price = 25000.0
        d._last_trading_date = datetime(2026, 6, 11).date()
        state = d.check_now()
        assert state.level == CircuitBreakerLevel.NONE

    @patch("core.circuit_breaker_detector.now_ist", return_value=datetime(2026, 6, 11, 11, 0))
    def test_callback_on_trigger(self, mock_now):
        callback = MagicMock()
        d = CircuitBreakerDetector(
            price_getter=lambda x: 22000.0,
            on_circuit_breaker=callback,
        )
        d._reference_price = 25000.0
        d._last_trading_date = datetime(2026, 6, 11).date()
        d.check_now()
        callback.assert_called_once()

    def test_is_trading_allowed_normal(self):
        allowed, msg = self.detector.is_trading_allowed()
        assert allowed
        assert "Trading allowed" in msg

    @patch("core.circuit_breaker_detector.now_ist", return_value=datetime(2026, 6, 11, 11, 0))
    def test_is_trading_allowed_level_2(self, mock_now):
        d = CircuitBreakerDetector(price_getter=lambda x: 21000.0)
        d._reference_price = 25000.0
        d._last_trading_date = datetime(2026, 6, 11).date()
        d.check_now()
        allowed, msg = d.is_trading_allowed()
        assert not allowed
        assert "LEVEL_2" in msg

    @patch("core.circuit_breaker_detector.now_ist", return_value=datetime(2026, 6, 11, 11, 0))
    def test_is_trading_allowed_level_3(self, mock_now):
        d = CircuitBreakerDetector(price_getter=lambda x: 19000.0)
        d._reference_price = 25000.0
        d._last_trading_date = datetime(2026, 6, 11).date()
        d.check_now()
        allowed, msg = d.is_trading_allowed()
        assert not allowed
        assert "LEVEL_3" in msg

    def test_is_trading_allowed_market_halt(self):
        # Modify internal state directly (get_state() returns a copy)
        self.detector._state.level = CircuitBreakerLevel.MARKET_HALT
        allowed, msg = self.detector.is_trading_allowed()
        assert not allowed
        assert "Market halted" in msg

    def test_is_trading_allowed_closed(self):
        with patch("core.circuit_breaker_detector.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 11, 15, 31)
            state = self.detector.check_now()
            allowed, msg = self.detector.is_trading_allowed()
            assert not allowed
            assert "post-close" in msg or "closed" in msg

    def test_reset_reference_price(self):
        self.detector._reference_price = 25000.0
        self.detector._last_trading_date = datetime(2026, 6, 11).date()
        self.detector.reset_reference_price()
        assert self.detector._reference_price is None
        assert self.detector._last_trading_date is None
        assert self.detector._state.level == CircuitBreakerLevel.NONE

    def test_start_stop(self):
        self.detector.start()
        assert self.detector._running is True
        self.detector.stop()
        assert self.detector._running is False

    def test_double_start_noop(self):
        self.detector.start()
        self.detector.start()
        assert self.detector._running is True
        self.detector.stop()


class TestCircuitBreakerState:
    """CircuitBreakerState dataclass."""

    def test_create_state(self):
        now = datetime(2026, 6, 11, 10, 0)
        state = CircuitBreakerState(
            level=CircuitBreakerLevel.LEVEL_1,
            market_status=MarketStatus.OPEN,
            last_check=now,
            trigger_price=22000.0,
            current_price=22000.0,
            reference_price=25000.0,
            percent_change=-12.0,
        )
        assert state.level == CircuitBreakerLevel.LEVEL_1
        assert state.percent_change == -12.0


class TestCreateCircuitBreakerDetector:
    """Factory function."""

    def test_default_creation(self):
        d = create_circuit_breaker_detector()
        assert isinstance(d, CircuitBreakerDetector)
        assert d._index_name == "NIFTY"

    def test_with_price_getter(self):
        getter = lambda x: 25000.0
        d = create_circuit_breaker_detector(price_getter=getter, index_name="BANKNIFTY")
        assert d._index_name == "BANKNIFTY"
        assert d._get_current_price() == 25000.0


class TestNseHalts:
    """NseHalts static helper."""

    def test_no_broker(self):
        halted, reason = NseHalts.check_halt_status(None)
        assert not halted
        assert reason == "No broker"

    def test_broker_with_market_status_halted(self):
        broker = MagicMock()
        broker.get_market_status.return_value = {"halted": True, "reason": "Circuit break"}
        halted, reason = NseHalts.check_halt_status(broker)
        assert halted
        assert "Circuit break" in reason

    def test_broker_with_market_status_not_halted(self):
        broker = MagicMock()
        broker.get_market_status.return_value = {"halted": False}
        # Prevent MagicMock auto-creating truthy is_market_halted
        broker.is_market_halted.return_value = False
        halted, reason = NseHalts.check_halt_status(broker)
        assert not halted

    def test_broker_with_is_market_halted(self):
        broker = MagicMock()
        broker.is_market_halted.return_value = True
        halted, reason = NseHalts.check_halt_status(broker)
        assert halted

    def test_broker_with_no_methods(self):
        broker = MagicMock(spec=[])
        halted, reason = NseHalts.check_halt_status(broker)
        assert not halted
