"""Tests for core/straddle_strategy.py (v2.45 Item 10)."""
import pytest
from core.straddle_strategy import (
    StraddlePosition, StraddleExitDecision,
    build_straddle, build_strangle,
    evaluate_straddle_exit, check_straddle_conditions,
)


def _chain(spot=22000, cp=200.0, pp=180.0, width=100):
    return {
        "calls": {spot: cp, spot + width: 80.0, spot + width * 2: 40.0},
        "puts":  {spot: pp, spot - width: 70.0, spot - width * 2: 30.0},
    }


def _cfg(**kw):
    base = {
        "straddle_strategy_enabled": True,
        "straddle_max_iv_rank": 20,
        "straddle_target_mult": 1.5,
        "straddle_stop_mult": 0.6,
        "straddle_close_both_on_target": False,
        "strangle_width_steps": 1,
        "gex_lot_size": 50,
    }
    base.update(kw)
    return base


# ── check_straddle_conditions ─────────────────────────────────────────────────

def test_disabled_fails():
    ok, _ = check_straddle_conditions("CHOPPY", 15.0, 12.0, 10.0, False, {"straddle_strategy_enabled": False})
    assert ok is False


def test_event_day_low_iv_passes():
    ok, reason = check_straddle_conditions("TRENDING", 30.0, 20.0, 15.0, True, _cfg())
    assert ok is True
    assert "event_day" in reason


def test_event_day_high_iv_fails():
    ok, _ = check_straddle_conditions("TRENDING", 30.0, 20.0, 25.0, True, _cfg(straddle_max_iv_rank=20))
    assert ok is False


def test_choppy_regime_conditions_pass():
    ok, _ = check_straddle_conditions("CHOPPY", 14.0, 12.0, 10.0, False, _cfg())
    assert ok is True


def test_trending_regime_non_event_fails():
    ok, _ = check_straddle_conditions("TRENDING", 14.0, 12.0, 10.0, False, _cfg())
    assert ok is False


def test_choppy_high_vix_fails():
    ok, _ = check_straddle_conditions("CHOPPY", 14.0, 20.0, 10.0, False, _cfg())
    assert ok is False


def test_choppy_high_adx_fails():
    ok, _ = check_straddle_conditions("CHOPPY", 25.0, 12.0, 10.0, False, _cfg())
    assert ok is False


# ── build_straddle ────────────────────────────────────────────────────────────

def test_build_straddle_returns_position():
    pos = build_straddle(22000.0, _chain(), _cfg())
    assert pos is not None
    assert pos.strategy_type == "STRADDLE"


def test_build_straddle_atm_strike():
    pos = build_straddle(22050.0, _chain(spot=22000), _cfg())
    assert pos is not None
    assert pos.call_strike == pos.put_strike == 22000


def test_build_straddle_total_debit():
    pos = build_straddle(22000.0, _chain(cp=200.0, pp=180.0), _cfg())
    assert pos is not None
    assert abs(pos.total_debit - 380.0) < 0.01


def test_build_straddle_breakevens():
    pos = build_straddle(22000.0, _chain(cp=200.0, pp=180.0), _cfg())
    assert pos is not None
    assert abs(pos.breakeven_up - (22000 + 380)) < 0.1
    assert abs(pos.breakeven_down - (22000 - 380)) < 0.1


def test_build_straddle_none_chain():
    assert build_straddle(22000.0, None, _cfg()) is None


def test_build_straddle_empty_chain():
    assert build_straddle(22000.0, {"calls": {}, "puts": {}}, _cfg()) is None


# ── build_strangle ────────────────────────────────────────────────────────────

def test_build_strangle_otm_strikes():
    pos = build_strangle(22000.0, _chain(spot=22000, width=100), _cfg(strangle_width_steps=1))
    assert pos is not None
    assert pos.strategy_type == "STRANGLE"
    assert pos.call_strike > 22000
    assert pos.put_strike < 22000


def test_build_strangle_different_strikes():
    pos = build_strangle(22000.0, _chain(), _cfg(strangle_width_steps=1))
    assert pos is not None
    assert pos.call_strike != pos.put_strike


def test_build_strangle_none_chain():
    assert build_strangle(22000.0, None, _cfg()) is None


# ── evaluate_straddle_exit ────────────────────────────────────────────────────

def _make_pos(total_debit=380.0):
    return StraddlePosition(
        call_strike=22000, put_strike=22000, expiry="", call_premium=200.0,
        put_premium=180.0, total_debit=total_debit, breakeven_up=22380.0,
        breakeven_down=21620.0, max_loss=total_debit, spot_at_entry=22000.0,
        strategy_type="STRADDLE",
    )


def test_exit_hold_when_within_bounds():
    pos = _make_pos(380.0)
    dec = evaluate_straddle_exit(pos, 200.0, 180.0, _cfg())
    assert dec.action == "HOLD"


def test_exit_call_target_hit():
    pos = _make_pos(380.0)
    # target = 380 × 1.5 = 570; call_prem = 600 > 570
    dec = evaluate_straddle_exit(pos, 600.0, 100.0, _cfg())
    assert dec.action == "FULL_EXIT"
    assert "CALL" in dec.exit_leg or "BOTH" in dec.exit_leg


def test_exit_put_target_hit():
    pos = _make_pos(380.0)
    dec = evaluate_straddle_exit(pos, 100.0, 600.0, _cfg())
    assert dec.action == "FULL_EXIT"


def test_exit_stop_fires():
    pos = _make_pos(380.0)
    # stop = 380 × 0.6 = 228; current = 100+50 = 150 < 228
    dec = evaluate_straddle_exit(pos, 100.0, 50.0, _cfg())
    assert dec.action == "FULL_EXIT"
    assert "stop" in dec.reason


def test_exit_close_both_on_target():
    pos = _make_pos(380.0)
    dec = evaluate_straddle_exit(pos, 600.0, 100.0, _cfg(straddle_close_both_on_target=True))
    assert dec.exit_leg == "BOTH"
