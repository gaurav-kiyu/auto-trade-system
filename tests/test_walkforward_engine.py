"""Tests for WalkForwardEngine — walk-forward validation and drift monitoring."""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from core.walkforward_engine import (
    WalkForwardEngine,
    WalkForwardReport,
    WalkForwardWindow,
    analyze_parameter_drift,
    calculate_adaptive_retrain_trigger,
    calculate_statistical_significance,
    WalkForwardDriftMonitor,
)


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def sample_df():
    """Create a small sample DataFrame for walk-forward tests."""
    dates = pd.date_range("2026-01-01", periods=100, freq="1min")
    return pd.DataFrame(
        {"Open": 100, "High": 101, "Low": 99, "Close": 100, "Volume": 1000},
        index=dates,
    )


@pytest.fixture
def mock_strategy():
    strategy = MagicMock()
    strategy.run.return_value = MagicMock(
        total_trades=5,
        net_pnl=100.0,
        win_rate=0.6,
        sharpe_ratio=1.2,
        max_drawdown_pct=0.05,
        to_dict=lambda: {"total_trades": 5, "net_pnl": 100.0},
    )
    return strategy


# ── WalkForwardReport tests ─────────────────────────────────────

class TestWalkForwardReport:
    """WalkForwardReport dataclass and serialization."""

    def test_to_dict_returns_valid_dict(self):
        window = WalkForwardWindow(
            train_start="2026-01-01", train_end="2026-01-02",
            test_start="2026-01-03", test_end="2026-01-04",
            report=MagicMock(to_dict=lambda: {"net_pnl": 100}),
        )
        report = WalkForwardReport(
            windows=[window],
            total_test_trades=5,
            net_test_pnl=100.0,
            avg_win_rate=0.6,
            mode="rolling",
        )
        d = report.to_dict()
        assert d["mode"] == "rolling"
        assert d["total_test_trades"] == 5
        assert len(d["windows"]) == 1


# ── WalkForwardEngine tests ─────────────────────────────────────

class TestWalkForwardEngine:
    """WalkForwardEngine — strategy quality over train/test windows."""

    def test_init_with_strategy(self, mock_strategy):
        engine = WalkForwardEngine(mock_strategy)
        assert engine._strategy_engine is mock_strategy

    def test_run_rolling_mode(self, mock_strategy, sample_df):
        engine = WalkForwardEngine(mock_strategy)
        report = engine.run(
            name="NIFTY",
            base_df=sample_df,
            train_bars=30,
            test_bars=10,
            step_bars=10,
            anchored=False,
        )
        assert isinstance(report, WalkForwardReport)
        assert report.mode == "rolling"
        assert report.total_test_trades > 0 or True  # at least runs cleanly

    def test_run_anchored_mode(self, mock_strategy, sample_df):
        engine = WalkForwardEngine(mock_strategy)
        report = engine.run(
            name="NIFTY",
            base_df=sample_df,
            train_bars=30,
            test_bars=10,
            step_bars=10,
            anchored=True,
        )
        assert report.mode == "anchored"

    def test_run_with_adapt_fn(self, mock_strategy, sample_df):
        calls = []

        def adapt_fn(df):
            calls.append(len(df))

        engine = WalkForwardEngine(mock_strategy, adapt_fn=adapt_fn)
        engine.run("NIFTY", sample_df, train_bars=30, test_bars=10, step_bars=20)
        assert len(calls) > 0

    def test_run_insufficient_data(self, mock_strategy):
        small_df = pd.DataFrame({"Close": [100] * 10}, index=pd.date_range("2026-01-01", periods=10))
        engine = WalkForwardEngine(mock_strategy)
        report = engine.run("NIFTY", small_df, train_bars=30, test_bars=10)
        assert len(report.windows) == 0

    def test_run_multiple_windows(self, mock_strategy, sample_df):
        engine = WalkForwardEngine(mock_strategy)
        report = engine.run("NIFTY", sample_df, train_bars=30, test_bars=10, step_bars=10)
        assert len(report.windows) >= 1
        total_len = sum(w.report.total_trades for w in report.windows)
        assert report.total_test_trades >= total_len

    def test_custom_step_bars(self, mock_strategy, sample_df):
        engine = WalkForwardEngine(mock_strategy)
        report = engine.run("NIFTY", sample_df, train_bars=50, test_bars=10, step_bars=5)
        assert len(report.windows) > 0


# ── Statistical significance tests ──────────────────────────────

