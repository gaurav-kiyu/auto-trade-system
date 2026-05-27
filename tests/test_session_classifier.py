"""
Tests for Phase 3 — Time-of-Day Intelligence Layer (session_classifier.py).

Covers:
  - classify_session: correct SessionType at each boundary
  - classify_session: PRE_MARKET / CLOSED outside cash hours
  - classify_session: config-driven boundary overrides
  - get_session_score_adj: default adjustments per session
  - get_session_score_adj: config override per session
  - session_entry_allowed: defaults (all True except PRE_MARKET/CLOSED)
  - session_entry_allowed: config-driven hard-block
  - session_summary: returns expected keys
  - adaptive_signal: session_adj written into score_components
"""
from __future__ import annotations

import datetime

from unittest.mock import patch as _patch

from core.session_classifier import (
    SessionType,
    ExpirySessionName,
    classify_session,
    get_session_score_adj,
    session_entry_allowed,
    session_summary,
    is_expiry_day,
    get_expiry_session,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _t(h: int, m: int, s: int = 0) -> datetime.time:
    return datetime.time(h, m, s)


_EMPTY_CFG: dict = {}


# ── Class 1: classify_session — boundary correctness ─────────────────────────


class TestClassifySessionBoundaries:
    def test_before_open_is_pre_market(self):
        assert classify_session(_t(9, 0)) == SessionType.PRE_MARKET

    def test_at_open_is_opening(self):
        assert classify_session(_t(9, 15)) == SessionType.OPENING

    def test_mid_opening_is_opening(self):
        assert classify_session(_t(9, 45)) == SessionType.OPENING

    def test_just_before_early_end_is_opening(self):
        assert classify_session(_t(10, 14)) == SessionType.OPENING

    def test_at_early_end_is_trending(self):
        # Default early_end = 10:15 (from nse_early_session_end_time)
        assert classify_session(_t(10, 15)) == SessionType.TRENDING

    def test_mid_trending_is_trending(self):
        assert classify_session(_t(11, 0)) == SessionType.TRENDING

    def test_just_before_choppy_is_trending(self):
        assert classify_session(_t(11, 29)) == SessionType.TRENDING

    def test_at_choppy_start_is_choppy(self):
        assert classify_session(_t(11, 30)) == SessionType.CHOPPY

    def test_mid_choppy_is_choppy(self):
        assert classify_session(_t(12, 30)) == SessionType.CHOPPY

    def test_just_before_recovery_is_choppy(self):
        assert classify_session(_t(13, 29)) == SessionType.CHOPPY

    def test_at_recovery_start_is_recovery(self):
        assert classify_session(_t(13, 30)) == SessionType.RECOVERY

    def test_mid_recovery_is_recovery(self):
        assert classify_session(_t(13, 50)) == SessionType.RECOVERY

    def test_at_pre_close_start_is_pre_close(self):
        assert classify_session(_t(14, 15)) == SessionType.PRE_CLOSE

    def test_mid_pre_close_is_pre_close(self):
        assert classify_session(_t(14, 45)) == SessionType.PRE_CLOSE

    def test_at_block_from_is_closed(self):
        # Default block_from = 15:00
        assert classify_session(_t(15, 0)) == SessionType.CLOSED

    def test_after_close_is_closed(self):
        assert classify_session(_t(16, 0)) == SessionType.CLOSED


class TestClassifySessionConfigOverride:
    def test_custom_choppy_start(self):
        cfg = {"session_choppy_start_hour": 12, "session_choppy_start_minute": 0}
        # 11:30 should still be TRENDING under this config
        assert classify_session(_t(11, 30), cfg) == SessionType.TRENDING
        # 12:00 should be CHOPPY
        assert classify_session(_t(12, 0), cfg) == SessionType.CHOPPY

    def test_custom_recovery_start(self):
        cfg = {"session_recovery_start_hour": 14, "session_recovery_start_minute": 0}
        assert classify_session(_t(13, 45), cfg) == SessionType.CHOPPY
        assert classify_session(_t(14, 0), cfg) == SessionType.RECOVERY

    def test_custom_pre_close_start(self):
        cfg = {"session_pre_close_start_hour": 14, "session_pre_close_start_minute": 30}
        assert classify_session(_t(14, 20), cfg) == SessionType.RECOVERY
        assert classify_session(_t(14, 30), cfg) == SessionType.PRE_CLOSE


# ── Class 2: get_session_score_adj — defaults ─────────────────────────────────


class TestGetSessionScoreAdj:
    def test_opening_default_is_minus_10(self):
        assert get_session_score_adj(SessionType.OPENING) == -10

    def test_trending_default_is_plus_5(self):
        assert get_session_score_adj(SessionType.TRENDING) == 5

    def test_choppy_default_is_minus_15(self):
        assert get_session_score_adj(SessionType.CHOPPY) == -15

    def test_recovery_default_is_0(self):
        assert get_session_score_adj(SessionType.RECOVERY) == 0

    def test_pre_close_default_is_minus_5(self):
        assert get_session_score_adj(SessionType.PRE_CLOSE) == -5

    def test_pre_market_is_0(self):
        assert get_session_score_adj(SessionType.PRE_MARKET) == 0

    def test_closed_is_0(self):
        assert get_session_score_adj(SessionType.CLOSED) == 0

    def test_config_override_choppy(self):
        cfg = {"session_choppy_score_adj": -20}
        assert get_session_score_adj(SessionType.CHOPPY, cfg) == -20

    def test_config_override_trending(self):
        cfg = {"session_trending_score_adj": 10}
        assert get_session_score_adj(SessionType.TRENDING, cfg) == 10

    def test_config_override_opening(self):
        cfg = {"session_opening_score_adj": 0}
        assert get_session_score_adj(SessionType.OPENING, cfg) == 0


# ── Class 3: session_entry_allowed ───────────────────────────────────────────


class TestSessionEntryAllowed:
    def test_pre_market_always_blocked(self):
        assert session_entry_allowed(SessionType.PRE_MARKET) is False

    def test_closed_always_blocked(self):
        assert session_entry_allowed(SessionType.CLOSED) is False

    def test_opening_allowed_by_default(self):
        assert session_entry_allowed(SessionType.OPENING) is True

    def test_trending_always_allowed(self):
        assert session_entry_allowed(SessionType.TRENDING) is True

    def test_choppy_allowed_by_default(self):
        assert session_entry_allowed(SessionType.CHOPPY) is True

    def test_recovery_always_allowed(self):
        assert session_entry_allowed(SessionType.RECOVERY) is True

    def test_pre_close_always_allowed(self):
        assert session_entry_allowed(SessionType.PRE_CLOSE) is True

    def test_config_blocks_opening(self):
        cfg = {"session_opening_allowed": False}
        assert session_entry_allowed(SessionType.OPENING, cfg) is False

    def test_config_blocks_choppy(self):
        cfg = {"session_choppy_allowed": False}
        assert session_entry_allowed(SessionType.CHOPPY, cfg) is False

    def test_config_cannot_unblock_pre_market(self):
        cfg = {"session_opening_allowed": True}  # doesn't affect PRE_MARKET
        assert session_entry_allowed(SessionType.PRE_MARKET, cfg) is False


# ── Class 4: session_summary ─────────────────────────────────────────────────


class TestSessionSummary:
    def test_summary_has_required_keys(self):
        summary = session_summary(now=_t(10, 30))
        assert "session" in summary
        assert "score_adj" in summary
        assert "entry_allowed" in summary
        assert "boundaries" in summary

    def test_summary_session_value_is_string(self):
        summary = session_summary(now=_t(10, 30))
        assert isinstance(summary["session"], str)

    def test_summary_trending_at_1030(self):
        summary = session_summary(now=_t(10, 30))
        assert summary["session"] == "TRENDING"
        assert summary["score_adj"] == 5
        assert summary["entry_allowed"] is True

    def test_summary_choppy_at_1200(self):
        summary = session_summary(now=_t(12, 0))
        assert summary["session"] == "CHOPPY"
        assert summary["score_adj"] == -15

    def test_summary_boundaries_has_all_keys(self):
        summary = session_summary(now=_t(10, 0))
        bounds = summary["boundaries"]
        for key in ("nse_open", "trending", "choppy", "recovery", "pre_close", "block_from"):
            assert key in bounds, f"Missing boundary key: {key}"


# ── Class 5: adaptive_signal integration ─────────────────────────────────────


class TestAdaptiveSignalSessionWiring:
    """Verify session_adj is written into score_components when signal is evaluated."""

    def test_session_adj_in_score_components(self):
        """Smoke test: evaluate_adaptive_signal emits session_adj in score_components."""
        import numpy as np
        import pandas as pd
        from core.adaptive_signal import evaluate_adaptive_signal
        from core.pure_index_signal import PureIndexSignalParams

        n = 60
        idx = pd.date_range("2026-01-15 09:15", periods=n, freq="1min")
        df1 = pd.DataFrame({
            "Open":   np.full(n, 22500.0),
            "High":   np.full(n, 22600.0),
            "Low":    np.full(n, 22400.0),
            "Close":  np.linspace(22400, 22600, n),
            "Volume": np.full(n, 10000.0),
        }, index=idx)
        df5 = df1.resample("5min").agg({
            "Open": "first", "High": "max",
            "Low": "min", "Close": "last", "Volume": "sum",
        }).dropna()
        df15 = df1.resample("15min").agg({
            "Open": "first", "High": "max",
            "Low": "min", "Close": "last", "Volume": "sum",
        }).dropna()

        params = PureIndexSignalParams(
            name="NIFTY",
            iv_spike_threshold=60.0,
            signal_cfg={"session_classifier_enabled": True},
            regime="BULL",
            vol_ratio_min=0.5,
            is_early_session=False,
        )
        sig, reason = evaluate_adaptive_signal(
            params=params,
            df1=df1, df5=df5, df15=df15,
            vix=15.0, iv=15.0,
            oi_sup=22000.0, oi_res=23000.0,
            pcr=1.0, smart="BULLISH",
        )
        # If signal was generated, check session_adj is present
        if sig is not None:
            assert "session_adj" in sig.score_components

    def test_session_classifier_disabled_no_session_adj(self):
        """When session_classifier_enabled=False, session_adj should not appear."""
        import numpy as np
        import pandas as pd
        from core.adaptive_signal import evaluate_adaptive_signal
        from core.pure_index_signal import PureIndexSignalParams

        n = 60
        idx = pd.date_range("2026-01-15 09:15", periods=n, freq="1min")
        df1 = pd.DataFrame({
            "Open": np.full(n, 22500.0), "High": np.full(n, 22600.0),
            "Low": np.full(n, 22400.0), "Close": np.linspace(22400, 22600, n),
            "Volume": np.full(n, 10000.0),
        }, index=idx)
        df5 = df1.resample("5min").agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum",
        }).dropna()
        df15 = df1.resample("15min").agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum",
        }).dropna()

        params = PureIndexSignalParams(
            name="NIFTY",
            iv_spike_threshold=60.0,
            signal_cfg={"session_classifier_enabled": False},
            regime="BULL",
            vol_ratio_min=0.5,
            is_early_session=False,
        )
        sig, reason = evaluate_adaptive_signal(
            params=params,
            df1=df1, df5=df5, df15=df15,
            vix=15.0, iv=15.0,
            oi_sup=22000.0, oi_res=23000.0,
            pcr=1.0, smart="BULLISH",
        )
        if sig is not None:
            assert sig.score_components.get("session_adj", 0) == 0


