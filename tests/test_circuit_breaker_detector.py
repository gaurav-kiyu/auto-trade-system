"""Tests for core/circuit_breaker_detector.py - Circuit Breaker Detector.

Covers:
- CircuitBreakerLevel, MarketStatus enums
- CircuitBreakerState dataclass
- CircuitBreakerDetector init, start, stop
- check_market_status (time-based)
- check_now (price-based level detection)
- is_trading_allowed (various states)
- reset_reference_price
- NseHalts helper class
- create_circuit_breaker_detector factory
- Callback on circuit breaker trigger
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.circuit_breaker_detector import (
    CircuitBreakerDetector,
    CircuitBreakerLevel,
    CircuitBreakerState,
    MarketStatus,
    NseHalts,
    create_circuit_breaker_detector,
)


# =============================================================================
# Enum Tests
# =============================================================================

class TestCircuitBreakerLevel:
    def test_values(self):
        assert CircuitBreakerLevel.NONE.value == "NONE"
        assert CircuitBreakerLevel.LEVEL_1.value == "LEVEL_1"
        assert CircuitBreakerLevel.LEVEL_2.value == "LEVEL_2"
        assert CircuitBreakerLevel.LEVEL_3.value == "LEVEL_3"
        assert CircuitBreakerLevel.MARKET_HALT.value == "MARKET_HALT"


class TestMarketStatus:
    def test_values(self):
        assert MarketStatus.OPEN.value == "OPEN"
        assert MarketStatus.CLOSED.value == "CLOSED"
        assert MarketStatus.PRE_OPEN.value == "PRE_OPEN"
        assert MarketStatus.POST_CLOSE.value == "POST_CLOSE"
        assert MarketStatus.HALTED.value == "HALTED"
        assert MarketStatus.UNKNOWN.value == "UNKNOWN"


# =============================================================================
# CircuitBreakerState Tests
# =============================================================================

class TestCircuitBreakerState:
    def test_creation(self):
        now = datetime(2026, 6, 20, 10, 0, 0)
        state = CircuitBreakerState(
            level=CircuitBreakerLevel.NONE,
            market_status=MarketStatus.OPEN,
            last_check=now,
            trigger_price=50000.0,
            current_price=51000.0,
            reference_price=50000.0,
            percent_change=2.0,
        )
        assert state.level == CircuitBreakerLevel.NONE
        assert state.market_status == MarketStatus.OPEN
        assert state.percent_change == 2.0


# =============================================================================
# CircuitBreakerDetector Init Tests
# =============================================================================

class TestInit:
    def test_defaults(self):
        detector = CircuitBreakerDetector()
        assert detector._index_name == "NIFTY"
        assert detector._check_interval == 30
        assert detector._price_getter is None
        assert detector._on_circuit_breaker is None
        assert detector._running is False

    def test_custom_params(self):
        price_getter = MagicMock()
        cb = MagicMock()
        detector = CircuitBreakerDetector(
            price_getter=price_getter,
            index_name="BANKNIFTY",
            check_interval=60,
            on_circuit_breaker=cb,
        )
        assert detector._price_getter is price_getter
        assert detector._index_name == "BANKNIFTY"
        assert detector._on_circuit_breaker is cb


# =============================================================================
# check_market_status Tests
# =============================================================================

class TestCheckMarketStatus:
    def test_weekend_closed(self):
        detector = CircuitBreakerDetector()
        # Saturday
        saturday = datetime(2026, 6, 20, 12, 0, 0)  # June 20, 2026 is a Saturday
        assert detector.check_market_status(saturday) == MarketStatus.CLOSED

    def test_pre_open_window(self):
        detector = CircuitBreakerDetector()
        # 9:10 AM - 5 minutes before open
        pre_open = datetime(2026, 6, 22, 9, 10, 0)  # Monday
        assert detector.check_market_status(pre_open) == MarketStatus.PRE_OPEN

    def test_market_open(self):
        detector = CircuitBreakerDetector()
        # 11:00 AM
        market_hours = datetime(2026, 6, 22, 11, 0, 0)  # Monday
        assert detector.check_market_status(market_hours) == MarketStatus.OPEN

    def test_post_close(self):
        detector = CircuitBreakerDetector()
        # 15:45 - after close
        post_close = datetime(2026, 6, 22, 15, 45, 0)  # Monday
        assert detector.check_market_status(post_close) == MarketStatus.POST_CLOSE

    def test_early_morning_closed(self):
        detector = CircuitBreakerDetector()
        # 7:00 AM - well before open
        early = datetime(2026, 6, 22, 7, 0, 0)  # Monday
        assert detector.check_market_status(early) == MarketStatus.CLOSED


# =============================================================================
# check_now Tests (price-based)
# =============================================================================

class TestCheckNow:
    def test_no_price_getter_returns_none_level(self):
        with patch("core.circuit_breaker_detector.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 22, 11, 0, 0)  # Monday 11am
            detector = CircuitBreakerDetector()
            state = detector.check_now()
            assert state.current_price is None
            assert state.market_status == MarketStatus.OPEN

    def test_price_within_normal_range(self):
        """Price staying within 10% change should be NONE level."""
        with patch("core.circuit_breaker_detector.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 22, 11, 0, 0)  # Monday 11am
            price_getter = MagicMock(return_value=50500.0)
            detector = CircuitBreakerDetector(price_getter=price_getter)
            # First call sets reference price
            detector.check_now()
            # Second call with ~1% change
            price_getter.return_value = 50800.0
            state = detector.check_now()
            assert state.level == CircuitBreakerLevel.NONE

    def test_level_1_trigger(self):
        """10% change triggers LEVEL_1."""
        with patch("core.circuit_breaker_detector.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 22, 11, 0, 0)  # Monday 11am
            price_getter = MagicMock()
            detector = CircuitBreakerDetector(price_getter=price_getter)
            price_getter.return_value = 50000.0
            detector.check_now()
            price_getter.return_value = 55500.0  # 11% gain
            state = detector.check_now()
            assert state.level == CircuitBreakerLevel.LEVEL_1

    def test_level_2_trigger(self):
        with patch("core.circuit_breaker_detector.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 22, 11, 0, 0)
            price_getter = MagicMock()
            detector = CircuitBreakerDetector(price_getter=price_getter)
            price_getter.return_value = 50000.0
            detector.check_now()
            price_getter.return_value = 58000.0  # 16% gain
            state = detector.check_now()
            assert state.level == CircuitBreakerLevel.LEVEL_2

    def test_level_3_trigger(self):
        with patch("core.circuit_breaker_detector.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 22, 11, 0, 0)
            price_getter = MagicMock()
            detector = CircuitBreakerDetector(price_getter=price_getter)
            price_getter.return_value = 50000.0
            detector.check_now()
            price_getter.return_value = 61000.0  # 22% gain
            state = detector.check_now()
            assert state.level == CircuitBreakerLevel.LEVEL_3

    def test_negative_change_level_1(self):
        with patch("core.circuit_breaker_detector.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 22, 11, 0, 0)
            price_getter = MagicMock()
            detector = CircuitBreakerDetector(price_getter=price_getter)
            price_getter.return_value = 50000.0
            detector.check_now()
            price_getter.return_value = 44000.0  # -12% (abs 12%)
            state = detector.check_now()
            assert state.level == CircuitBreakerLevel.LEVEL_1


# =============================================================================
# is_trading_allowed Tests
# =============================================================================

class TestIsTradingAllowed:
    def test_allows_normal(self):
        detector = CircuitBreakerDetector()
        allowed, msg = detector.is_trading_allowed()
        assert allowed is True

    def test_blocks_market_halt(self):
        detector = CircuitBreakerDetector()
        detector._state.level = CircuitBreakerLevel.MARKET_HALT
        allowed, msg = detector.is_trading_allowed()
        assert allowed is False
        assert "Market halted" in msg

    def test_blocks_closed_market(self):
        detector = CircuitBreakerDetector()
        detector._state.market_status = MarketStatus.CLOSED
        allowed, msg = detector.is_trading_allowed()
        assert allowed is False
        assert "Market closed" in msg

    def test_blocks_level_2(self):
        detector = CircuitBreakerDetector()
        detector._state.level = CircuitBreakerLevel.LEVEL_2
        detector._state.percent_change = 16.0
        allowed, msg = detector.is_trading_allowed()
        assert allowed is False
        assert "LEVEL_2" in msg

    def test_blocks_level_3(self):
        detector = CircuitBreakerDetector()
        detector._state.level = CircuitBreakerLevel.LEVEL_3
        allowed, msg = detector.is_trading_allowed()
        assert allowed is False


# =============================================================================
# Callback Tests
# =============================================================================

class TestCallback:
    def test_callback_invoked_on_trigger(self):
        with patch("core.circuit_breaker_detector.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 22, 11, 0, 0)
            callback = MagicMock()
            price_getter = MagicMock()
            detector = CircuitBreakerDetector(
                price_getter=price_getter,
                on_circuit_breaker=callback,
            )
            price_getter.return_value = 50000.0
            detector.check_now()
            price_getter.return_value = 55500.0  # 11% -> Level 1
            detector.check_now()
            callback.assert_called_once_with(CircuitBreakerLevel.LEVEL_1, pytest.approx(11.0, abs=0.5))

    def test_callback_not_invoked_on_normal(self):
        with patch("core.circuit_breaker_detector.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 22, 11, 0, 0)
            callback = MagicMock()
            price_getter = MagicMock(return_value=50000.0)
            detector = CircuitBreakerDetector(
                price_getter=price_getter,
                on_circuit_breaker=callback,
            )
            detector.check_now()
            detector.check_now()  # Same price, no trigger
            callback.assert_not_called()


# =============================================================================
# reset_reference_price Tests
# =============================================================================

class TestResetReferencePrice:
    def test_resets_state(self):
        detector = CircuitBreakerDetector()
        detector._reference_price = 50000.0
        detector._state.level = CircuitBreakerLevel.LEVEL_1
        detector._state.percent_change = 10.5
        detector.reset_reference_price()
        assert detector._reference_price is None
        assert detector._last_trading_date is None
        assert detector._state.level == CircuitBreakerLevel.NONE
        assert detector._state.percent_change is None


# =============================================================================
# get_state Tests
# =============================================================================

class TestGetState:
    def test_returns_copy(self):
        detector = CircuitBreakerDetector()
        state = detector.get_state()
        assert isinstance(state, CircuitBreakerState)
        assert state.level == CircuitBreakerLevel.NONE


# =============================================================================
# NseHalts Tests
# =============================================================================

class TestNseHalts:
    def test_no_broker_returns_false(self):
        halted, _ = NseHalts.check_halt_status(None)
        assert halted is False

    def test_broker_with_get_market_status_halted(self):
        broker = MagicMock()
        broker.get_market_status.return_value = {"halted": True, "reason": "Circuit breaker"}
        halted, reason = NseHalts.check_halt_status(broker)
        assert halted is True
        assert reason == "Circuit breaker"

    def test_broker_with_get_market_status_not_halted(self):
        broker = MagicMock(spec=object)
        broker.get_market_status = MagicMock(return_value={"halted": False})
        halted, _ = NseHalts.check_halt_status(broker)
        assert halted is False

    def test_broker_with_is_market_halted(self):
        broker = MagicMock()
        broker.is_market_halted.return_value = True
        halted, _ = NseHalts.check_halt_status(broker)
        assert halted is True

    def test_broker_with_neither_method(self):
        broker = MagicMock(spec=object)
        halted, _ = NseHalts.check_halt_status(broker)
        assert halted is False

    def test_method_raises_exception(self):
        broker = MagicMock()
        broker.get_market_status.side_effect = AttributeError("No such method")
        halted, _ = NseHalts.check_halt_status(broker)
        assert halted is False


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestCreateCircuitBreakerDetector:
    def test_creates_detector(self):
        detector = create_circuit_breaker_detector()
        assert isinstance(detector, CircuitBreakerDetector)

    def test_with_price_getter(self):
        pg = MagicMock()
        detector = create_circuit_breaker_detector(price_getter=pg)
        assert detector._price_getter is pg
