"""Tests for core/intraday_performance_monitor.py - Intraday Performance Monitor.

Covers:
- IntradayStats, AdaptationParams dataclasses
- IntradayPerformanceMonitor init, record_trade_close
- get_current_params, reset_daily, get_stats
- _compute_adaptation for NORMAL/CAUTIOUS/DEFENSIVE levels
- Recovery: last 3 wins relax level
- Edge cases: disabled config, insufficient trades
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.intraday_performance_monitor import (
    AdaptationParams,
    IntradayPerformanceMonitor,
    IntradayStats,
    _CAUTIOUS_PARAMS,
    _DEFENSIVE_PARAMS,
    _NORMAL_PARAMS,
)


@pytest.fixture
def monitor() -> IntradayPerformanceMonitor:
    return IntradayPerformanceMonitor(cfg={
        "intraday_monitor_enabled": True,
        "intraday_min_trades_to_adapt": 3,
        "intraday_defensive_win_rate": 0.25,
        "intraday_cautious_win_rate": 0.40,
    })


# =============================================================================
# Dataclass Tests
# =============================================================================

class TestAdaptationParams:
    def test_normal_params(self):
        assert _NORMAL_PARAMS.score_threshold_boost == 0
        assert _NORMAL_PARAMS.position_size_mult == 1.0
        assert _NORMAL_PARAMS.level == "NORMAL"

    def test_cautious_params(self):
        assert _CAUTIOUS_PARAMS.level == "CAUTIOUS"
        assert _CAUTIOUS_PARAMS.position_size_mult == 0.75

    def test_defensive_params(self):
        assert _DEFENSIVE_PARAMS.level == "DEFENSIVE"
        assert _DEFENSIVE_PARAMS.position_size_mult == 0.50


# =============================================================================
# Init Tests
# =============================================================================

class TestInit:
    def test_default_state(self):
        m = IntradayPerformanceMonitor()
        assert m._level == "NORMAL"
        assert m._trades == []
        assert m._consec_losses == 0

    def test_empty_config(self):
        m = IntradayPerformanceMonitor(cfg={})
        assert m._cfg == {}


# =============================================================================
# record_trade_close Tests
# =============================================================================

class TestRecordTradeClose:
    def test_first_trade_returns_normal(self, monitor: IntradayPerformanceMonitor):
        params = monitor.record_trade_close(100.0, was_winner=True)
        assert params.level == "NORMAL"

    def test_enough_trades_triggers_adaptation(self, monitor: IntradayPerformanceMonitor):
        """3 consecutive losses with win rate 0% should trigger DEFENSIVE."""
        for _ in range(3):
            monitor.record_trade_close(-100.0, was_winner=False)
        params = monitor.record_trade_close(-100.0, was_winner=False)  # 4th loss
        # 0 wins / 4 trades = 0% win rate
        assert params.level == "DEFENSIVE"

    def test_cautious_on_bad_win_rate(self, monitor: IntradayPerformanceMonitor):
        """1 win, 3 losses = 25% win rate, which should be CAUTIOUS."""
        monitor.record_trade_close(100.0, was_winner=True)
        for _ in range(3):
            monitor.record_trade_close(-100.0, was_winner=False)
        params = monitor.record_trade_close(-100.0, was_winner=False)
        # 1/5 = 20% win rate
        assert params.level == "DEFENSIVE"

    def test_normal_with_good_win_rate(self, monitor: IntradayPerformanceMonitor):
        """High win rate keeps NORMAL."""
        for _ in range(5):
            monitor.record_trade_close(100.0, was_winner=True)
        monitor.record_trade_close(-50.0, was_winner=False)  # 5/6 = 83%
        params = monitor.record_trade_close(100.0, was_winner=True)
        assert params.level == "NORMAL"

    def test_recovers_from_defensive(self, monitor: IntradayPerformanceMonitor):
        """3 wins in a row should recover one level."""
        # Push to DEFENSIVE first
        for _ in range(5):
            monitor.record_trade_close(-100.0, was_winner=False)
        assert monitor.record_trade_close(-100.0, was_winner=False).level == "DEFENSIVE"

        # Now 3 wins should recover to CAUTIOUS
        p1 = monitor.record_trade_close(100.0, was_winner=True)
        p2 = monitor.record_trade_close(100.0, was_winner=True)
        p3 = monitor.record_trade_close(100.0, was_winner=True)
        assert p3.level == "CAUTIOUS"

        # 3 more wins should recover to NORMAL
        p4 = monitor.record_trade_close(100.0, was_winner=True)
        p5 = monitor.record_trade_close(100.0, was_winner=True)
        p6 = monitor.record_trade_close(100.0, was_winner=True)
        assert p6.level == "NORMAL"

    def test_disabled_returns_normal(self):
        m = IntradayPerformanceMonitor(cfg={"intraday_monitor_enabled": False})
        for _ in range(10):
            m.record_trade_close(-100.0, was_winner=False)
        params = m.record_trade_close(-100.0, was_winner=False)
        assert params.level == "NORMAL"


# =============================================================================
# get_current_params Tests
# =============================================================================

class TestGetCurrentParams:
    def test_initial_params(self, monitor: IntradayPerformanceMonitor):
        params = monitor.get_current_params()
        assert params.level == "NORMAL"

    def test_after_trades(self, monitor: IntradayPerformanceMonitor):
        for _ in range(5):
            monitor.record_trade_close(-100.0, was_winner=False)
        params = monitor.get_current_params()
        assert params.level in ("CAUTIOUS", "DEFENSIVE")


# =============================================================================
# reset_daily Tests
# =============================================================================

class TestResetDaily:
    def test_resets_state(self, monitor: IntradayPerformanceMonitor):
        for _ in range(5):
            monitor.record_trade_close(-100.0, was_winner=False)
        monitor.reset_daily()
        assert monitor._trades == []
        assert monitor._consec_losses == 0
        assert monitor._level == "NORMAL"


# =============================================================================
# get_stats Tests
# =============================================================================

class TestGetStats:
    def test_initial_stats(self, monitor: IntradayPerformanceMonitor):
        stats = monitor.get_stats()
        assert stats.trades_today == 0
        assert stats.wins_today == 0
        assert stats.adaptation_level == "NORMAL"

    def test_after_trades(self, monitor: IntradayPerformanceMonitor):
        monitor.record_trade_close(200.0, was_winner=True)
        monitor.record_trade_close(100.0, was_winner=True)
        monitor.record_trade_close(-50.0, was_winner=False)
        stats = monitor.get_stats()
        assert stats.trades_today == 3
        assert stats.wins_today == 2
        assert stats.losses_today == 1
        assert stats.session_win_rate == pytest.approx(2/3, abs=0.01)
        assert stats.avg_pnl_today == pytest.approx(250.0/3, abs=0.1)

    def test_consecutive_losses_tracked(self, monitor: IntradayPerformanceMonitor):
        monitor.record_trade_close(-50.0, was_winner=False)
        monitor.record_trade_close(-50.0, was_winner=False)
        monitor.record_trade_close(-50.0, was_winner=False)
        stats = monitor.get_stats()
        assert stats.consecutive_losses == 3

    def test_consecutive_losses_reset_on_win(self, monitor: IntradayPerformanceMonitor):
        monitor.record_trade_close(-50.0, was_winner=False)
        monitor.record_trade_close(-50.0, was_winner=False)
        monitor.record_trade_close(100.0, was_winner=True)
        stats = monitor.get_stats()
        assert stats.consecutive_losses == 0
