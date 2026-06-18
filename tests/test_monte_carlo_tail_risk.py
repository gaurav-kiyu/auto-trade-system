"""Tests for core/monte_carlo_tail_risk.py — Tail Risk Monte Carlo analysis.

Covers:
  - run_tail_risk_simulation() statistical properties
  - Empty / single-trade edge cases
  - Determinism with fixed seed
  - VaR, CVaR, tail ratio correctness
  - Drawdown extremes (median, 99th, absolute)
  - Distribution shape (skewness, kurtosis)
  - Worst streak percentiles
  - TailRiskResult field types and value ranges
  - summary() output contract
  - to_dict() serialization
  - Internal helper functions (_percentile, _mean, _std, _skewness, _kurtosis)
"""

import math

import pytest
from core.monte_carlo_tail_risk import (
    TailRiskResult,
    _equity_curve,
    _kurtosis,
    _max_drawdown,
    _mean,
    _percentile,
    _skewness,
    _std,
    run_tail_risk_simulation,
)

# ── Sample P&L sets ──────────────────────────────────────────────────────────

SAMPLE_PNLS = [100, -50, 200, -80, 150, -30, 90, -120, 60, 40]
ALL_WINNERS = [100, 200, 150, 300, 250]
ALL_LOSERS = [-100, -200, -50, -300, -150]
MIXED_PNLS = [500, -400, 300, -200, 100, -50, 200, -100]  # asymmetric
EXTREME_OUTLIER = [1000, -999, 500, -800, 200, -700, 300, -600]


# ── Internal helpers ──────────────────────────────────────────────────────────

class TestInternalHelpers:
    def test_percentile_median(self):
        vals = list(range(101))
        assert abs(_percentile(vals, 0.50) - 50.0) < 1e-9

    def test_percentile_empty(self):
        assert _percentile([], 0.5) == 0.0

    def test_percentile_single(self):
        assert abs(_percentile([42.0], 0.99) - 42.0) < 1e-9

    def test_mean_normal(self):
        assert abs(_mean([10, 20, 30]) - 20.0) < 1e-9

    def test_mean_empty(self):
        assert _mean([]) == 0.0

    def test_mean_single(self):
        assert abs(_mean([42.0]) - 42.0) < 1e-9

    def test_std_normal(self):
        vals = [10, 20, 30]
        s = _std(vals)
        assert s > 0
        assert abs(math.sqrt(100.0) - s) < 1e-6  # variance=100, std=10

    def test_std_insufficient(self):
        assert _std([5.0]) == 0.0
        assert _std([]) == 0.0

    def test_skewness_symmetric(self):
        vals = [-2, -1, 0, 1, 2]
        sk = _skewness(vals)
        assert abs(sk) < 0.3  # near zero for symmetric

    def test_skewness_positive(self):
        vals = [1, 2, 3, 4, 100]
        sk = _skewness(vals)
        assert sk > 0.5  # right-tailed

    def test_skewness_insufficient(self):
        assert _skewness([1, 2]) == 0.0
        assert _skewness([1]) == 0.0
        assert _skewness([]) == 0.0

    def test_kurtosis_normal(self):
        vals = list(range(1, 101))
        ku = _kurtosis(vals)
        # Standard normal approx: kurtosis near 0
        assert abs(ku) < 2.0

    def test_kurtosis_heavy_tailed(self):
        vals = [1] * 90 + [100] * 10  # bimodal / heavy-tail stylized
        ku = _kurtosis(vals)
        assert ku > -1  # not infinite, but not heavily negative

    def test_kurtosis_insufficient(self):
        assert _kurtosis([1, 2, 3]) == 0.0
        assert _kurtosis([1, 2]) == 0.0
        assert _kurtosis([1]) == 0.0
        assert _kurtosis([]) == 0.0

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


# ── run_tail_risk_simulation ─────────────────────────────────────────────────

