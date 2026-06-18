"""
Tests for Phase 4 - Greeks-Aware Strike Selector (core/strike_selector.py).

Covers:
  - ATM mode: always returns ATM (backward compatible)
  - OTM mode: tier-based step offset, correct CALL/PUT direction
  - OTM mode: max_otm_steps cap
  - DELTA mode: steps computed from delta approximation
  - DELTA mode: falls back to ATM when target delta >= atm_delta
  - Vega cap: reduces OTM depth when VIX > threshold
  - dte_entry_check: blocks when DTE < min_dte_for_entry
  - dte_entry_check: allows (with warning) when DTE <= warn_dte
  - strike_summary: returns all expected keys
"""
from __future__ import annotations

from core.strike_selector import (
    _apply_vega_cap,
    _otm_steps_for_delta,
    _otm_steps_for_tier,
    dte_entry_check,
    select_strike,
    strike_summary,
)

# ── Common fixtures ───────────────────────────────────────────────────────────

ATM   = 22500
STEP  = 50
VIX   = 15.0
DTE   = 3


# ── Class 1: ATM mode (default) ───────────────────────────────────────────────


class TestAtmMode:
    def test_default_mode_returns_atm_call(self):
        strike, tag = select_strike(ATM, "CALL", STEP, "STRONG", VIX, DTE)
        assert strike == ATM

    def test_default_mode_returns_atm_put(self):
        strike, tag = select_strike(ATM, "PUT", STEP, "STRONG", VIX, DTE)
        assert strike == ATM

    def test_explicit_atm_mode_returns_atm(self):
        cfg = {"strike_selection_mode": "ATM"}
        strike, _ = select_strike(ATM, "CALL", STEP, "STRONG", VIX, DTE, cfg)
        assert strike == ATM

    def test_atm_tag_contains_atm_string(self):
        _, tag = select_strike(ATM, "CALL", STEP, "MODERATE", VIX, DTE)
        assert "ATM" in tag.upper()

    def test_atm_mode_ignores_tier(self):
        for tier in ("STRONG", "MODERATE", "WEAK", "IGNORE"):
            strike, _ = select_strike(ATM, "CALL", STEP, tier, VIX, DTE)
            assert strike == ATM, f"ATM mode returned non-ATM for tier={tier}"


# ── Class 2: OTM mode - direction ────────────────────────────────────────────


class TestOtmModeDirection:
    def test_strong_call_one_step_otm(self):
        cfg = {"strike_selection_mode": "OTM", "otm_step_offset_strong": 1}
        strike, _ = select_strike(ATM, "CALL", STEP, "STRONG", VIX, DTE, cfg)
        assert strike == ATM + STEP  # CALL OTM = higher strike

    def test_strong_put_one_step_otm(self):
        cfg = {"strike_selection_mode": "OTM", "otm_step_offset_strong": 1}
        strike, _ = select_strike(ATM, "PUT", STEP, "STRONG", VIX, DTE, cfg)
        assert strike == ATM - STEP  # PUT OTM = lower strike

    def test_moderate_default_is_atm(self):
        cfg = {"strike_selection_mode": "OTM"}
        strike, _ = select_strike(ATM, "CALL", STEP, "MODERATE", VIX, DTE, cfg)
        assert strike == ATM  # default moderate offset = 0

    def test_weak_default_is_atm(self):
        cfg = {"strike_selection_mode": "OTM"}
        strike, _ = select_strike(ATM, "CALL", STEP, "WEAK", VIX, DTE, cfg)
        assert strike == ATM

    def test_two_step_otm_call(self):
        cfg = {"strike_selection_mode": "OTM", "otm_step_offset_strong": 2}
        strike, _ = select_strike(ATM, "CALL", STEP, "STRONG", VIX, DTE, cfg)
        assert strike == ATM + 2 * STEP

    def test_two_step_otm_put(self):
        cfg = {"strike_selection_mode": "OTM", "otm_step_offset_strong": 2}
        strike, _ = select_strike(ATM, "PUT", STEP, "STRONG", VIX, DTE, cfg)
        assert strike == ATM - 2 * STEP


class TestOtmModeCap:
    def test_max_otm_steps_caps_offset(self):
        cfg = {
            "strike_selection_mode": "OTM",
            "otm_step_offset_strong": 5,
            "max_otm_steps": 2,
        }
        strike, _ = select_strike(ATM, "CALL", STEP, "STRONG", VIX, DTE, cfg)
        assert strike == ATM + 2 * STEP  # capped at 2

    def test_zero_max_steps_returns_atm(self):
        cfg = {
            "strike_selection_mode": "OTM",
            "otm_step_offset_strong": 3,
            "max_otm_steps": 0,
        }
        strike, _ = select_strike(ATM, "CALL", STEP, "STRONG", VIX, DTE, cfg)
        assert strike == ATM


# ── Class 3: OTM tier helpers ─────────────────────────────────────────────────


class TestOtmStepsForTier:
    def test_strong_default(self):
        assert _otm_steps_for_tier("STRONG", {}) == 1

    def test_moderate_default(self):
        assert _otm_steps_for_tier("MODERATE", {}) == 0

    def test_weak_default(self):
        assert _otm_steps_for_tier("WEAK", {}) == 0

    def test_unknown_tier_uses_global(self):
        assert _otm_steps_for_tier("IGNORE", {}) == 0

    def test_config_override_strong(self):
        assert _otm_steps_for_tier("STRONG", {"otm_step_offset_strong": 2}) == 2

    def test_config_override_moderate(self):
        assert _otm_steps_for_tier("MODERATE", {"otm_step_offset_moderate": 1}) == 1


