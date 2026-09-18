"""Tests for Market Telemetry and Exchange Status Detection.

Validates:
1. Weekend detection (MARKET CLOSED).
2. NSE Holiday detection (NSE HOLIDAY).
3. Pre-open session (09:00 - 09:15) on market day.
4. Regular live session (09:15 - 15:30) on market day (MARKET OPEN).
5. Post-market session (15:30 - 16:00).
6. Off-hours session (after 16:00).
"""

from __future__ import annotations

import datetime
from unittest.mock import patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.enterprise_dashboard.routes.system import register_system_routes


class DummyDashboard:
    class AuthDeps:
        @staticmethod
        def require_auth_optional():
            return None
    _auth_deps = AuthDeps()


@pytest.fixture
def client():
    app = FastAPI()
    register_system_routes(app, DummyDashboard(), admin_only=None, operator_or_admin=None)
    return TestClient(app)


def test_market_telemetry_weekend(client):
    # Saturday Sep 19, 2026 at 11:00 IST
    mock_now = datetime.datetime(2026, 9, 19, 11, 0, 0)
    with patch("core.datetime_ist.now_ist", return_value=mock_now):
        resp = client.get("/api/system/market-telemetry")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "CLOSED"
        assert data["label"] == "MARKET CLOSED"
        assert data["is_open"] is False


def test_market_telemetry_holiday(client):
    # Friday Oct 2, 2026 (Gandhi Jayanti - Official NSE Holiday) at 11:00 IST
    mock_now = datetime.datetime(2026, 10, 2, 11, 0, 0)
    with patch("core.datetime_ist.now_ist", return_value=mock_now):
        resp = client.get("/api/system/market-telemetry")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "HOLIDAY"
        assert data["label"] == "NSE HOLIDAY"
        assert data["is_open"] is False


def test_market_telemetry_pre_open(client):
    # Friday Sep 18, 2026 at 09:05 IST
    mock_now = datetime.datetime(2026, 9, 18, 9, 5, 0)
    with patch("core.datetime_ist.now_ist", return_value=mock_now):
        resp = client.get("/api/system/market-telemetry")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "PRE_OPEN"
        assert data["label"] == "PRE-OPEN"
        assert data["is_open"] is True


def test_market_telemetry_market_open(client):
    # Friday Sep 18, 2026 at 10:30 IST
    mock_now = datetime.datetime(2026, 9, 18, 10, 30, 0)
    with patch("core.datetime_ist.now_ist", return_value=mock_now):
        resp = client.get("/api/system/market-telemetry")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "LIVE"
        assert data["label"] == "MARKET OPEN"
        assert data["is_open"] is True


def test_market_telemetry_post_market(client):
    # Friday Sep 18, 2026 at 15:45 IST
    mock_now = datetime.datetime(2026, 9, 18, 15, 45, 0)
    with patch("core.datetime_ist.now_ist", return_value=mock_now):
        resp = client.get("/api/system/market-telemetry")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "POST_MARKET"
        assert data["label"] == "POST-MARKET"
        assert data["is_open"] is False


def test_market_telemetry_after_hours(client):
    # Friday Sep 18, 2026 at 18:00 IST
    mock_now = datetime.datetime(2026, 9, 18, 18, 0, 0)
    with patch("core.datetime_ist.now_ist", return_value=mock_now):
        resp = client.get("/api/system/market-telemetry")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "CLOSED"
        assert data["label"] == "MARKET CLOSED"
        assert data["is_open"] is False
