"""
Enhanced Reporting — PDF Trade Report Generator (Phase 6).

Generates a multi-section PDF report from trades.db using ReportLab.
Includes:
  - Summary statistics (win rate, profit factor, Sharpe, drawdown)
  - Equity curve bar chart
  - Breakdowns by score bin, index, exit reason
  - Actionable insights

Usage:
    from core.report_generator import generate_pdf_report
    path = generate_pdf_report("trades.db", days=30, output_path="reports/daily.pdf")

    # CLI:
    python -m core.report_generator --days 30 --mode PAPER

Config keys (all optional — safe defaults built in)
---------------------------------------------------
  report_output_dir  : str   default "reports"
  report_default_days: int   default 30
  report_mode        : str   default "PAPER"  (PAPER | LIVE | ALL)
"""
from __future__ import annotations

import argparse
import datetime
import logging
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)

_DEFAULT_DB  = "trades.db"
_DEFAULT_DIR = "reports"


# ── ReportLab helpers ─────────────────────────────────────────────────────────

def _rl_imports():
    """Lazy import of ReportLab — raises ImportError with a helpful message if missing."""
    try:
        from reportlab.graphics import renderPDF
        from reportlab.graphics.shapes import Drawing, Line, Rect, String
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            HRFlowable,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
        return (colors, A4, getSampleStyleSheet, ParagraphStyle, cm,
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
                Drawing, Rect, Line, String, renderPDF)
    except ImportError as exc:
        raise ImportError(
            "reportlab is required for PDF reports: pip install reportlab"
        ) from exc


# ── Colour palette ─────────────────────────────────────────────────────────────

_GREEN  = (0.18, 0.69, 0.31)
_RED    = (0.93, 0.25, 0.22)
_BLUE   = (0.20, 0.44, 0.84)
_GREY   = (0.55, 0.55, 0.55)
_BLACK  = (0.08, 0.08, 0.08)
_LGREY  = (0.93, 0.93, 0.93)


def _rl_color(r, g, b):
    from reportlab.lib.colors import Color
    return Color(r, g, b)


# ── Equity curve chart (pure ReportLab, no matplotlib) ───────────────────────

def _equity_curve_drawing(trades: list[dict], width: float = 420, height: float = 120) -> Any:
    """Return a ReportLab Drawing containing a simple equity curve bar chart."""
    from reportlab.graphics.shapes import Drawing, Line, Rect, String
    from reportlab.lib.colors import Color

    net_pnls = [float(t.get("net_pnl") or 0) for t in trades]
    if not net_pnls:
        d = Drawing(width, height)
        d.add(String(width / 2, height / 2, "No trade data", fontSize=9, fillColor=Color(0.5, 0.5, 0.5)))
        return d

    cum = []
    running = 0.0
    for p in net_pnls:
        running += p
        cum.append(running)

    min_v = min(cum + [0.0])
    max_v = max(cum + [0.0])
    span  = max_v - min_v or 1.0
    pad_l, pad_r, pad_t, pad_b = 8, 8, 10, 20
    chart_w = width - pad_l - pad_r
    chart_h = height - pad_t - pad_b
    zero_y  = pad_b + ((-min_v) / span) * chart_h

    d = Drawing(width, height)

    # Zero baseline
    d.add(Line(pad_l, zero_y, pad_l + chart_w, zero_y,
               strokeColor=Color(*_GREY), strokeWidth=0.4, strokeDashArray=[2, 2]))

    # Bars
    n = len(cum)
    bar_w = max(1.0, chart_w / max(n, 1) - 1)
    for i, val in enumerate(cum):
        x = pad_l + i * (chart_w / n)
        y_raw = (val - min_v) / span * chart_h + pad_b
        bar_h = y_raw - zero_y
        col = Color(*_GREEN) if val >= 0 else Color(*_RED)
        if bar_h >= 0:
            d.add(Rect(x, zero_y, bar_w, bar_h, fillColor=col, strokeColor=None))
        else:
            d.add(Rect(x, zero_y + bar_h, bar_w, -bar_h, fillColor=col, strokeColor=None))

    # Axis labels
    d.add(String(pad_l, pad_b - 12, f"₹{min_v:+.0f}", fontSize=7, fillColor=Color(*_GREY)))
    d.add(String(pad_l + chart_w - 30, pad_b - 12, f"₹{max_v:+.0f}", fontSize=7, fillColor=Color(*_GREY)))
    d.add(String(pad_l, zero_y + 1, "0", fontSize=7, fillColor=Color(*_GREY)))

    return d