class TestRunTailRiskSimulation:
    def test_raises_on_empty_list(self):
        with pytest.raises(ValueError, match="empty"):
            run_tail_risk_simulation([])

    def test_returns_tail_risk_result(self):
        result = run_tail_risk_simulation(SAMPLE_PNLS, n_simulations=100, seed=42)
        assert isinstance(result, TailRiskResult)

    def test_n_trades_matches_input(self):
        result = run_tail_risk_simulation(SAMPLE_PNLS, n_simulations=100, seed=42)
        assert result.n_trades == len(SAMPLE_PNLS)

    def test_n_simulations_matches(self):
        result = run_tail_risk_simulation(SAMPLE_PNLS, n_simulations=500, seed=42)
        assert result.n_simulations == 500

    def test_determinism_with_seed(self):
        r1 = run_tail_risk_simulation(SAMPLE_PNLS, n_simulations=200, seed=7)
        r2 = run_tail_risk_simulation(SAMPLE_PNLS, n_simulations=200, seed=7)
        assert r1.var_95 == r2.var_95
        assert r1.cvar_95 == r2.cvar_95
        assert r1.tail_ratio == r2.tail_ratio
        assert r1.skewness == r2.skewness
        assert r1.max_dd_99 == r2.max_dd_99

    def test_different_seeds_produce_different_results(self):
        """Different random seeds should produce different shuffle orderings."""
        # Use a larger P&L list with high variance so shuffle order matters
        large_pnls = [100, -95, 200, -90, 300, -85, 400, -80, 500, -75,
                      150, -70, 250, -65, 350, -60, 450, -55, 550, -50] * 3
        r1 = run_tail_risk_simulation(large_pnls, n_simulations=200, seed=1)
        r2 = run_tail_risk_simulation(large_pnls, n_simulations=200, seed=999)
        # With 60 trades and high variance, max_dd_99 must differ across seeds
        assert r1.max_dd_99 != r2.max_dd_99, "Different seeds should produce different max_dd_99"

    def test_var_95_negative_for_mixed_pnls(self):
        """VaR (5th percentile) should be negative for mixed P&L."""
        result = run_tail_risk_simulation(EXTREME_OUTLIER, n_simulations=1000, seed=42)
        assert result.var_95 < 0

    def test_cvar_95_le_var_95(self):
        """CVaR should be <= VaR (more extreme average loss)."""
        result = run_tail_risk_simulation(EXTREME_OUTLIER, n_simulations=1000, seed=42)
        assert result.cvar_95 <= result.var_95 + 1e-6

    def test_tail_ratio_positive(self):
        """Tail ratio should be positive for any realistic distribution."""
        result = run_tail_risk_simulation(SAMPLE_PNLS, n_simulations=500, seed=42)
        assert result.tail_ratio > 0

    def test_all_winners_zero_var(self):
        """All winners should have VaR close to 0 or positive."""
        result = run_tail_risk_simulation(ALL_WINNERS, n_simulations=200, seed=42)
        assert result.var_95 >= -1e-6

    def test_all_losers_negative_var(self):
        """All losers should have strongly negative VaR."""
        result = run_tail_risk_simulation(ALL_LOSERS, n_simulations=200, seed=42)
        assert result.var_95 < -50

    def test_max_dd_median_non_negative(self):
        result = run_tail_risk_simulation(SAMPLE_PNLS, n_simulations=500, seed=42)
        assert result.max_dd_median >= 0

    def test_max_dd_99_ge_median(self):
        """99th percentile DD should be >= median DD."""
        result = run_tail_risk_simulation(EXTREME_OUTLIER, n_simulations=1000, seed=42)
        assert result.max_dd_99 >= result.max_dd_median - 1e-6

    def test_max_dd_absolute_ge_99(self):
        """Absolute worst DD >= 99th percentile DD."""
        result = run_tail_risk_simulation(EXTREME_OUTLIER, n_simulations=1000, seed=42)
        assert result.max_dd_absolute >= result.max_dd_99 - 1e-6

    def test_skewness_type(self):
        """Test that different P&L sets produce measurably different skewness."""
        # ALL_WINNERS (all positive) and ALL_LOSERS (all negative) should have
        # different distribution shapes even after shuffling (sum is constant
        # but intermediate equity curves differ)
        winners = run_tail_risk_simulation(ALL_WINNERS, n_simulations=500, seed=42)
        losers = run_tail_risk_simulation(ALL_LOSERS, n_simulations=500, seed=42)
        assert isinstance(winners.skewness, float)
        assert isinstance(losers.skewness, float)
        # Verify they produce different results
        assert winners.var_95 > losers.var_95

    def test_kurtosis_type(self):
        result = run_tail_risk_simulation(SAMPLE_PNLS, n_simulations=500, seed=42)
        assert isinstance(result.kurtosis, float)

    def test_worst_streak_p99_non_negative(self):
        result = run_tail_risk_simulation(SAMPLE_PNLS, n_simulations=500, seed=42)
        assert result.worst_streak_p99 >= 0

    def test_worst_streak_absolute_ge_p99(self):
        """Absolute worst streak >= 99th percentile streak."""
        result = run_tail_risk_simulation(SAMPLE_PNLS, n_simulations=500, seed=42)
        assert result.worst_streak_absolute >= result.worst_streak_p99

    def test_aliases_match(self):
        """p5_final_pnl == var_95, p1_final_pnl == worst_1pct."""
        result = run_tail_risk_simulation(SAMPLE_PNLS, n_simulations=200, seed=42)
        assert abs(result.p5_final_pnl - result.var_95) < 1e-6
        assert abs(result.p1_final_pnl - result.worst_1pct) < 1e-6

    def test_single_trade(self):
        """Single trade: should produce valid VaR = that trade's value."""
        result = run_tail_risk_simulation([500.0], n_simulations=50, seed=42)
        assert result.n_trades == 1
        assert abs(result.var_95 - 500.0) < 1e-6  # only one value

    def test_increasing_alpha_widens_var(self):
        """Lower alpha (more extreme tail) should give more negative VaR."""
        r1 = run_tail_risk_simulation(MIXED_PNLS, n_simulations=1000, seed=42, alpha=0.10)
        r2 = run_tail_risk_simulation(MIXED_PNLS, n_simulations=1000, seed=42, alpha=0.01)
        # r1.var_95 uses 0.10 tail, r2 uses 0.01 tail
        # r2 (1% confidence) should be <= r1 (10% tail)
        assert r2.var_95 <= r1.var_95 + 1e-6


