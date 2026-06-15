"""Tests for ProductionMandateEnforcer — trade mandate checks (deprecated but tested)."""

from __future__ import annotations

from unittest.mock import patch
from datetime import datetime

from core.mandate_enforcer import (
    ProductionMandateEnforcer,
    MandateState,
    get_mandate_enforcer,
    reset_mandate_enforcer,
)


class TestMandateState:
    """MandateState defaults."""

    def test_defaults(self):
        s = MandateState()
        assert s.capital == 5000.0
        assert s.equity_peak == 5000.0
        assert s.daily_pnl == 0.0
        assert s.trades_today == 0
        assert s.is_hard_halted is False
        assert s.vix == 20.0


class TestProductionMandateEnforcer:
    """ProductionMandateEnforcer — trade gates and position sizing."""

    def setup_method(self):
        self.enforcer = ProductionMandateEnforcer({"BASE_CAPITAL": 5000})

    def test_initial_state(self):
        assert self.enforcer._state.capital == 5000
        assert self.enforcer._state.equity_peak == 5000

    def test_update_market(self):
        self.enforcer.update_market(vix=25.0, data_age_seconds=10)
        assert self.enforcer._state.vix == 25.0
        assert self.enforcer._state.data_stale_seconds == 10

    def test_update_capital(self):
        self.enforcer.update_capital(5500, 500, 300)
        assert self.enforcer._state.capital == 5500
        assert self.enforcer._state.daily_pnl == 500
        assert self.enforcer._state.weekly_pnl == 300

    def test_update_capital_peak(self):
        self.enforcer.update_capital(6000, 1000, 500)
        assert self.enforcer._state.equity_peak == 6000

    def test_reset_daily(self):
        self.enforcer._state.trades_today = 5
        self.enforcer.reset_daily()
        assert self.enforcer._state.trades_today == 0

    def test_can_trade_normal(self):
        allowed, msg = self.enforcer.can_trade()
        assert allowed
        assert "MANDATE_CHECK_PASSED" in msg

    def test_can_trade_halted(self):
        self.enforcer._state.is_hard_halted = True
        allowed, msg = self.enforcer.can_trade()
        assert not allowed
        assert "HARD_HALT" in msg

    def test_can_trade_vix_block(self):
        self.enforcer.update_market(vix=30.0, data_age_seconds=0)
        allowed, msg = self.enforcer.can_trade()
        assert not allowed
        assert "VIX" in msg

    def test_can_trade_data_stale(self):
        self.enforcer.update_market(vix=20.0, data_age_seconds=30)
        allowed, msg = self.enforcer.can_trade()
        assert not allowed
        assert "DATA_STALE" in msg

    def test_can_trade_daily_loss_stop(self):
        self.enforcer.update_capital(5000, -150, -100)
        allowed, msg = self.enforcer.can_trade()
        assert not allowed
        assert "DAILY_STOP" in msg

    def test_get_position_size_basic(self):
        size = self.enforcer.get_position_size(entry_price=100, regime="TRENDING", sl_pct=0.12)
        assert size >= 1
        assert size <= 25

    def test_get_position_size_capital_zero(self):
        self.enforcer._state.capital = 0
        size = self.enforcer.get_position_size(entry_price=100, regime="TRENDING", sl_pct=0.12)
        assert size == 0

    def test_get_max_daily_loss(self):
        loss = self.enforcer.get_max_daily_loss()
        assert loss < 0
        assert loss == -125.0  # 5000 * 0.025

    def test_get_max_trades_today_high_vix(self):
        self.enforcer.update_market(vix=29.0, data_age_seconds=0)
        assert self.enforcer.get_max_trades_today() == 1

    def test_get_max_trades_today_normal(self):
        assert self.enforcer.get_max_trades_today() == 4

    def test_should_skip_first_20_min_true_morning(self):
        with patch("core.mandate_enforcer.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 11, 9, 30)
            assert self.enforcer.should_skip_first_20_min() is True

    def test_should_skip_first_20_min_false_later(self):
        with patch("core.mandate_enforcer.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 11, 10, 0)
            assert self.enforcer.should_skip_first_20_min() is False

    def test_should_skip_last_45_min_true(self):
        with patch("core.mandate_enforcer.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 11, 15, 0)
            assert self.enforcer.should_skip_last_45_min() is True

    def test_is_in_trading_window_mid_market(self):
        with patch("core.mandate_enforcer.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 11, 10, 30)
            assert self.enforcer.is_in_trading_window() is True

    def test_is_in_trading_window_afternoon(self):
        with patch("core.mandate_enforcer.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 11, 13, 30)
            assert self.enforcer.is_in_trading_window() is True

    def test_is_in_trading_window_closed(self):
        with patch("core.mandate_enforcer.now_ist") as mock_now:
            mock_now.return_value = datetime(2026, 6, 11, 16, 0)
            assert self.enforcer.is_in_trading_window() is False

    def test_get_min_score_trending(self):
        assert self.enforcer.get_min_score("TRENDING") == 68

    def test_get_min_score_sideways(self):
        assert self.enforcer.get_min_score("SIDEWAYS") == 73

    def test_get_min_score_choppy(self):
        assert self.enforcer.get_min_score("CHOPPY") == 78

    def test_should_block_false_signal(self):
        assert self.enforcer.should_block_false_signal(75, 27) is True
        assert self.enforcer.should_block_false_signal(70, 27) is False
        assert self.enforcer.should_block_false_signal(75, 20) is False

    def test_get_status_structure(self):
        status = self.enforcer.get_status()
        assert "capital" in status
        assert "drawdown_pct" in status
        assert "vix" in status
        assert "hard_halted" in status
        assert status["capital"] == 5000

    def test_get_mandate_enforcer_singleton(self):
        reset_mandate_enforcer()
        e1 = get_mandate_enforcer({"BASE_CAPITAL": 10000})
        e2 = get_mandate_enforcer()
        assert e1 is e2
        reset_mandate_enforcer()
