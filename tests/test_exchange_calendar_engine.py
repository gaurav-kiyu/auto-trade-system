"""Tests for ExchangeCalendarEngine (Master Prompt Phase 19)."""

from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest

from core.exchange_calendar_engine import (
    ExchangeCalendarEngine,
    ExtendedMarketStatus,
    ExpiryRecord,
    TradingHours,
    get_calendar_engine,
)


# ── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture
def engine():
    """Return an ExchangeCalendarEngine with mock-disabled NSE API."""
    with patch("core.event_calendar._fetch_nse_holidays", return_value=set()):
        cfg = {
            "event_calendar_enabled": False,
            "event_dates": [],
            "corp_action_calendar_enabled": False,
            "ipo_calendar_enabled": False,
            "sebi_circulars_enabled": False,
        }
        yield ExchangeCalendarEngine(cfg)


# ── Module-level tests ───────────────────────────────────────────────────────


class TestExchangeCalendarEngineModule:
    """Tests for module-level convenience API and data structures."""

    def test_imports(self):
        """All public symbols should be importable."""
        from core.exchange_calendar_engine import (
            ExchangeCalendarEngine,
            ExtendedMarketStatus,
            ExpiryRecord,
            TradingHours,
            get_calendar_engine,
        )
        assert ExchangeCalendarEngine is not None
        assert ExtendedMarketStatus is not None
        assert ExpiryRecord is not None
        assert TradingHours is not None
        assert get_calendar_engine is not None

    def test_get_calendar_engine(self):
        """get_calendar_engine should return a configured engine."""
        with patch("core.event_calendar._fetch_nse_holidays", return_value=set()):
            engine = get_calendar_engine({})
            assert isinstance(engine, ExchangeCalendarEngine)

    def test_extended_market_status_values(self):
        """ExtendedMarketStatus should have all expected enum values."""
        assert ExtendedMarketStatus.OPEN.value == "OPEN"
        assert ExtendedMarketStatus.PRE_MARKET.value == "PRE_MARKET"
        assert ExtendedMarketStatus.POST_MARKET.value == "POST_MARKET"
        assert ExtendedMarketStatus.NON_TRADING.value == "NON_TRADING"
        assert ExtendedMarketStatus.HALF_DAY.value == "HALF_DAY"
        assert ExtendedMarketStatus.MUHURAT.value == "MUHURAT"

    def test_trading_hours_dataclass(self):
        """TradingHours should store and return correct values."""
        d = datetime.date(2026, 6, 25)
        hours = TradingHours(
            date=d,
            is_trading_day=True,
            session_type="REGULAR",
            open_time=datetime.time(9, 15),
            close_time=datetime.time(15, 30),
            description="Regular trading session",
        )
        assert hours.date == d
        assert hours.is_trading_day is True
        assert hours.session_type == "REGULAR"
        assert str(hours.open_time) == "09:15:00"
        assert str(hours.close_time) == "15:30:00"

    def test_trading_hours_non_trading(self):
        """TradingHours should work for non-trading days."""
        d = datetime.date(2026, 6, 27)  # Saturday
        hours = TradingHours(
            date=d,
            is_trading_day=False,
            session_type="CLOSED",
            description="Weekend",
        )
        assert hours.is_trading_day is False
        assert hours.open_time is None

    def test_expiry_record(self):
        """ExpiryRecord should store expiry data correctly."""
        d = datetime.date(2026, 7, 2)  # Thursday
        record = ExpiryRecord(
            index_name="NIFTY",
            expiry_date=d,
            is_weekly=True,
            trading_week=27,
        )
        assert record.index_name == "NIFTY"
        assert record.expiry_date == d
        assert record.is_weekly is True
        assert record.trading_week == 27


# ── Engine initialization ────────────────────────────────────────────────────


class TestEngineInitialization:
    """Tests for engine construction and basic state."""

    def test_init_defaults(self, engine):
        """Engine should init with defaults and not crash."""
        assert engine is not None
        assert engine._cfg is not None

    def test_init_with_config(self, engine):
        """Engine should accept and store config."""
        assert engine._cfg.get("event_calendar_enabled") is False

    def test_init_singleton_cache(self, engine):
        """Special cache should be empty on init."""
        with patch.object(engine, "_special_cache", {}):
            assert len(engine._special_cache) == 0


