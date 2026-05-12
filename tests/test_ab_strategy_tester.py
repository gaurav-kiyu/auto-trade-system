"""Tests for core/ab_strategy_tester.py (v2.44 Item 20)."""
import json
import os
import tempfile
import pytest
from core.ab_strategy_tester import (
    ABVariantState,
    ABSignalDecision,
    ABComparisonResult,
    ABStrategyTester,
    _mann_whitney_p,
)


# ── ABVariantState ────────────────────────────────────────────────────────────

def test_variant_state_initial():
    v = ABVariantState(name="CONTROL")
    assert v.n_trades == 0
    assert v.n_wins == 0
    assert v.total_pnl == 0.0
    assert v.pnls == []


def test_variant_state_add_win():
    v = ABVariantState(name="A")
    v.add_outcome(100.0)
    assert v.n_trades == 1
    assert v.n_wins == 1
    assert v.total_pnl == pytest.approx(100.0)


def test_variant_state_add_loss():
    v = ABVariantState(name="A")
    v.add_outcome(-50.0)
    assert v.n_trades == 1
    assert v.n_wins == 0
    assert v.total_pnl == pytest.approx(-50.0)


def test_variant_state_win_rate():
    v = ABVariantState(name="A")
    v.add_outcome(100)
    v.add_outcome(-50)
    assert v.win_rate == pytest.approx(0.5)


def test_variant_state_win_rate_zero_trades():
    v = ABVariantState(name="A")
    assert v.win_rate == 0.0


def test_variant_state_profit_factor():
    v = ABVariantState(name="A")
    v.add_outcome(200)
    v.add_outcome(-100)
    # PF = 200 / 100 = 2.0
    assert v.profit_factor == pytest.approx(2.0)


def test_variant_state_profit_factor_no_losses():
    v = ABVariantState(name="A")
    v.add_outcome(100)
    assert v.profit_factor >= 10.0  # capped


def test_variant_state_sharpe():
    v = ABVariantState(name="A")
    for p in [100, 100, 100, -50, -50]:
        v.add_outcome(p)
    assert v.sharpe > 0


def test_variant_state_sharpe_zero_trades():
    v = ABVariantState(name="A")
    assert v.sharpe == 0.0


# ── ABStrategyTester — disabled ───────────────────────────────────────────────

def make_tester(enabled=True, overrides=None):
    cfg = {
        "ab_testing_enabled": enabled,
        "ab_variant_name": "VARIANT_A",
        "ab_variant_overrides": overrides or {},
        "ab_min_trades_for_significance": 5,
        "AI_THRESHOLD": 65,
    }
    return ABStrategyTester(cfg)


def test_disabled_evaluate_returns_decision():
    t = make_tester(enabled=False)
    d = t.evaluate_signal({"score": 70, "allowed": True})
    assert isinstance(d, ABSignalDecision)


def test_disabled_record_does_not_update():
    t = make_tester(enabled=False)
    t.record_trade_outcome("CONTROL", 100)
    assert t.control.n_trades == 0


def test_disabled_comparison_returns_result():
    t = make_tester(enabled=False)
    result = t.get_comparison()
    assert isinstance(result, ABComparisonResult)


# ── ABStrategyTester — enabled ────────────────────────────────────────────────

def test_evaluate_signal_both_enter_above_threshold():
    t = make_tester()
    d = t.evaluate_signal({"score": 80, "allowed": True})
    assert d.control_enter is True
    assert d.variant_enter is True


def test_evaluate_signal_both_reject_below_threshold():
    t = make_tester()
    d = t.evaluate_signal({"score": 40, "allowed": True})
    assert d.control_enter is False
    assert d.variant_enter is False


def test_evaluate_signal_variant_different_threshold():
    cfg = {
        "ab_testing_enabled": True,
        "ab_variant_name": "LOW_THRESH",
        "ab_variant_overrides": {"AI_THRESHOLD": 50},
        "ab_min_trades_for_significance": 5,
        "AI_THRESHOLD": 70,
    }
    t = ABStrategyTester(cfg)
    d = t.evaluate_signal({"score": 60, "allowed": True})
    # Control needs 70, variant needs 50 → control rejects, variant accepts
    assert d.control_enter is False
    assert d.variant_enter is True


