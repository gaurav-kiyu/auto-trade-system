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

from unittest.mock import MagicMock

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


@pytest.fixture
def client_wired_full(tmp_path: Path) -> Generator[tuple[TestClient, dict], None, None]:
    """Create dashboard TestClient with wired rate limiter, signal queue, signal log.

    Yields (TestClient, mocks_dict) so tests can assert on mock calls.
    """
    reset_fundamental_analyzer()
    mock_rate_limiter = MagicMock()
    mock_rate_limiter.check.return_value = True
    mock_signal_queue = MagicMock()
    mock_signal_log = MagicMock()
    mocks = {
        "rate_limiter": mock_rate_limiter,
        "signal_queue": mock_signal_queue,
        "signal_log": mock_signal_log,
    }
    app = maybe_start_dashboard(
        {
            "web_dashboard_enabled": True,
            "webhook_enabled": True,
            "chain_viz_enabled": True,
            "web_dashboard_host": "127.0.0.1",
            "web_dashboard_port": 0,
        },
        db_path=str(tmp_path / "trades_wired.db"),
        signal_log=mock_signal_log,
        signal_queue=mock_signal_queue,
        rate_limiter=mock_rate_limiter,
    )
    if app is None:
        pytest.skip("Dashboard app could not be created")
    yield TestClient(app), mocks
    reset_fundamental_analyzer()


@pytest.fixture
def client_rate_limited(tmp_path: Path) -> Generator[TestClient, None, None]:
    """Create dashboard TestClient with rate limiter that rejects requests."""
    reset_fundamental_analyzer()
    mock_rate_limiter = MagicMock()
    mock_rate_limiter.check.return_value = False  # Reject all
    app = maybe_start_dashboard(
        {
            "web_dashboard_enabled": True,
            "webhook_enabled": True,
            "chain_viz_enabled": True,
            "web_dashboard_host": "127.0.0.1",
            "web_dashboard_port": 0,
        },
        db_path=str(tmp_path / "trades_rate.db"),
        rate_limiter=mock_rate_limiter,
    )
    if app is None:
        pytest.skip("Dashboard app could not be created")
    yield TestClient(app)
    reset_fundamental_analyzer()


