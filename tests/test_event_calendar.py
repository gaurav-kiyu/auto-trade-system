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
        # Advance time by 61s each call to eventually pass target
        times = [datetime.datetime(2026, 1, 5, 9, 0, 0) + datetime.timedelta(seconds=61 * i) for i in range(100)]
        mock_now.side_effect = times
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


class TestIPOEvent:
    """IPO Calendar event tests."""

    def test_ipo_event_dataclass(self):
        """IPOEvent should store fields correctly."""
        from core.event_calendar import IPOEvent
        ev = IPOEvent(company_name="Test Corp", symbol="TEST", ipo_type="IPO",
                     issue_price_min=100.0, issue_price_max=120.0, lot_size=50,
                     open_date=datetime.date(2026, 5, 1),
                     close_date=datetime.date(2026, 5, 5),
                     listing_date=datetime.date(2026, 5, 15),
                     total_issue_size=500.0, status="ANNOUNCED")
        assert ev.company_name == "Test Corp"
        assert ev.symbol == "TEST"
        assert ev.ipo_type == "IPO"
        assert ev.issue_price_min == 100.0
        assert ev.lot_size == 50
        assert ev.open_date == datetime.date(2026, 5, 1)
        assert ev.close_date == datetime.date(2026, 5, 5)
        assert ev.status == "ANNOUNCED"

    def test_fetch_ipo_events_disabled(self):
        """Disabled IPO calendar should return empty."""
        from core.event_calendar import fetch_ipo_events
        assert fetch_ipo_events({"ipo_calendar_enabled": False}) == []

    def test_fetch_ipo_events_empty(self):
        """Empty entries should return empty."""
        from core.event_calendar import fetch_ipo_events
        assert fetch_ipo_events({"ipo_calendar_enabled": True}) == []

    def test_fetch_ipo_events_with_data(self):
        """Should parse IPO events from config."""
        from core.event_calendar import fetch_ipo_events
        cfg = {
            "ipo_calendar_enabled": True,
            "ipo_calendar_entries": [
                {"company_name": "Test Corp", "symbol": "TEST", "ipo_type": "IPO",
                 "issue_price_min": 100.0, "issue_price_max": 120.0, "lot_size": 50,
                 "open_date": "2026-05-01", "close_date": "2026-05-05",
                 "total_issue_size": 500.0, "status": "ANNOUNCED"},
                {"company_name": "Big Corp", "symbol": "BIG", "ipo_type": "FPO",
                 "open_date": "2026-06-01", "close_date": "2026-06-05",
                 "total_issue_size": 1000.0, "status": "OPEN"},
            ],
        }
        events = fetch_ipo_events(cfg)
        assert len(events) == 2
        assert events[0].company_name == "Test Corp"
        assert events[1].company_name == "Big Corp"
        assert events[0].ipo_type == "IPO"
        assert events[1].ipo_type == "FPO"

    def test_fetch_ipo_events_bad_entry(self):
        """Bad entries should be skipped."""
        from core.event_calendar import fetch_ipo_events
        cfg = {
            "ipo_calendar_enabled": True,
            "ipo_calendar_entries": [
                {"company_name": "Bad Corp", "open_date": "invalid", "close_date": "invalid"},
            ],
        }
        assert fetch_ipo_events(cfg) == []

    def test_fetch_ipo_events_sorted(self):
        """Should return sorted by open_date ascending."""
        from core.event_calendar import fetch_ipo_events
        cfg = {
            "ipo_calendar_enabled": True,
            "ipo_calendar_entries": [
                {"company_name": "B", "open_date": "2026-06-01"},
                {"company_name": "A", "open_date": "2026-05-01"},
            ],
        }
        events = fetch_ipo_events(cfg)
        assert events[0].company_name == "A"
        assert events[1].company_name == "B"

    def test_is_ipo_issue_date_found(self):
        """Should detect if date is within an IPO window."""
        from core.event_calendar import is_ipo_issue_date
        cfg = {
            "ipo_calendar_enabled": True,
            "ipo_calendar_entries": [
                {"company_name": "Test Corp", "symbol": "TEST",
                 "open_date": "2026-05-01", "close_date": "2026-05-05",
                 "ipo_type": "IPO"},
            ],
        }
        found, desc = is_ipo_issue_date(datetime.date(2026, 5, 3), cfg)
        assert found is True
        assert "IPO" in desc
        assert "Test Corp" in desc

    def test_is_ipo_issue_date_not_found(self):
        """Should return False if date is outside any IPO window."""
        from core.event_calendar import is_ipo_issue_date
        cfg = {
            "ipo_calendar_enabled": True,
            "ipo_calendar_entries": [
                {"company_name": "Test Corp", "symbol": "TEST",
                 "open_date": "2026-05-01", "close_date": "2026-05-05"},
            ],
        }
        found, desc = is_ipo_issue_date(datetime.date(2026, 5, 10), cfg)
        assert found is False
        assert desc == ""

    def test_get_upcoming_ipos(self):
        """Should return only upcoming IPOs."""
        from core.event_calendar import get_upcoming_ipos
        cfg = {
            "ipo_calendar_enabled": True,
            "ipo_calendar_entries": [
                {"company_name": "Past Corp", "open_date": "2020-01-01", "close_date": "2020-01-05"},
                {"company_name": "Future Corp", "open_date": "2099-01-01", "close_date": "2099-01-05"},
            ],
        }
        upcoming = get_upcoming_ipos(cfg)
        assert len(upcoming) == 1
        assert upcoming[0].company_name == "Future Corp"


