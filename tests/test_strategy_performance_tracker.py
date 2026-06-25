"""Tests for core/strategy/performance_tracker.py — StrategyPerformanceTracker.

Covers:
- DB initialization
- record_trade, update_trade_exit
- get_metrics (empty, single, multiple trades, time window)
- get_rankings (by sharpe, win_rate, total_pnl)
- export_trades
- get_summary_report
- Singleton get_performance_tracker
- Edge cases (no trades, open trades, negative PnLs, etc.)
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from core.strategy.performance_tracker import (
    StrategyMetrics,
    StrategyPerformanceTracker,
    StrategyRanking,
    get_performance_tracker,
)


class TestStrategyMetrics:
    """Tests for the StrategyMetrics dataclass."""

    def test_defaults(self):
        m = StrategyMetrics()
        assert m.strategy_name == ""
        assert m.total_trades == 0
        assert m.win_rate == 0.0
        assert m.sharpe == 0.0


class TestStrategyRanking:
    """Tests for the StrategyRanking dataclass."""

    def test_defaults(self):
        r = StrategyRanking()
        assert r.rankings == []
        assert r.metric == "sharpe"
        assert r.total_strategies == 0


# ── Fixture ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tracker() -> StrategyPerformanceTracker:
    """Create a tracker with a temp DB file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    t = StrategyPerformanceTracker(db_path=tmp.name)
    yield t
    try:
        os.unlink(tmp.name)
    except PermissionError:
        pass


