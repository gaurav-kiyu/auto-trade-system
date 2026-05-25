"""Tests for core/slippage_model.py (v2.45 Item 14)."""
from core.slippage_model import (
    SlippageModel,
    _ols,
    calibrate_model,
    format_slippage_summary,
    predict_slippage,
)


def _make_model(intercept=0.05, lot_coeff=0.01, spread_coeff=0.2):
    return SlippageModel(
        intercept=intercept,
        lot_coeff=lot_coeff,
        spread_coeff=spread_coeff,
        r_squared=0.75,
        n_samples=50,
        calibrated_at="2026-04-30T10:00:00",
    )


# ── _ols ──────────────────────────────────────────────────────────────────────

def test_ols_perfect_fit():
    # y = 2 + 3*x  → intercept=2, coeff=3
    X = [[i] for i in range(5)]
    y = [2 + 3 * i for i in range(5)]
    coefs, r2 = _ols(X, y)
    assert abs(coefs[0] - 2.0) < 0.01
    assert abs(coefs[1] - 3.0) < 0.01
    assert abs(r2 - 1.0) < 0.01


def test_ols_returns_three_coefs():
    X = [[1.0, 0.5], [2.0, 0.8], [3.0, 1.2]]
    y = [1.0, 2.0, 3.0]
    coefs, r2 = _ols(X, y)
    assert len(coefs) == 3   # intercept + 2 features


def test_ols_r2_between_0_and_1():
    X = [[i, i * 0.5] for i in range(10)]
    y = [i + 0.1 for i in range(10)]
    _, r2 = _ols(X, y)
    assert 0.0 <= r2 <= 1.0


# ── predict_slippage ──────────────────────────────────────────────────────────

def test_predict_slippage_none_model():
    assert predict_slippage(5.0, 0.1, model=None) == 0.0


def test_predict_slippage_positive():
    m = _make_model(intercept=0.05, lot_coeff=0.01, spread_coeff=0.2)
    slip = predict_slippage(lot_size=3.0, spread_pct=0.5, model=m)
    # 0.05 + 0.01*3 + 0.2*0.5 = 0.05 + 0.03 + 0.10 = 0.18
    assert abs(slip - 0.18) < 0.001


def test_predict_slippage_clipped_to_zero():
    m = _make_model(intercept=-10.0, lot_coeff=0.0, spread_coeff=0.0)
    assert predict_slippage(1.0, 0.0, model=m) == 0.0


def test_predict_slippage_increases_with_lots():
    m = _make_model(lot_coeff=0.01)
    s1 = predict_slippage(1.0, 0.0, m)
    s5 = predict_slippage(5.0, 0.0, m)
    assert s5 > s1


def test_predict_slippage_increases_with_spread():
    m = _make_model(spread_coeff=0.5)
    s1 = predict_slippage(1.0, 0.1, m)
    s2 = predict_slippage(1.0, 0.5, m)
    assert s2 > s1


# ── calibrate_model ───────────────────────────────────────────────────────────

def test_calibrate_disabled_returns_none():
    result = calibrate_model(cfg={"slippage_model_enabled": False})
    assert result is None


def test_calibrate_no_db_returns_none():
    result = calibrate_model(
        db_path="nonexistent_slip_xyz.db",
        cfg={"slippage_model_enabled": True, "slippage_calibration_min_samples": 1},
    )
    assert result is None


# ── format_slippage_summary ───────────────────────────────────────────────────

def test_format_none_model():
    out = format_slippage_summary(None)
    assert "not calibrated" in out


def test_format_model_has_r2():
    out = format_slippage_summary(_make_model())
    assert "R²" in out


def test_format_model_has_n_samples():
    out = format_slippage_summary(_make_model())
    assert "n=50" in out
