"""Tests for the /api/system/data-providers/health endpoint.

Covers all health states: unavailable, idle, healthy, degraded, critical, and error.
Uses the same fixture pattern as test_enterprise_dashboard.py.
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
        "capital": 100000, "execution_mode": "paper",
    }))
    return str(p)


@pytest.fixture()
def dashboard(state_file: str, tmp_path: Path):
    from core.enterprise_dashboard import EnterpriseDashboard

    db = EnterpriseDashboard(config={
        "web_dashboard_host": "127.0.0.1",
        "trader_state_path": state_file,
        "auth_db_path": str(tmp_path / "auth.db"),
    })
    db.wire_bot_refs(pause_event=threading.Event(), signal_log=MagicMock())
    return db


@pytest.fixture()
def client(dashboard) -> TestClient:
    return TestClient(dashboard.app)


# ── Mock MarketDataService helpers ────────────────────────────────────────────


def _mock_mds(adapters: dict, total: int, connected: int):
    """Create a mock MarketDataService with the given adapter state."""
    mds = MagicMock()
    mds.list_adapters.return_value = adapters
    mds.health_check.return_value = {
        "total_adapters": total,
        "connected_adapters": connected,
        "disconnected_adapters": total - connected,
        "adapter_details": adapters,
    }
    return mds


# ── Tests for /api/system/data-providers/health ───────────────────────────────


class TestDataProvidersHealthEndpoint:
    """Tests the /api/system/data-providers/health endpoint."""

    def test_health_unavailable(self, client: TestClient):
        """No market_data_service wired → unavailable."""
        resp = client.get("/api/system/data-providers/health",
                          headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unavailable"
        assert "detail" in data

    def test_health_healthy_all_connected(self, dashboard, client: TestClient):
        """All adapters connected → healthy."""
        adapters = {
            "yfinance": {"adapter_type": "YFinanceAdapter", "asset_classes": ["index", "equity"], "priority": 10, "connected": True},
            "websocket": {"adapter_type": "NseIndexWebSocketAdapter", "asset_classes": ["index"], "priority": 100, "connected": True},
        }
        dashboard._bot_refs["market_data_service"] = _mock_mds(adapters, total=2, connected=2)

        resp = client.get("/api/system/data-providers/health",
                          headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["total"] == 2
        assert data["connected"] == 2
        assert data["disconnected"] == 0
        assert data["health_pct"] == 100.0
        assert "adapter_details" in data

    def test_health_degraded_some_connected(self, dashboard, client: TestClient):
        """Some adapters connected, some not → degraded."""
        adapters = {
            "yfinance": {"adapter_type": "YFinanceAdapter", "asset_classes": ["index", "equity"], "priority": 10, "connected": True},
            "websocket": {"adapter_type": "NseIndexWebSocketAdapter", "asset_classes": ["index"], "priority": 100, "connected": False},
            "broker": {"adapter_type": "BrokerAdapter", "asset_classes": ["equity", "fo"], "priority": 50, "connected": True},
        }
        dashboard._bot_refs["market_data_service"] = _mock_mds(adapters, total=3, connected=2)

        resp = client.get("/api/system/data-providers/health",
                          headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["total"] == 3
        assert data["connected"] == 2
        assert data["disconnected"] == 1
        assert data["health_pct"] == pytest.approx(66.7, rel=0.1)
        assert "adapter_details" in data

    def test_health_critical_none_connected(self, dashboard, client: TestClient):
        """All adapters disconnected → critical."""
        adapters = {
            "yfinance": {"adapter_type": "YFinanceAdapter", "asset_classes": ["index"], "priority": 10, "connected": False},
            "websocket": {"adapter_type": "NseIndexWebSocketAdapter", "asset_classes": ["index"], "priority": 100, "connected": False},
        }
        dashboard._bot_refs["market_data_service"] = _mock_mds(adapters, total=2, connected=0)

        resp = client.get("/api/system/data-providers/health",
                          headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "critical"
        assert data["connected"] == 0
        assert data["health_pct"] == 0.0

    def test_health_idle_no_adapters(self, dashboard, client: TestClient):
        """Zero adapters registered → idle."""
        dashboard._bot_refs["market_data_service"] = _mock_mds({}, total=0, connected=0)

        resp = client.get("/api/system/data-providers/health",
                          headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "idle"
        assert data["total"] == 0
        assert data["health_pct"] == 0.0

    def test_health_single_adapter_connected(self, dashboard, client: TestClient):
        """Single adapter, connected → healthy."""
        adapters = {
            "yfinance": {"adapter_type": "YFinanceAdapter", "asset_classes": ["index"], "priority": 10, "connected": True},
        }
        dashboard._bot_refs["market_data_service"] = _mock_mds(adapters, total=1, connected=1)

        resp = client.get("/api/system/data-providers/health",
                          headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["health_pct"] == 100.0

    def test_health_single_adapter_disconnected(self, dashboard, client: TestClient):
        """Single adapter, disconnected → critical."""
        adapters = {
            "yfinance": {"adapter_type": "YFinanceAdapter", "asset_classes": ["index"], "priority": 10, "connected": False},
        }
        dashboard._bot_refs["market_data_service"] = _mock_mds(adapters, total=1, connected=0)

        resp = client.get("/api/system/data-providers/health",
                          headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "critical"
        assert data["health_pct"] == 0.0

    def test_health_error_from_service(self, dashboard, client: TestClient):
        """MarketDataService raises an exception → error response."""
        broken_mds = MagicMock()
        broken_mds.health_check.side_effect = RuntimeError("Connection timeout")
        dashboard._bot_refs["market_data_service"] = broken_mds

        resp = client.get("/api/system/data-providers/health",
                          headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "detail" in data

    def test_health_has_timestamp(self, dashboard, client: TestClient):
        """Response includes a valid timestamp."""
        adapters = {
            "yfinance": {"adapter_type": "YFinanceAdapter", "asset_classes": ["index"], "priority": 10, "connected": True},
        }
        dashboard._bot_refs["market_data_service"] = _mock_mds(adapters, total=1, connected=1)

        resp = client.get("/api/system/data-providers/health",
                          headers={"accept": "application/json"})
        data = resp.json()
        assert "timestamp" in data
        assert isinstance(data["timestamp"], (int, float))
        assert data["timestamp"] > 0

    def test_health_reflects_adapter_details(self, dashboard, client: TestClient):
        """adapter_details contains per-adapter status info."""
        adapters = {
            "yfinance": {"adapter_type": "YFinanceAdapter", "asset_classes": ["index"], "priority": 10, "connected": True},
        }
        dashboard._bot_refs["market_data_service"] = _mock_mds(adapters, total=1, connected=1)

        resp = client.get("/api/system/data-providers/health",
                          headers={"accept": "application/json"})
        data = resp.json()
        details = data.get("adapter_details", {})
        assert "yfinance" in details
        assert details["yfinance"]["connected"] is True

    def test_health_covered_by_no_auth(self, state_file: str, tmp_path):
        """Endpoint does NOT require admin auth."""
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "0.0.0.0",
            "trader_state_path": state_file,
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        c = TestClient(db.app)
        resp = c.get("/api/system/data-providers/health",
                     headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unavailable"  # no MDS wired

    def test_health_pct_precision(self, dashboard, client: TestClient):
        """health_pct is rounded to 1 decimal place."""
        adapters = {
            "a": {"adapter_type": "A", "asset_classes": [], "priority": 10, "connected": True},
            "b": {"adapter_type": "B", "asset_classes": [], "priority": 10, "connected": True},
            "c": {"adapter_type": "C", "asset_classes": [], "priority": 10, "connected": False},
        }
        dashboard._bot_refs["market_data_service"] = _mock_mds(adapters, total=3, connected=2)

        resp = client.get("/api/system/data-providers/health",
                          headers={"accept": "application/json"})
        data = resp.json()
        # 2/3 = 66.666... → rounded to 66.7
        assert data["health_pct"] == 66.7
