#!/usr/bin/env python3
"""Quantitative Validation Report Generator (Phase 9).

Reads trades.db, computes all quantitative measures including:
  - Sharpe Ratio (annualized), Sortino Ratio, Calmar Ratio
  - CAGR, Win Rate, Profit Factor, Recovery Factor
  - Ulcer Index, MAR Ratio
  - Monte Carlo simulation (via core.monte_carlo)
  - Parametric VaR (95/99)
  - Stress test scenarios

Generates an HTML report with tables, charts (ASCII for terminal,
data tables for HTML), and CI-ready JSON output.

Usage:
    python scripts/quantitative_validation_report.py
    python scripts/quantitative_validation_report.py --days 90 --mode PAPER
    python scripts/quantitative_validation_report.py --ci --html report.html
    python scripts/quantitative_validation_report.py --json
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_log = logging.getLogger("quantitative_validation")

_DEFAULT_DB = "db/trades.db"
_DEFAULT_CAPITAL = 200000.0  # Default starting capital for RoR calculations
_REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"

# ── Database helpers ──────────────────────────────────────────────────────────


def _load_trades(
    db_path: str = _DEFAULT_DB,
    mode: str | None = None,
    days: int | None = None,
) -> list[dict]:
    """Load trades from trades.db with optional filtering."""
    path = Path(db_path)
    if not path.exists():
        print(f"  [WARN] trades.db not found: {db_path}")
        return []

    try:
        conn = sqlite3.connect(str(path), detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        params: list[Any] = []
        clauses: list[str] = []

        if mode:
            clauses.append("mode = ?")
            params.append(mode.upper())
        if days and days > 0:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
            clauses.append("ts >= ?")
            params.append(cutoff)

        where = " AND ".join(clauses) if clauses else ""
        sql = "SELECT * FROM trades"
        if where:
            sql += " WHERE " + where
        sql += " ORDER BY ts"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        # Try execution_orders table
        try:
            conn = sqlite3.connect(str(path), detect_types=sqlite3.PARSE_DECLTYPES)
            conn.row_factory = sqlite3.Row
            params = []
            clauses = []
            if mode:
                clauses.append("mode = ?")
                params.append(mode.upper())
            if days and days > 0:
                cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
                clauses.append("created_at >= ?")
                params.append(cutoff)
            where = " AND ".join(clauses) if clauses else ""
            sql = "SELECT * FROM execution_orders"
            if where:
                sql += " WHERE " + where
            sql += " ORDER BY created_at"
            rows = conn.execute(sql, params).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            print(f"  [ERROR] DB read failed: {e}")
            return []
    except sqlite3.Error as e:
        print(f"  [ERROR] DB read failed: {e}")
        return []


# ── Risk-free rate & annualization ────────────────────────────────────────────

_RISK_FREE_RATE = 0.07  # 7% annual (Indian T-bill proxy)
_TRADING_DAYS_PER_YEAR = 252


def _annualize_factor(n_trades: int, first_date: str | None, last_date: str | None) -> float:
    """Estimate annualization factor from trade date span or count."""
    if first_date and last_date:
        try:
            d1 = datetime.fromisoformat(first_date)
            d2 = datetime.fromisoformat(last_date)
            days = max((d2 - d1).days, 1)
            return math.sqrt(max(days / _TRADING_DAYS_PER_YEAR, 0.01))  # sqrt of years
        except (ValueError, TypeError):
            pass
    # Fallback: assume ~2 trades/day = ~500/yr
    years = max(n_trades / 500, 0.1)
    return math.sqrt(years)


# ── Quantitative metric computations ──────────────────────────────────────────


def _compute_sharpe_ratio(
    daily_returns: list[float],
    risk_free: float = _RISK_FREE_RATE,
) -> float:
    """Annualized Sharpe ratio from daily return list."""
    if len(daily_returns) < 2:
        return 0.0
    mean_ret = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean_ret) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return 0.0
    daily_rf = risk_free / _TRADING_DAYS_PER_YEAR
    excess = mean_ret - daily_rf
    sharpe = (excess / std) * math.sqrt(_TRADING_DAYS_PER_YEAR)
    return round(sharpe, 4)


def _compute_sortino_ratio(
    daily_returns: list[float],
    risk_free: float = _RISK_FREE_RATE,
) -> float:
    """Annualized Sortino ratio (downside deviation instead of std)."""
    if len(daily_returns) < 2:
        return 0.0
    mean_ret = sum(daily_returns) / len(daily_returns)
    daily_rf = risk_free / _TRADING_DAYS_PER_YEAR
    excess = mean_ret - daily_rf

    downside = [r for r in daily_returns if r < daily_rf]
    if not downside:
        return float("inf") if excess > 0 else 0.0
    downside_var = sum((r - daily_rf) ** 2 for r in downside) / len(daily_returns)
    downside_std = math.sqrt(downside_var) if downside_var > 0 else 0.0
    if downside_std == 0:
        return 0.0
    sortino = (excess / downside_std) * math.sqrt(_TRADING_DAYS_PER_YEAR)
    return round(sortino, 4)


def _compute_cagr(
    total_pnl: float,
    starting_capital: float,
    first_date: str | None,
    last_date: str | None,
) -> float:
    """Compound Annual Growth Rate."""
    if starting_capital <= 0 or not first_date or not last_date:
        return 0.0
    try:
        d1 = datetime.fromisoformat(first_date)
        d2 = datetime.fromisoformat(last_date)
        days = max((d2 - d1).days, 1)
        years = days / 365.0
        ending_value = starting_capital + total_pnl
        if starting_capital <= 0 or ending_value <= 0:
            return 0.0
        cagr = (ending_value / starting_capital) ** (1.0 / years) - 1
        return round(cagr, 6)
    except (ValueError, TypeError):
        return 0.0


def _compute_calmar_ratio(cagr: float, max_drawdown: float) -> float:
    """Calmar Ratio = CAGR / Max Drawdown (absolute)."""
    if max_drawdown <= 0:
        return float("inf") if cagr > 0 else 0.0
    return round(cagr / max_drawdown, 6)


def _compute_ulcer_index(daily_values: list[float]) -> float:
    """Ulcer Index: root-mean-square of drawdowns from previous peak."""
    if len(daily_values) < 2:
        return 0.0
    peak = daily_values[0]
    drawdowns: list[float] = []
    for v in daily_values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        drawdowns.append(dd * 100)  # as percentage
    if not drawdowns:
        return 0.0
    sum_sq = sum(d * d for d in drawdowns)
    return round(math.sqrt(sum_sq / len(drawdowns)), 4)


def _compute_mar_ratio(cagr: float, max_drawdown_pct: float) -> float:
    """MAR Ratio = CAGR / Max Drawdown %."""
    if max_drawdown_pct <= 0:
        return float("inf") if cagr > 0 else 0.0
    return round(cagr / (max_drawdown_pct / 100.0), 4)


def _compute_var(net_pnls: list[float], confidence: float = 0.95) -> float:
    """Parametric VaR assuming normal distribution."""
    if len(net_pnls) < 2:
        return 0.0
    mean = sum(net_pnls) / len(net_pnls)
    variance = sum((p - mean) ** 2 for p in net_pnls) / (len(net_pnls) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return 0.0
    from math import erfinv
    z_score = math.sqrt(2) * erfinv(2 * confidence - 1)
    var = mean + z_score * std
    return round(var, 2)


def _compute_historical_var(net_pnls: list[float], confidence: float = 0.95) -> float:
    """Historical VaR (non-parametric)."""
    if not net_pnls:
        return 0.0
    sorted_pnls = sorted(net_pnls)
    idx = int((1 - confidence) * len(sorted_pnls))
    idx = max(0, min(idx, len(sorted_pnls) - 1))
    return round(sorted_pnls[idx], 2)


def _build_daily_series(trades: list[dict]) -> list[dict]:
    """Aggregate trades by trading day, computing daily P&L and equity."""
    daily: dict[str, list[float]] = {}
    dates: list[str] = []
    for t in trades:
        ts = str(t.get("ts", ""))[:10]  # YYYY-MM-DD
        if not ts:
            continue
        if ts not in daily:
            daily[ts] = []
            dates.append(ts)
        daily[ts].append(float(t.get("net_pnl", 0) or 0))
    dates.sort()

    equity = 0.0
    series = []
    for d in dates:
        day_pnl = sum(daily[d])
        equity += day_pnl
        series.append({
            "date": d,
            "pnl": round(day_pnl, 2),
            "equity": round(equity, 2),
            "trades": len(daily[d]),
        })
    return series


def _compute_stress_scenarios(trades: list[dict]) -> dict[str, Any]:
    """Simulate worst-case scenario impacts on the portfolio."""
    net_pnls = [float(t.get("net_pnl", 0) or 0) for t in trades]
    if not net_pnls:
        return {}

    total_pnl = sum(net_pnls)
    avg_pnl = total_pnl / len(net_pnls)
    sorted_pnls = sorted(net_pnls)
    worst_10 = sorted_pnls[:max(1, len(sorted_pnls) // 10)]
    worst_5 = sorted_pnls[:max(1, len(sorted_pnls) // 20)]

    return {
        "total_trades": len(net_pnls),
        "total_pnl": round(total_pnl, 2),
        "avg_trade_pnl": round(avg_pnl, 2),
        "worst_10_pct_avg": round(sum(worst_10) / len(worst_10), 2) if worst_10 else 0.0,
        "worst_5_pct_avg": round(sum(worst_5) / len(worst_5), 2) if worst_5 else 0.0,
        "flash_crash_impact": round(sum(worst_10) * 1.5, 2),  # 50% worse than worst 10%
        "gap_up_impact": round(sum(t for t in net_pnls if t < 0) * 1.3, 2),  # 30% worse losses
        "volatility_spike_impact": round(sum(net_pnls) * -0.15, 2) if total_pnl > 0 else round(total_pnl * 0.5, 2),
    }


# ── Monte Carlo wrapper ────────────────────────────────────────────────────────


def _run_monte_carlo(
    net_pnls: list[float],
    n_sims: int = 1000,
) -> dict[str, Any]:
    """Run Monte Carlo simulation using core.monte_carlo if available, else inline."""
    try:
        from core.monte_carlo import run_simulation as mc_run
        result = mc_run(net_pnls, n_simulations=n_sims, seed=42)
        return {
            "n_simulations": result.n_simulations,
            "n_trades": result.n_trades,
            "median_final_pnl": result.median_final_pnl,
            "p5_final_pnl": result.p5_final_pnl,
            "p95_final_pnl": result.p95_final_pnl,
            "mean_final_pnl": result.mean_final_pnl,
            "prob_of_profit": result.prob_of_profit * 100,
            "median_max_drawdown": result.median_max_drawdown,
            "p95_max_drawdown": result.p95_max_drawdown,
            "worst_case_streak_p95": result.worst_case_streak_p95,
            "median_sharpe": result.median_sharpe,
            "p5_sharpe": result.p5_sharpe,
        }
    except ImportError:
        pass

    # Fallback inline Monte Carlo
    import random
    rng = random.Random(42)
    n = len(net_pnls)
    if n < 2:
        return {"error": "Need at least 2 trades for Monte Carlo"}

    final_pnls: list[float] = []
    max_dds: list[float] = []
    for _ in range(n_sims):
        sim = list(net_pnls)
        rng.shuffle(sim)
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for p in sim:
            cumulative += p
            peak = max(peak, cumulative)
            max_dd = max(max_dd, peak - cumulative)
        final_pnls.append(cumulative)
        max_dds.append(max_dd)

    final_pnls.sort()
    max_dds.sort()

    def pct(arr: list[float], p: float) -> float:
        idx = int(p * (len(arr) - 1))
        return arr[idx]

    return {
        "n_simulations": n_sims,
        "n_trades": n,
        "median_final_pnl": round(pct(final_pnls, 0.50), 2),
        "p5_final_pnl": round(pct(final_pnls, 0.05), 2),
        "p95_final_pnl": round(pct(final_pnls, 0.95), 2),
        "mean_final_pnl": round(sum(final_pnls) / n_sims, 2),
        "prob_of_profit": round(sum(1 for v in final_pnls if v > 0) / n_sims * 100, 1),
        "median_max_drawdown": round(pct(max_dds, 0.50), 2),
        "p95_max_drawdown": round(pct(max_dds, 0.95), 2),
    }


# ── Main validation engine ─────────────────────────────────────────────────────


def compute_quantitative_report(
    db_path: str = _DEFAULT_DB,
    mode: str | None = None,
    days: int | None = None,
    starting_capital: float = _DEFAULT_CAPITAL,
    n_monte_carlo: int = 1000,
) -> dict[str, Any]:
    """Compute the full quantitative validation report."""
    trades = _load_trades(db_path, mode=mode, days=days)
    if not trades:
        return {"error": "No trades found", "trades": 0}

    net_pnls = [float(t.get("net_pnl", 0) or 0) for t in trades]
    gross_pnls = [float(t.get("gross_pnl", 0) or 0) for t in trades]
    n = len(trades)

    # Basic metrics
    winners = [p for p in net_pnls if p >= 0]
    losers = [p for p in net_pnls if p < 0]
    n_win = len(winners)
    n_loss = len(losers)
    win_rate = n_win / n if n else 0.0
    avg_win = sum(winners) / n_win if n_win else 0.0
    avg_loss = sum(losers) / n_loss if n_loss else 0.0

    total_net = sum(net_pnls)
    total_gross = sum(gross_pnls)
    gross_wins = sum(p for p in gross_pnls if p > 0)
    gross_losses = abs(sum(p for p in gross_pnls if p < 0))
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else float("inf")

    # Daily series for time-based metrics
    daily_series = _build_daily_series(trades)
    daily_returns = [d["pnl"] / max(starting_capital, 1) for d in daily_series]
    daily_equity = [d["equity"] for d in daily_series]

    # Max drawdown
    equity_curve = [0.0]
    for p in net_pnls:
        equity_curve.append(equity_curve[-1] + p)
    peak = 0.0
    max_dd = 0.0
    max_dd_pct = 0.0
    for v in equity_curve:
        peak = max(peak, v)
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = (dd / peak * 100) if peak > 0 else 0.0
    current_dd = peak - equity_curve[-1] if equity_curve else 0.0

    # Dates for CAGR
    first_date = str(trades[0].get("ts", "")) if trades else None
    last_date = str(trades[-1].get("ts", "")) if trades else None

    # Compute all advanced metrics
    sharpe_annualized = _compute_sharpe_ratio(daily_returns)
    sortino_annualized = _compute_sortino_ratio(daily_returns)
    cagr = _compute_cagr(total_net, starting_capital, first_date, last_date)
    calmar = _compute_calmar_ratio(cagr, max_dd)
    ulcer = _compute_ulcer_index(daily_equity) if daily_equity else 0.0
    mar = _compute_mar_ratio(cagr, max_dd_pct)

    # VaR
    var_95 = _compute_var(net_pnls, 0.95)
    var_99 = _compute_var(net_pnls, 0.99)
    hist_var_95 = _compute_historical_var(net_pnls, 0.95)
    hist_var_99 = _compute_historical_var(net_pnls, 0.99)

    # Recovery factor
    recovery = (total_net / max_dd) if max_dd > 0 else float("inf")

    # Expectancy
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    # Consecutive wins/losses
    max_consec_w = 0
    max_consec_l = 0
    cur_w = 0
    cur_l = 0
    for p in net_pnls:
        if p >= 0:
            cur_w += 1
            cur_l = 0
            max_consec_w = max(max_consec_w, cur_w)
        else:
            cur_l += 1
            cur_w = 0
            max_consec_l = max(max_consec_l, cur_l)

    # Stress scenarios
    stress = _compute_stress_scenarios(trades)

    # Monte Carlo
    mc = _run_monte_carlo(net_pnls, n_sims=n_monte_carlo)

    # Return on capital
    roc = (total_net / starting_capital * 100) if starting_capital > 0 else 0.0

    report: dict[str, Any] = {
        "report_metadata": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "db_path": db_path,
            "mode": mode or "ALL",
            "days": days or "ALL",
            "starting_capital": starting_capital,
            "trades_analyzed": n,
        },
        "summary_metrics": {
            "total_trades": n,
            "winners": n_win,
            "losers": n_loss,
            "win_rate_pct": round(win_rate * 100, 2),
            "win_loss_ratio": round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else float("inf"),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "expectancy": round(expectancy, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "inf",
            "total_net_pnl": round(total_net, 2),
            "total_gross_pnl": round(total_gross, 2),
            "largest_win": round(max(net_pnls), 2) if net_pnls else 0.0,
            "largest_loss": round(min(net_pnls), 2) if net_pnls else 0.0,
        },
        "risk_adjusted_metrics": {
            "sharpe_ratio_annualized": sharpe_annualized,
            "sortino_ratio_annualized": sortino_annualized,
            "cagr_pct": round(cagr * 100, 4),
            "calmar_ratio": calmar,
            "mar_ratio": mar,
            "ulcer_index": ulcer,
            "return_on_capital_pct": round(roc, 2),
        },
        "drawdown_metrics": {
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "current_drawdown": round(current_dd, 2),
            "recovery_factor": round(recovery, 2) if recovery != float("inf") else "inf",
            "max_consecutive_wins": max_consec_w,
            "max_consecutive_losses": max_consec_l,
        },
        "var_metrics": {
            "var_95_parametric": var_95,
            "var_99_parametric": var_99,
            "var_95_historical": hist_var_95,
            "var_99_historical": hist_var_99,
        },
        "stress_scenarios": stress,
        "monte_carlo": mc,
        "daily_series": daily_series[-30:],  # Last 30 days only
    }

    return report


# ── HTML Report Generator ─────────────────────────────────────────────────────


def _val(v: Any, fmt: str = ".2f") -> str:
    """Format a value for HTML display."""
    if v is None:
        return "—"
    if isinstance(v, float):
        if abs(v) > 1e9:
            return f"₹{v:,.0f}"
        if fmt == ".2f":
            return f"₹{v:,.2f}" if abs(v) >= 0.01 else f"₹{v:.4f}"
        return f"{v:{fmt}}"
    if isinstance(v, str) and v == "inf":
        return "∞"
    return str(v)


def _metric_row(label: str, value: Any, threshold: tuple | None = None) -> str:
    """Generate an HTML table row with optional pass/warn/fail coloring."""
    css_class = ""
    if threshold:
        if isinstance(value, (int, float)):
            lo, hi = threshold
            if value < lo:
                css_class = ' class="metric-fail"'
            elif value < hi:
                css_class = ' class="metric-warn"'
            else:
                css_class = ' class="metric-pass"'
    return f"<tr{css_class}><td class='label'>{label}</td><td class='value'>{_val(value)}</td></tr>"


def generate_html_report(report: dict[str, Any]) -> str:
    """Generate a self-contained HTML report."""
    meta = report.get("report_metadata", {})
    summary = report.get("summary_metrics", {})
    risk = report.get("risk_adjusted_metrics", {})
    dd = report.get("drawdown_metrics", {})
    var_m = report.get("var_metrics", {})
    stress = report.get("stress_scenarios", {})
    mc = report.get("monte_carlo", {})
    daily = report.get("daily_series", [])

    # Determine pass/fail thresholds
    sharpe = risk.get("sharpe_ratio_annualized", 0)
    sortino = risk.get("sortino_ratio_annualized", 0)
    ulcer = risk.get("ulcer_index", 0)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Quantitative Validation Report — OPB Trading System</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 960px; margin: 20px auto; padding: 20px; background: #f5f7fa; color: #333; }}
  h1 {{ color: #1a237e; border-bottom: 3px solid #1a237e; padding-bottom: 8px; }}
  h2 {{ color: #283593; margin-top: 30px; }}
  .meta {{ color: #666; font-size: 0.9em; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 10px 0 20px 0; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-radius: 4px; }}
  th, td {{ padding: 8px 14px; text-align: left; border-bottom: 1px solid #e0e0e0; }}
  th {{ background: #1a237e; color: white; font-weight: 500; }}
  .label {{ font-weight: 500; color: #555; width: 60%; }}
  .value {{ font-weight: 600; text-align: right; font-family: 'Consolas', monospace; }}
  .metric-pass {{ background: #e8f5e9; }}
  .metric-pass .value {{ color: #2e7d32; }}
  .metric-warn {{ background: #fff8e1; }}
  .metric-warn .value {{ color: #f57f17; }}
  .metric-fail {{ background: #ffebee; }}
  .metric-fail .value {{ color: #c62828; }}
  .section {{ margin: 20px 0; }}
  .overall-score {{ text-align: center; padding: 20px; background: linear-gradient(135deg, #1a237e, #3949ab); color: white; border-radius: 8px; margin: 20px 0; }}
  .overall-score .score {{ font-size: 3em; font-weight: 700; }}
  .overall-score .label {{ color: rgba(255,255,255,0.8); font-size: 1.1em; }}
  .status-badge {{ display: inline-block; padding: 4px 12px; border-radius: 4px; font-weight: 600; font-size: 0.85em; }}
  .status-pass {{ background: #4caf50; color: white; }}
  .status-warn {{ background: #ff9800; color: white; }}
  .status-fail {{ background: #f44336; color: white; }}
  .daily-chart {{ margin: 20px 0; padding: 15px; background: white; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .daily-chart .bar {{ display: inline-block; margin: 0 1px; vertical-align: bottom; }}
  .daily-chart .bar-positive {{ background: #4caf50; }}
  .daily-chart .bar-negative {{ background: #f44336; }}
  footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e0e0e0; color: #999; font-size: 0.85em; text-align: center; }}
</style>
</head>
<body>
<h1>📊 Quantitative Validation Report</h1>
<div class="meta">
  Generated: {meta.get('generated_at', 'N/A')}<br>
  Database: {meta.get('db_path', 'N/A')} | Mode: {meta.get('mode', 'ALL')} |
  Period: {f'Last {meta.get("days", "ALL")} days' if isinstance(meta.get('days'), int) else 'All time'}<br>
  Starting Capital: ₹{meta.get('starting_capital', 0):,.0f} |
  Trades Analyzed: <strong>{meta.get('trades_analyzed', 0)}</strong>
</div>

<div class="overall-score">
  <div class="label">Quantitative Health Score</div>
  <div class="score">{_compute_overall_score(summary, risk, dd, mc):.1f}%</div>
  <div style="margin-top:8px"><span class="status-badge {_pass_fail(_compute_overall_score(summary, risk, dd, mc), 50, 75)}">{
    'PASS' if _compute_overall_score(summary, risk, dd, mc) >= 75 else 'WARN' if _compute_overall_score(summary, risk, dd, mc) >= 50 else 'FAIL'
  }</span></div>
</div>

<div class="section">
<h2>1. Summary Metrics</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
{_metric_row('Total Trades', summary.get('total_trades', 0))}
{_metric_row('Winners / Losers', f"{summary.get('winners', 0)} / {summary.get('losers', 0)}")}
{_metric_row('Win Rate', summary.get('win_rate_pct', 0), (30, 45))}
{_metric_row('Win/Loss Ratio', summary.get('win_loss_ratio', 0), (1.0, 1.5))}
{_metric_row('Expectancy (per trade)', summary.get('expectancy', 0), (0, 10))}
{_metric_row('Profit Factor', summary.get('profit_factor', 0), (1.0, 1.5))}
{_metric_row('Total Net P&L', summary.get('total_net_pnl', 0))}
{_metric_row('Avg Win', summary.get('avg_win', 0))}
{_metric_row('Avg Loss', summary.get('avg_loss', 0))}
{_metric_row('Largest Win', summary.get('largest_win', 0))}
{_metric_row('Largest Loss', summary.get('largest_loss', 0))}
</table>
</div>

<div class="section">
<h2>2. Risk-Adjusted Metrics</h2>
<table>
<tr><th>Metric</th><th>Value</th><th>Benchmark</th></tr>
<tr{_score_class(sharpe, 0.5, 1.0)}><td class='label'>Sharpe Ratio (Annualized)</td><td class='value'>{sharpe:.3f}</td><td>>1.0 Excellent</td></tr>
<tr{_score_class(sortino, 0.8, 1.5)}><td class='label'>Sortino Ratio (Annualized)</td><td class='value'>{sortino:.3f}</td><td>>1.5 Excellent</td></tr>
<tr{_score_class(risk.get('cagr_pct', 0), 5, 15)}><td class='label'>CAGR</td><td class='value'>{risk.get('cagr_pct', 0):.2f}%</td><td>>15% Excellent</td></tr>
<tr{_score_class(risk.get('calmar_ratio', 0), 0.5, 1.0)}><td class='label'>Calmar Ratio</td><td class='value'>{risk.get('calmar_ratio', 0):.3f}</td><td>>1.0 Excellent</td></tr>
<tr{_score_class(risk.get('mar_ratio', 0), 0.5, 1.0)}><td class='label'>MAR Ratio</td><td class='value'>{risk.get('mar_ratio', 0):.3f}</td><td>>1.0 Excellent</td></tr>
<tr{_score_class_lower_better(ulcer, 5, 20)}><td class='label'>Ulcer Index</td><td class='value'>{ulcer:.2f}</td><td><5 Low</td></tr>
<tr{_score_class(risk.get('return_on_capital_pct', 0), 5, 20)}><td class='label'>Return on Capital</td><td class='value'>{risk.get('return_on_capital_pct', 0):.2f}%</td><td>>20% Excellent</td></tr>
</table>
</div>

<div class="section">
<h2>3. Drawdown Analysis</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
{_metric_row('Max Drawdown (₹)', dd.get('max_drawdown', 0))}
{_metric_row('Max Drawdown (%)', dd.get('max_drawdown_pct', 0), (15, 30))}
{_metric_row('Current Drawdown (₹)', dd.get('current_drawdown', 0))}
{_metric_row('Recovery Factor', dd.get('recovery_factor', 0), (1.0, 2.0))}
{_metric_row('Max Consecutive Wins', dd.get('max_consecutive_wins', 0))}
<tr class="{'metric-pass' if dd.get('max_consecutive_losses', 0) <= 2 else 'metric-warn' if dd.get('max_consecutive_losses', 0) <= 5 else 'metric-fail'}"><td class='label'>Max Consecutive Losses</td><td class='value'>{_val(dd.get('max_consecutive_losses', 0))}</td></tr>
</table>
</div>

<div class="section">
<h2>4. Value-at-Risk</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
{_metric_row('VaR 95% (Parametric)', var_m.get('var_95_parametric', 0))}
{_metric_row('VaR 99% (Parametric)', var_m.get('var_99_parametric', 0))}
{_metric_row('VaR 95% (Historical)', var_m.get('var_95_historical', 0))}
{_metric_row('VaR 99% (Historical)', var_m.get('var_99_historical', 0))}
</table>
</div>

<div class="section">
<h2>5. Monte Carlo Simulation</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
{_metric_row('Simulations', mc.get('n_simulations', 0))}
{_metric_row('Trades Used', mc.get('n_trades', 0))}
{_metric_row('Median Final P&L', mc.get('median_final_pnl', 0))}
{_metric_row('P5 Final P&L (Worst 5%)', mc.get('p5_final_pnl', 0))}
{_metric_row('P95 Final P&L (Best 95%)', mc.get('p95_final_pnl', 0))}
{_metric_row('Probability of Profit', mc.get('prob_of_profit', 0), (50, 80))}
{_metric_row('Median Max Drawdown', mc.get('median_max_drawdown', 0))}
{_metric_row('P95 Max Drawdown', mc.get('p95_max_drawdown', 0))}
</table>
</div>

<div class="section">
<h2>6. Stress Test Scenarios</h2>
<table>
<tr><th>Scenario</th><th>Estimated Impact</th></tr>
{_metric_row('Average Trade', stress.get('avg_trade_pnl', 0))}
{_metric_row('Worst 10% Avg', stress.get('worst_10_pct_avg', 0))}
{_metric_row('Flash Crash (50% worse)', stress.get('flash_crash_impact', 0))}
{_metric_row('Gap Up (30% worse losses)', stress.get('gap_up_impact', 0))}
{_metric_row('Volatility Spike', stress.get('volatility_spike_impact', 0))}
</table>
</div>

<div class="section">
<h2>7. Daily P&L (Last {min(len(daily), 30)} Days)</h2>
<table>
<tr><th>Date</th><th>Trades</th><th>Daily P&L</th><th>Cumulative Equity</th></tr>
"""

    for d in daily[-30:]:
        cls = ""
        pnl = d.get("pnl", 0)
        if pnl > 0:
            cls = ' style="color:#2e7d32"'
        elif pnl < 0:
            cls = ' style="color:#c62828"'
        html += f"<tr><td>{d.get('date', '')}</td><td>{d.get('trades', 0)}</td><td{cls}>₹{pnl:+,.2f}</td><td>₹{d.get('equity', 0):+,.2f}</td></tr>\n"

    # Simple equity bar chart using Unicode
    if daily:
        equities = [d.get("equity", 0) for d in daily]
        min_eq = min(equities)
        max_eq = max(equities)
        span_eq = max(max_eq - min_eq, 1)
        bars_html = '<div style="background:#f5f5f5; padding:10px; border-radius:4px; font-family:Consolas,monospace; font-size:0.75em; line-height:1.2; white-space:nowrap; overflow-x:auto;">'
        bars_html += '<div style="margin-bottom:6px; color:#666;">Equity Curve (█=positive, ░=negative)</div>'
        for d in daily:
            eq = d.get("equity", 0)
            h = int((eq - min_eq) / span_eq * 20) + 1
            bar_char = "█" if eq >= 0 else "░"
            color = "#4caf50" if eq >= 0 else "#f44336"
            bars_html += f'<div style="color:{color};">{bar_char * h} ₹{eq:+,.0f}</div>'
        bars_html += '</div>'
        html += f'<tr><td colspan="4">{bars_html}</td></tr>'

    html += """
</table>
</div>

<footer>
  OPB Index Options Trading System — Quantitative Validation Report
  | Generated by scripts/quantitative_validation_report.py
</footer>
</body>
</html>"""
    return html


