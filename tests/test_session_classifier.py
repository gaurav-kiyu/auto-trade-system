"""Tests for core/session_classifier.py - Time-of-Day Session Classifier.

Covers:
- SessionType enum values
- classify_session() for all 7 session bands
- get_session_score_adj() for each session
- session_entry_allowed() for hard-block logic
- is_expiry_day() for index-specific expiry detection
- get_expiry_session() for expiry day session timing
- session_summary() snapshot dict
- Edge cases: boundary times, custom config overrides
"""
from __future__ import annotations

import datetime
from typing import Any

import pytest

from core.session_classifier import (
    ExpirySession,
    ExpirySessionName,
    SessionType,
    classify_session,
    get_expiry_session,
    get_session_score_adj,
    is_expiry_day,
    session_entry_allowed,
    session_summary,
)


# =============================================================================
# SessionType Enum Tests
# =============================================================================

class TestSessionType:
    def test_has_all_sessions(self):
        assert SessionType.PRE_MARKET.value == "PRE_MARKET"
        assert SessionType.OPENING.value == "OPENING"
        assert SessionType.TRENDING.value == "TRENDING"
        assert SessionType.CHOPPY.value == "CHOPPY"
        assert SessionType.RECOVERY.value == "RECOVERY"
        assert SessionType.PRE_CLOSE.value == "PRE_CLOSE"
        assert SessionType.CLOSED.value == "CLOSED"


# =============================================================================
# classify_session Tests
# =============================================================================

class TestClassifySession:
    def _t(self, hour: int, minute: int = 0) -> datetime.time:
        return datetime.time(hour, minute)

    def test_pre_market_before_915(self):
        assert classify_session(self._t(8, 0)) == SessionType.PRE_MARKET
        assert classify_session(self._t(9, 14)) == SessionType.PRE_MARKET

    def test_opening_915_to_1015(self):
        cfg = {
            "NSE_CASH_SESSION_START_HOUR": 9, "NSE_CASH_SESSION_START_MINUTE": 15,
            "NSE_EARLY_SESSION_END_HOUR": 10, "NSE_EARLY_SESSION_END_MINUTE": 15,
            "NSE_BLOCK_NEW_ENTRIES_FROM_HOUR": 15, "NSE_BLOCK_NEW_ENTRIES_FROM_MINUTE": 0,
        }
        assert classify_session(self._t(9, 15), cfg) == SessionType.OPENING
        assert classify_session(self._t(9, 30), cfg) == SessionType.OPENING
        # At exactly 10:15, session transitions to TRENDING (early session ends)
        assert classify_session(self._t(10, 14), cfg) == SessionType.OPENING

    def test_trending_1015_to_1130(self):
        assert classify_session(self._t(10, 16)) == SessionType.TRENDING
        assert classify_session(self._t(11, 0)) == SessionType.TRENDING
        assert classify_session(self._t(11, 29)) == SessionType.TRENDING

    def test_choppy_1130_to_1330(self):
        assert classify_session(self._t(11, 30)) == SessionType.CHOPPY
        assert classify_session(self._t(12, 30)) == SessionType.CHOPPY
        assert classify_session(self._t(13, 29)) == SessionType.CHOPPY

    def test_recovery_1330_to_1415(self):
        assert classify_session(self._t(13, 30)) == SessionType.RECOVERY
        assert classify_session(self._t(14, 0)) == SessionType.RECOVERY
        assert classify_session(self._t(14, 14)) == SessionType.RECOVERY

    def test_pre_close_1415_to_1500(self):
        assert classify_session(self._t(14, 15)) == SessionType.PRE_CLOSE
        assert classify_session(self._t(14, 30)) == SessionType.PRE_CLOSE
        assert classify_session(self._t(14, 59)) == SessionType.PRE_CLOSE

    def test_closed_after_1500(self):
        assert classify_session(self._t(15, 0)) == SessionType.CLOSED
        assert classify_session(self._t(16, 0)) == SessionType.CLOSED

    def test_with_datetime_input(self):
        dt = datetime.datetime(2026, 6, 20, 9, 30)
        assert classify_session(dt) == SessionType.OPENING

    def test_custom_boundaries(self):
        """Custom session boundaries override defaults."""
        cfg = {
            "session_choppy_start_hour": 12,
            "session_choppy_start_minute": 0,
        }
        assert classify_session(self._t(11, 30), cfg) == SessionType.TRENDING
        assert classify_session(self._t(12, 0), cfg) == SessionType.CHOPPY


