"""Tests for /api/config/drift endpoint.

Tests the config drift detection endpoint that compares live config
against defaults. Creates admin sessions directly via dashboard._auth
to avoid CSRF issues with HTTP-based auth.
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
def defaults_file(tmp_path: Path) -> str:
    p = tmp_path / "index_config.defaults.json"
    p.write_text(json.dumps({
        "BASE_CAPITAL": 200000,
        "MAX_DAILY_LOSS": 1000,
        "EXECUTION_MODE": "paper",
        "SL_PCT": 0.05,
        "TARGET_PCT": 0.10,
    }))
    return str(p)


@pytest.fixture()
def dashboard_with_admin(state_file: str, defaults_file: str):
    """Create EnterpriseDashboard and return (dashboard, session_cookie)."""
    from core.enterprise_dashboard import EnterpriseDashboard

    db = EnterpriseDashboard(config={
        "web_dashboard_host": "127.0.0.1",
        "web_dashboard_auth_token": "",
        "trader_state_path": state_file,
        "auth_db_path": str(Path(state_file).parent / "auth.db"),
        "index_config_defaults_path": defaults_file,
    })
    db.wire_bot_refs(
        pause_event=threading.Event(),
        signal_log=MagicMock(),
        ml_model_loaded=False,
    )

    # Create an admin user directly and get session
    result = db._auth.create_user("drift_tester", "DriftT3st@!", role="admin")
    assert result.get("success"), f"Failed to create test user: {result}"
    user = db._auth.get_user("drift_tester")
    assert user is not None, "User not found after creation"
    token = db._auth.create_session(user, ip_address="127.0.0.1")
    session_val = token.token

    return db, session_val


@pytest.fixture()
def dashboard(state_file: str, defaults_file: str):
    """Create EnterpriseDashboard without admin user (for auth - test)."""
    from core.enterprise_dashboard import EnterpriseDashboard
    db = EnterpriseDashboard(config={
        "web_dashboard_host": "127.0.0.1",
        "web_dashboard_auth_token": "",
        "trader_state_path": state_file,
        "auth_db_path": str(Path(state_file).parent / "auth.db"),
        "index_config_defaults_path": defaults_file,
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


# ── Config Drift Tests ────────────────────────────────────────────────────────


class TestConfigDrift:
    """Tests for the /api/config/drift endpoint."""

    def test_drift_no_auth_returns_401(self, state_file: str):
        """Admin-only endpoint should return 401 without auth."""
        from core.enterprise_dashboard import EnterpriseDashboard
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "0.0.0.0",
            "web_dashboard_auth_token": "test-token",
            "trader_state_path": state_file,
            "auth_db_path": str(Path(state_file).parent / "auth.db"),
        })
        db.wire_bot_refs(pause_event=threading.Event())
        c = TestClient(db.app)
        resp = c.get("/api/config/drift", headers={"accept": "application/json"})
        assert resp.status_code == 401

    def test_drift_returns_dict(self, dashboard_with_admin):
        """Drift endpoint should return a dict."""
        db, session_val = dashboard_with_admin
        c = TestClient(db.app)
        resp = c.get("/api/config/drift",
                     cookies={"opb_session": session_val},
                     headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_drift_has_keys(self, dashboard_with_admin):
        """Drift response should contain expected top-level keys."""
        db, session_val = dashboard_with_admin
        c = TestClient(db.app)
        resp = c.get("/api/config/drift",
                     cookies={"opb_session": session_val},
                     headers={"accept": "application/json"})
        data = resp.json()
        assert "drift_pct" in data
        assert "drift_count" in data
        assert "total_keys" in data
        assert "changed_count" in data
        assert "added_count" in data
        assert "removed_count" in data
        assert "changes" in data
        assert "added_keys" in data
        assert "removed_keys" in data
        assert "timestamp" in data

    def test_drift_pct_is_float(self, dashboard_with_admin):
        """drift_pct should be a float between 0 and 100."""
        db, session_val = dashboard_with_admin
        c = TestClient(db.app)
        resp = c.get("/api/config/drift",
                     cookies={"opb_session": session_val},
                     headers={"accept": "application/json"})
        data = resp.json()
        assert isinstance(data["drift_pct"], (int, float))
        assert 0 <= data["drift_pct"] <= 100

    def test_drift_count_matches_total(self, dashboard_with_admin):
        """drift_count should equal sum of changed + added + removed counts."""
        db, session_val = dashboard_with_admin
        c = TestClient(db.app)
        resp = c.get("/api/config/drift",
                     cookies={"opb_session": session_val},
                     headers={"accept": "application/json"})
        data = resp.json()
        expected = data["changed_count"] + data["added_count"] + data["removed_count"]
        assert data["drift_count"] == expected

    def test_drift_changed_keys_for_live_diff(self, state_file: str, defaults_file: str):
        """Live config with custom key should show as changed."""
        from core.enterprise_dashboard import EnterpriseDashboard
        from core.auth.handler import AuthHandler

        # Create dashboard with drifted BASE_CAPITAL
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "web_dashboard_auth_token": "",
            "trader_state_path": state_file,
            "auth_db_path": str(Path(state_file).parent / "auth.db"),
            "index_config_defaults_path": defaults_file,
            "BASE_CAPITAL": 500000,  # differs from default 200000
        })
        db.wire_bot_refs(pause_event=threading.Event(), signal_log=MagicMock())

        # Create admin user and get session
        result = db._auth.create_user("drift_tester", "DriftT3st@!", role="admin")
        assert result.get("success"), f"Failed to create test user: {result}"
        user = db._auth.get_user("drift_tester")
        assert user is not None
        token = db._auth.create_session(user, ip_address="127.0.0.1")
        session_val = token.token

        c = TestClient(db.app)
        resp = c.get("/api/config/drift",
                     cookies={"opb_session": session_val},
                     headers={"accept": "application/json"})
        data = resp.json()
        changed_keys = [ch["key"] for ch in data["changes"]]
        assert "BASE_CAPITAL" in changed_keys
        assert data["changed_count"] >= 1

    def test_drift_timestamp_is_recent(self, dashboard_with_admin):
        """Timestamp should be within the last 30 seconds."""
        import time
        db, session_val = dashboard_with_admin
        c = TestClient(db.app)
        resp = c.get("/api/config/drift",
                     cookies={"opb_session": session_val},
                     headers={"accept": "application/json"})
        data = resp.json()
        now = time.time()
        assert abs(now - data["timestamp"]) < 30

    def test_drift_without_defaults_path(self, state_file: str):
        """When no index_config_defaults_path is set, drift still returns gracefully."""
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "web_dashboard_auth_token": "",
            "trader_state_path": state_file,
            "auth_db_path": str(Path(state_file).parent / "auth.db"),
        })
        db.wire_bot_refs(pause_event=threading.Event(), signal_log=MagicMock())

        result = db._auth.create_user("drift_tester", "DriftT3st@!", role="admin")
        assert result.get("success"), f"Failed to create test user: {result}"
        user = db._auth.get_user("drift_tester")
        assert user is not None
        token = db._auth.create_session(user, ip_address="127.0.0.1")
        session_val = token.token

        c = TestClient(db.app)
        resp = c.get("/api/config/drift",
                     cookies={"opb_session": session_val},
                     headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "drift_pct" in data
