"""
Parameter Sensitivity Analyzer (v2.44 Item 15).

Varies one config parameter at a time over a sweep of test values, re-applies
that parameter to historical trade outcomes, and reports how sensitive key
performance metrics are to that parameter's value.

Method: for each test value, the closed trades from trades.db are re-scored
using the alternative exit multiplier (or threshold) to produce a "what-if"
P&L series.  Summary stats (Sharpe, win rate, profit factor) are computed for
each point, and sensitivity_score = std(sharpes) / |mean(sharpes)| classifies
the parameter as:

    ROBUST    — sensitivity_score < 0.10
    SENSITIVE — 0.10 ≤ sensitivity_score < 0.25
    FRAGILE   — sensitivity_score ≥ 0.25

Public API
----------
    run_single_parameter_sensitivity(param, values, trades, cfg) → SensitivityResult

    run_sensitivity_analysis(db_path, params, cfg) → list[SensitivityResult]

    format_sensitivity_report(results) → str

    cli: python -m core.sensitivity_analyzer [--param SL_PCT] [--days 60]

Config keys (index_config.defaults.json)
-----------------------------------------
    sensitivity_analyzer_enabled : bool  default false
    sensitivity_report_days      : int   default 60
    sensitivity_in_pdf           : bool  default false
"""
from __future__ import annotations

import argparse
import logging
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_DB   = "trades.db"
_DEFAULT_DAYS = 60

# Parameters to sweep by default
DEFAULT_SENSITIVITY_PARAMS: dict[str, list[float]] = {
    "SL_PCT":           [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50],
    "TARGET_PCT":       [0.30, 0.40, 0.50, 0.60, 0.75, 1.00, 1.25],
    "TRAIL_PCT":        [0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50],
    "AI_THRESHOLD":     [55, 60, 65, 70, 75, 80],
    "IV_SPIKE_THRESHOLD": [1.2, 1.4, 1.6, 1.8, 2.0, 2.5],
}


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ParameterTestPoint:
    param_value:   float
    n_trades:      int
    win_rate:      float
    profit_factor: float
    sharpe:        float
    total_pnl:     float


@dataclass
class SensitivityResult:
    param_name:        str
    test_points:       list[ParameterTestPoint] = field(default_factory=list)
    sensitivity_score: float = 0.0
    verdict:           str   = "UNKNOWN"
    best_value:        float = 0.0
    best_sharpe:       float = 0.0
    insight:           str   = ""


# ── Trade loader ──────────────────────────────────────────────────────────────

