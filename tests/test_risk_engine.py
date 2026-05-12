"""Tests for core.risk_engine — unified RiskEngine (v1+v2)."""
from __future__ import annotations

from typing import Any

from core.risk_engine import (
    RiskConfig,
    RiskDecision,
    RiskEngine,
    RiskEngineV2Config,
    RiskEvalResult,
    evaluate_risk,
)


class TestRiskConfig:
    def test_defaults(self) -> None:
        c = RiskConfig()
        assert c.min_volume_ratio == 0.0
        assert c.max_spread_pct == 1.0
        assert c.portfolio_risk_cap_pct == 0.75


class TestRiskDecision:
    def test_allowed(self) -> None:
        d = RiskDecision(True, "ok")
        assert d.allowed
        assert d.reason == "ok"

    def test_denied(self) -> None:
        d = RiskDecision(False, "too risky")
        assert not d.allowed


class TestRiskEngineQualityCheck:
    def test_all_checks_pass(self) -> None:
        engine = RiskEngine()
        decision = engine.quality_check(volume_ratio=1.0, spread_pct=0.05, slippage_pct=0.02)
        assert decision.allowed
        assert decision.reason == ""

    def test_low_volume_fails(self) -> None:
        engine = RiskEngine(config=RiskConfig(min_volume_ratio=0.5))
        decision = engine.quality_check(volume_ratio=0.1)
        assert not decision.allowed
        assert "low volume" in decision.reason

    def test_wide_spread_fails(self) -> None:
        engine = RiskEngine(config=RiskConfig(max_spread_pct=0.1))
        decision = engine.quality_check(spread_pct=0.2)
        assert not decision.allowed
        assert "spread" in decision.reason

    def test_high_slippage_fails(self) -> None:
        engine = RiskEngine(config=RiskConfig(max_slippage_pct=0.1))
        decision = engine.quality_check(slippage_pct=0.2)
        assert not decision.allowed
        assert "slippage" in decision.reason


class TestRiskEngineLossStreak:
    def test_no_streak_ok(self) -> None:
        engine = RiskEngine(consecutive_loss_fn=lambda: 0)
        decision = engine.loss_streak_check()
        assert decision.allowed

    def test_streak_exceeds_limit(self) -> None:
        engine = RiskEngine(
            config=RiskConfig(max_consecutive_losses=2),
            consecutive_loss_fn=lambda: 3,
        )
        decision = engine.loss_streak_check()
        assert not decision.allowed
        assert "loss streak" in decision.reason

    def test_streak_function_none(self) -> None:
        engine = RiskEngine()
        assert engine.current_loss_streak() == 0

    def test_streak_function_returns_negative(self) -> None:
        engine = RiskEngine(consecutive_loss_fn=lambda: -1)
        assert engine.current_loss_streak() == 0


class TestRiskEngineV2Evaluate:
    def test_all_checks_pass(self) -> None:
        engine = RiskEngine(
            v2_config=RiskEngineV2Config(max_daily_loss=-400, max_open=2, max_trades_day=5, cooldown_seconds=0),
            get_state_fn=lambda: {
                "daily_pnl": 100.0,
                "open_positions": 0,
                "trade_count": 1,
                "last_trade_time": {"NIFTY": 0},
            },
        )
        result = engine.evaluate("NIFTY")
        assert result.allowed

    def test_daily_loss_exceeded(self) -> None:
        engine = RiskEngine(
            v2_config=RiskEngineV2Config(max_daily_loss=-400),
            get_state_fn=lambda: {"daily_pnl": -500.0},
        )
        result = engine.evaluate("ANY")
        assert not result.allowed
        assert "daily loss" in result.reason
        assert not result.daily_loss_ok

    def test_max_open_positions(self) -> None:
        engine = RiskEngine(
            v2_config=RiskEngineV2Config(max_open=1),
            get_state_fn=lambda: {"open_positions": 1},
        )
        result = engine.evaluate("NIFTY")
        assert not result.allowed
        assert "max open" in result.reason

    def test_max_trades_reached(self) -> None:
        engine = RiskEngine(
            v2_config=RiskEngineV2Config(max_trades_day=2),
            get_state_fn=lambda: {"trade_count": 2},
        )
        result = engine.evaluate("ANY")
        assert not result.allowed
        assert "max trades" in result.reason

    def test_cooldown_active(self) -> None:
        import time
        now = time.time()
        engine = RiskEngine(
            v2_config=RiskEngineV2Config(cooldown_seconds=300),
            get_state_fn=lambda: {
                "last_trade_time": {"NIFTY": now - 10},
            },
        )
        result = engine.evaluate("NIFTY")
        assert not result.allowed
        assert "cooldown" in result.reason


class TestRiskEnginePositionSize:
    def test_with_callback(self) -> None:
        engine = RiskEngine(position_size_fn=lambda name, ltp, vix: 75)
        assert engine.get_position_size("NIFTY", 100.0) == 75

    def test_without_callback(self) -> None:
        engine = RiskEngine()
        assert engine.get_position_size("NIFTY", 100.0) == 0


class TestStandaloneEvaluateRisk:
    def test_all_ok(self) -> None:
        result = evaluate_risk(
            {"daily_pnl": 100, "open_positions": 0, "trade_count": 1, "last_trade_time": {}},
            {"risk": {"max_daily_loss": -400}, "timing": {"cooldown": 0}},
            "NIFTY",
        )
        assert result["allowed"]

    def test_daily_loss_rejected(self) -> None:
        result = evaluate_risk(
            {"daily_pnl": -500},
            {"risk": {"max_daily_loss": -400}},
        )
        assert not result["allowed"]
        assert "max daily loss" in result["reason"]

    def test_max_trades_rejected(self) -> None:
        result = evaluate_risk(
            {"daily_pnl": 100, "trade_count": 2},
            {"risk": {"max_daily_loss": -400, "max_trades_day": 2}},
        )
        assert not result["allowed"]
        assert "max trades" in result["reason"]

    def test_empty_config(self) -> None:
        result = evaluate_risk({"daily_pnl": 100}, {}, "NIFTY")
        assert result["allowed"]

    def test_empty_state(self) -> None:
        result = evaluate_risk({}, {"risk": {"max_daily_loss": -400}}, "NIFTY")
        assert result["allowed"]


class TestRiskEvalResult:
    def test_defaults(self) -> None:
        r = RiskEvalResult(allowed=True, reason="ok")
        assert r.allowed
        assert r.quality_ok

    def test_not_allowed(self) -> None:
        r = RiskEvalResult(allowed=False, reason="risk", daily_loss_ok=False)
        assert not r.allowed
        assert not r.daily_loss_ok