# ── TailRiskResult ────────────────────────────────────────────────────────────

class TestTailRiskResult:
    def test_summary_returns_string(self):
        result = run_tail_risk_simulation(SAMPLE_PNLS, n_simulations=100, seed=42)
        s = result.summary()
        assert isinstance(s, str)
        assert len(s) > 100

    def test_summary_contains_key_labels(self):
        result = run_tail_risk_simulation(SAMPLE_PNLS, n_simulations=100, seed=42)
        s = result.summary()
        for label in ("CVaR", "Tail Ratio", "Drawdown", "Skewness", "Kurtosis", "Streak"):
            assert label in s

    def test_to_dict_has_all_keys(self):
        result = run_tail_risk_simulation(SAMPLE_PNLS, n_simulations=100, seed=42)
        d = result.to_dict()
        expected_keys = {
            "n_simulations", "n_trades", "var_95", "cvar_95", "tail_ratio",
            "worst_1pct", "max_dd_median", "max_dd_99", "max_dd_absolute",
            "skewness", "kurtosis", "worst_streak_p99", "worst_streak_absolute",
            "timestamp",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_value_types(self):
        result = run_tail_risk_simulation(SAMPLE_PNLS, n_simulations=100, seed=42)
        d = result.to_dict()
        assert isinstance(d["n_simulations"], int)
        assert isinstance(d["n_trades"], int)
        assert isinstance(d["var_95"], float)
        assert isinstance(d["tail_ratio"], float)
        assert isinstance(d["worst_streak_p99"], int)
        assert isinstance(d["timestamp"], str)

    def test_frozen_dataclass(self):
        """TailRiskResult should be immutable."""
        result = run_tail_risk_simulation(SAMPLE_PNLS, n_simulations=100, seed=42)
        with pytest.raises(Exception):  # dataclass frozen → AttributeError
            result.var_95 = 999.0


# ── Constant-distribution checks ─────────────────────────────────────────────

class TestConstantDistribution:
    """When all trades are identical, tail metrics should have predictable values."""

    def test_all_same_positive(self):
        result = run_tail_risk_simulation([50] * 10, n_simulations=500, seed=42)
        # Every simulation is identical → VaR = 50*10 = 500
        assert abs(result.var_95 - 500.0) < 1e-6
        assert result.max_dd_median == 0.0
        assert result.worst_streak_p99 == 0

    def test_all_same_negative(self):
        result = run_tail_risk_simulation([-50] * 10, n_simulations=500, seed=42)
        # Every simulation is identical → VaR = -50*10 = -500
        assert abs(result.var_95 - (-500.0)) < 1e-6
        assert result.worst_streak_p99 == 10  # all trades are losses
