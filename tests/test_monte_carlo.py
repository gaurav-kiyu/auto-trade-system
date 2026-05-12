"""
Tests for core/monte_carlo.py (Phase A4).

Covers:
  - run_simulation() statistical properties
  - Empty / single-trade edge cases
  - Determinism with fixed seed
  - Non-determinism without seed
  - equity band arrays length matches n_trades
  - plot_equity_band() rendering
  - format_summary() output contract
  - load_pnl_from_db() file-not-found guard
  - MonteCarloResult field types and value ranges
"""
import math
import sqlite3
import os

import pytest

from core.monte_carlo import (
    run_simulation,
    plot_equity_band,
    format_summary,
    load_pnl_from_db,
    MonteCarloResult,
    _equity_curve,
    _max_drawdown,
    _sharpe,
    _max_consec_losses,
    _percentile,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db(tmp_path, pnls):
    """Create a minimal trades.db with given net_pnl values."""
    p = tmp_path / "trades.db"
    conn = sqlite3.connect(str(p))
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY,
            ts TEXT,
            net_pnl REAL,
            mode TEXT
        )
    """)
    import datetime
    for i, v in enumerate(pnls):
        ts = (datetime.datetime(2025, 1, 1) + datetime.timedelta(hours=i)).isoformat()
        conn.execute("INSERT INTO trades (ts, net_pnl, mode) VALUES (?,?,?)",
                     (ts, v, "PAPER"))
    conn.commit()
    conn.close()
    return str(p)


SAMPLE_PNLS = [100, -50, 200, -80, 150, -30, 90, -120, 60, 40]


# ── Internal helpers ──────────────────────────────────────────────────────────

class TestInternalHelpers:
    def test_equity_curve_cumulative(self):
        eq = _equity_curve([10, -5, 20])
        assert eq == [10, 5, 25]

    def test_equity_curve_empty(self):
        assert _equity_curve([]) == []

    def test_max_drawdown_flat(self):
        eq = [10, 10, 10]
        assert _max_drawdown(eq) == 0.0

    def test_max_drawdown_decline(self):
        eq = [100, 80, 60]
        assert abs(_max_drawdown(eq) - 40.0) < 1e-9

    def test_max_drawdown_recovery(self):
        eq = [100, 60, 120, 80]
        assert abs(_max_drawdown(eq) - 40.0) < 1e-9

    def test_sharpe_zero_std(self):
        assert _sharpe([5, 5, 5]) == 0.0

    def test_sharpe_positive_edge(self):
        pnls = [100] * 10 + [-10] * 5
        s = _sharpe(pnls)
        assert s > 0

    def test_sharpe_single_trade(self):
        assert _sharpe([100]) == 0.0

    def test_max_consec_losses_none(self):
        assert _max_consec_losses([10, 20, 30]) == 0

    def test_max_consec_losses_streak(self):
        assert _max_consec_losses([-1, -2, -3, 10, -4]) == 3

    def test_percentile_median(self):
        vals = list(range(101))
        assert _percentile(vals, 0.50) == 50.0

    def test_percentile_empty(self):
        assert _percentile([], 0.5) == 0.0

    def test_percentile_single(self):
        assert _percentile([42.0], 0.99) == 42.0


# ── run_simulation ────────────────────────────────────────────────────────────

class TestRunSimulation:
    def test_raises_on_empty_list(self):
        with pytest.raises(ValueError, match="empty"):
            run_simulation([])

    def test_returns_monte_carlo_result(self):
        result = run_simulation(SAMPLE_PNLS, n_simulations=100, seed=42)
        assert isinstance(result, MonteCarloResult)

    def test_n_trades_matches_input(self):
        result = run_simulation(SAMPLE_PNLS, n_simulations=100, seed=42)
        assert result.n_trades == len(SAMPLE_PNLS)

    def test_n_simulations_matches(self):
        result = run_simulation(SAMPLE_PNLS, n_simulations=200, seed=42)
        assert result.n_simulations == 200

    def test_determinism_with_seed(self):
        r1 = run_simulation(SAMPLE_PNLS, n_simulations=100, seed=7)
        r2 = run_simulation(SAMPLE_PNLS, n_simulations=100, seed=7)
        assert r1.median_final_pnl == r2.median_final_pnl
        assert r1.p95_max_drawdown == r2.p95_max_drawdown

    def test_different_seeds_produce_different_paths(self):
        # Final PnL is always sum-of-trades (constant regardless of shuffle order).
        # Intermediate equity percentiles will differ between seeds.
        r1 = run_simulation(SAMPLE_PNLS, n_simulations=100, seed=1)
        r2 = run_simulation(SAMPLE_PNLS, n_simulations=100, seed=999)
        mid = len(SAMPLE_PNLS) // 2
        assert r1.equity_p5[mid] != r2.equity_p5[mid] or r1.equity_p95[mid] != r2.equity_p95[mid]

    def test_prob_of_profit_range(self):
        result = run_simulation(SAMPLE_PNLS, n_simulations=200, seed=42)
        assert 0.0 <= result.prob_of_profit <= 1.0

    def test_p5_le_median_le_p95(self):
        result = run_simulation(SAMPLE_PNLS, n_simulations=500, seed=42)
        assert result.p5_final_pnl <= result.median_final_pnl
        assert result.median_final_pnl <= result.p95_final_pnl

    def test_drawdown_non_negative(self):
        result = run_simulation(SAMPLE_PNLS, n_simulations=100, seed=42)
        assert result.median_max_drawdown >= 0
        assert result.p95_max_drawdown >= 0

    def test_equity_bands_length(self):
        result = run_simulation(SAMPLE_PNLS, n_simulations=100, seed=42)
        n = len(SAMPLE_PNLS)
        assert len(result.equity_p5)  == n
        assert len(result.equity_p50) == n
        assert len(result.equity_p95) == n

    def test_equity_p5_le_p95_everywhere(self):
        result = run_simulation(SAMPLE_PNLS, n_simulations=200, seed=42)
        for p5v, p95v in zip(result.equity_p5, result.equity_p95):
            assert p5v <= p95v + 1e-6

    def test_single_trade(self):
        result = run_simulation([500.0], n_simulations=50, seed=42)
        assert result.n_trades == 1
        assert result.equity_p5 == []
        assert result.equity_p50 == []
        assert result.equity_p95 == []

    def test_all_winners(self):
        result = run_simulation([100, 200, 150], n_simulations=100, seed=42)
        assert result.prob_of_profit == 1.0

    def test_all_losers(self):
        result = run_simulation([-100, -200, -50], n_simulations=100, seed=42)
        assert result.prob_of_profit == 0.0

    def test_worst_streak_p95_non_negative(self):
        result = run_simulation(SAMPLE_PNLS, n_simulations=200, seed=42)
        assert result.worst_case_streak_p95 >= 0

    def test_sharpe_p5_le_median(self):
        result = run_simulation(SAMPLE_PNLS, n_simulations=500, seed=42)
        assert result.p5_sharpe <= result.median_sharpe + 1e-6


# ── plot_equity_band ──────────────────────────────────────────────────────────

class TestPlotEquityBand:
    def test_returns_string(self):
        result = run_simulation(SAMPLE_PNLS, n_simulations=100, seed=42)
        chart = plot_equity_band(result)
        assert isinstance(chart, str)

    def test_contains_box_chars(self):
        result = run_simulation(SAMPLE_PNLS, n_simulations=100, seed=42)
        chart = plot_equity_band(result)
        assert "┌" in chart and "┘" in chart

    def test_single_trade_fallback_message(self):
        result = run_simulation([100.0], n_simulations=50, seed=42)
        chart = plot_equity_band(result)
        assert "Insufficient" in chart

    def test_footer_contains_prob(self):
        result = run_simulation(SAMPLE_PNLS, n_simulations=100, seed=42)
        chart = plot_equity_band(result)
        assert "Prob>0" in chart


# ── format_summary ────────────────────────────────────────────────────────────

class TestFormatSummary:
    def test_returns_non_empty_string(self):
        result = run_simulation(SAMPLE_PNLS, n_simulations=100, seed=42)
        s = format_summary(result)
        assert isinstance(s, str) and len(s) > 50

    def test_contains_key_labels(self):
        result = run_simulation(SAMPLE_PNLS, n_simulations=100, seed=42)
        s = format_summary(result)
        for label in ("Prob of Profit", "Drawdown", "Sharpe", "Streak"):
            assert label in s


# ── load_pnl_from_db ──────────────────────────────────────────────────────────

class TestLoadPnlFromDb:
    def test_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_pnl_from_db(str(tmp_path / "nosuch.db"))

    def test_loads_correct_values(self, tmp_path):
        pnls = [100.0, -50.0, 200.0]
        db_path = _make_db(tmp_path, pnls)
        loaded = load_pnl_from_db(db_path, days=0)
        assert len(loaded) == 3
        assert abs(sum(loaded) - 250.0) < 1e-6

    def test_days_filter_excludes_old(self, tmp_path):
        import datetime, sqlite3
        p = tmp_path / "t.db"
        conn = sqlite3.connect(str(p))
        conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, ts TEXT, net_pnl REAL, mode TEXT)")
        old_ts = (datetime.datetime.utcnow() - datetime.timedelta(days=120)).isoformat()
        new_ts = (datetime.datetime.utcnow() - datetime.timedelta(days=5)).isoformat()
        conn.execute("INSERT INTO trades (ts,net_pnl,mode) VALUES (?,?,?)", (old_ts, 999.0, "PAPER"))
        conn.execute("INSERT INTO trades (ts,net_pnl,mode) VALUES (?,?,?)", (new_ts, 100.0, "PAPER"))
        conn.commit(); conn.close()
        loaded = load_pnl_from_db(str(p), days=30)
        assert len(loaded) == 1
        assert abs(loaded[0] - 100.0) < 1e-6

    def test_mode_filter(self, tmp_path):
        import datetime, sqlite3
        p = tmp_path / "t2.db"
        conn = sqlite3.connect(str(p))
        conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, ts TEXT, net_pnl REAL, mode TEXT)")
        ts = datetime.datetime.utcnow().isoformat()
        conn.execute("INSERT INTO trades (ts,net_pnl,mode) VALUES (?,?,?)", (ts, 111.0, "PAPER"))
        conn.execute("INSERT INTO trades (ts,net_pnl,mode) VALUES (?,?,?)", (ts, 222.0, "LIVE"))
        conn.commit(); conn.close()
        loaded = load_pnl_from_db(str(p), days=0, mode="PAPER")
        assert len(loaded) == 1
        assert abs(loaded[0] - 111.0) < 1e-6
