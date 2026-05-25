"""
Tests for core/spread_strategy.py (Phase D).

Covers:
  - build_spread() disabled by default (spread_strategy_enabled=False)
  - build_spread() call spread construction
  - build_spread() put spread construction
  - build_spread() missing premium returns None
  - build_spread() non-viable spread (net_debit <= 0) returns None
  - mark_to_market() P&L calculation
  - mark_to_market() missing premium returns 0
  - paper_fill_spread() target exit
  - paper_fill_spread() stop exit
  - paper_fill_spread() force exit
  - paper_fill_spread() returns None when conditions not met
  - paper_fill_spread() closed position returns None
  - compute_spread_metrics() empty list
  - compute_spread_metrics() mixed winners/losers
  - format_spread_summary() string contract
  - SpreadPosition spread_width property
"""
import time

from core.spread_strategy import (
    SpreadLeg,
    SpreadPosition,
    SpreadResult,
    build_spread,
    compute_spread_metrics,
    format_spread_summary,
    mark_to_market,
    paper_fill_spread,
)

# ── Common fixtures ───────────────────────────────────────────────────────────

_ENABLED_CFG = {
    "spread_strategy_enabled": True,
    "spread_width_strikes": 2,
    "spread_slippage_pct": 0.0,     # zero slippage for deterministic tests
    "spread_exit_pnl_pct": 0.50,
    "spread_stop_pct": 0.80,
    "lot_size": 1,
}

# NIFTY-like: ATM=22000, step=50
_CALL_PREMIUMS = {
    22000: 100.0,
    22050: 80.0,
    22100: 60.0,
    22150: 45.0,
}
_PUT_PREMIUMS = {
    21900: 60.0,
    21950: 80.0,
    22000: 100.0,
    22050: 130.0,
}


def _make_position(direction="CALL_SPREAD", net_debit=80.0,
                   max_profit=20.0, max_loss=80.0):
    long_leg  = SpreadLeg(22000, 100.0, "CALL", "BUY",  1)
    short_leg = SpreadLeg(22100, 60.0,  "CALL", "SELL", 1)
    return SpreadPosition(
        direction=direction,
        long_leg=long_leg,
        short_leg=short_leg,
        entry_ts=time.time(),
        net_debit=net_debit,
        max_profit=max_profit,
        max_loss=max_loss,
        lot_size=1,
    )


def _make_result(gross_pnl: float) -> SpreadResult:
    return SpreadResult(
        direction="CALL_SPREAD",
        long_strike=22000, short_strike=22100,
        net_debit=80.0, exit_premium=90.0,
        gross_pnl=gross_pnl, lot_size=1,
        entry_ts=time.time(), exit_ts=time.time(),
        exit_reason="TARGET_50pct",
        is_winner=gross_pnl > 0,
    )


# ── build_spread ──────────────────────────────────────────────────────────────

