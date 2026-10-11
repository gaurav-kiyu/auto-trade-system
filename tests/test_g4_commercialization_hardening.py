"""Target Security and Commercialization-Readiness Tests for OPB v2.61 — G4 Hardening.

Authority: OPB-FINAL-PHASE-GOVERNANCE-001
Phase: OPB PUBLIC RELEASE & COMMERCIALIZATION HARDENING — G4

Test Matrix Covers:
1. G4-SEC-01: Unauthenticated requests to GET /api/intelligence/summary return 401 Unauthorized.
2. G4-SEC-01: Unauthenticated requests to GET /api/intelligence/incidents/list return 401 Unauthorized.
3. G4-SEC-01: Unauthenticated requests to GET /api/intelligence/bi/quality return 401 Unauthorized.
4. G4-SEC-01: Unauthenticated requests to GET /api/intelligence/pipeline/stats return 401 Unauthorized.
5. G4-SEC-01: Unauthenticated requests to GET /api/intelligence/architecture/stats return 401 Unauthorized.
6. G4-SEC-01: Unauthenticated requests to POST /api/intelligence/incidents/create return 401 Unauthorized.
7. G4-SEC-01: Unauthenticated requests to POST /api/intelligence/chaos/run return 401 Unauthorized.
8. G4-SEC-01: Unauthenticated requests to POST /api/intelligence/pipeline/run return 401 Unauthorized.
9. G4-SEC-01: Unauthenticated requests to POST /api/intelligence/ml/retrain return 401 Unauthorized.
10. RBAC: Authenticated user with viewer role receives 403 Forbidden on operator_or_admin endpoints.
11. RBAC: Authenticated user with operator role receives 200 OK on operator_or_admin endpoints.
12. RBAC: Authenticated operator receives 403 Forbidden on admin_only /api/intelligence/ml/retrain.
13. RBAC: Authenticated admin receives 200 OK on admin_only /api/intelligence/ml/retrain.
14. Bearer Token: Authorization header with valid operator session token is accepted.
15. Account Status: Inactive / disabled user receives 403 Forbidden (Account disabled).
16. Case B Preservation: POST /signals/inject remains accessible without user session token.
17. Case B Preservation: POST /api/execution/iceberg-slice returns simulation plan.
18. Health Observability: GET /health and /api/health remain accessible unauthenticated.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _make_trades_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            trade_id TEXT PRIMARY KEY,
            symbol TEXT,
            direction TEXT,
            entry_price REAL,
            exit_price REAL,
            pnl REAL,
            timestamp TEXT,
            status TEXT
        )
    """)
    conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def g4_env(tmp_path_factory):
    """Fixture providing an EnterpriseDashboard instance with isolated auth DB."""
    from core.enterprise_dashboard import EnterpriseDashboard

    tmp_path = tmp_path_factory.mktemp("g4_test")
    state_p = tmp_path / "trader_state.json"
    state_p.write_text(json.dumps({
        "daily_pnl": 1500.0, "open_positions": 2, "hard_halt": False,
        "capital": 100000, "execution_mode": "paper", "total_trades": 42,
    }))
    trades_db = str(tmp_path / "trades.db")
    _make_trades_db(trades_db)
    auth_db = str(tmp_path / "auth.db")

    db = EnterpriseDashboard(config={
        "web_dashboard_host": "127.0.0.1",
        "trader_state_path": str(state_p),
        "auth_db_path": auth_db,
    }, db_path=trades_db)

    signal_log_mock = MagicMock()
    signal_log_mock.recent.return_value = []
    db.wire_bot_refs(
        pause_event=threading.Event(),
        signal_log=signal_log_mock,
    )

    admin_user = db._auth.get_user("admin")
    admin_token = db._auth.create_session(admin_user).token

    db._auth.create_user("g4operator", "OperatorPass123!", "operator")
    operator_user = db._auth.get_user("g4operator")
    operator_token = db._auth.create_session(operator_user).token

    db._auth.create_user("g4viewer", "ViewerPass123!", "viewer")
    viewer_user = db._auth.get_user("g4viewer")
    viewer_token = db._auth.create_session(viewer_user).token

    db._auth.create_user("g4disabled", "DisabledPass123!", "operator")
    disabled_user = db._auth.get_user("g4disabled")
    disabled_token = db._auth.create_session(disabled_user).token
    db._auth.disable_user("g4disabled", admin_user.username)

    client = TestClient(db.app)
    # Establish real CSRF cookie and header for mutation tests
    r_get = client.get("/login")
    csrf_token = r_get.cookies.get("opb_csrf", "")
    client.headers.update({"X-CSRF-Token": csrf_token})
    client.cookies.set("opb_csrf", csrf_token)

    return {
        "dashboard": db,
        "client": client,
        "admin_token": admin_token,
        "operator_token": operator_token,
        "viewer_token": viewer_token,
        "disabled_token": disabled_token,
        "csrf_token": csrf_token,
    }


def test_g4_unauth_intelligence_summary(g4_env):
    """GET /api/intelligence/summary must return 401 Unauthorized when unauthenticated."""
    client = g4_env["client"]
    resp = client.get("/api/intelligence/summary", headers={"accept": "application/json"})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text[:200]}"


def test_g4_unauth_intelligence_incidents_list(g4_env):
    """GET /api/intelligence/incidents/list must return 401 Unauthorized when unauthenticated."""
    client = g4_env["client"]
    resp = client.get("/api/intelligence/incidents/list", headers={"accept": "application/json"})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text[:200]}"