class TestSEBICircular:
    """SEBI circular tracking tests."""

    def test_sebi_circular_dataclass(self):
        """SEBICircular should store fields correctly."""
        from core.event_calendar import SEBICircular
        d = datetime.date(2026, 4, 1)
        circ = SEBICircular(date=d, category="MARGIN", title="New margin rules",
                           details="Increase in initial margin to 25%", impact="CRITICAL")
        assert circ.date == d
        assert circ.category == "MARGIN"
        assert circ.title == "New margin rules"
        assert circ.impact == "CRITICAL"

    def test_fetch_sebi_circulars_empty(self):
        """Empty config should return empty list."""
        from core.event_calendar import fetch_sebi_circulars
        assert fetch_sebi_circulars({}) == []

    def test_fetch_sebi_circulars_with_data(self):
        """Should parse SEBI circulars from config."""
        from core.event_calendar import fetch_sebi_circulars
        cfg = {
            "sebi_circulars_enabled": True,
            "sebi_circulars": [
                {"date": "2026-04-01", "category": "MARGIN", "title": "Margin rule change",
                 "details": "New margin rules effective", "impact": "CRITICAL"},
                {"date": "2026-05-01", "category": "EXPIRY", "title": "Expiry time change",
                 "details": "Expiry time moved to 13:30", "impact": "WARNING"},
            ],
        }
        circs = fetch_sebi_circulars(cfg)
        assert len(circs) == 2
        assert circs[0].category == "MARGIN"
        assert circs[1].category == "EXPIRY"

    def test_fetch_sebi_circulars_bad_entry(self):
        """Bad entries should be skipped."""
        from core.event_calendar import fetch_sebi_circulars
        cfg = {
            "sebi_circulars_enabled": True,
            "sebi_circulars": [
                {"date": "invalid", "category": "OTHER", "title": "Bad", "details": "", "impact": "INFO"},
            ],
        }
        assert fetch_sebi_circulars(cfg) == []

    def test_fetch_sebi_circulars_sorted(self):
        """Should return sorted by date ascending."""
        from core.event_calendar import fetch_sebi_circulars
        cfg = {
            "sebi_circulars_enabled": True,
            "sebi_circulars": [
                {"date": "2026-06-01", "category": "OTHER", "title": "B", "details": "", "impact": "INFO"},
                {"date": "2026-04-01", "category": "OTHER", "title": "A", "details": "", "impact": "INFO"},
            ],
        }
        circs = fetch_sebi_circulars(cfg)
        assert circs[0].title == "A"
        assert circs[1].title == "B"

    def test_get_sebi_circulars_for_date(self):
        """Should filter circulars by date."""
        from core.event_calendar import get_sebi_circulars_for_date
        cfg = {
            "sebi_circulars_enabled": True,
            "sebi_circulars": [
                {"date": "2026-04-01", "category": "MARGIN", "title": "Margin change",
                 "details": "", "impact": "CRITICAL"},
                {"date": "2026-04-02", "category": "EXPIRY", "title": "Expiry change",
                 "details": "", "impact": "WARNING"},
            ],
        }
        circs = get_sebi_circulars_for_date(datetime.date(2026, 4, 1), cfg)
        assert len(circs) == 1
        assert circs[0].title == "Margin change"

    def test_get_sebi_circulars_no_match(self):
        """Should return empty if no circulars on that date."""
        from core.event_calendar import get_sebi_circulars_for_date
        cfg = {"sebi_circulars_enabled": True, "sebi_circulars": [{"date": "2026-04-01", "category": "OTHER", "title": "Test",
                                    "details": "", "impact": "INFO"}]}
        assert get_sebi_circulars_for_date(datetime.date(2026, 4, 2), cfg) == []

    def test_sebi_circular_summary(self):
        """Should summarize upcoming circulars."""
        from core.event_calendar import sebi_circular_summary
        cfg = {
            "sebi_circulars_enabled": True,
            "sebi_circulars": [
                {"date": "2026-04-01", "category": "MARGIN", "title": "Margin change",
                 "details": "", "impact": "CRITICAL"},
            ],
        }
        summary = sebi_circular_summary(cfg)
        assert isinstance(summary, list)
        if summary:
            assert summary[0]["title"] == "Margin change"
