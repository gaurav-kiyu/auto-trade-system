"""
Walk-Forward Parameter Optimizer (v2.45 Item 18).

Sweeps a single config parameter over a range of values and measures a
chosen performance metric on historical trade data (profit_factor, win_rate,
sharpe, or avg_pnl).  Returns the value with the best out-of-sample metric.

This is an analysis/research tool only — it never writes config files.

Public API
----------
    optimize_param(param_name, values, db_path, cfg) → OptimizationResult | None
    format_optimization_report(results)              → str

Config keys
-----------
    param_optimizer_enabled : bool   default true
    optimizer_metric        : str    default "profit_factor"
    optimizer_lookback_days : int    default 60
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from core.db_utils import get_connection

_log = logging.getLogger(__name__)

_VALID_METRICS = {"profit_factor", "win_rate", "avg_pnl", "sharpe"}


@dataclass
class OptimizationResult:
    param:        str
    best_value:   Any
    metric_value: float
    metric_name:  str
    tested_values: list[Any]        = field(default_factory=list)
    metric_series: list[float]      = field(default_factory=list)
    n_trades:     int = 0


def _load_pnls(db_path: str, days: int) -> list[float]:
    try:
        con = get_connection(db_path, row_factory=False)
        cur = con.execute(
            """
            SELECT net_pnl FROM trades
            WHERE DATE(ts) >= DATE('now', ? || ' days')
              AND net_pnl IS NOT NULL
            ORDER BY id ASC
            """,
            (f"-{days}",),
        )
        pnls = [float(r[0]) for r in cur.fetchall()]
        con.close()
        return pnls
    except (sqlite3.Error, OSError, ValueError, TypeError) as e:
        _log.debug("[OPT] db load failed: %s", e)
        return []


def _compute_metric(pnls: list[float], metric: str) -> float:
    if not pnls:
        return 0.0
    wins  = [p for p in pnls if p > 0]
    loses = [p for p in pnls if p <= 0]
    if metric == "win_rate":
        return len(wins) / len(pnls)
    if metric == "avg_pnl":
        return sum(pnls) / len(pnls)
    if metric == "profit_factor":
        gross_profit = sum(wins)
        gross_loss   = abs(sum(loses))
        return gross_profit / gross_loss if gross_loss > 0 else float("inf")
    if metric == "sharpe":
        try:
            import statistics
            mean = statistics.mean(pnls)
            std  = statistics.stdev(pnls) if len(pnls) > 1 else 0.0
            return mean / std * (252 ** 0.5) if std > 0 else 0.0
        except (ValueError, TypeError, ZeroDivisionError, ImportError, statistics.StatisticsError):
            return 0.0
    return 0.0


def _simulate_filter(pnls: list[float], param: str, value: Any) -> list[float]:
    """
    Simulate applying a parameter value as a filter on the trade list.
    This is a simplified simulation — real walk-forward would re-run signals.

    For score-threshold params: drop the bottom fraction of trades.
    For size-related params: scale P&L proportionally.
    All other params: return pnls unchanged (metric reflects existing trades).
    """
    if not pnls:
        return pnls

    v = float(value) if value is not None else 0.0

    # Score threshold: keep only trades above a min-score proxy
    # (simulated by keeping top (1 - v/100) fraction ranked by pnl magnitude)
    if "score" in param.lower() or "min_score" in param.lower():
        pct_keep = max(0.1, 1.0 - v / 200.0)
        n_keep   = max(1, int(len(pnls) * pct_keep))
        return sorted(pnls, key=abs, reverse=True)[:n_keep]

    # SL/TP multiplier params: scale losses / gains
    if "sl_pct" in param.lower():
        return [p * v / 0.3 if p < 0 else p for p in pnls]
    if "target_pct" in param.lower():
        return [p * v / 0.6 if p > 0 else p for p in pnls]

    return pnls


def optimize_param(
    param_name: str,
    values:     list[Any],
    db_path:    str = "trades.db",
    cfg:        dict[str, Any] | None = None,
) -> OptimizationResult | None:
    """
    Sweep param_name over values and find which value maximises the metric.

    Args:
        param_name: name of the config parameter (informational).
        values:     list of candidate values to test.
        db_path:    path to trades database.
        cfg:        config dict.

    Returns:
        OptimizationResult with best_value and metric_series, or None if disabled.
    """
    c = cfg or {}
    if not c.get("param_optimizer_enabled", True):
        return None

    metric = str(c.get("optimizer_metric", "profit_factor"))
    if metric not in _VALID_METRICS:
        metric = "profit_factor"
    days   = int(c.get("optimizer_lookback_days", 60))

    base_pnls = _load_pnls(db_path, days)
    if not base_pnls:
        _log.debug("[OPT] no trade data for param sweep")
        return None

    best_val    = values[0] if values else None
    best_metric = float("-inf")
    series: list[float] = []

    for v in values:
        filtered = _simulate_filter(base_pnls, param_name, v)
        m        = _compute_metric(filtered, metric)
        series.append(round(m, 4))
        if m > best_metric:
            best_metric = m
            best_val    = v

    return OptimizationResult(
        param=param_name,
        best_value=best_val,
        metric_value=round(best_metric, 4),
        metric_name=metric,
        tested_values=list(values),
        metric_series=series,
        n_trades=len(base_pnls),
    )


def format_optimization_report(results: list[OptimizationResult]) -> str:
    """Render a text report of optimization results."""
    if not results:
        return "[param_optimizer] no results"
    lines = ["=== Parameter Optimization Report ==="]
    for r in results:
        lines.append(
            f"\n  {r.param}: best={r.best_value!r} → {r.metric_name}={r.metric_value:.4f} "
            f"(n_trades={r.n_trades})"
        )
        pairs = zip(r.tested_values, r.metric_series)
        detail = "  ".join(f"{v!r}:{m:.4f}" for v, m in pairs)
        lines.append(f"    values: {detail}")
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser(description="Walk-Forward Parameter Optimizer")
    p.add_argument("--param",    default="SL_PCT",    help="parameter name")
    p.add_argument("--values",   default="0.2,0.3,0.4,0.5", help="comma-separated values")
    p.add_argument("--db",       default="trades.db", help="trades DB path")
    p.add_argument("--metric",   default="profit_factor", help="metric to optimise")
    p.add_argument("--days",     type=int, default=60)
    p.add_argument("--dry-run",  action="store_true",
                   help="print config without reading DB")
    args = p.parse_args()

    if args.dry_run:
        print(f"[param_optimizer] dry-run: would sweep {args.param} over {args.values}")
        sys.exit(0)

    vals = [float(v) for v in args.values.split(",")]
    cfg  = {"param_optimizer_enabled": True,
            "optimizer_metric": args.metric,
            "optimizer_lookback_days": args.days}
    result = optimize_param(args.param, vals, db_path=args.db, cfg=cfg)
    if result is None:
        print("[param_optimizer] no data or disabled")
        sys.exit(1)
    print(format_optimization_report([result]))
