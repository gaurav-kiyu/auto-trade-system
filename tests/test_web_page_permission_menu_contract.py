"""Ensure enterprise navigation visibility matches page-level RBAC gates."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAV = ROOT / "templates" / "enterprise" / "_nav.html"
PAGES = ROOT / "core" / "enterprise_dashboard" / "routes" / "pages.py"


def test_governance_menu_matches_toggle_strategies_page_gate():
    nav = NAV.read_text(encoding="utf-8")
    pages = PAGES.read_text(encoding="utf-8")
    assert '{% if can_toggle_strategies %}<a href="/governance"' in nav
    assert 'dashboard, "toggle_strategies"' in pages


def test_trade_copier_menu_matches_broker_management_boundary():
    nav = NAV.read_text(encoding="utf-8")
    pages = PAGES.read_text(encoding="utf-8")
    assert nav.count('{% if can_manage_brokers %}<a href="/trade-copier"') == 2
    # Trade Copier remains an admin-only page; menu is hidden for users without broker-management privilege.
    assert 'name="trade_copier.html"' in pages
    assert 'user, err = _require_admin_page(request)' in pages


def test_ab_tester_menu_matches_deploy_models_page_gate():
    nav = NAV.read_text(encoding="utf-8")
    pages = PAGES.read_text(encoding="utf-8")
    assert '{% if can_deploy_models %}<a href="/ab-tester"' in nav
    assert 'dashboard, "deploy_models"' in pages


def test_pricing_and_whats_new_pages_match_menu_permissions():
    nav = NAV.read_text(encoding="utf-8")
    pages = PAGES.read_text(encoding="utf-8")
    assert '{% if can_modify_config %}<a href="/pricing-plans"' in nav
    assert 'dashboard, "modify_config", admin_only=True' in pages
    assert '{% if can_view_logs %}<a href="/whats-new"' in nav
    assert 'dashboard, "view_logs"' in pages


def test_admin_signals_page_accepts_only_its_menu_permissions():
    nav = NAV.read_text(encoding="utf-8")
    pages = PAGES.read_text(encoding="utf-8")
    assert '{% if can_modify_config or can_view_logs %}<a href="/admin/signals"' in nav
    assert 'for perm in ("modify_config", "view_logs")' in pages
