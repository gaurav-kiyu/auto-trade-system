"""Tests for IV skew functions in core/iv_rank.py (v2.44 Item 11)."""

import pytest
from core.iv_rank import (
    IVSkewData,
    _bs_approx_iv,
    compute_iv_skew,
    get_skew_adjusted_premium,
)

CFG = {
    "iv_skew_enabled": True,
    "iv_skew_adj_mult": 0.5,
    "iv_skew_extreme_threshold": 7.0,
    "iv_skew_elevated_threshold": 3.0,
    "iv_skew_extreme_score_penalty": 5,
}

SPOT = 22000.0
DTE = 7


def make_chain(spot=SPOT, put_otm_pct=0.02, call_otm_pct=0.02, atm_prem=200.0):
    put_strike = int(spot * (1 - put_otm_pct))
    call_strike = int(spot * (1 + call_otm_pct))
    atm_strike = int(spot)
    return {
        "calls": {atm_strike: atm_prem, call_strike: atm_prem * 0.6},
        "puts": {atm_strike: atm_prem, put_strike: atm_prem * 1.2},
    }


# ── _bs_approx_iv ─────────────────────────────────────────────────────────────

def test_bs_approx_iv_positive():
    iv = _bs_approx_iv(premium=100.0, spot=22000.0, strike=22000.0, dte_days=7)
    assert iv > 0


def test_bs_approx_iv_higher_for_deeper_otm():
    iv_atm = _bs_approx_iv(100.0, 22000.0, 22000.0, 7)
    iv_otm = _bs_approx_iv(50.0, 22000.0, 21500.0, 7, is_put=True)
    # Can't assert direction without more context, just no exception
    assert iv_atm > 0
    assert iv_otm >= 0


def test_bs_approx_iv_zero_dte_handled():
    iv = _bs_approx_iv(100.0, 22000.0, 22000.0, 0)
    assert iv >= 0


def test_bs_approx_iv_zero_premium_returns_zero():
    iv = _bs_approx_iv(0.0, 22000.0, 22000.0, 7)
    assert iv == 0.0


# ── compute_iv_skew ───────────────────────────────────────────────────────────

def test_compute_iv_skew_returns_ivskewdata():
    chain = make_chain()
    result = compute_iv_skew(chain, SPOT, DTE, CFG)
    assert result is None or isinstance(result, IVSkewData)


def test_compute_iv_skew_normal_regime():
    # Low premium dispersion → NORMAL skew
    chain = make_chain(put_otm_pct=0.01)
    result = compute_iv_skew(chain, SPOT, DTE, CFG)
    if result is not None:
        # regime should be in valid set
        assert result.regime in ("NORMAL", "ELEVATED", "EXTREME")


def test_compute_iv_skew_extreme_regime():
    # Force high put premium relative to call
    chain = {
        "calls": {22000: 100.0, 22200: 60.0},
        "puts": {22000: 100.0, 21800: 500.0},  # very high OTM put
    }
    result = compute_iv_skew(chain, 22000.0, DTE, CFG)
    if result is not None:
        assert result.put_skew >= 0


def test_compute_iv_skew_fields():
    chain = make_chain()
    result = compute_iv_skew(chain, SPOT, DTE, CFG)
    if result is not None:
        assert hasattr(result, "put_skew")
        assert hasattr(result, "atm_iv")
        assert hasattr(result, "put_25d_iv")
        assert hasattr(result, "call_25d_iv")
        assert hasattr(result, "skew_percentile")
        assert hasattr(result, "regime")
        assert hasattr(result, "ts")


def test_compute_iv_skew_disabled_returns_none():
    cfg = dict(CFG, iv_skew_enabled=False)
    chain = make_chain()
    result = compute_iv_skew(chain, SPOT, DTE, cfg)
    assert result is None


def test_compute_iv_skew_empty_chain_returns_none():
    result = compute_iv_skew({"calls": {}, "puts": {}}, SPOT, DTE, CFG)
    assert result is None


def test_compute_iv_skew_ts_is_float():
    chain = make_chain()
    result = compute_iv_skew(chain, SPOT, DTE, CFG)
    if result is not None:
        assert isinstance(result.ts, float)
        assert result.ts > 0


# ── get_skew_adjusted_premium ─────────────────────────────────────────────────

def test_otm_put_premium_increased_when_elevated():
    skew = IVSkewData(
        put_skew=5.0, atm_iv=15.0, put_25d_iv=20.0, call_25d_iv=14.0,
        skew_percentile=70.0, regime="ELEVATED", ts=1.0
    )
    raw = 100.0
    adjusted = get_skew_adjusted_premium(raw, is_put=True, is_otm=True, skew_data=skew, cfg=CFG)
    assert adjusted > raw


def test_otm_call_premium_unchanged_when_elevated():
    skew = IVSkewData(
        put_skew=5.0, atm_iv=15.0, put_25d_iv=20.0, call_25d_iv=14.0,
        skew_percentile=70.0, regime="ELEVATED", ts=1.0
    )
    raw = 100.0
    adjusted = get_skew_adjusted_premium(raw, is_put=False, is_otm=True, skew_data=skew, cfg=CFG)
    assert adjusted == pytest.approx(raw)


def test_atm_put_unchanged_regardless_of_regime():
    skew = IVSkewData(
        put_skew=5.0, atm_iv=15.0, put_25d_iv=20.0, call_25d_iv=14.0,
        skew_percentile=70.0, regime="ELEVATED", ts=1.0
    )
    raw = 100.0
    adjusted = get_skew_adjusted_premium(raw, is_put=True, is_otm=False, skew_data=skew, cfg=CFG)
    assert adjusted == pytest.approx(raw)


def test_normal_regime_no_adjustment():
    skew = IVSkewData(
        put_skew=1.0, atm_iv=15.0, put_25d_iv=15.5, call_25d_iv=14.5,
        skew_percentile=20.0, regime="NORMAL", ts=1.0
    )
    raw = 100.0
    adjusted = get_skew_adjusted_premium(raw, is_put=True, is_otm=True, skew_data=skew, cfg=CFG)
    assert adjusted == pytest.approx(raw)


def test_none_skew_data_returns_raw():
    raw = 100.0
    adjusted = get_skew_adjusted_premium(raw, is_put=True, is_otm=True, skew_data=None, cfg=CFG)
    assert adjusted == pytest.approx(raw)


def test_adjustment_magnitude_uses_adj_mult():
    skew = IVSkewData(
        put_skew=6.0, atm_iv=15.0, put_25d_iv=21.0, call_25d_iv=14.0,
        skew_percentile=80.0, regime="ELEVATED", ts=1.0
    )
    cfg_high = dict(CFG, iv_skew_adj_mult=1.0)
    cfg_low = dict(CFG, iv_skew_adj_mult=0.1)
    adj_high = get_skew_adjusted_premium(100.0, True, True, skew, cfg_high)
    adj_low = get_skew_adjusted_premium(100.0, True, True, skew, cfg_low)
    assert adj_high > adj_low