# ── Class 6: classify_session with datetime input (line 150) ─────────────


class TestClassifySessionDatetimeInput:
    """Covers line 150: classify_session with datetime.datetime input."""

    def test_datetime_input_classified_correctly(self):
        dt = datetime.datetime(2026, 5, 28, 10, 30)
        assert classify_session(dt) == SessionType.TRENDING


# ── Class 7: fallback boundary functions (lines 93-94, 107-108, 121-122) ──


class TestFallbackBoundaryFunctions:
    """Covers the except Exception blocks in _nse_open_time, _nse_early_end_time,
    _nse_block_time — lines 93-94, 107-108, 121-122."""

    @_patch("core.datetime_ist.nse_cash_open_time", side_effect=RuntimeError("mock"))
    def test_nse_open_time_fallback(self, _):
        assert classify_session(_t(9, 15)) == SessionType.OPENING

    @_patch("core.datetime_ist.nse_early_session_end_time", side_effect=RuntimeError("mock"))
    def test_nse_early_end_time_fallback(self, _):
        assert classify_session(_t(10, 15)) == SessionType.TRENDING

    @_patch("core.datetime_ist.nse_block_new_entries_from_time", side_effect=RuntimeError("mock"))
    def test_nse_block_time_fallback(self, _):
        assert classify_session(_t(15, 0)) == SessionType.CLOSED


