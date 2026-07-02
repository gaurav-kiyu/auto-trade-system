"""Generate a professional PPTX presentation from PRESENTATION_DECK.md.

Usage:
    python scripts/generate_pptx.py

Output:
    OPB_Presentation_v2.53.0.pptx in the project root.
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parent.parent

# ── Color scheme ──────────────────────────────────────────────────────────────
DARK_BG     = RGBColor(0x1E, 0x1E, 0x2E)   # Dark navy
ACCENT      = RGBColor(0x00, 0xD2, 0x8E)   # Green accent
ACCENT2     = RGBColor(0x00, 0x9E, 0xE6)   # Blue accent
WHITE       = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_GRAY  = RGBColor(0xBB, 0xBB, 0xBB)
DARK_TEXT    = RGBColor(0x2D, 0x2D, 0x3F)
RED_ACCENT  = RGBColor(0xFF, 0x6B, 0x6B)
YELLOW_ACC  = RGBColor(0xFF, 0xD7, 0x00)

# ── Helper functions ──────────────────────────────────────────────────────────

def _add_bg(slide, color=DARK_BG):
    """Fill slide background with solid color."""
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def _add_shape(slide, left, top, width, height, color=ACCENT, shape_type=MSO_SHAPE.RECTANGLE):
    """Add a colored rectangle."""
    shape = slide.shapes.add_shape(shape_type, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape


def _add_text_box(slide, left, top, width, height, text, font_size=14, bold=False,
                  color=WHITE, alignment=PP_ALIGN.LEFT, font_name="Calibri"):
    """Add a text box with single paragraph."""
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.bold = bold
    p.font.color.rgb = color
    p.font.name = font_name
    p.alignment = alignment
    return txBox


def _add_bullet_box(slide, left, top, width, height, items, font_size=13,
                    color=WHITE, title=None, title_size=18):
    """Add a text box with bullet points."""
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True

    if title:
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(title_size)
        p.font.bold = True
        p.font.color.rgb = ACCENT
        p.font.name = "Calibri"
        p.space_after = Pt(8)

    for i, item in enumerate(items):
        idx = i + (1 if title else 0)
        if idx >= len(tf.paragraphs):
            p = tf.add_paragraph()
        else:
            p = tf.paragraphs[idx]
        p.text = f"•  {item}"
        p.font.size = Pt(font_size)
        p.font.color.rgb = color
        p.font.name = "Calibri"
        p.space_before = Pt(2)
        p.space_after = Pt(2)
    return txBox


def _add_table(slide, left, top, width, height, headers, rows, header_color=ACCENT,
               row_colors=None):
    """Add a styled table."""
    total_rows = len(rows) + 1
    total_cols = len(headers)
    table_shape = slide.shapes.add_table(total_rows, total_cols, left, top, width, height)
    table = table_shape.table

    # Header row
    for ci, h in enumerate(headers):
        cell = table.cell(0, ci)
        cell.text = h
        for p in cell.text_frame.paragraphs:
            p.font.size = Pt(11)
            p.font.bold = True
            p.font.color.rgb = DARK_TEXT
            p.font.name = "Calibri"
            p.alignment = PP_ALIGN.CENTER
        cell.fill.solid()
        cell.fill.fore_color.rgb = header_color

    # Data rows
    for ri, row in enumerate(rows):
        bg = row_colors[ri % len(row_colors)] if row_colors else DARK_BG
        for ci, val in enumerate(row):
            cell = table.cell(ri + 1, ci)
            cell.text = str(val)
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(10)
                p.font.color.rgb = WHITE
                p.font.name = "Calibri"
                p.alignment = PP_ALIGN.CENTER
            cell.fill.solid()
            cell.fill.fore_color.rgb = bg
    return table_shape


def _add_title_bar(slide, text):
    """Add a colored title bar at the top."""
    _add_shape(slide, Inches(0), Inches(0), Inches(13.33), Inches(0.08), ACCENT)
    _add_text_box(slide, Inches(0.5), Inches(0.3), Inches(12), Inches(0.6),
                  text, font_size=26, bold=True, color=WHITE)


# ── Slide builders ────────────────────────────────────────────────────────────

def slide01_title(prs):
    """Title Slide."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank
    _add_bg(slide, DARK_BG)
    # Accent bar
    _add_shape(slide, Inches(0), Inches(3.0), Inches(13.33), Inches(0.06), ACCENT)
    # Title
    _add_text_box(slide, Inches(1), Inches(1.5), Inches(11), Inches(1.2),
                  "OPB Index Options Buying Bot\nv2.53.0",
                  font_size=40, bold=True, color=WHITE, alignment=PP_ALIGN.CENTER)
    # Subtitle
    _add_text_box(slide, Inches(1), Inches(3.3), Inches(11), Inches(0.6),
                  "Institutional-Grade Automated NSE Index Options Trading System",
                  font_size=18, color=LIGHT_GRAY, alignment=PP_ALIGN.CENTER)
    # Score
    _add_text_box(slide, Inches(2), Inches(4.5), Inches(9), Inches(0.8),
                  "Production Certified  |  Score: 8.9/10  |  June 2026",
                  font_size=16, color=ACCENT, alignment=PP_ALIGN.CENTER)
    # Bottom line
    _add_text_box(slide, Inches(1), Inches(6.5), Inches(11), Inches(0.4),
                  "NIFTY  |  BANKNIFTY  |  FINNIFTY",
                  font_size=12, color=LIGHT_GRAY, alignment=PP_ALIGN.CENTER)


