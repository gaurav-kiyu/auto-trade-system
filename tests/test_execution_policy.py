"""Tests for core.execution_policy - ExecutionPolicy.apply()."""
from __future__ import annotations

from core.execution_policy import ExecutionPolicy


class TestExecutionPolicy:
    def test_strong_high_score_trades(self) -> None:
        decision = ExecutionPolicy.apply(
            signal={"score": 90, "direction": "CALL"},
            config={},
            regime="TRENDING",
            max_lots=5,
        )
        assert decision.trade
        assert decision.tier == "STRONG"
        assert decision.lots >= 1

    def test_low_score_skips(self) -> None:
        decision = ExecutionPolicy.apply(
            signal={"score": 30, "direction": "CALL"},
            config={},
            regime="TRENDING",
            max_lots=5,
        )
        assert not decision.trade
        assert decision.mode == "SKIP"

    def test_decision_contains_sl_mult(self) -> None:
        decision = ExecutionPolicy.apply(
            signal={"score": 85, "direction": "CALL"},
            config={},
            regime="TRENDING",
            max_lots=5,
        )
        assert decision.sl_mult == 1.0

    def test_decision_contains_reasons(self) -> None:
        decision = ExecutionPolicy.apply(
            signal={"score": 85, "direction": "CALL"},
            config={},
            regime="TRENDING",
            max_lots=5,
        )
        assert isinstance(decision.reasons, list)

    def test_quality_score_is_computed(self) -> None:
        decision = ExecutionPolicy.apply(
            signal={"score": 85, "direction": "CALL", "vol_ratio": 1.5, "adx": 25},
            config={},
            regime="TRENDING",
            max_lots=5,
        )
        assert 0.0 <= decision.quality_score <= 1.0

    def test_execution_decision_lots_property(self) -> None:
        decision = ExecutionPolicy.apply(
            signal={"score": 90, "direction": "CALL"},
            config={},
            regime="TRENDING",
            max_lots=3,
        )
        assert decision.lots >= 0

    def test_tier_boundary_is_config_configurable(self) -> None:
        """A Super-Admin-configured TIER_STRONG_MIN must change the resulting tier."""
        default_decision = ExecutionPolicy.apply(
            signal={"score": 82, "direction": "CALL"},
            config={},
            regime="TRENDING",
            max_lots=5,
        )
        assert default_decision.tier == "STRONG"

        overridden_decision = ExecutionPolicy.apply(
            signal={"score": 82, "direction": "CALL"},
            config={"TIER_STRONG_MIN": 85},
            regime="TRENDING",
            max_lots=5,
        )
        assert overridden_decision.tier == "MODERATE"


class TestPartialExitGlobalOverride:
    """config key PARTIAL_EXIT_ENABLED - global override on top of
    TierRules' per-tier partial_exit_enabled (already live for
    MODERATE/WEAK regardless of this key)."""

    def test_default_true_preserves_moderate_tier_partial_exit(self) -> None:
        """Regression guard: default config (no PARTIAL_EXIT_ENABLED key,
        same as its real default of true) must leave MODERATE's already-
        shipped partial exit behavior completely unchanged."""
        decision = ExecutionPolicy.apply(
            signal={"score": 75, "direction": "CALL"},
            config={},
            regime="TRENDING",
            max_lots=5,
        )
        assert decision.tier == "MODERATE"
        assert decision.partial_exit_enabled is True
        assert decision.mode == "PARTIAL"

    def test_explicit_false_forces_full_exit_on_moderate_tier(self) -> None:
        """Setting PARTIAL_EXIT_ENABLED=False must override TierRules'
        MODERATE partial_exit_enabled=True and force a FULL exit instead -
        proving this is a real, working global override."""
        decision = ExecutionPolicy.apply(
            signal={"score": 75, "direction": "CALL"},
            config={"PARTIAL_EXIT_ENABLED": False},
            regime="TRENDING",
            max_lots=5,
        )
        assert decision.tier == "MODERATE"
        assert decision.partial_exit_enabled is False
        assert decision.mode == "FULL"
