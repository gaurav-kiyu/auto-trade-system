"""Integration tests for new enterprise dashboard pages and API endpoints.

Covers:
- /trade-journal HTML page route
- /live-pnl HTML page route
- /system-health HTML page route
- /event-store HTML page route
- /api/trade-journal endpoint
- /api/system/events endpoint
- /api/system/events/verify endpoint
- /api/system/notifications endpoint
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _make_trades_db(db_path: str) -> None:
    """Create a trades.db with sample trade data for journal and P&L tests."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, symbol TEXT, expiry TEXT, direction TEXT,
            strike INTEGER, qty INTEGER, entry_price REAL, exit_price REAL,
            net_pnl REAL, pnl REAL, quantity INTEGER,
            mode TEXT, strategy TEXT, status TEXT,
            entry_time TEXT, exit_time TEXT, index_name TEXT,
            score INTEGER
        )
    """)
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    trades = [
        (1, now, "NIFTY", "25MAY2026", "CALL", 25000, 75, 150.0, 185.0, 2625.0, 2625.0, 75,
         "PAPER", "BUY", "closed", now, now, "NIFTY", 82),
        (2, now, "BANKNIFTY", "25MAY2026", "PUT", 51000, 50, 200.0, 140.0, -3000.0, -3000.0, 50,
         "PAPER", "SELL", "closed", now, now, "BANKNIFTY", 45),
        (3, now, "FINNIFTY", "25MAY2026", "CALL", 22000, 40, 100.0, 130.0, 1200.0, 1200.0, 40,
         "PAPER", "BUY", "closed", now, now, "FINNIFTY", 75),
    ]
    conn.executemany(
        "INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        trades,
    )
    conn.commit()
    conn.close()


def _make_event_store_db(path: str) -> None:
    """Create a minimal event_store.db with sample events for testing."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            priority INTEGER,
            timestamp TEXT NOT NULL,
            source TEXT,
            aggregate_id TEXT,
            correlation_id TEXT,
            causation_id TEXT,
            version INTEGER DEFAULT 1,
            intent_id TEXT,
            client_order_id TEXT,
            broker_order_id TEXT,
            symbol TEXT,
            direction TEXT,
            quantity INTEGER,
            price REAL,
            metadata_json TEXT,
            sequence_number INTEGER,
            previous_hash TEXT,
            sha256 TEXT
        )
    """)
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    conn.execute("""
        INSERT INTO events (event_id, event_type, priority, timestamp, source,
            intent_id, client_order_id, symbol, direction, quantity, price,
            metadata_json, sequence_number, previous_hash, sha256)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ("evt-001", "SIGNAL_GENERATED", 2, now, "signal_generator",
          "intent-001", None, "NIFTY", "CALL", 75, 150.0,
          '{}', 1, None,
          "abc123def456"))
    conn.execute("""
        INSERT INTO events (event_id, event_type, priority, timestamp, source,
            intent_id, client_order_id, symbol, direction, quantity, price,
            metadata_json, sequence_number, previous_hash, sha256)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ("evt-002", "RISK_APPROVED", 2, now, "risk_engine",
          "intent-001", "coid-001", "NIFTY", "CALL", 75, 150.0,
          '{"limit_check": "pass"}', 2, "abc123def456",
          "def456ghi789"))
    conn.execute("""
        INSERT INTO events (event_id, event_type, priority, timestamp, source,
            intent_id, client_order_id, symbol, direction, quantity, price,
            metadata_json, sequence_number, previous_hash, sha256)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ("evt-003", "ORDER_SUBMITTED", 2, now, "execution_service",
          "intent-001", "coid-001", "NIFTY", "CALL", 75, 150.0,
          '{"broker": "paper"}', 3, "def456ghi789",
          "ghi789jkl012"))
    conn.commit()
    conn.close()


@pytest.fixture()
def state_file(tmp_path: Path) -> str:
    p = tmp_path / "trader_state.json"
    p.write_text(json.dumps({
        "daily_pnl": 1500.0, "open_positions": 2, "hard_halt": False,
        "capital": 100000, "execution_mode": "paper", "total_trades": 42,
        "base_capital": 100000,
    }))
    return str(p)


