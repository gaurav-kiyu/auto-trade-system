"""Global privilege-based navigation initialization and consistency test suite.

Validates that:
1. Canonical RBAC capability matrix is deterministically generated for all roles.
2. First-render invariant: /change-password immediately renders identical privilege
   navigation as subsequent routes (zero false hiding for admin, zero privilege leakage).
3. Centralized TemplateResponse defensive wrapper auto-injects canonical context and
   attaches strict Cache-Control headers.
4. Fail-closed defaults: unauthenticated/None users receive boolean False for all capabilities.
5. Zero authorization bypass: non-admin roles are strictly blocked from admin routes/APIs.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.auth.handler import AuthHandler
from core.auth.permissions import Permission, Role, get_role_permissions, is_super_admin_identity
from core.enterprise_dashboard import EnterpriseDashboard
from core.enterprise_dashboard.routes.pages import _page_context


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def auth_db_path() -> Generator[str, None, None]:
    tmp = tempfile.mktemp(suffix=".db")
    yield tmp
    try:
        os.unlink(tmp)
    except OSError:
        pass


@pytest.fixture
def auth_handler(auth_db_path: str) -> AuthHandler:
    return AuthHandler(db_path=auth_db_path, token_ttl=3600)


@pytest.fixture
def dashboard(auth_handler: AuthHandler) -> EnterpriseDashboard:
    tmp_trades = tempfile.mktemp(suffix=".db")
    dash = EnterpriseDashboard(
        config={
            "EXECUTION_MODE": "PAPER",
            "api_rate_limit_per_minute": 1000,
            "admin_api_rate_limit_per_minute": 1000,
        },
        auth_handler=auth_handler,
        db_path=tmp_trades,
    )
    yield dash
    try:
        if os.path.exists(tmp_trades):
            os.unlink(tmp_trades)
    except OSError:
        pass


@pytest.fixture
def client(dashboard: EnterpriseDashboard) -> TestClient:
    return TestClient(dashboard.app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def create_user_and_session(auth: AuthHandler, username: str, role: str, must_change_password: bool = False):
    pwd = "Str0ng!PwdX"
    user = auth.get_user(username)
    if user is None:
        create_res = auth.create_user(
            username=username,
            password=pwd,
            role=role,
            display_name=f"{username.capitalize()} User",
        )
        assert create_res["success"], f"Failed to create user {username}: {create_res}"
        user = auth.get_user(username)
    assert user is not None
    if must_change_password:
        conn = auth._get_conn()
        conn.execute("UPDATE users SET must_change_password = 1 WHERE username = ?", (username,))
        conn.commit()
        conn.close()
    session = auth.create_session(user=user)
    assert session is not None
    return user, session.token


# ── 1. Role Capability Matrix Invariant ────────────────────────────────────────

class TestRoleCapabilityMatrix:
    """Verifies that _page_context deterministically returns exact RBAC flags for all roles."""

    def test_unauthenticated_fail_closed(self):
        ctx = _page_context(None, nonce="test-nonce", current_page="change_password")
        assert ctx["user"] is None
        assert ctx["is_admin"] is False
        assert ctx["is_super_admin"] is False
        assert ctx["can_view_state"] is False
        assert ctx["can_halt_trading"] is False
        assert ctx["can_modify_risk"] is False
        assert ctx["can_toggle_strategies"] is False
        assert ctx["can_deploy_models"] is False
        assert ctx["can_modify_code"] is False
        assert ctx["can_view_logs"] is False
        assert ctx["can_manage_brokers"] is False
        assert ctx["can_modify_config"] is False
        assert ctx["can_manage_users"] is False
        assert ctx["can_manage_permissions"] is False
        assert ctx["nonce"] == "test-nonce"
        assert ctx["execution_mode"] == "PAPER"

    def test_legacy_admin_user(self, auth_handler: AuthHandler):
        user, _ = create_user_and_session(auth_handler, "admin", "admin")
        ctx = _page_context(user, nonce="n1", current_page="root")
        assert ctx["is_admin"] is True
        assert ctx["is_super_admin"] is True
        assert ctx["can_view_state"] is True
        assert ctx["can_halt_trading"] is True
        assert ctx["can_modify_risk"] is True
        assert ctx["can_toggle_strategies"] is True
        assert ctx["can_deploy_models"] is True
        assert ctx["can_modify_code"] is True
        assert ctx["can_view_logs"] is True
        assert ctx["can_manage_brokers"] is True
        assert ctx["can_modify_config"] is True
        assert ctx["can_manage_users"] is True
        assert ctx["can_manage_permissions"] is True

    def test_super_admin_role(self, auth_handler: AuthHandler):
        user, _ = create_user_and_session(auth_handler, "super_usr", "super_admin")
        ctx = _page_context(user, nonce="n2", current_page="root")
        assert ctx["is_admin"] is True
        assert ctx["is_super_admin"] is True
        assert ctx["can_manage_permissions"] is True

    def test_standard_admin_user(self, auth_handler: AuthHandler):
        user, _ = create_user_and_session(auth_handler, "ops_admin", "admin")
        ctx = _page_context(user, nonce="n3", current_page="root")
        assert ctx["is_admin"] is True
        assert ctx["is_super_admin"] is False
        assert ctx["can_modify_config"] is True
        assert ctx["can_modify_risk"] is True
        assert ctx["can_manage_users"] is True
        assert ctx["can_manage_permissions"] is False

    def test_operator_user(self, auth_handler: AuthHandler):
        user, _ = create_user_and_session(auth_handler, "operator_bob", "operator")
        ctx = _page_context(user, nonce="n4", current_page="root")
        assert ctx["is_admin"] is False
        assert ctx["is_super_admin"] is False
        assert ctx["can_view_state"] is True
        assert ctx["can_halt_trading"] is True
        assert ctx["can_toggle_strategies"] is True
        assert ctx["can_view_logs"] is True
        assert ctx["can_modify_config"] is False
        assert ctx["can_modify_risk"] is False
        assert ctx["can_manage_users"] is False

    def test_viewer_user(self, auth_handler: AuthHandler):
        user, _ = create_user_and_session(auth_handler, "viewer_charlie", "viewer")
        ctx = _page_context(user, nonce="n5", current_page="root")
        assert ctx["is_admin"] is False
        assert ctx["is_super_admin"] is False
        assert ctx["can_view_state"] is True
        assert ctx["can_view_logs"] is True
        assert ctx["can_halt_trading"] is False
        assert ctx["can_modify_config"] is False
        assert ctx["can_modify_risk"] is False


# ── 2. First-Render Invariant: /change-password vs / ──────────────────────────

class TestFirstRenderNavigationConsistency:
    """Verifies that navigation rendered on first authenticated route (/change-password)
    is strictly identical to subsequent route renders."""

    def test_admin_first_render_has_admin_navigation(self, client: TestClient, auth_handler: AuthHandler):
        """When an admin with must_change_password=True logs in and lands on /change-password,
        Admin & Governance must immediately be rendered on the very first page."""
        _, token = create_user_and_session(auth_handler, "admin", "admin", must_change_password=True)

        # 1st render: Landing page (/change-password)
        resp1 = client.get("/change-password", cookies={"opb_session": token})
        assert resp1.status_code == 200
        html1 = resp1.text
        assert "⚙️ Admin &amp; Governance" in html1 or "⚙️ Admin & Governance" in html1, "Admin & Governance missing on first render!"
        assert "/admin/config" in html1
        assert "/admin/users" in html1
        assert "/admin/kill-switch" in html1

        # 2nd render: Subsequent page (/)
        resp2 = client.get("/", cookies={"opb_session": token})
        assert resp2.status_code == 200
        html2 = resp2.text
        assert "⚙️ Admin &amp; Governance" in html2 or "⚙️ Admin & Governance" in html2
        assert "/admin/config" in html2

    def test_operator_first_render_hides_admin_navigation(self, client: TestClient, auth_handler: AuthHandler):
        """Operators must never see Admin & Governance on first or subsequent renders."""
        _, token = create_user_and_session(auth_handler, "op1", "operator", must_change_password=True)

        resp1 = client.get("/change-password", cookies={"opb_session": token})
        assert resp1.status_code == 200
        html1 = resp1.text
        assert "Admin & Governance" not in html1
        assert "Admin &amp; Governance" not in html1
        assert "/admin/users" not in html1

        resp2 = client.get("/", cookies={"opb_session": token})
        assert resp2.status_code == 200
        html2 = resp2.text
        assert "Admin & Governance" not in html2
        assert "Admin &amp; Governance" not in html2

    def test_viewer_first_render_hides_admin_navigation(self, client: TestClient, auth_handler: AuthHandler):
        """Viewers must never see Admin & Governance on first or subsequent renders."""
        _, token = create_user_and_session(auth_handler, "vw1", "viewer", must_change_password=True)

        resp1 = client.get("/change-password", cookies={"opb_session": token})
        assert resp1.status_code == 200
        assert "Admin & Governance" not in resp1.text
        assert "Admin &amp; Governance" not in resp1.text

        resp2 = client.get("/", cookies={"opb_session": token})
        assert resp2.status_code == 200
        assert "Admin & Governance" not in resp2.text
        assert "Admin &amp; Governance" not in resp2.text

    def test_unauthenticated_change_password_renders_safely_without_privileges(self, client: TestClient):
        """Anonymous request to /change-password renders with fail-closed privilege state."""
        resp = client.get("/change-password")
        assert resp.status_code == 200
        assert "Admin & Governance" not in resp.text
        assert "Admin &amp; Governance" not in resp.text


# ── 3. TemplateResponse Defensive Wrapper & Cache-Control Headers ──────────────

class TestTemplateResponseDefensiveEnrichment:
    """Verifies that TemplateResponse auto-injects canonical context and attaches
    strict Cache-Control headers."""

    def test_template_response_attaches_no_cache_headers(self, client: TestClient, auth_handler: AuthHandler):
        _, token = create_user_and_session(auth_handler, "admin", "admin")
        resp = client.get("/change-password", cookies={"opb_session": token})
        assert resp.status_code == 200
        assert "Cache-Control" in resp.headers
        assert "no-cache" in resp.headers["Cache-Control"]
        assert "no-store" in resp.headers["Cache-Control"]
        assert "must-revalidate" in resp.headers["Cache-Control"]
        assert resp.headers.get("Pragma") == "no-cache"
        assert resp.headers.get("Expires") == "0"

    def test_template_response_auto_enriches_missing_is_admin(self, dashboard: EnterpriseDashboard, auth_handler: AuthHandler):
        """If a route handler calls TemplateResponse without is_admin, wrapper auto-enriches it."""
        from fastapi import Request
        user, token = create_user_and_session(auth_handler, "admin", "admin")

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test-route",
            "headers": [(b"cookie", f"opb_session={token}".encode())],
        }
        req = Request(scope)

        # Call with minimal context missing is_admin
        resp = dashboard._templates.TemplateResponse(
            request=req,
            name="change_password.html",
            context={"nonce": "abc"},
        )
        assert resp.status_code == 200
        assert "⚙️ Admin &amp; Governance" in resp.body.decode() or "⚙️ Admin & Governance" in resp.body.decode()


# ── 4. Zero Authorization Bypass (Backend Gate Enforcement) ───────────────────

class TestZeroAuthorizationBypass:
    """Confirms that UI navigation visibility changes NEVER bypass backend authorization."""

    def test_viewer_cannot_access_admin_config(self, client: TestClient, auth_handler: AuthHandler):
        _, token = create_user_and_session(auth_handler, "vw2", "viewer")
        resp = client.get("/admin/config", cookies={"opb_session": token})
        # Admin page must reject non-admin with 403
        assert resp.status_code == 403

    def test_operator_cannot_access_admin_users(self, client: TestClient, auth_handler: AuthHandler):
        _, token = create_user_and_session(auth_handler, "op2", "operator")
        resp = client.get("/admin/users", cookies={"opb_session": token})
        assert resp.status_code == 403

    def test_unauthenticated_cannot_access_admin_config(self, client: TestClient):
        resp = client.get("/admin/config", follow_redirects=False)
        # Unauthenticated request redirects to /login
        assert resp.status_code in (302, 307)
        assert resp.headers.get("location") == "/login"
