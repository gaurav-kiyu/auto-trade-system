"""Tests for core/gex_analyzer.py (v2.45 Item 3)."""
import math

from core.gex_analyzer import GEXResult, _bs_gamma, _phi, compute_gex, get_gex_score_adj

# ── Math helpers ──────────────────────────────────────────────────────────────

def test_phi_at_zero():
    # Normal PDF at 0 = 1/sqrt(2π)
    assert abs(_phi(0.0) - 1.0 / math.sqrt(2 * math.pi)) < 1e-10


def test_phi_symmetry():
    assert abs(_phi(1.0) - _phi(-1.0)) < 1e-10


def test_bs_gamma_atm_positive():
    gamma = _bs_gamma(22000, 22000, 0.15, 7/365)
    assert gamma > 0


def test_bs_gamma_zero_inputs():
    assert _bs_gamma(0, 22000, 0.15, 7/365) == 0.0
    assert _bs_gamma(22000, 0, 0.15, 7/365) == 0.0
    assert _bs_gamma(22000, 22000, 0, 7/365) == 0.0
    assert _bs_gamma(22000, 22000, 0.15, 0) == 0.0


# ── compute_gex ───────────────────────────────────────────────────────────────

def _make_chain(spot=22000, call_oi=100000, put_oi=80000):
    k = spot
    return {
        "calls": {k: {"oi": call_oi, "premium": 200.0}, k+200: {"oi": 50000, "premium": 80.0}},
        "puts":  {k: {"oi": put_oi,  "premium": 180.0}, k-200: {"oi": 30000, "premium": 90.0}},
    }


def test_disabled_returns_none():
    assert compute_gex(_make_chain(), 22000.0, {"gex_enabled": False}) is None


def test_none_chain_returns_none():
    assert compute_gex(None, 22000.0, {"gex_enabled": True}) is None


def test_zero_spot_returns_none():
    assert compute_gex(_make_chain(), 0.0, {"gex_enabled": True}) is None


def test_long_gamma_when_calls_dominate():
    chain = _make_chain(call_oi=200000, put_oi=50000)
    result = compute_gex(chain, 22000.0, {"gex_enabled": True, "gex_lot_size": 50, "gex_dte": 7, "gex_vix_proxy": 15.0})
    assert result is not None
    assert result.regime == "LONG_GAMMA"
    assert result.net_gex > 0


def test_short_gamma_when_puts_dominate():
    chain = _make_chain(call_oi=50000, put_oi=200000)
    result = compute_gex(chain, 22000.0, {"gex_enabled": True, "gex_lot_size": 50, "gex_dte": 7, "gex_vix_proxy": 15.0})
    assert result is not None
    assert result.regime == "SHORT_GAMMA"
    assert result.net_gex < 0


def test_result_has_top_strikes():
    chain = _make_chain()
    result = compute_gex(chain, 22000.0, {"gex_enabled": True, "gex_lot_size": 50, "gex_dte": 7, "gex_vix_proxy": 15.0})
    assert result is not None
    assert isinstance(result.top_strikes, list)
    assert len(result.top_strikes) <= 5


def test_empty_chain_returns_none():
    result = compute_gex({"calls": {}, "puts": {}}, 22000.0, {"gex_enabled": True})
    assert result is None


# ── get_gex_score_adj ─────────────────────────────────────────────────────────

def test_score_adj_disabled():
    r = GEXResult(net_gex=1000, gamma_flip=0, regime="LONG_GAMMA")
    assert get_gex_score_adj(r, "CALL", {"gex_enabled": False}) == 0


def test_score_adj_none_result():
    assert get_gex_score_adj(None, "CALL", {"gex_enabled": True}) == 0


def test_score_adj_long_gamma_negative():
    r = GEXResult(net_gex=1000, gamma_flip=0, regime="LONG_GAMMA")
    adj = get_gex_score_adj(r, "CALL", {"gex_enabled": True, "gex_long_gamma_adj": -5})
    assert adj == -5


def test_score_adj_short_gamma_positive():
    r = GEXResult(net_gex=-1000, gamma_flip=0, regime="SHORT_GAMMA")
    adj = get_gex_score_adj(r, "CALL", {"gex_enabled": True, "gex_short_gamma_adj": 5})
    assert adj == 5


def test_gamma_flip_in_result():
    chain = {
        "calls": {22000: {"oi": 200000, "premium": 200.0}, 22200: {"oi": 10000, "premium": 50.0}},
        "puts":  {22000: {"oi": 10000,  "premium": 180.0}, 21800: {"oi": 200000, "premium": 90.0}},
    }
    result = compute_gex(chain, 22000.0, {"gex_enabled": True, "gex_lot_size": 50, "gex_dte": 7, "gex_vix_proxy": 15.0})
    assert result is not None
    assert isinstance(result.gamma_flip, float)
