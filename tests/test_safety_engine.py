"""
Tests for core/safety_engine.py - Central circuit-breaker safety checks.

Covers:
  - SafetyConfig dataclass defaults and custom
  - SafetyContext dataclass
  - SafetyDecision dataclass
  - SafetyEngine.evaluate with all guard conditions
  - Each failure condition independently
  - Success path when all conditions pass
"""
from __future__ import annotations

import pytest

from core.safety_engine import SafetyConfig, SafetyContext, SafetyDecision, SafetyEngine


# ── SafetyConfig ────────────────────────────────────────────────────


class TestSafetyConfig:
    def test_default_values(self) -> None:
        cfg = SafetyConfig()
        assert cfg.max_api_failures == 5
        assert cfg.max_consecutive_losses == 3
        assert cfg.max_reconciliation_mismatches == 1
        assert cfg.max_slippage_pct == 0.02
        assert cfg.max_stale_data_sec == 180
        assert cfg.require_healthy_data is True

    def test_custom_values(self) -> None:
        cfg = SafetyConfig(
            max_api_failures=10,
            max_consecutive_losses=5,
            max_slippage_pct=0.05,
            require_healthy_data=False,
        )
        assert cfg.max_api_failures == 10
        assert cfg.max_consecutive_losses == 5
        assert cfg.max_slippage_pct == 0.05
        assert cfg.require_healthy_data is False


# ── SafetyContext ───────────────────────────────────────────────────


class TestSafetyContext:
    def test_default_values(self) -> None:
        ctx = SafetyContext()
        assert ctx.api_failures == 0
        assert ctx.consecutive_losses == 0
        assert ctx.reconciliation_mismatches == 0
        assert ctx.slippage_pct == 0.0
        assert ctx.stale_data_sec == 0
        assert ctx.data_healthy is True

    def test_custom_values(self) -> None:
        ctx = SafetyContext(
            api_failures=3,
            consecutive_losses=2,
            data_healthy=False,
        )
        assert ctx.api_failures == 3
        assert ctx.consecutive_losses == 2
        assert ctx.data_healthy is False


# ── SafetyDecision ──────────────────────────────────────────────────


class TestSafetyDecision:
    def test_allowed_with_reason(self) -> None:
        d = SafetyDecision(allowed=True, reason="")
        assert d.allowed
        assert d.reason == ""

    def test_denied_with_reason(self) -> None:
        d = SafetyDecision(allowed=False, reason="market data is unhealthy")
        assert not d.allowed
        assert d.reason == "market data is unhealthy"

    def test_default_reason(self) -> None:
        d = SafetyDecision(allowed=True)
        assert d.reason == ""


# ── SafetyEngine.evaluate ───────────────────────────────────────────


class TestSafetyEngineEvaluate:
    @pytest.fixture()
    def engine(self) -> SafetyEngine:
        return SafetyEngine(SafetyConfig())

    def test_all_conditions_pass(self, engine: SafetyEngine) -> None:
        ctx = SafetyContext()
        result = engine.evaluate(ctx)
        assert result.allowed
        assert result.reason == ""

    def test_unhealthy_data_blocks(self, engine: SafetyEngine) -> None:
        ctx = SafetyContext(data_healthy=False)
        result = engine.evaluate(ctx)
        assert not result.allowed
        assert "unhealthy" in result.reason

    def test_unhealthy_data_disabled_when_not_required(self) -> None:
        engine = SafetyEngine(SafetyConfig(require_healthy_data=False))
        ctx = SafetyContext(data_healthy=False)
        result = engine.evaluate(ctx)
        assert result.allowed

    def test_api_failures_blocks(self, engine: SafetyEngine) -> None:
        ctx = SafetyContext(api_failures=5)
        result = engine.evaluate(ctx)
        assert not result.allowed
        assert "api failures" in result.reason

    def test_api_failures_below_threshold(self, engine: SafetyEngine) -> None:
        ctx = SafetyContext(api_failures=4)
        result = engine.evaluate(ctx)
        assert result.allowed

    def test_consecutive_losses_blocks(self, engine: SafetyEngine) -> None:
        ctx = SafetyContext(consecutive_losses=3)
        result = engine.evaluate(ctx)
        assert not result.allowed
        assert "loss streak" in result.reason

    def test_consecutive_losses_below_threshold(self, engine: SafetyEngine) -> None:
        ctx = SafetyContext(consecutive_losses=2)
        result = engine.evaluate(ctx)
        assert result.allowed

    def test_reconciliation_mismatches_blocks(self, engine: SafetyEngine) -> None:
        ctx = SafetyContext(reconciliation_mismatches=1)
        result = engine.evaluate(ctx)
        assert not result.allowed
        assert "reconciliation" in result.reason

    def test_reconciliation_mismatches_below_threshold(self, engine: SafetyEngine) -> None:
        ctx = SafetyContext(reconciliation_mismatches=0)
        result = engine.evaluate(ctx)
        assert result.allowed

    def test_slippage_blocks(self, engine: SafetyEngine) -> None:
        ctx = SafetyContext(slippage_pct=0.03)
        result = engine.evaluate(ctx)
        assert not result.allowed
        assert "slippage" in result.reason

    def test_slippage_below_threshold(self, engine: SafetyEngine) -> None:
        ctx = SafetyContext(slippage_pct=0.01)
        result = engine.evaluate(ctx)
        assert result.allowed

    def test_slippage_at_boundary(self, engine: SafetyEngine) -> None:
        """Slippage exactly at threshold should pass (not exceed)."""
        ctx = SafetyContext(slippage_pct=0.02)
        result = engine.evaluate(ctx)
        assert result.allowed

    def test_stale_data_blocks(self, engine: SafetyEngine) -> None:
        ctx = SafetyContext(stale_data_sec=200)
        result = engine.evaluate(ctx)
        assert not result.allowed
        assert "stale data" in result.reason

    def test_stale_data_below_threshold(self, engine: SafetyEngine) -> None:
        ctx = SafetyContext(stale_data_sec=100)
        result = engine.evaluate(ctx)
        assert result.allowed

    def test_multiple_failures_reports_first(self, engine: SafetyEngine) -> None:
        """First failing condition should be reported."""
        ctx = SafetyContext(
            api_failures=10,
            consecutive_losses=5,
            data_healthy=False,
        )
        result = engine.evaluate(ctx)
        assert not result.allowed
        # data_healthy is checked first
        assert "unhealthy" in result.reason

    def test_custom_config_engine(self) -> None:
        engine = SafetyEngine(SafetyConfig(
            max_api_failures=2,
            max_consecutive_losses=4,
            max_stale_data_sec=60,
        ))
        # Within new limits
        assert engine.evaluate(SafetyContext(api_failures=2)).allowed is False  # at threshold
        assert engine.evaluate(SafetyContext(consecutive_losses=3)).allowed is True
        assert engine.evaluate(SafetyContext(consecutive_losses=4)).allowed is False
        assert engine.evaluate(SafetyContext(stale_data_sec=59)).allowed is True
        assert engine.evaluate(SafetyContext(stale_data_sec=60)).allowed is True  # not exceeding

    def test_frozen_dataclass(self) -> None:
        cfg = SafetyConfig()
        with pytest.raises(Exception):  # frozen dataclass can't be modified
            cfg.max_api_failures = 10  # type: ignore
