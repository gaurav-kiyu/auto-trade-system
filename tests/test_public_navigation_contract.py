"""Contract and Regression Tests for Public vs. Authenticated Navigation Architecture (DEF-003).

Validates:
1. Unauthenticated visitors receive public-safe navigation across desktop,
   drawer, and bottom dock without leaking internal workspace links or
   triggering unexpected 302 redirects.
2. Authenticated users receive full workspace cockpits (Signals Radar, Markets & Radar,
   Execution & PnL, Strategy & AI).
3. Administrators receive Admin & Governance navigation including /admin/inquiries.
4. Universal theme consistency across all 5 official OPB design system themes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.enterprise_dashboard import create_enterprise_dashboard


@pytest.fixture(scope="module")
def dashboard_app():
    dash = create_enterprise_dashboard(config={"ENVIRONMENT": "PAPER"})
    client = TestClient(dash.app)
    return client, dash


class TestPublicNavigationContract:
    @pytest.mark.parametrize("route", ["/contact", "/about", "/terms", "/privacy"])
    def test_unauthenticated_public_pages_render_public_nav(self, dashboard_app, route):
        client, _ = dashboard_app
        resp = client.get(route)
        assert resp.status_code == 200
        html = resp.text

        # 1. Desktop Nav Bar must contain public links
        assert "<!-- Public Navigation Row -->" in html
        assert "🏠 Overview" in html
        assert "ℹ️ About Platform" in html
        assert "💎 Pricing &amp; Plans" in html
        assert "✉️ Contact &amp; Support" in html
        assert "📜 Terms &amp; Disclosures" in html
        assert "🛡️ Privacy Policy" in html

        # 2. Desktop Nav Bar must NOT contain private workspace links
        assert "⚡ Signals Radar" not in html
        assert "📊 Markets &amp; Radar" not in html and "📊 Markets & Radar" not in html
        assert "📈 Execution &amp; PnL" not in html and "📈 Execution & PnL" not in html
        assert "🧪 Strategy &amp; AI" not in html and "🧪 Strategy & AI" not in html
        assert "⚙️ Admin &amp; Governance" not in html and "⚙️ Admin & Governance" not in html

        # 3. Mobile Drawer must render public sections only
        assert "🌐 Platform Overview" in html
        assert "🏠 Primary Cockpit" not in html
        assert "⚙️ Super Admin &amp; System Governance" not in html

        # 4. Mobile Bottom Dock must render public tabs
        assert 'title="About Platform"' in html
        assert 'title="Pricing &amp; Plans"' in html
        assert 'title="Contact Support"' in html
        assert 'title="Signals Radar"' not in html
        assert 'title="Live P&amp;L Cockpit"' not in html

    def test_authenticated_user_navigation(self, dashboard_app):
        client, dash = dashboard_app
        auth = dash._auth
        user = auth.get_user("viewer_nav_test")
        if not user:
            res = auth.create_user("viewer_nav_test", "V!ew3r_X9#qL$2mK@8vP", role="viewer")
            user = auth.get_user_by_id(res["user_id"])
        session = auth.create_session(user)

        resp = client.get("/about", cookies={"opb_session": session.token})
        assert resp.status_code == 200
        html = resp.text

        # Authenticated workspace links must be present
        assert "🏠 Command Center" in html
        assert "⚡ Signals Radar" in html
        assert "📊 Markets & Radar" in html or "📊 Markets &amp; Radar" in html
        assert "📈 Execution & PnL" in html or "📈 Execution &amp; PnL" in html
        assert "🧪 Strategy & AI" in html or "🧪 Strategy &amp; AI" in html

        # Viewer should not see admin dropdown
        assert "⚙️ Admin & Governance" not in html

        # Mobile Bottom Dock must display authenticated tabs
        assert 'title="Signals Radar"' in html
        assert 'title="Live P&L Cockpit"' in html or 'title="Live P&amp;L Cockpit"' in html

    def test_authenticated_admin_navigation_includes_inquiries(self, dashboard_app):
        client, dash = dashboard_app
        auth = dash._auth
        user = auth.get_user("admin_nav_test")
        if not user:
            res = auth.create_user("admin_nav_test", "Adm!n_X9#qL$2mK@8vP", role="admin")
            user = auth.get_user_by_id(res["user_id"])
        session = auth.create_session(user)

        resp = client.get("/about", cookies={"opb_session": session.token})
        assert resp.status_code == 200
        html = resp.text

        # Admin dropdown present
        assert "⚙️ Admin & Governance" in html or "⚙️ Admin &amp; Governance" in html

        # Inquiries management link present in desktop admin dropdown and mobile drawer
        assert "/admin/inquiries" in html
        assert "📬 Contact Inquiries & Support" in html or "📬 Contact Inquiries &amp; Support" in html

    def test_all_five_themes_present_in_selector(self, dashboard_app):
        client, _ = dashboard_app
        resp = client.get("/contact")
        assert resp.status_code == 200
        html = resp.text

        # All 5 themes defined in OPB 2026 design system
        expected_themes = [
            "dark-cyber",
            "dracula-purple",
            "ivory-gold",
            "midnight-slate",
            "emerald-matrix",
        ]
        for theme in expected_themes:
            assert f'value="{theme}"' in html, f"Theme '{theme}' missing from theme selector"
