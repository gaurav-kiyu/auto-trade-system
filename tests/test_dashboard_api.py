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
