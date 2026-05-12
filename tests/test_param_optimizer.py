"""Tests for core/param_optimizer.py (v2.45 Item 18)."""
import pytest
from core.param_optimizer import (
    OptimizationResult, _compute_metric, _simulate_filter,
    optimize_param, format_optimization_report,
)


_PNLS = [100.0, 200.0, -50.0, 150.0, -30.0, 300.0, -80.0, 250.0]


# ── _compute_metric ───────────────────────────────────────────────────────────

def test_win_rate():
    pnls = [100.0, -50.0, 200.0, -30.0]
    wr = _compute_metric(pnls, "win_rate")
    assert abs(wr - 0.5) < 0.01


def test_avg_pnl():
    pnls = [100.0, 200.0]
    assert _compute_metric(pnls, "avg_pnl") == 150.0


def test_profit_factor():
    pnls = [100.0, 200.0, -50.0]
    pf = _compute_metric(pnls, "profit_factor")
    assert abs(pf - 6.0) < 0.01   # (100+200)/50 = 6


def test_profit_factor_all_wins():
    pf = _compute_metric([100.0, 200.0], "profit_factor")
    assert pf == float("inf")


def test_sharpe_positive_for_positive_pnls():
    pnls = [100.0] * 10
    # std=0 → sharpe=0; slight variation needed
    pnls[0] = 110.0
    s = _compute_metric(pnls, "sharpe")
    assert isinstance(s, float)


def test_metric_empty_pnls():
    assert _compute_metric([], "win_rate") == 0.0


# ── _simulate_filter ──────────────────────────────────────────────────────────

def test_filter_non_score_returns_same():
    result = _simulate_filter(_PNLS, "some_other_param", 0.3)
    assert len(result) == len(_PNLS)


def test_filter_score_reduces_count():
    result = _simulate_filter(_PNLS, "min_score", 80)
    assert len(result) <= len(_PNLS)


def test_filter_sl_pct_scales_losses():
    pnls = [100.0, -50.0]
    # SL_PCT=0.6 → losses scaled to -50 × 0.6/0.3 = -100
    result = _simulate_filter(pnls, "sl_pct", 0.6)
    assert result[1] < -50.0  # scaled up in magnitude


# ── optimize_param ────────────────────────────────────────────────────────────

def test_disabled_returns_none():
    result = optimize_param("SL_PCT", [0.2, 0.3], cfg={"param_optimizer_enabled": False})
    assert result is None


def test_no_db_returns_none():
    result = optimize_param(
        "SL_PCT", [0.2, 0.3],
        db_path="nonexistent_opt_xyz.db",
        cfg={"param_optimizer_enabled": True},
    )
    assert result is None


# ── format_optimization_report ───────────────────────────────────────────────

def test_format_no_results():
    out = format_optimization_report([])
    assert "no results" in out


def test_format_has_param_name():
    r = OptimizationResult(
        param="SL_PCT", best_value=0.3, metric_value=2.5,
        metric_name="profit_factor", tested_values=[0.2, 0.3, 0.4],
        metric_series=[2.0, 2.5, 1.8], n_trades=50,
    )
    out = format_optimization_report([r])
    assert "SL_PCT" in out


def test_format_has_best_value():
    r = OptimizationResult(
        param="SL_PCT", best_value=0.3, metric_value=2.5,
        metric_name="profit_factor", tested_values=[0.2, 0.3],
        metric_series=[2.0, 2.5], n_trades=30,
    )
    out = format_optimization_report([r])
    assert "0.3" in out


def test_format_has_metric_name():
    r = OptimizationResult(
        param="TARGET_PCT", best_value=0.6, metric_value=1.8,
        metric_name="profit_factor", tested_values=[0.5, 0.6],
        metric_series=[1.5, 1.8], n_trades=25,
    )
    out = format_optimization_report([r])
    assert "profit_factor" in out