# ── Table builders ─────────────────────────────────────────────────────────────

def _metric_table(m: dict[str, Any], styles):
    """Two-column table of summary metrics."""
    from reportlab.lib.colors import Color
    from reportlab.platypus import Table, TableStyle

    def _fmt(v):
        if isinstance(v, float):
            return f"{v:,.2f}"
        if isinstance(v, int):
            return f"{v:,}"
        return str(v)

    rows = [
        ("Trades", _fmt(m.get("trades", 0))),
        ("Win Rate", f"{m.get('win_rate', 0):.1f}%"),
        ("Winners / Losers", f"{m.get('winners', 0)} / {m.get('losers', 0)}"),
        ("Avg Win", f"₹{m.get('avg_win', 0):,.2f}"),
        ("Avg Loss", f"₹{m.get('avg_loss', 0):,.2f}"),
        ("Win/Loss Ratio", _fmt(m.get("win_loss_ratio", 0))),
        ("Expectancy/Trade", f"₹{m.get('expectancy', 0):+,.2f}"),
        ("Profit Factor", _fmt(m.get("profit_factor", 0))),
        ("Total Net PnL", f"₹{m.get('total_net_pnl', 0):+,.2f}"),
        ("Largest Win", f"₹{m.get('largest_win', 0):+,.2f}"),
        ("Largest Loss", f"₹{m.get('largest_loss', 0):+,.2f}"),
        ("Sharpe (per trade)", _fmt(m.get("sharpe_per_trade", 0))),
        ("Max Drawdown", f"₹{m.get('max_drawdown', 0):,.2f}"),
        ("Recovery Factor", _fmt(m.get("recovery_factor", 0))),
        ("Max Consec Wins", str(m.get("max_consec_wins", 0))),
        ("Max Consec Losses", str(m.get("max_consec_losses", 0))),
    ]

    col_w = [180, 120]
    tbl = Table([("Metric", "Value")] + rows, colWidths=col_w)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0),  Color(*_BLUE)),
        ("TEXTCOLOR",   (0, 0), (-1, 0),  Color(1, 1, 1)),
        ("FONTNAME",    (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [Color(*_LGREY), Color(1, 1, 1)]),
        ("GRID",        (0, 0), (-1, -1), 0.3, Color(*_GREY)),
        ("TOPPADDING",  (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return tbl


def _monte_carlo_table(result: Any) -> Any:
    """Two-column table of MonteCarloResult fields."""
    from reportlab.lib.colors import Color
    from reportlab.platypus import Table, TableStyle

    rows = [
        ("Simulations", f"{result.n_simulations:,}"),
        ("Trades analysed", f"{result.n_trades:,}"),
        ("Final P&L — P5",    f"₹{result.p5_final_pnl:+,.0f}"),
        ("Final P&L — Median", f"₹{result.median_final_pnl:+,.0f}"),
        ("Final P&L — P95",   f"₹{result.p95_final_pnl:+,.0f}"),
        ("Mean Final P&L",    f"₹{result.mean_final_pnl:+,.0f}"),
        ("Max Drawdown — Median", f"₹{result.median_max_drawdown:,.0f}"),
        ("Max Drawdown — P95 (worst)", f"₹{result.p95_max_drawdown:,.0f}"),
        ("Probability of Profit", f"{result.prob_of_profit * 100:.1f}%"),
        ("Worst Losing Streak — P95", f"{result.worst_case_streak_p95} trades"),
        ("Sharpe — Median",  f"{result.median_sharpe:.4f}"),
        ("Sharpe — P5",      f"{result.p5_sharpe:.4f}"),
    ]

    col_w = [200, 120]
    tbl = Table([("Monte Carlo Metric", "Value")] + rows, colWidths=col_w)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0),  Color(*_BLUE)),
        ("TEXTCOLOR",   (0, 0), (-1, 0),  Color(1, 1, 1)),
        ("FONTNAME",    (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [Color(*_LGREY), Color(1, 1, 1)]),
        ("GRID",        (0, 0), (-1, -1), 0.3, Color(*_GREY)),
        ("TOPPADDING",  (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return tbl


def _breakdown_table(data: dict[str, dict], header: str) -> Any:
    """Generic breakdown table (regime / score / index / exit reason)."""
    from reportlab.lib.colors import Color
    from reportlab.platypus import Table, TableStyle

    if not data:
        return None
    col_headers = ("Category", "Trades", "Win%", "Avg PnL", "Total PnL")
    rows = [col_headers]
    for cat, d in sorted(data.items()):
        rows.append((
            cat,
            str(d.get("trades", 0)),
            f"{d.get('win_rate', 0):.1f}%",
            f"₹{d.get('avg_pnl', 0):+,.2f}",
            f"₹{d.get('total_pnl', 0):+,.2f}",
        ))
    tbl = Table(rows, colWidths=[120, 50, 55, 70, 75])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),  Color(*_BLUE)),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  Color(1, 1, 1)),
        ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, -1), 7.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [Color(*_LGREY), Color(1, 1, 1)]),
        ("GRID",         (0, 0), (-1, -1), 0.3, Color(*_GREY)),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
    ]))
    return tbl


