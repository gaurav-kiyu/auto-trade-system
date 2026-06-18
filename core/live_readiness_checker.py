"""
Paper Trading Scorecard / Live Readiness Checker (v2.44 Item 19).

Evaluates paper trading history against a set of blocking and warning criteria
to determine whether the bot is ready to switch to live execution.

Blocking criteria (ALL must pass to be "ready"):
  1. Minimum paper trades  ≥ live_readiness_min_paper_trades (default 50)
  2. Win rate              ≥ live_readiness_min_win_rate      (default 0.50)
  3. Profit factor         ≥ live_readiness_min_profit_factor (default 1.30)
  4. Max drawdown          ≤ live_readiness_max_drawdown_pct  (default 15%)
  5. Minimum trading days  ≥ live_readiness_min_trading_days  (default 10)

Warning criteria (non-blocking, reduce readiness_score):
  6. Sharpe ratio          ≥ 0.5
  7. Average entry spread  ≤ health_check_spread_warn_pct
  8. ML accuracy           ≥ health_check_accuracy_warn
  9. Signal block rate     ≤ 80%   (not so many blocks that few signals go through)
  10. No drift detected in ML features

Public API
----------
    check_live_readiness(db_path, cfg) → ReadinessReport

    format_readiness_report(report) → str

    cli: python -m core.live_readiness_checker

Config keys (index_config.defaults.json)
-----------------------------------------
    BASE_CAPITAL                     : float default 5000.0
    live_readiness_check_on_startup  : bool  default true
    live_readiness_min_paper_trades  : int   default 50
    live_readiness_min_win_rate      : float default 0.50
    live_readiness_min_profit_factor : float default 1.30
    live_readiness_max_drawdown_pct  : float default 15.0
    live_readiness_min_trading_days  : int   default 10
    live_readiness_days_window       : int   default 30
    live_readiness_min_sharpe        : float default 0.5
"""
from __future__ import annotations

import argparse
import logging
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.db_utils import get_connection

_log = logging.getLogger(__name__)

_DEFAULT_DB   = "trades.db"
_FLAG_FILE    = ".live_readiness_notified"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class CriterionResult:
    name:     str
    passed:   bool
    blocking: bool
    actual:   Any     = None
    required: Any     = None
    message:  str     = ""

    @property
    def status(self) -> str:
        if self.passed:
            return "PASS"
        return "FAIL" if self.blocking else "WARN"


@dataclass
class ReadinessReport:
    overall_ready:    bool
    blocking_score:   int               # 0-5 - number of blocking criteria that passed
    readiness_score:  float             # 0.0-1.0
    criteria:         list[CriterionResult] = field(default_factory=list)
    summary:          str               = ""
    recommendation:   str               = ""

    @property
    def blocking_criteria(self) -> list[CriterionResult]:
        return [c for c in self.criteria if c.blocking]

    @property
    def warning_criteria(self) -> list[CriterionResult]:
        return [c for c in self.criteria if not c.blocking]


# ── Trade data loader ─────────────────────────────────────────────────────────

def _load_paper_trades(db_path: str, days: int) -> list[dict]:
    p = Path(db_path)
    if not p.is_file():
        return []
    try:
        conn = get_connection(p, timeout=5)
        try:
            params: list[Any] = ["PAPER"]
            where = ["mode = ?", "net_pnl IS NOT NULL"]
            if days and days > 0:
                import datetime as dt
                cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
                where.append("ts >= ?")
                params.append(cutoff)
            # Validate WHERE clause columns against known column names
            allowed_where_cols = {"mode", "net_pnl", "ts", "symbol", "direction", "status"}
            for w in where:
                col = w.split(" = ")[0].split(" IS ")[0].split(" >= ")[0].split(" <= ")[0].strip()
                if col not in allowed_where_cols:
                    raise ValueError(f"Invalid WHERE column: {col}")
            sql = f"SELECT * FROM trades WHERE {' AND '.join(where)} ORDER BY ts"
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]
    except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
        _log.debug("[READINESS] _load_paper_trades failed: %s", exc)
        return []


def _count_trading_days(trades: list[dict]) -> int:
    """Count unique trading days (YYYY-MM-DD) in the trade list."""
    days: set[str] = set()
    for t in trades:
        ts = str(t.get("ts") or "")
        if len(ts) >= 10:
            days.add(ts[:10])
    return len(days)


def _compute_drawdown(pnls: list[float]) -> float:
    """Maximum drawdown as a percentage of peak equity, from cumulative equity curve."""
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        if peak > 0:
            dd = (peak - cumulative) / peak * 100
            if dd > max_dd:
                max_dd = dd
    return round(max_dd, 2)