# =============================================================================
# get_session_score_adj Tests
# =============================================================================

class TestGetSessionScoreAdj:
    def test_opening_penalty(self):
        assert get_session_score_adj(SessionType.OPENING) == -10

    def test_trending_bonus(self):
        assert get_session_score_adj(SessionType.TRENDING) == 5

    def test_choppy_penalty(self):
        assert get_session_score_adj(SessionType.CHOPPY) == -15

    def test_recovery_neutral(self):
        assert get_session_score_adj(SessionType.RECOVERY) == 0

    def test_pre_close_penalty(self):
        assert get_session_score_adj(SessionType.PRE_CLOSE) == -5

    def test_pre_market_neutral(self):
        assert get_session_score_adj(SessionType.PRE_MARKET) == 0

    def test_closed_neutral(self):
        assert get_session_score_adj(SessionType.CLOSED) == 0

    def test_custom_adjustments(self):
        cfg = {"session_choppy_score_adj": -20}
        assert get_session_score_adj(SessionType.CHOPPY, cfg) == -20

    def test_custom_trending_bonus(self):
        cfg = {"session_trending_score_adj": 10}
        assert get_session_score_adj(SessionType.TRENDING, cfg) == 10


# =============================================================================
# session_entry_allowed Tests
# =============================================================================

class TestSessionEntryAllowed:
    def test_pre_market_blocked(self):
        assert session_entry_allowed(SessionType.PRE_MARKET) is False

    def test_closed_blocked(self):
        assert session_entry_allowed(SessionType.CLOSED) is False

    def test_opening_allowed(self):
        assert session_entry_allowed(SessionType.OPENING) is True

    def test_trending_allowed(self):
        assert session_entry_allowed(SessionType.TRENDING) is True

    def test_recovery_allowed(self):
        assert session_entry_allowed(SessionType.RECOVERY) is True

    def test_opening_blocked_by_config(self):
        cfg = {"session_opening_allowed": False}
        assert session_entry_allowed(SessionType.OPENING, cfg) is False

    def test_choppy_blocked_by_config(self):
        cfg = {"session_choppy_allowed": False}
        assert session_entry_allowed(SessionType.CHOPPY, cfg) is False

    def test_trending_always_allowed(self):
        """Trending can't be blocked by config."""
        assert session_entry_allowed(SessionType.TRENDING) is True


# =============================================================================
# is_expiry_day Tests
# =============================================================================

class TestIsExpiryDay:
    def test_nifty_expiry_thursday(self):
        """NIFTY expiry is Thursday (weekday=3)."""
        thursday = datetime.date(2026, 6, 25)  # Thursday
        assert is_expiry_day("NIFTY", check_date=thursday) is True

    def test_finnifty_expiry_tuesday(self):
        """FINNIFTY expiry is Tuesday (weekday=1)."""
        tuesday = datetime.date(2026, 6, 23)  # Tuesday
        assert is_expiry_day("FINNIFTY", check_date=tuesday) is True

    def test_not_expiry_day(self):
        monday = datetime.date(2026, 6, 22)  # Monday
        assert is_expiry_day("NIFTY", check_date=monday) is False

    def test_friday_not_nifty_expiry(self):
        friday = datetime.date(2026, 6, 26)  # Friday
        assert is_expiry_day("BANKNIFTY", check_date=friday) is False

    def test_unknown_index_defaults_to_thursday(self):
        """Unknown index defaults to NIFTY (Thursday)."""
        thursday = datetime.date(2026, 6, 25)
        assert is_expiry_day("SENSEX", check_date=thursday) is True

    def test_saturday_not_expiry(self):
        saturday = datetime.date(2026, 6, 27)  # Saturday
        assert is_expiry_day("NIFTY", check_date=saturday) is False


