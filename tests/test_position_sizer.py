"""Tests for core.position_sizer - tiered position sizing engine."""
from __future__ import annotations

from core.position_sizer import PositionSizer


class TestPositionSizer:
    def test_strong_tier_max_lots(self) -> None:
        spec = PositionSizer.calculate(score=90, tier="STRONG", regime="TRENDING", max_lots=5)
        assert spec.tier == "STRONG"
        assert spec.lots == 5  # 100% of 5
        assert spec.tier_base_pct == 1.0

    def test_moderate_tier_reduces_size(self) -> None:
        spec = PositionSizer.calculate(score=75, tier="MODERATE", regime="TRENDING", max_lots=5)
        assert spec.tier == "MODERATE"
        assert 1 <= spec.lots <= 5
        assert spec.tier_base_pct == 0.60

    def test_weak_tier_small_size(self) -> None:
        spec = PositionSizer.calculate(score=65, tier="WEAK", regime="TRENDING", max_lots=5)
        assert spec.tier == "WEAK"
        assert spec.tier_base_pct == 0.30

    def test_ignore_tier_zero_lots(self) -> None:
        spec = PositionSizer.calculate(score=30, tier="IGNORE", regime="TRENDING", max_lots=5)
        assert spec.lots == 0
        assert spec.effective_pct == 0.0

    def test_choppy_regime_reduces_size(self) -> None:
        trending = PositionSizer.calculate(score=85, tier="STRONG", regime="TRENDING", max_lots=5)
        choppy = PositionSizer.calculate(score=85, tier="STRONG", regime="CHOPPY", max_lots=5)
        assert trending.lots >= choppy.lots
        assert choppy.regime_adj == 0.50

    def test_event_regime_heavy_reduction(self) -> None:
        spec = PositionSizer.calculate(score=85, tier="STRONG", regime="EVENT", max_lots=5)
        assert spec.regime_adj == 0.30

    def test_returns_position_spec_with_reasoning(self) -> None:
        spec = PositionSizer.calculate(score=80, tier="MODERATE", regime="TRENDING", max_lots=3)
        assert spec.reasoning
        assert "MODERATE" in spec.reasoning
        assert spec.lots >= 1