def test_evaluate_signal_not_allowed():
    t = make_tester()
    d = t.evaluate_signal({"score": 80, "allowed": False})
    assert d.control_enter is False
    assert d.variant_enter is False


def test_record_control_outcome():
    t = make_tester()
    t.record_trade_outcome("CONTROL", 100.0)
    assert t.control.n_trades == 1


def test_record_variant_outcome():
    t = make_tester()
    t.record_trade_outcome("VARIANT_A", -50.0)
    assert t.variant.n_trades == 1


def test_record_control_and_variant():
    t = make_tester()
    t.record_trade_outcome("CONTROL", 100)
    t.record_trade_outcome("CONTROL", -50)
    t.record_trade_outcome("VARIANT_A", 200)
    assert t.control.n_trades == 2
    assert t.variant.n_trades == 1


# ── ABComparisonResult ────────────────────────────────────────────────────────

def test_comparison_insufficient_data():
    t = make_tester()
    t.record_trade_outcome("CONTROL", 100)
    result = t.get_comparison()
    assert result.winner == "INSUFFICIENT_DATA"
    assert result.min_trades_met is False


def test_comparison_enough_data_not_significant():
    t = make_tester()
    for _ in range(6):
        t.record_trade_outcome("CONTROL", 100)
        t.record_trade_outcome("VARIANT_A", 100)
    result = t.get_comparison()
    # Identical outcomes → not significant
    assert result.is_significant is False
    assert result.winner in ("NOT_SIGNIFICANT", "INSUFFICIENT_DATA", "CONTROL", "VARIANT_A")


def test_comparison_summary_non_empty():
    t = make_tester()
    result = t.get_comparison()
    assert isinstance(result.summary, str)
    assert len(result.summary) > 0


def test_comparison_p_value_range():
    t = make_tester()
    for _ in range(6):
        t.record_trade_outcome("CONTROL", 100)
        t.record_trade_outcome("VARIANT_A", -50)
    result = t.get_comparison()
    assert 0.0 <= result.p_value <= 1.0


# ── State persistence ─────────────────────────────────────────────────────────

def test_save_and_load_state():
    t = make_tester()
    t.record_trade_outcome("CONTROL", 100)
    t.record_trade_outcome("VARIANT_A", -50)

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        fpath = f.name

    try:
        t.save_state(fpath)
        t2 = make_tester()
        t2.load_state(fpath)
        assert t2.control.n_trades == 1
        assert t2.variant.n_trades == 1
    finally:
        os.unlink(fpath)


def test_load_state_missing_file_no_error():
    t = make_tester()
    t.load_state("/nonexistent/ab_state.json")  # should not raise
    assert t.control.n_trades == 0


def test_save_state_disabled_no_file():
    t = make_tester(enabled=False)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        fpath = f.name
    os.unlink(fpath)
    t.save_state(fpath)
    assert not os.path.exists(fpath)


def test_reset_clears_state():
    t = make_tester()
    t.record_trade_outcome("CONTROL", 100)
    t.record_trade_outcome("VARIANT_A", -50)
    t.reset()
    assert t.control.n_trades == 0
    assert t.variant.n_trades == 0


# ── _mann_whitney_p ───────────────────────────────────────────────────────────

def test_mann_whitney_p_identical_returns_high():
    p = _mann_whitney_p([100, 100, 100], [100, 100, 100])
    assert p >= 0.5


def test_mann_whitney_p_different_returns_low_ish():
    p = _mann_whitney_p([1000] * 50, [-1000] * 50)
    assert p <= 0.05


def test_mann_whitney_p_empty_returns_1():
    p = _mann_whitney_p([], [100, 100])
    assert p == 1.0


def test_mann_whitney_p_range():
    p = _mann_whitney_p([10, 20, 30], [-10, -20, -30])
    assert 0.0 <= p <= 1.0
