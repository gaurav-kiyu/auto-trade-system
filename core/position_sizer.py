"""
Position sizing engine for the tiered adaptive framework.

effective_pct = tier_base × regime_adj × score_within_tier_adj

    tier_base       — from TierRules.position_pct (1.00 / 0.60 / 0.30)
    regime_adj      — market regime multiplier (TRENDING=1.0 → CHOPPY=0.5)
    score_within    — linear scale within tier band → [0.90, 1.10]

Final lots = floor(effective_pct × max_lots), minimum 1 if tier is tradeable.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.tier_engine import (
    TIER_MODERATE_MIN,
    TIER_RULES,
    TIER_STRONG_MIN,
    TIER_WEAK_MIN,
)

# Regime-based position size multipliers
_REGIME_SIZE_ADJ: dict[str, float] = {
    "TRENDING":        1.00,
    "NEUTRAL":         0.90,
    "SIDEWAYS":        0.75,
    "CHOPPY":          0.50,
    "HIGH_VOLATILITY": 0.65,
    "EVENT":           0.30,
    "SIM":             0.90,   # simulation default
}

# Tier score ranges for within-tier normalisation [min_inclusive, max_inclusive]
_TIER_RANGES: dict[str, tuple[int, int]] = {
    "STRONG":   (TIER_STRONG_MIN,   100),
    "MODERATE": (TIER_MODERATE_MIN, TIER_STRONG_MIN - 1),
    "WEAK":     (TIER_WEAK_MIN,     TIER_MODERATE_MIN - 1),
    "IGNORE":   (0,                 TIER_WEAK_MIN - 1),
}


@dataclass
class PositionSpec:
    tier: str
    regime: str
    score: int
    tier_base_pct: float      # raw tier fraction (e.g. 0.60 for MODERATE)
    regime_adj: float         # regime multiplier applied
    score_adj: float          # within-tier score scaling [0.90, 1.10]
    effective_pct: float      # final fraction of max_lots
    lots: int                 # actual lots (floor of effective_pct × max_lots, min 1)
    reasoning: str


class PositionSizer:
    """Stateless position sizing calculator. All methods are static."""

    @staticmethod
    def calculate(
        score: int,
        tier: str,
        regime: str,
        max_lots: int,
        atr: float = 0.0,
        capital: float = 100_000.0,
    ) -> PositionSpec:
        """
        Calculate position size for a given signal.

        Capital-aware sizing: max_lots is reduced proportionally when capital
        is below BASE_CAPITAL threshold, preventing over-leverage on small accounts.

        Args:
            score:     Final adjusted signal score (0-100)
            tier:      Signal tier (STRONG / MODERATE / WEAK / IGNORE)
            regime:    Market regime string
            max_lots:  Maximum configured lots per trade
            atr:       Current ATR (unused numerically, available for future ATR-scaling)
            capital:   Available capital — used to cap lots when below BASE_CAPITAL

        Returns:
            PositionSpec with lots=0 for IGNORE tier.
        """
        rules = TIER_RULES.get(tier)
        if rules is None or rules.position_pct == 0.0:
            return PositionSpec(
                tier=tier, regime=regime, score=score,
                tier_base_pct=0.0, regime_adj=0.0, score_adj=0.0,
                effective_pct=0.0, lots=0,
                reasoning="IGNORE tier — no trade",
            )

        tier_base  = rules.position_pct
        regime_adj = _REGIME_SIZE_ADJ.get(regime, 0.90)

        # Within-tier score scaling: 0.90 at tier minimum, 1.10 at tier maximum
        lo, hi = _TIER_RANGES.get(tier, (60, 100))
        norm = (score - lo) / (hi - lo) if hi > lo else (1.0 if score >= hi else 0.0)
        norm = max(0.0, min(1.0, norm))
        score_adj = 0.90 + norm * 0.20    # [0.90, 1.10]

        effective_pct = tier_base * regime_adj * score_adj
        effective_pct = max(0.0, min(1.0, round(effective_pct, 4)))

        # ── Capital constraint (Phase 5E / C12) ─────────────────────────────
        # Scale down max_lots when capital is below the baseline.
        # Baseline matches index_config.defaults.json BASE_CAPITAL default.
        _BASE_CAPITAL = 100_000.0
        if capital < _BASE_CAPITAL and capital > 0:
            capital_ratio = capital / BASE_CAPITAL
            max_lots = max(1, int(max_lots * capital_ratio))

        # Always at least 1 lot if tier is tradeable and max_lots >= 1
        lots = max(1, int(effective_pct * max(1, max_lots)))

        reasoning = (
            f"{tier} base={tier_base:.0%} × "
            f"regime({regime})={regime_adj:.2f} × "
            f"score_adj={score_adj:.2f} → "
            f"{effective_pct:.1%} = {lots}/{max_lots} lots"
        )

        return PositionSpec(
            tier=tier,
            regime=regime,
            score=score,
            tier_base_pct=tier_base,
            regime_adj=regime_adj,
            score_adj=score_adj,
            effective_pct=effective_pct,
            lots=lots,
            reasoning=reasoning,
        )
