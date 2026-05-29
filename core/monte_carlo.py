"""
Monte Carlo Backtest Simulation (Phase A4).

Runs N randomised reshufflings of a closed-trade P&L series to estimate the
range of possible outcomes — separating signal edge from trade-order luck.

Public API
----------
    run_simulation(pnl_list, n_simulations=1000, confidence=0.95)
        → MonteCarloResult

    plot_equity_band(result) → str (ASCII chart, no matplotlib)

    cli entry point: python -m core.monte_carlo --days 90

Config keys
-----------
    None required.  All parameters are function arguments with safe defaults.
"""
from __future__ import annotations
import logging
_log = logging.getLogger(__name__)

import argparse
import logging
import math
import random
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_DB = "trades.db"


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MonteCarloResult:
    n_simulations: int
    n_trades: int

    # Final P&L distribution
    median_final_pnl: float
    p5_final_pnl: float
    p95_final_pnl: float
    mean_final_pnl: float

    # Drawdown distribution
    median_max_drawdown: float
    p95_max_drawdown: float

    # Win probability
    prob_of_profit: float          # fraction of simulations ending positive

    # Streak
    worst_case_streak_p95: int     # 95th-percentile max consecutive losses

    # Sharpe distribution
    median_sharpe: float
    p5_sharpe: float

    # Raw equity percentiles — (list of cumulative-PnL lists at p5/p50/p95)
    # Stored as equal-length lists for plotting; empty if n_trades < 2
    equity_p5:    list[float] = field(default_factory=list)
    equity_p50:   list[float] = field(default_factory=list)
    equity_p95:   list[float] = field(default_factory=list)


# ── Core simulation ───────────────────────────────────────────────────────────

def _equity_curve(pnls: list[float]) -> list[float]:
    """Cumulative sum of a P&L list."""
    out: list[float] = []
    running = 0.0
    for p in pnls:
        running += p
        out.append(running)
    return out


def _max_drawdown(equity: list[float]) -> float:
    """Maximum peak-to-trough drawdown (positive value = loss magnitude)."""
    peak = 0.0
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _sharpe(pnls: list[float]) -> float:
    """Per-trade Sharpe ratio (mean / std). Returns 0 if std is 0."""
    n = len(pnls)
    if n < 2:
        return 0.0
    mean = sum(pnls) / n
    variance = sum((p - mean) ** 2 for p in pnls) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    return round(mean / std, 4) if std > 0 else 0.0