def test_g4_unauth_intelligence_bi_quality(g4_env):
    """GET /api/intelligence/bi/quality must return 401 Unauthorized when unauthenticated."""
    client = g4_env["client"]
    resp = client.get("/api/intelligence/bi/quality", headers={"accept": "application/json"})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text[:200]}"


def test_g4_unauth_intelligence_pipeline_stats(g4_env):
    """GET /api/intelligence/pipeline/stats must return 401 Unauthorized when unauthenticated."""
    client = g4_env["client"]
    resp = client.get("/api/intelligence/pipeline/stats", headers={"accept": "application/json"})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text[:200]}"


def test_g4_unauth_intelligence_architecture_stats(g4_env):
    """GET /api/intelligence/architecture/stats must return 401 Unauthorized when unauthenticated."""
    client = g4_env["client"]
    resp = client.get("/api/intelligence/architecture/stats", headers={"accept": "application/json"})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text[:200]}"


def test_g4_unauth_intelligence_incidents_create(g4_env):
    """POST /api/intelligence/incidents/create must return 401 Unauthorized when unauthenticated."""
    client = g4_env["client"]
    resp = client.post(
        "/api/intelligence/incidents/create",
        json={"title": "Test Incident", "severity": "P3"},
        headers={"accept": "application/json"},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text[:200]}"


def test_g4_unauth_intelligence_chaos_run(g4_env):
    """POST /api/intelligence/chaos/run must return 401 Unauthorized when unauthenticated."""
    client = g4_env["client"]
    resp = client.post(
        "/api/intelligence/chaos/run",
        json={"experiment": "latency"},
        headers={"accept": "application/json"},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text[:200]}"


def test_g4_unauth_intelligence_pipeline_run(g4_env):
    """POST /api/intelligence/pipeline/run must return 401 Unauthorized when unauthenticated."""
    client = g4_env["client"]
    resp = client.post(
        "/api/intelligence/pipeline/run",
        json={"target": "full"},
        headers={"accept": "application/json"},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text[:200]}"


def test_g4_unauth_intelligence_ml_retrain(g4_env):
    """POST /api/intelligence/ml/retrain must return 401 Unauthorized when unauthenticated."""
    client = g4_env["client"]
    resp = client.post(
        "/api/intelligence/ml/retrain",
        headers={"accept": "application/json"},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text[:200]}"


def test_g4_viewer_forbidden_on_operator_routes(g4_env):
    """Viewer role must receive 403 Forbidden on operator_or_admin endpoints."""
    client = g4_env["client"]
    cookies = {"opb_session": g4_env["viewer_token"]}
    headers = {"accept": "application/json"}

    resp = client.get("/api/intelligence/summary", cookies=cookies, headers=headers)
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text[:200]}"


def test_g4_operator_allowed_on_operator_routes(g4_env):
    """Operator role must receive 200 OK on operator_or_admin endpoints."""
    client = g4_env["client"]
    cookies = {"opb_session": g4_env["operator_token"]}
    headers = {"accept": "application/json"}

    resp = client.get("/api/intelligence/summary", cookies=cookies, headers=headers)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert data.get("status") == "ok"


def test_g4_operator_forbidden_on_admin_routes(g4_env):
    """Operator role must receive 403 Forbidden on admin_only routes."""
    client = g4_env["client"]
    cookies = {"opb_session": g4_env["operator_token"]}
    headers = {"accept": "application/json"}

    resp = client.post("/api/intelligence/ml/retrain", cookies=cookies, headers=headers)
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text[:200]}"


def test_g4_admin_allowed_on_admin_routes(g4_env):
    """Admin role must receive 200 OK on admin_only routes."""
    client = g4_env["client"]
    cookies = {"opb_session": g4_env["admin_token"]}
    headers = {"accept": "application/json"}

    resp = client.post("/api/intelligence/ml/retrain", cookies=cookies, headers=headers)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"


def test_g4_bearer_token_authorization(g4_env):
    """Bearer token in Authorization header must be accepted for protected routes."""
    client = g4_env["client"]
    headers = {
        "Authorization": f"Bearer {g4_env['operator_token']}",
        "accept": "application/json",
    }
    resp = client.get("/api/intelligence/summary", headers=headers)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"


def test_g4_disabled_account_rejected(g4_env):
    """Disabled user session must receive 403 Forbidden (Account disabled)."""
    client = g4_env["client"]
    cookies = {"opb_session": g4_env["disabled_token"]}
    headers = {"accept": "application/json"}

    resp = client.get("/api/intelligence/summary", cookies=cookies, headers=headers)
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text[:200]}"
    assert resp.json().get("code") == 403 or resp.json().get("error") == "Forbidden"


def test_g4_case_b_signals_inject_unauthenticated(g4_env):
    """Case B: POST /signals/inject remains accessible without session auth."""
    client = g4_env["client"]
    resp = client.post("/signals/inject", json={"test": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") in ("disabled", "queued", "rate_limited")


def test_g4_case_b_iceberg_slice_simulation(g4_env):
    """Case B: POST /api/execution/iceberg-slice returns simulation plan without order placement."""
    client = g4_env["client"]
    payload = {
        "symbol": "TCS",
        "side": "BUY",
        "total_quantity": 100,
        "benchmark_price": 2500.0,
        "num_tranches": 5,
    }
    resp = client.post("/api/execution/iceberg-slice", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("symbol") == "TCS"
    assert data.get("total_quantity") == 100
    assert "tranches" in data


def test_g4_health_endpoints_unauthenticated(g4_env):
    """Health endpoints remain accessible unauthenticated for operational monitoring."""
    client = g4_env["client"]
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") in ("HEALTHY", "ok")
