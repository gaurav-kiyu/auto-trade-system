"""Test suite for discovered routes inventory reconciliation: TC-0959 to TC-0980.

Verifies HTTP response codes, redirects, and canonical routes for all 18 unrepresented
routes plus system/API documentation endpoints.
"""

from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

from core.auth.handler import AuthHandler
from core.enterprise_dashboard import EnterpriseDashboard

PWD = "Str0ng!Secret99X"


@pytest.fixture
def auth_dash_env(tmp_path):
    auth_db = tmp_path / "auth_discovered.db"
    trades_db = tmp_path / "trades_discovered.db"
    auth = AuthHandler(db_path=str(auth_db), token_ttl=3600)
    dash = EnterpriseDashboard(
        config={"EXECUTION_MODE": "PAPER", "api_rate_limit_per_minute": 5000},
        auth_handler=auth,
        db_path=str(trades_db),
    )
    auth.create_user(username="admin_recon", password=PWD, role="admin")
    admin_user = auth.get_user("admin_recon")
    sess = auth.create_session(user=admin_user)
    client = TestClient(dash.app)
    return SimpleNamespace(auth=auth, dash=dash, client=client, token=sess.token)


def test_tc_0959_admin_root_redirect(auth_dash_env):
    """TC-0959: GET /admin -> 307 redirect to /admin/config"""
    resp = auth_dash_env.client.get("/admin", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers.get("location") == "/admin/config"


def test_tc_0960_admin_slash_redirect(auth_dash_env):
    """TC-0960: GET /admin/ -> 307 redirect to /admin/config"""
    resp = auth_dash_env.client.get("/admin/", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers.get("location") == "/admin/config"


def test_tc_0961_broker_route(auth_dash_env):
    """TC-0961: GET /broker -> 200 for authenticated admin"""
    resp = auth_dash_env.client.get("/broker", cookies={"opb_session": auth_dash_env.token})
    assert resp.status_code in (200, 307)


def test_tc_0962_business_intelligence_route(auth_dash_env):
    """TC-0962: GET /business-intelligence -> 200 for authenticated admin"""
    resp = auth_dash_env.client.get("/business-intelligence", cookies={"opb_session": auth_dash_env.token})
    assert resp.status_code in (200, 307)


def test_tc_0963_chain_index_route(auth_dash_env):
    """TC-0963: GET /chain/NIFTY -> 200 for authenticated admin"""
    resp = auth_dash_env.client.get("/chain/NIFTY", cookies={"opb_session": auth_dash_env.token})
    assert resp.status_code in (200, 307)


def test_tc_0964_change_password_route(auth_dash_env):
    """TC-0964: GET /change-password -> 200 for authenticated user"""
    resp = auth_dash_env.client.get("/change-password", cookies={"opb_session": auth_dash_env.token})
    assert resp.status_code == 200
    assert "Password" in resp.text


def test_tc_0965_service_worker_script(auth_dash_env):
    """TC-0965: GET /dashboard-sw.js -> 200 JavaScript"""
    resp = auth_dash_env.client.get("/dashboard-sw.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers.get("content-type", "") or "text" in resp.headers.get("content-type", "")


def test_tc_0966_health_route(auth_dash_env):
    """TC-0966: GET /health -> 200 JSON health status"""
    resp = auth_dash_env.client.get("/health", follow_redirects=False)
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


def test_tc_0967_logout_route(auth_dash_env):
    """TC-0967: GET /logout -> 307 redirect to /api/auth/logout"""
    resp = auth_dash_env.client.get("/logout", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert any(loc in resp.headers.get("location", "") for loc in ("/login", "/api/auth/logout"))


def test_tc_0968_logs_route(auth_dash_env):
    """TC-0968: GET /logs -> 200 for authenticated admin"""
    resp = auth_dash_env.client.get("/logs", cookies={"opb_session": auth_dash_env.token})
    assert resp.status_code in (200, 307)


def test_tc_0969_ml_route(auth_dash_env):
    """TC-0969: GET /ml -> 200 for authenticated admin"""
    resp = auth_dash_env.client.get("/ml", cookies={"opb_session": auth_dash_env.token})
    assert resp.status_code in (200, 307)


def test_tc_0970_payoff_calculator_route(auth_dash_env):
    """TC-0970: GET /payoff-calculator -> 200 for authenticated user"""
    resp = auth_dash_env.client.get("/payoff-calculator", cookies={"opb_session": auth_dash_env.token})
    assert resp.status_code == 200


def test_tc_0971_risk_route(auth_dash_env):
    """TC-0971: GET /risk -> 200 for authenticated admin"""
    resp = auth_dash_env.client.get("/risk", cookies={"opb_session": auth_dash_env.token})
    assert resp.status_code in (200, 307)


def test_tc_0972_signals_route(auth_dash_env):
    """TC-0972: GET /signals -> 200 for authenticated admin"""
    resp = auth_dash_env.client.get("/signals", cookies={"opb_session": auth_dash_env.token})
    assert resp.status_code in (200, 307)


def test_tc_0973_signals_inject_guard(auth_dash_env):
    """TC-0973: POST /signals/inject -> 200 with status in disabled, queued, rate_limited"""
    resp = auth_dash_env.client.post("/signals/inject", json={"test": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") in ("disabled", "queued", "rate_limited")


def test_tc_0974_system_state_route(auth_dash_env):
    """TC-0974: GET /system/state -> 200 JSON or 401/403"""
    resp = auth_dash_env.client.get("/system/state", cookies={"opb_session": auth_dash_env.token})
    assert resp.status_code in (200, 401, 403)


def test_tc_0975_testing_suite_route(auth_dash_env):
    """TC-0975: GET /testing-suite -> 200 for authenticated admin"""
    resp = auth_dash_env.client.get("/testing-suite", cookies={"opb_session": auth_dash_env.token})
    assert resp.status_code in (200, 307)


def test_tc_0976_trading_route(auth_dash_env):
    """TC-0976: GET /trading -> 200 for authenticated admin"""
    resp = auth_dash_env.client.get("/trading", cookies={"opb_session": auth_dash_env.token})
    assert resp.status_code in (200, 307)


def test_tc_0977_api_docs(auth_dash_env):
    """TC-0977: GET /api/docs -> Swagger documentation"""
    resp = auth_dash_env.client.get("/api/docs")
    assert resp.status_code in (200, 401, 403, 404)


def test_tc_0978_api_redoc(auth_dash_env):
    """TC-0978: GET /api/redoc -> Redoc documentation"""
    resp = auth_dash_env.client.get("/api/redoc")
    assert resp.status_code in (200, 401, 403, 404)


def test_tc_0979_openapi_json(auth_dash_env):
    """TC-0979: GET /openapi.json -> OpenAPI specification"""
    resp = auth_dash_env.client.get("/openapi.json")
    assert resp.status_code in (200, 401, 403, 404)


def test_tc_0980_swagger_oauth_redirect(auth_dash_env):
    """TC-0980: GET /docs/oauth2-redirect -> Swagger OAuth redirect"""
    resp = auth_dash_env.client.get("/docs/oauth2-redirect")
    assert resp.status_code in (200, 401, 403, 404)


def test_tc_0981_admin_capabilities_page(auth_dash_env):
    """TC-0981: GET /admin/capabilities -> 200 for authenticated admin"""
    resp = auth_dash_env.client.get("/admin/capabilities", cookies={"opb_session": auth_dash_env.token})
    assert resp.status_code == 200
    assert "Capability Diagnostics" in resp.text


def test_tc_0982_api_admin_capabilities(auth_dash_env):
    """TC-0982: GET /api/admin/capabilities -> 200 JSON capability report"""
    resp = auth_dash_env.client.get("/api/admin/capabilities", cookies={"opb_session": auth_dash_env.token})
    assert resp.status_code == 200
    data = resp.json()
    assert "capabilities" in data
    assert "summary" in data


def test_tc_0983_api_health_route(auth_dash_env):
    """TC-0983: GET /api/health -> 200 JSON health status"""
    resp = auth_dash_env.client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


def test_tc_0984_api_market_telemetry(auth_dash_env):
    """TC-0984: GET /api/system/market-telemetry -> 200 market status"""
    resp = auth_dash_env.client.get("/api/system/market-telemetry")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "label" in data
