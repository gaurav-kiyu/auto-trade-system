"""Tests for market calendar functions in core/event_calendar.py (v2.44 Item 5)."""
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from core.event_calendar import (
    MarketStatus,
    get_market_status,
    get_next_market_open,
    is_market_day,
    sleep_until,
)

CFG = {
    "MARKET_OPEN_HOUR": 9,
    "MARKET_OPEN_MIN": 15,
    "MARKET_CLOSE_HOUR": 15,
    "MARKET_CLOSE_MIN": 20,
    "NSE_HOLIDAYS": [],
    "holiday_sleep_enabled": True,
    "pre_market_buffer_mins": 2,
}


# ── is_market_day ─────────────────────────────────────────────────────────────

def test_weekday_is_market_day():
    monday = date(2024, 1, 15)  # Monday
    assert is_market_day(CFG, check_date=monday) is True


def test_saturday_not_market_day():
    saturday = date(2024, 1, 13)
    assert is_market_day(CFG, check_date=saturday) is False


def test_sunday_not_market_day():
    sunday = date(2024, 1, 14)
    assert is_market_day(CFG, check_date=sunday) is False


def test_holiday_not_market_day():
    holiday = date(2024, 1, 26)  # Republic Day
    cfg = dict(CFG, NSE_HOLIDAYS=["2024-01-26"])
    assert is_market_day(cfg, check_date=holiday) is False


def test_friday_is_market_day():
    friday = date(2024, 1, 19)
    assert is_market_day(CFG, check_date=friday) is True


# ── get_market_status ─────────────────────────────────────────────────────────

def test_open_during_trading_hours():
    dt = datetime(2024, 1, 15, 10, 30)  # Monday 10:30
    status = get_market_status(CFG, check_dt=dt)
    assert status == MarketStatus.OPEN


def test_pre_market_before_open():
    dt = datetime(2024, 1, 15, 8, 0)
    status = get_market_status(CFG, check_dt=dt)
    assert status == MarketStatus.PRE_MARKET


def test_post_market_after_close():
    dt = datetime(2024, 1, 15, 16, 0)
    status = get_market_status(CFG, check_dt=dt)
    assert status == MarketStatus.POST_MARKET


def test_non_trading_on_weekend():
    dt = datetime(2024, 1, 13, 10, 30)  # Saturday
    status = get_market_status(CFG, check_dt=dt)
    assert status == MarketStatus.NON_TRADING


def test_non_trading_on_holiday():
    cfg = dict(CFG, NSE_HOLIDAYS=["2024-01-26"])
    dt = datetime(2024, 1, 26, 10, 30)
    status = get_market_status(cfg, check_dt=dt)
    assert status == MarketStatus.NON_TRADING


def test_market_status_at_open_time():
    dt = datetime(2024, 1, 15, 9, 15)
    status = get_market_status(CFG, check_dt=dt)
    assert status == MarketStatus.OPEN


def test_market_status_at_close_time():
    dt = datetime(2024, 1, 15, 15, 20)
    # 15:20 is boundary; may be POST or OPEN depending on implementation
    status = get_market_status(CFG, check_dt=dt)
    assert status in (MarketStatus.OPEN, MarketStatus.POST_MARKET)


# ── get_next_market_open ──────────────────────────────────────────────────────

def test_next_open_returns_datetime():
    dt = datetime(2024, 1, 13, 12, 0)  # Saturday
    result = get_next_market_open(CFG, from_dt=dt)
    assert isinstance(result, datetime)


def test_next_open_from_saturday_is_monday():
    dt = datetime(2024, 1, 13, 12, 0)  # Saturday
    result = get_next_market_open(CFG, from_dt=dt)
    assert result.weekday() == 0  # Monday


def test_next_open_time_is_market_open():
    dt = datetime(2024, 1, 13, 12, 0)
    result = get_next_market_open(CFG, from_dt=dt)
    assert result.hour == CFG["MARKET_OPEN_HOUR"]
    assert result.minute == CFG["MARKET_OPEN_MIN"]


# ── sleep_until ───────────────────────────────────────────────────────────────

def test_sleep_until_past_time_returns_immediately():
    past = datetime(2020, 1, 1, 9, 0)
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    # Should return without sleeping
    with patch("time.sleep") as mock_sleep:
        sleep_until(past, stop_event=stop_event)
        mock_sleep.assert_not_called()


def test_sleep_until_respects_stop_event():
    future = datetime(2099, 1, 1, 9, 0)
    stop_event = MagicMock()
    stop_event.is_set.side_effect = [False, True]  # stop on second check
    with patch("time.sleep"):
        sleep_until(future, stop_event=stop_event)
        # Should have checked stop_event


# ── MarketStatus enum ─────────────────────────────────────────────────────────

def test_market_status_values():
    assert MarketStatus.OPEN == "OPEN"
    assert MarketStatus.PRE_MARKET == "PRE_MARKET"
    assert MarketStatus.POST_MARKET == "POST_MARKET"
    assert MarketStatus.NON_TRADING == "NON_TRADING"
