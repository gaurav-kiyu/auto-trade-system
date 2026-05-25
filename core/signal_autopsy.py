"""
Signal Autopsy (Step 3) — post-trade analysis of why signals succeeded or failed.

For each closed trade, the autopsy correlates the entry signal attributes
(score, tier, direction, session, regime, IV rank, VIX, PCR) with the actual
outcome (winner/loser, P&L, duration) to surface actionable patterns.

Three analysis layers:
  1. Feature breakdown  — win rate by score bin, tier, direction, regime,
                          session, iv_rank bucket
  2. Failure patterns   — most common feature combinations in losing trades
  3. Edge decay check   — rolling win rate over time (are recent trades worse?)

Public API
----------
    load_autopsy_data(db_path, days, mode) → list[dict]

    compute_feature_breakdown(trades) → dict[str, dict]

    find_failure_patterns(trades, top_n) → list[dict]

    compute_edge_decay(trades, window) → list[dict]

    run_autopsy(db_path, *, days, mode, cfg) → AutopsyReport

    format_autopsy_report(report) → str

Config keys (all optional — safe defaults built in)
---------------------------------------------------
  signal_autopsy_enabled   : bool default true
  signal_autopsy_days      : int  default 30
  signal_autopsy_window    : int  default 10  (rolling window for edge decay)
  signal_autopsy_top_n     : int  default 5   (top failure patterns to surface)
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DAYS_MAP = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}

_log = logging.getLogger(__name__)

_DEFAULT_DB    = "trades.db"
_DEFAULT_DAYS  = 30
_DEFAULT_WIN   = 10
_DEFAULT_TOP_N = 5


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class AutopsyReport:
    n_trades:          int
    n_winners:         int
    n_losers:          int
    overall_win_rate:  float

    # Feature-level breakdown {dim: {bucket: {win_rate, trades, avg_pnl}}}
    feature_breakdown: dict[str, dict] = field(default_factory=dict)

    # Top failure pattern descriptions
    failure_patterns:  list[dict] = field(default_factory=list)

    # Rolling win rate over time [{index, win_rate, trades}]
    edge_decay:        list[dict] = field(default_factory=list)

    # Human-readable insights
    insights:          list[str] = field(default_factory=list)

    # Trade time heatmap (win rate by hour × day_of_week); None when not computed
    time_heatmap: TimeHeatmap | None = None


# ── Heatmap dataclasses (v2.44 Item 16) ──────────────────────────────────────

@dataclass
class HeatmapCell:
    hour:        int
    day_of_week: int            # 0=Monday … 6=Sunday
    n_trades:    int
    n_wins:      int
    win_rate:    float          # 0.0–1.0
    avg_pnl:     float


@dataclass
class TimeHeatmap:
    """Win-rate heatmap keyed by (hour, day_of_week)."""
    cells:       list[HeatmapCell] = field(default_factory=list)
    hours:       list[int]         = field(default_factory=list)   # sorted unique hours
    days:        list[int]         = field(default_factory=list)   # sorted unique days
    min_cell_trades: int           = 3


# ── Data loader ───────────────────────────────────────────────────────────────

def load_autopsy_data(
    db_path: str = _DEFAULT_DB,
    *,
    days: int = _DEFAULT_DAYS,
    mode: str | None = None,
) -> list[dict]:
    """
    Load closed trades from trades.db for autopsy analysis.

    Returns:
        List of trade dicts with keys: ts, index_name, direction, score,
        net_pnl, regime, iv, vix, mode, is_winner.
        Empty list if db is missing or no matching trades.
    """
    p = Path(db_path)
    if not p.is_file():
        return []
    try:
        conn = sqlite3.connect(str(p), check_same_thread=False, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            params: list[Any] = []
            where  = ["net_pnl IS NOT NULL"]
            if days and days > 0:
                from datetime import timedelta

                from core.datetime_ist import now_ist
                cutoff = (now_ist() - timedelta(days=days)).isoformat()
                where.append("ts >= ?")
                params.append(cutoff)
            if mode and mode.upper() not in ("ALL", ""):
                where.append("mode = ?")
                params.append(mode.upper())
            sql = f"SELECT * FROM trades WHERE {' AND '.join(where)} ORDER BY ts"
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()

        trades = []
        for row in rows:
            d     = dict(row)
            pnl   = float(d.get("net_pnl") or 0)
            score = float(d.get("score") or 0)
            trades.append({
                "ts":          str(d.get("ts") or ""),
                "index_name":  str(d.get("index_name") or ""),
                "direction":   str(d.get("direction") or ""),
                "score":       score,
                "score_bin":   _score_bin(score),
                "net_pnl":     pnl,
                "regime":      str(d.get("regime") or "UNKNOWN"),
                "iv":          float(d.get("iv") or 0),
                "vix":         float(d.get("vix") or 0),
                "mode":        str(d.get("mode") or ""),
                "is_winner":   1 if pnl > 0 else 0,
            })
        return trades
    except Exception as exc:
        _log.debug("[AUTOPSY] load_autopsy_data failed: %s", exc)
        return []


def _score_bin(score: float) -> str:
    if score >= 90: return "90+"
    if score >= 80: return "80-89"
    if score >= 70: return "70-79"
    if score >= 60: return "60-69"
    return "<60"


# ── Feature breakdown ─────────────────────────────────────────────────────────

def compute_feature_breakdown(
    trades: list[dict],
) -> dict[str, dict]:
    """
    Compute win rate, trade count, and average P&L for each dimension bucket.

    Dimensions analysed: score_bin, direction, regime, index_name.

    Returns:
        {dimension: {bucket: {"trades": int, "win_rate": float, "avg_pnl": float}}}
    """
    if not trades:
        return {}

    dims = ["score_bin", "direction", "regime", "index_name"]
    result: dict[str, dict] = {}

    for dim in dims:
        buckets: dict[str, list[dict]] = {}
        for t in trades:
            key = str(t.get(dim) or "UNKNOWN")
            buckets.setdefault(key, []).append(t)

        result[dim] = {}
        for bucket, items in sorted(buckets.items()):
            n     = len(items)
            wins  = sum(t["is_winner"] for t in items)
            total = sum(t["net_pnl"] for t in items)
            result[dim][bucket] = {
                "trades":   n,
                "win_rate": round(wins / n * 100, 1) if n else 0.0,
                "avg_pnl":  round(total / n, 2) if n else 0.0,
            }

    return result


# ── Failure pattern analysis ──────────────────────────────────────────────────

def find_failure_patterns(
    trades: list[dict],
    top_n: int = _DEFAULT_TOP_N,
) -> list[dict]:
    """
    Find the most common (direction, regime, score_bin) combinations in losers.

    Returns:
        Top-N dicts: {direction, regime, score_bin, count, avg_pnl, pct_of_losses}
        ordered by count descending.
    """
    losers = [t for t in trades if t["is_winner"] == 0]
    if not losers:
        return []

    combos: dict[tuple, list[float]] = {}
    for t in losers:
        key = (t["direction"], t["regime"], t["score_bin"])
        combos.setdefault(key, []).append(t["net_pnl"])

    total_losses = len(losers)
    patterns = []
    for (direction, regime, score_bin), pnls in sorted(
        combos.items(), key=lambda kv: len(kv[1]), reverse=True
    )[:top_n]:
        patterns.append({
            "direction":     direction,
            "regime":        regime,
            "score_bin":     score_bin,
            "count":         len(pnls),
            "avg_pnl":       round(sum(pnls) / len(pnls), 2),
            "pct_of_losses": round(len(pnls) / total_losses * 100, 1),
        })
    return patterns


# ── Edge decay (rolling win rate) ─────────────────────────────────────────────

def compute_edge_decay(
    trades: list[dict],
    window: int = _DEFAULT_WIN,
) -> list[dict]:
    """
    Compute a rolling win rate over chronologically-ordered trades.

    Args:
        trades : Trade list (assumed sorted by ts ascending).
        window : Rolling window size in trades.

    Returns:
        List of dicts: {trade_index, win_rate, trades_in_window, avg_pnl}
        One entry per window position.  Empty if fewer than window trades.
    """
    n = len(trades)
    if n < window:
        return []

    decay: list[dict] = []
    for i in range(window - 1, n):
        window_trades = trades[max(0, i - window + 1) : i + 1]
        wins  = sum(t["is_winner"] for t in window_trades)
        pnls  = [t["net_pnl"] for t in window_trades]
        decay.append({
            "trade_index":      i,
            "win_rate":         round(wins / len(window_trades) * 100, 1),
            "trades_in_window": len(window_trades),
            "avg_pnl":          round(sum(pnls) / len(pnls), 2),
        })
    return decay


# ── Insight generator ─────────────────────────────────────────────────────────

def _generate_insights(
    report: AutopsyReport,
    trades: list[dict],
) -> list[str]:
    """Derive up to 5 actionable insights from autopsy data."""
    insights: list[str] = []

    # 1. Best score bin
    breakdown = report.feature_breakdown.get("score_bin", {})
    if breakdown:
        best_bin = max(breakdown.items(), key=lambda kv: kv[1]["win_rate"])
        if best_bin[1]["win_rate"] >= 60:
            insights.append(
                f"Score bin '{best_bin[0]}' shows the highest win rate "
                f"({best_bin[1]['win_rate']:.1f}% over {best_bin[1]['trades']} trades)."
            )

    # 2. Worst regime
    reg_break = report.feature_breakdown.get("regime", {})
    if reg_break:
        worst_reg = min(reg_break.items(), key=lambda kv: kv[1]["win_rate"])
        if worst_reg[1]["win_rate"] < 40 and worst_reg[1]["trades"] >= 3:
            insights.append(
                f"Regime '{worst_reg[0]}' has low win rate "
                f"({worst_reg[1]['win_rate']:.1f}%) — consider reducing exposure."
            )

    # 3. Top failure pattern
    if report.failure_patterns:
        fp = report.failure_patterns[0]
        insights.append(
            f"Top failure pattern: {fp['direction']} in {fp['regime']} "
            f"at score {fp['score_bin']} — {fp['count']} losses "
            f"({fp['pct_of_losses']:.1f}% of all losses)."
        )

    # 4. Edge decay warning
    if report.edge_decay:
        recent_wr = report.edge_decay[-1]["win_rate"]
        overall_wr = report.overall_win_rate
        if recent_wr < overall_wr - 10:
            insights.append(
                f"Edge decay detected: recent win rate {recent_wr:.1f}% vs "
                f"overall {overall_wr:.1f}%. Consider model retraining."
            )

    # 5. Direction asymmetry
    dir_break = report.feature_breakdown.get("direction", {})
    call_d = dir_break.get("CALL", {})
    put_d  = dir_break.get("PUT", {})
    if call_d and put_d and call_d.get("trades", 0) >= 3 and put_d.get("trades", 0) >= 3:
        gap = abs(call_d["win_rate"] - put_d["win_rate"])
        if gap >= 15:
            better = "CALL" if call_d["win_rate"] > put_d["win_rate"] else "PUT"
            insights.append(
                f"Direction asymmetry: {better} trades outperform by {gap:.1f}pp."
            )

    return insights


# ── Main entry point ──────────────────────────────────────────────────────────

def run_autopsy(
    db_path: str = _DEFAULT_DB,
    *,
    days:   int   = _DEFAULT_DAYS,
    mode:   str | None = None,
    window: int   = _DEFAULT_WIN,
    top_n:  int   = _DEFAULT_TOP_N,
    cfg:    dict[str, Any] | None = None,
) -> AutopsyReport:
    """
    Run the full signal autopsy pipeline and return an AutopsyReport.

    Args:
        db_path : Path to trades.db.
        days    : Look-back window in days.
        mode    : Trade mode filter — "PAPER", "LIVE", or None/ALL.
        window  : Rolling window size for edge decay.
        top_n   : Number of top failure patterns to surface.
        cfg     : Config dict (overrides individual params if set).

    Returns:
        AutopsyReport — always returns even if there are no trades.
    """
    c      = cfg or {}
    db_path = str(c.get("trades_db", db_path))
    days    = int(c.get("signal_autopsy_days",  days))
    window  = int(c.get("signal_autopsy_window", window))
    top_n   = int(c.get("signal_autopsy_top_n",  top_n))

    trades = load_autopsy_data(db_path, days=days, mode=mode)
    n      = len(trades)

    if n == 0:
        return AutopsyReport(
            n_trades=0, n_winners=0, n_losers=0, overall_win_rate=0.0,
            insights=["No trades found in the specified window."],
        )

    winners = sum(t["is_winner"] for t in trades)
    losers  = n - winners
    wr      = round(winners / n * 100, 1)

    breakdown  = compute_feature_breakdown(trades)
    patterns   = find_failure_patterns(trades, top_n=top_n)
    decay      = compute_edge_decay(trades, window=window)
    min_cell   = int(c.get("heatmap_min_cell_trades", 3))
    time_hmap  = compute_time_heatmap(trades, min_cell_trades=min_cell)

    report = AutopsyReport(
        n_trades=n, n_winners=winners, n_losers=losers,
        overall_win_rate=wr,
        feature_breakdown=breakdown,
        failure_patterns=patterns,
        edge_decay=decay,
        time_heatmap=time_hmap,
    )
    report.insights = _generate_insights(report, trades)
    return report


# ── Formatter ─────────────────────────────────────────────────────────────────

def format_autopsy_report(report: AutopsyReport) -> str:
    """Return a compact multi-line autopsy summary."""
    lines = [
        f"Signal Autopsy — {report.n_trades} trades  "
        f"Win: {report.n_winners}  Loss: {report.n_losers}  "
        f"Win Rate: {report.overall_win_rate:.1f}%"
    ]

    # Score bin breakdown
    sb = report.feature_breakdown.get("score_bin", {})
    if sb:
        lines.append("\n  Score Bin Breakdown:")
        for bucket, m in sorted(sb.items()):
            lines.append(
                f"    {bucket:8s}  {m['trades']:3d} trades  "
                f"{m['win_rate']:5.1f}%  avg ₹{m['avg_pnl']:+,.0f}"
            )

    # Top failure patterns
    if report.failure_patterns:
        lines.append("\n  Top Failure Patterns:")
        for fp in report.failure_patterns:
            lines.append(
                f"    {fp['direction']:4s} | {fp['regime']:12s} | "
                f"score {fp['score_bin']:5s} → {fp['count']} losses "
                f"({fp['pct_of_losses']:.1f}%)"
            )

    # Edge decay
    if report.edge_decay:
        latest_wr = report.edge_decay[-1]["win_rate"]
        lines.append(f"\n  Recent Win Rate (last {report.edge_decay[-1]['trades_in_window']} trades): {latest_wr:.1f}%")

    # Insights
    if report.insights:
        lines.append("\n  Insights:")
        for ins in report.insights:
            lines.append(f"    • {ins}")

    return "\n".join(lines)


# ── Heatmap compute + render (v2.44 Item 16) ──────────────────────────────────

def compute_time_heatmap(
    trades: list[dict],
    min_cell_trades: int = 3,
) -> TimeHeatmap:
    """
    Build a win-rate heatmap by (hour_of_day, day_of_week).

    Cells with fewer than `min_cell_trades` are included but flagged by having
    n_trades < min_cell_trades (callers should render them differently).

    Args:
        trades          : Trade list (each must have "ts" key in ISO format).
        min_cell_trades : Minimum trades per cell for reliable win-rate estimate.

    Returns:
        TimeHeatmap with all observed (hour, day) cells.
    """
    import datetime as _dt

    buckets: dict[tuple[int, int], list[dict]] = {}
    for t in trades:
        ts_str = str(t.get("ts") or "")
        try:
            ts = _dt.datetime.fromisoformat(ts_str)
        except ValueError:
            continue
        key = (ts.hour, ts.weekday())
        buckets.setdefault(key, []).append(t)

    cells: list[HeatmapCell] = []
    for (hour, dow), items in sorted(buckets.items()):
        n    = len(items)
        wins = sum(t["is_winner"] for t in items)
        wr   = wins / n if n > 0 else 0.0
        apnl = sum(t["net_pnl"] for t in items) / n if n > 0 else 0.0
        cells.append(HeatmapCell(
            hour=hour,
            day_of_week=dow,
            n_trades=n,
            n_wins=wins,
            win_rate=round(wr, 4),
            avg_pnl=round(apnl, 2),
        ))

    hours = sorted({c.hour for c in cells})
    days  = sorted({c.day_of_week for c in cells})
    return TimeHeatmap(cells=cells, hours=hours, days=days, min_cell_trades=min_cell_trades)


def render_ascii_heatmap(heatmap: TimeHeatmap) -> str:
    """
    Render the TimeHeatmap as an ASCII table.

    Columns = hours, rows = days.  Each cell shows win_rate% or '--' if sparse.

    Returns:
        Multi-line string.
    """
    if not heatmap.cells:
        return "  (no heatmap data)"

    # Build lookup: (hour, dow) → HeatmapCell
    lkp: dict[tuple[int, int], HeatmapCell] = {
        (c.hour, c.day_of_week): c for c in heatmap.cells
    }

    header = "Day\\Hour  " + "".join(f"{h:>7}" for h in heatmap.hours)
    lines  = ["  " + header, "  " + "-" * len(header)]

    for dow in heatmap.days:
        day_label = _DAYS_MAP.get(dow, str(dow))
        row = f"{day_label:<8} "
        for h in heatmap.hours:
            cell = lkp.get((h, dow))
            if cell is None:
                row += "       "
            elif cell.n_trades < heatmap.min_cell_trades:
                row += "    -- "
            else:
                pct = cell.win_rate * 100
                row += f"  {pct:>4.0f}% "
        lines.append("  " + row)

    lines.append("")
    lines.append("  Values: win% per cell (-- = sparse, blank = no trades)")
    return "\n".join(lines)