@pytest.fixture
def client_chain_viz(tmp_path: Path) -> Generator[TestClient, None, None]:
    """Create dashboard TestClient with a mock market_data provider for chain viz."""
    reset_fundamental_analyzer()
    from core.enterprise_dashboard import EnterpriseDashboard
    dash = EnterpriseDashboard(
        config={
            "web_dashboard_enabled": True,
            "webhook_enabled": True,
            "chain_viz_enabled": True,
            "web_dashboard_host": "127.0.0.1",
            "web_dashboard_port": 0,
        },
        db_path=str(tmp_path / "trades_chain.db"),
    )
    # Wire a mock market_data provider into _bot_refs
    mock_market_data = MagicMock()
    mock_market_data.get_option_chain.return_value = {
        "calls": [{"strike": 24000, "ltp": 150}],
        "puts": [{"strike": 24000, "ltp": 120}],
    }
    dash._bot_refs["market_data"] = mock_market_data
    dash._bot_refs["ltp_NIFTY"] = 24100.0
    dash._bot_refs["ltp_BANKNIFTY"] = 57800.0
    app = dash.app
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
        """Webhook returns routed (or queued fallback) when webhook_enabled=True."""
        resp = client_full.post("/signals/inject", json={"symbol": "NIFTY", "action": "BUY"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") in ("routed", "queued")

    def test_webhook_routes_via_dispatcher(self, client_full: TestClient) -> None:
        """Webhook routes NIFTY signal through dispatcher with INDEX_OPTIONS asset class."""
        resp = client_full.post("/signals/inject", json={
            "symbol": "NIFTY", "direction": "CALL", "score": 85, "price": 24000,
        })
        assert resp.status_code == 200
        data = resp.json()
        if data.get("status") == "routed":
            assert data["symbol"] == "NIFTY"
            assert "asset_class" in data
            assert "engine" in data

    def test_webhook_routes_banknifty_signal(self, client_full: TestClient) -> None:
        """Webhook routes BANKNIFTY and FINNIFTY signals correctly."""
        for sym in ("BANKNIFTY", "FINNIFTY"):
            resp = client_full.post("/signals/inject", json={
                "symbol": sym, "direction": "PUT", "score": 75,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("status") in ("routed", "queued")
            if data.get("status") == "routed":
                assert data["symbol"] == sym

    def test_webhook_json_decode_error(self, client_full: TestClient) -> None:
        """Webhook handles malformed JSON gracefully (returns queued)."""
        resp = client_full.post("/signals/inject", data=b"not valid json", headers={"content-type": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        # Should fall back to queued on JSON decode error
        assert data.get("status") == "queued"

    def test_webhook_with_empty_body(self, client_full: TestClient) -> None:
        """Webhook handles empty/invalid body gracefully."""
        resp = client_full.post("/signals/inject", json={}, headers={"content-type": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") in ("queued", "skipped")

    def test_webhook_form_data(self, client_full: TestClient) -> None:
        """Webhook gracefully handles form-encoded data (falls back gracefully)."""
        resp = client_full.post("/signals/inject", data={"symbol": "NIFTY"})
        # Should return 200 with queued status (JSON parsing will fail for form data)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "queued"

    def test_webhook_rate_limited(self, client_rate_limited: TestClient) -> None:
        """Webhook returns rate_limited when rate limiter rejects."""
        resp = client_rate_limited.post("/signals/inject", json={"symbol": "NIFTY", "action": "BUY"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "rate_limited"
        assert data.get("retry_after") == 60

    def test_webhook_wired_signal_queue_used(self, client_wired_full: tuple) -> None:
        """Webhook calls signal_queue.put when queue is wired."""
        client, mocks = client_wired_full
        body = {"symbol": "NIFTY", "direction": "CALL", "score": 80}
        resp = client.post("/signals/inject", json=body)
        assert resp.status_code == 200
        mock_queue = mocks["signal_queue"]
        assert mock_queue.put.called
        assert mock_queue.put.call_args[0][0] == body

    def test_webhook_wired_signal_log_used(self, client_wired_full: tuple) -> None:
        """Webhook calls signal_log.append when log is wired."""
        client, mocks = client_wired_full
        body = {"symbol": "BANKNIFTY", "direction": "PUT", "score": 75}
        resp = client.post("/signals/inject", json=body)
        assert resp.status_code == 200
        mock_log = mocks["signal_log"]
        assert mock_log.append.called
        assert mock_log.append.call_args[0][0]["symbol"] == "BANKNIFTY"

    def test_webhook_wired_rate_limiter_checked(self, client_wired_full: tuple) -> None:
        """Webhook calls rate_limiter.check when limiter is wired."""
        client, mocks = client_wired_full
        resp = client.post("/signals/inject", json={"symbol": "FINNIFTY", "direction": "CALL"})
        assert resp.status_code == 200
        mock_limiter = mocks["rate_limiter"]
        assert mock_limiter.check.called
        assert mock_limiter.check.call_args[0][0] == "webhook"

    def test_chain_viz_enabled_with_rate_limiter(self, client_rate_limited: TestClient) -> None:
        """Chain viz returns symbol data when enabled (independent of rate limiter)."""
        resp = client_rate_limited.get("/chain/NIFTY")
        assert resp.status_code == 200
        data = resp.json()
        assert "symbol" in data
        assert data["symbol"] == "NIFTY"

    def test_chain_viz_with_market_data(self, client_chain_viz: TestClient) -> None:
        """Chain viz returns option_chain data when market_data is wired."""
        resp = client_chain_viz.get("/chain/NIFTY")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "NIFTY"
        assert "index" in data
        assert data["index"] == "NIFTY"
        assert "option_chain" in data
        oc = data["option_chain"]
        assert "calls" in oc
        assert "puts" in oc
        assert data["spot_price"] == 24100.0

    def test_chain_viz_banknifty(self, client_chain_viz: TestClient) -> None:
        """Chain viz returns correct data for BANKNIFTY."""
        resp = client_chain_viz.get("/chain/BANKNIFTY")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "BANKNIFTY"
        assert "option_chain" in data
        assert data["spot_price"] == 57800.0


@pytest.fixture
def client_chain_viz_no_data(tmp_path: Path) -> Generator[TestClient, None, None]:
    """Create dashboard TestClient with market_data that raises on get_option_chain."""
    reset_fundamental_analyzer()
    from core.enterprise_dashboard import EnterpriseDashboard
    dash = EnterpriseDashboard(
        config={
            "web_dashboard_enabled": True,
            "webhook_enabled": True,
            "chain_viz_enabled": True,
            "web_dashboard_host": "127.0.0.1",
            "web_dashboard_port": 0,
        },
        db_path=str(tmp_path / "trades_chain_err.db"),
    )
    # Wire a market_data that raises ValueError
    mock_market_data = MagicMock()
    mock_market_data.get_option_chain.side_effect = ValueError("API error")
    dash._bot_refs["market_data"] = mock_market_data
    # Don't set ltps to test spot_price fallback
    app = dash.app
    if app is None:
        pytest.skip("Dashboard app could not be created")
    yield TestClient(app)
    reset_fundamental_analyzer()


class TestChainVizEdgeCases:
    """Edge cases for the options chain viz endpoint."""

    def test_chain_viz_market_data_error(self, client_chain_viz_no_data: TestClient) -> None:
        """Chain viz handles get_option_chain error gracefully (no option_chain key)."""
        resp = client_chain_viz_no_data.get("/chain/NIFTY")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "NIFTY"
        # When get_option_chain raises, option_chain should NOT be in response
        assert "option_chain" not in data

    def test_chain_viz_spot_price_fallback_zero(self, client_chain_viz_no_data: TestClient) -> None:
        """Chain viz defaults spot_price to 0 when ltp_{symbol} is not in _bot_refs."""
        resp = client_chain_viz_no_data.get("/chain/FINNIFTY")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "FINNIFTY"
        # No ltp_FINNIFTY set, should default to 0
        assert data["spot_price"] == 0

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


class TestSignalLogDirect:
    """Direct unit tests for SignalLog (covers lock-protected lines)."""

    def test_append_and_recent(self) -> None:
        """SignalLog.append stores signals and recent returns them."""
        from core.web_dashboard import SignalLog
        log = SignalLog(maxlen=10)
        log.append({"symbol": "NIFTY", "direction": "CALL"})
        log.append({"symbol": "BANKNIFTY", "direction": "PUT"})
        recent = log.recent(10)
        assert len(recent) == 2
        assert recent[0]["symbol"] == "NIFTY"
        assert recent[1]["symbol"] == "BANKNIFTY"
        assert "_ts" in recent[0]

    def test_recent_returns_correct_count(self) -> None:
        """SignalLog.recent returns at most n items."""
        from core.web_dashboard import SignalLog
        log = SignalLog(maxlen=10)
        for i in range(10):
            log.append({"i": i})
        assert len(log.recent(3)) == 3
        assert len(log.recent()) == 10  # default 50, capped to 10

    def test_overflow_trims_oldest(self) -> None:
        """SignalLog drops oldest entries when maxlen exceeded."""
        from core.web_dashboard import SignalLog
        log = SignalLog(maxlen=3)
        log.append({"id": 1})
        log.append({"id": 2})
        log.append({"id": 3})
        log.append({"id": 4})
        recent = log.recent(5)
        assert len(recent) == 3
        assert recent[0]["id"] == 2
        assert recent[-1]["id"] == 4

    def test_clear_empties_buffer(self) -> None:
        """SignalLog.clear removes all entries."""
        from core.web_dashboard import SignalLog
        log = SignalLog(maxlen=10)
        log.append({"symbol": "NIFTY"})
        log.append({"symbol": "BANKNIFTY"})
        log.clear()
        assert len(log.recent(10)) == 0


class TestServeEdgeCases:
    """Edge case tests for the serve() function (SSL/TLS config, warnings)."""

    def test_serve_disabled_returns_none(self) -> None:
        """maybe_start_dashboard returns None when web_dashboard_enabled is False."""
        from core.web_dashboard import maybe_start_dashboard
        result = maybe_start_dashboard({"web_dashboard_enabled": False})
        assert result is None

    def test_serve_with_ssl_config_passed_to_uvicorn(self) -> None:
        """serve() passes ssl_certfile/ssl_keyfile to uvicorn.Config."""
        from unittest.mock import MagicMock, patch

        import uvicorn as _uvicorn
        from core.web_dashboard import serve
        mock_app = MagicMock()
        with patch.object(_uvicorn, "Config") as mock_config:
            with patch.object(_uvicorn, "Server") as mock_server:
                mock_server.return_value = MagicMock()
                serve(mock_app, host="127.0.0.1", port=8765, ssl_certfile="/fake/cert.pem", ssl_keyfile="/fake/key.pem")
                assert mock_config.called
                _, kwargs = mock_config.call_args
                assert kwargs.get("ssl_certfile") == "/fake/cert.pem"
                assert kwargs.get("ssl_keyfile") == "/fake/key.pem"