@pytest.fixture()
def trades_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "trades.db")
    _make_trades_db(db_path)
    return db_path


@pytest.fixture()
def event_db(tmp_path: Path) -> str:
    """Create an event_store.db at the CWD so the API endpoint finds it.

    The route reads the relative path db/event_store.db (Path("db/event_store.db")),
    not <cwd>/event_store.db directly - this fixture used to seed the wrong
    path, so db_file.exists() was always False and every test in this class
    was silently passing against an empty event list without ever really
    exercising the seeded rows.
    """
    original_cwd = Path.cwd()
    import os
    os.chdir(tmp_path)
    db_path = tmp_path / "db" / "event_store.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _make_event_store_db(str(db_path))
    yield str(db_path)
    os.chdir(original_cwd)


@pytest.fixture()
def dashboard(state_file: str, trades_db: str, tmp_path: Path):
    from core.enterprise_dashboard import EnterpriseDashboard

    cfg = {
        "web_dashboard_host": "127.0.0.1",
        "trader_state_path": state_file,
        "auth_db_path": str(tmp_path / "dash_auth.db"),
        "broker_name": "TestBroker",
        "execution_mode": "paper",
    }
    db = EnterpriseDashboard(config=cfg, db_path=trades_db)
    signal_log_mock = MagicMock()
    signal_log_mock.recent.return_value = []
    db.wire_bot_refs(
        pause_event=threading.Event(),
        signal_log=signal_log_mock,
    )
    return db


def _create_admin_client(db_path: str, state_file: str, tmp_path: Path) -> TestClient:
    """Helper: create an admin-authenticated test client with session cookie.

    Sets the env var BEFORE creating the dashboard so the default admin
    password is properly initialized.
    """
    import os as os_mod
    os_mod.environ["OPBUYING_DEFAULT_ADMIN_PASSWORD"] = "Admin@123!test"

    from core.enterprise_dashboard import EnterpriseDashboard
    db = EnterpriseDashboard(config={
        "web_dashboard_host": "127.0.0.1",
        "trader_state_path": state_file,
        "auth_db_path": str(tmp_path / "admin_auth.db"),
        "broker_name": "Test",
        "execution_mode": "paper",
    }, db_path=db_path)
    signal_log_mock = MagicMock()
    signal_log_mock.recent.return_value = []
    db.wire_bot_refs(
        pause_event=threading.Event(),
        signal_log=signal_log_mock,
    )

    pw = "Admin@123!test"
    user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
    assert user is not None, "Admin authentication failed"
    token = db._auth.create_session(user)
    c = TestClient(db.app)
    c.cookies.set("opb_session", token.token)
    return c


# Reusable admin client per test class - each class provides its own fixture
# to create the dashboard with the env var set first.


# ═════════════════════════════════════════════════════════════════════════════
#  Page Route Tests (New Pages)
# ═════════════════════════════════════════════════════════════════════════════


class TestTradeJournalPageRoute:
    """Test the /trade-journal HTML page route."""

    @pytest.fixture()
    def admin_client(self, trades_db: str, state_file: str, tmp_path: Path):
        return _create_admin_client(trades_db, state_file, tmp_path)

    def test_trade_journal_redirects_when_not_logged_in(self, dashboard):
        c = TestClient(dashboard.app)
        resp = c.get("/trade-journal", headers={"accept": "text/html"})
        assert resp.status_code in (200, 303, 307)
        if resp.status_code in (303, 307):
            assert "/login" in resp.headers.get("location", "")

    def test_trade_journal_authenticated(self, admin_client):
        resp = admin_client.get("/trade-journal")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        html = resp.text.lower()
        assert "trade journal" in html or "journal" in html
        assert "trade" in html


class TestLivePnlPageRoute:
    """Test the /live-pnl HTML page route."""

    @pytest.fixture()
    def admin_client(self, trades_db: str, state_file: str, tmp_path: Path):
        return _create_admin_client(trades_db, state_file, tmp_path)

    def test_live_pnl_redirects_when_not_logged_in(self, dashboard):
        c = TestClient(dashboard.app)
        resp = c.get("/live-pnl", headers={"accept": "text/html"})
        assert resp.status_code in (200, 303, 307)
        if resp.status_code in (303, 307):
            assert "/login" in resp.headers.get("location", "")

    def test_live_pnl_authenticated(self, admin_client):
        resp = admin_client.get("/live-pnl")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        html = resp.text.lower()
        assert "pnl" in html or "p&l" in html


