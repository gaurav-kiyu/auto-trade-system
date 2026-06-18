"""
Live Performance Analysis - DATA + DISCIPLINE + REVIEW

Reads from trade_journal.db and produces a structured performance report.

Entry points:
    analyze_live_performance(db_path, mode) -> dict    - machine-readable
    print_live_performance(db_path, mode)              - human-readable console report
    main()                                             - CLI: python -m core.live_analysis

Design principles:
    - DATA: all insights come from the journal, not assumptions
    - DISCIPLINE: flag when rules were violated (quality filter bypassed, etc.)
    - REVIEW: continuous improvement loop - identify what to avoid, what to do more of
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from core.db_utils import get_connection

_log = logging.getLogger(__name__)


# ── SQL helpers ────────────────────────────────────────────────────────────────

def _connect(db_path: str) -> sqlite3.Connection:
    conn = get_connection(db_path)
    return conn


def _rows(db_path: str, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    try:
        with _connect(db_path) as conn:
            return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        _log.warning("[LIVEANALYSIS DB] Query failed (%s) - returning empty: %s", db_path, exc)
        return []


def _one(db_path: str, sql: str, params: tuple = ()) -> sqlite3.Row | None:
    rows = _rows(db_path, sql, params)
    return rows[0] if rows else None


# ── Core analysis ──────────────────────────────────────────────────────────────

def analyze_live_performance(
    db_path: str = "trade_journal.db",
    mode: str = "LIVE",
) -> dict[str, Any]:
    """
    Full performance analysis from trade journal.

    Returns a structured dict with all metrics. The dict is the single source
    of truth for downstream reporting, dashboards, and decision-support.
    """
    db = str(Path(db_path))

    # ── Summary ────────────────────────────────────────────────────────────
    summary = _one(db, """
        SELECT
            COUNT(*)                                             AS trades,
            SUM(is_winner)                                       AS wins,
            ROUND(100.0 * SUM(is_winner) / COUNT(*), 1)         AS win_rate,
            ROUND(AVG(CASE WHEN is_winner=1 THEN net_pnl END), 2) AS avg_win,
            ROUND(AVG(CASE WHEN is_winner=0 THEN net_pnl END), 2) AS avg_loss,
            ROUND(SUM(net_pnl), 2)                               AS total_pnl,
            ROUND(AVG(net_pnl), 2)                               AS expectancy,
            ROUND(AVG(total_slippage), 3)                        AS avg_slippage,
            ROUND(AVG(execution_delay_ms), 0)                    AS avg_delay_ms,
            ROUND(AVG(rr_achieved), 3)                           AS avg_rr,
            ROUND(AVG(pnl_vs_expected), 2)                       AS avg_pnl_vs_model
        FROM journal
        WHERE mode = ? AND actual_exit > 0
    """, (mode,))

    if not summary or not summary["trades"]:
        return {"status": "no_data", "mode": mode, "db_path": db_path}

    n         = summary["trades"]
    wins      = summary["wins"] or 0
    losses    = n - wins
    wr        = (wins / n) if n else 0.0
    avg_win   = float(summary["avg_win"]  or 0)
    avg_loss  = abs(float(summary["avg_loss"] or 0))
    exp       = round(wr * avg_win - (1 - wr) * avg_loss, 2)
    pf        = round(wins * avg_win / max(losses * avg_loss, 0.01), 3) if losses else float("inf")

    # ── By tier ────────────────────────────────────────────────────────────
    tier_rows = _rows(db, """
        SELECT
            tier,
            COUNT(*)                                                AS trades,
            SUM(is_winner)                                          AS wins,
            ROUND(100.0 * SUM(is_winner) / COUNT(*), 1)            AS win_rate,
            ROUND(AVG(CASE WHEN is_winner=1 THEN net_pnl END), 2)  AS avg_win,
            ROUND(AVG(CASE WHEN is_winner=0 THEN net_pnl END), 2)  AS avg_loss,
            ROUND(AVG(net_pnl), 2)                                  AS expectancy,
            ROUND(AVG(total_slippage), 3)                           AS avg_slippage,
            ROUND(AVG(quality_score), 3)                            AS avg_quality,
            ROUND(AVG(quality_accurate), 3)                         AS quality_accuracy
        FROM journal
        WHERE mode = ? AND actual_exit > 0
        GROUP BY tier
        ORDER BY CASE tier WHEN 'STRONG' THEN 1 WHEN 'MODERATE' THEN 2 ELSE 3 END
    """, (mode,))

    by_tier: dict[str, Any] = {}
    for r in tier_rows:
        t_n   = r["trades"] or 0
        t_w   = r["wins"] or 0
        t_wr  = float(r["win_rate"] or 0)
        t_aw  = float(r["avg_win"] or 0)
        t_al  = abs(float(r["avg_loss"] or 0))
        t_exp = round((t_wr / 100) * t_aw - (1 - t_wr / 100) * t_al, 2)
        t_l   = t_n - t_w
        t_pf  = round(t_w * t_aw / max(t_l * t_al, 0.01), 3) if t_l else float("inf")
        by_tier[r["tier"]] = {
            "trades":           t_n,
            "wins":             t_w,
            "win_rate":         t_wr,
            "avg_win":          t_aw,
            "avg_loss":         float(r["avg_loss"] or 0),
            "expectancy":       t_exp,
            "profit_factor":    t_pf,
            "avg_slippage":     float(r["avg_slippage"] or 0),
            "avg_quality":      float(r["avg_quality"] or 0),
            "quality_accuracy": float(r["quality_accuracy"] or 0),
        }

    # ── By regime ──────────────────────────────────────────────────────────
    regime_rows = _rows(db, """
        SELECT
            regime,
            COUNT(*)                                                AS trades,
            SUM(is_winner)                                          AS wins,
            ROUND(100.0 * SUM(is_winner) / COUNT(*), 1)            AS win_rate,
            ROUND(AVG(net_pnl), 2)                                  AS expectancy,
            ROUND(SUM(net_pnl), 2)                                  AS total_pnl
        FROM journal
        WHERE mode = ? AND actual_exit > 0
        GROUP BY regime
        ORDER BY SUM(net_pnl) DESC
    """, (mode,))

    by_regime: dict[str, Any] = {}
    for r in regime_rows:
        by_regime[r["regime"]] = {
            "trades":     r["trades"],
            "wins":       r["wins"] or 0,
            "win_rate":   float(r["win_rate"] or 0),
            "expectancy": float(r["expectancy"] or 0),
            "total_pnl":  float(r["total_pnl"] or 0),
        }

    # ── Score vs outcome correlation ───────────────────────────────────────
    score_corr = _one(db, """
        SELECT
            ROUND(
                (COUNT(*) * SUM(score * is_winner) - SUM(score) * SUM(is_winner)) /
                (SQRT(COUNT(*) * SUM(score*score) - SUM(score)*SUM(score)) *
                 SQRT(COUNT(*) * SUM(is_winner*is_winner) - SUM(is_winner)*SUM(is_winner)) + 0.001),
            3) AS pearson_r,
            ROUND(AVG(CASE WHEN score >= 80 THEN is_winner*1.0 END) * 100, 1) AS wr_strong,
            ROUND(AVG(CASE WHEN score >= 70 AND score < 80 THEN is_winner*1.0 END) * 100, 1) AS wr_moderate,
            ROUND(AVG(CASE WHEN score >= 60 AND score < 70 THEN is_winner*1.0 END) * 100, 1) AS wr_weak
        FROM journal
        WHERE mode = ? AND actual_exit > 0
    """, (mode,))

    score_outcome = {
        "pearson_r":   float(score_corr["pearson_r"] or 0) if score_corr else 0.0,
        "wr_strong":   float(score_corr["wr_strong"] or 0) if score_corr else 0.0,
        "wr_moderate": float(score_corr["wr_moderate"] or 0) if score_corr else 0.0,
        "wr_weak":     float(score_corr["wr_weak"] or 0) if score_corr else 0.0,
    }

    # ── Best setups (high score + winner) ─────────────────────────────────
    best_rows = _rows(db, """
        SELECT trade_id, symbol, direction, entry_ts, score, tier, regime,
               net_pnl, pct_pnl, rr_achieved, exit_reason, quality_score
        FROM journal
        WHERE mode = ? AND is_winner = 1 AND actual_exit > 0
        ORDER BY net_pnl DESC
        LIMIT 5
    """, (mode,))
    best_setups = [dict(r) for r in best_rows]

    # ── Worst setups (biggest losers) ─────────────────────────────────────
    worst_rows = _rows(db, """
        SELECT trade_id, symbol, direction, entry_ts, score, tier, regime,
               net_pnl, pct_pnl, rr_achieved, exit_reason, quality_score,
               soft_blocks
        FROM journal
        WHERE mode = ? AND is_winner = 0 AND actual_exit > 0
        ORDER BY net_pnl ASC
        LIMIT 5
    """, (mode,))
    worst_setups = [dict(r) for r in worst_rows]

    # ── Slippage analysis ──────────────────────────────────────────────────
    slip_rows = _rows(db, """
        SELECT
            tier,
            ROUND(AVG(entry_slippage), 3)  AS avg_entry_slip,
            ROUND(AVG(exit_slippage), 3)   AS avg_exit_slip,
            ROUND(AVG(total_slippage), 3)  AS avg_total_slip,
            ROUND(MAX(total_slippage), 3)  AS max_total_slip,
            ROUND(AVG(execution_delay_ms)) AS avg_delay_ms
        FROM journal
        WHERE mode = ? AND actual_exit > 0
        GROUP BY tier
    """, (mode,))
    slippage = {r["tier"]: dict(r) for r in slip_rows}

    # ── Drawdown from equity curve ─────────────────────────────────────────
    pnl_rows = _rows(db, """
        SELECT net_pnl FROM journal
        WHERE mode = ? AND actual_exit > 0
        ORDER BY created_at ASC
    """, (mode,))
    pnl_series = [float(r["net_pnl"]) for r in pnl_rows]
    max_dd_pct = _calc_max_drawdown(pnl_series)

    # ── Decision support ───────────────────────────────────────────────────
    avoidance, priority = _generate_decisions(by_tier, by_regime, score_outcome)

    # ── Exit reason distribution ───────────────────────────────────────────
    exit_rows = _rows(db, """
        SELECT exit_reason, COUNT(*) AS cnt,
               ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM journal
                     WHERE mode = ? AND actual_exit > 0), 1) AS pct
        FROM journal WHERE mode = ? AND actual_exit > 0
        GROUP BY exit_reason ORDER BY cnt DESC
    """, (mode, mode))
    exit_reasons = {r["exit_reason"]: {"count": r["cnt"], "pct": float(r["pct"] or 0)}
                    for r in exit_rows}

    return {
        "status":       "ok",
        "mode":         mode,
        "db_path":      db_path,
        "summary": {
            "trades":          n,
            "wins":            wins,
            "losses":          losses,
            "win_rate":        round(wr * 100, 1),
            "avg_win":         avg_win,
            "avg_loss":        -avg_loss,
            "expectancy":      exp,
            "profit_factor":   pf,
            "total_pnl":       float(summary["total_pnl"] or 0),
            "avg_rr":          float(summary["avg_rr"] or 0),
            "max_drawdown_pct": max_dd_pct,
            "avg_slippage":    float(summary["avg_slippage"] or 0),
            "avg_delay_ms":    float(summary["avg_delay_ms"] or 0),
            "pnl_vs_model":    float(summary["avg_pnl_vs_model"] or 0),
        },
        "by_tier":      by_tier,
        "by_regime":    by_regime,
        "score_outcome": score_outcome,
        "slippage":     slippage,
        "exit_reasons": exit_reasons,
        "best_setups":  best_setups,
        "worst_setups": worst_setups,
        "decisions":    {"avoid": avoidance, "prioritize": priority},
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _calc_max_drawdown(pnl_series: list[float]) -> float:
    if len(pnl_series) < 2:
        return 0.0
    equity = 0.0
    peak   = 0.0
    max_dd = 0.0
    for pnl in pnl_series:
        equity += pnl
        peak    = max(peak, equity)
        dd      = (peak - equity) / max(abs(peak), 1e-9)
        max_dd  = max(max_dd, dd)
    return round(max_dd * 100, 2)


def _generate_decisions(
    by_tier: dict,
    by_regime: dict,
    score_outcome: dict,
) -> tuple[list[str], list[str]]:
    avoidance: list[str] = []
    priority: list[str]  = []

    # Tier-based
    for tier, stats in by_tier.items():
        wr  = stats.get("win_rate", 0)
        exp = stats.get("expectancy", 0)
        n   = stats.get("trades", 0)
        if n < 5:
            continue
        if exp < 0:
            avoidance.append(
                f"{tier} tier (n={n}): negative expectancy "
                f"Rs{exp:+.0f}/trade, WR={wr:.0f}% - reduce or disable"
            )
        elif exp > 0 and wr >= 55:
            priority.append(
                f"{tier} tier (n={n}): positive edge "
                f"Rs{exp:+.0f}/trade, WR={wr:.0f}% - prioritize"
            )

    # Regime-based
    for regime, stats in by_regime.items():
        wr  = stats.get("win_rate", 0)
        exp = stats.get("expectancy", 0)
        n   = stats.get("trades", 0)
        if n < 3:
            continue
        if exp < 0 and wr < 40:
            avoidance.append(
                f"{regime} regime (n={n}): WR={wr:.0f}%, "
                f"exp=Rs{exp:+.0f} - avoid or reduce to WEAK-skip"
            )
        elif exp > 0 and wr >= 55:
            priority.append(
                f"{regime} regime (n={n}): WR={wr:.0f}%, "
                f"exp=Rs{exp:+.0f} - increase allocation"
            )

    # Score correlation
    r = score_outcome.get("pearson_r", 0)
    if r < 0.10 and sum(
        v.get("trades", 0) for v in by_tier.values()
    ) >= 20:
        avoidance.append(
            f"Score-outcome correlation is low (r={r:.2f}): "
            f"raw score is not predicting winners - review scoring weights"
        )

    return avoidance, priority


# ── Console reporter ───────────────────────────────────────────────────────────

_W  = 70
_SEP  = "=" * _W
_SEP2 = "-" * _W
_LN   = "-" * 44


def _h(title: str) -> None:
    print(f"\n{_SEP2}")
    print(f"  {title}")
    print(_SEP2)


def _bar(wr: float, w: int = 24) -> str:
    n = int(round(wr / 100 * w))
    return "[" + "#" * n + " " * (w - n) + f"] {wr:.1f}%"


def print_live_performance(
    db_path: str = "trade_journal.db",
    mode: str = "LIVE",
) -> None:
    """
    Print a human-readable live performance report to stdout.
    """
    data = analyze_live_performance(db_path, mode)

    if data.get("status") == "no_data":
        print(f"\n[Live Analysis] No closed trades found in '{db_path}' (mode={mode})")
        print("  Start trading in LIVE mode to populate the journal.")
        return

    s = data["summary"]

    print()
    print(_SEP)
    print(f"  LIVE PERFORMANCE REVIEW  |  mode={mode}  |  trades={s['trades']}")
    print(_SEP)

    # ── Summary ────────────────────────────────────────────────────────────
    _h("OVERALL SUMMARY")
    print(f"  {'Trades':<30}: {s['trades']}  ({s['wins']}W / {s['losses']}L)")
    print(f"  {'Win rate':<30}: {_bar(s['win_rate'])}")
    print(f"  {'Profit factor':<30}: {s['profit_factor']:.3f}  (>1.5 = strong edge)")
    print(f"  {'Avg winner (Rs)':<30}: +Rs{s['avg_win']:,.2f}")
    print(f"  {'Avg loser  (Rs)':<30}: -Rs{abs(s['avg_loss']):,.2f}")
    print(f"  {'Net expectancy/trade':<30}: Rs{s['expectancy']:+,.2f}")
    print(f"  {'Total PnL':<30}: Rs{s['total_pnl']:+,.2f}")
    print(f"  {'Avg RR achieved':<30}: {s['avg_rr']:.3f}x")
    print(f"  {'Max drawdown':<30}: {s['max_drawdown_pct']:.1f}%")
    print(f"  {'Avg slippage/trade':<30}: Rs{s['avg_slippage']:+.3f}")
    print(f"  {'Avg execution delay':<30}: {s['avg_delay_ms']:.0f} ms")
    print(f"  {'PnL vs model (avg delta)':<30}: Rs{s['pnl_vs_model']:+.2f}/trade")

    # ── By tier ────────────────────────────────────────────────────────────
    _h("PERFORMANCE BY TIER  (DATA-DRIVEN ALLOCATION GUIDE)")
    print(f"  {'Tier':<10} {'N':>4} {'WR':>9} {'AvgWin':>9} {'AvgLoss':>9} "
          f"{'Exp/T':>9} {'PF':>7} {'Quality':>8}")
    print(f"  {_LN}")
    for tier in ("STRONG", "MODERATE", "WEAK"):
        t = data["by_tier"].get(tier)
        if not t:
            print(f"  {tier:<10} {'-':>4}  no trades")
            continue
        print(
            f"  {tier:<10} {t['trades']:>4} "
            f"{_bar(t['win_rate'], 18):>26}  "
            f"Rs{t['avg_win']:>+7,.0f}  Rs{t['avg_loss']:>+7,.0f}  "
            f"Rs{t['expectancy']:>+7,.0f}  {t['profit_factor']:>6.3f}  "
            f"{t['avg_quality']:.2f}"
        )

    # ── By regime ──────────────────────────────────────────────────────────
    _h("PERFORMANCE BY REGIME")
    print(f"  {'Regime':<16} {'N':>4} {'WR':>9} {'Exp/T':>9} {'Total PnL':>11}")
    print(f"  {_LN}")
    for regime, r in sorted(data["by_regime"].items(),
                             key=lambda x: -x[1].get("total_pnl", 0)):
        print(
            f"  {regime:<16} {r['trades']:>4} "
            f"{_bar(r['win_rate'], 18):>26}  "
            f"Rs{r['expectancy']:>+7,.0f}  Rs{r['total_pnl']:>+9,.0f}"
        )

    # ── Score vs outcome ───────────────────────────────────────────────────
    _h("SCORE vs OUTCOME CORRELATION")
    sc = data["score_outcome"]
    print(f"  Pearson r (score->winner)  : {sc['pearson_r']:+.3f}  "
          f"({'positive edge' if sc['pearson_r'] > 0.15 else 'weak' if sc['pearson_r'] > 0 else 'NEGATIVE - investigate'})")
    print("  Win rate by band:")
    print(f"    STRONG  (80+) : {sc['wr_strong']:.1f}%")
    print(f"    MODERATE(70-79): {sc['wr_moderate']:.1f}%")
    print(f"    WEAK    (60-69): {sc['wr_weak']:.1f}%")
    print()
    print("  Higher tier should have higher WR (validates score calibration).")
    if sc["wr_strong"] and sc["wr_weak"] and sc["wr_strong"] <= sc["wr_weak"]:
        print("  [!] STRONG win rate <= WEAK win rate - scoring may need recalibration.")

    # ── Slippage ───────────────────────────────────────────────────────────
    _h("SLIPPAGE ANALYSIS")
    print(f"  {'Tier':<10} {'Avg Entry':>10} {'Avg Exit':>10} {'Avg Total':>10} "
          f"{'Max Total':>10} {'Avg Delay':>10}")
    print(f"  {_LN}")
    for tier, sl in sorted(data["slippage"].items()):
        print(
            f"  {tier:<10} "
            f"Rs{float(sl.get('avg_entry_slip', 0)):>+8.2f}  "
            f"Rs{float(sl.get('avg_exit_slip', 0)):>+8.2f}  "
            f"Rs{float(sl.get('avg_total_slip', 0)):>+8.2f}  "
            f"Rs{float(sl.get('max_total_slip', 0)):>+8.2f}  "
            f"{float(sl.get('avg_delay_ms', 0)):>8.0f} ms"
        )

    # ── Exit reason distribution ───────────────────────────────────────────
    _h("EXIT REASON DISTRIBUTION")
    for reason, v in sorted(data["exit_reasons"].items(), key=lambda x: -x[1]["count"]):
        bar_w = int(v["pct"] / 100 * 24)
        print(f"  {reason:<18}: {'#'*bar_w}{'.'*(24-bar_w)} {v['count']:>4} ({v['pct']:.1f}%)")

    # ── Best / worst setups ────────────────────────────────────────────────
    _h("BEST SETUPS  (Top 5 by PnL)")
    for i, t in enumerate(data["best_setups"], 1):
        print(
            f"  {i}. [{t.get('tier','?'):<8}] score={t.get('score',0):>3}  "
            f"regime={t.get('regime','?'):<12}  "
            f"+Rs{abs(float(t.get('net_pnl', 0))):>7,.0f}  "
            f"exit={t.get('exit_reason','?')}"
        )

    _h("WORST SETUPS  (Bottom 5 by PnL)")
    for i, t in enumerate(data["worst_setups"], 1):
        sb = t.get("soft_blocks", "[]")
        print(
            f"  {i}. [{t.get('tier','?'):<8}] score={t.get('score',0):>3}  "
            f"regime={t.get('regime','?'):<12}  "
            f"-Rs{abs(float(t.get('net_pnl', 0))):>7,.0f}  "
            f"exit={t.get('exit_reason','?')}  soft={sb}"
        )

    # ── Decision support ───────────────────────────────────────────────────
    _h("DECISION SUPPORT  (DATA -> REVIEW -> ADJUST EXECUTION)")
    decisions = data["decisions"]
    if decisions["avoid"]:
        print("  AVOID / REDUCE:")
        for d in decisions["avoid"]:
            print(f"    - {d}")
    else:
        print("  AVOID: no clear patterns to avoid yet (need >=5 trades/tier)")

    print()
    if decisions["prioritize"]:
        print("  PRIORITIZE / INCREASE ALLOCATION:")
        for d in decisions["prioritize"]:
            print(f"    + {d}")
    else:
        print("  PRIORITIZE: no clear edge identified yet (need >=5 trades/tier)")

    print()
    print("  CONTINUOUS IMPROVEMENT:")
    print("  Use decisions above to adjust execution policy only.")
    print("  Do NOT change scoring logic or thresholds based on <20 trades.")
    print("  Re-run after every 10 new trades to update recommendations.")
    print()
    print(_SEP)


# ── CLI entry point ────────────────────────────────────────────────────────────

def main() -> None:
    """
    CLI: python -m core.live_analysis [--db path] [--mode LIVE|PAPER]
    """
    import argparse
    p = argparse.ArgumentParser(description="Live trade performance analysis")
    p.add_argument("--db",   default="trade_journal.db", help="Path to trade_journal.db")
    p.add_argument("--mode", default="LIVE", choices=["LIVE", "PAPER"], help="Trading mode")
    p.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = p.parse_args()

    if args.json:
        import json
        result = analyze_live_performance(args.db, args.mode)
        print(json.dumps(result, indent=2, default=str))
    else:
        print_live_performance(args.db, args.mode)


if __name__ == "__main__":
    main()
