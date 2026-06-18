"""Integration tests for /api/config/drift with real config files.

Tests the config drift detection endpoint end-to-end by creating real
config files with known drifts and verifying the API detects them
correctly.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


# ==============================================================================
# Helpers
# ==============================================================================

_DASHBOARD_KEYS = {
    "web_dashboard_host": "127.0.0.1",
    "web_dashboard_auth_token": "",
}


def _make_defaults_file(path: Path, **extra_defaults: str) -> Path:
    """Write defaults JSON including matched dashboard keys.

    Includes ``_DASHBOARD_KEYS`` plus any *extra_defaults`` so the
    defaults file has values that match what ``EnterpriseDashboard`` will
    store in ``self._cfg``.
    """
    defaults = {
        "BASE_CAPITAL": 200000,
        "MAX_DAILY_LOSS": -2000,
        "EXECUTION_MODE": "paper",
        "SL_PCT": 0.92,
        "TARGET_PCT": 1.30,
        "TRAIL_PCT": 0.93,
        "ENABLE_NEWS_SENTINEL": True,
        "MAX_OPEN": 5,
        **_DASHBOARD_KEYS,
        **extra_defaults,
    }
    path.write_text(json.dumps(defaults, sort_keys=True), encoding="utf-8")
    return path


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture()
def trader_state(tmp_path: Path) -> Path:
    p = tmp_path / "trader_state.json"
    p.write_text(json.dumps({
        "daily_pnl": 0.0, "open_positions": 0, "hard_halt": False,
        "capital": 100000, "execution_mode": "paper",
    }))
    return p


@pytest.fixture()
def defaults_only(tmp_path: Path) -> Path:
    """Defaults with dashboard keys (empty-str paths that match the pattern)."""
    return _make_defaults_file(
        tmp_path / "index_config.defaults.json",
        trader_state_path="",
        auth_db_path="",
        index_config_defaults_path="",
    )


def _build_dashboard_config(
    trader_state: Path,
    defaults: Path,
    **extra: object,
) -> tuple[Path, dict]:
    """Write a defaults file with correct dashboard paths and return config dict.

    Creates a defaults file whose ``trader_state_path`` / ``auth_db_path`` /
    ``index_config_defaults_path`` match exactly what the dashboard's own
    config dict will contain, so those keys don't register as drift.
    """
    dflt = _make_defaults_file(
        defaults,
        trader_state_path=str(trader_state),
        auth_db_path=str(trader_state.parent / "auth.db"),
        index_config_defaults_path=str(defaults),
    )
    cfg = {
        "web_dashboard_host": "127.0.0.1",
        "web_dashboard_auth_token": "",
        "trader_state_path": str(trader_state),
        "auth_db_path": str(trader_state.parent / "auth.db"),
        "index_config_defaults_path": str(defaults),
        **extra,
    }
    return dflt, cfg


def _create_admin(db, username: str) -> str:
    """Create an admin user and return the session token value."""
    result = db._auth.create_user(username, "IntT3st@!", role="admin")
    assert result.get("success"), f"Failed to create user: {result}"
    user = db._auth.get_user(username)
    assert user is not None
    token = db._auth.create_session(user, ip_address="127.0.0.1")
    return token.token


# ==============================================================================
# Integration Tests
# ==============================================================================


class TestConfigDriftIntegration:
    """End-to-end integration tests for config drift detection."""

    def test_zero_drift_when_config_matches_defaults(self, trader_state: Path, tmp_path: Path):
        """When live config matches defaults exactly, drift should be 0%."""
        from core.enterprise_dashboard import EnterpriseDashboard

        dflt, cfg = _build_dashboard_config(trader_state, tmp_path / "index_config.defaults.json")
        # Include ALL default app keys with matching values
        app_defaults = {
            "BASE_CAPITAL": 200000,
            "MAX_DAILY_LOSS": -2000,
            "EXECUTION_MODE": "paper",
            "SL_PCT": 0.92,
            "TARGET_PCT": 1.30,
            "TRAIL_PCT": 0.93,
            "ENABLE_NEWS_SENTINEL": True,
            "MAX_OPEN": 5,
        }
        cfg.update(app_defaults)

        db = EnterpriseDashboard(config=cfg)
        db.wire_bot_refs(pause_event=threading.Event(), signal_log=MagicMock())
        session_val = _create_admin(db, "drift_int")

        c = TestClient(db.app)
        resp = c.get("/api/config/drift", cookies={"opb_session": session_val})
        data = resp.json()
        assert data["drift_pct"] == 0.0
        assert data["changed_count"] == 0
        assert data["added_count"] == 0
        assert data["removed_count"] == 0
        assert data["drift_count"] == 0

    def test_type_change_is_drift(self, trader_state: Path, tmp_path: Path):
        """Same key but different type should register as drift."""
        from core.enterprise_dashboard import EnterpriseDashboard

        dflt, cfg = _build_dashboard_config(trader_state, tmp_path / "index_config.defaults.json")
        cfg["MAX_OPEN"] = "5"  # string instead of int

        db = EnterpriseDashboard(config=cfg)
        db.wire_bot_refs(pause_event=threading.Event(), signal_log=MagicMock())
        session_val = _create_admin(db, "drift_int")

        c = TestClient(db.app)
        resp = c.get("/api/config/drift", cookies={"opb_session": session_val})
        data = resp.json()
        assert data["changed_count"] == 1
        drifts = {ch["key"]: ch for ch in data["changes"]}
        assert "MAX_OPEN" in drifts
        assert drifts["MAX_OPEN"]["default"] == 5
        assert drifts["MAX_OPEN"]["current"] == "5"

    def test_added_keys_detected(self, trader_state: Path, tmp_path: Path):
        """Keys in live config but not in defaults should appear in added_keys."""
        from core.enterprise_dashboard import EnterpriseDashboard

        dflt, cfg = _build_dashboard_config(trader_state, tmp_path / "index_config.defaults.json")
        cfg["NEW_KEY_1"] = "custom_value"
        cfg["NEW_KEY_2"] = 999

        db = EnterpriseDashboard(config=cfg)
        db.wire_bot_refs(pause_event=threading.Event(), signal_log=MagicMock())
        session_val = _create_admin(db, "drift_int")

        c = TestClient(db.app)
        resp = c.get("/api/config/drift", cookies={"opb_session": session_val})
        data = resp.json()
        assert data["added_count"] == 2
        assert "NEW_KEY_1" in data["added_keys"]
        assert "NEW_KEY_2" in data["added_keys"]

    def test_removed_keys_detected(self, trader_state: Path, tmp_path: Path):
        """Keys in defaults but missing from live config should appear in removed_keys."""
        from core.enterprise_dashboard import EnterpriseDashboard

        dflt, cfg = _build_dashboard_config(trader_state, tmp_path / "index_config.defaults.json")
        # Don't pass SL_PCT or TRAIL_PCT — they'll be absent from live config
        # but present in defaults

        db = EnterpriseDashboard(config=cfg)
        db.wire_bot_refs(pause_event=threading.Event(), signal_log=MagicMock())
        session_val = _create_admin(db, "drift_int")

        c = TestClient(db.app)
        resp = c.get("/api/config/drift", cookies={"opb_session": session_val})
        data = resp.json()
        assert data["removed_count"] >= 2
        removed_set = set(data["removed_keys"])
        assert "SL_PCT" in removed_set
        assert "TRAIL_PCT" in removed_set

    def test_realistic_drift_scenario(self, trader_state: Path, tmp_path: Path):
        """Production-like scenario: 2 changed, 1 added, 1 removed."""
        from core.enterprise_dashboard import EnterpriseDashboard

        dflt, cfg = _build_dashboard_config(trader_state, tmp_path / "index_config.defaults.json")
        cfg["BASE_CAPITAL"] = 500000        # changed
        cfg["MAX_DAILY_LOSS"] = -5000       # changed
        cfg["CUSTOM_STOP_LOSS"] = 0.85      # added

        db = EnterpriseDashboard(config=cfg)
        db.wire_bot_refs(pause_event=threading.Event(), signal_log=MagicMock())
        session_val = _create_admin(db, "drift_int")

        c = TestClient(db.app)
        resp = c.get("/api/config/drift", cookies={"opb_session": session_val})
        data = resp.json()
        assert data["changed_count"] == 2
        assert data["added_count"] == 1
        assert data["removed_count"] >= 1
        assert data["drift_count"] >= 4
        assert data["drift_pct"] > 0

        changed_keys = {ch["key"] for ch in data["changes"]}
        assert "BASE_CAPITAL" in changed_keys
        assert "MAX_DAILY_LOSS" in changed_keys

    def test_drift_pct_formula(self, trader_state: Path, tmp_path: Path):
        """drift_pct should be (drift_count / total_keys) * 100."""
        from core.enterprise_dashboard import EnterpriseDashboard

        dflt, cfg = _build_dashboard_config(trader_state, tmp_path / "index_config.defaults.json")
        cfg["ADDED_1"] = True
        cfg["ADDED_2"] = True

        db = EnterpriseDashboard(config=cfg)
        db.wire_bot_refs(pause_event=threading.Event(), signal_log=MagicMock())
        session_val = _create_admin(db, "drift_int")

        c = TestClient(db.app)
        resp = c.get("/api/config/drift", cookies={"opb_session": session_val})
        data = resp.json()
        expected_pct = round((data["drift_count"] / max(data["total_keys"], 1)) * 100, 1)
        assert data["drift_pct"] == expected_pct

    def test_drift_with_nested_values(self, trader_state: Path, tmp_path: Path):
        """Drift endpoint handles nested dict values without crashing."""
        from core.enterprise_dashboard import EnterpriseDashboard

        dflt, cfg = _build_dashboard_config(trader_state, tmp_path / "index_config.defaults.json")
        cfg["BROKER_CONFIG"] = {"api_key": "test", "secret": "redacted"}

        db = EnterpriseDashboard(config=cfg)
        db.wire_bot_refs(pause_event=threading.Event(), signal_log=MagicMock())
        session_val = _create_admin(db, "drift_int")

        c = TestClient(db.app)
        resp = c.get("/api/config/drift", cookies={"opb_session": session_val})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") != "error"
        # BROKER_CONFIG is not in defaults so it appears in added_keys
        assert "BROKER_CONFIG" in data.get("added_keys", [])

    def test_rapid_consecutive_calls(self, trader_state: Path, defaults_only: Path):
        """5 rapid calls to drift endpoint should all succeed."""
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "web_dashboard_auth_token": "",
            "trader_state_path": str(trader_state),
            "auth_db_path": str(trader_state.parent / "auth.db"),
            "index_config_defaults_path": str(defaults_only),
        })
        db.wire_bot_refs(pause_event=threading.Event(), signal_log=MagicMock())
        session_val = _create_admin(db, "drift_int")

        c = TestClient(db.app)
        for _ in range(5):
            resp = c.get("/api/config/drift", cookies={"opb_session": session_val})
            assert resp.status_code == 200
            data = resp.json()
            assert "drift_pct" in data

    def test_response_time(self, trader_state: Path, defaults_only: Path):
        """Drift endpoint response should complete in under 500ms."""
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "web_dashboard_auth_token": "",
            "trader_state_path": str(trader_state),
            "auth_db_path": str(trader_state.parent / "auth.db"),
            "index_config_defaults_path": str(defaults_only),
        })
        db.wire_bot_refs(pause_event=threading.Event(), signal_log=MagicMock())
        session_val = _create_admin(db, "drift_int")

        c = TestClient(db.app)
        start = time.perf_counter()
        resp = c.get("/api/config/drift", cookies={"opb_session": session_val})
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, f"Drift endpoint too slow: {elapsed*1000:.0f}ms"
        assert resp.status_code == 200