class TestSystemHealthPageRoute:
    """Test the /system-health HTML page route."""

    @pytest.fixture()
    def admin_client(self, trades_db: str, state_file: str, tmp_path: Path):
        return _create_admin_client(trades_db, state_file, tmp_path)

    def test_system_health_redirects_when_not_logged_in(self, dashboard):
        c = TestClient(dashboard.app)
        resp = c.get("/system-health", headers={"accept": "text/html"})
        assert resp.status_code in (200, 303, 307)
        if resp.status_code in (303, 307):
            assert "/login" in resp.headers.get("location", "")

    def test_system_health_authenticated(self, admin_client):
        resp = admin_client.get("/system-health")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        html = resp.text.lower()
        assert "health" in html
        assert "system" in html


class TestEventStorePageRoute:
    """Test the /event-store HTML page route."""

    @pytest.fixture()
    def admin_client(self, trades_db: str, state_file: str, tmp_path: Path, event_db: str):
        return _create_admin_client(trades_db, state_file, tmp_path)

    def test_event_store_redirects_when_not_logged_in(self, dashboard):
        c = TestClient(dashboard.app)
        resp = c.get("/event-store", headers={"accept": "text/html"})
        assert resp.status_code in (200, 303, 307)
        if resp.status_code in (303, 307):
            assert "/login" in resp.headers.get("location", "")

    def test_event_store_authenticated(self, admin_client):
        resp = admin_client.get("/event-store")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        html = resp.text.lower()
        assert "event" in html
        assert "store" in html or "chain" in html


