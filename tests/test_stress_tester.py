"""Tests for core/stress_tester.py (v2.45 Item 8)."""
from core.stress_tester import _greek_shock, format_stress_summary, run_stress_test


def _pos(delta=100.0, vega=50.0, theta=20.0, vix=15.0, lots=1.0, name="NIFTY_CE"):
    return {"delta": delta, "vega": vega, "theta": theta, "vix": vix, "lots": lots, "name": name}


# ── disabled ──────────────────────────────────────────────────────────────────

def test_disabled_returns_empty():
    result = run_stress_test([_pos()], 100000, {"stress_test_enabled": False})
    assert result == []


def test_no_positions_returns_empty():
    result = run_stress_test([], 100000, {"stress_test_enabled": True})
    assert result == []


def test_zero_capital_returns_empty():
    result = run_stress_test([_pos()], 0, {"stress_test_enabled": True})
    assert result == []


# ── flash crash scenario ──────────────────────────────────────────────────────

def test_flash_crash_negative_for_call():
    # CALL position: delta>0, vega=0 to isolate delta effect only
    # Flash crash: index -3% → delta shock = 100 × (-3.0) = -300
    pos = _pos(delta=100.0, vega=0.0, theta=0.0, vix=15.0, lots=1.0)
    results = run_stress_test([pos], 100000, {"stress_test_enabled": True})
    fc = next(r for r in results if r.scenario == "FLASH_CRASH")
    assert fc.total_pnl_shock < 0  # pure delta loss on crash


# ── gap up scenario ───────────────────────────────────────────────────────────

def test_gap_up_positive_for_call():
    pos = _pos(delta=100.0, vega=0.0, theta=0.0, vix=15.0, lots=1.0)
    results = run_stress_test([pos], 100000, {"stress_test_enabled": True})
    gu = next(r for r in results if r.scenario == "GAP_UP")
    assert gu.total_pnl_shock > 0  # index +1.8% with positive delta


# ── all 4 built-in scenarios present ─────────────────────────────────────────

def test_all_builtin_scenarios_present():
    results = run_stress_test([_pos()], 100000, {"stress_test_enabled": True})
    names = [r.scenario for r in results]
    assert "FLASH_CRASH" in names
    assert "SLOW_GRIND" in names
    assert "GAP_UP" in names
    assert "EXPIRY_CRUSH" in names


# ── Greeks sign correctness ───────────────────────────────────────────────────

def test_put_position_benefits_from_crash():
    # PUT: delta < 0 (profits when index falls)
    pos = _pos(delta=-100.0, vega=50.0, theta=10.0, vix=15.0, lots=1.0)
    results = run_stress_test([pos], 100000, {"stress_test_enabled": True})
    fc = next(r for r in results if r.scenario == "FLASH_CRASH")
    # index_shock = -100 × (-3.0) = +300 (positive for put on crash)
    assert fc.total_pnl_shock > 0


def test_theta_reduces_pnl():
    # High theta position → expiry crush penalises it
    pos_high_theta = _pos(delta=0.0, vega=0.0, theta=100.0, vix=15.0, lots=1.0)
    pos_low_theta  = _pos(delta=0.0, vega=0.0, theta=1.0,   vix=15.0, lots=1.0)
    results_high = run_stress_test([pos_high_theta], 100000, {"stress_test_enabled": True})
    results_low  = run_stress_test([pos_low_theta],  100000, {"stress_test_enabled": True})
    ec_high = next(r for r in results_high if r.scenario == "EXPIRY_CRUSH")
    ec_low  = next(r for r in results_low  if r.scenario == "EXPIRY_CRUSH")
    assert ec_high.total_pnl_shock < ec_low.total_pnl_shock


# ── alert ─────────────────────────────────────────────────────────────────────

def test_alert_fires_on_large_loss():
    # Large positive delta + crash → massive loss; pct_of_capital < -10% triggers alert
    pos = _pos(delta=50000.0, vega=0.0, theta=0.0, vix=15.0, lots=1.0)
    results = run_stress_test([pos], 100000, {"stress_test_enabled": True, "max_stress_loss_pct": 10.0})
    fc = next(r for r in results if r.scenario == "FLASH_CRASH")
    # delta=50000 × (-3%) = -150000 → -150% of capital → alert fires
    assert fc.pct_of_capital < 0
    assert fc.alert is True


# ── pct of capital ────────────────────────────────────────────────────────────

def test_pct_of_capital_calculation():
    pos = _pos(delta=100.0, vega=0.0, theta=0.0, vix=15.0, lots=1.0)
    results = run_stress_test([pos], 100000, {"stress_test_enabled": True})
    for r in results:
        assert isinstance(r.pct_of_capital, float)


# ── custom scenarios ──────────────────────────────────────────────────────────

def test_custom_scenario_added():
    custom = [{"name": "BLACK_SWAN", "index_move_pct": -8.0, "vix_mult": 3.0, "time_mins": 10}]
    results = run_stress_test([_pos()], 100000, {
        "stress_test_enabled": True, "stress_custom_scenarios": custom
    })
    names = [r.scenario for r in results]
    assert "BLACK_SWAN" in names


# ── format ────────────────────────────────────────────────────────────────────

def test_format_summary_string():
    results = run_stress_test([_pos()], 100000, {"stress_test_enabled": True})
    s = format_stress_summary(results)
    assert isinstance(s, str)
    assert "Stress" in s


def test_format_no_positions():
    s = format_stress_summary([])
    assert "no positions" in s.lower()


# ── _greek_shock ──────────────────────────────────────────────────────────────

def test_greek_shock_zero_position():
    shock = _greek_shock({}, 0.0, 1.0, 0.0)
    assert shock == 0.0


def test_greek_shock_lots_multiplier():
    pos1 = _pos(delta=100.0, vega=0.0, theta=0.0, lots=1.0)
    pos2 = _pos(delta=100.0, vega=0.0, theta=0.0, lots=2.0)
    s1 = _greek_shock(pos1, -3.0, 1.0, 0.0)
    s2 = _greek_shock(pos2, -3.0, 1.0, 0.0)
    assert abs(s2 - 2 * s1) < 0.01
