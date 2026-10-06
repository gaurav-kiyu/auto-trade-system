"""
OPB v2.60 — Total Row, Theme Engine, Typography & Final Governance Audit Test Suite
Verifies:
1. Universal .opb-table-total-row component in static/opb_design_system.css
2. Presence and mathematical correctness of TOTAL rows across all applicable quantitative tables
3. Rate recalculation invariants (NEVER average percentages; win rates recalculated from aggregate counts)
4. Weighted average score calculations
5. Complete theme audit for all 5 themes: dark-cyber, emerald-matrix, dracula-purple, ivory-gold, midnight-slate
6. Prevention of accidental hardcoded color bypasses breaking light/dark themes
7. Tabular numerals (tabular-nums) enforcement on financial/statistical table cells
8. Authoritative production safety invariants (PAPER, SIGNAL_ONLY, LIVE_TRADING_LOCKOUT=True, FULL_AUTO_ALLOWED=False)
"""

import os
import re
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_design_system_total_row_component():
    """Verify universal .opb-table-total-row component is defined in opb_design_system.css."""
    css_path = os.path.join(ROOT_DIR, "static", "opb_design_system.css")
    assert os.path.exists(css_path), f"Missing design system: {css_path}"
    with open(css_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert ".opb-table-total-row" in content
    assert "tabular-nums" in content
    assert "var(--bg-card-hover)" in content
    assert "var(--border-color)" in content
    assert "var(--text-primary)" in content


def test_theme_engine_all_five_themes_registered():
    """Verify all 5 institutional fintech themes are registered in static/theme_engine.js."""
    engine_path = os.path.join(ROOT_DIR, "static", "theme_engine.js")
    assert os.path.exists(engine_path), f"Missing theme engine: {engine_path}"
    with open(engine_path, "r", encoding="utf-8") as f:
        content = f.read()

    expected_themes = [
        "dark-cyber",
        "dracula-purple",
        "ivory-gold",
        "midnight-slate",
        "emerald-matrix",
    ]
    for theme in expected_themes:
        assert f"'{theme}'" in content or f'"{theme}"' in content, f"Theme '{theme}' missing from theme engine"

    # Verify light themes have light background tokens and dark themes have dark background tokens
    assert "'--bg-primary': '#080c14'" in content  # dark-cyber
    assert "'--bg-primary': '#faf7fc'" in content  # dracula-purple
    assert "'--bg-primary': '#f5f0e6'" in content  # ivory-gold
    assert "'--bg-primary': '#f6f8fb'" in content  # midnight-slate
    assert "'--bg-primary': '#020d07'" in content  # emerald-matrix


def test_admin_signals_total_rows():
    """Verify templates/enterprise/admin_signals.html includes TOTAL rows with mathematical recalculation."""
    tmpl_path = os.path.join(ROOT_DIR, "templates", "enterprise", "admin_signals.html")
    assert os.path.exists(tmpl_path)
    with open(tmpl_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Category table TOTAL row
    assert "categoryTableBody" in content
    assert "totSignals" in content
    assert "totWinRate = totRes > 0 ? `${((totT1 / totRes) * 100).toFixed(1)}%` : 'N/A (0 resolved)'" in content
    assert "totAvgScore = totSignals > 0 ? (weightedScoreSum / totSignals).toFixed(1) : '0'" in content
    assert "opb-table-total-row" in content
    assert "TOTAL" in content

    # System Signals Audit Table TOTAL row
    assert "signalsTableBody" in content
    assert "totSigCount" in content
    assert "totActiveCount" in content
    assert "totT1Count" in content
    assert "avgScoreVal" in content
    assert "avgPnlVal" in content


def test_live_pnl_render_rows_total_row():
    """Verify templates/enterprise/live_pnl.html includes dynamic TOTAL row across all 5 breakdown tables."""
    tmpl_path = os.path.join(ROOT_DIR, "templates", "enterprise", "live_pnl.html")
    assert os.path.exists(tmpl_path)
    with open(tmpl_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "renderRows(dict, isDir = false)" in content
    assert "totTrades" in content
    assert "totWins" in content
    assert "totLosses" in content
    assert "totPnlSum" in content
    assert "aggWinRate = totTrades > 0 ? (totWins / totTrades) : 0" in content
    assert "aggAvgPnl = totTrades > 0 ? (totPnlSum / totTrades) : 0" in content
    assert "opb-table-total-row" in content


def test_performance_regime_total_row():
    """Verify templates/enterprise/performance.html includes dynamic TOTAL row on regime breakdown."""
    tmpl_path = os.path.join(ROOT_DIR, "templates", "enterprise", "performance.html")
    assert os.path.exists(tmpl_path)
    with open(tmpl_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "regimeTable" in content
    assert "totTrades" in content
    assert "totPnlSum" in content
    assert "aggWinRate = totTrades > 0 ? (totWins / totTrades * 100).toFixed(1) + '%' : '-'" in content
    assert "aggAvgPnl = totTrades > 0 ? (totPnlSum / totTrades).toFixed(2) : '0.00'" in content
    assert "opb-table-total-row" in content


def test_portfolio_analyzer_total_row():
    """Verify templates/enterprise/admin_portfolio_analyzer.html includes dynamic TOTAL row."""
    tmpl_path = os.path.join(ROOT_DIR, "templates", "enterprise", "admin_portfolio_analyzer.html")
    assert os.path.exists(tmpl_path)
    with open(tmpl_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "stock-table-body" in content
    assert "totalQty = data.stock_guidance.reduce" in content
    assert "totTr.className = 'opb-table-total-row'" in content
    assert "TOTAL" in content


def test_sector_radar_total_row():
    """Verify templates/enterprise/sector_radar.html includes dynamic TOTAL row with turnover & weighted change."""
    tmpl_path = os.path.join(ROOT_DIR, "templates", "enterprise", "sector_radar.html")
    assert os.path.exists(tmpl_path)
    with open(tmpl_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "sectorTableBody" in content
    assert "totTurnover = sectors.reduce" in content
    assert "weightedDayChangeSum = sectors.reduce" in content
    assert "opb-table-total-row" in content
    assert "TOTAL" in content


def test_margin_radar_total_row():
    """Verify templates/enterprise/margin_radar.html includes dynamic TOTAL row with aggregated utilization."""
    tmpl_path = os.path.join(ROOT_DIR, "templates", "enterprise", "margin_radar.html")
    assert os.path.exists(tmpl_path)
    with open(tmpl_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "marginTableBody" in content
    assert "totMargin = brokers.reduce" in content
    assert "totUsed = brokers.reduce" in content
    assert "aggUtilPct = totMargin > 0 ? ((totUsed / totMargin) * 100).toFixed(1) : '0'" in content
    assert "opb-table-total-row" in content
    assert "TOTAL" in content


def test_fii_dii_radar_total_row():
    """Verify templates/enterprise/fii_dii_radar.html includes dynamic TOTAL row for institutional positioning."""
    tmpl_path = os.path.join(ROOT_DIR, "templates", "enterprise", "fii_dii_radar.html")
    assert os.path.exists(tmpl_path)
    with open(tmpl_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "participantTableBody" in content
    assert "totIndexFut = data.participants.reduce" in content
    assert "totIndexCall = data.participants.reduce" in content
    assert "totIndexPut = data.participants.reduce" in content
    assert "totStockFut = data.participants.reduce" in content
    assert "opb-table-total-row" in content
    assert "TOTAL" in content


def test_user_signals_total_row():
    """Verify templates/enterprise/user_signals.html includes dynamic TOTAL row on user feed table."""
    tmpl_path = os.path.join(ROOT_DIR, "templates", "enterprise", "user_signals.html")
    assert os.path.exists(tmpl_path)
    with open(tmpl_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "userSignalsBody" in content
    assert "totSigCount = signalsCache.length" in content
    assert "avgScoreVal" in content
    assert "opb-table-total-row" in content
    assert "TOTAL" in content


def test_capacity_and_intelligence_total_rows():
    """Verify capacity.html and intelligence.html include dynamic TOTAL rows."""
    cap_path = os.path.join(ROOT_DIR, "templates", "enterprise", "capacity.html")
    with open(cap_path, "r", encoding="utf-8") as f:
        cap_c = f.read()
    assert "forecastsTableBody" in cap_c
    assert "totCurrentSize = data.forecasts.reduce" in cap_c
    assert "opb-table-total-row" in cap_c

    intel_path = os.path.join(ROOT_DIR, "templates", "enterprise", "intelligence.html")
    with open(intel_path, "r", encoding="utf-8") as f:
        intel_c = f.read()
    assert "incidentByType" in intel_c
    assert "incidentBySeverity" in intel_c
    assert "opb-table-total-row" in intel_c


def test_no_hardcoded_button_active_black_text():
    """Verify _nav.html and dashboard.html use dynamic var(--btn-primary-text) rather than static #000000."""
    nav_path = os.path.join(ROOT_DIR, "templates", "enterprise", "_nav.html")
    with open(nav_path, "r", encoding="utf-8") as f:
        nav_c = f.read()
    assert ".opb-theme-pill:active" in nav_c
    assert "var(--btn-primary-text, #000000)" in nav_c

    dash_path = os.path.join(ROOT_DIR, "templates", "enterprise", "dashboard.html")
    with open(dash_path, "r", encoding="utf-8") as f:
        dash_c = f.read()
    assert ".mobile-action-btn:active" in dash_c
    assert "var(--btn-primary-text, #000000)" in dash_c


def test_pricing_plans_light_theme_contrast():
    """Verify pricing_plans.html button text colors use dynamic var(--btn-primary-text)."""
    pp_path = os.path.join(ROOT_DIR, "templates", "enterprise", "pricing_plans.html")
    with open(pp_path, "r", encoding="utf-8") as f:
        pp_c = f.read()

    assert "var(--btn-primary-text" in pp_c
    # Verify no accidental static white text on submit buttons
    assert 'style="background:var(--success-color, #22c55e);color:#ffffff;font-weight:700;"' not in pp_c
    assert 'style="flex:1;background:var(--success-color, #22c55e);color:#ffffff;font-weight:600;"' not in pp_c


def test_production_safety_invariants_preserved():
    """Verify trading safety parameters remain locked to PAPER/SIGNAL_ONLY."""
    import json
    cfg_path = os.path.join(ROOT_DIR, "json", "index_config.defaults.json")
    assert os.path.exists(cfg_path), f"Missing index config defaults: {cfg_path}"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    assert cfg.get("EXECUTION_MODE") in ("SIGNAL_ONLY", "PAPER", "PAPER_TRADING")
    assert cfg.get("LIVE_TRADING_LOCKOUT") is True or cfg.get("live_trading_lockout_enabled") is True
    assert (cfg.get("full_auto_allowed") is False or cfg.get("FULL_AUTO_ALLOWED") is False)

