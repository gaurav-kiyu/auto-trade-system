"""Tests for core/event_calendar.py - Event Calendar & Market Day Checks.

Covers:
- EventRecord dataclass
- _parse_event_dates() and _build_index()
- get_event(), event_entry_allowed(), event_size_multiplier()
- event_summary()
- MarketStatus enum
- is_market_day() with weekends, holidays, live API
- get_market_status(), is_pre_market()
- get_next_market_open(), get_time_until_market_open()
- sleep_until()
- CorporateAction dataclass
- fetch_corporate_actions(), is_corp_action_day()
"""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.event_calendar import (
    CorporateAction,
    EventRecord,
    MarketStatus,
    event_entry_allowed,
    event_size_multiplier,
    event_summary,
    fetch_corporate_actions,
    get_event,
    get_market_status,
    get_next_market_open,
    get_time_until_market_open,
    is_corp_action_day,
    is_market_day,
    is_pre_market,
    sleep_until,
)


class TestEventRecord:
    """EventRecord dataclass."""

    def test_fields(self):
        d = datetime.date(2026, 2, 1)
        ev = EventRecord(date=d, event_type="BUDGET", name="Union Budget",
                         block_entries=True, size_mult=0.5)
        assert ev.date == d
        assert ev.event_type == "BUDGET"
        assert ev.name == "Union Budget"
        assert ev.block_entries is True
        assert ev.size_mult == 0.5

    def test_repr(self):
        d = datetime.date(2026, 2, 1)
        ev = EventRecord(date=d, event_type="RBI", name="RBI Policy",
                         block_entries=False, size_mult=0.75)
        r = repr(ev)
        assert "RBI" in r
        assert "2026-02-01" in r


class TestGetEvent:
    """get_event() tests."""

    def test_no_event_configured(self):
        d = datetime.date(2026, 3, 15)
        cfg = {"event_calendar_enabled": True, "event_dates": []}
        assert get_event(d, cfg) is None

    def test_event_found(self):
        d = datetime.date(2026, 4, 1)
        cfg = {
            "event_calendar_enabled": True,
            "event_dates": [
                {"date": "2026-04-01", "type": "FOMC", "name": "Fed Meeting",
                 "block_entries": True, "size_mult": 0.5},
            ],
        }
        ev = get_event(d, cfg)
        assert ev is not None
        assert ev.event_type == "FOMC"
        assert ev.block_entries is True

    def test_disabled_returns_none(self):
        d = datetime.date(2026, 4, 1)
        cfg = {"event_calendar_enabled": False, "event_dates": []}
        assert get_event(d, cfg) is None

    def test_no_cfg_returns_none(self):
        d = datetime.date(2026, 4, 1)
        assert get_event(d, None) is None

    def test_bad_date_skipped(self):
        cfg = {
            "event_calendar_enabled": True,
            "event_dates": [
                {"date": "invalid", "type": "CUSTOM", "name": "Bad", "block_entries": False, "size_mult": 1.0},
            ],
        }
        d = datetime.date(2026, 4, 1)
        assert get_event(d, cfg) is None


class TestEventEntryAllowed:
    """event_entry_allowed()."""

    def test_no_event_allowed(self):
        d = datetime.date(2026, 5, 10)
        assert event_entry_allowed(d)[0] is True

    def test_block_entries(self):
        d = datetime.date(2026, 5, 10)
        cfg = {
            "event_calendar_enabled": True,
            "event_dates": [
                {"date": "2026-05-10", "type": "BUDGET", "name": "Budget Day",
                 "block_entries": True, "size_mult": 0.0},
            ],
        }
        allowed, reason = event_entry_allowed(d, cfg)
        assert allowed is False
        assert "blocked" in reason

    def test_non_blocking_event(self):
        d = datetime.date(2026, 5, 10)
        cfg = {
            "event_calendar_enabled": True,
            "event_dates": [
                {"date": "2026-05-10", "type": "RESULT", "name": "Results",
                 "block_entries": False, "size_mult": 0.8},
            ],
        }
        allowed, reason = event_entry_allowed(d, cfg)
        assert allowed is True
        assert reason == ""


class TestEventSizeMultiplier:
    """event_size_multiplier()."""

    def test_no_event_returns_1(self):
        d = datetime.date(2026, 6, 1)
        assert event_size_multiplier(d) == 1.0

    def test_event_reduces_size(self):
        d = datetime.date(2026, 6, 1)
        cfg = {
            "event_calendar_enabled": True,
            "event_dates": [
                {"date": "2026-06-01", "type": "FOMC", "name": "Fed",
                 "block_entries": False, "size_mult": 0.5},
            ],
        }
        mult = event_size_multiplier(d, cfg)
        assert mult == 0.5

    def test_multiplier_clamped(self):
        d = datetime.date(2026, 6, 1)
        cfg = {
            "event_calendar_enabled": True,
            "event_dates": [
                {"date": "2026-06-01", "type": "CUSTOM", "name": "Test",
                 "block_entries": False, "size_mult": 5.0},  # above max 1.0
            ],
        }
        mult = event_size_multiplier(d, cfg)
        assert mult == 1.0  # clamped to 1.0


