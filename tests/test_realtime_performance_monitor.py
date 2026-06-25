"""Tests for core.realtime_performance_monitor - live performance tracking."""

from __future__ import annotations

from datetime import datetime

import pytest

from core.realtime_performance_monitor import (
    PerformanceConfig,
    PerformanceSnapshot,
    RealtimePerformanceMonitor,
    create_performance_monitor,
)


class TestPerformanceConfig:
    """Tests for PerformanceConfig dataclass."""

    def test_defaults(self) -> None:
        cfg = PerformanceConfig()
        assert cfg.enabled is False
        assert cfg.alert_webhook_url == ""
        assert cfg.alert_drawdown_pct == 0.05
        assert cfg.alert_loss_streak == 3


class TestPerformanceSnapshot:
    """Tests for PerformanceSnapshot dataclass."""

    def test_defaults(self) -> None:
        snap = PerformanceSnapshot(
            timestamp=datetime.now(), total_trades=0, win_rate=0.0,
            total_pnl=0.0, current_drawdown=0.0, win_streak=0, loss_streak=0,
        )
        assert snap.total_trades == 0
        assert snap.win_rate == 0.0


class TestRealtimePerformanceMonitor:
    """Tests for RealtimePerformanceMonitor - live trade tracking."""

    def setup_method(self) -> None:
        self.monitor = RealtimePerformanceMonitor(PerformanceConfig())

    def test_initial_snapshot_empty(self) -> None:
        snap = self.monitor.get_current_snapshot()
        assert snap.total_trades == 0
        assert snap.win_rate == 0.0
        assert snap.total_pnl == 0.0
        assert snap.current_drawdown == 0.0
        assert snap.win_streak == 0
        assert snap.loss_streak == 0

    def test_add_winning_trade(self) -> None:
        self.monitor.add_trade(100.0)
        snap = self.monitor.get_current_snapshot()
        assert snap.total_trades == 1
        assert snap.win_rate == 100.0
        assert snap.total_pnl == 100.0
        assert snap.win_streak == 1
        assert snap.loss_streak == 0

    def test_add_losing_trade(self) -> None:
        self.monitor.add_trade(-50.0)
        snap = self.monitor.get_current_snapshot()
        assert snap.total_trades == 1
        assert snap.win_rate == 0.0
        assert snap.total_pnl == -50.0
        assert snap.win_streak == 0
        assert snap.loss_streak == 1

    def test_mixed_trades(self) -> None:
        self.monitor.add_trade(100.0)
        self.monitor.add_trade(-50.0)
        self.monitor.add_trade(75.0)
        snap = self.monitor.get_current_snapshot()
        assert snap.total_trades == 3
        assert snap.win_rate == 66.66666666666666  # 2/3 wins
        assert snap.total_pnl == 125.0
        # win streak reset on loss: last trade is a win, but streak starts at 1
        assert snap.win_streak == 1

    def test_consecutive_wins(self) -> None:
        self.monitor.add_trade(50.0)
        self.monitor.add_trade(75.0)
        self.monitor.add_trade(100.0)
        snap = self.monitor.get_current_snapshot()
        assert snap.win_streak == 3
        assert snap.loss_streak == 0

    def test_consecutive_losses(self) -> None:
        self.monitor.add_trade(-50.0)
        self.monitor.add_trade(-75.0)
        self.monitor.add_trade(-100.0)
        snap = self.monitor.get_current_snapshot()
        assert snap.loss_streak == 3
        assert snap.win_streak == 0

    def test_drawdown_calculation(self) -> None:
        """Drawdown should track peak-to-trough decline."""
        self.monitor.add_trade(100.0)  # peak = 100
        self.monitor.add_trade(-80.0)  # trough from peak = -80 → drawdown = 80
        snap = self.monitor.get_current_snapshot()
        assert snap.current_drawdown == 80.0

    def test_no_alerts_when_disabled(self) -> None:
        """No alerts when config is disabled."""
        # Should not raise even with consecutive losses
        for _ in range(5):
            self.monitor.add_trade(-100.0)
        snap = self.monitor.get_current_snapshot()
        assert snap.loss_streak == 5


class TestCreatePerformanceMonitor:
    """Tests for create_performance_monitor factory."""

    def test_default_config(self) -> None:
        monitor = create_performance_monitor({})
        assert monitor.config.enabled is False

    def test_custom_config(self) -> None:
        monitor = create_performance_monitor({
            "REAL_TIME_DASHBOARD_ENABLED": True,
            "REAL_TIME_ALERT_WEBHOOK_URL": "https://hooks.example.com/alert",
            "REAL_TIME_ALERT_ON_DRAWDOWN_PCT": 0.10,
            "REAL_TIME_ALERT_ON_LOSS_STREAK": 5,
        })
        assert monitor.config.enabled is True
        assert monitor.config.alert_webhook_url == "https://hooks.example.com/alert"
        assert monitor.config.alert_drawdown_pct == 0.10
        assert monitor.config.alert_loss_streak == 5
