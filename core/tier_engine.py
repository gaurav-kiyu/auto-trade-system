"""Tiered signal classification and per-tier execution rules.

Tiers define HOW aggressively the system trades a given signal:

    STRONG   (≥80)  : full position, standard risk, trailing SL enabled
    MODERATE (70-79): 60% position, tighter SL/TP, partial exit at TP1
    WEAK     (60-69): 30% position, quick exit, no aggressive trailing
    IGNORE   (<60)  : no trade

Each tier has a TierRules dataclass that drives execution parameters.
These are multipliers/overrides on top of the base SimConfig values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ── Tier score boundaries ──────────────────────────────────────────────────

TIER_STRONG_MIN   = 80
TIER_MODERATE_MIN = 70
TIER_WEAK_MIN     = 60


def classify_tier(
    score: int,
    *,
    strong_min: int = TIER_STRONG_MIN,
    moderate_min: int = TIER_MODERATE_MIN,
    weak_min: int = TIER_WEAK_MIN,
) -> str:
    """Classify a score into a tier.

    ``strong_min``/``moderate_min``/``weak_min`` default to this module's
    constants (today's behavior, unchanged for any caller that doesn't pass
    them). Callers on the live path pass the resolved
    ``TIER_STRONG_MIN``/``TIER_MODERATE_MIN``/``TIER_WEAK_MIN`` config values
    so a Super Admin config change actually takes effect - see
    ``config_from_dict()`` below.
    """
    if score >= strong_min:
        return "STRONG"
    if score >= moderate_min:
        return "MODERATE"
    if score >= weak_min:
        return "WEAK"
    return "IGNORE"


def tier_bounds_from_config(cfg: Any) -> tuple[int, int, int]:
    """Resolve (strong_min, moderate_min, weak_min) from a config mapping.

    Falls back to this module's hardcoded constants for any key not present,
    so passing an empty/partial dict reproduces today's behavior exactly.
    """
    cfg = cfg or {}
    return (
        int(cfg.get("TIER_STRONG_MIN", TIER_STRONG_MIN)),
        int(cfg.get("TIER_MODERATE_MIN", TIER_MODERATE_MIN)),
        int(cfg.get("TIER_WEAK_MIN", TIER_WEAK_MIN)),
    )


# ── Per-tier execution parameters ─────────────────────────────────────────

@dataclass(frozen=True)
class TierRules:
    tier: str

    # Position sizing (fraction of configured max_lots)
    position_pct: float

    # SL/TP multipliers applied ON TOP of base sl_atr_mult / tp_atr_mult
    sl_mult_adj: float       # < 1.0 = tighter SL
    tp_mult_adj: float       # < 1.0 = nearer TP (faster booking)

    # Trailing SL
    trail_enabled:       bool
    trail_activate_pct:  float   # activate trail after X% premium gain
    trail_from_peak_pct: float   # trail at Y% below peak

    # Max bars in trade (as fraction of SimConfig.max_bars_in_trade)
    max_bars_mult: float

    # Partial exit at TP1 before TP2
    partial_exit_enabled: bool
    partial_exit_pct:     float   # fraction of position to exit at TP1


# Canonical tier rule set - do NOT change without updating config.json mirrors
TIER_RULES: dict[str, TierRules] = {
    "STRONG": TierRules(
        tier                 = "STRONG",
        position_pct         = 1.00,
        sl_mult_adj          = 1.00,    # standard SL distance
        tp_mult_adj          = 1.00,    # standard TP
        trail_enabled        = True,
        trail_activate_pct   = 0.30,    # activate at 30% premium gain
        trail_from_peak_pct  = 0.20,    # trail 20% below peak
        max_bars_mult        = 1.00,
        partial_exit_enabled = False,
        partial_exit_pct     = 0.00,
    ),
    "MODERATE": TierRules(
        tier                 = "MODERATE",
        position_pct         = 0.60,
        sl_mult_adj          = 0.90,    # tighter SL (90% of standard)
        tp_mult_adj          = 0.85,    # faster profit booking
        trail_enabled        = True,
        trail_activate_pct   = 0.20,    # activate trail sooner
        trail_from_peak_pct  = 0.25,    # slightly tighter trail
        max_bars_mult        = 0.75,    # exit 25% sooner
        partial_exit_enabled = True,
        partial_exit_pct     = 0.50,    # exit 50% of position at TP1
    ),
    "WEAK": TierRules(
        tier                 = "WEAK",
        position_pct         = 0.30,
        sl_mult_adj          = 0.80,    # much tighter SL
        tp_mult_adj          = 0.65,    # quick profit booking
        trail_enabled        = False,   # no trailing - simple SL/TP only
        trail_activate_pct   = 1.00,    # effectively disabled
        trail_from_peak_pct  = 0.50,
        max_bars_mult        = 0.50,    # exit at half normal time
        partial_exit_enabled = True,
        partial_exit_pct     = 0.75,    # exit 75% at TP1
    ),
    "IGNORE": TierRules(
        tier                 = "IGNORE",
        position_pct         = 0.00,
        sl_mult_adj          = 1.00,
        tp_mult_adj          = 1.00,
        trail_enabled        = False,
        trail_activate_pct   = 1.00,
        trail_from_peak_pct  = 1.00,
        max_bars_mult        = 0.00,
        partial_exit_enabled = False,
        partial_exit_pct     = 0.00,
    ),
}


def get_tier_rules(
    score: int,
    *,
    strong_min: int = TIER_STRONG_MIN,
    moderate_min: int = TIER_MODERATE_MIN,
    weak_min: int = TIER_WEAK_MIN,
) -> TierRules:
    return TIER_RULES[
        classify_tier(score, strong_min=strong_min, moderate_min=moderate_min, weak_min=weak_min)
    ]


# ── Adaptive threshold: regime shifts the effective entry bar ─────────────
# In a trending market the system is more permissive; in choppy/volatile more selective.

_REGIME_THRESHOLD_ADJ: dict[str, int] = {
    "TRENDING":        -5,    # more opportunity
    "NEUTRAL":          0,
    "SIDEWAYS":        +5,    # more selective
    "CHOPPY":         +10,    # very selective
    "HIGH_VOLATILITY": +8,
    "EVENT":          +15,    # nearly never trade
}


def adaptive_threshold(base: int, regime: str) -> int:
    """Return the effective minimum score for entry, adjusted by market regime."""
    return base + _REGIME_THRESHOLD_ADJ.get(regime, 0)


__all__ = [
    "TIER_MODERATE_MIN",
    "TIER_RULES",
    "TIER_STRONG_MIN",
    "TIER_WEAK_MIN",
    "TierRules",
    "adaptive_threshold",
    "classify_tier",
    "get_tier_rules",
    "tier_bounds_from_config",
]