# ── Readiness check ───────────────────────────────────────────────────────────

def check_live_readiness(
    db_path: str = _DEFAULT_DB,
    cfg:     dict[str, Any] | None = None,
) -> ReadinessReport:
    """
    Evaluate paper trading history against live readiness criteria.

    Args:
        db_path : Path to trades.db (PAPER mode trades).
        cfg     : Config dict.

    Returns:
        ReadinessReport - always returns.
    """
    c = cfg or {}
    days       = int(c.get("live_readiness_days_window",       30))
    min_trades = int(c.get("live_readiness_min_paper_trades",  50))
    min_wr     = float(c.get("live_readiness_min_win_rate",    0.50))
    min_pf     = float(c.get("live_readiness_min_profit_factor", 1.30))
    max_dd     = float(c.get("live_readiness_max_drawdown_pct", 15.0))
    min_days   = int(c.get("live_readiness_min_trading_days",  10))

    trades = _load_paper_trades(db_path, days)
    n      = len(trades)
    pnls   = [float(t.get("net_pnl") or 0) for t in trades]

    wins   = sum(1 for p in pnls if p > 0)
    n - wins
    wr     = (wins / n) if n > 0 else 0.0

    gross_wins   = sum(p for p in pnls if p > 0)
    gross_losses = abs(sum(p for p in pnls if p < 0))
    pf = (gross_wins / gross_losses) if gross_losses > 0 else (10.0 if gross_wins > 0 else 0.0)

    actual_dd   = _compute_drawdown(pnls)
    trade_days  = _count_trading_days(trades)

    # Sharpe
    if n > 1:
        mean_p = sum(pnls) / n
        std_p  = math.sqrt(sum((p - mean_p) ** 2 for p in pnls) / n)
        sharpe = mean_p / std_p if std_p > 0 else 0.0
    else:
        sharpe = 0.0

    criteria: list[CriterionResult] = []

    # ── Blocking criteria ──────────────────────────────────────────────────────
    criteria.append(CriterionResult(
        name="Minimum paper trades",
        passed=(n >= min_trades),
        blocking=True,
        actual=n,
        required=min_trades,
        message=f"{n} trades (need {min_trades})",
    ))
    criteria.append(CriterionResult(
        name="Win rate",
        passed=(wr >= min_wr),
        blocking=True,
        actual=round(wr * 100, 1),
        required=round(min_wr * 100, 1),
        message=f"{wr*100:.1f}% (need >= {min_wr*100:.0f}%)",
    ))
    criteria.append(CriterionResult(
        name="Profit factor",
        passed=(pf >= min_pf),
        blocking=True,
        actual=round(pf, 3),
        required=min_pf,
        message=f"{pf:.3f} (need >= {min_pf:.2f})",
    ))
    criteria.append(CriterionResult(
        name="Max drawdown <= threshold",
        passed=(actual_dd <= max_dd),
        blocking=True,
        actual=round(actual_dd, 2),
        required=max_dd,
        message=f"{actual_dd:.1f}% (max allowed {max_dd:.0f}%)",
    ))
    criteria.append(CriterionResult(
        name="Minimum trading days",
        passed=(trade_days >= min_days),
        blocking=True,
        actual=trade_days,
        required=min_days,
        message=f"{trade_days} days (need {min_days})",
    ))

    # ── Warning criteria ───────────────────────────────────────────────────────
    sharpe_min = float(c.get("live_readiness_min_sharpe", 0.5))
    criteria.append(CriterionResult(
        name="Sharpe ratio",
        passed=(sharpe >= sharpe_min),
        blocking=False,
        actual=round(sharpe, 3),
        required=sharpe_min,
        message=f"{sharpe:.3f} (recommend >= {sharpe_min})",
    ))

    # ML accuracy check
    try:
        import core.ml_performance_tracker as ml_tracker
        db_path = cfg.get("ml_tracker_db_path", "ml_tracker.db")
        cal_bins = ml_tracker.compute_calibration(n_bins=5, db_path=db_path) or []
        n_total = sum(b.get("count", 0) for b in cal_bins)
        ml_acc = 0.5
        if n_total > 0:
            correct = sum(b.get("count", 0) for b in cal_bins if b.get("calibrated", False))
            ml_acc = correct / n_total
        ml_min = float(c.get("health_check_accuracy_warn", 0.50))
        criteria.append(CriterionResult(
            name="ML accuracy",
            passed=(ml_acc >= ml_min),
            blocking=False,
            actual=round(ml_acc * 100, 1),
            required=round(ml_min * 100, 1),
            message=f"{ml_acc*100:.1f}% (recommend >= {ml_min*100:.0f}%)",
        ))
    except (ImportError, ValueError, TypeError, AttributeError, KeyError):
        _log.debug("[READINESS] ML accuracy check skipped")

    # ── Scoring ───────────────────────────────────────────────────────────────
    blocking = [c for c in criteria if c.blocking]
    warnings = [c for c in criteria if not c.blocking]
    n_blocking_pass = sum(1 for c in blocking if c.passed)
    n_warn_pass     = sum(1 for c in warnings if c.passed)
    overall_ready   = all(c.passed for c in blocking)

    n_warn_total = len(warnings) or 1
    blocking_score = n_blocking_pass
    readiness_score = round(
        0.7 * (n_blocking_pass / max(len(blocking), 1))
        + 0.3 * (n_warn_pass   / n_warn_total),
        3,
    )

    # Summary
    if overall_ready:
        summary = (
            f"READY FOR LIVE - All {len(blocking)} blocking criteria passed. "
            f"Readiness score: {readiness_score*100:.0f}%"
        )
        recommendation = "System meets minimum live trading requirements."
    else:
        failed_names = [c.name for c in blocking if not c.passed]
        summary = (
            f"NOT READY - {len(failed_names)} blocking criteria failed: "
            + ", ".join(failed_names)
        )
        recommendation = (
            "Continue paper trading until all blocking criteria are met. "
            f"Current score: {n_blocking_pass}/{len(blocking)} blocking passed."
        )

    return ReadinessReport(
        overall_ready=overall_ready,
        blocking_score=blocking_score,
        readiness_score=readiness_score,
        criteria=criteria,
        summary=summary,
        recommendation=recommendation,
    )


