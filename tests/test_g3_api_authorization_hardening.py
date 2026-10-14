"""Comprehensive security verification tests for Gate G3: API Authorization & Access-Control Hardening.

Verifies:
1. Unauthenticated requests to PUT /api/fundamentals/weights return 401 Unauthorized.
2. Authenticated requests with invalid token to PUT /api/fundamentals/weights return 401.
3. Authenticated requests with viewer role to PUT /api/fundamentals/weights return 403 Forbidden.
4. Authenticated requests with operator role to PUT /api/fundamentals/weights return 403 Forbidden.
5. Authenticated requests with admin role to PUT /api/fundamentals/weights return 200 OK.
6. Bearer token Authorization header with admin role works on PUT /api/fundamentals/weights.
7. Unauthenticated requests to POST /api/fundamentals/screen return 401 Unauthorized.
8. Authenticated requests with invalid token to POST /api/fundamentals/screen return 401.
9. Authenticated requests with viewer role to POST /api/fundamentals/screen return 403 Forbidden.
10. Authenticated requests with operator role to POST /api/fundamentals/screen return 200 OK.
11. Authenticated requests with admin role to POST /api/fundamentals/screen return 200 OK.
12. Bearer token Authorization header with operator role works on POST /api/fundamentals/screen.
13. Disabled admin account on PUT /api/fundamentals/weights is rejected with 403 Forbidden.
14. Disabled operator account on POST /api/fundamentals/screen is rejected with 403 Forbidden.
15. Unauthenticated requests to GET /api/fundamentals/weights return 200 OK (Case B verified).
16. Unauthenticated requests to GET /api/fundamentals/analyze/{symbol} return 200 OK (Case B verified).
17. Unauthenticated requests to GET /api/system/state return 200 OK (Case B verified).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _make_trades_db(db_path: str) -> None:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, symbol TEXT,
            expiry TEXT, direction TEXT, strike INTEGER, qty INTEGER,
            entry_price REAL, exit_price REAL, net_pnl REAL, pnl REAL,
            quantity INTEGER, mode TEXT, strategy TEXT, status TEXT,
            entry_time TEXT, exit_time TEXT, index_name TEXT, score INTEGER
        )
    """)
    conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def g3_env(tmp_path_factory):
    from core.enterprise_dashboard import EnterpriseDashboard
    from core.fundamental_analyzer import reset_fundamental_analyzer

    reset_fundamental_analyzer()

    tmp_path = tmp_path_factory.mktemp("g3_test")
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

    # Pre-create test users across roles
    admin_user = db._auth.get_user("admin")
    admin_token = db._auth.create_session(admin_user).token

    db._auth.create_user("operator_user", "OperatorPass123!", "operator")
    op_user = db._auth.get_user("operator_user")
    op_token = db._auth.create_session(op_user).token

    db._auth.create_user("viewer_user", "ViewerPass123!", "viewer")
    viewer_user = db._auth.get_user("viewer_user")
    viewer_token = db._auth.create_session(viewer_user).token

    db._auth.create_user("disabled_admin", "DisabledPass123!", "admin")
    disabled_admin = db._auth.get_user("disabled_admin")
    disabled_admin_token = db._auth.create_session(disabled_admin).token
    db._auth.disable_user("disabled_admin", admin_user.username)

    db._auth.create_user("disabled_operator", "DisabledPass123!", "operator")
    disabled_operator = db._auth.get_user("disabled_operator")
    disabled_op_token = db._auth.create_session(disabled_operator).token
    db._auth.disable_user("disabled_operator", admin_user.username)

    client = TestClient(db.app)

    return {
        "dashboard": db,
        "client": client,
        "admin_token": admin_token,
        "operator_token": op_token,
        "viewer_token": viewer_token,
        "disabled_admin_token": disabled_admin_token,
        "disabled_op_token": disabled_op_token,
    }