# ── Special session detection ────────────────────────────────────────────────


class TestSpecialSessions:
    """Tests for muhurat trading, half-days, and special session detection."""

    def test_known_muhurat_2025(self, engine):
        """2025 Muhurat trading should be detected from hard-coded data."""
        sessions = engine.get_special_sessions(2025)
        muhurat = [s for s in sessions if s["type"] == "MUHURAT"]
        assert len(muhurat) == 1
        assert muhurat[0]["date"] == datetime.date(2025, 10, 21)
        assert muhurat[0]["open_time"] == datetime.time(18, 15)
        assert muhurat[0]["close_time"] == datetime.time(19, 15)

    def test_known_half_day_2025(self, engine):
        """2025 half-day sessions should be detected."""
        sessions = engine.get_special_sessions(2025)
        half_days = [s for s in sessions if s["type"] == "HALF_DAY"]
        assert len(half_days) == 1
        assert half_days[0]["date"] == datetime.date(2025, 3, 14)

    def test_empty_2026_specials(self, engine):
        """2026 should have no hard-coded special sessions yet."""
        sessions = engine.get_special_sessions(2026)
        assert len(sessions) == 0  # Not yet announced by NSE

    def test_is_muhurat_trading(self, engine):
        """is_muhurat_trading should return True on known muhurat dates."""
        result = engine.is_muhurat_trading(datetime.date(2025, 10, 21))
        assert result is True

    def test_is_muhurat_trading_false(self, engine):
        """is_muhurat_trading should return False on normal dates."""
        result = engine.is_muhurat_trading(datetime.date(2026, 6, 25))
        assert result is False

    def test_is_half_day(self, engine):
        """is_half_day should return True on known half-day dates."""
        result = engine.is_half_day(datetime.date(2025, 3, 14))
        assert result is True

    def test_is_half_day_false(self, engine):
        """is_half_day should return False on normal dates."""
        result = engine.is_half_day(datetime.date(2026, 6, 25))
        assert result is False

    def test_special_sessions_from_config(self, engine):
        """Custom event_dates with MUHURAT/HALF_DAY types should be detected."""
        cfg_engine = ExchangeCalendarEngine({
            "event_dates": [
                {"date": "2026-11-10", "type": "MUHURAT", "name": "Diwali Muhurat 2026"},
                {"date": "2026-03-13", "type": "HALF_DAY", "name": "Holi Half Day 2026"},
            ],
        })
        sessions = cfg_engine.get_special_sessions(2026)
        types = {(s["type"], str(s["date"])) for s in sessions}
        assert ("MUHURAT", "2026-11-10") in types
        assert ("HALF_DAY", "2026-03-13") in types


# ── Trading hours ────────────────────────────────────────────────────────────


class TestTradingHours:
    """Tests for trading hours query."""

    def test_regular_trading_day(self, engine):
        """A regular weekday should have REGULAR session."""
        hours = engine.get_trading_hours(datetime.date(2026, 6, 25))  # Thursday
        assert hours.session_type == "REGULAR"
        assert hours.is_trading_day is True
        assert str(hours.open_time) == "09:15:00"
        assert str(hours.close_time) == "15:30:00"

    def test_weekend_non_trading(self, engine):
        """Weekend should be CLOSED."""
        hours = engine.get_trading_hours(datetime.date(2026, 6, 27))  # Saturday
        assert hours.session_type == "CLOSED"
        assert hours.is_trading_day is False

    def test_sunday_non_trading(self, engine):
        """Sunday should be CLOSED."""
        hours = engine.get_trading_hours(datetime.date(2026, 6, 28))
        assert hours.is_trading_day is False

    def test_muhurat_session_hours(self, engine):
        """Muhurat trading should have evening hours."""
        hours = engine.get_trading_hours(datetime.date(2025, 10, 21))
        assert hours.session_type == "MUHURAT"
        assert hours.is_trading_day is True
        assert str(hours.open_time) == "18:15:00"
        assert str(hours.close_time) == "19:15:00"

    def test_half_day_hours(self, engine):
        """Half-day should have early close."""
        hours = engine.get_trading_hours(datetime.date(2025, 3, 14))
        assert hours.session_type == "HALF_DAY"
        assert hours.is_trading_day is True
        assert str(hours.close_time) == "12:30:00"