def _compute_overall_score(
    summary: dict, risk: dict, dd: dict, mc: dict
) -> float:
    """Compute an overall quantitative health score 0-100."""
    scores: list[float] = []

    # Win rate: 0-100 scaled
    wr = summary.get("win_rate_pct", 0)
    scores.append(min(wr * 1.5, 100) if wr > 0 else 0)

    # Profit factor: 0-100, target >= 2.0
    pf = summary.get("profit_factor", 0)
    if isinstance(pf, (int, float)):
        scores.append(min(pf * 40, 100) if pf > 0 else 0)

    # Sharpe: 0-100, target >= 2.0
    sharpe = risk.get("sharpe_ratio_annualized", 0)
    scores.append(min(max(sharpe * 30 + 40, 0), 100))

    # Sortino: 0-100
    sortino = risk.get("sortino_ratio_annualized", 0)
    scores.append(min(max(sortino * 25 + 40, 0), 100))

    # CAGR: 0-100, target >= 20%
    cagr = risk.get("cagr_pct", 0)
    scores.append(min(cagr * 3, 100) if cagr > 0 else 0)

    # Calmar: 0-100, target >= 2.0
    calmar = risk.get("calmar_ratio", 0)
    if isinstance(calmar, (int, float)):
        scores.append(min(calmar * 30 + 20, 100) if calmar > 0 else 20)

    # Ulcer: inverse - lower is better
    ulcer = risk.get("ulcer_index", 100)
    scores.append(max(100 - ulcer * 5, 0) if ulcer > 0 else 100)

    # Max DD%: inverse
    dd_pct = dd.get("max_drawdown_pct", 100)
    scores.append(max(100 - dd_pct * 2, 0) if dd_pct > 0 else 100)

    # Recovery factor: 0-100
    rf = dd.get("recovery_factor", 0)
    if isinstance(rf, (int, float)):
        scores.append(min(rf * 20, 100))

    # MC prob of profit
    mc_prob = mc.get("prob_of_profit", 0)
    if isinstance(mc_prob, (int, float)):
        scores.append(mc_prob)

    avg_score = sum(scores) / len(scores) if scores else 0.0
    return round(avg_score, 1)


