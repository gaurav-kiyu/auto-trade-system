"""
P&L Attribution Analysis (v2.45 Item 13).

Breaks down trade P&L by multiple dimensions to identify which market
conditions, regimes, sessions, and score tiers drive profitability.

Public API
----------
    compute_pnl_attribution(db_path, days, cfg) → list[AttributionResult]
    format_attribution_table(results, title)    → str

Config keys
-----------
    pnl_attribution_enabled : bool  default true
    pnl_attribution_days    : int   default 30
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

DIMENSIONS = ("direction", "regime", "session", "score_tier", "day_of_week")


@dataclass
class AttributionResult:
    dimension:  str
    bucket:     str
    trades:     int
    wins:       int
    win_rate:   float   # 0-1
    total_pnl:  float
    avg_pnl:    float


def _score_tier(score: float | None) -> str:
    if score is None:
        return "UNKNOWN"
    s = float(score)
    if s >= 80:
        return "HIGH(80+)"
    if s >= 65:
        return "MED(65-79)"
    return "LOW(<65)"


def _load_trades(db_path: str, days: int) -> list[dict]:
    try:
        con = sqlite3.connect(db_path, timeout=10)
        con.row_factory = sqlite3.Row
        cur = con.execute(
            """
            SELECT direction, regime, session, score, day_of_week,
                   net_pnl, exit_reason
            FROM trades
            WHERE DATE(ts) >= DATE('now', ? || ' days')
            ORDER BY id DESC
            """,
            (f"-{days}",),
        )
        rows = [dict(r) for r in cur.fetchall()]
        con.close()
        return rows
    except Exception as e:
        _log.debug("[ATTR] db load failed: %s", e)
        return []


def _group_by(rows: list[dict], key_fn) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        k = str(key_fn(r))
        groups.setdefault(k, []).append(r)
    return groups


def _summarise(dimension: str, bucket: str, rows: list[dict]) -> AttributionResult:
    pnls = [float(r.get("net_pnl") or 0.0) for r in rows]
    wins = sum(1 for p in pnls if p > 0)
    total = sum(pnls)
    n = len(pnls)
    return AttributionResult(
        dimension=dimension,
        bucket=bucket,
        trades=n,
        wins=wins,
        win_rate=wins / n if n else 0.0,
        total_pnl=round(total, 2),
        avg_pnl=round(total / n, 2) if n else 0.0,
    )


def compute_pnl_attribution(
    db_path: str = "trades.db",
    days: int = 30,
    cfg: dict[str, Any] | None = None,
) -> list[AttributionResult]:
    """
    Compute P&L attribution across all standard dimensions.

    Args:
        db_path: path to trades SQLite database.
        days:    lookback window in days.
        cfg:     config dict.

    Returns:
        List of AttributionResult, one per (dimension, bucket) pair.
    """
    c = cfg or {}
    if not c.get("pnl_attribution_enabled", True):
        return []

    days = int(c.get("pnl_attribution_days", days))
    rows = _load_trades(db_path, days)
    if not rows:
        return []

    key_fns = {
        "direction":   lambda r: r.get("direction") or "UNKNOWN",
        "regime":      lambda r: r.get("regime") or "UNKNOWN",
        "session":     lambda r: r.get("session") or "UNKNOWN",
        "score_tier":  lambda r: _score_tier(r.get("score")),
        "day_of_week": lambda r: r.get("day_of_week") or "UNKNOWN",
    }

    results: list[AttributionResult] = []
    for dim, fn in key_fns.items():
        for bucket, group in sorted(_group_by(rows, fn).items()):
            results.append(_summarise(dim, bucket, group))

    return results


def format_attribution_table(
    results: list[AttributionResult],
    title: str = "P&L Attribution",
) -> str:
    """Render attribution results as a readable text table."""
    if not results:
        return f"[{title}] no data"

    lines = [f"=== {title} ==="]
    cur_dim = None
    for r in results:
        if r.dimension != cur_dim:
            cur_dim = r.dimension
            lines.append(f"\n[{cur_dim.upper()}]")
            lines.append(f"  {'Bucket':<18} {'Trades':>6} {'WR%':>6} {'TotalPnL':>10} {'AvgPnL':>9}")
            lines.append("  " + "-" * 55)
        wr = f"{r.win_rate * 100:.0f}%"
        lines.append(
            f"  {r.bucket:<18} {r.trades:>6} {wr:>6} "
            f"{r.total_pnl:>10.0f} {r.avg_pnl:>9.0f}"
        )
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser(description="P&L Attribution Analysis")
    p.add_argument("--db",   default="trades.db", help="trades DB path")
    p.add_argument("--days", type=int, default=30, help="lookback days")
    args = p.parse_args()

    results = compute_pnl_attribution(db_path=args.db, days=args.days)
    if not results:
        print("[pnl_attribution] no trades found in the last", args.days, "days")
        sys.exit(0)
    print(format_attribution_table(results, f"P&L Attribution — last {args.days} days"))
