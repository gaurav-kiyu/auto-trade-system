"""Comprehensive security verification tests for Gate G2: API Authentication Hardening.

Verifies:
1. Unauthenticated requests to /api/system/signals return 401 Unauthorized.
2. Authenticated requests to /api/system/signals return 200 OK.
3. Bearer token authorization header works on /api/system/signals.
4. Unauthenticated requests to /api/system/trades return 401 Unauthorized.
5. Authenticated requests to /api/system/trades return 200 OK.
6. Unauthenticated requests to /api/system/performance return 401 Unauthorized.
7. Authenticated requests to /api/system/performance return 200 OK.
8. Unauthenticated requests to /api/trade-journal return 401 Unauthorized.
9. Authenticated requests to /api/trade-journal return 200 OK.
10. Unauthenticated requests to /api/system/trades/export return 401 Unauthorized.
11. Authenticated requests to /api/system/trades/export return 200 OK.
12. Intentionally public health endpoints (/api/system/health/docker) remain 200 OK without auth.
13. Role matrix verification: viewer, operator, admin all succeed once authenticated.
14. Disabled account sessions are rejected with 403 Forbidden.
15. Invalid / forged session tokens are rejected with 401 Unauthorized.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
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
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    trades = [
        (1, now, "NIFTY", "25MAY2026", "CALL", 25000, 75, 150.0, 185.0, 2625.0, 2625.0, 75,
         "PAPER", "BUY", "closed", now, now, "NIFTY", 85),
        (2, now, "BANKNIFTY", "25MAY2026", "PUT", 51000, 50, 200.0, 140.0, -3000.0, -3000.0, 50,
         "PAPER", "SELL", "closed", now, now, "BANKNIFTY", 45),
    ]
    conn.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", trades)
    conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def g2_env(tmp_path_factory):
    from core.enterprise_dashboard import EnterpriseDashboard

    tmp_path = tmp_path_factory.mktemp("g2_test")
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
    signal_log_mock.recent.return_value = [
        {"symbol": "NIFTY26AUG24050CE", "direction": "BUY", "score": 8.8, "strength": "STRONG"}
    ]
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

    db._auth.create_user("disabled_user", "DisabledPass123!", "viewer")
    disabled_user = db._auth.get_user("disabled_user")
    disabled_token = db._auth.create_session(disabled_user).token
    db._auth.disable_user("disabled_user", admin_user.username)

    client = TestClient(db.app)

    return {
        "dashboard": db,
        "client": client,
        "admin_token": admin_token,
        "operator_token": op_token,
        "viewer_token": viewer_token,
        "disabled_token": disabled_token,
    }


class TestG2SignalsAuthentication:
    def test_signals_unauthenticated_returns_401(self, g2_env):
        client = g2_env["client"]
        resp = client.get("/api/system/signals")
        assert resp.status_code == 401
        assert "Authentication required" in resp.text

    def test_signals_invalid_token_returns_401(self, g2_env):
        client = g2_env["client"]
        resp = client.get(
            "/api/system/signals",
            cookies={"opb_session": "forged_nonexistent_token_12345"},
        )
        assert resp.status_code == 401

    def test_signals_authenticated_cookie_returns_200(self, g2_env):
        client = g2_env["client"]
        resp = client.get(
            "/api/system/signals",
            cookies={"opb_session": g2_env["admin_token"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_signals_bearer_header_returns_200(self, g2_env):
        client = g2_env["client"]
        resp = client.get(
            "/api/system/signals",
            headers={"Authorization": f"Bearer {g2_env['admin_token']}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


class TestG2TradesAuthentication:
    def test_trades_unauthenticated_returns_401(self, g2_env):
        client = g2_env["client"]
        resp = client.get("/api/system/trades")
        assert resp.status_code == 401

    def test_trades_authenticated_cookie_returns_200(self, g2_env):
        client = g2_env["client"]
        resp = client.get(
            "/api/system/trades",
            cookies={"opb_session": g2_env["admin_token"]},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestG2PerformanceAuthentication:
    def test_performance_unauthenticated_returns_401(self, g2_env):
        client = g2_env["client"]
        resp = client.get("/api/system/performance")
        assert resp.status_code == 401

    def test_performance_authenticated_cookie_returns_200(self, g2_env):
        client = g2_env["client"]
        resp = client.get(
            "/api/system/performance",
            cookies={"opb_session": g2_env["admin_token"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "win_rate" in data
        assert "profit_factor" in data


class TestG2TradeJournalAuthentication:
    def test_trade_journal_unauthenticated_returns_401(self, g2_env):
        client = g2_env["client"]
        resp = client.get("/api/trade-journal")
        assert resp.status_code == 401

    def test_trade_journal_authenticated_cookie_returns_200(self, g2_env):
        client = g2_env["client"]
        resp = client.get(
            "/api/trade-journal",
            cookies={"opb_session": g2_env["admin_token"]},
        )
        assert resp.status_code == 200
        assert "trades" in resp.json()


class TestG2TradesExportAuthentication:
    def test_trades_export_unauthenticated_returns_401(self, g2_env):
        client = g2_env["client"]
        resp = client.get("/api/system/trades/export")
        assert resp.status_code == 401

    def test_trades_export_authenticated_cookie_returns_200(self, g2_env):
        client = g2_env["client"]
        resp = client.get(
            "/api/system/trades/export",
            cookies={"opb_session": g2_env["admin_token"]},
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")


class TestG2RoleMatrixAndInvariants:
    def test_docker_health_remains_public(self, g2_env):
        client = g2_env["client"]
        resp = client.get("/api/system/health/docker")
        assert resp.status_code == 200
        assert resp.json().get("status") in ("ok", "healthy")

    def test_viewer_role_access(self, g2_env):
        client = g2_env["client"]
        resp = client.get(
            "/api/system/signals",
            cookies={"opb_session": g2_env["viewer_token"]},
        )
        assert resp.status_code == 200

    def test_operator_role_access(self, g2_env):
        client = g2_env["client"]
        resp = client.get(
            "/api/system/signals",
            cookies={"opb_session": g2_env["operator_token"]},
        )
        assert resp.status_code == 200

    def test_disabled_user_returns_403(self, g2_env):
        client = g2_env["client"]
        resp = client.get(
            "/api/system/signals",
            cookies={"opb_session": g2_env["disabled_token"]},
            headers={"accept": "application/json"},
        )
        assert resp.status_code == 403
        assert resp.json().get("code") == 403