# ── Class 8: is_expiry_day (lines 297-320, including 301-302, 315-318) ────


class TestIsExpiryDay:
    """Covers the is_expiry_day function — lines 297-320."""

    def test_nifty_not_expiry_day(self):
        assert is_expiry_day("NIFTY", check_date=datetime.date(2026, 5, 27)) is False

    @_patch("core.event_calendar._nse_holidays", return_value=set())
    def test_nifty_expiry_day(self, _):
        assert is_expiry_day("NIFTY", check_date=datetime.date(2026, 5, 28)) is True

    def test_finnifty_not_expiry_day(self):
        assert is_expiry_day("FINNIFTY", check_date=datetime.date(2026, 5, 27)) is False

    @_patch("core.event_calendar._nse_holidays", return_value=set())
    def test_finnifty_expiry_day(self, _):
        assert is_expiry_day("FINNIFTY", check_date=datetime.date(2026, 5, 26)) is True

    @_patch("core.event_calendar._nse_holidays", return_value=set())
    def test_unknown_index_defaults_to_thursday(self, _):
        assert is_expiry_day("FOO", check_date=datetime.date(2026, 5, 28)) is True
        assert is_expiry_day("FOO", check_date=datetime.date(2026, 5, 27)) is False

    @_patch("core.datetime_ist.now_ist", side_effect=RuntimeError("mock"))
    def test_now_ist_fallback_to_date_today(self, _):
        """Covers lines 301-302: now_ist() raises, falls back to date.today()."""
        assert is_expiry_day("NIFTY") is False

    @_patch("core.event_calendar._nse_holidays")
    def test_holiday_returns_false(self, mock_h):
        """Covers line 315: today in holidays → return False."""
        mock_h.return_value = {datetime.date(2026, 5, 28)}
        assert is_expiry_day("NIFTY", check_date=datetime.date(2026, 5, 28)) is False

    @_patch("core.event_calendar._nse_holidays", side_effect=RuntimeError("mock"))
    def test_holiday_exception_passes(self, _):
        """Covers lines 317-318: exception in holiday check is swallowed."""
        assert is_expiry_day("NIFTY", check_date=datetime.date(2026, 5, 28)) is True