def slide02_mission(prs):
    """Mission & Mandate."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_bg(slide, DARK_BG)
    _add_title_bar(slide, "Mission & Mandate")

    # Core mission
    _add_text_box(slide, Inches(0.5), Inches(1.2), Inches(12), Inches(0.8),
                  "\"Survive first. Compound second. Never reverse that order.\"",
                  font_size=22, bold=True, color=ACCENT, alignment=PP_ALIGN.CENTER)
    _add_shape(slide, Inches(4), Inches(2.0), Inches(5), Inches(0.03), YELLOW_ACC)

    # Core Objectives
    _add_bullet_box(slide, Inches(0.5), Inches(2.3), Inches(6), Inches(2.5), [
        "Capital Preservation — Max 1.5% risk per trade",
        "Consistent Returns — Algorithmic signal generation",
        "Risk-First Architecture — 15+ pre-trade risk gates",
    ], font_size=15, color=WHITE, title="Core Objectives")

    # The System
    _add_bullet_box(slide, Inches(0.5), Inches(4.5), Inches(12), Inches(2.5), [
        "Automated NSE index options: NIFTY, BANKNIFTY, FINNIFTY",
        "Three execution modes: MANUAL → PAPER → AUTO",
        "860+ config keys with 4-layer merge system",
        "3 timeframes scanned: 1m, 5m, 15m OHLCV",
    ], font_size=15, color=WHITE, title="The System")


def slide03_architecture(prs):
    """Architecture Overview."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_bg(slide, DARK_BG)
    _add_title_bar(slide, "Architecture Overview")

    _add_bullet_box(slide, Inches(0.5), Inches(1.2), Inches(6), Inches(2.5), [
        "Clean Architecture with Ports & Adapters",
        "Dependency Injection container for service wiring",
        "Deterministic State Machine for order execution",
        "Write-Ahead Journal for crash recovery",
    ], font_size=14, color=WHITE, title="Key Components")

    _add_bullet_box(slide, Inches(0.5), Inches(3.8), Inches(12), Inches(3.0), [
        "Signal Pipeline: IV Rank → Session → ML → Tier → Score",
        "Risk Service: Position sizing, drawdown guard, VIX scaling",
        "Execution Service: Order management, idempotency, reconciliation",
        "Broker Adapters: Kite, Angel, PaperBroker (abstraction layer)",
        "Market Data: yfinance, NSE API, WebSocket feeds",
    ], font_size=14, color=WHITE, title="Core Components")


