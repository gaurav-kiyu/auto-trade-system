"""Tests for core/strategy/benchmark.py — StrategyBenchmark.

Covers:
- StrategyBenchmark init, add_strategy, remove_strategy
- run() with mock strategies (empty, single, multiple)
- run_from_tracker() with historical data
- format_report()
- Edge cases (no strategies, no signals, all HOLD)
"""

from __future__ import annotations

from typing import Any


from core.strategy.benchmark import (
    BenchmarkReport,
    BenchmarkResult,
    StrategyBenchmark,
)
from core.strategy.performance_tracker import (
    StrategyPerformanceTracker,
)
from core.strategy.plugin_framework import (
    BaseStrategy,
    FillInfo,
    MarketData,
    RiskUpdate,
    StrategySignal,
    StrategySignalOutput,
)


# ── Mock Strategies ────────────────────────────────────────────────────────


class AlwaysBuyStrategy(BaseStrategy):
    """Strategy that always generates a BUY signal."""

    @property
    def name(self) -> str:
        return "AlwaysBuy"

    def on_market_data(self, data: MarketData) -> None:
        pass

    def generate_signal(self, data: MarketData) -> StrategySignalOutput | None:
        return StrategySignalOutput(
            signal=StrategySignal.BUY,
            confidence=0.9,
            score=85,
            price=data.last_price,
            quantity=1,
            reason="Always BUY",
        )

    def on_fill(self, fill: FillInfo) -> None:
        pass

    def on_risk_update(self, risk: RiskUpdate) -> None:
        pass


class AlternatingStrategy(BaseStrategy):
    """Strategy alternates between BUY and SELL."""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._count = 0

    @property
    def name(self) -> str:
        return "Alternating"

    def on_market_data(self, data: MarketData) -> None:
        pass

    def generate_signal(self, data: MarketData) -> StrategySignalOutput | None:
        self._count += 1
        signal = StrategySignal.BUY if self._count % 2 == 0 else StrategySignal.SELL
        return StrategySignalOutput(
            signal=signal,
            confidence=0.7,
            score=60,
            price=data.last_price,
            quantity=1,
            reason=f"Signal #{self._count}",
        )

    def on_fill(self, fill: FillInfo) -> None:
        pass

    def on_risk_update(self, risk: RiskUpdate) -> None:
        pass


class HoldStrategy(BaseStrategy):
    """Strategy that always returns HOLD (no signals)."""

    @property
    def name(self) -> str:
        return "HoldOnly"

    def on_market_data(self, data: MarketData) -> None:
        pass

    def generate_signal(self, data: MarketData) -> StrategySignalOutput | None:
        return None

    def on_fill(self, fill: FillInfo) -> None:
        pass

    def on_risk_update(self, risk: RiskUpdate) -> None:
        pass


# ── Sample data ────────────────────────────────────────────────────────────

SAMPLE_DATA = [
    {"symbol": "NIFTY", "last_price": 23500.0, "volume": 1000},
    {"symbol": "NIFTY", "last_price": 23550.0, "volume": 1200},
    {"symbol": "NIFTY", "last_price": 23600.0, "volume": 1500},
    {"symbol": "NIFTY", "last_price": 23580.0, "volume": 1100},
    {"symbol": "NIFTY", "last_price": 23620.0, "volume": 1300},
]


# ── Tests ──────────────────────────────────────────────────────────────────


class TestBenchmarkResult:
    """Tests for the BenchmarkResult dataclass."""

    def test_defaults(self):
        r = BenchmarkResult()
        assert r.strategy_name == ""
        assert r.total_signals == 0


class TestBenchmarkReport:
    """Tests for the BenchmarkReport dataclass."""

    def test_defaults(self):
        r = BenchmarkReport()
        assert r.best_strategy == ""
        assert r.total_strategies == 0


class TestInit:
    """Tests for StrategyBenchmark initialization."""

    def test_empty_initially(self):
        bm = StrategyBenchmark()
        assert bm.get_strategy_count() == 0
        assert bm.get_strategy_names() == []

    def test_with_tracker(self):
        bm = StrategyBenchmark(db_path=":memory:")
        assert bm._tracker is not None


class TestAddRemove:
    """Tests for adding/removing strategies."""

    def test_add_strategy(self):
        bm = StrategyBenchmark()
        s = AlwaysBuyStrategy({})
        bm.add_strategy(s)
        assert bm.get_strategy_count() == 1
        assert "AlwaysBuy" in bm.get_strategy_names()

    def test_add_multiple(self):
        bm = StrategyBenchmark()
        bm.add_strategy(AlwaysBuyStrategy({}))
        bm.add_strategy(AlternatingStrategy({}))
        assert bm.get_strategy_count() == 2

    def test_remove_strategy(self):
        bm = StrategyBenchmark()
        s = AlwaysBuyStrategy({})
        bm.add_strategy(s)
        assert bm.remove_strategy("AlwaysBuy") is True
        assert bm.get_strategy_count() == 0

    def test_remove_nonexistent(self):
        bm = StrategyBenchmark()
        assert bm.remove_strategy("NonExistent") is False


