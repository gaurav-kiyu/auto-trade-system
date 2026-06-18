"""Tests for core/iron_condor_strategy.py (v2.45 Item 11)."""
from core.iron_condor_strategy import (
    IronCondorPosition,
    build_iron_condor,
    check_ic_conditions,
    evaluate_ic_exit,
)


def _chain(spot=22000, width=100):
    """Build chain with decreasing premiums away from ATM."""
    k = spot
    return {
        "calls": {
            k:          100.0,
            k + width:  60.0,
            k + width*2: 30.0,
            k + width*3: 15.0,
            k + width*4: 8.0,
        },
        "puts": {
            k:          95.0,
            k - width:  55.0,
            k - width*2: 25.0,
            k - width*3: 12.0,
            k - width*4: 6.0,
        },
    }


def _cfg(**kw):
    base = {
        "ic_strategy_enabled": True,
        "ic_max_adx": 18,
        "ic_max_vix": 15,
        "ic_min_dte": 3,
        "ic_wing_width_steps": 1,
        "ic_profit_target": 0.5,
        "ic_stop_mult": 0.8,
    }
    base.update(kw)
    return base


# ── check_ic_conditions ───────────────────────────────────────────────────────

def test_disabled_fails():
    ok, _ = check_ic_conditions("CHOPPY", 15.0, 12.0, 5, {"ic_strategy_enabled": False})
    assert ok is False


def test_choppy_all_pass():
    ok, _ = check_ic_conditions("CHOPPY", 15.0, 12.0, 5, _cfg())
    assert ok is True


def test_trending_fails():
    ok, _ = check_ic_conditions("TRENDING", 15.0, 12.0, 5, _cfg())
    assert ok is False


def test_high_adx_fails():
    ok, _ = check_ic_conditions("CHOPPY", 20.0, 12.0, 5, _cfg())
    assert ok is False


def test_high_vix_fails():
    ok, _ = check_ic_conditions("CHOPPY", 15.0, 16.0, 5, _cfg())
    assert ok is False


def test_low_dte_fails():
    ok, _ = check_ic_conditions("CHOPPY", 15.0, 12.0, 2, _cfg())
    assert ok is False


# ── build_iron_condor ─────────────────────────────────────────────────────────

def test_build_returns_position():
    pos = build_iron_condor(22000.0, _chain(), _cfg())
    assert pos is not None


def test_call_long_above_call_short():
    pos = build_iron_condor(22000.0, _chain(), _cfg())
    assert pos is not None
    assert pos.call_long_strike > pos.call_short_strike


def test_put_long_below_put_short():
    pos = build_iron_condor(22000.0, _chain(), _cfg())
    assert pos is not None
    assert pos.put_long_strike < pos.put_short_strike


def test_net_credit_positive():
    pos = build_iron_condor(22000.0, _chain(), _cfg())
    assert pos is not None
    assert pos.net_credit > 0


def test_max_profit_equals_net_credit():
    pos = build_iron_condor(22000.0, _chain(), _cfg())
    assert pos is not None
    assert abs(pos.max_profit - pos.net_credit) < 0.01


def test_max_loss_spread_minus_credit():
    pos = build_iron_condor(22000.0, _chain(), _cfg())
    assert pos is not None
    expected_max_loss = max(0.0, pos.spread_width - pos.net_credit)
    assert abs(pos.max_loss - expected_max_loss) < 0.01


def test_none_chain_returns_none():
    assert build_iron_condor(22000.0, None, _cfg()) is None


def test_small_chain_returns_none():
    small = {"calls": {22000: 100.0}, "puts": {22000: 95.0}}
    assert build_iron_condor(22000.0, small, _cfg()) is None


# ── evaluate_ic_exit - inverted P&L ──────────────────────────────────────────

def _make_ic():
    return IronCondorPosition(
        call_short_strike=22100, call_long_strike=22200,
        put_short_strike=21900, put_long_strike=21800,
        call_spread_credit=30.0, put_spread_credit=25.0,
        net_credit=55.0, spread_width=100.0,
        max_profit=55.0, max_loss=45.0, expiry="",
    )


def test_hold_when_within_bounds():
    pos = _make_ic()
    # current value = 30 (not at profit target, not at stop)
    dec = evaluate_ic_exit(pos, 20.0, 10.0, _cfg())
    assert dec.action == "HOLD"


def test_profit_target_exit():
    pos = _make_ic()
    # profit_target=0.5: close when value <= 55 × (1-0.5) = 27.5
    # current = 10 + 10 = 20 < 27.5 → exit
    dec = evaluate_ic_exit(pos, 10.0, 10.0, _cfg())
    assert dec.action == "FULL_EXIT"
    assert "ic_profit" in dec.reason


def test_stop_loss_exit():
    pos = _make_ic()
    # stop = 45 × 0.8 = 36; current = 20+20 = 40 >= 36 → stop
    dec = evaluate_ic_exit(pos, 20.0, 20.0, _cfg())
    assert dec.action == "FULL_EXIT"
    assert "ic_stop" in dec.reason


def test_eod_close_both():
    # When forcing close (pass very high values)
    pos = _make_ic()
    dec = evaluate_ic_exit(pos, 80.0, 80.0, _cfg())
    assert dec.action == "FULL_EXIT"


def test_inverted_pnl_profit_on_decay():
    # Value decreasing = good for us (sold premium)
    pos = _make_ic()
    evaluate_ic_exit(pos, 25.0, 25.0, _cfg())
    dec_late  = evaluate_ic_exit(pos,  5.0,  5.0, _cfg())
    # Late should exit (profit); early might hold
    assert dec_late.action == "FULL_EXIT"


def test_net_credit_calculation():
    pos = _make_ic()
    assert abs(pos.net_credit - (pos.call_spread_credit + pos.put_spread_credit)) < 0.01