def slide04_trading_workflow(prs):
    """Trading Workflow."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_bg(slide, DARK_BG)
    _add_title_bar(slide, "Trading Workflow")

    # Signal pipeline
    _add_text_box(slide, Inches(0.5), Inches(1.2), Inches(12), Inches(0.4),
                  "Signal Generation Pipeline", font_size=18, bold=True, color=ACCENT)

    steps = (
        "1. Fetch OHLCV (1m, 5m, 15m) via yfinance\n"
        "2. Compute indicators: RSI, MACD, ADX, VWAP, ATR, PCR\n"
        "3. Score signal (0-100) based on indicator alignment\n"
        "4. Apply ML win-probability adjustment (LightGBM)\n"
        "5. Apply session/regime/event-day filters\n"
        "6. Check risk gates: daily loss, drawdown, VIX, correlation\n"
        "7. Generate signal with stop-loss and targets"
    )
    _add_text_box(slide, Inches(0.5), Inches(1.7), Inches(6), Inches(3.0),
                  steps, font_size=13, color=WHITE)

    # Entry / Exit flows
    _add_text_box(slide, Inches(7), Inches(1.2), Inches(5.5), Inches(0.4),
                  "Order Lifecycle", font_size=18, bold=True, color=ACCENT2)

    entry_box = _add_shape(slide, Inches(7), Inches(1.8), Inches(5.5), Inches(1.5),
                           RGBColor(0x2A, 0x2A, 0x3E))
    tf = entry_box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "ENTRY FLOW"
    p.font.size = Pt(13)
    p.font.bold = True
    p.font.color.rgb = ACCENT
    p.font.name = "Calibri"
    p2 = tf.add_paragraph()
    p2.text = "Signal ≥ Threshold → Risk Check → Position Sizing → Order → Fill"
    p2.font.size = Pt(11)
    p2.font.color.rgb = WHITE
    p2.font.name = "Calibri"

    exit_box = _add_shape(slide, Inches(7), Inches(3.6), Inches(5.5), Inches(1.5),
                          RGBColor(0x2A, 0x2A, 0x3E))
    tf2 = exit_box.text_frame
    tf2.word_wrap = True
    p = tf2.paragraphs[0]
    p.text = "EXIT FLOW"
    p.font.size = Pt(13)
    p.font.bold = True
    p.font.color.rgb = RED_ACCENT
    p.font.name = "Calibri"
    p2 = tf2.add_paragraph()
    p2.text = "SL / Target / Trailing Stop / EOD / Manual → Position Closed"
    p2.font.size = Pt(11)
    p2.font.color.rgb = WHITE
    p2.font.name = "Calibri"


def slide05_risk(prs):
    """Risk Management Architecture."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_bg(slide, DARK_BG)
    _add_title_bar(slide, "Risk Management Architecture — 3-Layer Protection")

    # Layer 1
    _add_shape(slide, Inches(0.3), Inches(1.2), Inches(4), Inches(2.5),
              RGBColor(0x2A, 0x2A, 0x3E))
    _add_bullet_box(slide, Inches(0.5), Inches(1.3), Inches(3.6), Inches(2.3), [
        "Daily loss limit (-6% of capital)",
        "Max 1 open position at a time",
        "Max 2 trades per day",
        "VIX > 27 = all trades blocked",
        "Correlation guard (r ≥ 0.85)",
        "Event calendar (Budget/RBI/FOMC)",
        "Expiry day cutoff (13:30 IST)",
    ], font_size=11, color=WHITE, title="Layer 1: PRE-TRADE")

    # Layer 2
    _add_shape(slide, Inches(4.6), Inches(1.2), Inches(4), Inches(2.5),
              RGBColor(0x2A, 0x2A, 0x3E))
    _add_bullet_box(slide, Inches(4.8), Inches(1.3), Inches(3.6), Inches(2.3), [
        "Stop loss (entry × 0.88)",
        "Target (entry × 1.30)",
        "Trailing stop (peak × 0.93)",
        "Partial exit (entry × 1.15)",
        "Max position age (120 min)",
        "EOD squaring off (15:20 IST)",
    ], font_size=11, color=WHITE, title="Layer 2: POSITION")

    # Layer 3
    _add_shape(slide, Inches(8.9), Inches(1.2), Inches(4), Inches(2.5),
              RGBColor(0x2A, 0x2A, 0x3E))
    _add_bullet_box(slide, Inches(9.1), Inches(1.3), Inches(3.6), Inches(2.3), [
        "Hard halt (drawdown ≥ 30%)",
        "Kill file watcher (STOP_TRADING)",
        "Watchdog thread (hung scan)",
        "Circuit breaker (API failure rate)",
        "Connection pooling (SQLite WAL)",
        "Shutdown event (graceful stop)",
    ], font_size=11, color=WHITE, title="Layer 3: SYSTEM")

    # Bottom note
    _add_text_box(slide, Inches(0.5), Inches(4.0), Inches(12), Inches(0.4),
                  "All 3 layers must pass before a trade is executed.",
                  font_size=14, bold=True, color=YELLOW_ACC, alignment=PP_ALIGN.CENTER)