class TestEventSummary:
    """event_summary()."""

    def test_no_event(self):
        d = datetime.date(2026, 7, 1)
        s = event_summary(d)
        assert s["is_event_day"] is False
        assert s["date"] == "2026-07-01"

    def test_with_event(self):
        d = datetime.date(2026, 7, 1)
        cfg = {
            "event_calendar_enabled": True,
            "event_dates": [
                {"date": "2026-07-01", "type": "RBI", "name": "RBI Policy",
                 "block_entries": True, "size_mult": 0.25},
            ],
        }
        s = event_summary(d, cfg)
        assert s["is_event_day"] is True
        assert s["type"] == "RBI"
        assert s["block_entries"] is True
        assert s["size_mult"] == 0.25


class TestMarketStatus:
    """MarketStatus enum and is_market_day."""

    def test_enum_values(self):
        assert MarketStatus.OPEN.value == "OPEN"
        assert MarketStatus.PRE_MARKET.value == "PRE_MARKET"
        assert MarketStatus.POST_MARKET.value == "POST_MARKET"
        assert MarketStatus.NON_TRADING.value == "NON_TRADING"

    def test_saturday_non_trading(self):
        # Jan 3 2026 = Saturday (weekday() == 5)
        assert is_market_day({}, check_date=datetime.date(2026, 1, 3)) is False

    def test_sunday_non_trading(self):
        assert is_market_day({}, check_date=datetime.date(2026, 1, 4)) is False

    def test_weekday_is_trading(self):
        # Jan 5 2026 = Monday
        assert is_market_day({}, check_date=datetime.date(2026, 1, 5)) is True

    def test_holiday_via_config(self):
        cfg = {
            "event_dates": [
                {"date": "2026-01-26", "type": "CUSTOM", "name": "Republic Day",
                 "block_entries": True, "size_mult": 0.0},
            ],
        }
        # Jan 26 2026 is Monday
        assert is_market_day(cfg, check_date=datetime.date(2026, 1, 26)) is False

    def test_nse_holidays_list(self):
        cfg = {
            "NSE_HOLIDAYS": ["2026-08-15"],
        }
        # Aug 15 2026 is Saturday (already weekend), so check a different date
        assert is_market_day(cfg, check_date=datetime.date(2026, 8, 15)) is False  # weekend

    @patch("core.event_calendar._get_live_holidays")
    def test_live_holidays_integrated(self, mock_get_live):
        mock_get_live.return_value = {datetime.date(2026, 3, 2)}
        # March 2 2026 = Monday
        assert is_market_day({}, check_date=datetime.date(2026, 3, 2)) is False

    @patch("core.datetime_ist.now_ist")
    def test_get_market_status_open(self, mock_now):
        mock_now.return_value = datetime.datetime(2026, 1, 5, 10, 0, 0)
        status = get_market_status({})
        assert status == MarketStatus.OPEN

    @patch("core.datetime_ist.now_ist")
    def test_get_market_status_pre(self, mock_now):
        mock_now.return_value = datetime.datetime(2026, 1, 5, 8, 0, 0)
        status = get_market_status({})
        assert status == MarketStatus.PRE_MARKET

    @patch("core.datetime_ist.now_ist")
    def test_get_market_status_post(self, mock_now):
        mock_now.return_value = datetime.datetime(2026, 1, 5, 16, 0, 0)
        status = get_market_status({})
        assert status == MarketStatus.POST_MARKET

    @patch("core.datetime_ist.now_ist")
    def test_get_market_status_non_trading(self, mock_now):
        mock_now.return_value = datetime.datetime(2026, 1, 3, 10, 0, 0)  # Saturday
        status = get_market_status({})
        assert status == MarketStatus.NON_TRADING

    def test_is_pre_market_false_during_market(self):
        with patch("core.event_calendar.get_market_status", return_value=MarketStatus.OPEN):
            assert is_pre_market({}) is False

    def test_is_pre_market_true(self):
        with patch("core.event_calendar.get_market_status", return_value=MarketStatus.PRE_MARKET):
            assert is_pre_market({}) is True


