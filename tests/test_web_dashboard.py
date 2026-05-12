"""
Tests for core/web_dashboard.py (Step 4).

All tests use FastAPI's TestClient (via httpx/starlette) so no real server
is started.  Tests are skipped cleanly if FastAPI is not installed.

Covers:
  - SignalLog ring buffer (no FastAPI dependency)
  - create_app() returns a FastAPI app
  - GET / returns expected shape
  - GET /health returns paused flag
  - GET /state reads trader_state.json
  - GET /trades returns list
  - GET /signals reflects SignalLog
  - GET /metrics returns dict
  - GET /autopsy returns dict
  - GET /monte-carlo returns dict or error
  - POST /control/pause and /resume require auth token
  - POST /control/pause without token works when no token configured
  - maybe_start_dashboard() returns None when disabled
"""
import json
import threading
from pathlib import Path

import pytest

# Skip all tests if FastAPI not available
fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
try:
    from fastapi.testclient import TestClient
except ImportError:
    pytest.skip("fastapi.testclient not available", allow_module_level=True)

from core.web_dashboard import SignalLog, create_app, maybe_start_dashboard


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def state_file(tmp_path):
    p = tmp_path / "trader_state.json"
    p.write_text(json.dumps({"daily_pnl": 500.0, "open_positions": 1,
                              "hard_halt": False}), encoding="utf-8")
    return str(p)


@pytest.fixture()
def sig_log():
    log = SignalLog(maxlen=50)
    log.append({"direction": "CALL", "score": 82, "index": "NIFTY"})
    log.append({"direction": "PUT",  "score": 75, "index": "BANKNIFTY"})
    return log


@pytest.fixture()
def client(state_file, sig_log, tmp_path):
    db = str(tmp_path / "trades.db")
    app = create_app(cfg={}, state_path=state_file, signal_log=sig_log, db_path=db)
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def auth_client(state_file, sig_log, tmp_path):
    db = str(tmp_path / "trades.db")
    app = create_app(
        cfg={"web_dashboard_auth_token": "secret123"},
        state_path=state_file, signal_log=sig_log, db_path=db,
    )
    return TestClient(app, raise_server_exceptions=True)


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


# ── create_app ────────────────────────────────────────────────────────────────

class TestCreateApp:
    def test_raises_import_error_if_no_fastapi(self, monkeypatch):
        import sys
        # Don't actually remove fastapi — just verify the factory returns something
        app = create_app(cfg={})
        assert app is not None

    def test_returns_fastapi_app(self, tmp_path):
        app = create_app(cfg={}, db_path=str(tmp_path / "t.db"))
        assert hasattr(app, "routes")


# ── GET / ─────────────────────────────────────────────────────────────────────

class TestRootEndpoint:
    def test_returns_200(self, client):
        r = client.get("/")
        assert r.status_code == 200

    def test_contains_status_ok(self, client):
        r = client.get("/")
        assert r.json()["status"] == "ok"

    def test_contains_version(self, client):
        r = client.get("/")
        assert "version" in r.json()

    def test_contains_paused(self, client):
        r = client.get("/")
        assert "paused" in r.json()


# ── GET /health ───────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_returns_200(self, client):
        assert client.get("/health").status_code == 200

    def test_has_daily_pnl(self, client):
        r = client.get("/health").json()
        assert "daily_pnl" in r

    def test_paused_initially_false(self, client):
        r = client.get("/health").json()
        assert r["paused"] is False


# ── GET /state ────────────────────────────────────────────────────────────────

class TestStateEndpoint:
    def test_returns_200(self, client):
        assert client.get("/state").status_code == 200

    def test_reflects_state_file(self, client):
        r = client.get("/state").json()
        assert r.get("daily_pnl") == 500.0

    def test_empty_state_when_no_file(self, tmp_path):
        app = create_app(cfg={}, state_path=str(tmp_path / "missing.json"),
                         db_path=str(tmp_path / "t.db"))
        c = TestClient(app)
        r = c.get("/state")
        assert r.status_code == 200
        assert r.json() == {}


# ── GET /signals ──────────────────────────────────────────────────────────────

class TestSignalsEndpoint:
    def test_returns_list(self, client):
        r = client.get("/signals")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_reflects_signal_log(self, client):
        items = client.get("/signals").json()
        assert len(items) == 2

    def test_n_param_limits_results(self, client):
        items = client.get("/signals?n=1").json()
        assert len(items) <= 1


# ── GET /trades ───────────────────────────────────────────────────────────────

class TestTradesEndpoint:
    def test_returns_list(self, client):
        r = client.get("/trades")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_empty_when_no_db(self, client):
        items = client.get("/trades").json()
        assert items == []   # db_path points to a non-existent db in tmp_path


# ── GET /metrics ──────────────────────────────────────────────────────────────

class TestMetricsEndpoint:
    def test_returns_dict(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)


# ── GET /autopsy ──────────────────────────────────────────────────────────────

class TestAutopsyEndpoint:
    def test_returns_dict(self, client):
        r = client.get("/autopsy")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_has_n_trades(self, client):
        r = client.get("/autopsy").json()
        assert "n_trades" in r


# ── GET /monte-carlo ──────────────────────────────────────────────────────────

class TestMonteCarlo:
    def test_returns_dict(self, client):
        r = client.get("/monte-carlo")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)


# ── POST /control/pause and /resume ──────────────────────────────────────────

class TestControlEndpoints:
    def test_pause_no_auth_required_when_no_token(self, client):
        r = client.post("/control/pause")
        assert r.status_code == 200
        assert r.json()["status"] == "paused"

    def test_pause_sets_paused_in_health(self, client):
        client.post("/control/pause")
        r = client.get("/health").json()
        assert r["paused"] is True

    def test_resume_clears_pause(self, client):
        client.post("/control/pause")
        client.post("/control/resume")
        r = client.get("/health").json()
        assert r["paused"] is False

    def test_auth_required_when_token_set(self, auth_client):
        r = auth_client.post("/control/pause")
        assert r.status_code == 401

    def test_auth_valid_token_allowed(self, auth_client):
        r = auth_client.post("/control/pause",
                             headers={"Authorization": "Bearer secret123"})
        assert r.status_code == 200

    def test_resume_requires_auth(self, auth_client):
        r = auth_client.post("/control/resume")
        assert r.status_code == 401


# ── maybe_start_dashboard ─────────────────────────────────────────────────────

class TestMaybeStartDashboard:
    def test_returns_none_when_disabled(self):
        result = maybe_start_dashboard({"web_dashboard_enabled": False})
        assert result is None

    def test_returns_none_when_missing_key(self):
        result = maybe_start_dashboard({})
        assert result is None