def slide06_performance(prs):
    """Performance & Backtesting."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_bg(slide, DARK_BG)
    _add_title_bar(slide, "Performance & Backtesting — 55 Paper Trades")

    # Overall metrics
    headers = ["Metric", "Value"]
    rows = [
        ["Total Trades", "55"],
        ["Win Rate", "54.5%"],
        ["Profit Factor", "2.54"],
        ["Total PnL", "₹3,252"],
        ["Avg PnL/Trade", "₹59.13"],
        ["Sharpe Ratio", "6.99"],
        ["Max Drawdown", "0%"],
    ]
    _add_table(slide, Inches(0.5), Inches(1.2), Inches(5.5), Inches(2.8),
               headers, rows, row_colors=[RGBColor(0x2A, 0x2A, 0x3E), RGBColor(0x35, 0x35, 0x48)])

    # By Index
    headers2 = ["Index", "Trades", "PnL", "Avg/Trade"]
    rows2 = [
        ["NIFTY", "19", "₹1,430", "₹75.26"],
        ["BANKNIFTY", "18", "₹1,062", "₹59.00"],
        ["FINNIFTY", "18", "₹760", "₹42.22"],
    ]
    _add_text_box(slide, Inches(0.5), Inches(4.2), Inches(5.5), Inches(0.4),
                  "Results by Index", font_size=16, bold=True, color=ACCENT)
    _add_table(slide, Inches(0.5), Inches(4.7), Inches(5.5), Inches(1.5),
               headers2, rows2, row_colors=[RGBColor(0x2A, 0x2A, 0x3E), RGBColor(0x35, 0x35, 0x48)])

    # Equity curve summary
    _add_text_box(slide, Inches(6.5), Inches(1.2), Inches(6), Inches(0.4),
                  "Equity Curve", font_size=16, bold=True, color=ACCENT)

    _add_bullet_box(slide, Inches(6.5), Inches(1.7), Inches(6), Inches(1.5), [
        "Started: ₹5,000",
        "Peaked: ₹5,269",
        "Closed: ₹5,150",
        "Net Gain: ₹3,252 (net profit)",
        "Peak-to-Peak Growth: Smooth upward trend",
    ], font_size=13, color=WHITE, title="Summary")

    # Drawdown summary
    _add_text_box(slide, Inches(6.5), Inches(3.7), Inches(6), Inches(0.4),
                  "Drawdown", font_size=16, bold=True, color=ACCENT)
    _add_bullet_box(slide, Inches(6.5), Inches(4.2), Inches(6), Inches(1.5), [
        "Max Drawdown: 0% (paper period)",
        "Capital base: ₹5,000",
        "Duration: 30 trading days",
        "No losing streaks exceeding 3 trades",
    ], font_size=13, color=WHITE, title="Summary")


def slide07_security(prs):
    """Security Architecture."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_bg(slide, DARK_BG)
    _add_title_bar(slide, "Security Architecture")

    headers = ["Control", "Implementation"]
    rows = [
        ["Secrets Management", "OPBUYING_* environment variables"],
        ["Secret Redaction", "_redact() helper masks in logs"],
        ["RBAC", "Role-based access control"],
        ["MFA", "TOTP Multi-Factor Authentication"],
        ["Audit Trail", "JSONL event log, thread-safe"],
        ["AI Governance Gate", "Pre-implementation validation"],
        ["Credential Storage", "Keyring, encrypted files, env vars"],
        ["Dependency Scanning", "Dependabot for CVE detection"],
    ]
    _add_table(slide, Inches(0.5), Inches(1.2), Inches(12), Inches(3.5),
               headers, rows, row_colors=[RGBColor(0x2A, 0x2A, 0x3E), RGBColor(0x35, 0x35, 0x48)])

    # Principles
    _add_bullet_box(slide, Inches(0.5), Inches(5.0), Inches(12), Inches(2.0), [
        "Fail closed: On validation error, default to blocking",
        "Defense in depth: Multiple layers of security controls",
        "Least privilege: Each component has minimal access",
    ], font_size=15, color=WHITE, title="Security Principles")


