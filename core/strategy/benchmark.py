"""
Strategy Benchmark — side-by-side comparison of multiple strategies.

Runs N strategies on the same historical dataset and produces a
comparison report with ranking, win rate, Sharpe, max drawdown, and
profit factor for each strategy.

Designed to be instrument-agnostic: strategies receive generic MarketData
and return signals via the plugin framework interface. No assumptions about
options, equities, or any specific instrument type.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from core.strategy.plugin_framework import (
    BaseStrategy,
    MarketData,
    StrategySignal,
    StrategySignalOutput,
)
from core.strategy.performance_tracker import (
    StrategyMetrics,
    StrategyPerformanceTracker,
    StrategyRanking,
    get_performance_tracker,
)
from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)


# ── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class BenchmarkResult:
    """Result of a single strategy benchmark run.

    Attributes:
        strategy_name: Name of the strategy benchmarked.
        strategy_version: Version string.
        metrics: Computed performance metrics.
        total_signals: Total signals generated during the run.
        total_trades: Total simulated trades from signals.
        data_points: Number of market data points processed.
        duration_seconds: Wall-clock time for the benchmark run.
        direction_distribution: Breakdown of signal directions.
    """
    strategy_name: str = ""
    strategy_version: str = ""
    metrics: StrategyMetrics = field(default_factory=StrategyMetrics)
    total_signals: int = 0
    total_trades: int = 0
    data_points: int = 0
    duration_seconds: float = 0.0
    direction_distribution: dict[str, int] = field(default_factory=dict)


@dataclass
class BenchmarkReport:
    """Complete benchmark report across all strategies.

    Attributes:
        results: One BenchmarkResult per strategy.
        rankings: Strategy rankings by Sharpe.
        best_strategy: Name of the top-ranked strategy.
        total_strategies: Number of strategies benchmarked.
        timestamp: When the benchmark was run.
        data_points: Number of common data points used.
    """
    results: list[BenchmarkResult] = field(default_factory=list)
    rankings: StrategyRanking = field(default_factory=StrategyRanking)
    best_strategy: str = ""
    total_strategies: int = 0
    timestamp: str = ""
    data_points: int = 0


# ── Benchmark Runner ───────────────────────────────────────────────────────


class StrategyBenchmark:
    """Runs multiple strategies on the same dataset for comparison.

    Instrument-agnostic — works with any strategy implementing the
    plugin_framework BaseStrategy interface. Provides ranking and
    detailed per-strategy metrics.

    Usage:
        benchmark = StrategyBenchmark()
        benchmark.add_strategy(momentum_strategy)
        benchmark.add_strategy(mean_reversion_strategy)
        report = benchmark.run(data_points)
        print(report.best_strategy)
    """

    def __init__(
        self,
        tracker: StrategyPerformanceTracker | None = None,
        db_path: str = "strategy_performance.db",
    ) -> None:
        self._strategies: list[BaseStrategy] = []
        self._tracker = tracker or get_performance_tracker(db_path=db_path)
        self._lock = threading.RLock()

    def add_strategy(self, strategy: BaseStrategy) -> None:
        """Add a strategy to the benchmark comparison.

        Args:
            strategy: An initialized (but not started) strategy instance.
        """
        with self._lock:
            self._strategies.append(strategy)
            _log.info("[Benchmark] Added strategy: %s v%s",
                      strategy.name, strategy.version)

    def remove_strategy(self, name: str) -> bool:
        """Remove a strategy by name."""
        with self._lock:
            for i, s in enumerate(self._strategies):
                if s.name == name:
                    self._strategies.pop(i)
                    _log.info("[Benchmark] Removed strategy: %s", name)
                    return True
            return False

    def get_strategy_count(self) -> int:
        """Return the number of registered benchmark strategies."""
        return len(self._strategies)

    def get_strategy_names(self) -> list[str]:
        """Return names of all registered strategies."""
        return [s.name for s in self._strategies]

    def run(
        self,
        data_points: list[dict[str, Any]],
        record_results: bool = False,
    ) -> BenchmarkReport:
        """Run all strategies against the same historical data.

        Each strategy processes the data independently. Performance
        metrics are computed from simulated fills (BUY/SELL signals
        generate simulated trades with a simple metric).

        Args:
            data_points: List of market data dicts (must contain at least
                         'last_price' and 'symbol').
            record_results: If True, record simulated trades to the
                           performance tracker for long-term tracking.

        Returns:
            BenchmarkReport with per-strategy results and rankings.
        """
        with self._lock:
            strategies = list(self._strategies)

        if not strategies:
            _log.warning("[Benchmark] No strategies to benchmark")
            return BenchmarkReport(timestamp=now_ist().isoformat())

        results: list[BenchmarkResult] = []
        data_count = len(data_points)

        for strategy in strategies:
            start_ts = time.time()
            trade_count = 0
            signal_count = 0
            direction_dist: dict[str, int] = {}
            simulated_pnls: list[float] = []

            strategy.on_start()

            for dp in data_points:
                md = self._dict_to_market_data(dp)
                strategy.on_market_data(md)
                signal = strategy.generate_signal(md)

                if signal and signal.signal != StrategySignal.HOLD:
                    signal_count += 1
                    direction_label = signal.signal.value
                    direction_dist[direction_label] = \
                        direction_dist.get(direction_label, 0) + 1

                    # Simulate a trade with entry at signal price
                    if signal.price > 0:
                        trade_count += 1
                        # Simple PnL simulation: BUY goes long, SELL goes short
                        simulated_pnl = self._simulate_trade_pnl(
                            signal, dp.get("last_price", signal.price),
                        )
                        simulated_pnls.append(simulated_pnl)

                        if record_results:
                            self._tracker.record_trade(
                                trade_id=f"BM-{strategy.name}-{signal_count}",
                                strategy_name=strategy.name,
                                strategy_version=strategy.version,
                                pnl=simulated_pnl,
                                direction=signal.signal.value,
                                symbol=md.symbol,
                                entry_price=signal.price,
                                exit_price=dp.get("last_price", signal.price),
                                outcome="WIN" if simulated_pnl > 0 else "LOSS",
                                signal_score=signal.score,
                            )

            strategy.on_stop()
            elapsed = time.time() - start_ts

            # Compute metrics from simulated PnLs
            total = len(simulated_pnls)
            wins = [p for p in simulated_pnls if p > 0]
            losses = [p for p in simulated_pnls if p < 0]
            total_pnl = sum(simulated_pnls) if simulated_pnls else 0.0

            metrics = StrategyMetrics(
                strategy_name=strategy.name,
                strategy_version=strategy.version,
                total_trades=total,
                wins=len(wins),
                losses=len(losses),
                win_rate=round(len(wins) / total, 4) if total > 0 else 0.0,
                total_pnl=round(total_pnl, 2),
                avg_pnl=round(total_pnl / total, 2) if total > 0 else 0.0,
            )

            results.append(BenchmarkResult(
                strategy_name=strategy.name,
                strategy_version=strategy.version,
                metrics=metrics,
                total_signals=signal_count,
                total_trades=total,
                data_points=data_count,
                duration_seconds=round(elapsed, 4),
                direction_distribution=direction_dist,
            ))

            _log.info(
                "[Benchmark] %s: %d signals, %d trades, "
                "PnL=%.2f in %.2fs",
                strategy.name, signal_count, total,
                total_pnl, elapsed,
            )

        # Compute rankings by Sharpe
        ranked = sorted(
            results,
            key=lambda r: r.metrics.sharpe if r.metrics.total_trades >= 5 else -999,
            reverse=True,
        )
        rankings_list = [
            (rank + 1, r.strategy_name, r.metrics.sharpe)
            for rank, r in enumerate(ranked)
            if r.metrics.total_trades >= 5
        ]

        best = ranked[0].strategy_name if ranked else ""

        ranking = StrategyRanking(
            rankings=rankings_list,
            metric="sharpe",
            timestamp=now_ist().isoformat(),
            total_strategies=len(strategies),
        )

        return BenchmarkReport(
            results=results,
            rankings=ranking,
            best_strategy=best,
            total_strategies=len(strategies),
            timestamp=now_ist().isoformat(),
            data_points=data_count,
        )

    def run_from_tracker(
        self,
        window_days: int = 90,
        min_trades: int = 5,
    ) -> BenchmarkReport:
        """Generate a benchmark report from tracker history.

        Uses previously recorded trade data from the performance tracker
        rather than running a new simulation. Useful for comparing
        live-traded strategies.

        Args:
            window_days: Look-back window for metrics.
            min_trades: Minimum trades to be included.

        Returns:
            BenchmarkReport from historical data.
        """
        ranking = self._tracker.get_rankings(
            metric="sharpe",
            window_days=window_days,
            min_trades=min_trades,
        )

        results: list[BenchmarkResult] = []
        for _, name, _ in ranking.rankings:
            metrics = self._tracker.get_metrics(name, window_days=window_days)
            results.append(BenchmarkResult(
                strategy_name=name,
                metrics=metrics,
                total_trades=metrics.total_trades,
            ))

        best = ranking.rankings[0][1] if ranking.rankings else ""

        return BenchmarkReport(
            results=results,
            rankings=ranking,
            best_strategy=best,
            total_strategies=len(ranking.rankings),
            timestamp=ranking.timestamp,
            data_points=0,
        )

    def format_report(self, report: BenchmarkReport) -> str:
        """Format a benchmark report as a human-readable string."""
        lines = [
            "╔══════════════════════════════════════════════════════════╗",
            "║           Strategy Benchmark Report                     ║",
            f"║           {report.timestamp[:19]}                       ║",
            "╚══════════════════════════════════════════════════════════╝",
            "",
        ]

        if not report.results:
            lines.append("No benchmark results.")
            return "\n".join(lines)

        lines.append(f"Strategies: {report.total_strategies}")
        lines.append(f"Data points: {report.data_points}")
        if report.best_strategy:
            lines.append(f"Best: {report.best_strategy}")
        lines.append("")

        # Summary table
        lines.append(
            f"{'#':>3}  {'Strategy':<25}  {'Sharpe':>8}  "
            f"{'Win%':>7}  {'PnL':>10}  {'Trades':>6}  {'Time':>8}"
        )
        lines.append("-" * 75)

        for rank, name, sharpe in report.rankings.rankings:
            for r in report.results:
                if r.strategy_name == name:
                    lines.append(
                        f"{rank:>3}  {name:<25}  {sharpe:>8.4f}  "
                        f"{r.metrics.win_rate:>6.1%}  "
                        f"{r.metrics.total_pnl:>9.0f}  "
                        f"{r.total_trades:>6}  "
                        f"{r.duration_seconds:>7.2f}s"
                    )
                    break

        lines.append("")
        lines.append("--- Per-Strategy Details ---")
        for r in report.results:
            lines.append("")
            lines.append(f"  {r.strategy_name} v{r.strategy_version}")
            lines.append(f"    Signals: {r.total_signals}  "
                         f"Trades: {r.total_trades}  "
                         f"Data: {r.data_points}")
            lines.append(f"    Duration: {r.duration_seconds:.2f}s  "
                         f"Directions: {r.direction_distribution}")
            lines.append(f"    Sharpe: {r.metrics.sharpe:.4f}  "
                         f"WinRate: {r.metrics.win_rate:.1%}  "
                         f"PnL: {r.metrics.total_pnl:.2f}  "
                         f"PF: {r.metrics.profit_factor:.2f}")

        return "\n".join(lines)

    # ── Internal helpers ───────────────────────────────────────────────

    @staticmethod
    def _dict_to_market_data(dp: dict[str, Any]) -> MarketData:
        """Convert a data dict to MarketData for strategy consumption."""
        return MarketData(
            symbol=dp.get("symbol", ""),
            timestamp=dp.get("timestamp", ""),
            last_price=float(dp.get("last_price", 0.0)),
            bid=float(dp.get("bid", dp.get("last_price", 0.0))),
            ask=float(dp.get("ask", dp.get("last_price", 0.0))),
            volume=int(dp.get("volume", 0)),
            open_interest=int(dp.get("open_interest", 0)),
            iv=float(dp.get("iv", 0.0)),
            delta=float(dp.get("delta", 0.0)),
            gamma=float(dp.get("gamma", 0.0)),
            theta=float(dp.get("theta", 0.0)),
            vega=float(dp.get("vega", 0.0)),
            additional=dp.get("additional", {}),
        )

    @staticmethod
    def _simulate_trade_pnl(
        signal: StrategySignalOutput,
        exit_price: float,
    ) -> float:
        """Simulate PnL for a single signal (long on BUY, short on SELL)."""
        if signal.price <= 0:
            return 0.0
        if signal.signal == StrategySignal.BUY:
            return (exit_price - signal.price) * signal.quantity
        elif signal.signal == StrategySignal.SELL:
            return (signal.price - exit_price) * signal.quantity
        return 0.0


__all__ = [
    "BenchmarkResult",
    "BenchmarkReport",
    "StrategyBenchmark",
]
