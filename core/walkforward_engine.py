from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .backtest_engine import BacktestConfig, BacktestEngine, BacktestReport, ReplayConfig
from .strategy_engine import StrategyEngine


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    report: BacktestReport


@dataclass(frozen=True)
class WalkForwardReport:
    windows: list[WalkForwardWindow]
    total_test_trades: int
    net_test_pnl: float
    avg_win_rate: float
    mode: str = "rolling"   # "rolling" | "anchored"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "windows": [
                {
                    "train_start": window.train_start,
                    "train_end": window.train_end,
                    "test_start": window.test_start,
                    "test_end": window.test_end,
                    "report": window.report.to_dict(),
                }
                for window in self.windows
            ],
            "total_test_trades": self.total_test_trades,
            "net_test_pnl": self.net_test_pnl,
            "avg_win_rate": self.avg_win_rate,
        }


class WalkForwardEngine:
    """Evaluate strategy quality over rolling train/test windows."""

    def __init__(
        self,
        strategy_engine: StrategyEngine,
        *,
        replay_config: ReplayConfig | None = None,
        backtest_config: BacktestConfig | None = None,
        adapt_fn: Callable[[pd.DataFrame], None] | None = None,
    ) -> None:
        self._strategy_engine = strategy_engine
        self._replay_config = replay_config or ReplayConfig()
        self._backtest_config = backtest_config or BacktestConfig()
        self._adapt_fn = adapt_fn

    def run(
        self,
        name: str,
        base_df: pd.DataFrame,
        *,
        train_bars: int,
        test_bars: int,
        step_bars: int | None = None,
        vix: float = 0.0,
        anchored: bool = False,
    ) -> WalkForwardReport:
        """
        Run walk-forward validation.

        Args:
            name       : Strategy / index name passed to the backtest engine.
            base_df    : Full price DataFrame (1-min or target resolution).
            train_bars : Number of bars in the initial training window.
            test_bars  : Number of bars in each test window.
            step_bars  : How many bars to advance per iteration (default = test_bars).
            vix        : VIX value forwarded to the strategy engine.
            anchored   : If True, use anchored (expanding) walk-forward: the train
                         window always starts from bar 0 and grows each step.
                         If False (default), the train window slides forward at
                         the same rate as the test window (rolling).

        Returns:
            WalkForwardReport with ``mode="anchored"`` or ``mode="rolling"``.
        """
        step = int(step_bars or test_bars)
        windows: list[WalkForwardWindow] = []
        idx = 0
        while idx + train_bars + test_bars <= len(base_df):
            if anchored:
                # Anchored: training always starts at bar 0, grows each step.
                train_df = base_df.iloc[0 : idx + train_bars].copy()
            else:
                # Rolling: training window slides forward with each step.
                train_df = base_df.iloc[idx : idx + train_bars].copy()

            test_df = base_df.iloc[idx + train_bars : idx + train_bars + test_bars].copy()

            if self._adapt_fn:
                self._adapt_fn(train_df)

            backtest = BacktestEngine(
                self._strategy_engine,
                replay_config=self._replay_config,
                backtest_config=self._backtest_config,
            )
            report = backtest.run(name, test_df, vix=vix)
            windows.append(
                WalkForwardWindow(
                    train_start=str(train_df.index[0]),
                    train_end=str(train_df.index[-1]),
                    test_start=str(test_df.index[0]),
                    test_end=str(test_df.index[-1]),
                    report=report,
                )
            )
            idx += max(1, step)

        total_trades = sum(window.report.total_trades for window in windows)
        net_pnl = round(sum(window.report.net_pnl for window in windows), 2)
        avg_wr = round(sum(window.report.win_rate for window in windows) / len(windows), 2) if windows else 0.0
        return WalkForwardReport(
            windows=windows,
            total_test_trades=total_trades,
            net_test_pnl=net_pnl,
            avg_win_rate=avg_wr,
            mode="anchored" if anchored else "rolling",
        )
