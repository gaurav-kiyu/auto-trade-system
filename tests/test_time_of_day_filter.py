"""Tests for core/time_of_day_filter.py — time-of-day trading restrictions."""

from __future__ import annotations

from unittest import mock

import pytest

from core.time_of_day_filter import (
    TimeOfDayConfig,
    TimeOfDayFilter,
    create_time_of_day_filter,
)


# ── TimeOfDayConfig ───────────────────────────────────────────────────────────

class TestTimeOfDayConfig:
    def test_defaults(self) -> None:
        c = TimeOfDayConfig()
        assert c.enabled is True
        assert c.block_start_hour == 14
        assert c.block_end_hour == 15
        assert c.allow_trending_only is True

    def test_custom(self) -> None:
        c = TimeOfDayConfig(enabled=False, block_start_hour=9, block_end_hour=10, allow_trending_only=False)
        assert c.enabled is False
        assert c.block_start_hour == 9
        assert c.block_end_hour == 10


# ── should_allow_entry ────────────────────────────────────────────────────────

class TestShouldAllowEntry:
    def test_disabled_always_allows(self) -> None:
        f = TimeOfDayFilter(TimeOfDayConfig(enabled=False))
        ok, reason = f.should_allow_entry("TRENDING")
        assert ok is True
        assert reason == ""

    def test_outside_blocked_hours_allows(self) -> None:
        f = TimeOfDayFilter(TimeOfDayConfig(block_start_hour=14, block_end_hour=15))
        with mock.patch("core.time_of_day_filter.now_ist") as mock_now:
            mock_now.return_value.hour = 11  # 11 AM, outside block
            ok, _ = f.should_allow_entry("TRENDING")
            assert ok is True

    def test_inside_blocked_hour_blocks(self) -> None:
        f = TimeOfDayFilter(TimeOfDayConfig(block_start_hour=14, block_end_hour=15))
        with mock.patch("core.time_of_day_filter.now_ist") as mock_now:
            mock_now.return_value.hour = 14  # 2 PM, inside block
            ok, reason = f.should_allow_entry("RANGE")
            assert ok is False
            assert "Blocked" in reason

    def test_blocked_hour_but_trending_allowed(self) -> None:
        f = TimeOfDayFilter(TimeOfDayConfig(
            block_start_hour=14, block_end_hour=15, allow_trending_only=True,
        ))
        with mock.patch("core.time_of_day_filter.now_ist") as mock_now:
            mock_now.return_value.hour = 14
            ok, reason = f.should_allow_entry("TRENDING")
            assert ok is True
            assert "TRENDING" in reason

    def test_blocked_hour_bullish_allowed(self) -> None:
        f = TimeOfDayFilter(TimeOfDayConfig(
            block_start_hour=14, block_end_hour=15, allow_trending_only=True,
        ))
        with mock.patch("core.time_of_day_filter.now_ist") as mock_now:
            mock_now.return_value.hour = 14
            ok, _ = f.should_allow_entry("BULLISH")
            assert ok is True

    def test_blocked_hour_no_regime_fallback(self) -> None:
        f = TimeOfDayFilter(TimeOfDayConfig(
            block_start_hour=14, block_end_hour=15, allow_trending_only=True,
        ))
        with mock.patch("core.time_of_day_filter.now_ist") as mock_now:
            mock_now.return_value.hour = 14
            ok, reason = f.should_allow_entry("CHOPPY")
            assert ok is False
            assert "non-TRENDING" in reason

    def test_blocked_hour_allow_trending_false_blocks_all(self) -> None:
        f = TimeOfDayFilter(TimeOfDayConfig(
            block_start_hour=14, block_end_hour=15, allow_trending_only=False,
        ))
        with mock.patch("core.time_of_day_filter.now_ist") as mock_now:
            mock_now.return_value.hour = 14
            ok, reason = f.should_allow_entry("TRENDING")
            assert ok is False
            assert "Blocked trading hours" in reason

    def test_no_regime_in_blocked_hour_blocks(self) -> None:
        f = TimeOfDayFilter(TimeOfDayConfig(block_start_hour=14, block_end_hour=15))
        with mock.patch("core.time_of_day_filter.now_ist") as mock_now:
            mock_now.return_value.hour = 14
            ok, _ = f.should_allow_entry(None)
            assert ok is False


# ── get_restriction_level ─────────────────────────────────────────────────────

class TestGetRestrictionLevel:
    def test_disabled_returns_none(self) -> None:
        f = TimeOfDayFilter(TimeOfDayConfig(enabled=False))
        assert f.get_restriction_level() == "NONE"

    def test_blocked_hour(self) -> None:
        f = TimeOfDayFilter(TimeOfDayConfig(block_start_hour=14, block_end_hour=15))
        with mock.patch("core.time_of_day_filter.now_ist") as mock_now:
            mock_now.return_value.hour = 14
            assert f.get_restriction_level() == "BLOCKED"

    def test_allowed_hour(self) -> None:
        f = TimeOfDayFilter(TimeOfDayConfig(block_start_hour=14, block_end_hour=15))
        with mock.patch("core.time_of_day_filter.now_ist") as mock_now:
            mock_now.return_value.hour = 11
            assert f.get_restriction_level() == "ALLOWED"


# ── create_time_of_day_filter ─────────────────────────────────────────────────

class TestCreateFactory:
    def test_creates_from_config(self) -> None:
        f = create_time_of_day_filter({
            "TIME_OF_DAY_FILTER_ENABLED": False,
            "TIME_OF_DAY_BLOCK_START_HOUR": 9,
        })
        assert isinstance(f, TimeOfDayFilter)
        assert f.config.enabled is False
        assert f.config.block_start_hour == 9

    def test_uses_defaults(self) -> None:
        f = create_time_of_day_filter({})
        assert f.config.enabled is True
        assert f.config.block_start_hour == 14
        assert f.config.allow_trending_only is True