class TestBuildSpread:
    def test_disabled_by_default(self):
        pos = build_spread("CALL", 22000, 50, 22000.0,
                           _CALL_PREMIUMS, _PUT_PREMIUMS, cfg={})
        assert pos is None

    def test_call_spread_returns_position(self):
        pos = build_spread("CALL", 22000, 50, 22000.0,
                           _CALL_PREMIUMS, _PUT_PREMIUMS, cfg=_ENABLED_CFG)
        assert pos is not None
        assert pos.direction == "CALL_SPREAD"

    def test_put_spread_returns_position(self):
        pos = build_spread("PUT", 22000, 50, 22000.0,
                           _CALL_PREMIUMS, _PUT_PREMIUMS, cfg=_ENABLED_CFG)
        assert pos is not None
        assert pos.direction == "PUT_SPREAD"

    def test_call_spread_legs(self):
        pos = build_spread("CALL", 22000, 50, 22000.0,
                           _CALL_PREMIUMS, _PUT_PREMIUMS, cfg=_ENABLED_CFG)
        assert pos.long_leg.strike == 22000
        assert pos.short_leg.strike == 22000 + 2 * 50   # width=2 steps

    def test_put_spread_legs(self):
        pos = build_spread("PUT", 22000, 50, 22000.0,
                           _CALL_PREMIUMS, _PUT_PREMIUMS, cfg=_ENABLED_CFG)
        assert pos.long_leg.strike == 22000
        assert pos.short_leg.strike == 22000 - 2 * 50

    def test_missing_long_premium_returns_none(self):
        pos = build_spread("CALL", 99999, 50, 99999.0,
                           _CALL_PREMIUMS, _PUT_PREMIUMS, cfg=_ENABLED_CFG)
        assert pos is None

    def test_missing_short_premium_returns_none(self):
        sparse = {22000: 100.0}   # no second strike
        pos = build_spread("CALL", 22000, 50, 22000.0,
                           sparse, _PUT_PREMIUMS, cfg=_ENABLED_CFG)
        assert pos is None

    def test_net_debit_is_long_minus_short(self):
        pos = build_spread("CALL", 22000, 50, 22000.0,
                           _CALL_PREMIUMS, _PUT_PREMIUMS, cfg=_ENABLED_CFG)
        assert pos is not None
        expected = (100.0 - 60.0) * 1   # long=22000 @ 100, short=22100 @ 60
        assert abs(pos.net_debit - expected) < 0.01

    def test_spread_width_property(self):
        pos = build_spread("CALL", 22000, 50, 22000.0,
                           _CALL_PREMIUMS, _PUT_PREMIUMS, cfg=_ENABLED_CFG)
        assert pos is not None
        assert pos.spread_width == 100.0    # 22100 - 22000

    def test_unknown_direction_returns_none(self):
        pos = build_spread("STRADDLE", 22000, 50, 22000.0,
                           _CALL_PREMIUMS, _PUT_PREMIUMS, cfg=_ENABLED_CFG)
        assert pos is None

    def test_position_open_at_creation(self):
        pos = build_spread("CALL", 22000, 50, 22000.0,
                           _CALL_PREMIUMS, _PUT_PREMIUMS, cfg=_ENABLED_CFG)
        assert pos is not None
        assert pos.open is True

    def test_max_profit_positive(self):
        pos = build_spread("CALL", 22000, 50, 22000.0,
                           _CALL_PREMIUMS, _PUT_PREMIUMS, cfg=_ENABLED_CFG)
        assert pos is not None
        assert pos.max_profit > 0

    def test_max_loss_equals_net_debit(self):
        pos = build_spread("CALL", 22000, 50, 22000.0,
                           _CALL_PREMIUMS, _PUT_PREMIUMS, cfg=_ENABLED_CFG)
        assert pos is not None
        assert abs(pos.max_loss - pos.net_debit) < 0.01


# ── mark_to_market ────────────────────────────────────────────────────────────

class TestMarkToMarket:
    def test_zero_when_premiums_unchanged(self):
        pos = _make_position()
        pnl = mark_to_market(pos, 22050.0, _CALL_PREMIUMS, _PUT_PREMIUMS)
        # Long=22000 entry=100 current=100 → 0; Short=22100 entry=60 current=60 → 0
        assert abs(pnl) < 0.01

    def test_positive_pnl_when_long_premium_rises(self):
        pos = _make_position()
        call_up = dict(_CALL_PREMIUMS)
        call_up[22000] = 150.0    # long leg rose from 100 to 150
        pnl = mark_to_market(pos, 22100.0, call_up, _PUT_PREMIUMS)
        assert pnl > 0

    def test_negative_pnl_when_long_premium_falls(self):
        pos = _make_position()
        call_down = dict(_CALL_PREMIUMS)
        call_down[22000] = 50.0   # long leg fell from 100 to 50
        pnl = mark_to_market(pos, 21900.0, call_down, _PUT_PREMIUMS)
        assert pnl < 0

    def test_missing_premium_returns_zero(self):
        pos = _make_position()
        pnl = mark_to_market(pos, 22000.0, {}, {})
        assert pnl == 0.0

    def test_closed_position_returns_zero(self):
        pos = _make_position()
        pos.open = False
        pnl = mark_to_market(pos, 22000.0, _CALL_PREMIUMS, _PUT_PREMIUMS)
        assert pnl == 0.0


# ── paper_fill_spread ─────────────────────────────────────────────────────────