# ── Public API ────────────────────────────────────────────────────────────────

def generate_pdf_report(
    db_path: str = _DEFAULT_DB,
    *,
    days: int = 30,
    mode: str = "ALL",
    output_path: str | Path | None = None,
    cfg: dict[str, Any] | None = None,
) -> str:
    """
    Generate a PDF trade performance report.

    Args:
        db_path     : Path to trades.db.
        days        : Look-back window in days (0 = all time).
        mode        : Trade mode filter — "PAPER", "LIVE", or "ALL".
        output_path : Destination file path.  Auto-generated if None.
        cfg         : Bot config dict (for output_dir override).

    Returns:
        Absolute path of the generated PDF.

    Raises:
        ImportError  if reportlab is not installed.
        RuntimeError if no trades are available.
    """
    c = cfg or {}
    out_dir = Path(c.get("report_output_dir", _DEFAULT_DIR))
    out_dir.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        stamp = now_ist().strftime("%Y%m%d_%H%M%S")
        output_path = out_dir / f"trade_report_{stamp}.pdf"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Load data ────────────────────────────────────────────────────────────
    from core.performance_metrics import (
        compute_metrics,
        generate_insights,
        load_trades,
        metrics_by_exit_reason,
        metrics_by_index,
        metrics_by_regime,
        metrics_by_score_bin,
    )

    load_mode = None if mode.upper() == "ALL" else mode.upper()
    trades = load_trades(str(db_path), mode=load_mode, days=days if days > 0 else None)

    if not trades:
        raise RuntimeError(f"No trades found in {db_path} (mode={mode}, days={days})")

    m          = compute_metrics(trades)
    by_score   = metrics_by_score_bin(trades)
    by_index   = metrics_by_index(trades)
    by_reason  = metrics_by_exit_reason(trades)
    by_regime  = metrics_by_regime(trades)
    insights   = generate_insights(trades)

    # ── Build PDF ────────────────────────────────────────────────────────────
    (colors, A4, getSampleStyleSheet, ParagraphStyle, cm,
     SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
     Drawing, Rect, Line, String, renderPDF) = _rl_imports()

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=16, spaceAfter=4,
                         textColor=_rl_color(*_BLACK))
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11, spaceAfter=3,
                         textColor=_rl_color(*_BLUE), spaceBefore=12)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=8.5,
                           leading=13, spaceAfter=2)
    insight_style = ParagraphStyle("insight", parent=styles["Normal"], fontSize=8,
                                    leading=12, leftIndent=8, spaceBefore=2)

    period_label = f"Last {days} days" if days > 0 else "All time"
    title_date   = now_ist().strftime("%d %b %Y %H:%M")

    story = []

    # Title
    story.append(Paragraph("OPB Index Options — Trade Performance Report", h1))
    story.append(Paragraph(
        f"Generated: {title_date} &nbsp;|&nbsp; Period: {period_label} &nbsp;|&nbsp; Mode: {mode}",
        body,
    ))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_rl_color(*_GREY), spaceAfter=8))

    # Summary metrics
    story.append(Paragraph("Summary Metrics", h2))
    story.append(_metric_table(m, styles))
    story.append(Spacer(1, 10))

    # Equity curve
    story.append(Paragraph("Cumulative Net PnL — Equity Curve", h2))
    story.append(_equity_curve_drawing(trades, width=440, height=130))
    story.append(Spacer(1, 10))

    # Breakdowns
    for section_title, section_data in [
        ("Score Bin Breakdown", by_score),
        ("Index Breakdown", by_index),
        ("Exit Reason Breakdown", by_reason),
        ("Regime Breakdown", by_regime),
    ]:
        tbl = _breakdown_table(section_data, section_title)
        if tbl is not None:
            story.append(Paragraph(section_title, h2))
            story.append(tbl)
            story.append(Spacer(1, 6))

    # Insights
    story.append(Paragraph("Actionable Insights", h2))
    for ins in insights:
        story.append(Paragraph(f"• {ins}", insight_style))

    # Monte Carlo Robustness Analysis (optional — graceful skip if unavailable)
    try:
        from core.monte_carlo import plot_equity_band as _mc_plot
        from core.monte_carlo import run_simulation as _mc_run
        _mc_pnls = [float(t.get("net_pnl") or 0) for t in trades if t.get("net_pnl") is not None]
        if len(_mc_pnls) >= 2:
            _mc_n    = int(c.get("monte_carlo_n_simulations", 1000))
            _mc_seed = int(c.get("monte_carlo_seed", 42))
            _mc_res  = _mc_run(_mc_pnls, n_simulations=_mc_n, seed=_mc_seed)

            story.append(Spacer(1, 10))
            story.append(HRFlowable(width="100%", thickness=0.3, color=_rl_color(*_LGREY)))
            story.append(Paragraph(
                f"Monte Carlo Robustness Analysis ({_mc_n:,} simulations)", h2
            ))
            story.append(_monte_carlo_table(_mc_res))
            story.append(Spacer(1, 6))

            # ASCII equity band — rendered in Courier so columns align
            _mc_chart = _mc_plot(_mc_res, width=68, height=12)
            from reportlab.lib.styles import ParagraphStyle as _PS
            from reportlab.platypus import Preformatted
            _mc_style = _PS(
                "mc_chart",
                fontName="Courier",
                fontSize=6.5,
                leading=8,
                spaceBefore=4,
                spaceAfter=4,
                leftIndent=0,
            )
            story.append(Preformatted(_mc_chart, _mc_style))
    except (ValueError, TypeError, AttributeError, KeyError, ImportError) as _mc_exc:
        _log.warning("[REPORT] Monte Carlo section skipped: %s", _mc_exc)
    except Exception as _mc_exc:
        _log.warning("[REPORT] Monte Carlo section skipped (unexpected: %s): %s", type(_mc_exc).__name__, _mc_exc)

    # Benchmark Comparison — ^NSEI Buy-and-Hold (optional — graceful skip if unavailable)
    try:
        if c.get("benchmark_enabled", True):
            from core.benchmark import compute_alpha_metrics as _bm_alpha
            from core.benchmark import fetch_benchmark as _bm_fetch

            # Derive date range from trade timestamps
            _ts_list = [float(t["entry_ts"]) for t in trades if t.get("entry_ts") is not None]
            if _ts_list:
                _bm_start = datetime.date.fromtimestamp(min(_ts_list))
                _bm_end   = datetime.date.fromtimestamp(max(_ts_list))
            else:
                _bm_start = now_ist().date()
                _bm_end   = now_ist().date()

            _bm_symbol    = str(c.get("benchmark_symbol", "^NSEI"))
            _bm_risk_free = float(c.get("benchmark_risk_free_rate", 0.065))
            _bm_cache_hrs = int(c.get("benchmark_cache_hours", 24))

            bm = _bm_fetch(
                _bm_symbol,
                _bm_start,
                _bm_end,
                risk_free_rate=_bm_risk_free,
                cache_hours=_bm_cache_hrs,
            )

            _strat_ret_pct = float(m.get("total_return_pct", 0.0))
            _strat_dd_pct  = float(m.get("max_drawdown_pct", 0.0))

            alpha_m = _bm_alpha(
                strategy_return_pct=_strat_ret_pct,
                strategy_max_dd_pct=_strat_dd_pct,
                benchmark=bm,
                mc_pnls=[],
                benchmark_total_pnl=0.0,
            )

            story.append(Spacer(1, 10))
            story.append(HRFlowable(width="100%", thickness=0.3, color=_rl_color(*_LGREY)))
            story.append(Paragraph(
                f"Benchmark Comparison ({_bm_symbol} Buy-and-Hold)", h2
            ))

            if bm is None:
                story.append(Paragraph(
                    "Benchmark data unavailable (offline or cache miss).",
                    body,
                ))
            else:
                _bm_rows = [
                    ("Metric",                    "Strategy",                              "Benchmark"),
                    ("Total Return",              f"{_strat_ret_pct:+.2f}%",               f"{bm.total_return_pct:+.2f}%"),
                    ("Alpha (Strategy − Bench)",  f"{alpha_m.alpha_pct:+.2f}%",            "—"),
                    ("Information Ratio",         f"{alpha_m.information_ratio:.3f}",      "—"),
                    ("Drawdown Ratio (S/B)",      f"{alpha_m.drawdown_ratio:.3f}",         "—"),
                    ("Max Drawdown",              f"{_strat_dd_pct:.2f}%",                 f"{bm.max_drawdown_pct:.2f}%"),
                    ("Annualised Return",         "—",                                     f"{bm.annualized_return_pct:+.2f}%"),
                    ("Benchmark Sharpe",          "—",                                     f"{bm.sharpe_ratio:.3f}"),
                    ("Benchmark Volatility",      "—",                                     f"{bm.volatility_pct:.2f}%"),
                    ("Data Source",               "—",                                     bm.data_source),
                    ("Period",                    f"{_bm_start} → {_bm_end}",              f"{_bm_start} → {_bm_end}"),
                ]
                from reportlab.lib.colors import Color as _BmColor
                _bm_tbl = Table(_bm_rows, colWidths=[170, 100, 100])
                _bm_tbl.setStyle(TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, 0),  _BmColor(*_BLUE)),
                    ("TEXTCOLOR",     (0, 0), (-1, 0),  _BmColor(1, 1, 1)),
                    ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
                    ("FONTSIZE",      (0, 0), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_BmColor(*_LGREY), _BmColor(1, 1, 1)]),
                    ("GRID",          (0, 0), (-1, -1), 0.3, _BmColor(*_GREY)),
                    ("TOPPADDING",    (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                ]))
                story.append(_bm_tbl)
                story.append(Spacer(1, 6))
    except (ValueError, TypeError, AttributeError, KeyError, ImportError, ConnectionError, TimeoutError, OSError) as _bm_exc:
        _log.warning("[REPORT] Benchmark section skipped: %s", _bm_exc)
    except Exception as _bm_exc:
        _log.warning("[REPORT] Benchmark section skipped (unexpected: %s): %s", type(_bm_exc).__name__, _bm_exc)

    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=0.3, color=_rl_color(*_LGREY)))
    story.append(Paragraph(
        f"OPB Report — {m['trades']} trades — generated {title_date}",
        ParagraphStyle("footer", parent=styles["Normal"], fontSize=7,
                        textColor=_rl_color(*_GREY), spaceBefore=4),
    ))

    doc.build(story)
    _log.info("[REPORT] PDF written to %s (%d trades)", output_path, len(trades))
    return str(output_path.resolve())


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> None:
    p = argparse.ArgumentParser(description="Generate OPB PDF trade report")
    p.add_argument("--db",   default=_DEFAULT_DB,  help="Path to trades.db")
    p.add_argument("--days", default=30, type=int,  help="Look-back days (0 = all)")
    p.add_argument("--mode", default="ALL",         help="PAPER | LIVE | ALL")
    p.add_argument("--out",  default=None,          help="Output file path")
    args = p.parse_args()
    path = generate_pdf_report(args.db, days=args.days, mode=args.mode, output_path=args.out)
    print(f"Report written: {path}")


if __name__ == "__main__":
    _cli()