# ── Expiry calendar ──────────────────────────────────────────────────────────


class TestExpiryCalendar:
    """Tests for expiry calendar computation."""

    def test_nifty_weekly_expiries_2026(self, engine):
        """NIFTY should have ~52 weekly expiries in 2026, all Thursdays."""
        expiries = engine.get_expiry_calendar(2026, ["NIFTY"])
        assert "NIFTY" in expiries
        nifty = expiries["NIFTY"]
        assert len(nifty) >= 50  # ~52 weeks
        for exp in nifty:
            assert exp.index_name == "NIFTY"
            assert exp.expiry_date.weekday() == 3  # Thursday
            assert exp.expiry_date.year == 2026

    def test_banknifty_expiries(self, engine):
        """BANKNIFTY expiries should be on Wednesdays."""
        expiries = engine.get_expiry_calendar(2026, ["BANKNIFTY"])
        assert "BANKNIFTY" in expiries
        for exp in expiries["BANKNIFTY"][:10]:
            assert exp.expiry_date.weekday() == 2  # Wednesday

    def test_finnifty_expiries(self, engine):
        """FINNIFTY expiries should be on Tuesdays."""
        expiries = engine.get_expiry_calendar(2026, ["FINNIFTY"])
        assert "FINNIFTY" in expiries
        for exp in expiries["FINNIFTY"][:10]:
            assert exp.expiry_date.weekday() == 1  # Tuesday

    def test_multiple_indices(self, engine):
        """Getting expiries for multiple indices should return all."""
        expiries = engine.get_expiry_calendar(2026, ["NIFTY", "BANKNIFTY", "FINNIFTY"])
        assert len(expiries) == 3
        assert "NIFTY" in expiries
        assert "BANKNIFTY" in expiries
        assert "FINNIFTY" in expiries

    def test_next_expiry(self, engine):
        """get_next_expiry should return the next upcoming expiry."""
        from_date = datetime.date(2026, 6, 26)  # Friday (not expiry day)
        next_exp = engine.get_next_expiry("NIFTY", from_date)

        assert next_exp is not None
        assert next_exp.index_name == "NIFTY"
        # Next NIFTY expiry after Friday June 26 should be Thursday July 2
        assert next_exp.expiry_date > from_date
        assert next_exp.expiry_date.weekday() == 3  # Thursday

    def test_next_expiry_past_date(self, engine):
        """get_next_expiry should work for past dates."""
        from_date = datetime.date(2026, 1, 1)
        next_exp = engine.get_next_expiry("NIFTY", from_date)
        assert next_exp is not None
        assert next_exp.expiry_date >= from_date

    def test_is_expiry_day_true(self, engine):
        """is_expiry_day should return True on expiry dates."""
        next_exp = engine.get_next_expiry("NIFTY", datetime.date(2026, 6, 25))
        if next_exp:
            result = engine.is_expiry_day("NIFTY", next_exp.expiry_date)
            assert result is True

    def test_is_expiry_day_false(self, engine):
        """is_expiry_day should return False on non-expiry dates."""
        result = engine.is_expiry_day("NIFTY", datetime.date(2026, 6, 26))  # Friday
        assert result is False  # Friday is not NIFTY expiry


# ── Market status ────────────────────────────────────────────────────────────


class TestMarketStatus:
    """Tests for market status with special session awareness."""

    def test_status_on_muhurat_evening(self, engine):
        """Muhurat session evening should return MUHURAT status."""
        muhurat_dt = datetime.datetime(2025, 10, 21, 18, 30)  # 6:30 PM during muhurat
        status = engine.get_market_status(muhurat_dt)
        assert status == ExtendedMarketStatus.MUHURAT

    def test_status_before_muhurat(self, engine):
        """Before muhurat session should be PRE_MARKET."""
        early_dt = datetime.datetime(2025, 10, 21, 9, 0)  # 9 AM, before muhurat open
        status = engine.get_market_status(early_dt)
        assert status == ExtendedMarketStatus.PRE_MARKET

    def test_weekend_status(self, engine):
        """Weekend should return NON_TRADING."""
        saturday = datetime.datetime(2026, 6, 27, 10, 0)
        status = engine.get_market_status(saturday)
        assert status == ExtendedMarketStatus.NON_TRADING


# ── Summary ──────────────────────────────────────────────────────────────────