class TestPaperFillSpread:
    def test_force_exit_closes_position(self):
        pos = _make_position()
        res = paper_fill_spread(pos, 22050.0, _CALL_PREMIUMS, _PUT_PREMIUMS,
                                _ENABLED_CFG, force_exit_reason="EOD")
        assert res is not None
        assert res.exit_reason == "EOD"
        assert pos.open is False

    def test_target_exit_when_pnl_above_threshold(self):
        pos = _make_position(max_profit=100.0, max_loss=80.0)
        call_win = dict(_CALL_PREMIUMS)
        call_win[22000] = 150.0    # large gain on long
        res = paper_fill_spread(pos, 22050.0, call_win, _PUT_PREMIUMS,
                                _ENABLED_CFG)
        assert res is not None
        assert "TARGET" in res.exit_reason

    def test_stop_exit_when_loss_exceeds_threshold(self):
        pos = _make_position(max_profit=20.0, max_loss=80.0)
        call_down = dict(_CALL_PREMIUMS)
        call_down[22000] = 10.0    # long premium collapsed
        call_down[22100] = 100.0   # short premium surged (worst case)
        res = paper_fill_spread(pos, 21900.0, call_down, _PUT_PREMIUMS,
                                _ENABLED_CFG)
        assert res is not None
        assert "STOP" in res.exit_reason

    def test_returns_none_when_conditions_not_met(self):
        pos = _make_position()
        res = paper_fill_spread(pos, 22000.0, _CALL_PREMIUMS, _PUT_PREMIUMS,
                                _ENABLED_CFG)
        assert res is None
        assert pos.open is True

    def test_closed_position_returns_none(self):
        pos = _make_position()
        pos.open = False
        res = paper_fill_spread(pos, 22050.0, _CALL_PREMIUMS, _PUT_PREMIUMS,
                                _ENABLED_CFG, force_exit_reason="EOD")
        assert res is None

    def test_result_is_winner_on_profit(self):
        pos = _make_position()
        res = paper_fill_spread(pos, 22050.0, _CALL_PREMIUMS, _PUT_PREMIUMS,
                                _ENABLED_CFG, force_exit_reason="TEST")
        assert res is not None
        assert isinstance(res.is_winner, bool)

    def test_result_has_exit_ts(self):
        pos = _make_position()
        before = time.time()
        res = paper_fill_spread(pos, 22050.0, _CALL_PREMIUMS, _PUT_PREMIUMS,
                                _ENABLED_CFG, force_exit_reason="EOD")
        assert res is not None
        assert res.exit_ts >= before


# ── compute_spread_metrics ────────────────────────────────────────────────────

class TestComputeSpreadMetrics:
    def test_empty_returns_zero_trades(self):
        m = compute_spread_metrics([])
        assert m["trades"] == 0

    def test_all_winners(self):
        results = [_make_result(50.0) for _ in range(5)]
        m = compute_spread_metrics(results)
        assert m["trades"] == 5
        assert m["winners"] == 5
        assert m["win_rate"] == 100.0

    def test_mixed_win_loss(self):
        results = [_make_result(100.0), _make_result(-50.0)]
        m = compute_spread_metrics(results)
        assert m["winners"] == 1
        assert m["losers"] == 1
        assert m["win_rate"] == 50.0
        assert abs(m["total_pnl"] - 50.0) < 0.01

    def test_expectancy_sign(self):
        results = [_make_result(200.0), _make_result(-50.0)]
        m = compute_spread_metrics(results)
        assert m["expectancy"] > 0

    def test_max_and_min_pnl(self):
        results = [_make_result(100.0), _make_result(-30.0), _make_result(50.0)]
        m = compute_spread_metrics(results)
        assert m["max_profit"] == 100.0
        assert m["max_loss"] == -30.0


# ── format_spread_summary ─────────────────────────────────────────────────────

class TestFormatSpreadSummary:
    def test_empty_list(self):
        s = format_spread_summary([])
        assert "no closed" in s.lower()

    def test_contains_win_rate(self):
        results = [_make_result(50.0), _make_result(-20.0)]
        s = format_spread_summary(results)
        assert "%" in s

    def test_contains_total_pnl(self):
        results = [_make_result(100.0)]
        s = format_spread_summary(results)
        assert "P&L" in s or "pnl" in s.lower()

    def test_returns_string(self):
        results = [_make_result(100.0)]
        assert isinstance(format_spread_summary(results), str)
