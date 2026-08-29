"""Integration tests for enterprise dashboard API endpoints.

Tests non-HTML JSON endpoints only (avoiding Jinja2 version incompatibility).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def state_file(tmp_path: Path) -> str:
    p = tmp_path / "trader_state.json"
    p.write_text(json.dumps({
        "daily_pnl": 1500.0, "open_positions": 2, "hard_halt": False,
        "capital": 100000, "execution_mode": "paper", "total_trades": 42,
    }))
    return str(p)


@pytest.fixture()
def dashboard(state_file: str):
    from core.enterprise_dashboard import EnterpriseDashboard
    db = EnterpriseDashboard(config={
        "web_dashboard_host": "127.0.0.1",
        "web_dashboard_auth_token": "",
        "trader_state_path": state_file,
        "auth_db_path": str(Path(state_file).parent / "auth.db"),
        "manual_signal_db_path": str(Path(state_file).parent / "manual_signals.db"),
    })
    db.wire_bot_refs(
        pause_event=threading.Event(),
        signal_log=MagicMock(),
        ml_model_loaded=False,
    )
    return db


@pytest.fixture()
def client(dashboard) -> TestClient:
    return TestClient(dashboard.app)


# ── Business-Logic Tests (no HTTP) ───────────────────────────────────────────


class TestDashboardLogic:
    def test_dashboard_creation(self):
        from core.enterprise_dashboard import EnterpriseDashboard
        db = EnterpriseDashboard(config={"web_dashboard_host": "127.0.0.1"})
        assert db is not None
        assert db.app is not None

    def test_wire_refs(self):
        from core.enterprise_dashboard import EnterpriseDashboard
        db = EnterpriseDashboard()
        db.wire_bot_refs(pause_event="test", signal_log="test")
        assert db._pause_event == "test"
        assert db._signal_log == "test"

    def test_validate_config_ok(self):
        from core.enterprise_dashboard import EnterpriseDashboard
        db = EnterpriseDashboard()
        result = db._validate_config_change({"BASE_CAPITAL": 10000})
        assert result["valid"]

    def test_validate_config_env_ref(self):
        from core.enterprise_dashboard import EnterpriseDashboard
        db = EnterpriseDashboard()
        result = db._validate_config_change({"BOT_TOKEN": "${OPBUYING_BOT_TOKEN}"})
        assert result["valid"]
        assert len(result["warnings"]) > 0

    def test_preview_config(self):
        from core.enterprise_dashboard import EnterpriseDashboard
        db = EnterpriseDashboard(config={"BASE_CAPITAL": 5000})
        result = db._preview_config_change({"BASE_CAPITAL": 10000})
        assert result["total_changes"] == 1
        assert result["changed_keys"]["BASE_CAPITAL"]["old"] == 5000
        assert result["changed_keys"]["BASE_CAPITAL"]["new"] == 10000

    def test_execute_kill(self):
        from core.enterprise_dashboard import EnterpriseDashboard
        db = EnterpriseDashboard()
        db.wire_bot_refs(pause_event=threading.Event())
        result = db._execute_kill("Test kill", "admin")
        assert result["halted"]
        assert result["success"]

    def test_execute_resume(self):
        from core.enterprise_dashboard import EnterpriseDashboard
        pause = threading.Event()
        pause.set()
        db = EnterpriseDashboard()
        db.wire_bot_refs(pause_event=pause)
        result = db._execute_resume()
        assert not result["halted"]


# ── JSON API Endpoint Tests ───────────────────────────────────────────────────


class TestSystemState:
    def test_state(self, client: TestClient):
        resp = client.get("/api/system/state",
                          headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["daily_pnl"] == 1500.0
        assert data["open_positions"] == 2

    def test_state_reflects_file_changes(self, state_file: str, client: TestClient):
        state = json.loads(Path(state_file).read_text())
        state["daily_pnl"] = 999.0
        Path(state_file).write_text(json.dumps(state))
        resp = client.get("/api/system/state",
                          headers={"accept": "application/json"})
        assert resp.json()["daily_pnl"] == 999.0


class TestSystemHealth:
    def test_health(self, client: TestClient):
        resp = client.get("/api/system/health",
                          headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data


class TestBrokerML:
    def test_broker_info(self, client: TestClient):
        resp = client.get("/api/broker/info",
                          headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert "broker_name" in data
        assert "mode" in data

    def test_ml_status(self, client: TestClient):
        resp = client.get("/api/ml/status",
                          headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert "model_loaded" in data


class TestSystemEndpoints:
    def test_uptime(self, client: TestClient):
        resp = client.get("/api/system/uptime",
                          headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data.get("uptime_seconds"), (int, float))

    def test_trades(self, client: TestClient):
        resp = client.get("/api/system/trades",
                          headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_risk_concentration(self, client: TestClient):
        resp = client.get("/api/risk/concentration",
                          headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_docker_health(self, client: TestClient):
        resp = client.get("/api/system/health/docker",
                          headers={"accept": "application/json"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)


class TestKillSwitch:
    """Regression coverage for the kill-switch screen's confirmed bugs:
    the Resume button called /api/system/kill (re-triggering kill, never
    clearing the halt, while showing a false success toast), kill/resume
    never wrote an audit_log row the panel could show, and /api/system/
    kill-status never returned open_positions/capital/day_pnl at all."""

    @pytest.fixture()
    def admin_client(self, dashboard, monkeypatch) -> TestClient:
        from unittest.mock import AsyncMock

        from core.auth.csrf import csrf_protection
        monkeypatch.setattr(csrf_protection, "validate", AsyncMock(return_value=None))
        monkeypatch.setattr(csrf_protection, "ensure_cookie_set", AsyncMock(return_value=None))

        client = TestClient(dashboard.app)
        auth = dashboard._auth
        user = auth.get_user("admin")
        if not user:
            res = auth.create_user("admin", "AdminPassword123!", role="admin")
            user = auth.get_user_by_id(res["user_id"])
        session = auth.create_session(user)
        client.cookies.set("opb_session", session.token)
        return client

    def test_kill_then_resume_via_real_endpoints_clears_halt(self, dashboard, admin_client: TestClient):
        kill_resp = admin_client.post("/api/system/kill", json={"reason": "test halt"})
        assert kill_resp.status_code == 200
        assert dashboard._pause_event.is_set()

        resume_resp = admin_client.post("/api/system/resume", json={"reason": "test resume"})
        assert resume_resp.status_code == 200
        assert resume_resp.json()["success"]
        assert not resume_resp.json()["halted"]
        assert not dashboard._pause_event.is_set()

    def test_kill_and_resume_write_kill_switch_audit_entries(self, dashboard, admin_client: TestClient):
        admin_client.post("/api/system/kill", json={"reason": "test halt"})
        admin_client.post("/api/system/resume", json={"reason": "test resume"})
        log = dashboard._auth.get_audit_log(limit=20, event_type="kill_switch")
        actions = [e["details"].get("action") for e in log]
        assert "KILL" in actions
        assert "RESUME" in actions

    def test_kill_status_returns_position_and_capital_fields(self, admin_client: TestClient):
        resp = admin_client.get("/api/system/kill-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["open_positions"] == 2
        assert data["capital"] == 100000
        assert data["day_pnl"] == 1500.0


class TestPaperTradeQueue:
    """Regression coverage: the dashboard's 1-click 'Trade' button called
    /api/v1/trade/paper-trade, a route that never existed anywhere in the
    codebase - fetch() against a missing route resolves (404) rather than
    throwing, so the frontend's try/catch never fired and it showed a fake
    'trade executed' success alert on every click regardless. Now wired to
    the real ManualSignalQueue (core/manual_signal.py)."""

    @pytest.fixture()
    def user_client(self, dashboard, monkeypatch) -> TestClient:
        from unittest.mock import AsyncMock

        from core.auth.csrf import csrf_protection
        monkeypatch.setattr(csrf_protection, "validate", AsyncMock(return_value=None))
        monkeypatch.setattr(csrf_protection, "ensure_cookie_set", AsyncMock(return_value=None))

        client = TestClient(dashboard.app)
        auth = dashboard._auth
        user = auth.get_user("trader1")
        if not user:
            res = auth.create_user("trader1", "Xk7$mQz9Lp2!", role="viewer")
            user = auth.get_user_by_id(res["user_id"])
        session = auth.create_session(user)
        client.cookies.set("opb_session", session.token)
        return client

    def test_paper_trade_queues_a_real_manual_signal(self, dashboard, user_client: TestClient):
        resp = user_client.post(
            "/api/v1/trade/paper-trade",
            json={"symbol": "NIFTY", "direction": "CALL", "score": 82},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"]
        assert data["status"] == "queued"
        assert data["signal_id"]

        pending = dashboard._manual_signal_queue.get_pending()
        assert any(s.signal_id == data["signal_id"] for s in pending)
        matched = next(s for s in pending if s.signal_id == data["signal_id"])
        assert matched.index_name == "NIFTY"
        assert matched.direction == "CALL"
        assert matched.analyst_name == "trader1"
        assert matched.source == "DASHBOARD"

    def test_paper_trade_requires_login(self, dashboard):
        client = TestClient(dashboard.app)
        resp = client.post("/api/v1/trade/paper-trade", json={"symbol": "NIFTY"})
        assert resp.status_code in (401, 403)

    def test_paper_trade_requires_symbol(self, user_client: TestClient):
        resp = user_client.post("/api/v1/trade/paper-trade", json={})
        assert resp.status_code == 200
        assert resp.json()["success"] is False


class TestAuthEndpoints:
    @pytest.fixture()
    def auth_dashboard(self, state_file: str):
        from core.enterprise_dashboard import EnterpriseDashboard
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "0.0.0.0",
            "web_dashboard_auth_token": "test-auth-token-123",
            "trader_state_path": state_file,
            "auth_db_path": str(Path(state_file).parent / "auth.db"),
        })
        db.wire_bot_refs(pause_event=threading.Event())
        return db

    def test_config_no_auth_returns_401(self, auth_dashboard):
        c = TestClient(auth_dashboard.app)
        resp = c.get("/api/config", headers={"accept": "application/json"})
        assert resp.status_code == 401

    def test_system_state_no_auth_allowed(self, auth_dashboard):
        """System state endpoint does NOT require admin role."""
        c = TestClient(auth_dashboard.app)
        resp = c.get("/api/system/state",
                     headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert "daily_pnl" in data

    def test_broker_info_no_auth_allowed(self, auth_dashboard):
        """Broker info endpoint does NOT require admin role."""
        c = TestClient(auth_dashboard.app)
        resp = c.get("/api/broker/info",
                     headers={"accept": "application/json"})
        assert resp.status_code == 200

    def test_api_system_state_auth_no_token(self, auth_dashboard):
        c = TestClient(auth_dashboard.app)
        resp = c.get("/api/system/state",
                     headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert "daily_pnl" in data
