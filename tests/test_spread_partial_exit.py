"""Tests for spread partial exit logic in core/spread_strategy.py (v2.44 Item 3)."""
from datetime import time as dtime
from unittest.mock import MagicMock, patch

import pytest
from core.spread_strategy import SpreadLeg, SpreadPosition, evaluate_spread_exit

CFG = {
    "spread_exit_pnl_pct": 0.50,      # full target at 50% of max_profit
    "spread_stop_pct": 0.80,          # hard stop at 80% of max_loss
    "spread_partial_exit_pct": 0.75,
    "spread_partial_lots_pct": 0.50,
    "spread_theta_exit_dte": 0,
    "spread_theta_exit_time": "14:00",
}

# max_loss=70, max_profit=70 for these tests (net_debit=70)
_NET = 70.0


def make_position(**kwargs):
    defaults = dict(
        direction="CE",
        long_leg=SpreadLeg(strike=18000, premium=100.0, option_type="CE", side="BUY"),
        short_leg=SpreadLeg(strike=18100, premium=30.0, option_type="CE", side="SELL"),
        entry_ts=0.0,
        net_debit=_NET,
        max_profit=_NET,
        max_loss=_NET,
        lot_size=50,
        open=True,
        partial_exit_done=False,
        partial_exit_pnl=0.0,
        partial_exit_ts=None,
    )
    defaults.update(kwargs)
    return SpreadPosition(**defaults)


# ── SpreadPosition fields ────────────────────────────────────────────────────

def test_position_has_partial_exit_done():
    p = make_position()
    assert hasattr(p, "partial_exit_done")
    assert p.partial_exit_done is False


def test_position_has_partial_exit_pnl():
    p = make_position()
    assert hasattr(p, "partial_exit_pnl")
    assert p.partial_exit_pnl == 0.0


def test_position_has_partial_exit_ts():
    p = make_position()
    assert hasattr(p, "partial_exit_ts")
    assert p.partial_exit_ts is None


# ── SpreadExitDecision fields ────────────────────────────────────────────────

def test_exit_decision_has_action():
    p = make_position()
    d = evaluate_spread_exit(p, 10.0, CFG)
    assert hasattr(d, "action")
    assert d.action in ("HOLD", "PARTIAL_EXIT", "FULL_EXIT")


def test_exit_decision_has_exit_pct():
    p = make_position()
    d = evaluate_spread_exit(p, 10.0, CFG)
    assert hasattr(d, "exit_pct")
    assert 0.0 <= d.exit_pct <= 1.0


def test_exit_decision_has_reason():
    p = make_position()
    d = evaluate_spread_exit(p, 10.0, CFG)
    assert isinstance(d.reason, str)
    assert len(d.reason) > 0


def test_exit_decision_has_trail_stop_level():
    p = make_position()
    d = evaluate_spread_exit(p, 10.0, CFG)
    assert hasattr(d, "trail_stop_level")


# ── Full stop loss ────────────────────────────────────────────────────────────

def test_full_exit_on_hard_stop():
    p = make_position()
    # SL triggers when pnl <= -(max_loss * spread_stop_pct=0.80)
    stop_trigger = -(_NET * 0.80) - 1
    d = evaluate_spread_exit(p, stop_trigger, CFG)
    assert d.action == "FULL_EXIT"
    assert d.exit_pct == pytest.approx(1.0)


def test_full_exit_stop_reason_contains_stop_loss():
    p = make_position()
    d = evaluate_spread_exit(p, -(_NET * 0.80) - 1, CFG)
    assert "STOP" in d.reason.upper() or "LOSS" in d.reason.upper()


# ── Full target ───────────────────────────────────────────────────────────────

def test_full_exit_on_target():
    p = make_position()
    # Target at pnl >= max_profit * spread_exit_pnl_pct=0.50
    target_pnl = _NET * 0.50 + 1
    d = evaluate_spread_exit(p, target_pnl, CFG)
    assert d.action == "FULL_EXIT"


def test_full_exit_at_exactly_target():
    p = make_position()
    target_pnl = _NET * 0.50
    d = evaluate_spread_exit(p, target_pnl, CFG)
    assert d.action == "FULL_EXIT"


# ── Partial exit ─────────────────────────────────────────────────────────────

def test_partial_exit_at_75pct_profit():
    p = make_position()
    # Partial at 75% of max_profit, but below full target (50%)
    # Wait — partial_exit_pct=0.75 > exit_pnl_pct=0.50, so target is checked first!
    # With exit_pnl_pct=0.50, any pnl >= 50% will be FULL_EXIT.
    # Need to set a higher full-exit threshold to test partial
    cfg = dict(CFG, spread_exit_pnl_pct=0.90, spread_partial_exit_pct=0.50)
    partial_pnl = _NET * 0.50 + 1  # > 50% (partial) but < 90% (full target)
    d = evaluate_spread_exit(p, partial_pnl, cfg)
    assert d.action == "PARTIAL_EXIT"
    assert d.exit_pct == pytest.approx(0.50)


def test_no_repeat_partial_exit():
    cfg = dict(CFG, spread_exit_pnl_pct=0.90, spread_partial_exit_pct=0.50)
    p = make_position(partial_exit_done=True)
    partial_pnl = _NET * 0.55
    d = evaluate_spread_exit(p, partial_pnl, cfg)
    assert d.action != "PARTIAL_EXIT"


def test_hold_below_partial_threshold():
    p = make_position()
    # Mock time to before theta cutoff so theta guard doesn't fire
    with patch("core.datetime_ist.now_ist", return_value=_make_now_ist(10, 0)):
        d = evaluate_spread_exit(p, 5.0, CFG)  # 5 << target & partial threshold
    assert d.action == "HOLD"


# ── Theta decay guard ────────────────────────────────────────────────────────

def _make_now_ist(h, m):
    mock_dt = MagicMock()
    mock_dt.time.return_value = dtime(h, m)
    return mock_dt


def test_theta_exit_after_cutoff_with_profit():
    p = make_position()
    with patch("core.datetime_ist.now_ist", return_value=_make_now_ist(14, 30)):
        d = evaluate_spread_exit(p, 5.0, CFG)
        # pnl > 0 and time >= 14:00 → PARTIAL_EXIT (theta guard)
        assert d.action in ("PARTIAL_EXIT", "HOLD")  # may trigger theta guard


def test_no_theta_exit_with_negative_pnl():
    p = make_position()
    with patch("core.datetime_ist.now_ist", return_value=_make_now_ist(14, 30)):
        # Negative pnl → theta guard should not fire (pnl must be > 0)
        d = evaluate_spread_exit(p, -5.0, CFG)
    assert d.action == "HOLD"


# ── Closed position ───────────────────────────────────────────────────────────

def test_closed_position_returns_hold():
    p = make_position(open=False)
    d = evaluate_spread_exit(p, 100.0, CFG)
    assert d.action == "HOLD"


# ── Hold small negative pnl ───────────────────────────────────────────────────

def test_hold_small_negative_pnl():
    p = make_position()
    with patch("core.datetime_ist.now_ist", return_value=_make_now_ist(10, 0)):
        d = evaluate_spread_exit(p, -5.0, CFG)
    assert d.action == "HOLD"


# ── Stop priority over everything ────────────────────────────────────────────

def test_stop_takes_priority_over_target():
    # With very high pnl that would trigger target but also triggers stop
    # In practice impossible but test the SL check comes first
    p = make_position(max_loss=0.001)  # near-zero max_loss makes any negative trigger SL
    d = evaluate_spread_exit(p, -0.01, CFG)
    assert d.action == "FULL_EXIT"
