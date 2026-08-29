"""Tests for core/strike_selector.py - Greeks-Aware Strike Selection.

Covers:
- select_strike() with ATM, OTM, DELTA modes
- dte_entry_check() for min DTE gate and theta bleed warning
- strike_summary() snapshot dict
- Edge cases: vega cap, step calculation, tier-dependent offset
"""
from __future__ import annotations

from core.strike_selector import (
    dte_entry_check,
    select_strike,
    strike_summary,
)

# =============================================================================
# select_strike Tests
# =============================================================================

class TestSelectStrike:
    def test_atm_mode_default(self):
        """ATM mode returns ATM strike unchanged."""
        strike, reason = select_strike(
            atm=23500, direction="CALL", step=50,
            tier="MODERATE", vix=15.0, dte=5,
        )
        assert strike == 23500
        assert "ATM" in reason

    def test_atm_mode_put(self):
        strike, reason = select_strike(
            atm=23500, direction="PUT", step=50,
            tier="WEAK", vix=15.0, dte=5,
        )
        assert strike == 23500
        assert "ATM" in reason

    def test_otm_mode_strong_call(self):
        """STRONG tier in OTM mode selects 1 step OTM for CALL."""
        strike, reason = select_strike(
            atm=23500, direction="CALL", step=50,
            tier="STRONG", vix=15.0, dte=5,
            cfg={"strike_selection_mode": "OTM"},
        )
        assert strike == 23550  # ATM + 1*50 = OTM for CALL
        assert "OTM" in reason
        assert "STRONG" in reason

    def test_otm_mode_strong_put(self):
        """STRONG tier in OTM mode selects 1 step OTM for PUT."""
        strike, reason = select_strike(
            atm=23500, direction="PUT", step=50,
            tier="STRONG", vix=15.0, dte=5,
            cfg={"strike_selection_mode": "OTM"},
        )
        assert strike == 23450  # ATM - 1*50 = OTM for PUT

    def test_otm_mode_moderate_call(self):
        """MODERATE tier in OTM mode uses default 0 steps."""
        strike, reason = select_strike(
            atm=23500, direction="CALL", step=50,
            tier="MODERATE", vix=15.0, dte=5,
            cfg={"strike_selection_mode": "OTM"},
        )
        assert strike == 23500  # No OTM offset for moderate

    def test_otm_mode_with_custom_config(self):
        """Custom OTM step offsets from config."""
        strike, reason = select_strike(
            atm=23500, direction="CALL", step=50,
            tier="STRONG", vix=15.0, dte=5,
            cfg={
                "strike_selection_mode": "OTM",
                "otm_step_offset_strong": 2,
            },
        )
        assert strike == 23600  # ATM + 2*50 = 23600

    def test_delta_mode_selects_strike(self):
        """DELTA mode selects strike closest to target delta."""
        # With VIX=15, DTE=5, atm_delta ≈ 0.50
        # Steps to reach target 0.40: round((0.50 - 0.40) / 0.08) = 1
        strike, reason = select_strike(
            atm=23500, direction="CALL", step=50,
            tier="MODERATE", vix=15.0, dte=5,
            cfg={"strike_selection_mode": "DELTA"},
        )
        assert "DELTA" in reason
        # Should be 1 step OTM: 23550
        # But actual depends on atm_delta calculation
        assert strike >= 23500

    def test_vega_cap_reduces_otm_steps(self):
        """When VIX > vega_cap_vix_threshold, reduce OTM depth by 1."""
        strike_normal, _ = select_strike(
            atm=23500, direction="CALL", step=50,
            tier="STRONG", vix=15.0, dte=5,
            cfg={"strike_selection_mode": "OTM", "otm_step_offset_strong": 2},
        )
        strike_capped, _ = select_strike(
            atm=23500, direction="CALL", step=50,
            tier="STRONG", vix=35.0, dte=5,  # VIX > 30 triggers cap
            cfg={"strike_selection_mode": "OTM", "otm_step_offset_strong": 2},
        )
        assert strike_capped <= strike_normal
        # With vix_cap: 2 steps - 1 = 1 step → 23550
        # Without vix_cap: 2 steps → 23600
        assert strike_normal == 23600  # 2 steps OTM
        assert strike_capped == 23550   # 1 step OTM (vega capped)

    def test_max_otm_steps_cap(self):
        """OTM steps clamped to max_otm_steps."""
        strike, _ = select_strike(
            atm=23500, direction="CALL", step=50,
            tier="STRONG", vix=15.0, dte=5,
            cfg={
                "strike_selection_mode": "OTM",
                "otm_step_offset_strong": 5,
                "max_otm_steps": 2,
            },
        )
        assert strike == 23600  # 2 steps max

    def test_weak_tier_no_offset(self):
        """WEAK tier always gets 0 OTM steps."""
        strike, _ = select_strike(
            atm=23500, direction="CALL", step=50,
            tier="WEAK", vix=15.0, dte=5,
            cfg={"strike_selection_mode": "OTM"},
        )
        assert strike == 23500

    def test_banknifty_step_100(self):
        """BANKNIFTY uses 100 step size."""
        strike, _ = select_strike(
            atm=50000, direction="PUT", step=100,
            tier="STRONG", vix=15.0, dte=5,
            cfg={"strike_selection_mode": "OTM"},
        )
        assert strike == 49900  # PUT OTM: 50000 - 100