def slide08_monitoring(prs):
    """Monitoring & Observability."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_bg(slide, DARK_BG)
    _add_title_bar(slide, "Monitoring & Observability")

    headers = ["Tool", "Purpose"]
    rows = [
        ["Console Dashboard", "Real-time trading display"],
        ["Web Dashboard", "FastAPI + Jinja2 (port 8765)"],
        ["Telegram Alerts", "Push notifications for signals/errors"],
        ["Prometheus Metrics", "/metrics endpoint"],
        ["Health Checks", "DB/ML/config/disk (EOD Sunday)"],
        ["Log Rotation", "50 MB, gzip, error-only handler"],
        ["Audit Trail", "JSONL event log (all actions)"],
    ]
    _add_table(slide, Inches(0.5), Inches(1.2), Inches(7), Inches(3.0),
               headers, rows, row_colors=[RGBColor(0x2A, 0x2A, 0x3E), RGBColor(0x35, 0x35, 0x48)])

    _add_bullet_box(slide, Inches(0.5), Inches(4.5), Inches(12), Inches(2.5), [
        "Real-time signal display with strength indicators",
        "Open position monitoring with live P&L",
        "Market status and India VIX display",
        "Config editor and kill switch (admin only)",
        "RBAC user management for multi-user access",
    ], font_size=14, color=WHITE, title="Dashboard Features")


def slide09_deployment(prs):
    """Deployment Architecture."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_bg(slide, DARK_BG)
    _add_title_bar(slide, "Deployment Options")

    _add_bullet_box(slide, Inches(0.5), Inches(1.2), Inches(5.5), Inches(2.0), [
        "python -m index_app.index_trader --paper",
        "GUI launcher: OPBuying_INDEX_Launcher.exe",
        "Docker: docker compose up -d",
        "Kubernetes: k8s/deployment.yaml",
    ], font_size=15, color=WHITE, title="Run Commands")

    headers = ["Resource", "Minimum", "Recommended"]
    rows = [
        ["CPU", "2 cores", "4 cores"],
        ["RAM", "4 GB", "8 GB"],
        ["Disk", "500 MB", "1 GB"],
        ["Python", "3.10-3.19", "3.12+"],
    ]
    _add_table(slide, Inches(0.5), Inches(3.5), Inches(7), Inches(2.0),
               headers, rows, row_colors=[RGBColor(0x2A, 0x2A, 0x3E), RGBColor(0x35, 0x35, 0x48)])


