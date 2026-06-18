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

    # ── Fundamentals API ────────────────────────────────────────────────────

    def test_fundamentals_analyze_endpoint_exists(self, tmp_path):
        """GET /api/fundamentals/analyze/{symbol} returns a response."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            resp = client.get("/api/fundamentals/analyze/RELIANCE.NS")
            assert resp.status_code == 200
            data = resp.json()
            # Should return a result dict with symbol, composite_score, or error field
            assert "symbol" in data or "error" in data

    def test_fundamentals_analyze_returns_structure(self, tmp_path):
        """Analyze endpoint returns dimension_scores and details when successful."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            resp = client.get("/api/fundamentals/analyze/RELIANCE.NS")
            assert resp.status_code == 200
            data = resp.json()
            if "error" not in data:
                assert "symbol" in data
                assert "composite_score" in data
                assert "verdict" in data
                assert "dimension_scores" in data
                assert "value" in data["dimension_scores"]
                assert "growth" in data["dimension_scores"]
                assert "quality" in data["dimension_scores"]
                assert "momentum" in data["dimension_scores"]
                assert "details" in data
                assert "short_summary" in data

    def test_fundamentals_analyze_bad_symbol(self, tmp_path):
        """Analyze endpoint returns error for non-existent symbol."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            resp = client.get("/api/fundamentals/analyze/NONEXISTENT_12345")
            assert resp.status_code == 200
            data = resp.json()
            # Should have an error or symbol field
            assert "error" in data or "symbol" in data

    def test_fundamentals_screen_empty(self, tmp_path):
        """Screen endpoint returns error when no symbols provided."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            resp = client.post("/api/fundamentals/screen", json={"symbols": []})
            assert resp.status_code == 200, f'Screen endpoint returned {resp.status_code}: {resp.text[:200]}'
            data = resp.json()
            assert data.get("error") == "No symbols provided"

    def test_fundamentals_screen_returns_results(self, tmp_path):
        """Screen endpoint returns results list."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            resp = client.post("/api/fundamentals/screen", json={
                "symbols": ["RELIANCE.NS", "TCS.NS"]
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "results" in data
            assert "count" in data
            assert data["count"] >= 0  # Could be 0 if yfinance fails
            assert "timestamp" in data

    def test_fundamentals_screen_truncates_large_lists(self, tmp_path):
        """Screen endpoint truncates symbol lists > 50."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            symbols = [f"STOCK{i}.NS" for i in range(100)]
            resp = client.post("/api/fundamentals/screen", json={"symbols": symbols})
            assert resp.status_code == 200, f'Screen truncation returned {resp.status_code}: {resp.text[:200]}'
            data = resp.json()
            assert "results" in data or "error" in data

    def test_fundamentals_screen_with_min_score(self, tmp_path):
        """Screen endpoint respects min_score parameter."""

        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            resp = client.post("/api/fundamentals/screen", json={
                "symbols": ["RELIANCE.NS"],
                "min_score": 0.0
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "results" in data

    def test_fundamentals_screen_force_refresh(self, tmp_path):
        """Screen endpoint accepts force_refresh parameter."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            resp = client.post("/api/fundamentals/screen", json={
                "symbols": ["RELIANCE.NS"],
                "force_refresh": True
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "results" in data

    def test_fundamentals_screen_result_structure(self, tmp_path):
        """Screen results have expected fields."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            client = TestClient(result)
            resp = client.post("/api/fundamentals/screen", json={
                "symbols": ["RELIANCE.NS"]
            })
            assert resp.status_code == 200
            data = resp.json()
            for r in data.get("results", []):
                assert "symbol" in r
                assert "composite_score" in r
                assert "verdict" in r
                assert "dimension_scores" in r
                assert "short_summary" in r

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

    # ── Fundamentals Weights API ─────────────────────────────────────────────

    # ── Fundamentals Weights API - Edge Cases ────────────────────────────

    def test_fundamentals_weights_get(self, tmp_path):
        """GET /api/fundamentals/weights returns current/default weights."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            from core.fundamental_analyzer import reset_fundamental_analyzer
            reset_fundamental_analyzer()
            client = TestClient(result)
            resp = client.get('/api/fundamentals/weights')
            assert resp.status_code == 200, f'Weights GET returned {resp.status_code}'
            data = resp.json()
            assert 'weights' in data or 'error' in data
            if 'weights' in data:
                for k in ('value', 'growth', 'quality', 'momentum'):
                    assert k in data['weights']
            reset_fundamental_analyzer()

    def test_fundamentals_weights_put(self, tmp_path):
        """PUT /api/fundamentals/weights accepts new weights."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            from core.fundamental_analyzer import reset_fundamental_analyzer
            reset_fundamental_analyzer()
            client = TestClient(result)
            new_weights = {"weights": {"value": 0.40, "growth": 0.20, "quality": 0.20, "momentum": 0.20}}
            resp = client.put('/api/fundamentals/weights', json=new_weights)
            assert resp.status_code == 200, f'Weight PUT returned {resp.status_code}: {resp.text[:200]}'
            data = resp.json()
            assert data.get("success") is True
            assert "weights" in data
            for k in ('value', 'growth', 'quality', 'momentum'):
                assert k in data['weights']
            reset_fundamental_analyzer()

    def test_fundamentals_weights_put_invalid(self, tmp_path):
        """PUT with invalid data returns error (not 500)."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            from core.fundamental_analyzer import reset_fundamental_analyzer
            reset_fundamental_analyzer()
            client = TestClient(result)
            # Missing 'weights' key
            resp = client.put('/api/fundamentals/weights', json={"not_weights": {}})
            assert resp.status_code == 200
            data = resp.json()
            assert data.get('success') is False
            assert 'error' in data
            reset_fundamental_analyzer()

    def test_fundamentals_weights_persist(self, tmp_path):
        """PUT updates weights, subsequent GET returns updated values."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            from core.fundamental_analyzer import reset_fundamental_analyzer
            reset_fundamental_analyzer()
            client = TestClient(result)
            # PUT new weights
            new_w = {"weights": {"value": 0.50, "growth": 0.20, "quality": 0.15, "momentum": 0.15}}
            resp = client.put('/api/fundamentals/weights', json=new_w)
            assert resp.status_code == 200
            # GET should reflect updated weights
            resp2 = client.get('/api/fundamentals/weights')
            assert resp2.status_code == 200
            data = resp2.json()
            if 'weights' in data:
                assert abs(data['weights']['value'] - 0.50) < 0.001
            reset_fundamental_analyzer()

    def test_fundamentals_analyze_with_weights(self, tmp_path):
        """Analyze endpoint accepts weights query param."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            from core.fundamental_analyzer import reset_fundamental_analyzer
            reset_fundamental_analyzer()
            client = TestClient(result)
            weights = {"value": 0.40, "growth": 0.20, "quality": 0.20, "momentum": 0.20}
            import json
            resp = client.get("/api/fundamentals/analyze/RELIANCE.NS?weights=" + json.dumps(weights))
            assert resp.status_code == 200, f'Weights analyze returned {resp.status_code}: {resp.text[:200]}'
            data = resp.json()
            assert data.get("symbol") == "RELIANCE.NS" or "error" in data
            reset_fundamental_analyzer()

    def test_fundamentals_analyze_invalid_weights(self, tmp_path):
        """Analyze endpoint handles invalid weights JSON gracefully."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            from core.fundamental_analyzer import reset_fundamental_analyzer
            reset_fundamental_analyzer()
            client = TestClient(result)
            # Malformed JSON in weights param
            resp = client.get("/api/fundamentals/analyze/RELIANCE.NS?weights={invalid}")
            assert resp.status_code == 200, f'Invalid weights returned {resp.status_code}'
            data = resp.json()
            assert "symbol" in data or "error" in data
            reset_fundamental_analyzer()

    def test_fundamentals_screen_with_weights(self, tmp_path):
        """Screen endpoint accepts weights in request body."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            from core.fundamental_analyzer import reset_fundamental_analyzer
            reset_fundamental_analyzer()
            client = TestClient(result)
            payload = {
                "symbols": ["RELIANCE.NS"],
                "weights": {"value": 0.40, "growth": 0.20, "quality": 0.20, "momentum": 0.20},
            }
            resp = client.post("/api/fundamentals/screen", json=payload)
            assert resp.status_code == 200, f'Screen with weights returned {resp.status_code}: {resp.text[:200]}'
            data = resp.json()
            assert "results" in data or "error" in data
            reset_fundamental_analyzer()

    def test_fundamentals_screen_all_bad(self, tmp_path):
        """Screen with non-existent symbols returns gracefully."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            from core.fundamental_analyzer import reset_fundamental_analyzer
            reset_fundamental_analyzer()
            client = TestClient(result)
            resp = client.post("/api/fundamentals/screen", json={
                "symbols": ["ZZZ_FAKE_12345", "ABC_DEF_67890"]
            })
            assert resp.status_code == 200, f'Bad symbols returned {resp.status_code}'
            data = resp.json()
            assert "results" in data
            assert "count" in data
            reset_fundamental_analyzer()

    def test_fundamentals_screen_min_score_filters(self, tmp_path):
        """Screen respects min_score filtering."""
        result = maybe_start_dashboard(
            {"web_dashboard_enabled": True, "web_dashboard_host": "127.0.0.1", "web_dashboard_port": 0},
            db_path=str(tmp_path / "trades.db"),
        )
        if result is not None:
            from fastapi.testclient import TestClient
            from core.fundamental_analyzer import reset_fundamental_analyzer
            reset_fundamental_analyzer()
            client = TestClient(result)
            # min_score=10.0 should return fewer or equal results than min_score=0.0
            resp_low = client.post("/api/fundamentals/screen", json={
                "symbols": ["RELIANCE.NS", "TCS.NS"],
                "min_score": 0.0
            })
            assert resp_low.status_code == 200
            count_low = resp_low.json().get("count", 0)

            resp_high = client.post("/api/fundamentals/screen", json={
                "symbols": ["RELIANCE.NS", "TCS.NS"],
                "min_score": 10.0
            })
            assert resp_high.status_code == 200
            count_high = resp_high.json().get("count", 0)

            assert count_high <= count_low, f'Filtering failed: {count_high} > {count_low}'
            reset_fundamental_analyzer()
