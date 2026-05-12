"""Tests for core/implied_move.py (v2.45 Item 2)."""
import math
import pytest
from core.implied_move import ImpliedMove, compute_implied_move, check_implied_move_gate, get_implied_move_score_adj


# ── compute_implied_move ──────────────────────────────────────────────────────

def _make_chain(atm: int = 22000, call_prem: float = 200.0, put_prem: float = 180.0):
    """Build minimal option chain with OI-style dicts."""
    return {
        "calls": {atm: {"oi": 100000, "premium": call_prem}, atm + 100: {"oi": 50000, "premium": 80.0}},
        "puts":  {atm: {"oi": 90000,  "premium": put_prem},  atm - 100: {"oi": 40000, "premium": 70.0}},
    }


def _make_simple_chain(atm: int = 22000, call_prem: float = 200.0, put_prem: float = 180.0):
    """Simplified chain: strike → premium float."""
    return {
        "calls": {atm: call_prem, atm + 100: 80.0},
        "puts":  {atm: put_prem,  atm - 100: 70.0},
    }


def test_disabled_returns_none():
    chain = _make_simple_chain()
    result = compute_implied_move(chain, 22000.0, {"implied_move_enabled": False})
    assert result is None


def test_none_chain_returns_none():
    result = compute_implied_move(None, 22000.0, {"implied_move_enabled": True})
    assert result is None


def test_zero_spot_returns_none():
    chain = _make_simple_chain()
    result = compute_implied_move(chain, 0.0, {"implied_move_enabled": True})
    assert result is None


def test_formula_accuracy():
    cfg = {"implied_move_enabled": True}
    chain = _make_simple_chain(atm=22000, call_prem=200.0, put_prem=180.0)
    result = compute_implied_move(chain, 22000.0, cfg)
    assert result is not None
    # straddle = 380, move_pct = 380/22000*100 = 1.727%
    assert abs(result.move_pct - (380 / 22000 * 100)) < 0.01


def test_weekly_and_daily_relationship():
    cfg = {"implied_move_enabled": True}
    chain = _make_simple_chain(atm=22000, call_prem=200.0, put_prem=180.0)
    result = compute_implied_move(chain, 22000.0, cfg)
    assert result is not None
    assert abs(result.daily_move_pct - result.weekly_move_pct / math.sqrt(5)) < 0.001


def test_atm_strike_detection():
    cfg = {"implied_move_enabled": True}
    # Spot = 22050, ATM should be 22000 (nearest)
    chain = _make_simple_chain(atm=22000)
    result = compute_implied_move(chain, 22050.0, cfg)
    assert result is not None
    assert result.atm_strike == 22000


def test_move_points_equals_straddle():
    cfg = {"implied_move_enabled": True}
    chain = _make_simple_chain(atm=22000, call_prem=300.0, put_prem=250.0)
    result = compute_implied_move(chain, 22000.0, cfg)
    assert result is not None
    assert abs(result.move_points - 550.0) < 0.01


def test_empty_chain_returns_none():
    cfg = {"implied_move_enabled": True}
    result = compute_implied_move({"calls": {}, "puts": {}}, 22000.0, cfg)
    assert result is None


# ── check_implied_move_gate ───────────────────────────────────────────────────

def _make_im(move_pct=1.5) -> ImpliedMove:
    return ImpliedMove(
        move_pct=move_pct, move_points=move_pct * 220, weekly_move_pct=move_pct,
        daily_move_pct=move_pct / math.sqrt(5), atm_call_premium=200.0,
        atm_put_premium=130.0, atm_strike=22000,
    )


def test_gate_passes_when_disabled():
    passed, reason = check_implied_move_gate(_make_im(), 1.0, "CALL", {"implied_move_enabled": False})
    assert passed is True
    assert reason == ""


def test_gate_passes_when_none():
    passed, reason = check_implied_move_gate(None, 1.0, "CALL", {"implied_move_enabled": True})
    assert passed is True


def test_gate_passes_with_sufficient_edge():
    im = _make_im(move_pct=1.0)
    passed, reason = check_implied_move_gate(im, 1.5, "CALL", {"implied_move_enabled": True, "implied_move_min_edge_mult": 1.2})
    assert passed is True


def test_gate_fails_insufficient_edge():
    im = _make_im(move_pct=2.0)
    passed, reason = check_implied_move_gate(im, 1.0, "CALL", {"implied_move_enabled": True, "implied_move_min_edge_mult": 1.2})
    assert passed is False
    assert "implied_move_gate" in reason


def test_score_adj_zero_when_gate_passes():
    im = _make_im(move_pct=1.0)
    adj = get_implied_move_score_adj(im, 2.0, {"implied_move_enabled": True})
    assert adj == 0


def test_score_adj_negative_when_gate_fails():
    im = _make_im(move_pct=3.0)
    adj = get_implied_move_score_adj(im, 1.0, {"implied_move_enabled": True, "implied_move_min_edge_mult": 1.2})
    assert adj < 0