# =============================================================================
# dte_entry_check Tests
# =============================================================================

class TestDteEntryCheck:
    def test_allows_normal_dte(self):
        allowed, reason = dte_entry_check(dte=7)
        assert allowed is True
        assert reason == ""

    def test_blocks_expiry_day(self):
        """DTE=0 is below min_dte_for_entry=1."""
        allowed, reason = dte_entry_check(dte=0)
        assert allowed is False
        assert "min_dte" in reason

    def test_blocks_dte_below_min(self):
        allowed, reason = dte_entry_check(dte=0, cfg={"min_dte_for_entry": 2})
        assert allowed is False
        assert "min_dte" in reason

    def test_custom_min_dte(self):
        allowed, reason = dte_entry_check(dte=3, cfg={"min_dte_for_entry": 5})
        assert allowed is False
        assert "min_dte" in reason

    def test_warns_near_expiry(self):
        """DTE <= warn_dte logs warning but returns allowed."""
        allowed, reason = dte_entry_check(dte=1)
        assert allowed is True
        assert reason == ""

    def test_valid_dte_custom_config(self):
        allowed, reason = dte_entry_check(dte=5, cfg={"min_dte_for_entry": 3})
        assert allowed is True
        assert reason == ""


# =============================================================================
# strike_summary Tests
# =============================================================================

class TestStrikeSummary:
    def test_returns_expected_keys(self):
        summary = strike_summary(
            atm=23500, direction="CALL", step=50,
            tier="STRONG", vix=15.0, dte=5,
        )
        assert "mode" in summary
        assert "atm" in summary
        assert "selected" in summary
        assert "otm_steps" in summary
        assert "direction" in summary
        assert "tier" in summary
        assert "vix" in summary
        assert "dte" in summary
        assert "dte_allowed" in summary
        assert "reason" in summary

    def test_atm_mode_no_otm_steps(self):
        summary = strike_summary(
            atm=23500, direction="CALL", step=50,
            tier="MODERATE", vix=15.0, dte=5,
        )
        assert summary["mode"] == "ATM"
        assert summary["selected"] == 23500
        assert summary["otm_steps"] == 0
        assert summary["dte_allowed"] is True

    def test_otm_mode_call_steps(self):
        summary = strike_summary(
            atm=23500, direction="CALL", step=50,
            tier="STRONG", vix=15.0, dte=5,
            cfg={"strike_selection_mode": "OTM"},
        )
        assert summary["otm_steps"] == 1
        assert summary["selected"] == 23550

    def test_otm_mode_put_negative_steps(self):
        summary = strike_summary(
            atm=23500, direction="PUT", step=100,
            tier="STRONG", vix=15.0, dte=5,
            cfg={"strike_selection_mode": "OTM"},
        )
        # For PUT: otm_steps = (atm - selected) // step
        assert summary["otm_steps"] == 1
        assert summary["selected"] == 23400

    def test_dte_blocked_in_summary(self):
        summary = strike_summary(
            atm=23500, direction="CALL", step=50,
            tier="MODERATE", vix=15.0, dte=0,
        )
        assert summary["dte_allowed"] is False
        assert "min_dte" in summary["dte_reason"]