def slide10_certification(prs):
    """Certification Scores."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_bg(slide, DARK_BG)
    _add_title_bar(slide, "Certification Scores")

    headers = ["Category", "Score"]
    rows = [
        ["Architecture", "8.5/10"],
        ["Maintainability", "8.0/10"],
        ["Reliability", "9.0/10"],
        ["Performance", "7.8/10"],
        ["Security", "8.5/10"],
        ["Scalability", "7.0/10"],
        ["Testability", "8.5/10"],
        ["Code Quality", "8.2/10"],
        ["Risk Management", "8.8/10"],
        ["Operational Readiness", "8.5/10"],
        ["Documentation", "7.5/10"],
        ["Future Readiness", "8.0/10"],
    ]
    _add_table(slide, Inches(0.5), Inches(1.2), Inches(6), Inches(4.5),
               headers, rows, row_colors=[RGBColor(0x2A, 0x2A, 0x3E), RGBColor(0x35, 0x35, 0x48)])

    _add_text_box(slide, Inches(7), Inches(1.5), Inches(5.5), Inches(0.5),
                  "Overall Results", font_size=20, bold=True, color=ACCENT)

    results = [
        "Weighted Final Score:  8.9 / 10",
        "Engineering Quality Index:  89%",
        "Production Readiness Index:  88%",
        "Enterprise Readiness Index:  85%",
        "",
        "Verdict:",
        "Production Certified with Minor Recommendations  ✅",
    ]
    y = 2.2
    for r in results:
        c = ACCENT if r.startswith("Verdict") or r.startswith("Production") else WHITE
        b = True if r.startswith("Verdict") or r.startswith("Production") else False
        sz = 16 if r.startswith("Weighted") else (14 if r else 8)
        _add_text_box(slide, Inches(7), Inches(y), Inches(5.5), Inches(0.4),
                      r, font_size=sz, bold=b, color=c)
        y += 0.4


def slide11_risk_register(prs):
    """Risk Register Summary."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_bg(slide, DARK_BG)
    _add_title_bar(slide, "Risk Register Summary")

    headers = ["ID", "Risk", "Severity", "Status"]
    rows = [
        ["R-01", "yfinance rate limiting", "Medium", "OPEN"],
        ["R-02", "SQLite DB fragmentation", "Low", "OPEN"],
        ["R-03", "NSE 403 (Akamai) blocks", "Medium", "ACCEPTED"],
        ["R-04", "OI snapshot cold-start", "Low", "ACCEPTED"],
        ["R-05", "Deprecated modules", "Low", "OPEN (v3.1)"],
        ["R-06", "Holiday fallback", "Low", "CLOSED"],
        ["R-07", "No encryption at rest", "Medium", "ACCEPTED"],
    ]
    _add_table(slide, Inches(0.5), Inches(1.2), Inches(12), Inches(3.0),
               headers, rows, row_colors=[RGBColor(0x2A, 0x2A, 0x3E), RGBColor(0x35, 0x35, 0x48)])

    _add_text_box(slide, Inches(0.5), Inches(4.5), Inches(12), Inches(0.4),
                  "7 Closed Risks", font_size=18, bold=True, color=ACCENT)
    _add_text_box(slide, Inches(0.5), Inches(5.0), Inches(12), Inches(1.5),
                  "Python 3.13 blocking  |  SQLite connection leak  |  Deadlock in monitor()\n"
                  "CSV write thread safety  |  Secrets in logs  |  Position persistence on crash\n"
                  "Duplicate order prevention (deterministic state machine)",
                  font_size=12, color=LIGHT_GRAY)