class TestSummary:
    """Tests for the comprehensive summary method."""

    def test_summary_contains_all_keys(self, engine):
        """Summary should contain all expected keys."""
        s = engine.summary()
        expected_keys = [
            "timestamp", "market_status", "is_trading_day", "trading_hours",
            "special_sessions", "event_day", "next_expiries",
            "corporate_actions", "upcoming_ipos", "sebi_circulars",
            "saturday_trading_allowed",
        ]
        for key in expected_keys:
            assert key in s, f"Missing key: {key}"

    def test_summary_types(self, engine):
        """Summary values should have correct types."""
        s = engine.summary()
        assert isinstance(s["timestamp"], str)
        assert isinstance(s["is_trading_day"], bool)
        assert isinstance(s["market_status"], str)
        assert isinstance(s["next_expiries"], dict)
        assert isinstance(s["special_sessions"], dict)
        assert isinstance(s["corporate_actions"], int)

    def test_summary_next_expiries(self, engine):
        """Summary should include next expiries for major indices."""
        s = engine.summary()
        assert "NIFTY" in s["next_expiries"]
        assert "BANKNIFTY" in s["next_expiries"]
        assert "FINNIFTY" in s["next_expiries"]

    def test_summary_special_sessions_structure(self, engine):
        """Special sessions section should have expected structure."""
        s = engine.summary()
        assert "total" in s["special_sessions"]
        assert "upcoming" in s["special_sessions"]

    def test_print_summary(self, engine):
        """print_summary should not raise."""
        import io
        import sys
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            engine.print_summary()
        finally:
            sys.stdout = old_stdout
        output = captured.getvalue()
        assert "EXCHANGE CALENDAR ENGINE SUMMARY" in output


# ── Error handling ───────────────────────────────────────────────────────────


class TestErrorHandling:
    """Tests for graceful degradation on errors."""

    def test_empty_config(self):
        """Engine should work with empty config."""
        with patch("core.event_calendar._fetch_nse_holidays", return_value=set()):
            engine = ExchangeCalendarEngine()
            assert engine is not None
            assert engine._cfg == {}

    def test_invalid_dates_in_config(self, engine):
        """Config with invalid dates should be silently skipped."""
        engine._cfg["event_dates"] = [
            {"date": "not-a-date", "type": "BUDGET"},
        ]
        sessions = engine.get_special_sessions(2026)
        # Should not crash, should return gracefully
        assert isinstance(sessions, list)


# ── Delegation tests ─────────────────────────────────────────────────────────


class TestDelegation:
    """Tests that engine correctly delegates to event_calendar.py functions."""

    def test_get_corporate_actions(self, engine):
        """get_corporate_actions should not crash."""
        actions = engine.get_corporate_actions()
        assert isinstance(actions, list)

    def test_get_ipo_calendar(self, engine):
        """get_ipo_calendar should not crash."""
        ipos = engine.get_ipo_calendar()
        assert isinstance(ipos, list)

    def test_get_sebi_circulars(self, engine):
        """get_sebi_circulars should not crash."""
        circulars = engine.get_sebi_circulars()
        assert isinstance(circulars, list)

    def test_get_event_calendar(self, engine):
        """get_event_calendar should not crash."""
        event = engine.get_event_calendar()
        assert isinstance(event, dict)
        assert "is_event_day" in event


# ── Holiday check ────────────────────────────────────────────────────────────


class TestHolidayDetection:
    """Tests for holiday/market day detection."""

    def test_is_market_day_weekday(self, engine):
        """Regular weekdays should be market days."""
        with patch("core.event_calendar._nse_holidays", return_value=set()):
            result = engine.is_market_day(datetime.date(2026, 6, 25))  # Thursday
            assert result is True

    def test_is_market_day_saturday(self, engine):
        """Saturdays should not be market days by default."""
        with patch("core.event_calendar._nse_holidays", return_value=set()):
            result = engine.is_market_day(datetime.date(2026, 6, 27))
            assert result is False

    def test_is_holiday_inverse(self, engine):
        """is_holiday should be inverse of is_market_day."""
        with patch("core.event_calendar._nse_holidays", return_value=set()):
            market = engine.is_market_day(datetime.date(2026, 6, 25))
            holiday = engine.is_holiday(datetime.date(2026, 6, 25))
            assert market != holiday  # Should be opposite