class TestNextMarketOpen:
    """get_next_market_open()."""

    def test_next_open_found(self):
        # From Friday 23:00, next open should be Monday 09:15
        with patch("core.event_calendar.is_market_day", side_effect=[False, False, True]):
            with patch("core.datetime_ist.now_ist") as mock_now:
                mock_now.return_value = datetime.datetime(2026, 1, 2, 23, 0, 0)  # Friday
                next_open = get_next_market_open({})
                assert next_open.hour == 9
                assert next_open.minute == 15

    def test_fallback_after_14_days(self):
        with patch("core.event_calendar.is_market_day", return_value=False):
            with patch("core.datetime_ist.now_ist") as mock_now:
                mock_now.return_value = datetime.datetime(2026, 1, 1, 10, 0, 0)
                next_open = get_next_market_open({})
                assert next_open is not None
                assert next_open.hour == 9
                assert next_open.minute == 15


class TestSleepUntil:
    """sleep_until()."""

    @patch("core.event_calendar._time.sleep")
    @patch("core.datetime_ist.now_ist")
    @patch("os.path.exists")
    def test_no_stop_file(self, mock_exists, mock_now, mock_sleep):
        mock_exists.return_value = False
        target = datetime.datetime(2026, 1, 5, 10, 0, 0)
        mock_now.return_value = datetime.datetime(2026, 1, 5, 9, 0, 0)  # 1 hour before
        sleep_until(target)
        mock_sleep.assert_called()

    @patch("core.event_calendar._time.sleep")
    @patch("core.datetime_ist.now_ist")
    @patch("os.path.exists")
    def test_stop_file_detected(self, mock_exists, mock_now, mock_sleep):
        mock_exists.return_value = True
        target = datetime.datetime(2026, 1, 5, 10, 0, 0)
        mock_now.return_value = datetime.datetime(2026, 1, 5, 9, 0, 0)
        sleep_until(target)
        # Stop file detected, should return without sleeping
        mock_sleep.assert_not_called()

    @patch("core.datetime_ist.now_ist")
    def test_already_past_target(self, mock_now):
        target = datetime.datetime(2026, 1, 5, 9, 0, 0)
        mock_now.return_value = datetime.datetime(2026, 1, 5, 10, 0, 0)  # after target
        sleep_until(target)  # should return immediately without error


class TestCorporateAction:
    """CorporateAction and related functions."""

    def test_dataclass(self):
        d = datetime.date(2026, 5, 15)
        ca = CorporateAction(symbol="HDFCBANK", date=d, action_type="DIVIDEND", factor=10.0)
        assert ca.symbol == "HDFCBANK"
        assert ca.date == d
        assert ca.action_type == "DIVIDEND"
        assert ca.factor == 10.0

    def test_fetch_disabled(self):
        assert fetch_corporate_actions({"corp_action_calendar_enabled": False}) == []

    def test_fetch_empty(self):
        assert fetch_corporate_actions({"corp_action_calendar_enabled": True}) == []

    def test_fetch_with_data(self):
        cfg = {
            "corp_action_calendar_enabled": True,
            "corp_action_data": [
                {"symbol": "HDFCBANK", "date": "2026-05-15", "type": "DIVIDEND", "factor": 10.0},
                {"symbol": "ICICIBANK", "date": "2026-06-01", "type": "SPLIT", "factor": 2.0},
            ],
        }
        actions = fetch_corporate_actions(cfg)
        assert len(actions) == 2
        assert actions[0].symbol == "HDFCBANK"
        assert actions[1].symbol == "ICICIBANK"
        assert actions[0].action_type == "DIVIDEND"

    def test_fetch_bad_entry_skipped(self):
        cfg = {
            "corp_action_calendar_enabled": True,
            "corp_action_data": [
                {"symbol": "BAD", "date": "invalid", "type": "UNKNOWN", "factor": 1.0},
            ],
        }
        actions = fetch_corporate_actions(cfg)
        assert actions == []

    def test_fetch_sorted_by_date(self):
        cfg = {
            "corp_action_calendar_enabled": True,
            "corp_action_data": [
                {"symbol": "B", "date": "2026-06-01", "type": "SPLIT", "factor": 2.0},
                {"symbol": "A", "date": "2026-05-01", "type": "DIVIDEND", "factor": 5.0},
            ],
        }
        actions = fetch_corporate_actions(cfg)
        assert actions[0].symbol == "A"
        assert actions[1].symbol == "B"

    def test_is_corp_action_day_found(self):
        cfg = {
            "corp_action_calendar_enabled": True,
            "corp_action_data": [
                {"symbol": "HDFCBANK", "date": "2026-05-15", "type": "DIVIDEND", "factor": 10.0},
            ],
        }
        found, desc = is_corp_action_day("HDFCBANK", datetime.date(2026, 5, 15), cfg)
        assert found is True
        assert "DIVIDEND" in desc

    def test_is_corp_action_day_not_found(self):
        cfg = {
            "corp_action_calendar_enabled": True,
            "corp_action_data": [],
        }
        found, desc = is_corp_action_day("HDFCBANK", datetime.date(2026, 5, 15), cfg)
        assert found is False
        assert desc == ""