def slide12_recommendations(prs):
    """Recommendations & Roadmap."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_bg(slide, DARK_BG)
    _add_title_bar(slide, "Recommendations & Roadmap")

    # Completed
    _add_text_box(slide, Inches(0.5), Inches(1.2), Inches(6), Inches(0.4),
                  "✅  9 of 15 Completed", font_size=18, bold=True, color=ACCENT)

    completed = [
        "#2 Documentation consolidation",
        "#3 PaperTrader extraction (28 tests)",
        "#4 ExecutionService decomposition",
        "#5 DB migration rollback",
        "#7 Dual logger removal",
        "#8 Connection pooling",
        "#10 NSE_HOLIDAYS deduplication",
        "#12 Dead notification_service fix",
        "#13 In-memory cache cleanup",
    ]
    _add_bullet_box(slide, Inches(0.5), Inches(1.7), Inches(6), Inches(3.5),
                    completed, font_size=12, color=ACCENT)

    # Planned
    _add_text_box(slide, Inches(7), Inches(1.2), Inches(5.5), Inches(0.4),
                  "⏳  Planned for v3.1", font_size=18, bold=True, color=YELLOW_ACC)
    _add_bullet_box(slide, Inches(7), Inches(1.7), Inches(5.5), Inches(1.5), [
        "#1 Remove deprecated modules",
        "#6 Docker/K8s E2E tests",
    ], font_size=12, color=YELLOW_ACC)

    # Deferred
    _add_text_box(slide, Inches(7), Inches(3.2), Inches(5.5), Inches(0.4),
                  "🔽  Deferred (Low Priority)", font_size=18, bold=True, color=LIGHT_GRAY)
    _add_bullet_box(slide, Inches(7), Inches(3.7), Inches(5.5), Inches(1.5), [
        "E501 line length violations",
        "Config key naming standardization",
        "Stale phase/item references",
    ], font_size=12, color=LIGHT_GRAY)


def slide13_final(prs):
    """Final Readiness Conclusion."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_bg(slide, DARK_BG)
    _add_title_bar(slide, "Final Readiness Conclusion")

    # Strengths
    _add_bullet_box(slide, Inches(0.5), Inches(1.2), Inches(6), Inches(3.5), [
        "Robust architecture, clear separation of concerns",
        "15+ pre-trade risk gates",
        "Deterministic state machines, idempotency",
        "Secrets management, RBAC, MFA, audit logging",
        "2,670+ tests across all modules",
        "Docker, Prometheus, health checks, runbooks",
        "Multi-asset, multi-broker, multi-strategy ready",
    ], font_size=14, color=WHITE, title="System Strengths")

    # Verdict box
    verdict_box = _add_shape(slide, Inches(7), Inches(1.2), Inches(5.5), Inches(2.5),
                             RGBColor(0x2A, 0x2A, 0x3E))
    tf = verdict_box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "FINAL VERDICT"
    p.font.size = Pt(20)
    p.font.bold = True
    p.font.color.rgb = ACCENT
    p.font.name = "Calibri"
    p.alignment = PP_ALIGN.CENTER
    p2 = tf.add_paragraph()
    p2.text = ""
    p2.font.size = Pt(8)
    p3 = tf.add_paragraph()
    p3.text = "Production Certified"
    p3.font.size = Pt(28)
    p3.font.bold = True
    p3.font.color.rgb = ACCENT
    p3.font.name = "Calibri"
    p3.alignment = PP_ALIGN.CENTER
    p4 = tf.add_paragraph()
    p4.text = "with Minor Recommendations"
    p4.font.size = Pt(18)
    p4.font.color.rgb = LIGHT_GRAY
    p4.font.name = "Calibri"
    p4.alignment = PP_ALIGN.CENTER
    p5 = tf.add_paragraph()
    p5.text = ""
    p5.font.size = Pt(8)
    p6 = tf.add_paragraph()
    p6.text = "Score: 8.9 / 10"
    p6.font.size = Pt(16)
    p6.font.bold = True
    p6.font.color.rgb = YELLOW_ACC
    p6.font.name = "Calibri"
    p6.alignment = PP_ALIGN.CENTER

    # Next Steps
    _add_text_box(slide, Inches(7), Inches(4.0), Inches(5.5), Inches(0.4),
                  "Next Steps", font_size=16, bold=True, color=ACCENT2)
    _add_bullet_box(slide, Inches(7), Inches(4.5), Inches(5.5), Inches(2.5), [
        "Run PAPER mode (min 30 trades)",
        "Pass live readiness checker",
        "Enable broker connection (PAPER + broker)",
        "Validate with min capital (₹5,000)",
        "Gradually scale up",
    ], font_size=12, color=WHITE)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    prs = Presentation()
    prs.slide_width = Inches(13.33)
    prs.slide_height = Inches(7.5)

    output_path = ROOT / "OPB_Presentation_v2.53.0.pptx"

    # Safety check: warn before overwrite
    if output_path.exists():
        from datetime import datetime
        backup = output_path.with_suffix(f".{datetime.now().strftime('%Y%m%d_%H%M%S')}.pptx.bak")
        output_path.rename(backup)
        print(f"Existing file backed up to: {backup}")

    # Build all slides
    slide01_title(prs)
    slide02_mission(prs)
    slide03_architecture(prs)
    slide04_trading_workflow(prs)
    slide05_risk(prs)
    slide06_performance(prs)
    slide07_security(prs)
    slide08_monitoring(prs)
    slide09_deployment(prs)
    slide10_certification(prs)
    slide11_risk_register(prs)
    slide12_recommendations(prs)
    slide13_final(prs)

    prs.save(str(output_path))
    print(f"Presentation saved to: {output_path}")
    print(f"Total slides: {len(prs.slides)}")


if __name__ == "__main__":
    main()
