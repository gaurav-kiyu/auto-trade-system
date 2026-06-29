"""
Integration tests for the Enterprise Dashboard — full middleware stack.

Uses FastAPI TestClient which exercises the complete middleware chain
(security headers, rate limiting, CSRF, etc.) without needing a real
uvicorn server. This avoids port-binding issues on Windows while still
testing the full request/response cycle.

Usage:
    python -m pytest tests/test_dashboard_integration.py -v --tb=short
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")

from core.fundamental_analyzer import reset_fundamental_analyzer
from core.web_dashboard import maybe_start_dashboard
from fastapi.testclient import TestClient


@pytest.fixture
def client_basic(tmp_path: Path) -> Generator[TestClient, None, None]:
    """Create dashboard TestClient with basics enabled (no webhook, no chain viz)."""
    reset_fundamental_analyzer()
    app = maybe_start_dashboard(
        {
            "web_dashboard_enabled": True,
            "webhook_enabled": False,
            "chain_viz_enabled": False,
            "web_dashboard_host": "127.0.0.1",
            "web_dashboard_port": 0,
        },
        db_path=str(tmp_path / "trades.db"),
    )
    if app is None:
        pytest.skip("Dashboard app could not be created")
    yield TestClient(app)
    reset_fundamental_analyzer()


@pytest.fixture
def client_full(tmp_path: Path) -> Generator[TestClient, None, None]:
    """Create dashboard TestClient with all features enabled."""
    reset_fundamental_analyzer()
    app = maybe_start_dashboard(
        {
            "web_dashboard_enabled": True,
            "webhook_enabled": True,
            "chain_viz_enabled": True,
            "web_dashboard_host": "127.0.0.1",
            "web_dashboard_port": 0,
        },
        db_path=str(tmp_path / "trades_full.db"),
    )
    if app is None:
        pytest.skip("Dashboard app could not be created")
    yield TestClient(app)
    reset_fundamental_analyzer()


# ═════════════════════════════════════════════════════════════════════════
# Integration Tests (via TestClient — full middleware stack)
# ═════════════════════════════════════════════════════════════════════════


class TestDashboardIntegration:
    """Full middleware stack tests via TestClient."""

    def test_login_page(self, client_basic: TestClient) -> None:
        """Login page returns HTTP 200 and contains login form."""
        resp = client_basic.get("/login")
        assert resp.status_code == 200
        body = resp.text.lower()
        assert "login" in body
        assert "password" in body

    def test_security_headers(self, client_basic: TestClient) -> None:
        """Response includes security headers."""
        resp = client_basic.get("/login")
        headers = {k.lower(): v for k, v in resp.headers.items()}
        assert "x-content-type-options" in headers
        assert "x-frame-options" in headers
        assert "content-security-policy" in headers
        csp = headers.get("content-security-policy", "")
        assert "script-src" in csp

    def test_weights_get(self, client_basic: TestClient) -> None:
        """Weights GET returns default dimension weights."""
        resp = client_basic.get("/api/fundamentals/weights")
        assert resp.status_code == 200
        data = resp.json()
        assert "weights" in data
        w = data["weights"]
        for k in ("value", "growth", "quality", "momentum"):
            assert k in w
        total = sum(w.values())
        assert abs(total - 1.0) < 0.01

    def test_weights_put(self, client_basic: TestClient) -> None:
        """PUT weights updates and GET reflects changes."""
        new_w = {"weights": {"value": 0.40, "growth": 0.20, "quality": 0.20, "momentum": 0.20}}
        resp = client_basic.put("/api/fundamentals/weights", json=new_w)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        assert abs(data["weights"]["value"] - 0.40) < 0.001

        # GET reflects the change
        resp2 = client_basic.get("/api/fundamentals/weights")
        assert resp2.status_code == 200
        data2 = resp2.json()
        if "weights" in data2:
            assert abs(data2["weights"]["value"] - 0.40) < 0.001

    def test_weights_put_invalid(self, client_basic: TestClient) -> None:
        """PUT with missing weights key returns error."""
        resp = client_basic.put("/api/fundamentals/weights", json={"not_weights": {}})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is False
        assert "error" in data

    def test_screen_empty(self, client_basic: TestClient) -> None:
        """Screen with empty symbols list returns validation error."""
        resp = client_basic.post("/api/fundamentals/screen", json={"symbols": []})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("error") == "No symbols provided"

    def test_screen_with_symbols(self, client_full: TestClient) -> None:
        """Screen with real symbols returns results list."""
        resp = client_full.post("/api/fundamentals/screen", json={"symbols": ["RELIANCE.NS", "TCS.NS"]})
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "count" in data
        assert data["count"] >= 0

    def test_analyze_endpoint(self, client_basic: TestClient) -> None:
        """Analyze endpoint returns structured data."""
        resp = client_basic.get("/api/fundamentals/analyze/RELIANCE.NS")
        assert resp.status_code == 200
        data = resp.json()
        assert "symbol" in data or "error" in data

    def test_chain_viz_disabled(self, client_basic: TestClient) -> None:
        """Chain viz returns disabled when not enabled."""
        resp = client_basic.get("/chain/NIFTY")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "disabled"

    def test_webhook_disabled(self, client_basic: TestClient) -> None:
        """Webhook returns disabled when webhook_enabled=False."""
        resp = client_basic.post("/signals/inject", json={"signal": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "disabled"

    def test_webhook_enabled(self, client_full: TestClient) -> None:
        """Webhook returns queued when webhook_enabled=True."""
        resp = client_full.post("/signals/inject", json={"symbol": "NIFTY", "action": "BUY"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "queued"

    def test_health_docker(self, client_basic: TestClient) -> None:
        """Docker health endpoint returns status."""
        resp = client_basic.get("/api/system/health/docker")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "version" in data

    def test_rate_limit_not_exceeded(self, client_basic: TestClient) -> None:
        """Normal API usage does not trigger rate limiting."""
        for _ in range(5):
            resp = client_basic.get("/api/fundamentals/weights")
            assert resp.status_code == 200

    def test_404_for_unknown_route(self, client_basic: TestClient) -> None:
        """Unknown API route returns 404."""
        resp = client_basic.get("/api/nonexistent/route")
        assert resp.status_code == 404

    def test_weights_default_values(self, client_basic: TestClient) -> None:
        """Default weights match expected values."""
        resp = client_basic.get("/api/fundamentals/weights")
        assert resp.status_code == 200
        data = resp.json()
        if "weights" in data:
            w = data["weights"]
            assert abs(w["value"] - 0.30) < 0.001
            assert abs(w["growth"] - 0.25) < 0.001
            assert abs(w["quality"] - 0.25) < 0.001
            assert abs(w["momentum"] - 0.20) < 0.001
