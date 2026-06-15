"""Tests for core.tier_engine — tiered signal classification and per-tier execution rules."""

from __future__ import annotations

from core.tier_engine import (
    TIER_RULES,
    TIER_STRONG_MIN,
    TIER_MODERATE_MIN,
    TIER_WEAK_MIN,
    TierRules,
    adaptive_threshold,
    classify_tier,
    get_tier_rules,
)


# ── Constants ─────────────────────────────────────────────────────────────

def test_tier_constants() -> None:
    assert TIER_STRONG_MIN == 80
    assert TIER_MODERATE_MIN == 70
    assert TIER_WEAK_MIN == 60


# ── classify_tier ─────────────────────────────────────────────────────────

def test_classify_tier_strong() -> None:
    assert classify_tier(85) == "STRONG"
    assert classify_tier(80) == "STRONG"


def test_classify_tier_moderate() -> None:
    assert classify_tier(75) == "MODERATE"
    assert classify_tier(70) == "MODERATE"


def test_classify_tier_weak() -> None:
    assert classify_tier(65) == "WEAK"
    assert classify_tier(60) == "WEAK"


def test_classify_tier_ignore() -> None:
    assert classify_tier(55) == "IGNORE"
    assert classify_tier(0) == "IGNORE"
    assert classify_tier(59) == "IGNORE"


def test_classify_tier_boundary() -> None:
    assert classify_tier(79) == "MODERATE"
    assert classify_tier(80) == "STRONG"
    assert classify_tier(69) == "WEAK"
    assert classify_tier(70) == "MODERATE"


# ── get_tier_rules ───────────────────────────────────────────────────────

def test_get_tier_rules_strong() -> None:
    rules = get_tier_rules(85)
    assert isinstance(rules, TierRules)
    assert rules.tier == "STRONG"
    assert rules.position_pct == 1.0
    assert rules.sl_mult_adj == 1.0
    assert rules.trail_enabled is True


def test_get_tier_rules_moderate() -> None:
    rules = get_tier_rules(75)
    assert rules.tier == "MODERATE"
    assert rules.position_pct == 0.60
    assert rules.partial_exit_enabled is True
    assert rules.partial_exit_pct == 0.50


def test_get_tier_rules_weak() -> None:
    rules = get_tier_rules(65)
    assert rules.tier == "WEAK"
    assert rules.position_pct == 0.30
    assert rules.trail_enabled is False
    assert rules.partial_exit_enabled is True
    assert rules.partial_exit_pct == 0.75
    assert rules.sl_mult_adj == 0.80
    assert rules.max_bars_mult == 0.50


def test_get_tier_rules_ignore() -> None:
    rules = get_tier_rules(55)
    assert rules.tier == "IGNORE"
    assert rules.position_pct == 0.0
    assert rules.trail_enabled is False


# ── TierRules dataclass ──────────────────────────────────────────────────

def test_tier_rules_creation() -> None:
    rules = TierRules(
        tier="TEST", position_pct=0.5,
        sl_mult_adj=0.9, tp_mult_adj=0.85,
        trail_enabled=True, trail_activate_pct=0.2, trail_from_peak_pct=0.15,
        max_bars_mult=0.75, partial_exit_enabled=True, partial_exit_pct=0.5,
    )
    assert rules.tier == "TEST"
    assert rules.trail_activate_pct == 0.2


def test_tier_rules_frozen() -> None:
    rules = get_tier_rules(85)
    import pytest
    with pytest.raises(AttributeError):
        rules.tier = "MODIFIED"  # type: ignore[misc]


# ── TIER_RULES dict ──────────────────────────────────────────────────────

def test_tier_rules_all_tiers_present() -> None:
    assert "STRONG" in TIER_RULES
    assert "MODERATE" in TIER_RULES
    assert "WEAK" in TIER_RULES
    assert "IGNORE" in TIER_RULES


def test_tier_rules_strong_values() -> None:
    rules = TIER_RULES["STRONG"]
    assert rules.position_pct == 1.00
    assert rules.sl_mult_adj == 1.00
    assert rules.tp_mult_adj == 1.00
    assert rules.trail_enabled is True
    assert rules.trail_activate_pct == 0.30


def test_tier_rules_moderate_values() -> None:
    rules = TIER_RULES["MODERATE"]
    assert rules.position_pct == 0.60
    assert rules.sl_mult_adj == 0.90
    assert rules.tp_mult_adj == 0.85
    assert rules.partial_exit_enabled is True
    assert rules.partial_exit_pct == 0.50


def test_tier_rules_weak_values() -> None:
    rules = TIER_RULES["WEAK"]
    assert rules.position_pct == 0.30
    assert rules.sl_mult_adj == 0.80
    assert rules.tp_mult_adj == 0.65
    assert rules.trail_enabled is False
    assert rules.max_bars_mult == 0.50


def test_tier_rules_ignore_values() -> None:
    rules = TIER_RULES["IGNORE"]
    assert rules.position_pct == 0.0
    assert rules.max_bars_mult == 0.0


# ── adaptive_threshold ───────────────────────────────────────────────────

def test_adaptive_threshold_neutral() -> None:
    assert adaptive_threshold(65, "NEUTRAL") == 65


def test_adaptive_threshold_trending() -> None:
    assert adaptive_threshold(65, "TRENDING") == 60
    assert adaptive_threshold(75, "TRENDING") == 70


def test_adaptive_threshold_choppy() -> None:
    assert adaptive_threshold(65, "CHOPPY") == 75
    assert adaptive_threshold(70, "CHOPPY") == 80


def test_adaptive_threshold_sideways() -> None:
    assert adaptive_threshold(65, "SIDEWAYS") == 70


def test_adaptive_threshold_event() -> None:
    assert adaptive_threshold(65, "EVENT") == 80


def test_adaptive_threshold_high_volatility() -> None:
    assert adaptive_threshold(65, "HIGH_VOLATILITY") == 73


def test_adaptive_threshold_unknown_regime() -> None:
    assert adaptive_threshold(65, "UNKNOWN") == 65
