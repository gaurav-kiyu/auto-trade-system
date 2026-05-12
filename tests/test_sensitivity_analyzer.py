"""Tests for core/sensitivity_analyzer.py (v2.44 Item 15)."""
import pytest
from core.sensitivity_analyzer import (
    ParameterTestPoint,
    SensitivityResult,
    DEFAULT_SENSITIVITY_PARAMS,
    run_single_parameter_sensitivity,
    run_sensitivity_analysis,
    format_sensitivity_report,
    load_trades_for_sensitivity,
    _apply_exit_param,
    _compute_stats,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_trades(n=20, win_frac=0.6):
    """Create a list of fake trade dicts."""
    trades = []
    for i in range(n):
        pnl = 100 if i < int(n * win_frac) else -50
        trades.append({
            "id": i + 1,
            "entry": 100.0,
            "net_pnl": pnl,
            "score": 70 + (i % 10),
            "iv": 15.0 + i * 0.5,
            "ts": f"2024-01-{(i % 28) + 1:02d}T10:00:00",
        })
    return trades


# ── DEFAULT_SENSITIVITY_PARAMS ────────────────────────────────────────────────

def test_default_params_has_sl_pct():
    assert "SL_PCT" in DEFAULT_SENSITIVITY_PARAMS


def test_default_params_has_target_pct():
    assert "TARGET_PCT" in DEFAULT_SENSITIVITY_PARAMS


def test_default_params_has_trail_pct():
    assert "TRAIL_PCT" in DEFAULT_SENSITIVITY_PARAMS


def test_default_params_has_ai_threshold():
    assert "AI_THRESHOLD" in DEFAULT_SENSITIVITY_PARAMS


def test_default_params_values_are_lists():
    for k, v in DEFAULT_SENSITIVITY_PARAMS.items():
        assert isinstance(v, list), f"{k} should be a list"
        assert len(v) >= 2, f"{k} should have at least 2 test values"


# ── _compute_stats ────────────────────────────────────────────────────────────

def test_compute_stats_win_rate():
    pnls = [100, 100, -50, -50, 100]
    wr, pf, sharpe, total = _compute_stats(pnls)
    assert wr == pytest.approx(3/5, abs=0.01)


def test_compute_stats_profit_factor():
    pnls = [100, 100, -50]
    _, pf, _, _ = _compute_stats(pnls)
    assert pf == pytest.approx(200 / 50, abs=0.01)


def test_compute_stats_empty():
    wr, pf, sharpe, total = _compute_stats([])
    assert wr == 0.0
    assert pf == 0.0
    assert sharpe == 0.0
    assert total == 0.0


def test_compute_stats_all_wins():
    pnls = [100, 200, 150]
    wr, pf, _, _ = _compute_stats(pnls)
    assert wr == 1.0
    assert pf >= 10.0  # no losses → capped at 10


def test_compute_stats_sharpe_positive_edge():
    pnls = [100] * 10 + [-20] * 2
    _, _, sharpe, _ = _compute_stats(pnls)
    assert sharpe > 0


# ── _apply_exit_param ─────────────────────────────────────────────────────────

def test_apply_sl_pct_scales_losses():
    trades = [{"net_pnl": -100, "entry": 100.0, "score": 70, "iv": 0}]
    cfg    = {"SL_PCT": 0.30}
    pnls   = _apply_exit_param(trades, "SL_PCT", 0.15, cfg)
    # Tighter SL → smaller losses → ratio ≈ 0.15/0.30 = 0.5
    assert pnls[0] == pytest.approx(-50.0, abs=1)


def test_apply_target_pct_scales_wins():
    trades = [{"net_pnl": 100, "entry": 100.0, "score": 70, "iv": 0}]
    cfg    = {"TARGET_PCT": 0.60}
    pnls   = _apply_exit_param(trades, "TARGET_PCT", 1.20, cfg)
    # Larger target → larger wins → ratio ≈ 1.20/0.60 = 2
    assert pnls[0] == pytest.approx(200.0, abs=1)


def test_apply_ai_threshold_filters():
    trades = [
        {"net_pnl": 100, "entry": 100.0, "score": 55, "iv": 0},  # below 60
        {"net_pnl": 100, "entry": 100.0, "score": 75, "iv": 0},  # above 60
    ]
    cfg  = {}
    pnls = _apply_exit_param(trades, "AI_THRESHOLD", 60.0, cfg)
    assert len(pnls) == 1
    assert pnls[0] == pytest.approx(100.0)


# ── run_single_parameter_sensitivity ─────────────────────────────────────────

def test_single_sensitivity_returns_result():
    trades = make_trades(30)
    result = run_single_parameter_sensitivity(
        "SL_PCT", [0.20, 0.30, 0.40], trades, {"SL_PCT": 0.30}
    )
    assert isinstance(result, SensitivityResult)
    assert result.param_name == "SL_PCT"


def test_single_sensitivity_test_points_count():
    trades = make_trades(30)
    result = run_single_parameter_sensitivity(
        "SL_PCT", [0.20, 0.30, 0.40], trades, {"SL_PCT": 0.30}
    )
    assert len(result.test_points) == 3


def test_single_sensitivity_verdict_set():
    trades = make_trades(30)
    result = run_single_parameter_sensitivity(
        "SL_PCT", [0.20, 0.25, 0.30, 0.35, 0.40], trades, {"SL_PCT": 0.30}
    )
    assert result.verdict in ("ROBUST", "SENSITIVE", "FRAGILE", "NO_DATA")


def test_single_sensitivity_no_trades_returns_no_data():
    result = run_single_parameter_sensitivity(
        "SL_PCT", [0.20, 0.30], [], {}
    )
    assert result.verdict == "NO_DATA"


def test_single_sensitivity_best_value_in_range():
    trades = make_trades(50)
    values = [0.20, 0.25, 0.30, 0.35, 0.40]
    result = run_single_parameter_sensitivity(
        "SL_PCT", values, trades, {"SL_PCT": 0.30}
    )
    if result.test_points:
        assert result.best_value in values


def test_single_sensitivity_insight_non_empty():
    trades = make_trades(30)
    result = run_single_parameter_sensitivity(
        "TARGET_PCT", [0.50, 0.60, 0.70], trades, {"TARGET_PCT": 0.60}
    )
    assert isinstance(result.insight, str)
    if result.verdict != "NO_DATA":
        assert len(result.insight) > 0


def test_single_sensitivity_test_point_fields():
    trades = make_trades(30)
    result = run_single_parameter_sensitivity(
        "SL_PCT", [0.30], trades, {"SL_PCT": 0.30}
    )
    if result.test_points:
        pt = result.test_points[0]
        assert hasattr(pt, "param_value")
        assert hasattr(pt, "n_trades")
        assert hasattr(pt, "win_rate")
        assert hasattr(pt, "profit_factor")
        assert hasattr(pt, "sharpe")
        assert hasattr(pt, "total_pnl")


# ── run_sensitivity_analysis ──────────────────────────────────────────────────

def test_run_sensitivity_no_trades_returns_list():
    results = run_sensitivity_analysis("/nonexistent.db", None, {})
    assert isinstance(results, list)


def test_run_sensitivity_returns_one_per_param():
    import os, sqlite3, tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY, ts TEXT, entry REAL, net_pnl REAL,
            score INTEGER, iv REAL, mode TEXT
        )
    """)
    for i in range(30):
        conn.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?)",
                     (i+1, "2024-01-15T10:00:00", 100.0,
                      100 if i < 18 else -50, 70, 15.0, "PAPER"))
    conn.commit()
    conn.close()
    try:
        params = {"SL_PCT": [0.20, 0.30]}
        results = run_sensitivity_analysis(tmp.name, params, {})
        assert len(results) == 1
        assert results[0].param_name == "SL_PCT"
    finally:
        os.unlink(tmp.name)


# ── format_sensitivity_report ─────────────────────────────────────────────────

def test_format_sensitivity_report_returns_string():
    trades = make_trades(30)
    results = [run_single_parameter_sensitivity(
        "SL_PCT", [0.20, 0.30, 0.40], trades, {"SL_PCT": 0.30}
    )]
    report = format_sensitivity_report(results)
    assert isinstance(report, str)
    assert "SL_PCT" in report


def test_format_sensitivity_report_empty():
    report = format_sensitivity_report([])
    assert "no results" in report.lower()


def test_format_sensitivity_report_contains_verdict():
    trades = make_trades(30)
    result = run_single_parameter_sensitivity(
        "SL_PCT", [0.20, 0.30, 0.40], trades, {"SL_PCT": 0.30}
    )
    report = format_sensitivity_report([result])
    assert any(v in report for v in ("ROBUST", "SENSITIVE", "FRAGILE", "NO_DATA"))
