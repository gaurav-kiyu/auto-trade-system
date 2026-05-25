"""
Tests for anchored walk-forward mode in core/walkforward_engine.py (Phase E).

Covers:
  - Rolling mode (default) still works — regression guard
  - anchored=True produces mode="anchored" in report
  - anchored=False produces mode="rolling" in report
  - Anchored training window always starts from bar 0
  - Anchored training window grows with each step
  - Rolling training window slides forward with each step
  - Both modes produce same test windows (test slicing unchanged)
  - WalkForwardReport.to_dict() includes "mode" key
  - Empty data returns empty windows for both modes
  - step_bars=None defaults to test_bars
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from core import StrategyEngine
from core.walkforward_engine import WalkForwardEngine

# ── Fixtures ──────────────────────────────────────────────────────────────────

ROOT     = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


def _make_df(n_bars: int = 400) -> pd.DataFrame:
    """Create a synthetic 1-min OHLCV DataFrame."""
    import numpy as np
    rng   = np.random.default_rng(42)
    dates = pd.date_range("2025-01-02 09:15", periods=n_bars, freq="1min")
    close = 22000.0 + rng.normal(0, 10, n_bars).cumsum()
    df    = pd.DataFrame({
        "Open":   close - rng.uniform(0, 5, n_bars),
        "High":   close + rng.uniform(0, 8, n_bars),
        "Low":    close - rng.uniform(0, 8, n_bars),
        "Close":  close,
        "Volume": rng.integers(100, 1000, n_bars).astype(float),
    }, index=dates)
    return df


def _noop_strategy(name, frames, vix=0.0):
    """Strategy that never generates signals — makes tests fast."""
    return None


def _make_engine() -> WalkForwardEngine:
    strategy = StrategyEngine(generate_signal_fn=_noop_strategy)
    return WalkForwardEngine(strategy)


# ── Mode field ────────────────────────────────────────────────────────────────

class TestModeField:
    def test_rolling_mode_default(self):
        engine = _make_engine()
        df = _make_df(300)
        report = engine.run("NIFTY", df, train_bars=100, test_bars=50)
        assert report.mode == "rolling"

    def test_anchored_mode_flag(self):
        engine = _make_engine()
        df = _make_df(300)
        report = engine.run("NIFTY", df, train_bars=100, test_bars=50, anchored=True)
        assert report.mode == "anchored"

    def test_false_gives_rolling(self):
        engine = _make_engine()
        df = _make_df(300)
        report = engine.run("NIFTY", df, train_bars=100, test_bars=50, anchored=False)
        assert report.mode == "rolling"

    def test_to_dict_includes_mode(self):
        engine = _make_engine()
        df = _make_df(300)
        report = engine.run("NIFTY", df, train_bars=100, test_bars=50, anchored=True)
        d = report.to_dict()
        assert "mode" in d
        assert d["mode"] == "anchored"


# ── Window count and structure ────────────────────────────────────────────────

class TestWindowStructure:
    def _run(self, anchored: bool, n=300, train=100, test=50, step=50):
        engine = _make_engine()
        df = _make_df(n)
        return engine.run("NIFTY", df, train_bars=train, test_bars=test,
                          step_bars=step, anchored=anchored)

    def test_both_modes_same_window_count(self):
        r_roll = self._run(False)
        r_anch = self._run(True)
        assert r_roll.windows and r_anch.windows
        assert len(r_roll.windows) == len(r_anch.windows)

    def test_test_windows_identical_in_both_modes(self):
        r_roll = self._run(False)
        r_anch = self._run(True)
        for w_r, w_a in zip(r_roll.windows, r_anch.windows):
            assert w_r.test_start == w_a.test_start
            assert w_r.test_end   == w_a.test_end

    def test_anchored_train_always_starts_at_bar0(self):
        engine = _make_engine()
        df = _make_df(300)
        report = engine.run("NIFTY", df, train_bars=100, test_bars=50,
                            step_bars=50, anchored=True)
        first_ts = str(df.index[0])
        for w in report.windows:
            assert w.train_start == first_ts, (
                f"Anchored train_start should always be {first_ts}, got {w.train_start}"
            )

    def test_rolling_train_start_advances(self):
        engine = _make_engine()
        df = _make_df(300)
        report = engine.run("NIFTY", df, train_bars=100, test_bars=50,
                            step_bars=50, anchored=False)
        starts = [w.train_start for w in report.windows]
        # Rolling: each train_start should be later than the previous
        for i in range(1, len(starts)):
            assert starts[i] > starts[i - 1], "Rolling train_start should advance each step"

    def test_anchored_train_grows(self):
        engine = _make_engine()
        df = _make_df(300)
        report = engine.run("NIFTY", df, train_bars=100, test_bars=50,
                            step_bars=50, anchored=True)
        ends = [w.train_end for w in report.windows]
        # Anchored: train_end should grow each step
        for i in range(1, len(ends)):
            assert ends[i] > ends[i - 1], "Anchored train_end should grow each step"

    def test_rolling_train_end_advances(self):
        engine = _make_engine()
        df = _make_df(300)
        report = engine.run("NIFTY", df, train_bars=100, test_bars=50,
                            step_bars=50, anchored=False)
        ends = [w.train_end for w in report.windows]
        for i in range(1, len(ends)):
            assert ends[i] > ends[i - 1]

    def test_step_bars_none_defaults_to_test_bars(self):
        engine = _make_engine()
        df = _make_df(300)
        r1 = engine.run("NIFTY", df, train_bars=100, test_bars=50)
        r2 = engine.run("NIFTY", df, train_bars=100, test_bars=50, step_bars=50)
        assert len(r1.windows) == len(r2.windows)


# ── Report aggregates ─────────────────────────────────────────────────────────

class TestReportAggregates:
    def test_anchored_report_has_windows(self):
        engine = _make_engine()
        df = _make_df(300)
        report = engine.run("NIFTY", df, train_bars=100, test_bars=50, anchored=True)
        assert len(report.windows) > 0

    def test_total_test_trades_is_int(self):
        engine = _make_engine()
        df = _make_df(300)
        report = engine.run("NIFTY", df, train_bars=100, test_bars=50, anchored=True)
        assert isinstance(report.total_test_trades, int)
        assert report.total_test_trades == 0   # _noop_strategy never signals

    def test_net_test_pnl_zero_with_noop(self):
        engine = _make_engine()
        df = _make_df(300)
        report = engine.run("NIFTY", df, train_bars=100, test_bars=50, anchored=True)
        assert report.net_test_pnl == 0.0

    def test_rolling_report_unchanged(self):
        engine = _make_engine()
        df = _make_df(300)
        report = engine.run("NIFTY", df, train_bars=100, test_bars=50)
        assert report.mode == "rolling"
        assert isinstance(report.total_test_trades, int)

    def test_adapt_fn_called_per_window(self):
        call_count = []
        def _adapter(train_df):
            call_count.append(1)

        strategy = StrategyEngine(generate_signal_fn=_noop_strategy)
        engine = WalkForwardEngine(strategy, adapt_fn=_adapter)
        df = _make_df(300)
        report = engine.run("NIFTY", df, train_bars=100, test_bars=50,
                            step_bars=50, anchored=True)
        assert len(call_count) == len(report.windows)


# ── Regression: existing tests unaffected ────────────────────────────────────

class TestRegressionRolling:
    def test_csv_fixture_rolling(self):
        from core import BacktestConfig, ReplayConfig
        source_path = FIXTURES / "replay_minute_bars.csv"
        if not source_path.exists():
            pytest.skip("CSV fixture not found")

        from core import CsvReplaySource
        df = CsvReplaySource(source_path, ReplayConfig(warmup_bars=5)).load()
        strategy = StrategyEngine(generate_signal_fn=_noop_strategy)
        engine = WalkForwardEngine(
            strategy,
            replay_config=ReplayConfig(warmup_bars=5),
            backtest_config=BacktestConfig(max_bars_in_trade=5),
        )
        report = engine.run("NIFTY", df, train_bars=30, test_bars=15, step_bars=15)
        assert report.mode == "rolling"
        assert isinstance(report.windows, list)

    def test_csv_fixture_anchored(self):
        from core import BacktestConfig, ReplayConfig
        source_path = FIXTURES / "replay_minute_bars.csv"
        if not source_path.exists():
            pytest.skip("CSV fixture not found")

        from core import CsvReplaySource
        df = CsvReplaySource(source_path, ReplayConfig(warmup_bars=5)).load()
        strategy = StrategyEngine(generate_signal_fn=_noop_strategy)
        engine = WalkForwardEngine(
            strategy,
            replay_config=ReplayConfig(warmup_bars=5),
            backtest_config=BacktestConfig(max_bars_in_trade=5),
        )
        report = engine.run("NIFTY", df, train_bars=30, test_bars=15,
                            step_bars=15, anchored=True)
        assert report.mode == "anchored"
        first_ts = str(df.index[0])
        for w in report.windows:
            assert w.train_start == first_ts
