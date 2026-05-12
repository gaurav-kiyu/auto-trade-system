"""Tests for core.execution_policy — ExecutionPolicy.apply()."""
from __future__ import annotations

from core.execution_policy import ExecutionPolicy, ExecutionDecision


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
