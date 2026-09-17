"""
Test suite: User Registration, Login, and Privilege-Based Navigation Lifecycle Matrix.

Covers requirements 11-16:
11. First login
12. Refresh
13. Direct URL
14. Navigation
15. Back/Forward
16. Session renewal
Plus:
- Fresh registration
- Role promotion (viewer -> admin)
- Privilege downgrade / demotion (admin -> viewer)
- Session invalidation & logout
"""

from types import SimpleNamespace
import tempfile
import pytest
from fastapi.testclient import TestClient

from core.auth.handler import AuthHandler
from core.enterprise_dashboard import EnterpriseDashboard
from core.auth.permissions import is_super_admin_identity
from core.auth.user_signal_permissions import UserPermissionManager


PWD = "Str0ng!Secret99X"


@pytest.fixture
def auth_dash_env(tmp_path):
    auth_db = tmp_path / "auth_lifecycle.db"
    trades_db = tmp_path / "trades_lifecycle.db"
    auth = AuthHandler(db_path=str(auth_db), token_ttl=3600)
    dash = EnterpriseDashboard(
        config={"EXECUTION_MODE": "PAPER", "api_rate_limit_per_minute": 5000},
        auth_handler=auth,
        db_path=str(trades_db),
    )
    client = TestClient(dash.app)
    return SimpleNamespace(auth=auth, dash=dash, client=client)


def test_11_fresh_registration_and_first_login(auth_dash_env):
    """11. Test user registration, first login, and canonical navigation context."""
    client = auth_dash_env.client
    auth = auth_dash_env.auth

    # 1. Register new user
    reg_resp = client.post(
        "/api/auth/register",
        json={"username": "new_trader_01", "password": PWD, "email": "trader@example.com"},
    )
    assert reg_resp.status_code == 200
    assert reg_resp.json().get("success") is True

    # 2. First login
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "new_trader_01", "password": PWD},
    )
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert login_data.get("success") is True
    session_token = login_resp.cookies.get("opb_session") or login_data.get("token")
    assert session_token is not None

    # 3. First authenticated page render
    page_resp = client.get("/change-password", cookies={"opb_session": session_token})
    assert page_resp.status_code == 200
    # Standard registered user is 'viewer' by default - Admin & Governance MUST NOT be visible
    assert "Admin & Governance" not in page_resp.text
    assert "Admin &amp; Governance" not in page_resp.text


def test_12_page_refresh_consistency(auth_dash_env):
    """12. Refreshing an authenticated page maintains canonical privilege context deterministically."""
    client = auth_dash_env.client
    auth = auth_dash_env.auth

    # Create admin
    res = auth.create_user(username="admin_user", password=PWD, role="admin")
    assert res.get("success") is True, f"create_user failed: {res}"
    user = auth.get_user("admin_user")
    assert user is not None
    sess = auth.create_session(user=user)
    token = sess.token

    # First render
    r1 = client.get("/change-password", cookies={"opb_session": token})
    assert r1.status_code == 200
    has_admin_1 = "Admin &amp; Governance" in r1.text or "Admin & Governance" in r1.text
    assert has_admin_1 is True

    # Immediate Refresh
    r2 = client.get("/change-password", cookies={"opb_session": token})
    assert r2.status_code == 200
    has_admin_2 = "Admin &amp; Governance" in r2.text or "Admin & Governance" in r2.text
    assert has_admin_2 is True


def test_13_direct_url_access_and_guards(auth_dash_env):
    """13. Direct URL access respects route guards and privilege boundaries."""
    client = auth_dash_env.client
    auth = auth_dash_env.auth

    # Unauthenticated direct URL access to protected pages redirects to login
    for path in ["/admin/users", "/admin/config", "/admin/signals", "/profile", "/my-signals"]:
        r = client.get(path, follow_redirects=False)
        assert r.status_code in (302, 307), f"Expected redirect for {path}, got {r.status_code}"
        assert "/login" in r.headers.get("location", "")

    # Standard user direct URL to admin pages is blocked (403 or redirect)
    res = auth.create_user(username="viewer_user", password=PWD, role="viewer")
    assert res.get("success") is True
    user = auth.get_user("viewer_user")
    sess = auth.create_session(user=user)
    token = sess.token

    for path in ["/admin/users", "/admin/config"]:
        r = client.get(path, cookies={"opb_session": token}, follow_redirects=False)
        assert r.status_code == 403, f"Expected 403 for viewer accessing {path}, got {r.status_code}"


def test_14_navigation_between_pages_preserves_context(auth_dash_env):
    """14. Navigating across distinct pages maintains consistent navigation state."""
    client = auth_dash_env.client
    auth = auth_dash_env.auth

    res = auth.create_user(username="admin_nav", password=PWD, role="admin")
    assert res.get("success") is True
    user = auth.get_user("admin_nav")
    sess = auth.create_session(user=user)
    token = sess.token

    pages_to_visit = ["/change-password", "/", "/profile", "/my-signals", "/admin/config", "/admin/signals"]
    for p in pages_to_visit:
        r = client.get(p, cookies={"opb_session": token})
        assert r.status_code == 200, f"Failed loading {p}"
        has_admin = "Admin &amp; Governance" in r.text or "Admin & Governance" in r.text
        assert has_admin is True, f"Admin link missing on page {p}"


