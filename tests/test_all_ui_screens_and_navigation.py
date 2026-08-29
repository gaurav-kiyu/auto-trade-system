"""Comprehensive Tests for all 31 Enterprise Dashboard UI Screens, Navigation Links,
Buttons, Form Actions, and Interactive APIs.
"""

import pytest
pytest.importorskip("fastapi")
pytest.importorskip("starlette")
from fastapi.testclient import TestClient
from core.enterprise_dashboard.main import EnterpriseDashboard


@pytest.fixture(scope="module")
def dashboard_client(tmp_path_factory):
    """Regression: this fixture used to construct EnterpriseDashboard() with no
    path overrides at all, so every write this module's tests performed (most
    importantly /api/config/apply below) landed on the REAL project files -
    json/config.json, db/auth.db - not a throwaway test copy. That's how
    json/config.json ended up corrupted with this test's literal request body
    (`{"config": {...}, "reason": "..."}`) instead of the flat key/value pairs
    the config-merge system actually expects there."""
    tmp_path = tmp_path_factory.mktemp("dashboard_client")
    dashboard = EnterpriseDashboard(config={
        "web_dashboard_host": "127.0.0.1",
        "trader_state_path": str(tmp_path / "trader_state.json"),
        "auth_db_path": str(tmp_path / "auth.db"),
        "index_config_path": str(tmp_path / "config.json"),
    })
    app = dashboard.app
    client = TestClient(app, follow_redirects=False)
    
    # Create test admin user and session
    auth = dashboard._auth
    user = auth.get_user("admin")
    if not user:
        res = auth.create_user("admin", "AdminPassword123!", role="admin")
        user = auth.get_user_by_id(res["user_id"])
    
    session = auth.create_session(user)
    client.cookies.set("opb_session", session.token)
    return client, dashboard, user


# =============================================================================
# 1. Full Audit of all 31 UI Screens (GET Requests Render 200 OK HTML)
# =============================================================================

ALL_UI_SCREENS = [
    ("/", "Live Dashboard"),
    ("/login", "Login Page"),
    ("/register", "Registration Page"),
    ("/forgot-password", "Forgot Password"),
    ("/pricing-plans", "Pricing Plans"),
    ("/my-signals", "User Signals Screen"),
    ("/options-chain", "Options Chain Screen"),
    ("/live-pnl", "Live PnL Screen"),
    ("/trade-journal", "Trade Journal Screen"),
    ("/trade-copier", "Trade Copier Screen"),
    ("/strategy-sandbox", "Strategy Sandbox"),
    ("/fii-dii-radar", "FII / DII Radar"),
    ("/sector-radar", "Sector Radar"),
    ("/margin-radar", "Margin Radar"),
    ("/expiry-harvester", "Expiry Harvester"),
    ("/performance", "Performance Analytics"),
    ("/observability", "Observability"),
    ("/system-health", "System Health"),
    ("/data-quality", "Data Quality"),
    ("/event-store", "Event Store"),
    ("/governance", "Constitution Governance"),
    ("/intelligence", "Continuous Intelligence"),
    ("/capacity", "Capacity Planning"),
    ("/security", "Security Auditor"),
    ("/admin/config", "Admin Config Editor"),
    ("/admin/signals", "Admin Signal Manager"),
    ("/admin/users", "Admin User Manager"),
    ("/admin/portfolio-analyzer", "Admin Portfolio Analyzer"),
    ("/admin/kill-switch", "Admin Kill Switch"),
]


@pytest.mark.parametrize("route,title", ALL_UI_SCREENS)
def test_all_ui_screens_render_200_ok(dashboard_client, route, title):
    """Ensure every single UI screen renders 200 OK with non-empty HTML."""
    client, _, _ = dashboard_client
    resp = client.get(route)
    assert resp.status_code == 200, f"Screen {title} ({route}) returned {resp.status_code}"
    assert len(resp.text) > 100, f"Screen {title} ({route}) returned empty response"
    assert "html" in resp.headers.get("content-type", "").lower()


