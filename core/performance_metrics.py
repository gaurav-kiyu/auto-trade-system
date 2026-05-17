"""
Performance analytics for the OPB index options trading system.

Primary data source: trades.db (written by index_trader.py on every exit)
Optional rich source: trade_journal.db (written by TradeJournal — includes
    slippage, execution delay, quality scores — may be empty at first).

Usage (standalone):
    python -m core.performance_metrics
    python -m core.performance_metrics --days 30 --mode LIVE
    python -m core.performance_metrics --export trade_log.jsonl

Public API:
    load_trades(db_path, mode, days)  -> list[dict]
    compute_metrics(trades)           -> dict
    metrics_by_regime(trades)         -> dict
    metrics_by_score_bin(trades)      -> dict
    metrics_by_exit_reason(trades)    -> dict
    compute_drawdown(trades)          -> dict
    generate_insights(trades)         -> list[str]
    print_report(db_path, mode, days) -> None
    export_jsonl(trades, path)        -> None
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
from datetime import timedelta
from core.datetime_ist import now_ist
from pathlib import Path
from typing import Any

log = logging.getLogger("performance_metrics")

_COLS = [
    "id", "ts", "index_name", "direction", "entry", "exit_price", "qty",
    "gross_pnl", "net_pnl", "reason", "regime", "score", "iv", "vix",
    "ltp_estimated", "partial", "sl_warned", "mode", "version",
]

_DEFAULT_DB = "trades.db"


# ── Data loading ─────────────────────────────────────────────────────────────

def load_trades(
    db_path: str = _DEFAULT_DB,
    mode: str | None = None,
    days: int | None = None,
) -> list[dict]:
    """Load trades from trades.db.  Returns [] if DB missing or empty."""
    path = Path(db_path)
    if not path.exists():
        log.warning("trades.db not found at %s", path)
        return []
    try:
        with sqlite3.connect(str(path)) as conn:
            conn.row_factory = sqlite3.Row
            clauses, params = [], []
            if mode:
                clauses.append("mode = ?")
                params.append(mode.upper())
            if days:
                since = (now_ist() - timedelta(days=days)).isoformat()
                clauses.append("ts >= ?")
                params.append(since)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = conn.execute(
                f"SELECT * FROM trades {where} ORDER BY ts", params
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        log.error("load_trades error: %s", exc)
        return []


# ── Core metrics ─────────────────────────────────────────────────────────────

def compute_metrics(trades: list[dict]) -> dict[str, Any]:
    """Compute aggregate performance metrics from a list of trade dicts."""
    if not trades:
        return {"trades": 0, "note": "no trades yet"}

    net_pnls = [float(t.get("net_pnl") or 0) for t in trades]
    gross_pnls = [float(t.get("gross_pnl") or 0) for t in trades]

    winners = [p for p in net_pnls if p >= 0]
    losers  = [p for p in net_pnls if p < 0]
    n       = len(trades)
    n_win   = len(winners)
    n_loss  = len(losers)

    win_rate  = n_win / n if n else 0.0
    avg_win   = sum(winners) / n_win  if n_win  else 0.0
    avg_loss  = sum(losers)  / n_loss if n_loss else 0.0

    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    gross_wins   = sum(p for p in gross_pnls if p > 0)
    gross_losses = abs(sum(p for p in gross_pnls if p < 0))
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else float("inf")

    total_net = sum(net_pnls)

    # Risk-adjusted: mean / std of net PnL per trade
    if n > 1:
        mean_pnl = total_net / n
        var = sum((p - mean_pnl) ** 2 for p in net_pnls) / (n - 1)
        std_pnl = math.sqrt(var) if var > 0 else 0.0
        sharpe_trade = mean_pnl / std_pnl if std_pnl > 0 else 0.0
    else:
        std_pnl = 0.0
        sharpe_trade = 0.0

    largest_win  = max(net_pnls)
    largest_loss = min(net_pnls)

    # Consecutive stats
    max_consec_wins = _max_consecutive(net_pnls, positive=True)
    max_consec_loss = _max_consecutive(net_pnls, positive=False)

    dd = compute_drawdown(trades)

    return {
        "trades":         n,
        "winners":        n_win,
        "losers":         n_loss,
        "win_rate":       round(win_rate * 100, 1),
        "avg_win":        round(avg_win, 2),
        "avg_loss":       round(avg_loss, 2),
        "win_loss_ratio": round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else float("inf"),
        "expectancy":     round(expectancy, 2),
        "profit_factor":  round(profit_factor, 2) if profit_factor != float("inf") else "inf",
        "total_net_pnl":  round(total_net, 2),
        "total_gross_pnl": round(sum(gross_pnls), 2),
        "largest_win":    round(largest_win, 2),
        "largest_loss":   round(largest_loss, 2),
        "std_pnl":        round(std_pnl, 2),
        "sharpe_per_trade": round(sharpe_trade, 3),
        "max_consec_wins":  max_consec_wins,
        "max_consec_losses": max_consec_loss,
        **dd,
    }


def compute_drawdown(trades: list[dict]) -> dict[str, float]:
    """Max drawdown and current drawdown from trade list (sorted by ts)."""
    if not trades:
        return {"max_drawdown": 0.0, "current_drawdown": 0.0, "recovery_factor": 0.0}

    equity, peak = 0.0, 0.0
    max_dd = 0.0
    for t in trades:
        equity += float(t.get("net_pnl") or 0)
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    current_dd = peak - equity
    total_net  = equity
    recovery   = round(total_net / max_dd, 2) if max_dd > 0 else float("inf")

    return {
        "max_drawdown":    round(max_dd, 2),
        "current_drawdown": round(current_dd, 2),
        "recovery_factor": recovery if recovery != float("inf") else "inf",
    }


# ── Breakdowns ───────────────────────────────────────────────────────────────

def metrics_by_regime(trades: list[dict]) -> dict[str, dict]:
    """Win rate, avg PnL, total PnL per market regime."""
    buckets: dict[str, list[dict]] = {}
    for t in trades:
        reg = str(t.get("regime") or "UNKNOWN").upper()
        buckets.setdefault(reg, []).append(t)

    result = {}
    for reg, group in sorted(buckets.items()):
        pnls   = [float(t.get("net_pnl") or 0) for t in group]
        wins   = sum(1 for p in pnls if p >= 0)
        result[reg] = {
            "trades":    len(group),
            "win_rate":  round(wins / len(group) * 100, 1),
            "avg_pnl":   round(sum(pnls) / len(group), 2),
            "total_pnl": round(sum(pnls), 2),
        }
    return result


def metrics_by_score_bin(trades: list[dict]) -> dict[str, dict]:
    """Win rate and avg PnL per signal score bucket."""
    bins = {
        "60-64": [],
        "65-69": [],
        "70-79": [],
        "80-89": [],
        "90+":   [],
        "below_60": [],
    }
    for t in trades:
        s = int(t.get("score") or 0)
        if s >= 90:
            bins["90+"].append(t)
        elif s >= 80:
            bins["80-89"].append(t)
        elif s >= 70:
            bins["70-79"].append(t)
        elif s >= 65:
            bins["65-69"].append(t)
        elif s >= 60:
            bins["60-64"].append(t)
        else:
            bins["below_60"].append(t)

    result = {}
    for label, group in bins.items():
        if not group:
            continue
        pnls = [float(t.get("net_pnl") or 0) for t in group]
        wins = sum(1 for p in pnls if p >= 0)
        result[label] = {
            "trades":    len(group),
            "win_rate":  round(wins / len(group) * 100, 1),
            "avg_pnl":   round(sum(pnls) / len(group), 2),
            "total_pnl": round(sum(pnls), 2),
        }
    return result


def metrics_by_exit_reason(trades: list[dict]) -> dict[str, dict]:
    """Win rate and trade count per exit reason."""
    buckets: dict[str, list[dict]] = {}
    for t in trades:
        reason = str(t.get("reason") or "UNKNOWN").upper()
        buckets.setdefault(reason, []).append(t)

    result = {}
    for reason, group in sorted(buckets.items(), key=lambda x: -len(x[1])):
        pnls = [float(t.get("net_pnl") or 0) for t in group]
        wins = sum(1 for p in pnls if p >= 0)
        result[reason] = {
            "trades":    len(group),
            "win_rate":  round(wins / len(group) * 100, 1),
            "avg_pnl":   round(sum(pnls) / len(group), 2),
            "pct_of_total": round(len(group) / len(trades) * 100, 1),
        }
    return result


def metrics_by_direction(trades: list[dict]) -> dict[str, dict]:
    """Win rate breakdown: CALL vs PUT."""
    buckets: dict[str, list[dict]] = {}
    for t in trades:
        d = str(t.get("direction") or "UNKNOWN").upper()
        buckets.setdefault(d, []).append(t)

    result = {}
    for d, group in sorted(buckets.items()):
        pnls = [float(t.get("net_pnl") or 0) for t in group]
        wins = sum(1 for p in pnls if p >= 0)
        result[d] = {
            "trades":    len(group),
            "win_rate":  round(wins / len(group) * 100, 1),
            "avg_pnl":   round(sum(pnls) / len(group), 2),
            "total_pnl": round(sum(pnls), 2),
        }
    return result


def metrics_by_index(trades: list[dict]) -> dict[str, dict]:
    """Per-instrument breakdown."""
    buckets: dict[str, list[dict]] = {}
    for t in trades:
        name = str(t.get("index_name") or "UNKNOWN").upper()
        buckets.setdefault(name, []).append(t)

    result = {}
    for name, group in sorted(buckets.items()):
        pnls = [float(t.get("net_pnl") or 0) for t in group]
        wins = sum(1 for p in pnls if p >= 0)
        result[name] = {
            "trades":    len(group),
            "win_rate":  round(wins / len(group) * 100, 1),
            "avg_pnl":   round(sum(pnls) / len(group), 2),
            "total_pnl": round(sum(pnls), 2),
        }
    return result


# ── Insight generator ─────────────────────────────────────────────────────────

def generate_insights(trades: list[dict]) -> list[str]:
    """
    Return a list of human-readable, actionable insight strings.
    Designed to be logged or sent via Telegram summary.
    """
    if not trades:
        return ["No trades yet — insights will appear after the first trade exits."]

    insights: list[str] = []
    m   = compute_metrics(trades)
    wr  = m["win_rate"]
    exp = m["expectancy"]
    pf  = m["profit_factor"]
    n   = m["trades"]

    # ── Overall health
    if exp > 0:
        insights.append(f"System is PROFITABLE: expectancy ₹{exp:+.0f}/trade over {n} trades.")
    elif n < 20:
        insights.append(f"Only {n} trades — too few for statistical conclusions (need 20+).")
    else:
        insights.append(f"System is UNPROFITABLE: expectancy ₹{exp:+.0f}/trade — review entry filters.")

    if pf != "inf" and pf < 1.0:
        insights.append(f"Profit factor {pf} < 1.0 — gross losses exceed gross wins.")
    elif pf != "inf" and pf >= 1.5:
        insights.append(f"Profit factor {pf:.2f} is healthy (>1.5).")

    wl = m["win_loss_ratio"]
    if wr < 40 and wl < 2.0:
        insights.append(
            f"Win rate {wr}% AND win/loss ratio {wl:.1f}x are both low — "
            "raise entry score threshold or widen TP."
        )
    elif wr < 40 and wl >= 2.5:
        insights.append(
            f"Low win rate ({wr}%) offset by large wins ({wl:.1f}x avg loss) — "
            "system depends on few big winners; consider improving filter to boost consistency."
        )

    # ── Drawdown check
    max_dd = m.get("max_drawdown", 0)
    if max_dd > 0 and m["total_net_pnl"] > 0:
        dd_pct = round(max_dd / (m["total_net_pnl"] + max_dd) * 100, 1)
        if dd_pct > 30:
            insights.append(
                f"Max drawdown ₹{max_dd:.0f} ({dd_pct}% of peak equity) — "
                "consider tighter daily loss limits."
            )

    # ── Score bin analysis
    by_score = metrics_by_score_bin(trades)
    best_bin = max(by_score.items(), key=lambda x: x[1]["win_rate"], default=None)
    worst_bin = min(by_score.items(), key=lambda x: x[1]["win_rate"], default=None)
    overall_wr = wr
    if best_bin and best_bin[1]["trades"] >= 3:
        bwr = best_bin[1]["win_rate"]
        if bwr > overall_wr + 10:
            insights.append(
                f"Score bin {best_bin[0]} has highest win rate {bwr}% "
                f"(+{bwr-overall_wr:.0f}% vs overall) — score threshold well calibrated."
            )
    if worst_bin and worst_bin[1]["trades"] >= 3:
        wbwr = worst_bin[1]["win_rate"]
        if wbwr < overall_wr - 10 and worst_bin[0] != "below_60":
            insights.append(
                f"Score bin {worst_bin[0]} has low win rate {wbwr}% "
                f"({overall_wr-wbwr:.0f}% below overall) — "
                "these entries drag performance; raise threshold."
            )

    # ── Regime analysis
    by_regime = metrics_by_regime(trades)
    if len(by_regime) > 1:
        best_r  = max(by_regime.items(), key=lambda x: x[1]["avg_pnl"] if x[1]["trades"] >= 3 else -999)
        worst_r = min(by_regime.items(), key=lambda x: x[1]["avg_pnl"] if x[1]["trades"] >= 3 else 999)
        if best_r[1]["trades"] >= 3 and worst_r[1]["trades"] >= 3:
            insights.append(
                f"Best regime: {best_r[0]} (avg ₹{best_r[1]['avg_pnl']:+.0f}, "
                f"WR {best_r[1]['win_rate']}%) | "
                f"Worst: {worst_r[0]} (avg ₹{worst_r[1]['avg_pnl']:+.0f}, "
                f"WR {worst_r[1]['win_rate']}%)."
            )
        # Warn on unprofitable regimes with meaningful sample
        for reg, rm in by_regime.items():
            if rm["trades"] >= 5 and rm["total_pnl"] < 0:
                insights.append(
                    f"Regime {reg}: {rm['trades']} trades, total ₹{rm['total_pnl']:.0f} "
                    "— consider disabling entries in this regime."
                )

    # ── Exit reason analysis
    by_exit = metrics_by_exit_reason(trades)
    sl_data = by_exit.get("STOP_LOSS") or by_exit.get("SL") or {}
    tp_data = by_exit.get("TAKE_PROFIT") or by_exit.get("TP") or {}
    if sl_data:
        sl_pct = sl_data.get("pct_of_total", 0)
        if sl_pct > 60:
            insights.append(
                f"{sl_pct:.0f}% of trades exit at stop loss — "
                "consider tighter entry filters or wider initial SL."
            )
    if tp_data and sl_data:
        tp_wr = tp_data.get("win_rate", 0)
        insights.append(
            f"TP exit rate: {tp_data.get('pct_of_total',0):.0f}% "
            f"(WR {tp_wr}%) | SL rate: {sl_data.get('pct_of_total',0):.0f}%."
        )

    # ── Direction skew
    by_dir = metrics_by_direction(trades)
    if "CALL" in by_dir and "PUT" in by_dir:
        call_wr = by_dir["CALL"]["win_rate"]
        put_wr  = by_dir["PUT"]["win_rate"]
        diff    = abs(call_wr - put_wr)
        if diff >= 15 and by_dir["CALL"]["trades"] >= 5 and by_dir["PUT"]["trades"] >= 5:
            better  = "CALL" if call_wr > put_wr else "PUT"
            worse   = "PUT"  if better == "CALL" else "CALL"
            insights.append(
                f"{better} trades significantly outperform {worse} "
                f"({by_dir[better]['win_rate']}% vs {by_dir[worse]['win_rate']}% WR) — "
                "review PUT/CALL asymmetry in entry criteria."
            )

    # ── Consecutive losses warning
    max_cl = m.get("max_consec_losses", 0)
    if max_cl >= 5:
        insights.append(
            f"Max consecutive losses: {max_cl} — verify circuit breaker is active."
        )

    return insights


# ── JSONL export ──────────────────────────────────────────────────────────────

def export_jsonl(trades: list[dict], path: str) -> None:
    """Append-write trades to a JSONL file (one JSON object per line)."""
    p = Path(path)
    existing_ids: set = set()
    if p.exists():
        try:
            with p.open() as f:
                for line in f:
                    rec = json.loads(line)
                    existing_ids.add(rec.get("id"))
        except Exception:
            pass

    new_rows = [t for t in trades if t.get("id") not in existing_ids]
    if not new_rows:
        return
    with p.open("a", encoding="utf-8") as f:
        for row in new_rows:
            f.write(json.dumps(row, default=str) + "\n")
    log.info("Exported %d new trades to %s", len(new_rows), path)


# ── Report printer ────────────────────────────────────────────────────────────

def print_report(
    db_path: str = _DEFAULT_DB,
    mode: str | None = None,
    days: int | None = None,
) -> None:
    trades = load_trades(db_path, mode=mode, days=days)

    title_parts = []
    if mode:
        title_parts.append(f"mode={mode}")
    if days:
        title_parts.append(f"last {days}d")
    subtitle = f" ({', '.join(title_parts)})" if title_parts else ""

    print(f"\n{'=' * 62}")
    print(f"  OPB PERFORMANCE REPORT{subtitle}")
    print(f"{'=' * 62}")

    if not trades:
        print("  No trades found. Run the system to generate data.")
        print(f"{'=' * 62}\n")
        return

    m = compute_metrics(trades)

    print(f"\n  OVERALL  ({m['trades']} trades)")
    print(f"  Win Rate      : {m['win_rate']}%  ({m['winners']}W / {m['losers']}L)")
    print(f"  Expectancy    : {m['expectancy']:+.2f} / trade")
    print(f"  Profit Factor : {m['profit_factor']}")
    print(f"  Total Net PnL : {m['total_net_pnl']:+.2f}")
    print(f"  Avg Win       : {m['avg_win']:+.2f}  |  Avg Loss: {m['avg_loss']:+.2f}")
    print(f"  Win/Loss Ratio: {m['win_loss_ratio']}x")
    print(f"  Largest Win   : {m['largest_win']:+.2f}  |  Largest Loss: {m['largest_loss']:+.2f}")
    print(f"  Max Drawdown  : {m['max_drawdown']:.2f}  |  Recovery Factor: {m['recovery_factor']}")
    print(f"  Sharpe/Trade  : {m['sharpe_per_trade']:.3f}")
    print(f"  Max Consec W/L: {m['max_consec_wins']}W / {m['max_consec_losses']}L")

    # ── By Regime
    by_regime = metrics_by_regime(trades)
    if by_regime:
        print("\n  BY REGIME")
        print(f"  {'Regime':<18} {'Trades':>6} {'WR%':>6} {'AvgPnL':>9} {'TotalPnL':>10}")
        print(f"  {'-'*53}")
        for reg, rm in sorted(by_regime.items()):
            print(f"  {reg:<18} {rm['trades']:>6} {rm['win_rate']:>6.1f} "
                  f"{rm['avg_pnl']:>+9.2f} {rm['total_pnl']:>+10.2f}")

    # ── By Score Bin
    by_score = metrics_by_score_bin(trades)
    if by_score:
        print("\n  BY SCORE BIN")
        print(f"  {'Bin':<10} {'Trades':>6} {'WR%':>6} {'AvgPnL':>9} {'TotalPnL':>10}")
        print(f"  {'-'*45}")
        for label in ["below_60", "60-64", "65-69", "70-79", "80-89", "90+"]:
            bm = by_score.get(label)
            if not bm:
                continue
            print(f"  {label:<10} {bm['trades']:>6} {bm['win_rate']:>6.1f} "
                  f"{bm['avg_pnl']:>+9.2f} {bm['total_pnl']:>+10.2f}")

    # ── By Exit Reason
    by_exit = metrics_by_exit_reason(trades)
    if by_exit:
        print("\n  BY EXIT REASON")
        print(f"  {'Reason':<22} {'Trades':>6} {'WR%':>6} {'AvgPnL':>9} {'%Total':>7}")
        print(f"  {'-'*54}")
        for reason, rm in by_exit.items():
            print(f"  {reason:<22} {rm['trades']:>6} {rm['win_rate']:>6.1f} "
                  f"{rm['avg_pnl']:>+9.2f} {rm['pct_of_total']:>6.1f}%")

    # ── By Direction
    by_dir = metrics_by_direction(trades)
    if by_dir:
        print("\n  BY DIRECTION")
        print(f"  {'Direction':<10} {'Trades':>6} {'WR%':>6} {'AvgPnL':>9} {'TotalPnL':>10}")
        print(f"  {'-'*45}")
        for d, dm in sorted(by_dir.items()):
            print(f"  {d:<10} {dm['trades']:>6} {dm['win_rate']:>6.1f} "
                  f"{dm['avg_pnl']:>+9.2f} {dm['total_pnl']:>+10.2f}")

    # ── By Instrument
    by_idx = metrics_by_index(trades)
    if by_idx:
        print("\n  BY INSTRUMENT")
        print(f"  {'Index':<14} {'Trades':>6} {'WR%':>6} {'AvgPnL':>9} {'TotalPnL':>10}")
        print(f"  {'-'*49}")
        for idx, im in sorted(by_idx.items()):
            print(f"  {idx:<14} {im['trades']:>6} {im['win_rate']:>6.1f} "
                  f"{im['avg_pnl']:>+9.2f} {im['total_pnl']:>+10.2f}")

    # ── Insights
    insights = generate_insights(trades)
    if insights:
        print("\n  INSIGHTS")
        for i, txt in enumerate(insights, 1):
            print(f"  {i}. {txt}")

    print(f"\n{'=' * 62}\n")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _max_consecutive(values: list[float], *, positive: bool) -> int:
    max_run = cur_run = 0
    for v in values:
        hit = (v >= 0) if positive else (v < 0)
        if hit:
            cur_run += 1
            max_run = max(max_run, cur_run)
        else:
            cur_run = 0
    return max_run


# ── Periodic summary (call from scheduler / index_trader) ────────────────────

def periodic_summary(db_path: str = _DEFAULT_DB, mode: str = "PAPER") -> str:
    """Return a compact one-paragraph summary suitable for Telegram."""
    trades = load_trades(db_path, mode=mode)
    if not trades:
        return "No trades recorded yet."

    m = compute_metrics(trades)
    ins = generate_insights(trades)
    top_insight = ins[0] if ins else ""

    lines = [
        f"Trades: {m['trades']}  WR: {m['win_rate']}%  "
        f"Exp: {m['expectancy']:+.0f}  PF: {m['profit_factor']}",
        f"Net PnL: {m['total_net_pnl']:+.0f}  MaxDD: {m['max_drawdown']:.0f}",
    ]
    if top_insight:
        lines.append(top_insight)
    return "\n".join(lines)


# ── CLI entry point ───────────────────────────────────────────────────────────

def _cli() -> None:
    parser = argparse.ArgumentParser(description="OPB Performance Report")
    parser.add_argument("--db",     default=_DEFAULT_DB, help="Path to trades.db")
    parser.add_argument("--mode",   default=None,        help="Filter by mode (PAPER / LIVE)")
    parser.add_argument("--days",   type=int, default=None, help="Last N days only")
    parser.add_argument("--export", default=None,        help="Export to JSONL path")
    args = parser.parse_args()

    print_report(args.db, mode=args.mode, days=args.days)

    if args.export:
        trades = load_trades(args.db, mode=args.mode, days=args.days)
        export_jsonl(trades, args.export)
        print(f"Exported {len(trades)} trades to {args.export}")


if __name__ == "__main__":
    _cli()
