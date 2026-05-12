"""Tests for core/limit_order_engine.py (v2.45 Item 12)."""
import pytest
from core.limit_order_engine import LimitOrderResult, compute_limit_price, simulate_paper_fill


def _cfg(**kw):
    base = {
        "limit_order_enabled": True,
        "limit_order_mode": "ADAPTIVE",
        "limit_step_pct": 0.05,
        "limit_step_interval_secs": 5,
        "limit_timeout_secs": 30,
    }
    base.update(kw)
    return base


# ── compute_limit_price ───────────────────────────────────────────────────────

def test_aggressive_price_near_ask():
    price = compute_limit_price(bid=200.0, ask=210.0, mode="AGGRESSIVE")
    # 200 + (210-200) × 0.70 = 207.0
    assert abs(price - 207.0) < 0.01


def test_passive_price_near_bid():
    price = compute_limit_price(bid=200.0, ask=210.0, mode="PASSIVE")
    # 200 + (210-200) × 0.30 = 203.0
    assert abs(price - 203.0) < 0.01


def test_adaptive_at_zero_elapsed_is_passive():
    price = compute_limit_price(bid=200.0, ask=210.0, mode="ADAPTIVE", elapsed_secs=0.0, cfg=_cfg())
    # 0 steps → frac=0.30 → 203.0
    assert abs(price - 203.0) < 0.01


def test_adaptive_steps_toward_ask():
    price_0 = compute_limit_price(bid=200.0, ask=210.0, mode="ADAPTIVE", elapsed_secs=0.0, cfg=_cfg())
    price_5 = compute_limit_price(bid=200.0, ask=210.0, mode="ADAPTIVE", elapsed_secs=5.0, cfg=_cfg())
    assert price_5 > price_0


def test_adaptive_capped_at_ask():
    price = compute_limit_price(bid=200.0, ask=210.0, mode="ADAPTIVE", elapsed_secs=300.0, cfg=_cfg())
    assert price <= 210.0


def test_invalid_mode_defaults_to_adaptive():
    price = compute_limit_price(bid=200.0, ask=210.0, mode="INVALID", elapsed_secs=0.0, cfg=_cfg())
    assert 200.0 <= price <= 210.0


def test_zero_spread_returns_bid():
    price = compute_limit_price(bid=200.0, ask=200.0, mode="AGGRESSIVE")
    assert price == 200.0


# ── simulate_paper_fill ───────────────────────────────────────────────────────

def test_fill_when_mid_le_limit():
    # mid = (200+210)/2 = 205; limit = 207 → fill
    result = simulate_paper_fill(bid=200.0, ask=210.0, limit_price=207.0, elapsed_secs=0.0, cfg=_cfg())
    assert result.filled is True
    assert result.fill_price > 0


def test_no_fill_when_mid_gt_limit():
    # mid = (300+310)/2 = 305; limit = 200 → no fill
    result = simulate_paper_fill(bid=300.0, ask=310.0, limit_price=200.0, elapsed_secs=0.0, cfg=_cfg())
    assert result.filled is False


def test_timeout_cancels_order():
    result = simulate_paper_fill(bid=200.0, ask=205.0, limit_price=210.0, elapsed_secs=31.0, cfg=_cfg())
    assert result.filled is False
    assert result.timed_out is True


def test_no_timeout_before_deadline():
    result = simulate_paper_fill(bid=200.0, ask=205.0, limit_price=100.0, elapsed_secs=10.0, cfg=_cfg())
    assert result.timed_out is False


def test_fill_price_le_ask():
    result = simulate_paper_fill(bid=200.0, ask=210.0, limit_price=210.0, elapsed_secs=0.0, cfg=_cfg())
    if result.filled:
        assert result.fill_price <= 210.0


def test_slippage_zero_for_no_fill():
    result = simulate_paper_fill(bid=300.0, ask=310.0, limit_price=100.0, elapsed_secs=0.0)
    assert result.slippage_vs_limit == 0.0


def test_result_has_all_fields():
    result = simulate_paper_fill(bid=200.0, ask=210.0, limit_price=207.0, elapsed_secs=0.0)
    assert hasattr(result, "filled")
    assert hasattr(result, "fill_price")
    assert hasattr(result, "limit_price")
    assert hasattr(result, "elapsed_secs")
    assert hasattr(result, "timed_out")
    assert hasattr(result, "slippage_vs_limit")


def test_fill_rate_tracking_field():
    # LimitOrderResult returned always has a limit_price
    result = simulate_paper_fill(bid=200.0, ask=210.0, limit_price=205.0, elapsed_secs=0.0)
    assert result.limit_price == 205.0
