"""Tests for core/scalein_manager.py (v2.45 Item 9)."""
import time
import pytest
from core.scalein_manager import ScaleInState, ScaleInManager


def _cfg(**overrides):
    base = {
        "scalein_enabled": True,
        "scalein_first_pct": 0.5,
        "scalein_pullback_pct": 0.003,
        "scalein_timeout_mins": 5,
        "scalein_min_score": 80,
    }
    base.update(overrides)
    return base


# ── ScaleInManager.is_enabled ─────────────────────────────────────────────────

def test_disabled_by_config():
    assert ScaleInManager.is_enabled({"scalein_enabled": False}) is False


def test_enabled_by_config():
    assert ScaleInManager.is_enabled({"scalein_enabled": True}) is True


# ── qualifies ─────────────────────────────────────────────────────────────────

def test_qualifies_high_score():
    assert ScaleInManager.qualifies(85, _cfg()) is True


def test_qualifies_low_score():
    assert ScaleInManager.qualifies(70, _cfg()) is False


def test_qualifies_disabled():
    assert ScaleInManager.qualifies(90, {"scalein_enabled": False}) is False


# ── lot splits ────────────────────────────────────────────────────────────────

def test_leg1_lots_50pct():
    assert ScaleInManager.leg1_lots(4, _cfg(scalein_first_pct=0.5)) == 2


def test_leg2_lots_remainder():
    assert ScaleInManager.leg2_lots(4, _cfg(scalein_first_pct=0.5)) == 2


def test_leg1_min_one():
    assert ScaleInManager.leg1_lots(1, _cfg(scalein_first_pct=0.5)) == 1


def test_leg2_min_one():
    assert ScaleInManager.leg2_lots(1, _cfg()) >= 1


# ── create_state ──────────────────────────────────────────────────────────────

def test_create_state_call_trigger_below_entry():
    state = ScaleInManager.create_state("T1", 22000.0, 2, "CALL", _cfg())
    assert state.trigger_price < 22000.0


def test_create_state_put_trigger_above_entry():
    state = ScaleInManager.create_state("T2", 22000.0, 2, "PUT", _cfg())
    assert state.trigger_price > 22000.0


def test_create_state_timeout_in_future():
    state = ScaleInManager.create_state("T3", 22000.0, 2, "CALL", _cfg(scalein_timeout_mins=5))
    assert state.timeout_ts > time.time()


def test_create_state_correct_lots():
    state = ScaleInManager.create_state("T4", 22000.0, 4, "CALL", _cfg(scalein_first_pct=0.5))
    assert state.leg1_lots == 2
    assert state.leg2_lots == 2


# ── should_fill_leg2 ──────────────────────────────────────────────────────────

def test_call_fills_on_pullback():
    state = ScaleInManager.create_state("T5", 22000.0, 2, "CALL", _cfg())
    # trigger = 22000 × (1 - 0.003) = 21934
    assert ScaleInManager.should_fill_leg2(state, 21900.0) is True


def test_call_does_not_fill_above_trigger():
    state = ScaleInManager.create_state("T6", 22000.0, 2, "CALL", _cfg())
    assert ScaleInManager.should_fill_leg2(state, 22100.0) is False


def test_put_fills_on_bounce():
    state = ScaleInManager.create_state("T7", 22000.0, 2, "PUT", _cfg())
    # trigger = 22000 × (1 + 0.003) = 22066
    assert ScaleInManager.should_fill_leg2(state, 22100.0) is True


def test_timeout_forces_fill():
    state = ScaleInManager.create_state("T8", 22000.0, 2, "CALL", _cfg(scalein_timeout_mins=0))
    past_ts = time.time() - 1   # already expired
    state2 = ScaleInState(
        trade_id=state.trade_id, entry_price=state.entry_price,
        direction=state.direction, trigger_price=state.trigger_price,
        timeout_ts=past_ts, leg1_lots=state.leg1_lots, leg2_lots=state.leg2_lots,
    )
    assert ScaleInManager.should_fill_leg2(state2, 22200.0) is True   # not at trigger, but timed out


def test_completed_state_never_fills():
    state = ScaleInState(
        trade_id="T9", entry_price=22000.0, direction="CALL",
        trigger_price=21934.0, timeout_ts=time.time() - 1,
        leg1_lots=1, leg2_lots=1, completed=True,
    )
    assert ScaleInManager.should_fill_leg2(state, 21900.0) is False


# ── compute_avg_price ─────────────────────────────────────────────────────────

def test_avg_price_equal_lots():
    state = ScaleInManager.create_state("T10", 22000.0, 2, "CALL", _cfg(scalein_first_pct=0.5))
    avg = ScaleInManager.compute_avg_price(state, 21934.0)
    expected = (22000.0 * 1 + 21934.0 * 1) / 2
    assert abs(avg - expected) < 0.1


def test_avg_price_weighted():
    state = ScaleInManager.create_state("T11", 22000.0, 4, "CALL", _cfg(scalein_first_pct=0.75))
    # leg1=3, leg2=1
    avg = ScaleInManager.compute_avg_price(state, 21900.0)
    expected = (22000.0 * state.leg1_lots + 21900.0 * state.leg2_lots) / 4
    assert abs(avg - expected) < 0.1