def _pass_fail(score: float, warn_threshold: float, pass_threshold: float) -> str:
    """Return CSS class based on score thresholds."""
    if score >= pass_threshold:
        return "status-pass"
    elif score >= warn_threshold:
        return "status-warn"
    return "status-fail"


def _score_class(value: float, warn_lo: float, pass_lo: float) -> str:
    """Return HTML class. Assumes higher is better."""
    if value >= pass_lo:
        return ' class="metric-pass"'
    elif value >= warn_lo:
        return ' class="metric-warn"'
    return ' class="metric-fail"'


def _score_class_lower_better(value: float, pass_hi: float, warn_hi: float) -> str:
    """Return HTML class. Assumes lower is better (e.g., drawdown, ulcer index).

    - value <= pass_hi: green PASS (good, low value)
    - value <= warn_hi: yellow WARN
    - value > warn_hi: red FAIL (bad, high value)
    """
    if value <= pass_hi:
        return ' class="metric-pass"'
    elif value <= warn_hi:
        return ' class="metric-warn"'
    return ' class="metric-fail"'


# ── CLI ────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Quantitative Validation Report Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", default=_DEFAULT_DB, help="Path to trades.db")
    parser.add_argument("--mode", default=None, help="PAPER / LIVE filter")
    parser.add_argument("--days", type=int, default=None, help="Last N days only")
    parser.add_argument("--capital", type=float, default=_DEFAULT_CAPITAL,
                        help="Starting capital for RoR/CAGR (default 200000)")
    parser.add_argument("--mc-sims", type=int, default=1000,
                        help="Monte Carlo simulations (default 1000)")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON report to stdout")
    parser.add_argument("--html", default=None,
                        help="Path to write HTML report (default: reports/quantitative_validation_<date>.html)")
    parser.add_argument("--ci", action="store_true",
                        help="CI mode: exit non-zero if health score < 50")
    args = parser.parse_args()

    print("  Running quantitative validation...")
    print(f"  DB: {args.db} | Mode: {args.mode or 'ALL'} | Days: {args.days or 'ALL'}")
    print(f"  Monte Carlo simulations: {args.mc_sims}")

    report = compute_quantitative_report(
        db_path=args.db,
        mode=args.mode,
        days=args.days,
        starting_capital=args.capital,
        n_monte_carlo=args.mc_sims,
    )

    if "error" in report:
        print(f"  [ERROR] {report['error']}")
        return 1 if args.ci else 0

    # Display summary
    s = report.get("summary_metrics", {})
    r = report.get("risk_adjusted_metrics", {})
    d = report.get("drawdown_metrics", {})
    m = report.get("monte_carlo", {})
    score = _compute_overall_score(s, r, d, m)

    print(f"\n{'='*60}")
    print("  QUANTITATIVE VALIDATION REPORT")
    print(f"{'='*60}")
    print(f"  Trades: {s.get('total_trades', 0)} | WR: {s.get('win_rate_pct', 0):.1f}%")
    print(f"  PF: {s.get('profit_factor', '—')} | Expectancy: ₹{s.get('expectancy', 0):+.2f}")
    print(f"  Sharpe: {r.get('sharpe_ratio_annualized', 0):.3f} | Sortino: {r.get('sortino_ratio_annualized', 0):.3f}")
    print(f"  CAGR: {r.get('cagr_pct', 0):.2f}% | Calmar: {r.get('calmar_ratio', 0):.3f}")
    print(f"  Max DD: ₹{d.get('max_drawdown', 0):,.2f} ({d.get('max_drawdown_pct', 0):.1f}%)")
    print(f"  Ulcer Index: {r.get('ulcer_index', 0):.2f} | RoC: {r.get('return_on_capital_pct', 0):.1f}%")
    print(f"  VaR 95: ₹{report.get('var_metrics', {}).get('var_95_parametric', 0):,.2f}")
    print(f"  MC Profit Prob: {m.get('prob_of_profit', 0):.1f}% | MC Med P&L: ₹{m.get('median_final_pnl', 0):+,.0f}")
    print(f"\n  {'─'*50}")
    print(f"  Overall Quantitative Health Score: {score:.1f}%")
    status = "PASS" if score >= 75 else "WARN" if score >= 50 else "FAIL"
    print(f"  Status: {status}")
    print(f"{'='*60}\n")

    # JSON output
    if args.json:
        report["_summary"] = {
            "overall_score": score,
            "status": status,
        }
        print(json.dumps(report, indent=2, default=str))

    # HTML report
    html_path = args.html
    if not html_path:
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        date_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        html_path = str(_REPORTS_DIR / f"quantitative_validation_{date_str}.html")

    html_content = generate_html_report(report)
    Path(html_path).parent.mkdir(parents=True, exist_ok=True)
    Path(html_path).write_text(html_content, encoding="utf-8")
    print(f"  HTML report: {html_path}")

    # CI check
    if args.ci and score < 50:
        print(f"  [CI FAIL] Quantitative health score {score:.1f}% below threshold (50%)")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