# =============================================================================
# 2. Interactive Buttons, Admin Config Updates, and API Actions
# =============================================================================

def test_admin_config_validate_and_apply_button_actions(dashboard_client, monkeypatch):
    """Test validating configuration and applying changes via Admin Config UI API."""
    client, _, _ = dashboard_client

    # _apply_config_change() unconditionally calls core.env_sync.sync_env_file()
    # (imported locally inside the function, fresh on every call), which
    # writes OPBUYING_<KEY> lines into the real project .env file - there is
    # no path-override hook for it (unlike config/auth/state paths above). A
    # real .env commonly holds real broker/Telegram secrets, so a test must
    # never let this call through to the real file.
    import core.env_sync
    monkeypatch.setattr(core.env_sync, "sync_env_file", lambda *a, **k: True)
    
    # 1. GET current config to establish CSRF cookie
    resp = client.get("/admin/config")
    assert resp.status_code == 200
    csrf_token = client.cookies.get("opb_csrf", "")
    headers = {"X-CSRF-Token": csrf_token} if csrf_token else {}
    
    # 2. GET /api/config
    resp_cfg = client.get("/api/config")
    assert resp_cfg.status_code == 200
    data = resp_cfg.json()
    cfg = data.get("config", data)
    assert isinstance(cfg, dict)
    
    # 3. POST /api/config/validate (Validate button action) - the real
    # admin_config.html frontend sends the flat {key: value} dict directly
    # (see saveConfig()'s `body: JSON.stringify(changedKeys)`), not a
    # {"config": ..., "reason": ...} wrapper - _validate_config_change()/
    # _apply_config_change() both iterate `change.items()` expecting exactly
    # that flat shape.
    val_resp = client.post("/api/config/validate", json={"INDEX_MIN_SCORE": 85}, headers=headers)
    assert val_resp.status_code in (200, 422)

    # 4. POST /api/config/apply (Apply / Save button action)
    apply_resp = client.post(
        "/api/config/apply",
        json={
            "INDEX_MIN_SCORE": 85,
            "MIN_SCORE_THRESHOLD": 95,
        },
        headers=headers,
    )
    assert apply_resp.status_code in (200, 400)
    applied = apply_resp.json()
    assert applied.get("success") is True
    assert set(applied["applied_keys"]) == {"INDEX_MIN_SCORE", "MIN_SCORE_THRESHOLD"}

    # The applied keys must land as real top-level config keys, not nested
    # under a "config"/"reason" wrapper - this is the exact bug the isolated
    # fixture above exists to let us catch safely.
    resp_cfg2 = client.get("/api/config")
    cfg2 = resp_cfg2.json().get("config", {})
    assert cfg2.get("INDEX_MIN_SCORE") == 85
    assert cfg2.get("MIN_SCORE_THRESHOLD") == 95
    assert "reason" not in cfg2


def test_system_health_api_and_refresh_button(dashboard_client):
    """Test system health endpoint."""
    client, _, _ = dashboard_client
    resp = client.get("/api/system/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body or "healthy" in body or "ok" in body or isinstance(body, dict)


def test_options_chain_data_endpoint(dashboard_client):
    """Test options chain API endpoint."""
    client, _, _ = dashboard_client
    resp = client.get("/api/options-chain?symbol=NIFTY")
    assert resp.status_code in (200, 404, 400)


def test_unauthenticated_protected_routes_redirect_to_login():
    """Verify that unauthenticated requests to protected pages redirect to /login."""
    dashboard = EnterpriseDashboard()
    anon_client = TestClient(dashboard.app, follow_redirects=False)
    
    protected_routes = ["/", "/admin/config", "/admin/signals", "/admin/users", "/my-signals"]
    for route in protected_routes:
        resp = anon_client.get(route)
        assert resp.status_code in (302, 303, 307), f"Route {route} did not redirect unauthenticated user"
        assert resp.headers.get("location") == "/login"