def load_trades_for_sensitivity(
    db_path: str = _DEFAULT_DB,
    days:    int = _DEFAULT_DAYS,
) -> list[dict]:
    """Load closed trades for sensitivity analysis."""
    p = Path(db_path)
    if not p.is_file():
        return []
    try:
        conn = sqlite3.connect(str(p), check_same_thread=False, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            params: list[Any] = []
            where = ["net_pnl IS NOT NULL", "entry IS NOT NULL"]
            if days and days > 0:
                import datetime as dt
                cutoff = (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat()
                where.append("ts >= ?")
                params.append(cutoff)
            sql = f"SELECT * FROM trades WHERE {' AND '.join(where)} ORDER BY ts"
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]
    except Exception as exc:
        _log.debug("[SENSITIVITY] load_trades failed: %s", exc)
        return []


# ── What-if P&L re-computation ────────────────────────────────────────────────

def _apply_exit_param(
    trades: list[dict],
    param:  str,
    value:  float,
    base_cfg: dict[str, Any],
) -> list[float]:
    """
    Re-compute P&L for each trade using an alternative config parameter value.

    For SL_PCT / TARGET_PCT / TRAIL_PCT: scale original P&L proportionally to
    the ratio of new vs original multiplier.  For threshold params (AI_THRESHOLD,
    IV_SPIKE_THRESHOLD): filter out trades that would not have been taken.

    Returns a list of net P&L floats.
    """
    base_sl     = float(base_cfg.get("SL_PCT",     0.30))
    base_target = float(base_cfg.get("TARGET_PCT", 0.60))
    pnls: list[float] = []

    for t in trades:
        pnl   = float(t.get("net_pnl")  or 0)
        entry = float(t.get("entry")    or 1)
        score = int(t.get("score")      or 0)
        iv    = float(t.get("iv")       or 0)

        if param == "SL_PCT":
            ratio = value / base_sl if base_sl else 1.0
            if pnl < 0:
                pnls.append(pnl * ratio)
            else:
                pnls.append(pnl)

        elif param == "TARGET_PCT":
            ratio = value / base_target if base_target else 1.0
            if pnl > 0:
                pnls.append(pnl * ratio)
            else:
                pnls.append(pnl)

        elif param == "TRAIL_PCT":
            # Trail only affects winners; tighter trail locks in less
            trail_base = float(base_cfg.get("TRAIL_PCT", 0.20))
            ratio      = value / trail_base if trail_base else 1.0
            if pnl > 0:
                pnls.append(pnl * (0.5 + 0.5 * ratio))
            else:
                pnls.append(pnl)

        elif param == "AI_THRESHOLD":
            if score >= value:
                pnls.append(pnl)
            # else: trade would not have been taken — skip

        elif param == "IV_SPIKE_THRESHOLD":
            base_iv = float(base_cfg.get("IV_SPIKE_THRESHOLD", 1.5))
            # Higher threshold → fewer IV-spike filtered-out trades pass
            if iv <= value * entry * 0.01:  # rough check
                pnls.append(pnl)

        else:
            pnls.append(pnl)

    return pnls


# ── Metric computation ────────────────────────────────────────────────────────

def _compute_stats(pnls: list[float]) -> tuple[float, float, float, float]:
    """Return (win_rate, profit_factor, sharpe, total_pnl)."""
    n = len(pnls)
    if n == 0:
        return 0.0, 0.0, 0.0, 0.0

    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate      = len(wins) / n
    gross_wins    = sum(wins)
    gross_losses  = abs(sum(losses)) if losses else 0
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else (10.0 if gross_wins > 0 else 0.0)
    total_pnl     = sum(pnls)
    mean_pnl      = total_pnl / n
    std_pnl       = math.sqrt(sum((p - mean_pnl) ** 2 for p in pnls) / n) if n > 1 else 0.0
    sharpe        = (mean_pnl / std_pnl) if std_pnl > 0 else 0.0
    return win_rate, profit_factor, sharpe, total_pnl


# ── Core analysis ─────────────────────────────────────────────────────────────

def run_single_parameter_sensitivity(
    param:    str,
    values:   list[float],
    trades:   list[dict],
    cfg:      dict[str, Any] | None = None,
) -> SensitivityResult:
    """
    Run sensitivity analysis for one parameter over a list of test values.

    Args:
        param  : Config key name (e.g. "SL_PCT").
        values : List of test values to sweep.
        trades : Pre-loaded trade dicts.
        cfg    : Base config dict.

    Returns:
        SensitivityResult with all test points and derived verdict.
    """
    c = cfg or {}
    result = SensitivityResult(param_name=param)

    if not trades:
        result.verdict = "NO_DATA"
        result.insight = "Insufficient trade history for sensitivity analysis."
        return result

    for v in values:
        pnls = _apply_exit_param(trades, param, v, c)
        if not pnls:
            continue
        wr, pf, sharpe, total = _compute_stats(pnls)
        result.test_points.append(ParameterTestPoint(
            param_value   = v,
            n_trades      = len(pnls),
            win_rate      = round(wr * 100, 1),
            profit_factor = round(pf, 3),
            sharpe        = round(sharpe, 4),
            total_pnl     = round(total, 2),
        ))

    if not result.test_points:
        result.verdict = "NO_DATA"
        return result

    sharpes = [pt.sharpe for pt in result.test_points]
    mean_s  = sum(sharpes) / len(sharpes)
    std_s   = math.sqrt(sum((s - mean_s) ** 2 for s in sharpes) / len(sharpes)) if len(sharpes) > 1 else 0.0
    result.sensitivity_score = round(std_s / abs(mean_s), 4) if mean_s != 0 else std_s

    if result.sensitivity_score < 0.10:
        result.verdict = "ROBUST"
    elif result.sensitivity_score < 0.25:
        result.verdict = "SENSITIVE"
    else:
        result.verdict = "FRAGILE"

    best_pt = max(result.test_points, key=lambda pt: pt.sharpe)
    result.best_value  = best_pt.param_value
    result.best_sharpe = best_pt.sharpe

    if result.verdict == "ROBUST":
        result.insight = (
            f"{param} is robust — performance stable across tested range. "
            f"Optimal value ≈ {result.best_value}."
        )
    elif result.verdict == "SENSITIVE":
        result.insight = (
            f"{param} is moderately sensitive. "
            f"Best Sharpe ({result.best_sharpe:.3f}) at {result.best_value}. "
            f"Avoid extreme values."
        )
    else:
        result.insight = (
            f"WARNING: {param} is FRAGILE — small changes cause large metric swings. "
            f"Current config may be over-fitted. Best at {result.best_value}."
        )

    return result


def run_sensitivity_analysis(
    db_path: str = _DEFAULT_DB,
    params:  dict[str, list[float]] | None = None,
    cfg:     dict[str, Any] | None = None,
) -> list[SensitivityResult]:
    """
    Run sensitivity analysis for all parameters in `params`.

    Args:
        db_path : Path to trades.db.
        params  : {param_name: [test_values]}.  Defaults to DEFAULT_SENSITIVITY_PARAMS.
        cfg     : Config dict.

    Returns:
        List of SensitivityResult, one per parameter.
    """
    c     = cfg or {}
    days  = int(c.get("sensitivity_report_days", _DEFAULT_DAYS))
    param_map = params if params else DEFAULT_SENSITIVITY_PARAMS

    trades  = load_trades_for_sensitivity(db_path, days)
    results = []
    for param, values in param_map.items():
        r = run_single_parameter_sensitivity(param, values, trades, c)
        results.append(r)
        _log.debug("[SENSITIVITY] %s: %s (score=%.3f)", param, r.verdict, r.sensitivity_score)
    return results


# ── Formatter ─────────────────────────────────────────────────────────────────

def format_sensitivity_report(results: list[SensitivityResult]) -> str:
    """Return a multi-line human-readable sensitivity report."""
    if not results:
        return "Sensitivity analysis: no results."

    lines = ["Parameter Sensitivity Analysis", "=" * 50]
    for r in results:
        verdict_sym = {"ROBUST": "✓", "SENSITIVE": "~", "FRAGILE": "✗"}.get(r.verdict, "?")
        lines.append(
            f"\n  [{verdict_sym}] {r.param_name:<30}  {r.verdict:<10}  "
            f"score={r.sensitivity_score:.3f}  best={r.best_value} (sharpe {r.best_sharpe:.3f})"
        )
        for pt in r.test_points:
            bar = "#" * min(int(pt.win_rate / 2), 50)
            lines.append(
                f"      {pt.param_value:>8.3f}  trades={pt.n_trades:>4}  "
                f"wr={pt.win_rate:>5.1f}%  pf={pt.profit_factor:>5.2f}  "
                f"sharpe={pt.sharpe:>7.4f}  {bar}"
            )
        lines.append(f"    → {r.insight}")

    return "\n".join(lines)


# ── CLI entry point ───────────────────────────────────────────────────────────

def _cli() -> None:
    ap = argparse.ArgumentParser(
        prog="python -m core.sensitivity_analyzer",
        description="Analyze how sensitive performance is to config parameters.",
    )
    ap.add_argument("--db",     default=_DEFAULT_DB)
    ap.add_argument("--param",  help="Specific parameter to analyze (default: all)")
    ap.add_argument("--values", help="Comma-separated test values (e.g. 0.20,0.25,0.30)")
    ap.add_argument("--days",   type=int, default=_DEFAULT_DAYS)
    args = ap.parse_args()

    cfg = {"sensitivity_report_days": args.days}
    if args.param and args.values:
        vals = [float(v.strip()) for v in args.values.split(",")]
        results = [run_single_parameter_sensitivity(
            args.param, vals,
            load_trades_for_sensitivity(args.db, args.days), cfg,
        )]
    elif args.param:
        default_vals = DEFAULT_SENSITIVITY_PARAMS.get(args.param, [])
        if not default_vals:
            print(f"Unknown param '{args.param}'. Available: {list(DEFAULT_SENSITIVITY_PARAMS)}")
            return
        results = [run_single_parameter_sensitivity(
            args.param, default_vals,
            load_trades_for_sensitivity(args.db, args.days), cfg,
        )]
    else:
        results = run_sensitivity_analysis(args.db, None, cfg)

    print(format_sensitivity_report(results))


if __name__ == "__main__":
    _cli()
