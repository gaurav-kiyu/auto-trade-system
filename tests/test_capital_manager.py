"""Tests for core.capital_manager — equity-aware capital scaling and drawdown control."""
from __future__ import annotations

import pytest
from core.capital_manager import CapitalManager, ScaleResult


class TestCapitalManagerInit:
    def test_default_initialization(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        assert cm.current_capital == 100000
        assert cm.drawdown_pct == 0.0
        allowed, reason = cm.decide_trade_allowed()
        assert allowed
        assert reason == "OK"

    def test_max_daily_loss_must_be_negative(self) -> None:
        with pytest.raises(ValueError, match="must be negative"):
            CapitalManager(initial_capital=100000, max_daily_loss=100)

    def test_zero_max_daily_loss_raises(self) -> None:
        with pytest.raises(ValueError, match="must be negative"):
            CapitalManager(initial_capital=100000, max_daily_loss=0)

    def test_custom_drawdown_threshold(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000, max_drawdown_pct=0.10)
        assert cm._max_dd == 0.10


class TestCapitalManagerScale:
    def test_scale_returns_full_size_initially(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        result = cm.scale(base_lots=3, max_lots=5)
        assert isinstance(result, ScaleResult)
        assert result.scaled_lots >= 1
        assert 0.0 <= result.scale_factor <= 1.0

    def test_scale_with_max_lots_caps(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        result = cm.scale(base_lots=100, max_lots=2)
        assert result.scaled_lots <= 2
        assert result.scaled_lots >= 1

    def test_scale_factors_are_deterministic(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        r1 = cm.scale(2, 5)
        r2 = cm.scale(2, 5)
        assert r1.scale_factor == r2.scale_factor
        assert r1.scaled_lots == r2.scaled_lots

    def test_scale_drawdown_reduces_size(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        # Simulate large loss
        cm.record_trade(net_pnl=-30000, is_winner=False)
        result = cm.scale(base_lots=5, max_lots=5)
        assert result.drawdown_factor < 1.0


class TestCapitalManagerTradeRecording:
    def test_win_resets_consecutive_losses(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        cm.record_trade(net_pnl=-500, is_winner=False)
        cm.record_trade(net_pnl=1000, is_winner=True)
        state = cm.get_state()
        assert state["consecutive_losses"] == 0

    def test_loss_increments_consecutive_counter(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        cm.record_trade(net_pnl=-500, is_winner=False)
        cm.record_trade(net_pnl=-300, is_winner=False)
        state = cm.get_state()
        assert state["consecutive_losses"] == 2

    def test_record_trade_updates_capital(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        cm.record_trade(net_pnl=5000, is_winner=True)
        assert cm.current_capital == 105000

    def test_record_trade_updates_daily_pnl(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        cm.record_trade(net_pnl=2000, is_winner=True)
        state = cm.get_state()
        assert state["daily_pnl"] == 2000

    def test_record_trade_tracks_win_rate(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        cm.record_trade(net_pnl=100, is_winner=True)
        cm.record_trade(net_pnl=100, is_winner=True)
        cm.record_trade(net_pnl=-100, is_winner=False)
        state = cm.get_state()
        assert state["total_trades"] == 3
        assert state["win_rate"] == pytest.approx(66.7, rel=0.1)


class TestCapitalManagerSafetyGates:
    def test_daily_loss_limit_blocks_trades(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        cm.record_trade(net_pnl=-5000, is_winner=False)
        allowed, reason = cm.decide_trade_allowed()
        assert not allowed
        assert "Daily loss" in reason

    def test_drawdown_blocks_trades(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-40000, max_drawdown_pct=0.10)
        cm.record_trade(net_pnl=-12000, is_winner=False)
        allowed, reason = cm.decide_trade_allowed()
        assert not allowed
        assert "drawdown" in reason.lower()

    def test_five_consecutive_losses_trips_circuit_breaker(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        for _ in range(5):
            cm.record_trade(net_pnl=-100, is_winner=False)
        allowed, reason = cm.decide_trade_allowed()
        assert not allowed
        assert "circuit breaker" in reason.lower()

    def test_ok_after_single_loss(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        cm.record_trade(net_pnl=-100, is_winner=False)
        allowed, reason = cm.decide_trade_allowed()
        assert allowed


class TestCapitalManagerDailyReset:
    def test_reset_daily_clears_daily_pnl(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        cm.record_trade(net_pnl=5000, is_winner=True)
        cm.reset_daily()
        state = cm.get_state()
        assert state["daily_pnl"] == 0.0
        assert state["total_trades"] == 1  # persists across days


class TestCapitalManagerProfitLocking:
    def test_lock_profits_extracts_profit(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        cm.record_trade(net_pnl=20000, is_winner=True)
        locked = cm.lock_profits(lock_pct=0.5)
        assert locked > 0
        state = cm.get_state()
        assert state["locked_profit"] == locked

    def test_no_profit_no_lock(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        locked = cm.lock_profits(lock_pct=0.5)
        assert locked == 0.0


class TestCapitalManagerState:
    def test_get_state_contains_all_keys(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        state = cm.get_state()
        expected_keys = {
            "initial_capital", "current_capital", "peak_capital",
            "locked_profit", "daily_pnl", "drawdown_pct",
            "consecutive_losses", "total_trades", "win_rate",
            "capital_return_pct",
        }
        assert set(state.keys()) == expected_keys

    def test_get_state_reflects_trades(self) -> None:
        cm = CapitalManager(initial_capital=100000, max_daily_loss=-4000)
        cm.record_trade(net_pnl=5000, is_winner=True)
        state = cm.get_state()
        assert state["current_capital"] == 105000
        assert state["total_trades"] == 1
        assert state["win_rate"] == 100.0
