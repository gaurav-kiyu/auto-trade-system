"""
Strategy Performance Tracker — per-strategy PnL, win rate, Sharpe, ranking.

Stores trade outcomes per strategy in SQLite so strategies can be compared
objectively. Supports ranking, time-windowed analysis, and export.

Inspired by the A/B Strategy Tester pattern but extended to N strategies
with persistent storage and configurable time windows.
"""

from __future__ import annotations

import json
import logging
import math
import threading
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from core.datetime_ist import now_ist
from core.db_utils import get_connection

_log = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

TRACKER_DB = "strategy_performance.db"
DEFAULT_WINDOW_DAYS = 90


# ── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class StrategyTradeRecord:
    """A single trade outcome for a strategy.

    Attributes:
        trade_id: Unique trade identifier.
        strategy_name: Name of the strategy that generated this trade.
        strategy_version: Version string of the strategy.
        direction: Trade direction (BUY/SELL or CALL/PUT).
        symbol: Instrument symbol.
        entry_price: Entry price of the trade.
        exit_price: Exit price, or None if still open.
        pnl: Net P&L of the trade, or None if still open.
        entry_time: ISO timestamp of entry.
        exit_time: ISO timestamp of exit, or None.
        outcome: WIN, LOSS, or OPEN.
        signal_score: Score of the signal that triggered the trade.
        metadata: Arbitrary metadata dict.
    """
    trade_id: str = ""
    strategy_name: str = ""
    strategy_version: str = "1.0.0"
    direction: str = ""
    symbol: str = ""
    entry_price: float = 0.0
    exit_price: float | None = None
    pnl: float | None = None
    entry_time: str = ""
    exit_time: str | None = None
    outcome: str = "OPEN"
    signal_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyMetrics:
    """Aggregated performance metrics for a single strategy.

    Attributes:
        strategy_name: Name of the strategy.
        strategy_version: Version string.
        total_trades: Total number of closed trades.
        wins: Number of winning trades.
        losses: Number of losing trades.
        win_rate: Win rate as a fraction (0-1).
        total_pnl: Net P&L.
        avg_pnl: Average P&L per trade.
        max_drawdown: Maximum peak-to-trough drawdown.
        sharpe: Sharpe ratio of trade P&Ls.
        profit_factor: Gross profit / gross loss.
        avg_win: Average winning trade P&L.
        avg_loss: Average losing trade P&L.
        best_trade: Best single trade P&L.
        worst_trade: Worst single trade P&L.
        consecutive_wins: Longest winning streak.
        consecutive_losses: Longest losing streak.
        open_trades: Number of currently open trades.
        window_days: Time window in days for this metric calculation.
    """
    strategy_name: str = ""
    strategy_version: str = ""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    open_trades: int = 0
    window_days: int = DEFAULT_WINDOW_DAYS


@dataclass
class StrategyRanking:
    """Ranked list of strategies by a given metric.

    Attributes:
        rankings: List of (rank, strategy_name, metric_value) tuples.
        metric: The metric used for ranking.
        timestamp: When the ranking was generated.
        total_strategies: Number of strategies evaluated.
    """
    rankings: list[tuple[int, str, float]] = field(default_factory=list)
    metric: str = "sharpe"
    timestamp: str = ""
    total_strategies: int = 0


# ── Performance Tracker ────────────────────────────────────────────────────


