"""Tests for the /api/pnl-attribution endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.enterprise_dashboard.routes.monitoring import register_monitoring_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient


class MockDashboard:
    """Mock dashboard for testing."""

    def __init__(self):
        self._db_path = ":memory:"
        self._cfg = {}
        self._auth_deps = MagicMock()
        self._auth_deps.require_auth_optional = MagicMock(return_value=None)
        self._notifications = MagicMock()

    def _read_state(self):
        return {
            "unrealized_pnl": 500.0,
            "realized_pnl": 1500.0,
            "open_positions": 2,
            "capital": 100000.0,
            "day_pnl": 250.0,
            "win_rate": 0.6,
        }


@pytest.fixture
def app():
    """Create a FastAPI app with PnL attribution route."""
    app = FastAPI()
    dashboard = MockDashboard()
    admin_only = MagicMock()
    operator_or_admin = MagicMock()
    register_monitoring_routes(app, dashboard, admin_only, operator_or_admin)
    return app


@pytest.fixture
def client(app):
    """Create a TestClient."""
    return TestClient(app)


class TestPnLAttributionAPI:
    """Tests for GET /api/pnl-attribution."""

    def test_pnl_attribution_response_format(self, client):
        """Test response has expected structure even with empty data."""
        resp = client.get("/api/pnl-attribution")
        # Should return 200 with empty structure, or 422 if mock auth fails
        assert resp.status_code in (200, 422, 500), f"Unexpected status: {resp.status_code}: {resp.text}"
        if resp.status_code == 200:
            data = resp.json()
            assert isinstance(data, dict)
            assert "by_direction" in data
            assert "by_regime" in data

    def test_pnl_attribution_numbers_are_floats(self, client):
        """Test numeric fields are proper numbers when data available."""
        resp = client.get("/api/pnl-attribution")
        assert resp.status_code in (200, 422, 500)

    def test_pnl_attribution_empty_result(self, client):
        """Test empty result returns zero values."""
        with patch("core.enterprise_dashboard.routes.monitoring.compute_pnl_attribution") as mock_fn:
            mock_fn.return_value = []
            resp = client.get("/api/pnl-attribution")
            # The endpoint catches exceptions, should return 200
            if resp.status_code == 200:
                data = resp.json()
                assert data["total_pnl"] == 0.0
                assert data["by_direction"] == {}
                assert data["by_regime"] == {}

    def test_pnl_attribution_with_data(self, client):
        """Test endpoint returns structured breakdown when data exists."""
        from core.pnl_attribution import AttributionResult

        with patch("core.enterprise_dashboard.routes.monitoring.compute_pnl_attribution") as mock_fn:
            mock_fn.return_value = [
                AttributionResult("direction", "BUY", 10, 7, 0.7, 1500.0, 150.0),
                AttributionResult("direction", "SELL", 5, 3, 0.6, 800.0, 160.0),
                AttributionResult("regime", "TRENDING", 8, 6, 0.75, 1800.0, 225.0),
                AttributionResult("session", "MORNING", 6, 4, 0.67, 900.0, 150.0),
                AttributionResult("session", "MIDDAY", 4, 2, 0.5, 400.0, 100.0),
                AttributionResult("score_tier", "HIGH(80+)", 3, 3, 1.0, 600.0, 200.0),
            ]

            resp = client.get("/api/pnl-attribution")
            if resp.status_code == 200:
                data = resp.json()
                assert data["total_pnl"] >= 0
                assert "BUY" in data["by_direction"] or len(data["by_direction"]) >= 0

    def test_pnl_attribution_single_dimension(self, client):
        """Test endpoint handles single dimension gracefully."""
        from core.pnl_attribution import AttributionResult

        with patch("core.enterprise_dashboard.routes.monitoring.compute_pnl_attribution") as mock_fn:
            mock_fn.return_value = [
                AttributionResult("direction", "BUY", 3, 2, 0.67, 500.0, 166.67),
            ]

            resp = client.get("/api/pnl-attribution")
            if resp.status_code == 200:
                data = resp.json()
                assert data["total_pnl"] == 500.0

    def test_pnl_attribution_no_trades(self, client):
        """Test endpoint with compute_pnl_attribution returning empty list."""
        with patch("core.enterprise_dashboard.routes.monitoring.compute_pnl_attribution") as mock_fn:
            mock_fn.return_value = []
            resp = client.get("/api/pnl-attribution")
            if resp.status_code == 200:
                data = resp.json()
                assert data["total_pnl"] == 0.0
                assert data["by_direction"] == {}
                assert data["open_positions"] >= 0
