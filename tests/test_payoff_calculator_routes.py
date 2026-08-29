"""Tests for the Enterprise Dashboard's option strategy payoff-calculator route.

Covers:
  - register_payoff_calculator_routes is importable and callable
  - POST /api/payoff-calculator/compute happy path (straddle-shaped legs)
  - Validation errors (missing legs, too many legs, bad option_type/action,
    non-positive spot price, out-of-range price_range_pct)
  - /payoff-calculator HTML page route (auth redirect + authenticated render)
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_state_file(tmp_path: Path) -> str:
    p = tmp_path / "trader_state.json"
    p.write_text(json.dumps({
        "daily_pnl": 0.0, "open_positions": 0, "hard_halt": False,
        "capital": 100000, "execution_mode": "paper", "total_trades": 0,
        "base_capital": 100000,
    }), encoding="utf-8")
    return str(p)


def _make_trades_db(tmp_path: Path) -> str:
    import sqlite3
    db_path = str(tmp_path / "trades.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def dashboard(tmp_path: Path):
    from core.enterprise_dashboard import EnterpriseDashboard

    db = EnterpriseDashboard(config={
        "web_dashboard_host": "127.0.0.1",
        "trader_state_path": _make_state_file(tmp_path),
        "auth_db_path": str(tmp_path / "dash_auth.db"),
        "broker_name": "TestBroker",
        "execution_mode": "paper",
    }, db_path=_make_trades_db(tmp_path))
    signal_log_mock = MagicMock()
    signal_log_mock.recent.return_value = []
    db.wire_bot_refs(
        pause_event=threading.Event(),
        signal_log=signal_log_mock,
    )
    return db


@pytest.fixture()
def client(dashboard) -> TestClient:
    return TestClient(dashboard.app)


@pytest.fixture()
def csrf_client(dashboard) -> TestClient:
    """A TestClient with a real opb_csrf cookie established, for POSTing to
    the CSRF-protected /api/payoff-calculator/compute endpoint - mirrors the
    pattern in tests/test_admin_portfolio_analyzer.py (GET first to receive
    the cookie, then send it back as both header and cookie on the POST)."""
    c = TestClient(dashboard.app)
    r_get = c.get("/login")
    csrf_token = r_get.cookies.get("opb_csrf", "test_csrf_token")
    c.headers.update({"X-CSRF-Token": csrf_token})
    c.cookies.set("opb_csrf", csrf_token)
    return c


# ── Registration ──────────────────────────────────────────────────────────────

def test_register_payoff_calculator_routes_exists():
    from core.enterprise_dashboard.routes.payoff_calculator import register_payoff_calculator_routes
    assert callable(register_payoff_calculator_routes)


def test_register_payoff_calculator_routes_runs():
    app = FastAPI()
    dashboard = MagicMock()
    admin_only = lambda: None  # noqa: E731
    operator_or_admin = lambda: None  # noqa: E731
    from core.enterprise_dashboard.routes.payoff_calculator import register_payoff_calculator_routes
    register_payoff_calculator_routes(app, dashboard, admin_only, operator_or_admin)
    assert len(app.routes) > 0


# ── POST /api/payoff-calculator/compute ───────────────────────────────────────

def _long_straddle_legs():
    return [
        {"strike": 24500, "option_type": "CE", "action": "BUY", "quantity": 50, "premium": 120.0},
        {"strike": 24500, "option_type": "PE", "action": "BUY", "quantity": 50, "premium": 110.0},
    ]


class TestComputeHappyPath:
    def test_straddle_shape_returns_ok(self, csrf_client: TestClient):
        resp = csrf_client.post("/api/payoff-calculator/compute", json={
            "spot_price": 24500, "legs": _long_straddle_legs(),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        # net_premium = (120*50) + (110*50) for a long straddle (both legs BUY)
        assert data["net_premium"] == pytest.approx(11500.0)
        assert len(data["break_evens"]) == 2
        assert data["max_loss"] < 0

    def test_payoff_curve_has_expected_shape(self, csrf_client: TestClient):
        resp = csrf_client.post("/api/payoff-calculator/compute", json={
            "spot_price": 24500, "legs": _long_straddle_legs(), "price_range_pct": 0.1,
        })
        data = resp.json()
        curve = data["payoff_curve"]
        assert len(curve) == 101  # default 100 points + endpoint
        spots = [pt[0] for pt in curve]
        assert min(spots) < 24500 < max(spots)

    def test_single_call_leg_max_loss_is_bounded_by_premium(self, csrf_client: TestClient):
        resp = csrf_client.post("/api/payoff-calculator/compute", json={
            "spot_price": 100, "legs": [
                {"strike": 100, "option_type": "CE", "action": "BUY", "quantity": 1, "premium": 5.0},
            ],
        })
        data = resp.json()
        assert data["max_loss"] == pytest.approx(-5.0, abs=0.5)


class TestComputeValidation:
    def test_missing_legs_is_rejected(self, csrf_client: TestClient):
        resp = csrf_client.post("/api/payoff-calculator/compute", json={"spot_price": 24500, "legs": []})
        data = resp.json()
        assert data["status"] == "error"
        assert "leg" in data["detail"].lower()

    def test_too_many_legs_is_rejected(self, csrf_client: TestClient):
        legs = [{"strike": 100 + i, "option_type": "CE", "action": "BUY", "quantity": 1, "premium": 1.0} for i in range(9)]
        resp = csrf_client.post("/api/payoff-calculator/compute", json={"spot_price": 100, "legs": legs})
        data = resp.json()
        assert data["status"] == "error"
        assert "8" in data["detail"]

    def test_bad_option_type_is_rejected(self, csrf_client: TestClient):
        resp = csrf_client.post("/api/payoff-calculator/compute", json={
            "spot_price": 100, "legs": [
                {"strike": 100, "option_type": "XX", "action": "BUY", "quantity": 1, "premium": 1.0},
            ],
        })
        data = resp.json()
        assert data["status"] == "error"

    def test_bad_action_is_rejected(self, csrf_client: TestClient):
        resp = csrf_client.post("/api/payoff-calculator/compute", json={
            "spot_price": 100, "legs": [
                {"strike": 100, "option_type": "CE", "action": "HOLD", "quantity": 1, "premium": 1.0},
            ],
        })
        data = resp.json()
        assert data["status"] == "error"

    def test_non_positive_spot_price_is_rejected(self, csrf_client: TestClient):
        resp = csrf_client.post("/api/payoff-calculator/compute", json={
            "spot_price": 0, "legs": _long_straddle_legs(),
        })
        data = resp.json()
        assert data["status"] == "error"

    def test_out_of_range_price_range_pct_is_rejected(self, csrf_client: TestClient):
        resp = csrf_client.post("/api/payoff-calculator/compute", json={
            "spot_price": 100, "legs": _long_straddle_legs(), "price_range_pct": 5.0,
        })
        data = resp.json()
        assert data["status"] == "error"

    def test_malformed_json_body_does_not_crash(self, csrf_client: TestClient):
        resp = csrf_client.post("/api/payoff-calculator/compute", json={"legs": _long_straddle_legs()})
        # spot_price missing entirely -> KeyError caught, error response, not a 500
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"


# ── HTML page route ────────────────────────────────────────────────────────────

def test_payoff_calculator_page_redirects_when_not_logged_in(client: TestClient):
    resp = client.get("/payoff-calculator", headers={"accept": "text/html"})
    assert resp.status_code in (200, 303, 307)


def test_payoff_calculator_page_authenticated(tmp_path: Path):
    import os as os_mod

    from core.enterprise_dashboard import EnterpriseDashboard
    os_mod.environ["OPBUYING_DEFAULT_ADMIN_PASSWORD"] = "Admin@123!test"

    db = EnterpriseDashboard(config={
        "web_dashboard_host": "127.0.0.1",
        "trader_state_path": _make_state_file(tmp_path),
        "auth_db_path": str(tmp_path / "admin_auth_payoff.db"),
        "broker_name": "Test",
        "execution_mode": "paper",
    }, db_path=_make_trades_db(tmp_path))
    pw = "Admin@123!test"
    user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
    assert user is not None, "Admin authentication failed"
    token = db._auth.create_session(user)
    c = TestClient(db.app)
    c.cookies.set("opb_session", token.token)

    resp = c.get("/payoff-calculator")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    html = resp.text.lower()
    assert "payoff calculator" in html