class StrategyPerformanceTracker:
    """Tracks per-strategy trade outcomes and computes metrics.

    Thread-safe. SQLite-backed for persistence across restarts.
    Supports time-windowed metric calculation, ranking, and export.

    Usage:
        tracker = StrategyPerformanceTracker()
        tracker.record_trade("TRADE-1", "MomentumStrategy", pnl=150.0,
                             direction="BUY", symbol="NIFTY", entry_price=23500.0)
        metrics = tracker.get_metrics("MomentumStrategy")
        ranking = tracker.get_rankings(metric="sharpe")
    """

    def __init__(self, db_path: str = TRACKER_DB) -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    # ── DB setup ────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        try:
            with get_connection(self._db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS strategy_trades (
                        trade_id TEXT PRIMARY KEY,
                        strategy_name TEXT NOT NULL,
                        strategy_version TEXT DEFAULT '1.0.0',
                        direction TEXT DEFAULT '',
                        symbol TEXT DEFAULT '',
                        entry_price REAL DEFAULT 0.0,
                        exit_price REAL,
                        pnl REAL,
                        entry_time TEXT NOT NULL,
                        exit_time TEXT,
                        outcome TEXT DEFAULT 'OPEN',
                        signal_score REAL DEFAULT 0.0,
                        metadata_json TEXT DEFAULT '{}'
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_strategy_trades_name
                    ON strategy_trades(strategy_name)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_strategy_trades_time
                    ON strategy_trades(entry_time)
                """)
                conn.commit()
        except Exception as exc:
            _log.error("[PerfTracker] DB init failed: %s", exc)

    # ── Recording trades ────────────────────────────────────────────────

    def record_trade(
        self,
        trade_id: str,
        strategy_name: str,
        pnl: float | None = None,
        direction: str = "",
        symbol: str = "",
        entry_price: float = 0.0,
        exit_price: float | None = None,
        entry_time: str | None = None,
        exit_time: str | None = None,
        outcome: str = "WIN",
        signal_score: float = 0.0,
        strategy_version: str = "1.0.0",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a completed trade outcome for a strategy.

        Thread-safe: uses internal lock. Upserts on trade_id to allow
        updating open trades with exit information.
        """
        with self._lock:
            try:
                now = now_ist().isoformat() if entry_time is None else entry_time
                with get_connection(self._db_path) as conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO strategy_trades
                        (trade_id, strategy_name, strategy_version, direction,
                         symbol, entry_price, exit_price, pnl,
                         entry_time, exit_time, outcome, signal_score,
                         metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        trade_id,
                        strategy_name,
                        strategy_version,
                        direction,
                        symbol,
                        entry_price,
                        exit_price,
                        pnl,
                        now,
                        exit_time or now,
                        outcome,
                        signal_score,
                        json.dumps(metadata or {}),
                    ))
                    conn.commit()
            except Exception as exc:
                _log.error("[PerfTracker] Failed to record trade %s: %s",
                           trade_id, exc)

    def update_trade_exit(
        self,
        trade_id: str,
        exit_price: float,
        pnl: float,
        exit_time: str | None = None,
        outcome: str = "WIN",
    ) -> None:
        """Update a previously recorded open trade with exit information."""
        with self._lock:
            try:
                now = now_ist().isoformat() if exit_time is None else exit_time
                with get_connection(self._db_path) as conn:
                    conn.execute("""
                        UPDATE strategy_trades
                        SET exit_price = ?, pnl = ?, exit_time = ?,
                            outcome = ?
                        WHERE trade_id = ?
                    """, (exit_price, pnl, now, outcome, trade_id))
                    conn.commit()
            except Exception as exc:
                _log.error("[PerfTracker] Failed to update trade %s: %s",
                           trade_id, exc)

    # ── Metrics computation ─────────────────────────────────────────────

    def get_metrics(
        self,
        strategy_name: str,
        window_days: int = DEFAULT_WINDOW_DAYS,
    ) -> StrategyMetrics:
        """Compute aggregated metrics for a single strategy.

        Args:
            strategy_name: Name of the strategy.
            window_days: Look-back window in days (0 = all time).

        Returns:
            StrategyMetrics with all computed fields.
        """
        with self._lock:
            try:
                with get_connection(self._db_path) as conn:
                    # Determine cutoff
                    if window_days > 0:
                        cutoff = (now_ist() - timedelta(days=window_days)).isoformat()
                        rows = conn.execute(
                            "SELECT pnl, outcome FROM strategy_trades "
                            "WHERE strategy_name = ? AND entry_time >= ?",
                            (strategy_name, cutoff),
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            "SELECT pnl, outcome FROM strategy_trades "
                            "WHERE strategy_name = ?",
                            (strategy_name,),
                        ).fetchall()

                    pnls = []
                    open_trades = 0
                    for row in rows:
                        pnl_val = row[0]
                        outcome_val = row[1]
                        if outcome_val == "OPEN":
                            open_trades += 1
                        elif pnl_val is not None:
                            pnls.append(pnl_val)

                total = len(pnls)
                if total == 0:
                    return StrategyMetrics(
                        strategy_name=strategy_name,
                        open_trades=open_trades,
                        window_days=window_days,
                    )

                wins = [p for p in pnls if p > 0]
                losses = [p for p in pnls if p < 0]
                num_wins = len(wins)
                num_losses = len(losses)
                total_pnl = sum(pnls)
                avg_pnl = total_pnl / total

                # Win rate
                win_rate = num_wins / total if total > 0 else 0.0

                # Profit factor
                gross_profit = sum(wins) if wins else 0.0
                gross_loss = abs(sum(losses)) if losses else 0.0
                profit_factor = (gross_profit / gross_loss
                                 if gross_loss > 0
                                 else (10.0 if gross_profit > 0 else 0.0))

                # Average win/loss
                avg_win = (sum(wins) / num_wins) if num_wins > 0 else 0.0
                avg_loss = (sum(losses) / num_losses) if num_losses > 0 else 0.0

                # Best/worst trade
                best_trade = max(pnls) if pnls else 0.0
                worst_trade = min(pnls) if pnls else 0.0

                # Sharpe ratio
                sharpe = 0.0
                if total >= 2:
                    mean = total_pnl / total
                    variance = sum((p - mean) ** 2 for p in pnls) / total
                    std = math.sqrt(variance) if variance > 0 else 0.0
                    sharpe = mean / std if std > 0 else 0.0

                # Max drawdown
                max_dd = 0.0
                running_max = 0.0
                cumulative = 0.0
                for p in pnls:
                    cumulative += p
                    if cumulative > running_max:
                        running_max = cumulative
                    dd = running_max - cumulative
                    if dd > max_dd:
                        max_dd = dd

                # Consecutive wins/losses
                max_cons_wins = 0
                max_cons_losses = 0
                cur_wins = 0
                cur_losses = 0
                for p in pnls:
                    if p > 0:
                        cur_wins += 1
                        cur_losses = 0
                        max_cons_wins = max(max_cons_wins, cur_wins)
                    elif p < 0:
                        cur_losses += 1
                        cur_wins = 0
                        max_cons_losses = max(max_cons_losses, cur_losses)

                return StrategyMetrics(
                    strategy_name=strategy_name,
                    total_trades=total,
                    wins=num_wins,
                    losses=num_losses,
                    win_rate=round(win_rate, 4),
                    total_pnl=round(total_pnl, 2),
                    avg_pnl=round(avg_pnl, 2),
                    max_drawdown=round(max_dd, 2),
                    sharpe=round(sharpe, 4),
                    profit_factor=round(profit_factor, 2),
                    avg_win=round(avg_win, 2),
                    avg_loss=round(avg_loss, 2),
                    best_trade=round(best_trade, 2),
                    worst_trade=round(worst_trade, 2),
                    consecutive_wins=max_cons_wins,
                    consecutive_losses=max_cons_losses,
                    open_trades=open_trades,
                    window_days=window_days,
                )

            except Exception as exc:
                _log.error("[PerfTracker] Failed to compute metrics for %s: %s",
                           strategy_name, exc)
                return StrategyMetrics(strategy_name=strategy_name)

    # ── Ranking ─────────────────────────────────────────────────────────

    def get_rankings(
        self,
        metric: str = "sharpe",
        window_days: int = DEFAULT_WINDOW_DAYS,
        min_trades: int = 5,
    ) -> StrategyRanking:
        """Rank all strategies by a given metric.

        Args:
            metric: Metric to rank by (sharpe, win_rate, total_pnl,
                    profit_factor, avg_pnl).
            window_days: Look-back window.
            min_trades: Minimum trades required to be ranked.

        Returns:
            StrategyRanking with sorted list of (rank, strategy, value).
        """
        with self._lock:
            try:
                with get_connection(self._db_path) as conn:
                    strategy_names = [
                        row[0] for row in conn.execute(
                            "SELECT DISTINCT strategy_name FROM strategy_trades"
                        ).fetchall()
                    ]
            except Exception as exc:
                _log.error("[PerfTracker] Failed to get strategy names: %s", exc)
                strategy_names = []

        if not strategy_names:
            return StrategyRanking(
                metric=metric,
                timestamp=now_ist().isoformat(),
            )

        results: list[tuple[float, str]] = []
        for name in strategy_names:
            metrics = self.get_metrics(name, window_days=window_days)
            if metrics.total_trades < min_trades:
                continue

            value = getattr(metrics, metric, None)
            if value is None:
                continue
            # For drawdown, lower is better (invert)
            if metric == "max_drawdown":
                results.append((-value, name))
            else:
                results.append((value, name))

        # Sort descending (best first)
        results.sort(key=lambda x: x[0], reverse=True)

        rankings = [
            (rank + 1, name, round(val, 4))
            for rank, (val, name) in enumerate(results)
        ]

        return StrategyRanking(
            rankings=rankings,
            metric=metric,
            timestamp=now_ist().isoformat(),
            total_strategies=len(strategy_names),
        )

    # ── Export ──────────────────────────────────────────────────────────

    def export_trades(
        self,
        strategy_name: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Export trade records as list of dicts.

        Args:
            strategy_name: Filter to specific strategy, or None for all.
            limit: Maximum number of records.

        Returns:
            List of trade dicts for JSON serialization.
        """
        with self._lock:
            try:
                with get_connection(self._db_path) as conn:
                    if strategy_name:
                        rows = conn.execute(
                            "SELECT * FROM strategy_trades "
                            "WHERE strategy_name = ? "
                            "ORDER BY entry_time DESC LIMIT ?",
                            (strategy_name, limit),
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            "SELECT * FROM strategy_trades "
                            "ORDER BY entry_time DESC LIMIT ?",
                            (limit,),
                        ).fetchall()

                    columns = [desc[1] for desc in conn.execute(
                        "PRAGMA table_info(strategy_trades)"
                    ).fetchall()]

                return [
                    {col: row[i] for i, col in enumerate(columns)}
                    for row in rows
                ]
            except Exception as exc:
                _log.error("[PerfTracker] Export failed: %s", exc)
                return []

    def get_summary_report(self, min_trades: int = 5) -> str:
        """Generate a human-readable summary report of all strategies."""
        rankings = self.get_rankings(metric="sharpe", min_trades=min_trades)
        lines = [
            "╔══════════════════════════════════════════════════════╗",
            "║      Strategy Performance Report                     ║",
            f"║      Generated: {rankings.timestamp[:19]}                ║",
            "╚══════════════════════════════════════════════════════╝",
            "",
        ]

        if not rankings.rankings:
            lines.append("No strategies with sufficient data.")
            return "\n".join(lines)

        lines.append(f"Ranking by Sharpe (min {min_trades} trades):")
        lines.append(f"{'#':>3}  {'Strategy':<25}  {'Sharpe':>8}  {'WinRate':>8}  "
                      f"{'PnL':>10}  {'Trades':>6}")
        lines.append("-" * 70)

        for rank, name, sharpe_val in rankings.rankings:
            metrics = self.get_metrics(name)
            lines.append(
                f"{rank:>3}  {name:<25}  {sharpe_val:>8.4f}  "
                f"{metrics.win_rate:>7.1%}  "
                f"{metrics.total_pnl:>9.0f}  "
                f"{metrics.total_trades:>6}"
            )

        lines.append("")
        lines.append(f"Total strategies tracked: {rankings.total_strategies}")
        lines.append(f"Strategies with >= {min_trades} trades: {len(rankings.rankings)}")

        return "\n".join(lines)


# ── Singleton ──────────────────────────────────────────────────────────────

_perf_tracker: StrategyPerformanceTracker | None = None
_perf_lock = threading.RLock()


def get_performance_tracker(db_path: str = TRACKER_DB) -> StrategyPerformanceTracker:
    """Get singleton performance tracker."""
    global _perf_tracker
    with _perf_lock:
        if _perf_tracker is None:
            _perf_tracker = StrategyPerformanceTracker(db_path=db_path)
        return _perf_tracker


__all__ = [
    "StrategyTradeRecord",
    "StrategyMetrics",
    "StrategyRanking",
    "StrategyPerformanceTracker",
    "get_performance_tracker",
    "TRACKER_DB",
]