class TestG3FundamentalsWeightsAuthorization:
    """Verifies RBAC protection on PUT /api/fundamentals/weights (admin_only)."""

    def test_weights_put_unauthenticated_returns_401(self, g3_env):
        client = g3_env["client"]
        resp = client.put(
            "/api/fundamentals/weights",
            json={"weights": {"value": 0.4, "growth": 0.3, "quality": 0.2, "momentum": 0.1}},
        )
        assert resp.status_code == 401
        assert "Authentication required" in resp.text

    def test_weights_put_invalid_token_returns_401(self, g3_env):
        client = g3_env["client"]
        resp = client.put(
            "/api/fundamentals/weights",
            json={"weights": {"value": 0.4, "growth": 0.3, "quality": 0.2, "momentum": 0.1}},
            cookies={"opb_session": "forged_token_g3_99999"},
        )
        assert resp.status_code == 401

    def test_weights_put_viewer_role_returns_403(self, g3_env):
        client = g3_env["client"]
        resp = client.put(
            "/api/fundamentals/weights",
            json={"weights": {"value": 0.4, "growth": 0.3, "quality": 0.2, "momentum": 0.1}},
            cookies={"opb_session": g3_env["viewer_token"]},
            headers={"accept": "application/json"},
        )
        assert resp.status_code == 403

    def test_weights_put_operator_role_returns_403(self, g3_env):
        client = g3_env["client"]
        resp = client.put(
            "/api/fundamentals/weights",
            json={"weights": {"value": 0.4, "growth": 0.3, "quality": 0.2, "momentum": 0.1}},
            cookies={"opb_session": g3_env["operator_token"]},
            headers={"accept": "application/json"},
        )
        assert resp.status_code == 403

    def test_weights_put_admin_role_returns_200(self, g3_env):
        client = g3_env["client"]
        new_w = {"value": 0.35, "growth": 0.25, "quality": 0.25, "momentum": 0.15}
        resp = client.put(
            "/api/fundamentals/weights",
            json={"weights": new_w},
            cookies={"opb_session": g3_env["admin_token"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        assert data.get("weights") == new_w

    def test_weights_put_bearer_auth_returns_200(self, g3_env):
        client = g3_env["client"]
        new_w = {"value": 0.30, "growth": 0.30, "quality": 0.20, "momentum": 0.20}
        resp = client.put(
            "/api/fundamentals/weights",
            json={"weights": new_w},
            headers={"Authorization": f"Bearer {g3_env['admin_token']}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True

    def test_weights_put_disabled_admin_returns_403(self, g3_env):
        client = g3_env["client"]
        resp = client.put(
            "/api/fundamentals/weights",
            json={"weights": {"value": 0.25, "growth": 0.25, "quality": 0.25, "momentum": 0.25}},
            cookies={"opb_session": g3_env["disabled_admin_token"]},
            headers={"accept": "application/json"},
        )
        assert resp.status_code == 403


class TestG3FundamentalsScreenAuthorization:
    """Verifies RBAC protection on POST /api/fundamentals/screen (operator_or_admin)."""

    def test_screen_unauthenticated_returns_401(self, g3_env):
        client = g3_env["client"]
        resp = client.post(
            "/api/fundamentals/screen",
            json={"symbols": ["RELIANCE"]},
        )
        assert resp.status_code == 401
        assert "Authentication required" in resp.text

    def test_screen_invalid_token_returns_401(self, g3_env):
        client = g3_env["client"]
        resp = client.post(
            "/api/fundamentals/screen",
            json={"symbols": ["RELIANCE"]},
            cookies={"opb_session": "forged_token_screen_12345"},
        )
        assert resp.status_code == 401

    def test_screen_viewer_role_returns_403(self, g3_env):
        client = g3_env["client"]
        resp = client.post(
            "/api/fundamentals/screen",
            json={"symbols": ["RELIANCE"]},
            cookies={"opb_session": g3_env["viewer_token"]},
            headers={"accept": "application/json"},
        )
        assert resp.status_code == 403

    def test_screen_operator_role_returns_200(self, g3_env):
        client = g3_env["client"]
        resp = client.post(
            "/api/fundamentals/screen",
            json={"symbols": []},
            cookies={"opb_session": g3_env["operator_token"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("error") == "No symbols provided"

    def test_screen_admin_role_returns_200(self, g3_env):
        client = g3_env["client"]
        resp = client.post(
            "/api/fundamentals/screen",
            json={"symbols": []},
            cookies={"opb_session": g3_env["admin_token"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("error") == "No symbols provided"

    def test_screen_bearer_operator_returns_200(self, g3_env):
        client = g3_env["client"]
        resp = client.post(
            "/api/fundamentals/screen",
            json={"symbols": []},
            headers={"Authorization": f"Bearer {g3_env['operator_token']}"},
        )
        assert resp.status_code == 200

    def test_screen_disabled_operator_returns_403(self, g3_env):
        client = g3_env["client"]
        resp = client.post(
            "/api/fundamentals/screen",
            json={"symbols": []},
            cookies={"opb_session": g3_env["disabled_op_token"]},
            headers={"accept": "application/json"},
        )
        assert resp.status_code == 403


class TestG3PublicAndOptionalTelemetryContract:
    """Verifies Case B intentional unauthenticated access contracts remain preserved."""

    def test_fundamentals_weights_get_unauthenticated_returns_200(self, g3_env):
        client = g3_env["client"]
        resp = client.get("/api/fundamentals/weights")
        assert resp.status_code == 200
        data = resp.json()
        assert "weights" in data or "error" in data

    def test_fundamentals_analyze_unauthenticated_returns_200(self, g3_env):
        client = g3_env["client"]
        resp = client.get("/api/fundamentals/analyze/RELIANCE")
        assert resp.status_code == 200
        data = resp.json()
        assert "symbol" in data or "error" in data

    def test_system_state_unauthenticated_returns_200(self, g3_env):
        client = g3_env["client"]
        resp = client.get("/api/system/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "daily_pnl" in data
