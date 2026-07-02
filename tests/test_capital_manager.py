"""Tests for core/capital_manager.py - equity-aware capital scaling engine.

Covers:
- CapitalState, ScaleResult dataclasses
- CapitalManager init with validation
- scale() with various factors (growth, drawdown, consecutive loss, daily loss)
- record_trade() for winners/losers
- reset_daily()
- lock_profits()
- decide_trade_allowed() - hard-stop checks
- get_state(), drawdown_pct, current_capital properties
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from core.services.risk_service import CapitalManager


_PATCH_TARGET = "core.services.risk_service.trip_hard_halt"


@pytest.fixture
def cm() -> CapitalManager:
    return CapitalManager(initial_capital=100000.0, max_daily_loss=-2000.0)


# =============================================================================
# Init Tests
# =============================================================================

class TestInit:
    def test_valid_params(self):
        cm = CapitalManager(initial_capital=100000.0, max_daily_loss=-2000.0)
        assert cm.current_capital == 100000.0
        assert cm._max_daily_loss == -2000.0

    def test_raises_on_positive_max_daily_loss(self):
        with pytest.raises(ValueError, match="negative"):
            CapitalManager(initial_capital=100000.0, max_daily_loss=2000.0)

    def test_raises_on_zero_max_daily_loss(self):
        with pytest.raises(ValueError, match="negative"):
            CapitalManager(initial_capital=100000.0, max_daily_loss=0.0)

    def test_custom_drawdown(self):
        cm = CapitalManager(initial_capital=100000.0, max_daily_loss=-2000.0, max_drawdown_pct=0.15)
        assert cm._max_dd == 0.15

    def test_default_state(self, cm: CapitalManager):
        st = cm._state
        assert st.initial_capital == 100000.0
        assert st.current_capital == 100000.0
        assert st.peak_capital == 100000.0
        assert st.locked_profit == 0.0
        assert st.daily_pnl == 0.0
        assert st.consecutive_losses == 0
        assert st.total_trades == 0


# =============================================================================
# Scale Tests
# =============================================================================

class TestScale:
    def test_full_size_when_no_drawdown(self, cm: CapitalManager):
        result = cm.scale(base_lots=2, max_lots=2)
        assert result.scale_factor == pytest.approx(1.0, abs=0.1)
        assert result.scaled_lots == 2

    def test_scales_down_with_consecutive_losses(self, cm: CapitalManager):
        cm.record_trade(-1000.0, is_winner=False)
        cm.record_trade(-500.0, is_winner=False)
        result = cm.scale(base_lots=2, max_lots=2)
        # After 2 consecutive losses, consec_factor = 0.75
        assert result.consec_loss_factor == 0.75
        # growth = 1.0 (no change), dd = 1.0 (no dd), consec = 0.75, daily = 1.0
        # scale_factor = 1.0 * 1.0 * 0.75 * 1.0 = 0.75
        # scaled_lots = int(2 * 0.75) = 1
        assert result.scaled_lots <= 1

    def test_scales_down_with_3_consecutive_losses(self, cm: CapitalManager):
        for _ in range(3):
            cm.record_trade(-500.0, is_winner=False)
        result = cm.scale(base_lots=2, max_lots=2)
        assert result.consec_loss_factor == 0.50

    def test_scales_down_with_4_consecutive_losses(self, cm: CapitalManager):
        for _ in range(4):
            cm.record_trade(-500.0, is_winner=False)
        result = cm.scale(base_lots=2, max_lots=2)
        assert result.consec_loss_factor == 0.25

    def test_daily_loss_reduces_size(self, cm: CapitalManager):
        cm.record_trade(-1200.0, is_winner=False)  # daily_pnl = -1200
        # daily_warn_level = -2000 * 0.6 = -1200
        # daily_pnl <= daily_warn_level -> factor applies
        result = cm.scale(base_lots=2, max_lots=2)
        assert result.daily_loss_factor < 1.0
        assert result.scaled_lots <= 2

    def test_drawdown_reduces_size(self):
        cm = CapitalManager(initial_capital=100000.0, max_daily_loss=-2000.0, max_drawdown_pct=0.20)
        cm.record_trade(-30000.0, is_winner=False)  # current = 70000, peak = 100000
        result = cm.scale(base_lots=2, max_lots=2)
        assert result.drawdown_factor < 1.0
        assert result.drawdown_pct > 0

    def test_hard_block_at_max_drawdown(self):
        cm = CapitalManager(initial_capital=100000.0, max_daily_loss=-2000.0, max_drawdown_pct=0.20)
        cm.record_trade(-25000.0, is_winner=False)  # current = 75000, dd = 25%
        result = cm.scale(base_lots=2, max_lots=2)
        assert result.drawdown_pct >= 0.20
        assert result.scaled_lots == 0

    def test_multiplicative_factors(self, cm: CapitalManager):
        cm.record_trade(-1500.0, is_winner=False)  # daily hit
        cm.record_trade(-500.0, is_winner=False)  # consec = 2 -> 0.75
        result = cm.scale(base_lots=4, max_lots=4)
        assert result.scale_factor < 1.0
        # Scale factor is rounded to 3 decimals while components may differ
        assert result.scale_factor == pytest.approx(result.capital_growth * result.drawdown_factor * result.consec_loss_factor * result.daily_loss_factor, abs=0.001)

    def test_reasoning_includes_parts(self, cm: CapitalManager):
        result = cm.scale(base_lots=1, max_lots=1)
        assert "lots" in result.reasoning
        assert "growth" in result.reasoning

    def test_clamps_to_max_lots(self, cm: CapitalManager):
        result = cm.scale(base_lots=10, max_lots=3)
        assert result.scaled_lots <= 3


# =============================================================================
# record_trade Tests
# =============================================================================

class TestRecordTrade:
    def test_winner_resets_consecutive_losses(self, cm: CapitalManager):
        cm.record_trade(-500.0, is_winner=False)
        cm.record_trade(-300.0, is_winner=False)
        cm.record_trade(1000.0, is_winner=True)
        assert cm._state.consecutive_losses == 0

    def test_loser_increments_consecutive(self, cm: CapitalManager):
        cm.record_trade(-500.0, is_winner=False)
        assert cm._state.consecutive_losses == 1
        cm.record_trade(-300.0, is_winner=False)
        assert cm._state.consecutive_losses == 2

    def test_updates_current_capital(self, cm: CapitalManager):
        cm.record_trade(5000.0, is_winner=True)
        assert cm.current_capital == 105000.0

    def test_updates_daily_pnl(self, cm: CapitalManager):
        cm.record_trade(1000.0, is_winner=True)
        assert cm._state.daily_pnl == 1000.0

    def test_updates_peak_capital(self, cm: CapitalManager):
        cm.record_trade(-5000.0, is_winner=False)  # capital = 95000
        assert cm._state.peak_capital == 100000.0  # peak unchanged
        cm.record_trade(10000.0, is_winner=True)  # capital = 105000
        assert cm._state.peak_capital == 105000.0

    def test_tracks_total_trades_and_wins(self, cm: CapitalManager):
        cm.record_trade(100.0, is_winner=True)
        cm.record_trade(-50.0, is_winner=False)
        cm.record_trade(200.0, is_winner=True)
        assert cm._state.total_trades == 3
        assert cm._state.total_wins == 2


# =============================================================================
# reset_daily Tests
# =============================================================================

class TestResetDaily:
    def test_resets_daily_pnl(self, cm: CapitalManager):
        cm.record_trade(5000.0, is_winner=True)
        cm.reset_daily()
        assert cm._state.daily_pnl == 0.0
        assert cm._state.daily_trade_count == 0


# =============================================================================
# lock_profits Tests
# =============================================================================

class TestLockProfits:
    def test_locks_part_of_profit(self, cm: CapitalManager):
        cm.record_trade(20000.0, is_winner=True)  # capital = 120000, profit = 20000
        locked = cm.lock_profits(lock_pct=0.50)
        assert locked == 10000.0
        assert cm._state.locked_profit == 10000.0
        assert cm.current_capital == 110000.0  # 120000 - 10000

    def test_no_profit_no_lock(self, cm: CapitalManager):
        locked = cm.lock_profits(lock_pct=0.50)
        assert locked == 0.0

    def test_does_not_reduce_peak_capital(self, cm: CapitalManager):
        cm.record_trade(20000.0, is_winner=True)  # peak = 120000
        cm.lock_profits(lock_pct=0.50)
        assert cm._state.peak_capital == 120000.0  # Peak preserved

    def test_loss_no_lock(self, cm: CapitalManager):
        cm.record_trade(-5000.0, is_winner=False)
        locked = cm.lock_profits(lock_pct=0.50)
        assert locked == 0.0


# =============================================================================
# decide_trade_allowed Tests
# =============================================================================

class TestDecideTradeAllowed:
    def test_allows_under_limits(self, cm: CapitalManager):
        allowed, reason = cm.decide_trade_allowed()
        assert allowed is True
        assert reason == "OK"

    def test_blocks_daily_loss(self, cm: CapitalManager):
        cm.record_trade(-2500.0, is_winner=False)  # Below -2000
        allowed, reason = cm.decide_trade_allowed()
        assert allowed is False
        assert "Daily loss" in reason

    def test_blocks_max_drawdown(self):
        cm = CapitalManager(initial_capital=100000.0, max_daily_loss=-2000.0, max_drawdown_pct=0.20)
        # Make sufficient profit first so daily_pnl doesn't trigger daily loss gate
        cm.record_trade(25000.0, is_winner=True)  # daily_pnl = +25000
        cm.record_trade(-30000.0, is_winner=False)  # dd = 25%, but daily_pnl = -5000 <= -2000
        # Reset daily PnL to isolate drawdown check
        cm._state.daily_pnl = 0.0  # bypass daily loss gate to test drawdown specifically
        with patch(_PATCH_TARGET) as mock_halt:
            allowed, reason = cm.decide_trade_allowed()
            assert allowed is False
            assert "drawdown" in reason.lower()
            mock_halt.assert_called_once()

    def test_blocks_consecutive_losses(self, cm: CapitalManager):
        for _ in range(5):
            cm.record_trade(-100.0, is_winner=False)
        with patch(_PATCH_TARGET) as mock_halt:
            allowed, reason = cm.decide_trade_allowed()
            assert allowed is False
            assert "consecutive" in reason.lower() or "circuit breaker" in reason.lower()
            mock_halt.assert_called_once()


# =============================================================================
# get_state Tests
# =============================================================================

class TestGetState:
    def test_returns_expected_keys(self, cm: CapitalManager):
        state = cm.get_state()
        assert "initial_capital" in state
        assert "current_capital" in state
        assert "drawdown_pct" in state
        assert "consecutive_losses" in state
        assert "total_trades" in state
        assert "win_rate" in state

    def test_win_rate_zero_when_no_trades(self, cm: CapitalManager):
        state = cm.get_state()
        assert state["win_rate"] == 0.0

    def test_win_rate_after_trades(self, cm: CapitalManager):
        cm.record_trade(100.0, is_winner=True)
        cm.record_trade(100.0, is_winner=True)
        cm.record_trade(-50.0, is_winner=False)
        state = cm.get_state()
        assert state["win_rate"] == pytest.approx(66.7, abs=0.5)

    def test_drawdown_pct(self, cm: CapitalManager):
        cm.record_trade(-20000.0, is_winner=False)  # 20% drawdown
        state = cm.get_state()
        assert state["drawdown_pct"] == pytest.approx(20.0, abs=0.5)


# =============================================================================
# Properties Tests
# =============================================================================

class TestProperties:
    def test_drawdown_pct_property(self, cm: CapitalManager):
        assert cm.drawdown_pct == 0.0
        cm.record_trade(-25000.0, is_winner=False)
        assert cm.drawdown_pct > 0

    def test_current_capital_property(self, cm: CapitalManager):
        assert cm.current_capital == 100000.0
        cm.record_trade(5000.0, is_winner=True)
        assert cm.current_capital == 105000.0