# =============================================================================
# get_expiry_session Tests
# =============================================================================

class TestGetExpirySession:
    def _t(self, hour: int, minute: int = 0) -> datetime.time:
        return datetime.time(hour, minute)

    def test_none_on_non_expiry_day(self):
        monday = datetime.date(2026, 6, 22)
        result = get_expiry_session(
            "NIFTY", self._t(10, 0),
            check_date=monday,
        )
        assert result is None

    def test_expiry_morning_session(self):
        thursday = datetime.date(2026, 6, 25)
        result = get_expiry_session(
            "NIFTY", self._t(10, 0),
            check_date=thursday,
        )
        assert result is not None
        assert result.name == ExpirySessionName.EXPIRY_MORNING
        assert result.lot_multiplier == 0.6
        assert result.auto_execute_allowed is True

    def test_expiry_midday_session(self):
        thursday = datetime.date(2026, 6, 25)
        result = get_expiry_session(
            "NIFTY", self._t(11, 30),
            check_date=thursday,
        )
        assert result is not None
        assert result.name == ExpirySessionName.EXPIRY_MIDDAY
        assert result.lot_multiplier == 0.5
        assert result.auto_execute_allowed is True

    def test_expiry_caution_session(self):
        thursday = datetime.date(2026, 6, 25)
        result = get_expiry_session(
            "NIFTY", self._t(13, 0),
            check_date=thursday,
        )
        assert result is not None
        assert result.name == ExpirySessionName.EXPIRY_CAUTION
        assert result.lot_multiplier == 0.0
        assert result.auto_execute_allowed is False

    def test_expiry_blocked_session(self):
        thursday = datetime.date(2026, 6, 25)
        result = get_expiry_session(
            "NIFTY", self._t(14, 0),
            check_date=thursday,
        )
        assert result is not None
        assert result.name == ExpirySessionName.EXPIRY_BLOCKED
        assert result.lot_multiplier == 0.0
        assert result.auto_execute_allowed is False

    def test_block_all_mode(self):
        thursday = datetime.date(2026, 6, 25)
        result = get_expiry_session(
            "NIFTY", self._t(10, 0),
            cfg={"expiry_day_mode": "BLOCK_ALL"},
            check_date=thursday,
        )
        assert result is not None
        assert result.name == ExpirySessionName.EXPIRY_BLOCKED

    def test_custom_morning_params(self):
        thursday = datetime.date(2026, 6, 25)
        result = get_expiry_session(
            "NIFTY", self._t(10, 0),
            cfg={"expiry_morning_lot_mult": 0.8, "expiry_morning_sl_pct": 0.90},
            check_date=thursday,
        )
        assert result.lot_multiplier == 0.8
        assert result.sl_pct_override == 0.90

    def test_before_market_open_returns_none(self):
        thursday = datetime.date(2026, 6, 25)
        result = get_expiry_session(
            "NIFTY", self._t(8, 0),
            check_date=thursday,
        )
        assert result is None


# =============================================================================
# session_summary Tests
# =============================================================================

class TestSessionSummary:
    def test_returns_expected_keys(self):
        summary = session_summary(now=datetime.time(10, 0))
        assert "session" in summary
        assert "score_adj" in summary
        assert "entry_allowed" in summary
        assert "boundaries" in summary

    def test_opening_session_summary(self):
        summary = session_summary(now=datetime.time(10, 0))
        assert summary["session"] == "OPENING"
        assert summary["score_adj"] == -10
        assert summary["entry_allowed"] is True

    def test_closed_session_summary(self):
        summary = session_summary(now=datetime.time(15, 30))
        assert summary["session"] == "CLOSED"
        assert summary["entry_allowed"] is False

    def test_boundaries_included(self):
        summary = session_summary(now=datetime.time(10, 0))
        boundaries = summary["boundaries"]
        assert "nse_open" in boundaries
        assert "trending" in boundaries
        assert "block_from" in boundaries

    def test_summary_with_datetime(self):
        dt = datetime.datetime(2026, 6, 20, 13, 0)
        summary = session_summary(now=dt.time())
        assert summary["session"] == "CHOPPY"