def _max_consec_losses(pnls: list[float]) -> int:
    """Return the maximum consecutive losing streak in a P&L sequence."""
    max_streak = 0
    streak = 0
    for p in pnls:
        if p < 0:
            streak += 1
            if streak > max_streak:
                max_streak = streak
        else:
            streak = 0
    return max_streak


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Return the pct-th percentile (0–1) of a sorted list."""
    if not sorted_vals:
        return 0.0
    idx = pct * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def run_simulation(
    pnl_list: list[float],
    *,
    n_simulations: int = 1000,
    confidence: float = 0.95,
    seed: int | None = 42,
) -> MonteCarloResult:
    """
    Run Monte Carlo simulation by shuffling trade order N times.

    Args:
        pnl_list      : List of closed-trade net P&L values (from trades.db).
        n_simulations : Number of random orderings to simulate.
        confidence    : Percentile band for result (default 0.95 → p5/p95).
        seed          : Random seed for reproducibility (None = random).

    Returns:
        MonteCarloResult with full statistical summary.

    Raises:
        ValueError if pnl_list is empty.
    """
    if not pnl_list:
        raise ValueError("pnl_list is empty — need at least 1 trade to simulate")

    n = len(pnl_list)
    rng = random.Random(seed)

    lo_pct  = (1.0 - confidence) / 2.0      # e.g. 0.025 for 95% CI
    hi_pct  = 1.0 - lo_pct                  # e.g. 0.975

    final_pnls:   list[float] = []
    max_dds:      list[float] = []
    sharpes:      list[float] = []
    streaks:      list[int]   = []

    # Store equity curves for band plot (sub-sample to keep memory reasonable)
    _store_curves = n >= 2
    all_curves:   list[list[float]] = []

    for _ in range(n_simulations):
        sim = list(pnl_list)
        rng.shuffle(sim)
        eq  = _equity_curve(sim)
        final_pnls.append(eq[-1])
        max_dds.append(_max_drawdown(eq))
        sharpes.append(_sharpe(sim))
        streaks.append(_max_consec_losses(sim))
        if _store_curves:
            all_curves.append(eq)

    final_pnls.sort()
    max_dds.sort()
    sharpes.sort()
    streaks_s = sorted(streaks)

    prob_profit = sum(1 for v in final_pnls if v > 0) / n_simulations

    # Build P5 / P50 / P95 equity bands (point-by-point across simulations)
    eq_p5: list[float]  = []
    eq_p50: list[float] = []
    eq_p95: list[float] = []
    if _store_curves and all_curves:
        for step in range(n):
            vals = sorted(c[step] for c in all_curves)
            eq_p5.append(_percentile(vals, lo_pct))
            eq_p50.append(_percentile(vals, 0.50))
            eq_p95.append(_percentile(vals, hi_pct))

    return MonteCarloResult(
        n_simulations=n_simulations,
        n_trades=n,
        median_final_pnl=round(_percentile(final_pnls, 0.50), 2),
        p5_final_pnl=round(_percentile(final_pnls, lo_pct), 2),
        p95_final_pnl=round(_percentile(final_pnls, hi_pct), 2),
        mean_final_pnl=round(sum(final_pnls) / n_simulations, 2),
        median_max_drawdown=round(_percentile(max_dds, 0.50), 2),
        p95_max_drawdown=round(_percentile(max_dds, hi_pct), 2),
        prob_of_profit=round(prob_profit, 4),
        worst_case_streak_p95=int(_percentile(streaks_s, hi_pct)),
        median_sharpe=round(_percentile(sharpes, 0.50), 4),
        p5_sharpe=round(_percentile(sharpes, lo_pct), 4),
        equity_p5=eq_p5,
        equity_p50=eq_p50,
        equity_p95=eq_p95,
    )


# ── ASCII equity band plot ────────────────────────────────────────────────────

def plot_equity_band(result: MonteCarloResult, width: int = 72, height: int = 14) -> str:
    """
    Return a pure-ASCII equity band chart (P5 / median / P95).

    No matplotlib required — compatible with terminal output and log files.

    Example output:
        ┌──────────────────────────────────────────────────────────────────────┐
        │ ₹12,400                                          ●●●●●●●●●●         │
        │          ...                                  ●●●                   │
        │               ────────────────────────────────                       │
        │                                                           ░░░░░░    │
        └────────────────── 1 ──────────────── 50 ─────────────────── 100 ───┘
          P5=₹-1,200   Median=₹8,900   P95=₹12,400   Prob>0: 87.3%
    """
    p5   = result.equity_p5
    p50  = result.equity_p50
    p95  = result.equity_p95
    n    = len(p50)

    if n < 2:
        return (
            f"Monte Carlo ({result.n_simulations} sims, {result.n_trades} trades)\n"
            f"  Insufficient trades for equity band plot (need ≥ 2).\n"
            f"  Median final P&L: ₹{result.median_final_pnl:+,.0f}\n"
            f"  Prob of profit:   {result.prob_of_profit*100:.1f}%\n"
        )

    # Downsample to `width` columns
    step = max(1, n // width)
    cols = list(range(0, n, step))[:width]

    p5_s   = [p5[i]  for i in cols]
    p50_s  = [p50[i] for i in cols]
    p95_s  = [p95[i] for i in cols]

    all_vals = p5_s + p50_s + p95_s
    lo  = min(all_vals + [0.0])
    hi  = max(all_vals + [0.0])
    span = hi - lo or 1.0

    def _row(v: float) -> int:
        return int((v - lo) / span * (height - 1))

    # Build grid
    grid = [[" "] * len(cols) for _ in range(height)]
    for ci, (v5, v50, v95) in enumerate(zip(p5_s, p50_s, p95_s)):
        r95 = _row(v95)
        r50 = _row(v50)
        r5  = _row(v5)
        if 0 <= r95 < height:
            grid[height - 1 - r95][ci] = "●"
        if 0 <= r50 < height:
            grid[height - 1 - r50][ci] = "─"
        if 0 <= r5 < height:
            grid[height - 1 - r5][ci] = "░"

    # Y-axis labels (hi / zero / lo)
    zero_row = height - 1 - _row(0.0)

    lines: list[str] = []
    lines.append("┌" + "─" * (len(cols) + 2) + "┐")
    for ri, row in enumerate(grid):
        if ri == 0:
            label = f"₹{hi:+,.0f}"
        elif ri == zero_row:
            label = "  ₹0"
        elif ri == height - 1:
            label = f"₹{lo:+,.0f}"
        else:
            label = ""
        lines.append("│ " + "".join(row) + f" {label}")
    lines.append("└" + "─" * (len(cols) + 2) + "┘")
    lines.append(
        f"  P5=₹{result.p5_final_pnl:+,.0f}  "
        f"Median=₹{result.median_final_pnl:+,.0f}  "
        f"P95=₹{result.p95_final_pnl:+,.0f}  "
        f"Prob>0: {result.prob_of_profit*100:.1f}%  "
        f"(─=median ●=P95 ░=P5)"
    )
    return "\n".join(lines)


# ── Data loader ───────────────────────────────────────────────────────────────

def load_pnl_from_db(
    db_path: str = _DEFAULT_DB,
    *,
    days: int = 90,
    mode: str | None = None,
) -> list[float]:
    """
    Load closed-trade net P&L values from trades.db.

    Args:
        db_path : Path to trades.db.
        days    : Look-back window in days (0 = all time).
        mode    : "PAPER", "LIVE", or None/empty for all modes.

    Returns:
        List of float net_pnl values, ordered by entry timestamp.

    Raises:
        FileNotFoundError if db_path does not exist.
    """
    p = Path(db_path)
    if not p.is_file():
        raise FileNotFoundError(f"trades.db not found: {db_path}")
    try:
        conn = sqlite3.connect(str(p), check_same_thread=False, timeout=10)
        conn.text_factory = lambda b: b.decode("utf-8", "replace")
        params: list[Any] = []
        where_parts: list[str] = ["net_pnl IS NOT NULL"]
        if days and days > 0:
            from datetime import timedelta

            from core.datetime_ist import now_ist
            cutoff = (now_ist() - timedelta(days=days)).isoformat()
            where_parts.append("ts >= ?")
            params.append(cutoff)
        if mode and mode.upper() != "ALL":
            where_parts.append("mode = ?")
            params.append(mode.upper())
        where = " AND ".join(where_parts)
        rows = conn.execute(
            f"SELECT net_pnl FROM trades WHERE {where} ORDER BY ts",
            params,
        ).fetchall()
        conn.close()
        return [float(r[0]) for r in rows if r[0] is not None]
    except sqlite3.Error as exc:
        _log.warning("[MC] DB read failed: %s", exc)
        return []


# ── Summary formatter ─────────────────────────────────────────────────────────

def format_summary(result: MonteCarloResult) -> str:
    """Return a compact multi-line summary suitable for PDF or console."""
    lines = [
        f"Monte Carlo Robustness Analysis ({result.n_simulations:,} simulations, {result.n_trades} trades)",
        "",
        f"  Final P&L   P5: ₹{result.p5_final_pnl:+,.0f}  "
        f"Median: ₹{result.median_final_pnl:+,.0f}  "
        f"P95: ₹{result.p95_final_pnl:+,.0f}",
        f"  Max Drawdown  Median: ₹{result.median_max_drawdown:,.0f}  "
        f"P95 (worst): ₹{result.p95_max_drawdown:,.0f}",
        f"  Prob of Profit:   {result.prob_of_profit*100:.1f}%",
        f"  Worst Streak P95: {result.worst_case_streak_p95} consecutive losses",
        f"  Sharpe  Median: {result.median_sharpe:.3f}  P5: {result.p5_sharpe:.3f}",
    ]
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> None:
    p = argparse.ArgumentParser(description="OPB Monte Carlo Backtest Simulation")
    p.add_argument("--db",   default=_DEFAULT_DB, help="Path to trades.db")
    p.add_argument("--days", default=90, type=int, help="Look-back days (0 = all)")
    p.add_argument("--mode", default="ALL",        help="PAPER | LIVE | ALL")
    p.add_argument("--n",    default=1000, type=int, help="Number of simulations")
    p.add_argument("--seed", default=42, type=int,  help="Random seed")
    args = p.parse_args()

    mode = None if args.mode.upper() == "ALL" else args.mode.upper()
    pnls = load_pnl_from_db(args.db, days=args.days, mode=mode)
    if not pnls:
        print(f"No trades found in {args.db} (days={args.days} mode={args.mode})")
        return

    print(f"Running {args.n} simulations on {len(pnls)} trades...")
    result = run_simulation(pnls, n_simulations=args.n, seed=args.seed)
    print()
    print(format_summary(result))
    print()
    print(plot_equity_band(result))


if __name__ == "__main__":
    _cli()
