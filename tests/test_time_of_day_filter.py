"""Tests for TimeOfDayFilter — blocks or restricts trading during low liquidity periods."""

from __future__ import annotations

from unittest.mock import patch
from datetime import datetime

from core.time_of_day_filter import (
    TimeOfDayFilter,
    TimeOfDayConfig,
    create_time_of_day_filter,
)


class TestTimeOfDayFilter:
    """TimeOfDayFilter — should_allow_entry and get_restriction_level."""

    def test_default_config(self):
        cfg = TimeOfDayConfig()
        assert cfg.enabled is True
        assert cfg.block_start_hour == 14
        assert cfg.block_end_hour == 15
        assert cfg.allow_trending_only is True

    def test_disabled_allows_all(self):
        filter_ = TimeOfDayFilter(TimeOfDayConfig(enabled=False))
        allowed, reason = filter_.should_allow_entry("ANY")
        assert allowed
        assert reason == ""

    def test_disabled_restriction_level_none(self):
        filter_ = TimeOfDayFilter(TimeOfDayConfig(enabled=False))
        assert filter_.get_restriction_level() == "NONE"

    @patch("core.time_of_day_filter.now_ist")
    def test_blocked_hour_non_trending(self, mock_now):
        mock_now.return_value = datetime(2026, 6, 11, 14, 30)
        filter_ = TimeOfDayFilter(TimeOfDayConfig(
            block_start_hour=14, block_end_hour=15, allow_trending_only=True
        ))
        allowed, reason = filter_.should_allow_entry("SIDEWAYS")
        assert not allowed
        assert "non-TRENDING" in reason

    @patch("core.time_of_day_filter.now_ist")
    def test_blocked_hour_trending_allowed(self, mock_now):
        mock_now.return_value = datetime(2026, 6, 11, 14, 30)
        filter_ = TimeOfDayFilter(TimeOfDayConfig(
            block_start_hour=14, block_end_hour=15, allow_trending_only=True
        ))
        allowed, reason = filter_.should_allow_entry("TRENDING")
        assert allowed
        assert "Blocked hour but allowing TRENDING" in reason

    @patch("core.time_of_day_filter.now_ist")
    def test_blocked_hour_bullish_allowed(self, mock_now):
        mock_now.return_value = datetime(2026, 6, 11, 14, 30)
        filter_ = TimeOfDayFilter(TimeOfDayConfig(
            block_start_hour=14, block_end_hour=15, allow_trending_only=True
        ))
        allowed, _ = filter_.should_allow_entry("BULLISH")
        assert allowed

    @patch("core.time_of_day_filter.now_ist")
    def test_blocked_hour_no_regime_blocks(self, mock_now):
        mock_now.return_value = datetime(2026, 6, 11, 14, 30)
        filter_ = TimeOfDayFilter(TimeOfDayConfig(
            block_start_hour=14, block_end_hour=15, allow_trending_only=True
        ))
        allowed, reason = filter_.should_allow_entry()  # no regime
        assert not allowed
        assert "Blocked" in reason

    @patch("core.time_of_day_filter.now_ist")
    def test_blocked_hour_trending_disabled(self, mock_now):
        mock_now.return_value = datetime(2026, 6, 11, 14, 30)
        filter_ = TimeOfDayFilter(TimeOfDayConfig(
            block_start_hour=14, block_end_hour=15, allow_trending_only=False
        ))
        allowed, reason = filter_.should_allow_entry("TRENDING")
        assert not allowed
        assert "Blocked trading hours" in reason

    @patch("core.time_of_day_filter.now_ist")
    def test_normal_hour_allows(self, mock_now):
        mock_now.return_value = datetime(2026, 6, 11, 10, 30)
        filter_ = TimeOfDayFilter(TimeOfDayConfig(
            block_start_hour=14, block_end_hour=15
        ))
        allowed, reason = filter_.should_allow_entry("SIDEWAYS")
        assert allowed
        assert reason == ""

    @patch("core.time_of_day_filter.now_ist")
    def test_restriction_level_blocked(self, mock_now):
        mock_now.return_value = datetime(2026, 6, 11, 14, 30)
        filter_ = TimeOfDayFilter(TimeOfDayConfig(
            block_start_hour=14, block_end_hour=15
        ))
        assert filter_.get_restriction_level() == "BLOCKED"

    @patch("core.time_of_day_filter.now_ist")
    def test_restriction_level_allowed(self, mock_now):
        mock_now.return_value = datetime(2026, 6, 11, 10, 30)
        filter_ = TimeOfDayFilter(TimeOfDayConfig(
            block_start_hour=14, block_end_hour=15
        ))
        assert filter_.get_restriction_level() == "ALLOWED"

    @patch("core.time_of_day_filter.now_ist")
    def test_edge_of_blocked_window_start(self, mock_now):
        mock_now.return_value = datetime(2026, 6, 11, 14, 0)
        filter_ = TimeOfDayFilter(TimeOfDayConfig(
            block_start_hour=14, block_end_hour=15, allow_trending_only=False
        ))
        allowed, _ = filter_.should_allow_entry("TRENDING")
        assert not allowed  # >= 14 is blocked

    @patch("core.time_of_day_filter.now_ist")
    def test_edge_of_blocked_window_end(self, mock_now):
        mock_now.return_value = datetime(2026, 6, 11, 14, 59)
        filter_ = TimeOfDayFilter(TimeOfDayConfig(
            block_start_hour=14, block_end_hour=15, allow_trending_only=False
        ))
        allowed, _ = filter_.should_allow_entry("TRENDING")
        assert not allowed  # < 15 is blocked

    @patch("core.time_of_day_filter.now_ist")
    def test_after_blocked_window(self, mock_now):
        mock_now.return_value = datetime(2026, 6, 11, 15, 0)
        filter_ = TimeOfDayFilter(TimeOfDayConfig(
            block_start_hour=14, block_end_hour=15
        ))
        allowed, _ = filter_.should_allow_entry("SIDEWAYS")
        assert allowed  # >= 15 is not blocked


class TestCreateTimeOfDayFilter:
    """Factory function create_time_of_day_filter."""

    def test_create_with_defaults(self):
        filter_ = create_time_of_day_filter({})
        assert isinstance(filter_, TimeOfDayFilter)
        assert filter_.config.enabled is True

    def test_create_with_custom_config(self):
        filter_ = create_time_of_day_filter({
            "TIME_OF_DAY_FILTER_ENABLED": False,
            "TIME_OF_DAY_BLOCK_START_HOUR": 13,
            "TIME_OF_DAY_BLOCK_END_HOUR": 14,
            "TIME_OF_DAY_ALLOW_TRENDING_ONLY": False,
        })
        assert filter_.config.enabled is False
        assert filter_.config.block_start_hour == 13
        assert filter_.config.block_end_hour == 14
        assert filter_.config.allow_trending_only is False