# ── Class 9: get_expiry_session (lines 333-383, including 343-344, 352-354, 383) ─


class TestGetExpirySession:
    """Covers the get_expiry_session function — lines 333-383."""

    def test_not_expiry_day_returns_none(self):
        """May 27 is Wednesday, not NIFTY expiry day → None."""
        result = get_expiry_session(
            "NIFTY", _t(10, 0), check_date=datetime.date(2026, 5, 27),
        )
        assert result is None

    @_patch("core.event_calendar._nse_holidays", return_value=set())
    def test_block_all_mode(self, _):
        """Covers lines 343-344: expiry_day_mode=BLOCK_ALL."""
        result = get_expiry_session(
            "NIFTY", _t(10, 0),
            {"expiry_day_mode": "BLOCK_ALL"},
            check_date=datetime.date(2026, 5, 28),
        )
        assert result is not None
        assert result.name == ExpirySessionName.EXPIRY_BLOCKED

    @_patch("core.event_calendar._nse_holidays", return_value=set())
    def test_morning_session(self, _):
        """9:15-11:00 → EXPIRY_MORNING (default expiry_morning_end=11:00)."""
        result = get_expiry_session(
            "NIFTY", _t(9, 30), check_date=datetime.date(2026, 5, 28),
        )
        assert result is not None
        assert result.name == ExpirySessionName.EXPIRY_MORNING
        assert result.lot_multiplier == 0.6

    @_patch("core.event_calendar._nse_holidays", return_value=set())
    def test_midday_session(self, _):
        """11:00-12:30 → EXPIRY_MIDDAY."""
        result = get_expiry_session(
            "NIFTY", _t(11, 30), check_date=datetime.date(2026, 5, 28),
        )
        assert result is not None
        assert result.name == ExpirySessionName.EXPIRY_MIDDAY
        assert result.lot_multiplier == 0.5

    @_patch("core.event_calendar._nse_holidays", return_value=set())
    def test_caution_session(self, _):
        """12:30-13:30 → EXPIRY_CAUTION."""
        result = get_expiry_session(
            "NIFTY", _t(12, 45), check_date=datetime.date(2026, 5, 28),
        )
        assert result is not None
        assert result.name == ExpirySessionName.EXPIRY_CAUTION
        assert result.auto_execute_allowed is False

    @_patch("core.event_calendar._nse_holidays", return_value=set())
    def test_blocked_session(self, _):
        """After 13:30 → EXPIRY_BLOCKED."""
        result = get_expiry_session(
            "NIFTY", _t(14, 0), check_date=datetime.date(2026, 5, 28),
        )
        assert result is not None
        assert result.name == ExpirySessionName.EXPIRY_BLOCKED

    @_patch("core.event_calendar._nse_holidays", return_value=set())
    def test_invalid_time_config_fallback(self, _):
        """Covers lines 352-354: _t() except block with unparseable config."""
        result = get_expiry_session(
            "NIFTY", _t(9, 30),
            {"expiry_morning_end": "not-a-time"},
            check_date=datetime.date(2026, 5, 28),
        )
        assert result is not None
        assert result.name == ExpirySessionName.EXPIRY_MORNING

    @_patch("core.event_calendar._nse_holidays", return_value=set())
    def test_before_open_returns_none(self, _):
        """Covers line 383: before market open (9:00) → None."""
        result = get_expiry_session(
            "NIFTY", _t(9, 0), check_date=datetime.date(2026, 5, 28),
        )
        assert result is None

    @_patch("core.event_calendar._nse_holidays", return_value=set())
    def test_datetime_input(self, _):
        """Covers lines 338-339: hasattr(current_time, 'time') branch."""
        dt = datetime.datetime(2026, 5, 28, 9, 30)
        result = get_expiry_session(
            "NIFTY", dt, check_date=datetime.date(2026, 5, 28),
        )
        assert result is not None
        assert result.name == ExpirySessionName.EXPIRY_MORNING