class TestInit:
    """Tests for tracker initialization."""

    def test_creates_db(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_path = tmp.name
        t = StrategyPerformanceTracker(db_path=db_path)
        assert Path(db_path).exists()
        # Release reference and let GC handle SQLite connection
        del t
        import gc
        gc.collect()
        try:
            os.unlink(db_path)
        except PermissionError:
            pass  # Windows file lock — acceptable in test cleanup

    def test_creates_tables(self, tracker: StrategyPerformanceTracker):
        """Verify tables exist after init."""
        import sqlite3
        conn = sqlite3.connect(tracker._db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "strategy_trades" in table_names
        conn.close()


class TestRecordTrade:
    """Tests for recording trade outcomes."""

    def test_records_trade(self, tracker: StrategyPerformanceTracker):
        tracker.record_trade(
            trade_id="T1", strategy_name="Momentum",
            pnl=150.0, direction="BUY", symbol="NIFTY",
            entry_price=23500.0, outcome="WIN",
        )
        metrics = tracker.get_metrics("Momentum")
        assert metrics.total_trades == 1
        assert metrics.wins == 1
        assert metrics.total_pnl == 150.0

    def test_records_loss(self, tracker: StrategyPerformanceTracker):
        tracker.record_trade(
            trade_id="T2", strategy_name="Momentum",
            pnl=-50.0, direction="SELL", symbol="NIFTY",
            entry_price=23600.0, outcome="LOSS",
        )
        metrics = tracker.get_metrics("Momentum")
        assert metrics.losses == 1
        assert metrics.total_pnl == -50.0

    def test_records_open_trade(self, tracker: StrategyPerformanceTracker):
        tracker.record_trade(
            trade_id="T3", strategy_name="MeanRev",
            pnl=None, direction="BUY", symbol="BANKNIFTY",
            entry_price=50000.0, outcome="OPEN",
        )
        metrics = tracker.get_metrics("MeanRev")
        assert metrics.open_trades == 1
        assert metrics.total_trades == 0  # Only closed trades count

    def test_upsert_updates_existing(self, tracker: StrategyPerformanceTracker):
        tracker.record_trade(
            trade_id="T4", strategy_name="Trend",
            pnl=None, direction="BUY", symbol="NIFTY",
            entry_price=23500.0, outcome="OPEN",
        )
        tracker.record_trade(
            trade_id="T4", strategy_name="Trend",
            pnl=200.0, exit_price=23700.0,
            outcome="WIN", direction="BUY", symbol="NIFTY",
            entry_price=23500.0,
        )
        metrics = tracker.get_metrics("Trend")
        assert metrics.total_trades == 1
        assert metrics.total_pnl == 200.0


class TestUpdateTradeExit:
    """Tests for updating trades with exit info."""

    def test_updates_exit(self, tracker: StrategyPerformanceTracker):
        tracker.record_trade(
            trade_id="T5", strategy_name="Scalper",
            pnl=None, direction="BUY", symbol="NIFTY",
            entry_price=23500.0, outcome="OPEN",
        )
        tracker.update_trade_exit("T5", exit_price=23700.0, pnl=200.0, outcome="WIN")
        metrics = tracker.get_metrics("Scalper")
        assert metrics.total_trades == 1
        assert metrics.wins == 1


class TestGetMetrics:
    """Tests for metrics computation."""

    def test_no_trades(self, tracker: StrategyPerformanceTracker):
        metrics = tracker.get_metrics("NonExistent")
        assert metrics.total_trades == 0
        assert metrics.win_rate == 0.0

    def test_multiple_trades(self, tracker: StrategyPerformanceTracker):
        for i in range(10):
            pnl = 100.0 if i % 2 == 0 else -50.0
            outcome = "WIN" if pnl > 0 else "LOSS"
            tracker.record_trade(
                trade_id=f"MT-{i}", strategy_name="Balanced",
                pnl=pnl, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome=outcome,
            )
        metrics = tracker.get_metrics("Balanced")
        assert metrics.total_trades == 10
        assert metrics.wins == 5
        assert metrics.losses == 5
        assert metrics.win_rate == 0.5
        assert metrics.total_pnl == 250.0  # 5*100 + 5*(-50)

    def test_win_rate_100(self, tracker: StrategyPerformanceTracker):
        for i in range(5):
            tracker.record_trade(
                trade_id=f"WR-{i}", strategy_name="Perfect",
                pnl=100.0, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="WIN",
            )
        metrics = tracker.get_metrics("Perfect")
        assert metrics.win_rate == 1.0
        assert metrics.losses == 0

    def test_sharpe_ratio(self, tracker: StrategyPerformanceTracker):
        for i in range(20):
            pnl = 50.0 + (i % 5) * 2.0  # slight variance: 50, 52, 54, 56, 58, 50, ...
            tracker.record_trade(
                trade_id=f"SH-{i}", strategy_name="Steady",
                pnl=pnl, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="WIN",
            )
        metrics = tracker.get_metrics("Steady")
        assert metrics.sharpe > 0

    def test_max_drawdown(self, tracker: StrategyPerformanceTracker):
        # Create a sequence: up then down to create a drawdown
        pnls = [100, 100, 100, -200, -200, 100]
        for i, pnl in enumerate(pnls):
            outcome = "WIN" if pnl > 0 else "LOSS"
            tracker.record_trade(
                trade_id=f"DD-{i}", strategy_name="DrawdownTest",
                pnl=float(pnl), direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome=outcome,
            )
        metrics = tracker.get_metrics("DrawdownTest")
        # Cumulative: 100, 200, 300, 100, -100, 0
        # Running max: 100, 200, 300, 300, 300, 300
        # Drawdown: 0, 0, 0, 200, 400, 300
        # Max drawdown = 400
        assert metrics.max_drawdown >= 300

    def test_profit_factor(self, tracker: StrategyPerformanceTracker):
        for i in range(5):
            tracker.record_trade(
                trade_id=f"PF-{i}", strategy_name="Profitable",
                pnl=100.0, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="WIN",
            )
        for i in range(3):
            tracker.record_trade(
                trade_id=f"PF-L-{i}", strategy_name="Profitable",
                pnl=-50.0, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="LOSS",
            )
        metrics = tracker.get_metrics("Profitable")
        # PF = 500 / 150 = 3.33
        assert 3.0 <= metrics.profit_factor <= 3.5

    def test_consecutive_streaks(self, tracker: StrategyPerformanceTracker):
        pnls = [100, 100, -50, -50, -50, 100, 100]
        for i, pnl in enumerate(pnls):
            outcome = "WIN" if pnl > 0 else "LOSS"
            tracker.record_trade(
                trade_id=f"CS-{i}", strategy_name="StreakTest",
                pnl=float(pnl), direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome=outcome,
            )
        metrics = tracker.get_metrics("StreakTest")
        assert metrics.consecutive_wins == 2  # first two are wins
        assert metrics.consecutive_losses == 3  # then three losses

    def test_time_window(self, tracker: StrategyPerformanceTracker):
        # Record trades with timestamps far in the past
        from core.datetime_ist import now_ist
        from datetime import timedelta

        old_time = (now_ist() - timedelta(days=200)).isoformat()
        for i in range(3):
            tracker.record_trade(
                trade_id=f"OLD-{i}", strategy_name="Aging",
                pnl=100.0, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="WIN",
                entry_time=old_time,
            )
        # With 90-day window, old trades should be excluded
        metrics_90 = tracker.get_metrics("Aging", window_days=90)
        assert metrics_90.total_trades == 0

        # With 365-day window, they should be included
        metrics_365 = tracker.get_metrics("Aging", window_days=365)
        assert metrics_365.total_trades == 3

    def test_all_time_window(self, tracker: StrategyPerformanceTracker):
        for i in range(5):
            tracker.record_trade(
                trade_id=f"AT-{i}", strategy_name="AllTime",
                pnl=100.0, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="WIN",
            )
        metrics = tracker.get_metrics("AllTime", window_days=0)
        assert metrics.total_trades == 5


class TestGetRankings:
    """Tests for strategy rankings."""

    def test_empty_ranking(self, tracker: StrategyPerformanceTracker):
        ranking = tracker.get_rankings()
        assert ranking.rankings == []
        assert ranking.total_strategies == 0

    def test_rank_by_sharpe(self, tracker: StrategyPerformanceTracker):
        # Strategy A: steady wins with slight variance
        for i in range(10):
            pnl = 100.0 + (i % 3) * 0.5  # 100, 100.5, 101, 100, ...
            tracker.record_trade(
                trade_id=f"A-{i}", strategy_name="SteadyA",
                pnl=pnl, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="WIN",
            )
        # Strategy B: mixed (low Sharpe)
        for i in range(10):
            pnl = 200.0 if i % 2 == 0 else -190.0
            outcome = "WIN" if pnl > 0 else "LOSS"
            tracker.record_trade(
                trade_id=f"B-{i}", strategy_name="VolatileB",
                pnl=float(pnl), direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome=outcome,
            )
        ranking = tracker.get_rankings(metric="sharpe", min_trades=5)
        assert len(ranking.rankings) == 2
        # SteadyA should rank higher than VolatileB by Sharpe
        assert ranking.rankings[0][1] == "SteadyA"

    def test_rank_by_total_pnl(self, tracker: StrategyPerformanceTracker):
        for i in range(5):
            tracker.record_trade(
                trade_id=f"P-{i}", strategy_name="HighPnl",
                pnl=200.0, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="WIN",
            )
        for i in range(5):
            tracker.record_trade(
                trade_id=f"L-{i}", strategy_name="LowPnl",
                pnl=50.0, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="WIN",
            )
        ranking = tracker.get_rankings(metric="total_pnl")
        assert len(ranking.rankings) == 2
        assert ranking.rankings[0][1] == "HighPnl"

    def test_rank_by_win_rate(self, tracker: StrategyPerformanceTracker):
        for i in range(10):
            tracker.record_trade(
                trade_id=f"W-{i}", strategy_name="HighWR",
                pnl=100.0, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="WIN",
            )
        for i in range(5):
            pnl = 100.0 if i < 4 else -200.0
            outcome = "WIN" if pnl > 0 else "LOSS"
            tracker.record_trade(
                trade_id=f"M-{i}", strategy_name="MedWR",
                pnl=float(pnl), direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome=outcome,
            )
        ranking = tracker.get_rankings(metric="win_rate")
        assert ranking.rankings[0][1] == "HighWR"

    def test_min_trades_filter(self, tracker: StrategyPerformanceTracker):
        for i in range(2):
            tracker.record_trade(
                trade_id=f"FEW-{i}", strategy_name="FewTrades",
                pnl=100.0, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="WIN",
            )
        for i in range(10):
            tracker.record_trade(
                trade_id=f"MANY-{i}", strategy_name="ManyTrades",
                pnl=50.0, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="WIN",
            )
        ranking = tracker.get_rankings(min_trades=5)
        assert len(ranking.rankings) == 1
        assert ranking.rankings[0][1] == "ManyTrades"


class TestExport:
    """Tests for trade export."""

    def test_export_all(self, tracker: StrategyPerformanceTracker):
        tracker.record_trade(
            trade_id="E1", strategy_name="ExpTest",
            pnl=100.0, direction="BUY", symbol="NIFTY",
            entry_price=23500.0, outcome="WIN",
        )
        exported = tracker.export_trades()
        assert len(exported) == 1
        assert exported[0]["trade_id"] == "E1"

    def test_export_by_strategy(self, tracker: StrategyPerformanceTracker):
        tracker.record_trade(
            trade_id="ES1", strategy_name="StratA",
            pnl=100.0, direction="BUY", symbol="NIFTY",
            entry_price=23500.0, outcome="WIN",
        )
        tracker.record_trade(
            trade_id="ES2", strategy_name="StratB",
            pnl=50.0, direction="SELL", symbol="BANKNIFTY",
            entry_price=50000.0, outcome="WIN",
        )
        exported = tracker.export_trades(strategy_name="StratA")
        assert len(exported) == 1
        assert exported[0]["strategy_name"] == "StratA"

    def test_export_limit(self, tracker: StrategyPerformanceTracker):
        for i in range(10):
            tracker.record_trade(
                trade_id=f"EL-{i}", strategy_name="LimitTest",
                pnl=100.0, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="WIN",
            )
        exported = tracker.export_trades(limit=3)
        assert len(exported) == 3


class TestSummaryReport:
    """Tests for the summary report."""

    def test_empty_report(self, tracker: StrategyPerformanceTracker):
        report = tracker.get_summary_report()
        assert isinstance(report, str)
        assert "No strategies" in report

    def test_report_with_data(self, tracker: StrategyPerformanceTracker):
        for i in range(10):
            tracker.record_trade(
                trade_id=f"SR-{i}", strategy_name="TestStrat",
                pnl=100.0, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="WIN",
            )
        report = tracker.get_summary_report()
        assert "TestStrat" in report
        assert "Sharpe" in report
        assert "Strategy Performance Report" in report


class TestSingleton:
    """Tests for the singleton factory."""

    def test_singleton_returns_instance(self):
        import core.strategy.performance_tracker as pt_mod
        old = pt_mod._perf_tracker
        pt_mod._perf_tracker = None
        try:
            s1 = get_performance_tracker(db_path=":memory:")
            s2 = get_performance_tracker()
            assert s1 is s2
        finally:
            pt_mod._perf_tracker = old


class TestEdgeCases:
    """Edge case tests."""

    def test_single_trade_no_sharpe(self, tracker: StrategyPerformanceTracker):
        tracker.record_trade(
            trade_id="EC1", strategy_name="Single",
            pnl=100.0, direction="BUY", symbol="NIFTY",
            entry_price=23500.0, outcome="WIN",
        )
        metrics = tracker.get_metrics("Single")
        assert metrics.sharpe == 0.0  # Need >= 2 trades for Sharpe

    def test_all_losses(self, tracker: StrategyPerformanceTracker):
        for i in range(5):
            tracker.record_trade(
                trade_id=f"AL-{i}", strategy_name="AllLoss",
                pnl=-100.0, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="LOSS",
            )
        metrics = tracker.get_metrics("AllLoss")
        assert metrics.wins == 0
        assert metrics.losses == 5
        assert metrics.win_rate == 0.0

    def test_zero_pnl_trades(self, tracker: StrategyPerformanceTracker):
        # PnL=0 is neither win nor loss; it's a scratch trade
        for i in range(3):
            tracker.record_trade(
                trade_id=f"ZP-{i}", strategy_name="BreakEven",
                pnl=0.0, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="WIN",
            )
        # Add actual wins for counting
        for i in range(2):
            tracker.record_trade(
                trade_id=f"ZW-{i}", strategy_name="BreakEven",
                pnl=50.0, direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome="WIN",
            )
        metrics = tracker.get_metrics("BreakEven")
        assert metrics.total_pnl == 100.0  # 2*50 = 100 (zeros not counted)
        assert metrics.wins == 2
        assert metrics.losses == 0

    def test_large_number_of_trades(self, tracker: StrategyPerformanceTracker):
        for i in range(100):
            pnl = 10.0 if i % 2 == 0 else -5.0
            outcome = "WIN" if pnl > 0 else "LOSS"
            tracker.record_trade(
                trade_id=f"LN-{i}", strategy_name="LargeN",
                pnl=float(pnl), direction="BUY", symbol="NIFTY",
                entry_price=23500.0, outcome=outcome,
            )
        metrics = tracker.get_metrics("LargeN")
        assert metrics.total_trades == 100
        assert metrics.total_pnl == 250.0  # 50*10 + 50*(-5)