class TestRun:
    """Tests for the run() method."""

    def test_empty_no_strategies(self):
        bm = StrategyBenchmark()
        report = bm.run([])
        assert report.total_strategies == 0
        assert report.best_strategy == ""

    def test_run_empty_data(self):
        bm = StrategyBenchmark()
        bm.add_strategy(AlwaysBuyStrategy({}))
        report = bm.run([])
        assert report.total_strategies == 1
        assert report.results[0].total_signals == 0

    def test_single_strategy_buys(self):
        bm = StrategyBenchmark()
        bm.add_strategy(AlwaysBuyStrategy({}))
        report = bm.run(SAMPLE_DATA)
        assert len(report.results) == 1
        assert report.results[0].strategy_name == "AlwaysBuy"
        assert report.results[0].total_signals == len(SAMPLE_DATA)

    def test_multiple_strategies(self):
        bm = StrategyBenchmark()
        bm.add_strategy(AlwaysBuyStrategy({}))
        bm.add_strategy(AlternatingStrategy({}))
        report = bm.run(SAMPLE_DATA)
        assert len(report.results) == 2
        names = [r.strategy_name for r in report.results]
        assert "AlwaysBuy" in names
        assert "Alternating" in names

    def test_best_strategy_set(self):
        bm = StrategyBenchmark()
        bm.add_strategy(AlwaysBuyStrategy({}))
        report = bm.run(SAMPLE_DATA)
        assert report.best_strategy == "AlwaysBuy"

    def test_hold_strategy_no_signals(self):
        bm = StrategyBenchmark()
        bm.add_strategy(HoldStrategy({}))
        report = bm.run(SAMPLE_DATA)
        assert report.results[0].total_signals == 0
        assert report.results[0].total_trades == 0

    def test_direction_distribution(self):
        bm = StrategyBenchmark()
        bm.add_strategy(AlternatingStrategy({}))
        report = bm.run(SAMPLE_DATA[:4])  # 4 data points → 4 signals
        # Alternating generates: SELL(1), BUY(2), SELL(3), BUY(4)
        dd = report.results[0].direction_distribution
        assert "BUY" in dd
        assert "SELL" in dd

    def test_data_points_count(self):
        bm = StrategyBenchmark()
        bm.add_strategy(AlwaysBuyStrategy({}))
        report = bm.run(SAMPLE_DATA)
        assert report.data_points == len(SAMPLE_DATA)

    def test_duration_set(self):
        bm = StrategyBenchmark()
        bm.add_strategy(AlwaysBuyStrategy({}))
        report = bm.run(SAMPLE_DATA)
        assert report.results[0].duration_seconds >= 0.0

    def test_record_results_option(self):
        bm = StrategyBenchmark(db_path=":memory:")
        bm.add_strategy(AlwaysBuyStrategy({}))
        report = bm.run(SAMPLE_DATA, record_results=True)
        assert report.results[0].total_trades > 0


class TestRunFromTracker:
    """Tests for run_from_tracker()."""

    def test_no_tracker_data(self):
        # Pass a fresh tracker instance directly to avoid singleton leakage
        fresh_tracker = StrategyPerformanceTracker(db_path=":memory:")
        bm = StrategyBenchmark(tracker=fresh_tracker)
        report = bm.run_from_tracker()
        assert report.total_strategies == 0


class TestFormatReport:
    """Tests for format_report()."""

    def test_empty_report(self):
        bm = StrategyBenchmark()
        report = BenchmarkReport()
        text = bm.format_report(report)
        assert "No benchmark results" in text

    def test_report_with_results(self):
        bm = StrategyBenchmark()
        bm.add_strategy(AlwaysBuyStrategy({}))
        report = bm.run(SAMPLE_DATA)
        text = bm.format_report(report)
        assert "AlwaysBuy" in text
        assert "Strategy Benchmark Report" in text

    def test_report_best_strategy(self):
        bm = StrategyBenchmark()
        bm.add_strategy(AlwaysBuyStrategy({}))
        bm.add_strategy(HoldStrategy({}))
        report = bm.run(SAMPLE_DATA)
        text = bm.format_report(report)
        assert "AlwaysBuy" in text  # AlwaysBuy should be best


class TestHelpers:
    """Tests for internal helpers."""

    def test_dict_to_market_data(self):
        dp = {
            "symbol": "NIFTY",
            "last_price": 23500.0,
            "bid": 23499.0,
            "ask": 23501.0,
            "volume": 1000,
            "open_interest": 500,
        }
        md = StrategyBenchmark._dict_to_market_data(dp)
        assert md.symbol == "NIFTY"
        assert md.last_price == 23500.0
        assert md.open_interest == 500
        assert md.delta == 0.0  # default

    def test_dict_to_market_data_minimal(self):
        md = StrategyBenchmark._dict_to_market_data({"last_price": 100.0})
        assert md.last_price == 100.0
        assert md.symbol == ""

    def test_simulate_trade_pnl_buy(self):
        signal = StrategySignalOutput(
            signal=StrategySignal.BUY, confidence=0.8, score=75,
            price=100.0, quantity=10,
        )
        pnl = StrategyBenchmark._simulate_trade_pnl(signal, exit_price=110.0)
        assert pnl == 100.0  # (110 - 100) * 10

    def test_simulate_trade_pnl_sell(self):
        signal = StrategySignalOutput(
            signal=StrategySignal.SELL, confidence=0.8, score=75,
            price=100.0, quantity=10,
        )
        pnl = StrategyBenchmark._simulate_trade_pnl(signal, exit_price=90.0)
        assert pnl == 100.0  # (100 - 90) * 10

    def test_simulate_trade_pnl_zero_price(self):
        signal = StrategySignalOutput(
            signal=StrategySignal.BUY, confidence=0.8, score=75,
            price=0.0, quantity=10,
        )
        pnl = StrategyBenchmark._simulate_trade_pnl(signal, exit_price=110.0)
        assert pnl == 0.0

    def test_simulate_trade_pnl_hold(self):
        signal = StrategySignalOutput(
            signal=StrategySignal.HOLD, confidence=0.8, score=75,
            price=100.0, quantity=10,
        )
        pnl = StrategyBenchmark._simulate_trade_pnl(signal, exit_price=110.0)
        assert pnl == 0.0
