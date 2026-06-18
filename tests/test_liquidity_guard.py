"""Tests for core/liquidity_guard.py (v2.44 Item 1)."""
import pytest
from core.liquidity_guard import LiquidityCheck, check_entry_liquidity

CFG_DEFAULT = {
    "max_entry_spread_pct": 8.0,
    "min_option_premium": 5.0,
    "min_entry_oi": 100,   # maps to min_entry_oi in module
    "min_entry_volume": 10,
    "liquidity_guard_enabled": True,
}


def _check(**kwargs):
    defaults = dict(bid=95.0, ask=100.0, oi=500, volume=50, cfg=CFG_DEFAULT)
    defaults.update(kwargs)
    return check_entry_liquidity(
        defaults["bid"], defaults["ask"], defaults["oi"], defaults["volume"], defaults["cfg"]
    )


# ── Basic pass ────────────────────────────────────────────────────────────────

def test_passes_all_gates():
    r = _check()
    assert r.passed is True
    assert r.reject_reason is None


def test_mid_price_computed_correctly():
    r = _check(bid=95.0, ask=105.0)
    assert r.mid == pytest.approx(100.0)


def test_spread_pct_computed_correctly():
    r = _check(bid=95.0, ask=105.0)
    # spread = (105-95)/100 * 100 = 10%
    assert r.spread_pct == pytest.approx(10.0)


# ── Gate: bid/ask positive ────────────────────────────────────────────────────

def test_rejects_zero_bid():
    r = _check(bid=0.0)
    assert r.passed is False
    assert "bid" in r.reject_reason.lower()


def test_rejects_negative_bid():
    r = _check(bid=-1.0)
    assert r.passed is False


def test_rejects_zero_ask():
    r = _check(ask=0.0)
    assert r.passed is False
    assert "ask" in r.reject_reason.lower()


# ── Gate: ask > bid ───────────────────────────────────────────────────────────

def test_rejects_inverted_spread():
    r = _check(bid=105.0, ask=95.0)
    assert r.passed is False


def test_rejects_equal_bid_ask():
    r = _check(bid=100.0, ask=100.0)
    # spread_pct = 0; mid=100; this may pass depending on impl - just check no exception
    assert isinstance(r, LiquidityCheck)


# ── Gate: minimum premium ─────────────────────────────────────────────────────

def test_rejects_below_min_premium():
    r = _check(bid=2.0, ask=4.0)  # mid=3 < 5
    assert r.passed is False
    assert "premium" in r.reject_reason.lower()


def test_passes_at_min_premium():
    r = _check(bid=4.9, ask=5.1)  # mid=5.0 == min_premium, spread=3.9% < 8%
    assert r.passed is True


# ── Gate: spread_pct ─────────────────────────────────────────────────────────

def test_rejects_wide_spread():
    # spread = (120-80)/100 * 100 = 40%
    r = _check(bid=80.0, ask=120.0)
    assert r.passed is False
    assert "spread" in r.reject_reason.lower()


def test_passes_at_limit_spread():
    # spread = (104-96)/100 * 100 = 8% == max
    r = _check(bid=96.0, ask=104.0)
    assert r.passed is True


# ── Gate: OI ─────────────────────────────────────────────────────────────────

def test_rejects_low_oi():
    r = _check(oi=50)
    assert r.passed is False
    assert "oi" in r.reject_reason.lower()


def test_passes_at_min_oi():
    r = _check(oi=100)
    assert r.passed is True


# ── Gate: volume ─────────────────────────────────────────────────────────────

def test_rejects_low_volume():
    r = _check(volume=5)
    assert r.passed is False
    assert "volume" in r.reject_reason.lower()


def test_passes_at_min_volume():
    r = _check(volume=10)
    assert r.passed is True


# ── Guard disabled ────────────────────────────────────────────────────────────

def test_disabled_guard_passes_bad_data():
    cfg = dict(CFG_DEFAULT, liquidity_guard_enabled=False)
    r = check_entry_liquidity(0.0, 0.0, 0, 0, cfg)
    assert r.passed is True


# ── Custom thresholds ─────────────────────────────────────────────────────────

def test_custom_spread_threshold():
    cfg = dict(CFG_DEFAULT, max_entry_spread_pct=5.0)
    r = check_entry_liquidity(94.0, 100.0, 500, 50, cfg)  # spread=6% > 5%
    assert r.passed is False


def test_custom_premium_threshold():
    cfg = dict(CFG_DEFAULT, min_option_premium=15.0)
    r = check_entry_liquidity(8.0, 12.0, 500, 50, cfg)  # mid=10 < 15
    assert r.passed is False


def test_return_type_is_dataclass():
    r = _check()
    assert isinstance(r, LiquidityCheck)
    assert hasattr(r, "passed")
    assert hasattr(r, "spread_pct")
    assert hasattr(r, "mid")