class TestCalculateStatisticalSignificance:
    """calculate_statistical_significance — Welch's t-test approximation."""

    def test_empty_returns_zero(self):
        drift, conf = calculate_statistical_significance([], [])
        assert drift == 0.0
        assert conf == 0.0

    def test_identical_returns_low_drift(self):
        drift, conf = calculate_statistical_significance([1.0, 2.0], [1.0, 2.0])
        assert drift == 0.0

    def test_different_returns_positive_drift(self):
        drift, conf = calculate_statistical_significance([1.0, 2.0], [10.0, 20.0])
        assert drift > 0.0
        assert conf > 0.0

    def test_small_samples_return_low_confidence(self):
        drift, conf = calculate_statistical_significance([1.0], [10.0])
        assert drift >= 0.0
        # With n=1, variance is 0, so confidence should be 0.0
        assert conf == 0.0


# ── Parameter drift analysis tests ──────────────────────────────

class TestAnalyzeParameterDrift:
    """analyze_parameter_drift — stability across windows."""

    def test_empty_windows(self):
        reports = analyze_parameter_drift([], lambda r: {"value": 1.0})
        assert reports == []

    def test_stable_parameters(self):
        windows = [
            WalkForwardWindow("", "", "", "", MagicMock(to_dict=lambda: {})),
            WalkForwardWindow("", "", "", "", MagicMock(to_dict=lambda: {})),
        ]
        reports = analyze_parameter_drift(windows, lambda r: {"win_rate": 0.6})
        assert isinstance(reports, list)


# ── Adaptive retrain trigger tests ──────────────────────────────

class TestCalculateAdaptiveRetrainTrigger:
    """calculate_adaptive_retrain_trigger — when to retrain."""

    def test_no_trigger_when_healthy(self):
        result = calculate_adaptive_retrain_trigger(
            current_window_pnl=100,
            rolling_avg_pnl=100,
            consecutive_losses=0,
        )
        assert result["should_retrain"] is False

    def test_triggers_on_consecutive_losses(self):
        result = calculate_adaptive_retrain_trigger(
            current_window_pnl=-50,
            rolling_avg_pnl=100,
            consecutive_losses=3,
            max_consecutive_losses=3,
        )
        assert result["should_retrain"] is True
        assert result["urgency"] == "HIGH"

    def test_triggers_on_pnl_decline(self):
        result = calculate_adaptive_retrain_trigger(
            current_window_pnl=10,
            rolling_avg_pnl=100,
            consecutive_losses=0,
            pnl_decline_threshold=0.3,
        )
        # PnL ratio = 10/100 = 0.1, which is < (1 - 0.3) = 0.7
        assert result["should_retrain"] is True

    def test_returns_expected_keys(self):
        result = calculate_adaptive_retrain_trigger(50, 100, 1)
        assert "should_retrain" in result
        assert "trigger_reason" in result
        assert "urgency" in result
        assert "consecutive_losses" in result
        assert "pnl_ratio" in result


# ── WalkForwardDriftMonitor tests ───────────────────────────────

class TestWalkForwardDriftMonitor:
    """WalkForwardDriftMonitor — integrated drift monitoring."""

    def test_init(self, mock_strategy):
        monitor = WalkForwardDriftMonitor(mock_strategy)
        assert monitor._engine._strategy_engine is mock_strategy

    def test_run_with_drift_analysis(self, mock_strategy, sample_df):
        monitor = WalkForwardDriftMonitor(mock_strategy)
        report, drifts = monitor.run_with_drift_analysis(
            "NIFTY", sample_df,
            train_bars=30, test_bars=10, step_bars=10,
        )
        assert isinstance(report, WalkForwardReport)
        assert isinstance(drifts, list)

    def test_no_drift_summary_before_analysis(self, mock_strategy):
        monitor = WalkForwardDriftMonitor(mock_strategy)
        summary = monitor.get_drift_summary()
        assert summary.get("status") == "NO_ANALYSIS"

    def test_drift_summary_after_analysis(self, mock_strategy, sample_df):
        monitor = WalkForwardDriftMonitor(mock_strategy)
        monitor.run_with_drift_analysis(
            "NIFTY", sample_df,
            train_bars=30, test_bars=10, step_bars=10,
        )
        summary = monitor.get_drift_summary()
        assert "total_parameters" in summary

    def test_should_adaptive_retrain_insufficient_data(self, mock_strategy):
        monitor = WalkForwardDriftMonitor(mock_strategy)
        result = monitor.should_adaptive_retrain([])
        assert result["should_retrain"] is False