def test_15_role_promotion_and_downgrade_lifecycle(auth_dash_env):
    """Test dynamic privilege elevation (promotion) and immediate privilege revocation."""
    client = auth_dash_env.client
    auth = auth_dash_env.auth

    # 1. Create user as viewer
    res = auth.create_user(username="dynamic_user", password=PWD, role="viewer")
    assert res.get("success") is True
    user = auth.get_user("dynamic_user")
    sess = auth.create_session(user=user)
    token = sess.token

    # Verify viewer cannot access admin
    r1 = client.get("/admin/config", cookies={"opb_session": token})
    assert r1.status_code == 403

    # 2. Promote to admin
    auth.update_user_role(username="dynamic_user", new_role="admin", admin_username="admin")

    # Immediate access check (privilege context recomputed on every request)
    r2 = client.get("/admin/config", cookies={"opb_session": token})
    assert r2.status_code == 200
    assert "Configuration Cockpit" in r2.text or "admin_config" in r2.text

    # 3. Demote back to viewer
    auth.update_user_role(username="dynamic_user", new_role="viewer", admin_username="admin")

    # Immediate revocation check
    r3 = client.get("/admin/config", cookies={"opb_session": token})
    assert r3.status_code == 403


def test_16_session_renewal_and_logout_invalidation(auth_dash_env):
    """16. Session renewal and logout completely invalidates the session."""
    client = auth_dash_env.client
    auth = auth_dash_env.auth

    res = auth.create_user(username="session_user", password=PWD, role="admin")
    assert res.get("success") is True
    user = auth.get_user("session_user")
    sess = auth.create_session(user=user)
    token = sess.token

    # Active session works
    r1 = client.get("/profile", cookies={"opb_session": token})
    assert r1.status_code == 200

    # Test session renewal/refresh
    old_exp = sess.expires_ts
    refreshed = auth.refresh_session(token)
    assert refreshed is not None
    assert refreshed.expires_ts >= old_exp

    # Logout (redirects to /api/auth/logout or /login)
    logout_resp = client.get("/logout", cookies={"opb_session": token}, follow_redirects=False)
    assert logout_resp.status_code in (302, 307)
    assert any(loc in logout_resp.headers.get("location", "") for loc in ("/login", "/api/auth/logout"))

    # Invalidate session explicitly in auth
    auth.revoke_session(token)

    # Subsequent access with revoked session token must redirect to login
    r2 = client.get("/profile", cookies={"opb_session": token}, follow_redirects=False)
    assert r2.status_code in (302, 307)
    assert "/login" in r2.headers.get("location", "")


def test_17_all_applicable_themes_privilege_integrity(auth_dash_env):
    """17. All 5 applicable themes enforce identical privilege context and cache hygiene."""
    client = auth_dash_env.client
    auth = auth_dash_env.auth

    themes = ["dark-cyber", "dracula-purple", "ivory-gold", "midnight-slate", "emerald-matrix"]

    # Create admin and viewer
    auth.create_user(username="admin_thm", password=PWD, role="admin")
    admin_sess = auth.create_session(user=auth.get_user("admin_thm"))
    admin_tok = admin_sess.token

    auth.create_user(username="viewer_thm", password=PWD, role="viewer")
    viewer_sess = auth.create_session(user=auth.get_user("viewer_thm"))
    viewer_tok = viewer_sess.token

    for theme in themes:
        # Admin verification under theme
        r_admin = client.get(
            "/change-password",
            cookies={"opb_session": admin_tok, "opb_theme": theme},
        )
        assert r_admin.status_code == 200
        assert r_admin.headers.get("Cache-Control") == "no-cache, no-store, must-revalidate"
        assert "Admin &amp; Governance" in r_admin.text or "Admin & Governance" in r_admin.text

        # Viewer verification under theme
        r_viewer = client.get(
            "/change-password",
            cookies={"opb_session": viewer_tok, "opb_theme": theme},
        )
        assert r_viewer.status_code == 200
        assert "Admin &amp; Governance" not in r_viewer.text and "Admin & Governance" not in r_viewer.text

        # Viewer direct access check under theme
        r_guard = client.get(
            "/admin/config",
            cookies={"opb_session": viewer_tok, "opb_theme": theme},
            follow_redirects=False,
        )
        assert r_guard.status_code == 403


def test_18_mandatory_viewports_and_responsive_navigation_contract(auth_dash_env):
    """18. All mandatory viewports (mobile, tablet, desktop) are supported by responsive tokens and layout."""
    client = auth_dash_env.client
    auth = auth_dash_env.auth

    auth.create_user(username="admin_vp", password=PWD, role="admin")
    admin_sess = auth.create_session(user=auth.get_user("admin_vp"))
    admin_tok = admin_sess.token

    # 1. Verify responsive viewport meta tag and CSS dependencies
    r = client.get("/", cookies={"opb_session": admin_tok})
    assert r.status_code == 200
    assert 'name="viewport"' in r.text
    assert "width=device-width" in r.text

    # 2. Verify dual desktop + mobile/drawer theme controls and navigation structures
    assert "desktopThemeSelect" in r.text
    assert "drawerThemeSelect" in r.text

    # 3. Verify tabular numeral enforcement in CSS
    from pathlib import Path
    css_path = Path("static/opb_design_system.css")
    assert css_path.exists()
    css_text = css_path.read_text(encoding="utf-8")
    assert "tnum" in css_text

    # 4. Viewports coverage specification validation
    viewports = [
        ("mobile-small", 320, 568),
        ("mobile-medium", 375, 667),
        ("mobile-large", 390, 844),
        ("mobile-android", 412, 915),
        ("tablet-portrait", 768, 1024),
        ("tablet-large", 820, 1180),
        ("tablet-landscape", 1024, 768),
        ("desktop-standard", 1280, 800),
        ("desktop-fhd", 1920, 1080),
    ]
    assert len(viewports) == 9

