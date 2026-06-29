"""Tests for core/gex_analyzer.py - Gamma Exposure Analyzer.

Covers:
- _phi() std normal PDF helper
- _bs_gamma() Black-Scholes gamma computation
- StrikeGEX and GEXResult dataclasses
- compute_gex() with various chains, disabled, empty
- get_gex_score_adj() for LONG/SHORT gamma
"""
from __future__ import annotations

import pytest
from core.gex_analyzer import (
    GEXResult,
    StrikeGEX,
    _bs_gamma,
    _phi,
    compute_gex,
    get_gex_score_adj,
)


class TestPhi:
    """_phi() standard normal PDF."""

    def test_phi_at_zero(self):
        # φ(0) = 1/√(2π) ≈ 0.3989
        val = _phi(0.0)
        assert val == pytest.approx(0.3989, abs=0.001)

    def test_phi_symmetric(self):
        assert _phi(1.0) == pytest.approx(_phi(-1.0), abs=0.0001)

    def test_phi_decays(self):
        assert _phi(3.0) < _phi(0.0)


class TestBsGamma:
    """_bs_gamma() Black-Scholes gamma."""

    def test_zero_for_invalid_inputs(self):
        assert _bs_gamma(0.0, 100.0, 0.2, 0.1) == 0.0
        assert _bs_gamma(100.0, 0.0, 0.2, 0.1) == 0.0
        assert _bs_gamma(100.0, 100.0, 0.0, 0.1) == 0.0
        assert _bs_gamma(100.0, 100.0, 0.2, 0.0) == 0.0

    def test_positive_gamma_atm(self):
        gamma = _bs_gamma(100.0, 100.0, 0.2, 0.25)
        assert gamma > 0.0

    def test_gamma_higher_near_expiry(self):
        gamma_long = _bs_gamma(100.0, 100.0, 0.2, 0.5)
        gamma_short = _bs_gamma(100.0, 100.0, 0.2, 0.05)
        assert gamma_short > gamma_long  # Gamma increases near expiry

    def test_gamma_higher_lower_vol(self):
        gamma_low_vol = _bs_gamma(100.0, 100.0, 0.1, 0.25)
        gamma_high_vol = _bs_gamma(100.0, 100.0, 0.4, 0.25)
        assert gamma_low_vol > gamma_high_vol


class TestStrikeGEX:
    """StrikeGEX dataclass."""

    def test_fields(self):
        sg = StrikeGEX(strike=23500, gex=15000.5)
        assert sg.strike == 23500
        assert sg.gex == 15000.5


class TestGEXResult:
    """GEXResult dataclass."""

    def test_defaults(self):
        result = GEXResult(net_gex=100000.0, gamma_flip=23600.0, regime="LONG_GAMMA")
        assert result.net_gex == 100000.0
        assert result.gamma_flip == 23600.0
        assert result.regime == "LONG_GAMMA"
        assert result.top_strikes == []

    def test_with_strikes(self):
        sg = StrikeGEX(strike=23500, gex=5000.0)
        result = GEXResult(net_gex=5000.0, gamma_flip=0.0, regime="SHORT_GAMMA", top_strikes=[sg])
        assert len(result.top_strikes) == 1


class TestComputeGEX:
    """compute_gex()."""

    def test_disabled_returns_none(self):
        result = compute_gex({"calls": {}, "puts": {}}, 23500.0, {"gex_enabled": False})
        assert result is None

    def test_none_chain_returns_none(self):
        result = compute_gex(None, 23500.0, {"gex_enabled": True})
        assert result is None

    def test_empty_chain_returns_none(self):
        result = compute_gex({"calls": {}, "puts": {}}, 23500.0, {"gex_enabled": True})
        assert result is None

    def test_zero_spot(self):
        chain = {"calls": {23500: {"oi": 1000, "premium": 150}}, "puts": {23500: {"oi": 500, "premium": 200}}}
        result = compute_gex(chain, 0.0, {"gex_enabled": True})
        assert result is None

    def test_computes_gex_with_oi(self):
        chain = {
            "calls": {23500: {"oi": 1000, "premium": 150}},
            "puts": {23500: {"oi": 500, "premium": 200}},
        }
        result = compute_gex(chain, 23500.0, {"gex_enabled": True})
        assert result is not None
        assert isinstance(result.net_gex, float)
        assert isinstance(result.gamma_flip, float)
        assert result.regime in ("LONG_GAMMA", "SHORT_GAMMA")
        assert len(result.top_strikes) == 1

    def test_short_gamma_regime(self):
        # More put OI -> negative net GEX
        chain = {
            "calls": {23500: {"oi": 100, "premium": 150}},
            "puts": {23500: {"oi": 5000, "premium": 200}},
        }
        result = compute_gex(chain, 23500.0, {"gex_enabled": True})
        assert result is not None
        assert result.regime == "SHORT_GAMMA"

    def test_simplified_chain_no_oi(self):
        # Simplified {strike: premium} format has no OI -> 0 gex
        chain = {
            "calls": {23500: 150.0},
            "puts": {23500: 200.0},
        }
        result = compute_gex(chain, 23500.0, {"gex_enabled": True})
        assert result is not None
        # With no OI, all gex values are 0
        assert result.regime == "LONG_GAMMA"  # net_gex = 0 >= 0

    def test_custom_config(self):
        chain = {
            "calls": {23500: {"oi": 1000, "premium": 150}},
            "puts": {23500: {"oi": 500, "premium": 200}},
        }
        cfg = {"gex_enabled": True, "gex_lot_size": 75, "gex_dte": 14, "gex_vix_proxy": 20.0}
        result = compute_gex(chain, 23500.0, cfg)
        assert result is not None


class TestGetGEXScoreAdj:
    """get_gex_score_adj()."""

    def test_disabled_returns_zero(self):
        result = GEXResult(net_gex=1000.0, gamma_flip=0.0, regime="LONG_GAMMA")
        assert get_gex_score_adj(result, "CALL", {"gex_enabled": False}) == 0

    def test_none_result_returns_zero(self):
        assert get_gex_score_adj(None, "CALL", {"gex_enabled": True}) == 0

    def test_long_gamma_penalty(self):
        result = GEXResult(net_gex=1000.0, gamma_flip=0.0, regime="LONG_GAMMA")
        cfg = {"gex_enabled": True, "gex_long_gamma_adj": -5, "gex_short_gamma_adj": 5}
        assert get_gex_score_adj(result, "CALL", cfg) == -5

    def test_short_gamma_bonus(self):
        result = GEXResult(net_gex=-1000.0, gamma_flip=0.0, regime="SHORT_GAMMA")
        cfg = {"gex_enabled": True, "gex_long_gamma_adj": -5, "gex_short_gamma_adj": 5}
        assert get_gex_score_adj(result, "PUT", cfg) == 5

    def test_custom_adjustments(self):
        result = GEXResult(net_gex=-1000.0, gamma_flip=0.0, regime="SHORT_GAMMA")
        cfg = {"gex_enabled": True, "gex_long_gamma_adj": -3, "gex_short_gamma_adj": 3}
        assert get_gex_score_adj(result, "CALL", cfg) == 3