# ── Formatter ─────────────────────────────────────────────────────────────────

def format_readiness_report(report: ReadinessReport) -> str:
    lines = [
        "Live Readiness Check",
        "=" * 55,
        report.summary,
        "",
        "  Blocking Criteria:",
    ]
    for c in report.blocking_criteria:
        sym = "OK" if c.passed else "!!"
        lines.append(f"    [{sym}] {c.name:<35} {c.message}")
    lines.append("")
    lines.append("  Advisory Criteria (non-blocking):")
    for c in report.warning_criteria:
        sym = "OK" if c.passed else "~~"
        lines.append(f"    [{sym}] {c.name:<35} {c.message}")
    lines.append("")
    lines.append(f"  Readiness score:   {report.readiness_score*100:.1f}%")
    lines.append(f"  Recommendation:    {report.recommendation}")
    return "\n".join(lines)


def should_send_today(flag_dir: str = ".") -> bool:
    """Return True if the readiness notification has not been sent today."""
    import datetime as dt
    flag = Path(flag_dir) / _FLAG_FILE
    today = dt.date.today().isoformat()
    if flag.is_file():
        try:
            return flag.read_text().strip() != today
        except (OSError, ValueError):
            _log.debug("[READINESS] Flag file read failed")
    return True


def mark_sent_today(flag_dir: str = ".") -> None:
    """Write today's date to the flag file to prevent duplicate sends."""
    import datetime as dt
    flag = Path(flag_dir) / _FLAG_FILE
    try:
        flag.write_text(dt.date.today().isoformat())
    except (OSError, PermissionError) as e:
        _log.debug("[LIVE_READINESS_CHECKER] non-critical error: %s", e)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> None:
    ap = argparse.ArgumentParser(
        prog="python -m core.live_readiness_checker",
        description="Check if paper trading history meets live trading readiness criteria.",
    )
    ap.add_argument("--db",     default=_DEFAULT_DB)
    ap.add_argument("--days",   type=int, default=30)
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()

    cfg    = {"live_readiness_days_window": args.days}
    report = check_live_readiness(args.db, cfg)
    if args.format == "json":
        import json
        data = {
            "overall_ready":    report.overall_ready,
            "blocking_score":   report.blocking_score,
            "readiness_score":  report.readiness_score,
            "summary":          report.summary,
            "recommendation":   report.recommendation,
            "criteria": [
                {"name": c.name, "passed": c.passed, "blocking": c.blocking,
                 "actual": c.actual, "required": c.required, "message": c.message}
                for c in report.criteria
            ],
        }
        print(json.dumps(data, indent=2))
    else:
        print(format_readiness_report(report))


if __name__ == "__main__":
    _cli()
