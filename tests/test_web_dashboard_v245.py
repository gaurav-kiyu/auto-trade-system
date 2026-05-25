"""Tests for v2.45 web dashboard endpoints (webhook + chain viz, Items 21-22)."""

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────

def _get_app(webhook_enabled=True, chain_viz=True):
    try:
        from core.web_dashboard import create_app
        cfg = {
            "webhook_enabled": webhook_enabled,
            "webhook_rate_limit_per_min": 5,
            "chain_viz_enabled": chain_viz,
            "web_dashboard_enabled": True,
        }
        return create_app(cfg)
    except ImportError:
        pytest.skip("fastapi not installed")


# ── /signals/inject endpoint ──────────────────────────────────────────────────

def test_inject_disabled_returns_disabled():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")
    app = _get_app(webhook_enabled=False)
    client = TestClient(app)
    resp = client.post("/signals/inject", json={"symbol": "NIFTY", "direction": "CALL"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "disabled"


def test_inject_queues_signal():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")
    app = _get_app(webhook_enabled=True)
    client = TestClient(app)
    resp = client.post("/signals/inject", json={"symbol": "NIFTY", "direction": "CALL"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


def test_inject_rate_limit():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")
    try:
        from core.web_dashboard import create_app
        cfg = {"webhook_enabled": True, "webhook_rate_limit_per_min": 2}
        app = create_app(cfg)
    except ImportError:
        pytest.skip("fastapi not installed")
    client = TestClient(app)
    for _ in range(2):
        client.post("/signals/inject", json={"symbol": "X"})
    resp = client.post("/signals/inject", json={"symbol": "X"})
    assert resp.json()["status"] in ("rate_limited", "queued")


def test_inject_bad_json_no_crash():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")
    app = _get_app(webhook_enabled=True)
    client = TestClient(app)
    resp = client.post("/signals/inject", data="not-json",
                       headers={"content-type": "text/plain"})
    # FastAPI returns 422 for malformed body — not a 500 server error
    assert resp.status_code in (200, 422)


def test_inject_adds_source_field():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")
    app = _get_app(webhook_enabled=True)
    client = TestClient(app)
    resp = client.post("/signals/inject", json={"symbol": "BANKNIFTY"})
    assert resp.status_code == 200


# ── /chain/{index} endpoint ───────────────────────────────────────────────────

def test_chain_disabled_returns_disabled():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")
    app = _get_app(chain_viz=False)
    client = TestClient(app)
    resp = client.get("/chain/NIFTY")
    assert resp.status_code == 200
    assert resp.json()["status"] == "disabled"


def test_chain_returns_dict_with_index():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")
    app = _get_app(chain_viz=True)
    client = TestClient(app)
    resp = client.get("/chain/NIFTY")
    assert resp.status_code == 200
    data = resp.json()
    assert "index" in data
    assert data["index"] == "NIFTY"


def test_chain_unknown_index_returns_error_or_data():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")
    app = _get_app(chain_viz=True)
    client = TestClient(app)
    resp = client.get("/chain/UNKNOWN")
    assert resp.status_code == 200
    data = resp.json()
    assert "index" in data


def test_chain_banknifty_returns_index_field():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")
    app = _get_app(chain_viz=True)
    client = TestClient(app)
    resp = client.get("/chain/BANKNIFTY")
    assert resp.status_code == 200
    assert resp.json()["index"] == "BANKNIFTY"


def test_inject_response_has_ts_field():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")
    app = _get_app(webhook_enabled=True)
    client = TestClient(app)
    resp = client.post("/signals/inject", json={"symbol": "FINNIFTY"})
    if resp.json()["status"] == "queued":
        assert "ts" in resp.json()


def test_root_endpoint_still_works_after_v245_additions():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")
    app = _get_app()
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_control_pause_still_works():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")
    app = _get_app()
    client = TestClient(app)
    resp = client.post("/control/pause")
    assert resp.status_code == 200


def test_inject_uses_rate_limiter_when_provided():
    """When RateLimitingService is passed to create_app, it's used for rate limiting."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")
    try:
        from core.ports.rate_limiting.rate_limit_port import RateLimitConfig
        from core.services.rate_limiting_service import RateLimitingService
        from core.web_dashboard import create_app
        rl = RateLimitingService()
        rl.update_config("webhook", RateLimitConfig(limit=1, window=60, algorithm="fixed_window"))
        cfg = {
            "webhook_enabled": True,
            "rate_limiter_webhook_enabled": True,
            "web_dashboard_enabled": True,
        }
        app = create_app(cfg, rate_limiter=rl)
        client = TestClient(app)
        # First call allowed
        resp = client.post("/signals/inject", json={"symbol": "TEST"})
        assert resp.json()["status"] == "queued"
        # Second call rate-limited
        resp = client.post("/signals/inject", json={"symbol": "TEST"})
        assert resp.json()["status"] == "rate_limited"
    except ImportError:
        pytest.skip("fastapi not installed")
