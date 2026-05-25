"""Tests for core/trade_mandate.py — comprehensive mandate rule enforcement."""

from __future__ import annotations

from datetime import datetime
from unittest import mock

from core.datetime_ist import now_ist
from core.trade_mandate import (
    MandateConfig,
    OperatingMode,
    TradeDecision,
    TradeEligibility,
    TradeMandateEnforcer,
    create_mandate_enforcer,
)


def _default_config() -> dict:
    return {
        "BASE_CAPITAL": 50000,
        "MANDATE_RISK_PER_TRADE": 0.015,
        "MANDATE_DAILY_HARD_STOP": 0.025,
        "MANDATE_MAX_DRAWDOWN_PROTECTION": 0.12,
    }


# Patch now_ist() to return a time within trading hours (10:00 AM IST)
_TRADING_TIME = datetime(2026, 5, 25, 10, 0, 0)


def _within_trading_window() -> mock._patch:
    return mock.patch("core.trade_mandate.now_ist", return_value=_TRADING_TIME)


class TestMandateConfig:
    def test_defaults(self) -> None:
        c = MandateConfig()
        assert c.risk_per_trade == 0.015
        assert c.daily_hard_stop == 0.025
        assert c.score_trending_min == 68
        assert c.score_sideways_min == 73

    def test_custom(self) -> None:
        c = MandateConfig(risk_per_trade=0.02, score_trending_min=70)
        assert c.risk_per_trade == 0.02
        assert c.score_trending_min == 70