# ═════════════════════════════════════════════════════════════════════════════
#  API Endpoint Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestApiTradeJournal:
    """Test the /api/trade-journal endpoint."""

    def test_trade_journal_shape(self, client):
        resp = client.get("/api/trade-journal", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert "trades" in data
        assert "total" in data
        assert isinstance(data["trades"], list)
        assert data["total"] >= 3

    def test_trade_journal_fields(self, client):
        resp = client.get("/api/trade-journal", headers={"accept": "application/json"})
        data = resp.json()
        if data["trades"]:
            t = data["trades"][0]
            # Trade fields present
            for field in ("id", "symbol", "direction", "net_pnl", "entry_time"):
                assert field in t, f"Missing field: {field}"

    def test_trade_journal_filter_n(self, client):
        resp = client.get("/api/trade-journal?n=2", headers={"accept": "application/json"})
        data = resp.json()
        assert len(data["trades"]) <= 2

    @pytest.fixture()
    def client(self, dashboard) -> TestClient:
        return TestClient(dashboard.app)


class TestApiEvents:
    """Test the /api/system/events endpoint."""

    def test_events_shape(self, client):
        resp = client.get("/api/system/events", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert "total" in data
        assert isinstance(data["events"], list)

    def test_events_fields(self, client):
        resp = client.get("/api/system/events", headers={"accept": "application/json"})
        data = resp.json()
        if data["events"]:
            evt = data["events"][0]
            for field in ("event_id", "event_type", "timestamp", "source"):
                assert field in evt, f"Missing field: {field}"

    def test_events_limit(self, client):
        resp = client.get("/api/system/events?n=10", headers={"accept": "application/json"})
        data = resp.json()
        assert len(data["events"]) <= 10

    def test_events_no_crash(self, client):
        resp = client.get("/api/system/events?n=1000", headers={"accept": "application/json"})
        assert resp.status_code == 200

    def test_event_type_filter_uses_real_enum_value(self, client):
        """Regression: the event-store screen's dropdown used to send
        'SignalGenerated' (a made-up label), which is not a real EventType
        value - EventType('SignalGenerated') raises ValueError, and the
        handler's except branch then misinterprets the label as an order ID
        via get_events_for_order(), so the type filter silently did nothing.
        The dropdown now sends the real enum string 'SIGNAL_GENERATED'."""
        resp = client.get(
            "/api/system/events?event_type=SIGNAL_GENERATED",
            headers={"accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["events"]
        assert all(e["event_type"] == "SIGNAL_GENERATED" for e in data["events"])

    @pytest.fixture()
    def dashboard(self, state_file: str, trades_db: str, tmp_path: Path, event_db: str):
        """Override dashboard fixture to chdir to tmp for event_store.db."""
        from core.enterprise_dashboard import EnterpriseDashboard

        cfg = {
            "web_dashboard_host": "127.0.0.1",
            "trader_state_path": state_file,
            "auth_db_path": str(tmp_path / "dash_auth.db"),
            "broker_name": "Test",
            "execution_mode": "paper",
        }
        db = EnterpriseDashboard(config=cfg, db_path=trades_db)
        signal_log_mock = MagicMock()
        signal_log_mock.recent.return_value = []
        db.wire_bot_refs(
            pause_event=threading.Event(),
            signal_log=signal_log_mock,
        )
        return db

    @pytest.fixture()
    def client(self, dashboard) -> TestClient:
        return TestClient(dashboard.app)


class TestApiEventsVerify:
    """Test the /api/system/events/verify endpoint."""

    def test_verify_shape(self, client):
        resp = client.get("/api/system/events/verify", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert "is_valid" in data
        assert "events_checked" in data
        assert "message" in data
        assert isinstance(data["is_valid"], bool)

    def test_verify_no_crash(self, client):
        resp = client.get("/api/system/events/verify", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        # With our test DB that has hash values, it should validate or at least not crash
        assert data["events_checked"] >= 0

    @pytest.fixture()
    def dashboard(self, state_file: str, trades_db: str, tmp_path: Path, event_db: str):
        import os

        from core.enterprise_dashboard import EnterpriseDashboard

        os.chdir(tmp_path)
        cfg = {
            "web_dashboard_host": "127.0.0.1",
            "trader_state_path": state_file,
            "auth_db_path": str(tmp_path / "dash_auth.db"),
            "broker_name": "Test",
            "execution_mode": "paper",
        }
        db = EnterpriseDashboard(config=cfg, db_path=trades_db)
        signal_log_mock = MagicMock()
        signal_log_mock.recent.return_value = []
        db.wire_bot_refs(
            pause_event=threading.Event(),
            signal_log=signal_log_mock,
        )
        return db

    @pytest.fixture()
    def client(self, dashboard) -> TestClient:
        return TestClient(dashboard.app)


class TestApiNotifications:
    """Test the /api/system/notifications endpoint."""

    def test_list_notifications_empty(self, client):
        resp = client.get("/api/system/notifications", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert "notifications" in data
        assert "total" in data
        assert isinstance(data["notifications"], list)
        assert data["total"] >= 0

    def test_list_notifications_after_push(self, dashboard, client):
        dashboard._notifications.push("API test", severity="WARNING", category="test")
        resp = client.get("/api/system/notifications", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any(n["message"] == "API test" for n in data["notifications"])

    def test_push_and_list_integration(self, dashboard, client):
        dashboard._notifications.push("Integration test", severity="WARNING", category="test")
        resp = client.get("/api/system/notifications", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert any(n["message"] == "Integration test" for n in data["notifications"])

    def test_notification_fields(self, dashboard, client):
        dashboard._notifications.push("Field test", severity="INFO", category="test")
        resp = client.get("/api/system/notifications", headers={"accept": "application/json"})
        data = resp.json()
        if data["notifications"]:
            n = data["notifications"][-1]
            for field in ("id", "message", "severity", "category", "timestamp", "timestamp_human"):
                assert field in n, f"Missing field: {field}"

    def test_notification_n_param(self, dashboard, client):
        dashboard._notifications.push("One", severity="INFO", category="test")
        dashboard._notifications.push("Two", severity="WARNING", category="test")
        resp = client.get("/api/system/notifications?n=1", headers={"accept": "application/json"})
        data = resp.json()
        assert data["total"] <= 2
        assert len(data["notifications"]) <= 1

    @pytest.fixture()
    def client(self, dashboard) -> TestClient:
        return TestClient(dashboard.app)
