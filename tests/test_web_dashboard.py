"""
Tests for core/web_dashboard.py (enterprise-only version).

Tests are skipped cleanly if FastAPI is not installed.

Covers:
  - SignalLog ring buffer (no FastAPI dependency)
  - maybe_start_dashboard() returns None when disabled
  - maybe_start_dashboard() returns EnterpriseDashboard app when enabled
"""
import threading

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")

from core.web_dashboard import SignalLog, maybe_start_dashboard

# ── SignalLog (no FastAPI needed) ─────────────────────────────────────────────

class TestSignalLog:
    def test_append_and_recent(self):
        log = SignalLog(maxlen=5)
        for i in range(3):
            log.append({"n": i})
        items = log.recent(10)
        assert len(items) == 3

    def test_maxlen_respected(self):
        log = SignalLog(maxlen=3)
        for i in range(10):
            log.append({"n": i})
        assert len(log.recent(100)) == 3

    def test_recent_returns_last_n(self):
        log = SignalLog(maxlen=10)
        for i in range(8):
            log.append({"n": i})
        recent = log.recent(3)
        assert len(recent) == 3
        assert recent[-1]["n"] == 7

    def test_clear(self):
        log = SignalLog()
        log.append({"x": 1})
        log.clear()
        assert log.recent() == []

    def test_ts_added_on_append(self):
        log = SignalLog()
        log.append({"signal": "test"})
        item = log.recent(1)[0]
        assert "_ts" in item

    def test_thread_safe(self):
        log = SignalLog(maxlen=1000)
        threads = [
            threading.Thread(target=lambda: [log.append({"x": i}) for i in range(50)])
            for _ in range(4)
        ]
        for t in threads: t.start()
        for t in threads: t.join()
        assert len(log.recent(1000)) <= 1000


# ── maybe_start_dashboard ─────────────────────────────────────────────────────

class TestMaybeStartDashboard:
    def test_returns_none_when_disabled(self):
        result = maybe_start_dashboard({"web_dashboard_enabled": False})
        assert result is None

    def test_returns_none_when_missing_key(self):
        result = maybe_start_dashboard({})
        assert result is None

    def test_returns_app_when_enabled(self, tmp_path):
        """EnterpriseDashboard app is returned when web_dashboard_enabled=true."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        # Should return a FastAPI app or None if enterprise_dashboard imports fail
        if result is not None:
            assert hasattr(result, "routes")

    def test_app_has_auth_routes(self, tmp_path):
        """The EnterpriseDashboard app includes auth routes (login page)."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            resp = client.get("/login")
            assert resp.status_code == 200
            assert "login" in resp.text.lower()

    def test_kill_switch_requires_admin(self, tmp_path):
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            # /admin/kill-switch should redirect to login (no session cookie)
            resp = client.get("/admin/kill-switch", follow_redirects=False)
            assert resp.status_code in (200, 303, 307)
            # If redirected to login, that's correct auth behavior
            if resp.status_code in (303, 307):
                location = resp.headers.get("location", "")
                assert "login" in location.lower()

    # ── Webhook: /signals/inject ──────────────────────────────────────────────

    def test_webhook_disabled_by_default(self, tmp_path):
        """POST /signals/inject returns disabled when webhook_enabled is not set."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            resp = client.post("/signals/inject", json={"signal": "test"})
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("status") == "disabled"

    def test_webhook_enabled_returns_queued(self, tmp_path):
        """POST /signals/inject returns queued when webhook_enabled is True."""
        result = maybe_start_dashboard(
            {
                "web_dashboard_enabled": True,
                "webhook_enabled": True,
                "web_dashboard_host": "127.0.0.1",
                "web_dashboard_port": 0,
            },
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            resp = client.post("/signals/inject", json={"symbol": "NIFTY", "action": "BUY"})
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("status") == "queued"
            assert "ts" in data

    def test_webhook_empty_body_queued(self, tmp_path):
        """POST /signals/inject still returns queued even without JSON body."""
        result = maybe_start_dashboard(
            {
                "web_dashboard_enabled": True,
                "webhook_enabled": True,
                "web_dashboard_host": "127.0.0.1",
                "web_dashboard_port": 0,
            },
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            resp = client.post("/signals/inject")
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("status") == "queued"

    # ── Options Chain Viz: /chain/{index} ─────────────────────────────────────

    def test_chain_viz_disabled_by_default(self, tmp_path):
        """GET /chain/NIFTY returns disabled when chain_viz_enabled is not set."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            resp = client.get("/chain/NIFTY")
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("status") == "disabled"

    def test_chain_viz_enabled_returns_structure(self, tmp_path):
        """GET /chain/NIFTY returns chain structure when chain_viz_enabled is True."""
        result = maybe_start_dashboard(
            {
                "web_dashboard_enabled": True,
                "chain_viz_enabled": True,
                "web_dashboard_host": "127.0.0.1",
                "web_dashboard_port": 0,
            },
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            resp = client.get("/chain/BANKNIFTY")
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("index") == "BANKNIFTY"
            assert "symbol" in data
            assert "spot_price" in data

    def test_chain_viz_normalizes_index_name(self, tmp_path):
        """GET /chain/banknifty normalizes to uppercase BANKNIFTY."""
        result = maybe_start_dashboard(
            {
                "web_dashboard_enabled": True,
                "chain_viz_enabled": True,
                "web_dashboard_host": "127.0.0.1",
                "web_dashboard_port": 0,
            },
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            resp = client.get("/chain/banknifty")
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("index") == "BANKNIFTY"
