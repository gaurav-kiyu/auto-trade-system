"""
Backtesting entrypoint: candle simulator + legacy CSV replay types from ``core``.
"""

from __future__ import annotations

from core.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestReport,
    BacktestTrade,
    CsvReplaySource,
    ReplayConfig,
    ReplayEngine,
    ReplaySignal,
)
from core.candle_backtest import (
    CandleBacktestConfig,
    CandleBacktestEngine,
    CandleBacktestResult,
    PerformanceMetrics,
    TradeJournalRow,
    run_candle_backtest,
)

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestReport",
    "BacktestTrade",
    "CsvReplaySource",
    "ReplayConfig",
    "ReplayEngine",
    "ReplaySignal",
    "CandleBacktestConfig",
    "CandleBacktestEngine",
    "CandleBacktestResult",
    "PerformanceMetrics",
    "TradeJournalRow",
    "run_candle_backtest",
]