class TestInit:
    def test_loads_config(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        assert enforcer.cfg.risk_per_trade == 0.015
        assert enforcer.cfg.score_trending_min == 68

    def test_initial_state(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        assert enforcer._loss_streak == 0
        assert enforcer._trades_today == 0
        assert enforcer._daily_pnl == 0.0
        assert enforcer._current_vix is None


class TestUpdateMarketState:
    def test_updates_vix(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.update_market_state(18.5, now_ist())
        assert enforcer._current_vix == 18.5

    def test_updates_data_time(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        ts = now_ist()
        enforcer.update_market_state(18.5, ts)
        assert enforcer._last_data_time == ts


class TestUpdateCapitalState:
    def test_updates_capital(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.update_capital_state(50000, 52000, -500, -1000)
        assert enforcer._current_capital == 50000
        assert enforcer._equity_peak == 52000
        assert enforcer._daily_pnl == -500
        assert enforcer._weekly_pnl == -1000


class TestRecordTradeResult:
    def test_loss_increments_streak(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.record_trade_result(-100, now_ist())
        assert enforcer._loss_streak == 1
        assert enforcer._trades_today == 1

    def test_win_resets_streak(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.record_trade_result(-100, now_ist())
        enforcer.record_trade_result(150, now_ist())
        assert enforcer._loss_streak == 0

    def test_accumulates_daily_pnl(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.record_trade_result(100, now_ist())
        enforcer.record_trade_result(-50, now_ist())
        assert enforcer._daily_pnl == 50


class TestResetDaily:
    def test_resets_trades_today(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.record_trade_result(100, now_ist())
        enforcer.reset_daily()
        assert enforcer._trades_today == 0


class TestGetOperatingMode:
    def test_no_vix_returns_standard(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        assert enforcer.get_operating_mode() == OperatingMode.STANDARD

    def test_vix_high_block_returns_observe(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.update_market_state(35.0, now_ist())
        assert enforcer.get_operating_mode() == OperatingMode.OBSERVE_ONLY

    def test_vix_high_but_not_block_returns_high_stress(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.update_market_state(28.5, now_ist())
        assert enforcer.get_operating_mode() == OperatingMode.HIGH_STRESS

    def test_vix_25_plus_loss_streak_high_stress(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.update_market_state(26.0, now_ist())
        enforcer.record_trade_result(-100, now_ist())
        enforcer.record_trade_result(-100, now_ist())
        assert enforcer.get_operating_mode() == OperatingMode.HIGH_STRESS

    def test_vix_20_to_28_returns_cautious(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.update_market_state(22.0, now_ist())
        assert enforcer.get_operating_mode() == OperatingMode.CAUTIOUS

    def test_vix_below_20_returns_standard(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.update_market_state(15.0, now_ist())
        assert enforcer.get_operating_mode() == OperatingMode.STANDARD

    def test_drawdown_over_8pct_observe(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.update_capital_state(45000, 50000, -5000, -5000)
        enforcer.update_market_state(15.0, now_ist())
        assert enforcer.get_operating_mode() == OperatingMode.OBSERVE_ONLY


class TestCheckTradeEligibility:
    def test_observe_mode_blocks(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.update_market_state(35.0, now_ist())
        with _within_trading_window():
            result = enforcer.check_trade_eligibility("NIFTY", 75, "TRENDING", 0.8, 0.3, 100, 50, 0.5, 0)
        assert result.decision == TradeDecision.BLOCKED
        assert "OBSERVE_ONLY" in result.reason

    def test_max_positions_blocks(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.update_market_state(15.0, now_ist())
        with _within_trading_window():
            result = enforcer.check_trade_eligibility("NIFTY", 75, "TRENDING", 0.8, 0.3, 100, 50, 0.5, 2)
        assert result.decision == TradeDecision.BLOCKED
        assert "Max positions" in result.reason

    def test_vix_below_min_blocks(self) -> None:
        enforcer = TradeMandateEnforcer({
            **_default_config(),
            "MANDATE_VIX_MIN": 15.0,
        })
        enforcer.update_market_state(10.0, now_ist())
        with _within_trading_window():
            result = enforcer.check_trade_eligibility("NIFTY", 75, "TRENDING", 0.8, 0.3, 100, 50, 0.5, 0)
        assert result.decision == TradeDecision.BLOCKED
        assert "VIX" in result.reason

    def test_regime_confidence_below_min_blocks(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.update_market_state(15.0, now_ist())
        with _within_trading_window():
            result = enforcer.check_trade_eligibility("NIFTY", 75, "TRENDING", 0.5, 0.3, 100, 50, 0.5, 0)
        assert result.decision == TradeDecision.BLOCKED
        assert "confidence" in result.reason.lower()

    def test_score_below_min_for_regime_blocks(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.update_market_state(15.0, now_ist())
        with _within_trading_window():
            result = enforcer.check_trade_eligibility("NIFTY", 60, "TRENDING", 0.8, 0.3, 100, 50, 0.5, 0)
        assert result.decision == TradeDecision.BLOCKED
        assert "Score" in result.reason

    def test_high_score_high_iv_filter_blocks(self) -> None:
        enforcer = TradeMandateEnforcer({
            **_default_config(),
            "MANDATE_BLOCK_HIGH_IV_THRESHOLD": 0.25,
        })
        enforcer.update_market_state(15.0, now_ist())
        with _within_trading_window():
            result = enforcer.check_trade_eligibility("NIFTY", 80, "TRENDING", 0.8, 0.30, 100, 50, 0.5, 0)
        assert result.decision == TradeDecision.BLOCKED
        assert "false signal" in result.reason.lower()

    def test_iv_rank_below_min_blocks(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.update_market_state(15.0, now_ist())
        with _within_trading_window():
            result = enforcer.check_trade_eligibility("NIFTY", 75, "TRENDING", 0.8, 0.10, 100, 50, 0.5, 0)
        assert result.decision == TradeDecision.BLOCKED
        assert "IV rank" in result.reason

    def test_finnifty_rules_block(self) -> None:
        """Score passes SIDEWAYS min (73) but FINNIFTY regime check fails."""
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.update_market_state(15.0, now_ist())
        with _within_trading_window():
            result = enforcer.check_trade_eligibility(
                "FINNIFTY", 75, "SIDEWAYS", 0.8, 0.3, 100, 50, 0.5, 0,
            )
        assert result.decision == TradeDecision.BLOCKED
        assert "FINNIFTY" in result.reason

    def test_expected_value_below_min_blocks(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        enforcer.update_market_state(15.0, now_ist())
        with _within_trading_window():
            result = enforcer.check_trade_eligibility("NIFTY", 68, "TRENDING", 0.8, 0.3, 10, 200, 0.1, 0)
        assert result.decision == TradeDecision.BLOCKED
        assert "Expected value" in result.reason

    def test_all_checks_pass(self) -> None:
        """All gates pass: EV = 77 >= 40, score 75 >= 68, IV rank 0.35 >= 0.20."""
        enforcer = TradeMandateEnforcer({
            **_default_config(),
            "BASE_CAPITAL": 50000,
        })
        enforcer.update_capital_state(50000, 50000, 0, 0)
        enforcer.update_market_state(15.0, now_ist())
        # EV = (0.7 * 300 * 0.8) - (0.3 * 50 * 1.2) - 73 = 168 - 18 - 73 = 77 >= 40
        with _within_trading_window():
            result = enforcer.check_trade_eligibility(
                "NIFTY", 75, "TRENDING", 0.8, 0.35, 300, 50, 0.7, 0,
            )
        assert result.decision == TradeDecision.ALLOWED, f"Expected ALLOWED, got {result.decision}: {result.reason}"
        assert result.risk_amount > 0

    def test_loss_streak_cooldown_blocks(self) -> None:
        enforcer = TradeMandateEnforcer({
            **_default_config(),
            "MANDATE_LOSS_STREAK_THRESHOLD": 2,
        })
        enforcer.update_market_state(15.0, now_ist())
        enforcer.record_trade_result(-100, now_ist())
        enforcer.record_trade_result(-100, now_ist())
        with _within_trading_window():
            result = enforcer.check_trade_eligibility("NIFTY", 75, "TRENDING", 0.8, 0.3, 100, 50, 0.5, 0)
        assert result.decision == TradeDecision.BLOCKED
        assert "cooldown" in result.reason.lower()


class TestGetPositionSizing:
    def test_uncertainty_returns_cfg(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        assert enforcer.get_position_sizing("TRENDING", uncertainty=True) == 0.5

    def test_trending_multiplier(self) -> None:
        enforcer = TradeMandateEnforcer({
            **_default_config(),
            "BASE_CAPITAL": 10000,
        })
        enforcer.update_capital_state(10000, 10000, 0, 0)
        amount = enforcer.get_position_sizing("TRENDING")
        expected = 10000 * 0.015 * 1.2
        assert amount == expected

    def test_sideways_multiplier(self) -> None:
        enforcer = TradeMandateEnforcer({
            **_default_config(),
            "BASE_CAPITAL": 10000,
        })
        enforcer.update_capital_state(10000, 10000, 0, 0)
        amount = enforcer.get_position_sizing("SIDEWAYS")
        expected = 10000 * 0.015 * 0.85
        assert amount == expected

    def test_range_multiplier(self) -> None:
        enforcer = TradeMandateEnforcer({
            **_default_config(),
            "BASE_CAPITAL": 10000,
        })
        enforcer.update_capital_state(10000, 10000, 0, 0)
        amount = enforcer.get_position_sizing("CHOPPY")
        expected = 10000 * 0.015 * 0.75
        assert amount == expected


class TestIsTradingWindow:
    def test_morning_window_allows(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        with mock.patch("core.trade_mandate.now_ist") as mock_now:
            mock_now.return_value.hour = 10
            mock_now.return_value.minute = 0
            assert enforcer._is_trading_window() is True

    def test_afternoon_window_allows(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        with mock.patch("core.trade_mandate.now_ist") as mock_now:
            mock_now.return_value.hour = 14
            mock_now.return_value.minute = 0
            assert enforcer._is_trading_window() is True

    def test_lunch_break_blocks(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        with mock.patch("core.trade_mandate.now_ist") as mock_now:
            mock_now.return_value.hour = 12
            mock_now.return_value.minute = 0
            assert enforcer._is_trading_window() is False

    def test_late_afternoon_blocks(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        with mock.patch("core.trade_mandate.now_ist") as mock_now:
            mock_now.return_value.hour = 15
            mock_now.return_value.minute = 0
            assert enforcer._is_trading_window() is False

    def test_early_morning_blocks(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        with mock.patch("core.trade_mandate.now_ist") as mock_now:
            mock_now.return_value.hour = 8
            mock_now.return_value.minute = 0
            assert enforcer._is_trading_window() is False


class TestCalculateExpectedValue:
    def test_positive_ev(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        # win_rate=0.8, avg_win=200, avg_loss=50
        # adjusted_win = 200 * 0.8 = 160
        # adjusted_loss = 50 * 1.2 = 60
        # friction = 20 + 50 + 3 = 73
        # EV = (0.8 * 160) - (0.2 * 60) - 73 = 128 - 12 - 73 = 43
        ev = enforcer._calculate_expected_value(0.8, 200, 50)
        assert ev == 43.0

    def test_negative_ev(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        ev = enforcer._calculate_expected_value(0.3, 50, 100)
        assert ev < 0

    def test_includes_friction(self) -> None:
        enforcer = TradeMandateEnforcer(_default_config())
        ev = enforcer._calculate_expected_value(0.5, 200, 200)
        assert ev < 0


class TestCreateMandateEnforcer:
    def test_creates_from_config(self) -> None:
        enforcer = create_mandate_enforcer(_default_config())
        assert isinstance(enforcer, TradeMandateEnforcer)
        assert enforcer.cfg.risk_per_trade == 0.015

    def test_empty_config_defaults(self) -> None:
        enforcer = create_mandate_enforcer({})
        assert enforcer.cfg.risk_per_trade == 0.015
        assert enforcer.cfg.score_trending_min == 68


class TestTradeEligibility:
    def test_dataclass(self) -> None:
        e = TradeEligibility(
            decision=TradeDecision.ALLOWED,
            reason="All good",
            risk_amount=750.0,
            expected_value=50.0,
            mode=OperatingMode.STANDARD,
        )
        assert e.decision == TradeDecision.ALLOWED
        assert e.reason == "All good"
        assert e.risk_amount == 750.0
        assert e.expected_value == 50.0
        assert e.mode == OperatingMode.STANDARD
