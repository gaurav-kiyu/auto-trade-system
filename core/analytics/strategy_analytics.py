"""
Strategy Performance Analytics - Item 19

Track:
- Sharpe
- expectancy
- hit ratio
- drawdown
- avg holding time
- regime performance

Comprehensive strategy performance tracking.
"""
from __future__ import annotations

import logging
import math
import sqlite3
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class TradePerformance:
    """Individual trade performance metrics"""
    trade_id: str
    strategy_name: str
    entry_time: str
    exit_time: str
    pnl: float
    return_pct: float
    holding_seconds: int
    regime: str = "UNKNOWN"


@dataclass
class StrategyPerformance:
    """Strategy aggregate performance"""
    strategy_name: str

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    avg_winning_pnl: float = 0.0
    avg_losing_pnl: float = 0.0

    hit_ratio: float = 0.0
    expectancy: float = 0.0

    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0

    avg_holding_seconds: int = 0

    win_by_regime: dict[str, dict[str, Any]] = field(default_factory=dict)


class StrategyPerformanceAnalytics:
    """
    Strategy performance analytics engine.
    Tracks comprehensive performance metrics.
    """

    PERSISTENCE_PATH = "strategy_analytics.db"

    def __init__(self):
        self._trades: list[TradePerformance] = []
        self._lock = threading.Lock()
        self._init_durable_storage()

    def _init_durable_storage(self) -> None:
        """Initialize analytics storage"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS trade_performance (
                        trade_id TEXT PRIMARY KEY,
                        strategy_name TEXT,
                        entry_time TEXT,
                        exit_time TEXT,
                        pnl REAL,
                        return_pct REAL,
                        holding_seconds INTEGER,
                        regime TEXT
                    )
                """)
                conn.execute("CREATE INDEX idx_strategy ON trade_performance(strategy_name)")
                conn.execute("CREATE INDEX idx_entry_time ON trade_performance(entry_time)")
                conn.commit()
            _log.info("StrategyPerformanceAnalytics: Storage initialized")
        except Exception as e:
            _log.error(f"StrategyPerformanceAnalytics: Failed to init storage: {e}")

    def record_trade(
        self,
        trade_id: str,
        strategy_name: str,
        entry_time: str,
        exit_time: str,
        pnl: float,
        entry_price: float,
        exit_price: float,
        holding_seconds: int,
        regime: str = "UNKNOWN",
    ) -> None:
        """Record trade performance"""
        return_pct = ((exit_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0

        trade = TradePerformance(
            trade_id=trade_id,
            strategy_name=strategy_name,
            entry_time=entry_time,
            exit_time=exit_time,
            pnl=pnl,
            return_pct=return_pct,
            holding_seconds=holding_seconds,
            regime=regime,
        )

        with self._lock:
            self._trades.append(trade)

        self._persist_trade(trade)
        _log.debug(f"Recorded trade performance: {trade_id} P&L: {pnl:.2f}")

    def get_strategy_performance(self, strategy_name: str) -> StrategyPerformance:
        """Get performance for specific strategy"""
        with self._lock:
            trades = [t for t in self._trades if t.strategy_name == strategy_name]

            return self._calculate_performance(strategy_name, trades)

    def _calculate_performance(self, strategy_name: str, trades: list[TradePerformance]) -> StrategyPerformance:
        """Calculate performance metrics"""
        if not trades:
            return StrategyPerformance(strategy_name=strategy_name)

        total_trades = len(trades)
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl <= 0]

        win_count = len(winning_trades)
        loss_count = len(losing_trades)

        total_pnl = sum(t.pnl for t in trades)
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0

        avg_winning = sum(t.pnl for t in winning_trades) / win_count if win_count > 0 else 0
        avg_losing = sum(t.pnl for t in losing_trades) / loss_count if loss_count > 0 else 0

        hit_ratio = win_count / total_trades if total_trades > 0 else 0
        expectancy = (hit_ratio * avg_winning) - ((1 - hit_ratio) * abs(avg_losing)) if loss_count > 0 else avg_pnl

        sharpe = self._calculate_sharpe(trades)
        max_dd, max_dd_pct = self._calculate_max_drawdown(trades)

        avg_holding = sum(t.holding_seconds for t in trades) / total_trades if total_trades > 0 else 0

        win_by_regime = self._calculate_regime_performance(trades)

        return StrategyPerformance(
            strategy_name=strategy_name,
            total_trades=total_trades,
            winning_trades=win_count,
            losing_trades=loss_count,
            total_pnl=total_pnl,
            avg_pnl=avg_pnl,
            avg_winning_pnl=avg_winning,
            avg_losing_pnl=avg_losing,
            hit_ratio=hit_ratio,
            expectancy=expectancy,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            max_drawdown_pct=max_dd_pct,
            avg_holding_seconds=int(avg_holding),
            win_by_regime=win_by_regime,
        )

    def _calculate_sharpe(self, trades: list[TradePerformance], risk_free_rate: float = 0.07) -> float:
        """Calculate Sharpe ratio"""
        if len(trades) < 2:
            return 0.0

        returns = [t.return_pct / 100 for t in trades]
        avg_return = sum(returns) / len(returns)

        variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance)

        if std_dev == 0:
            return 0.0

        return (avg_return - risk_free_rate / 252) / std_dev * math.sqrt(252)

    def _calculate_max_drawdown(self, trades: list[TradePerformance]) -> tuple[float, float]:
        """Calculate maximum drawdown"""
        if not trades:
            return 0.0, 0.0

        sorted_trades = sorted(trades, key=lambda t: t.entry_time)

        equity = 0.0
        peak = 0.0
        max_dd = 0.0

        for trade in sorted_trades:
            equity += trade.pnl
            if equity > peak:
                peak = equity

            dd = peak - equity
            if dd > max_dd:
                max_dd = dd

        max_dd_pct = (max_dd / peak * 100) if peak > 0 else 0
        return max_dd, max_dd_pct

    def _calculate_regime_performance(self, trades: list[TradePerformance]) -> dict[str, dict[str, Any]]:
        """Calculate performance by regime"""
        regime_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})

        for trade in trades:
            regime = trade.regime
            regime_stats[regime]["trades"] += 1
            if trade.pnl > 0:
                regime_stats[regime]["wins"] += 1
            regime_stats[regime]["pnl"] += trade.pnl

        result = {}
        for regime, stats in regime_stats.items():
            result[regime] = {
                "total_trades": stats["trades"],
                "winning_trades": stats["wins"],
                "win_rate": stats["wins"] / stats["trades"] if stats["trades"] > 0 else 0,
                "total_pnl": stats["pnl"],
            }

        return result

    def get_all_strategies(self) -> list[str]:
        """Get all strategy names"""
        with self._lock:
            return list(set(t.strategy_name for t in self._trades))

    def get_top_performers(self, limit: int = 5) -> list[StrategyPerformance]:
        """Get top performing strategies"""
        strategies = self.get_all_strategies()

        performances = []
        for name in strategies:
            perf = self.get_strategy_performance(name)
            performances.append(perf)

        return sorted(performances, key=lambda p: p.total_pnl, reverse=True)[:limit]

    def get_worst_performers(self, limit: int = 5) -> list[StrategyPerformance]:
        """Get worst performing strategies"""
        strategies = self.get_all_strategies()

        performances = []
        for name in strategies:
            perf = self.get_strategy_performance(name)
            performances.append(perf)

        return sorted(performances, key=lambda p: p.total_pnl)[:limit]

    def get_recent_performance(self, days: int = 30) -> dict[str, Any]:
        """Get recent performance summary"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        with self._lock:
            recent = [t for t in self._trades if t.entry_time >= cutoff]

        if not recent:
            return {"total_trades": 0, "total_pnl": 0.0}

        return {
            "period_days": days,
            "total_trades": len(recent),
            "total_pnl": sum(t.pnl for t in recent),
            "avg_pnl": sum(t.pnl for t in recent) / len(recent),
            "avg_holding_seconds": sum(t.holding_seconds for t in recent) / len(recent),
        }

    def _persist_trade(self, trade: TradePerformance) -> None:
        """Persist trade to DB"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO trade_performance
                    (trade_id, strategy_name, entry_time, exit_time, pnl, return_pct, holding_seconds, regime)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade.trade_id,
                    trade.strategy_name,
                    trade.entry_time,
                    trade.exit_time,
                    trade.pnl,
                    trade.return_pct,
                    trade.holding_seconds,
                    trade.regime,
                ))
                conn.commit()
        except Exception as e:
            _log.error(f"Failed to persist trade: {e}")


_analytics: StrategyPerformanceAnalytics | None = None
_analytics_lock = threading.Lock()


def get_strategy_analytics() -> StrategyPerformanceAnalytics:
    """Get singleton strategy analytics"""
    global _analytics
    with _analytics_lock:
        if _analytics is None:
            _analytics = StrategyPerformanceAnalytics()
        return _analytics