# ── Class 4: DELTA mode ───────────────────────────────────────────────────────


class TestDeltaMode:
    def test_delta_mode_selects_otm_call(self):
        # atm_delta(vix=15, dte=3) ≈ 0.50; target=0.40; delta_per_step=0.08 → ~1 step OTM
        cfg = {
            "strike_selection_mode": "DELTA",
            "strike_target_delta": 0.40,
            "delta_per_step": 0.10,
        }
        strike, tag = select_strike(ATM, "CALL", STEP, "STRONG", 15.0, 3, cfg)
        # With atm_delta≈0.50, target=0.40, per_step=0.10 → 1 step OTM
        assert strike == ATM + STEP
        assert "DELTA" in tag.upper()

    def test_delta_mode_target_equals_atm_returns_atm(self):
        # target_delta ≥ atm_delta → 0 steps → ATM
        cfg = {
            "strike_selection_mode": "DELTA",
            "strike_target_delta": 0.55,   # above atm_delta
            "delta_per_step": 0.08,
        }
        strike, _ = select_strike(ATM, "CALL", STEP, "STRONG", 15.0, 3, cfg)
        assert strike == ATM

    def test_delta_steps_formula(self):
        # atm_delta=0.50, target=0.34, per_step=0.08 → round((0.50-0.34)/0.08)=2
        steps = _otm_steps_for_delta(0.50, 0.34, 0.08, 10)
        assert steps == 2

    def test_delta_steps_capped_by_max(self):
        steps = _otm_steps_for_delta(0.50, 0.10, 0.08, 2)
        assert steps == 2  # would be 5, capped at 2

    def test_delta_steps_zero_when_target_above_atm(self):
        steps = _otm_steps_for_delta(0.45, 0.50, 0.08, 3)
        assert steps == 0


# ── Class 5: Vega cap ────────────────────────────────────────────────────────


class TestVegaCap:
    def test_vega_cap_reduces_steps_when_high_vix(self):
        # 2 steps, VIX=35 > threshold=30 → reduced to 1
        steps = _apply_vega_cap(2, 35.0, {"vega_cap_vix_threshold": 30.0})
        assert steps == 1

    def test_vega_cap_no_change_when_low_vix(self):
        steps = _apply_vega_cap(2, 20.0, {"vega_cap_vix_threshold": 30.0})
        assert steps == 2

    def test_vega_cap_zero_steps_stays_zero(self):
        # Already ATM - no reduction possible
        steps = _apply_vega_cap(0, 35.0, {"vega_cap_vix_threshold": 30.0})
        assert steps == 0

    def test_vega_cap_applied_in_otm_mode(self):
        cfg = {
            "strike_selection_mode": "OTM",
            "otm_step_offset_strong": 2,
            "vega_cap_vix_threshold": 25.0,
        }
        # VIX=30 > threshold=25 → steps reduced from 2 to 1
        strike, _ = select_strike(ATM, "CALL", STEP, "STRONG", 30.0, DTE, cfg)
        assert strike == ATM + STEP  # 1 step, not 2


# ── Class 6: DTE entry check ─────────────────────────────────────────────────


class TestDteEntryCheck:
    def test_dte_above_min_is_allowed(self):
        ok, reason = dte_entry_check(3, {"min_dte_for_entry": 1})
        assert ok is True
        assert reason == ""

    def test_dte_equal_min_is_allowed(self):
        ok, reason = dte_entry_check(1, {"min_dte_for_entry": 1})
        assert ok is True

    def test_dte_zero_below_min_is_blocked(self):
        ok, reason = dte_entry_check(0, {"min_dte_for_entry": 1})
        assert ok is False
        assert "DTE=0" in reason

    def test_dte_default_min_is_1(self):
        # Default min_dte_for_entry = 1
        ok, _ = dte_entry_check(1)
        assert ok is True
        ok2, _ = dte_entry_check(0)
        assert ok2 is False

    def test_warn_dte_does_not_block(self):
        # DTE=2, warn_dte=2 → warning issued but entry allowed
        ok, reason = dte_entry_check(2, {"min_dte_for_entry": 1, "theta_bleed_warn_dte": 2})
        assert ok is True
        assert reason == ""


# ── Class 7: strike_summary ───────────────────────────────────────────────────


class TestStrikeSummary:
    def test_summary_has_required_keys(self):
        summary = strike_summary(ATM, "CALL", STEP, "STRONG", VIX, DTE)
        for key in ("mode", "atm", "selected", "otm_steps", "direction", "tier",
                    "vix", "dte", "dte_allowed", "reason", "dte_reason"):
            assert key in summary, f"Missing key: {key}"

    def test_summary_atm_mode_zero_otm_steps(self):
        summary = strike_summary(ATM, "CALL", STEP, "STRONG", VIX, DTE)
        assert summary["atm"] == ATM
        assert summary["selected"] == ATM
        assert summary["otm_steps"] == 0

    def test_summary_otm_mode_counts_steps(self):
        cfg = {"strike_selection_mode": "OTM", "otm_step_offset_strong": 2}
        summary = strike_summary(ATM, "CALL", STEP, "STRONG", VIX, DTE, cfg)
        assert summary["otm_steps"] == 2
        assert summary["selected"] == ATM + 2 * STEP

    def test_summary_dte_blocked_when_below_min(self):
        cfg = {"min_dte_for_entry": 2}
        summary = strike_summary(ATM, "CALL", STEP, "STRONG", VIX, 1, cfg)
        assert summary["dte_allowed"] is False
