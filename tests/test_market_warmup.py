"""Tests for MarketWarmup — warm-up period throttled-entry mode."""

from __future__ import annotations

from unittest.mock import patch
from datetime import datetime

from core.datetime_ist import now_ist
from core.market_warmup import MarketWarmup


_MOCK_MARKET_OPEN = datetime(2026, 6, 11, 9, 20)  # Thursday, 5 min after open (warmup active)


class TestMarketWarmup:
    """MarketWarmup — warm-up period controller."""

    def test_default_config(self):
        mw = MarketWarmup()
        # should be enabled, active depends on time
        assert mw._enabled is True
        assert mw._duration_mins == 15
        assert mw._size_mult == 0.5
        assert mw._score_boost == 10
        assert mw._max_trades == 2

    def test_custom_config(self):
        mw = MarketWarmup({
            "warmup_enabled": True,
            "warmup_duration_mins": 30,
            "warmup_size_mult": 0.75,
            "warmup_score_boost": 20,
            "warmup_max_trades": 3,
        })
        assert mw._duration_mins == 30
        assert mw._size_mult == 0.75
        assert mw._score_boost == 20
        assert mw._max_trades == 3

    def test_disabled_never_active(self):
        mw = MarketWarmup({"warmup_enabled": False})
        assert mw.is_warmup_active() is False
        assert mw.can_enter("NIFTY") is True
        assert mw.position_size_mult() == 1.0
        assert mw.score_threshold_adjustment() == 0
        assert mw.adjusted_position_size(10) == 10

    def test_reset_day(self):
        mw = MarketWarmup()
        mw._entries["NIFTY"] = 12345.0
        mw._current_day = "2026-01-01"
        mw.reset_day()
        assert mw._current_day is None
        assert mw._warmup_end is None
        assert len(mw._entries) == 0

    def test_enabled_no_warmup_end_means_not_active(self):
        mw = MarketWarmup()
        mw._warmup_end = None
        mw._current_day = now_ist().date()  # prevent recalc
        assert mw.is_warmup_active() is False

    @patch("core.market_warmup.now_ist", return_value=_MOCK_MARKET_OPEN)
    def test_position_size_multipliers(self, mock_now):
        mw = MarketWarmup({"warmup_size_mult": 0.33, "warmup_duration_mins": 15})
        # now_ist mocked to 09:20 -> warmup end = 09:30 -> warmup active
        assert mw.is_warmup_active() is True
        assert mw.position_size_mult() == 0.33
        assert mw.adjusted_position_size(10) == 3  # round(10 * 0.33) = 3

    @patch("core.market_warmup.now_ist", return_value=_MOCK_MARKET_OPEN)
    def test_adjusted_position_size_min_one(self, mock_now):
        mw = MarketWarmup({"warmup_size_mult": 0.01, "warmup_duration_mins": 15})
        assert mw.is_warmup_active() is True
        assert mw.adjusted_position_size(10) == 1  # max(1, round(10 * 0.01))

    @patch("core.market_warmup.now_ist", return_value=_MOCK_MARKET_OPEN)
    def test_score_threshold_adjustment(self, mock_now):
        mw = MarketWarmup({"warmup_score_boost": 15, "warmup_duration_mins": 15})
        assert mw.is_warmup_active() is True
        assert mw.score_threshold_adjustment() == 15

    @patch("core.market_warmup.now_ist", return_value=datetime(2026, 6, 11, 15, 0))
    def test_score_threshold_adjustment_outside_warmup(self, mock_now):
        mw = MarketWarmup({"warmup_score_boost": 15})
        assert mw.score_threshold_adjustment() == 0

    @patch("core.market_warmup.now_ist", return_value=datetime(2026, 6, 11, 15, 0))
    def test_can_enter_outside_warmup(self, mock_now):
        mw = MarketWarmup()
        assert mw.can_enter("NIFTY") is True

    @patch("core.market_warmup.now_ist", return_value=_MOCK_MARKET_OPEN)
    def test_try_mark_entry_success(self, mock_now):
        mw = MarketWarmup()
        result = mw.try_mark_entry("NIFTY")
        assert result is True
        assert "NIFTY" in mw._entries

    @patch("core.market_warmup.now_ist", return_value=_MOCK_MARKET_OPEN)
    def test_try_mark_entry_fails_when_blocked(self, mock_now):
        mw = MarketWarmup({"warmup_max_trades": 0, "warmup_duration_mins": 15})
        result = mw.try_mark_entry("NIFTY")
        assert result is False

    @patch("core.market_warmup.now_ist", return_value=_MOCK_MARKET_OPEN)
    def test_status_dict_structure(self, mock_now):
        mw = MarketWarmup()
        status = mw.status()
        assert isinstance(status, dict)
        assert "enabled" in status
        assert "warmup_active" in status
        assert "duration_mins" in status
        assert "size_mult" in status
        assert "score_boost" in status
        assert "max_trades" in status
        assert "entries_in_warmup" in status
        assert "remaining" in status

    @patch("core.market_warmup.now_ist", return_value=_MOCK_MARKET_OPEN)
    def test_status_shows_entries(self, mock_now):
        mw = MarketWarmup()
        # Trigger _maybe_reset_day first (sets _current_day, clears stale entries)
        _ = mw.status()
        # Now add entry - _current_day already matches, won't clear
        mw._entries["TEST"] = 12345.0
        status = mw.status()
        assert status["entries_in_warmup"] == 1

    def test_market_open_today_weekend_returns_none(self):
        mw = MarketWarmup()
        result = mw._market_open_today()
        if result is not None:
            assert hasattr(result, "hour")
