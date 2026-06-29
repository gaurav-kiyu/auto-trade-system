"""
Tests for new Enterprise Dashboard features:
- NotificationManager class (push, acknowledge, subscribe, clear)
- Notification REST API endpoints (list, acknowledge via internal)
- SSE notification stream (tested via NotificationManager directly)
- Performance comparison API endpoint
- push_notification() helper method

Follows the same patterns as test_enterprise_dashboard.py.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

# ── Helper ───────────────────────────────────────────────────────────────────


def _make_trades_db(db_path: str) -> None:
    """Create a sample trades.db with data for performance comparison tests."""
    import sqlite3
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
            regime TEXT, score INTEGER, reason TEXT
        )
    """)
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    trades = [
        (1, now, "NIFTY", "25MAY2026", "CALL", 25000, 75, 150.0, 185.0, 2625.0, 2625.0, 75,
         "PAPER", "BUY", "closed", now, now, "NIFTY", "TRENDING", 82, "TAKE_PROFIT"),
        (2, now, "BANKNIFTY", "25MAY2026", "PUT", 51000, 50, 200.0, 120.0, -4000.0, -4000.0, 50,
         "PAPER", "BUY", "closed", now, now, "BANKNIFTY", "RANGING", 65, "STOP_LOSS"),
        (3, now, "NIFTY", "25MAY2026", "CALL", 25100, 50, 100.0, 155.0, 2750.0, 2750.0, 50,
         "PAPER", "BUY", "closed", now, now, "NIFTY", "TRENDING", 91, "TAKE_PROFIT"),
        (4, now, "FINNIFTY", "25MAY2026", "CALL", 22000, 30, 180.0, 170.0, -300.0, -300.0, 30,
         "PAPER", "BUY", "closed", now, now, "FINNIFTY", "VOLATILE", 72, "MANUAL"),
        (5, now, "NIFTY", "25MAY2026", "PUT", 24900, 60, 90.0, 130.0, 2400.0, 2400.0, 60,
         "PAPER", "BUY", "closed", now, now, "NIFTY", "TRENDING", 88, "TAKE_PROFIT"),
    ]
    conn.executemany(
        "INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        trades,
    )
    conn.commit()
    conn.close()


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def notif_mgr():
    """Create a fresh NotificationManager for each test."""
    from core.enterprise_dashboard import NotificationManager
    return NotificationManager(maxlen=100)


@pytest.fixture()
def populated_mgr(notif_mgr):
    """NotificationManager pre-populated with sample notifications."""
    notif_mgr.push("Trade exited with profit", severity="INFO", category="trade", source="bot")
    notif_mgr.push("Daily loss limit reached", severity="CRITICAL", category="risk", source="bot")
    notif_mgr.push("ML model drift detected", severity="WARNING", category="ml", source="ml_engine")
    notif_mgr.push("Broker connection lost", severity="ERROR", category="broker", source="broker_adapter")
    notif_mgr.push("System health check passed", severity="INFO", category="system", source="health_checker")
    return notif_mgr


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
def dashboard(state_file: str, trades_db: str, tmp_path: Path):
    from core.enterprise_dashboard import EnterpriseDashboard

    cfg = {
        "web_dashboard_host": "127.0.0.1",
        "trader_state_path": state_file,
        "auth_db_path": str(tmp_path / "dash_auth.db"),
        "broker_name": "Zerodha",
        "execution_mode": "paper",
    }
    db = EnterpriseDashboard(config=cfg, db_path=trades_db)
    db.wire_bot_refs(pause_event=threading.Event())
    return db


@pytest.fixture()
def client(dashboard) -> TestClient:
    return TestClient(dashboard.app)


# ═════════════════════════════════════════════════════════════════════════════
#  NotificationManager Unit Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestNotificationManager:
    """Direct unit tests for NotificationManager without API layer."""

    def test_push_returns_notification(self, notif_mgr):
        n = notif_mgr.push("Test message", severity="INFO", category="test")
        assert n is not None
        assert n.message == "Test message"
        assert n.severity == "INFO"
        assert n.category == "test"
        assert n.source == "dashboard"
        assert n.id is not None
        assert len(n.id) == 12
        assert n.timestamp > 0
        assert not n.acknowledged

    def test_push_with_all_fields(self, notif_mgr):
        details = {"pnl": 2500, "trades": 5}
        n = notif_mgr.push("Trade summary", severity="WARNING", category="trade",
                           source="bot_engine", details=details)
        assert n.message == "Trade summary"
        assert n.severity == "WARNING"
        assert n.category == "trade"
        assert n.source == "bot_engine"
        assert n.details == details

    def test_push_auto_uppercases_severity(self, notif_mgr):
        n = notif_mgr.push("test", severity="critical", category="test")
        assert n.severity == "CRITICAL"

    def test_recent_returns_empty(self, notif_mgr):
        assert notif_mgr.recent() == []

    def test_recent_after_push(self, notif_mgr):
        notif_mgr.push("msg1", severity="INFO", category="test")
        notif_mgr.push("msg2", severity="ERROR", category="test")
        recent = notif_mgr.recent()
        assert len(recent) == 2
        assert recent[0]["message"] == "msg1"
        assert recent[1]["message"] == "msg2"

    def test_recent_limited_to_n(self, populated_mgr):
        recent = populated_mgr.recent(n=3)
        assert len(recent) == 3

    def test_recent_returns_dicts(self, populated_mgr):
        recent = populated_mgr.recent(n=2)
        for r in recent:
            assert "id" in r
            assert "message" in r
            assert "severity" in r
            assert "category" in r
            assert "timestamp" in r
            assert "timestamp_human" in r
            assert "acknowledged" in r

    def test_notification_to_dict(self, notif_mgr):
        n = notif_mgr.push("Hello", severity="INFO", category="system")
        d = n.to_dict()
        assert d["id"] == n.id
        assert d["message"] == "Hello"
        assert d["severity"] == "INFO"
        assert d["acknowledged"] is False

    def test_acknowledge_single(self, populated_mgr):
        recent = populated_mgr.recent()
        first_id = recent[0]["id"]
        ok = populated_mgr.acknowledge(first_id)
        assert ok is True
        for n in populated_mgr.recent():
            if n["id"] == first_id:
                assert n["acknowledged"] is True
                break
        else:
            pytest.fail("Acknowledged notification not found")

    def test_acknowledge_nonexistent_returns_false(self, notif_mgr):
        ok = notif_mgr.acknowledge("nonexistent-id-1234")
        assert ok is False

    def test_acknowledge_all_without_severity(self, populated_mgr):
        count = populated_mgr.acknowledge_all()
        assert count == 5
        for n in populated_mgr.recent():
            assert n["acknowledged"] is True

    def test_acknowledge_all_with_severity_filter(self, populated_mgr):
        count = populated_mgr.acknowledge_all(severity="CRITICAL")
        assert count == 1
        for n in populated_mgr.recent():
            if n["severity"] == "CRITICAL":
                assert n["acknowledged"] is True
            else:
                assert n["acknowledged"] is False

    def test_acknowledge_all_case_insensitive(self, populated_mgr):
        count = populated_mgr.acknowledge_all(severity="critical")
        assert count == 1

    def test_clear(self, populated_mgr):
        count = populated_mgr.clear()
        assert count == 5
        assert populated_mgr.recent() == []
        assert populated_mgr.count == 0

    def test_count_property(self, notif_mgr):
        assert notif_mgr.count == 0
        notif_mgr.push("test", category="test")
        assert notif_mgr.count == 1
        notif_mgr.push("test2", category="test")
        assert notif_mgr.count == 2

    def test_maxlen_enforced(self):
        from core.enterprise_dashboard import NotificationManager
        mgr = NotificationManager(maxlen=3)
        mgr.push("a", category="test")
        mgr.push("b", category="test")
        mgr.push("c", category="test")
        mgr.push("d", category="test")
        assert mgr.count == 3
        messages = [n["message"] for n in mgr.recent()]
        assert "a" not in messages
        assert messages == ["b", "c", "d"]

    def test_severity_levels(self, notif_mgr):
        for sev in ["INFO", "WARNING", "ERROR", "CRITICAL"]:
            n = notif_mgr.push(f"test {sev}", severity=sev, category="test")
            assert n.severity == sev

    def test_severity_default_is_info(self, notif_mgr):
        n = notif_mgr.push("test message", category="test")
        assert n.severity == "INFO"

    def test_subscribe_registers_subscriber(self, notif_mgr):
        """subscribe() registers a subscriber when driven by an event loop."""
        import asyncio
        async def _run():
            gen = notif_mgr.subscribe()
            # Launch concurrent reader task
            async def _reader():
                async for n in gen:
                    pass  # consume until cancelled
            task = asyncio.create_task(_reader())
            await asyncio.sleep(0.01)  # Let generator start
            with notif_mgr._sub_lock:
                assert len(notif_mgr._subscribers) == 1
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            with notif_mgr._sub_lock:
                assert len(notif_mgr._subscribers) == 0
        asyncio.run(_run())

    def test_subscribe_returns_async_gen(self, notif_mgr):
        """subscribe() returns an object with async generator methods."""
        gen = notif_mgr.subscribe()
        assert hasattr(gen, "__anext__")
        assert hasattr(gen, "aclose")
        assert hasattr(gen, "asend")
        assert hasattr(gen, "athrow")

    def test_subscribe_push_notifies_subscriber(self, notif_mgr):
        """After subscribe() starts, push() adds to the subscriber queue."""
        import asyncio
        async def _run():
            gen = notif_mgr.subscribe()
            async def _reader():
                async for n in gen:
                    pass
            task = asyncio.create_task(_reader())
            await asyncio.sleep(0.01)
            with notif_mgr._sub_lock:
                assert len(notif_mgr._subscribers) == 1
                q = notif_mgr._subscribers[0]
                assert q.qsize() == 0
            notif_mgr.push("test notification", severity="INFO", category="test")
            with notif_mgr._sub_lock:
                q = notif_mgr._subscribers[0]
                assert q.qsize() == 1
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
        asyncio.run(_run())


# ═════════════════════════════════════════════════════════════════════════════
#  Notification REST API Tests (GET via TestClient, POST via internal methods)
# ═════════════════════════════════════════════════════════════════════════════


class TestApiNotifications:
    """Test notification REST endpoints."""

    def test_list_notifications_empty(self, client: TestClient):
        resp = client.get("/api/system/notifications", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert "notifications" in data
        assert data["total"] >= 0

    def test_list_notifications_after_push(self, dashboard, client: TestClient):
        dashboard._notifications.push("API test", severity="WARNING", category="test")
        resp = client.get("/api/system/notifications", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any(n["message"] == "API test" for n in data["notifications"])

    def test_acknowledge_via_internal(self, dashboard):
        """Test acknowledge via internal method (avoids CSRF on POST)."""
        n = dashboard._notifications.push("Ack test", severity="INFO", category="test")
        ok = dashboard._notifications.acknowledge(n.id)
        assert ok is True
        for notif in dashboard._notifications.recent():
            if notif["id"] == n.id:
                assert notif["acknowledged"] is True
                break
        else:
            pytest.fail("Notification not found")

    def test_acknowledge_all_via_internal(self, dashboard):
        dashboard._notifications.push("A1", severity="INFO", category="test")
        dashboard._notifications.push("A2", severity="WARNING", category="test")
        count = dashboard._notifications.acknowledge_all()
        assert count >= 2

    def test_acknowledge_with_severity_via_internal(self, dashboard):
        dashboard._notifications.push("Err", severity="ERROR", category="test")
        dashboard._notifications.push("Info", severity="INFO", category="test")
        count = dashboard._notifications.acknowledge_all(severity="ERROR")
        assert count >= 1
        for n in dashboard._notifications.recent():
            if n["severity"] == "ERROR":
                assert n["acknowledged"] is True
            elif n["severity"] == "INFO":
                assert n["acknowledged"] is False

    def test_push_and_list_integration(self, dashboard, client: TestClient):
        """Push via internal, verify via GET API."""
        dashboard._notifications.push("Integration test", severity="WARNING", category="test")
        resp = client.get("/api/system/notifications", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert any(n["message"] == "Integration test" for n in data["notifications"])

    def test_push_notification_with_details(self, notif_mgr):
        n = notif_mgr.push("With details", severity="CRITICAL", details={"key": "value"})
        assert n.severity == "CRITICAL"
        assert n.details == {"key": "value"}


# ═════════════════════════════════════════════════════════════════════════════
#  SSE Notification Stream Tests (via NotificationManager, avoiding HTTP auth)
# ═════════════════════════════════════════════════════════════════════════════


class TestSseNotificationStream:
    """Test SSE notification stream via NotificationManager subscribe/push API.

    The HTTP SSE endpoint at /api/system/notifications/stream is tested
    indirectly through the NotificationManager's subscribe() and push() methods.
    The StreamingResponse wrapper is trivially tested in the endpoint definition.
    """

    def test_subscribe_receives_pushed_notification(self, notif_mgr):
        """A subscriber receives notifications pushed after subscribing."""
        import asyncio
        async def _run():
            gen = notif_mgr.subscribe()
            async def _reader():
                async for n in gen:
                    pass
            task = asyncio.create_task(_reader())
            await asyncio.sleep(0.01)
            notif_mgr.push("SSE test msg", severity="INFO", category="test")
            with notif_mgr._sub_lock:
                assert len(notif_mgr._subscribers) >= 1
                q = notif_mgr._subscribers[0]
                assert q.qsize() >= 1
                item = q.get_nowait()
                assert item["message"] == "SSE test msg"
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
        asyncio.run(_run())

    def test_multiple_subscribers_receive_push(self, notif_mgr):
        """Multiple subscribers all receive the same notification."""
        import asyncio
        async def _run():
            gen1 = notif_mgr.subscribe()
            gen2 = notif_mgr.subscribe()
            async def _reader1():
                async for n in gen1:
                    pass
            async def _reader2():
                async for n in gen2:
                    pass
            t1 = asyncio.create_task(_reader1())
            t2 = asyncio.create_task(_reader2())
            await asyncio.sleep(0.01)
            notif_mgr.push("broadcast", severity="INFO", category="test")
            with notif_mgr._sub_lock:
                assert len(notif_mgr._subscribers) == 2
                for q in notif_mgr._subscribers:
                    assert q.qsize() == 1
                    item = q.get_nowait()
                    assert item["message"] == "broadcast"
            t1.cancel()
            t2.cancel()
            try:
                await t1
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            try:
                await t2
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
        asyncio.run(_run())

    def test_subscribe_cleanup_on_close(self, notif_mgr):
        """Closing the generator removes it from subscriber list."""
        import asyncio
        async def _run():
            gen = notif_mgr.subscribe()
            async def _reader():
                async for n in gen:
                    pass
            task = asyncio.create_task(_reader())
            await asyncio.sleep(0.01)
            assert len(notif_mgr._subscribers) == 1
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            with notif_mgr._sub_lock:
                assert len(notif_mgr._subscribers) == 0
        asyncio.run(_run())


# ═════════════════════════════════════════════════════════════════════════════
#  Performance Comparison API Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestApiPerformanceComparison:
    """Test the performance comparison API endpoint."""

    def test_performance_returns_ok(self, client: TestClient):
        resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["trades_count"] >= 5

    def test_performance_overall_metrics(self, client: TestClient):
        resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})
        data = resp.json()
        overall = data.get("overall", {})
        assert overall.get("trades", 0) >= 5
        assert "win_rate" in overall
        assert "total_net_pnl" in overall
        assert "profit_factor" in overall

    def test_performance_all_breakdowns(self, client: TestClient):
        resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})
        data = resp.json()
        assert "by_regime" in data
        assert "by_score_bin" in data
        assert "by_direction" in data
        assert "by_index" in data
        assert "by_exit_reason" in data

    def test_performance_regime_breakdown(self, client: TestClient):
        resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})
        data = resp.json()
        regimes = data.get("by_regime", {})
        assert len(regimes) >= 1
        if "TRENDING" in regimes:
            assert regimes["TRENDING"]["trades"] >= 3
            assert "win_rate" in regimes["TRENDING"]

    def test_performance_index_breakdown(self, client: TestClient):
        resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})
        data = resp.json()
        indices = data.get("by_index", {})
        assert len(indices) >= 1
        if "NIFTY" in indices:
            assert indices["NIFTY"]["trades"] >= 3

    def test_performance_direction_breakdown(self, client: TestClient):
        resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})
        data = resp.json()
        directions = data.get("by_direction", {})
        assert len(directions) >= 1
        if "CALL" in directions:
            assert directions["CALL"]["trades"] >= 3

    def test_performance_score_bins(self, client: TestClient):
        resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})
        data = resp.json()
        assert len(data.get("by_score_bin", {})) >= 1

    def test_performance_exit_reason(self, client: TestClient):
        resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})
        data = resp.json()
        exits = data.get("by_exit_reason", {})
        assert len(exits) >= 1
        if "TAKE_PROFIT" in exits:
            assert "pct_of_total" in exits["TAKE_PROFIT"]

    def test_performance_insights(self, client: TestClient):
        resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})
        data = resp.json()
        insights = data.get("insights", [])
        assert len(insights) >= 1
        assert all(isinstance(i, str) for i in insights)

    def test_performance_with_days_param(self, client: TestClient):
        resp = client.get("/api/performance/comparison?days=30", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["period_days"] == 30

    def test_performance_with_mode_param(self, client: TestClient):
        resp = client.get("/api/performance/comparison?mode=PAPER", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["period_mode"] == "PAPER"

    def test_performance_invalid_days_default(self, client: TestClient):
        resp = client.get("/api/performance/comparison?days=abc", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["period_days"] == 90

    def test_performance_empty_db(self, tmp_path: Path, state_file: str):
        """No trades in empty DB returns empty breakdowns."""
        import sqlite3

        from core.enterprise_dashboard import EnterpriseDashboard

        empty_db = str(tmp_path / "empty_trades.db")
        conn = sqlite3.connect(empty_db)
        conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "trader_state_path": state_file,
            "auth_db_path": str(tmp_path / "auth.db"),
        }, db_path=empty_db)
        c = TestClient(db.app)
        resp = c.get("/api/performance/comparison", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["trades_count"] == 0
        assert data["overall"] == {}


# ═════════════════════════════════════════════════════════════════════════════
#  push_notification Helper Method Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestPushNotificationMethod:
    """Test the EnterpriseDashboard.push_notification() helper."""

    def test_push_notification_with_all_params(self, dashboard):
        n = dashboard.push_notification(
            "System alert", severity="WARNING", category="system",
            details={"source": "test"},
        )
        assert n is not None
        assert n.message == "System alert"
        assert n.severity == "WARNING"
        assert n.category == "system"
        assert n.source == "system"
        assert n.details == {"source": "test"}

    def test_push_notification_appears_in_recent(self, dashboard):
        dashboard.push_notification("Helper test", severity="INFO", category="system")
        assert any(n["message"] == "Helper test" for n in dashboard._notifications.recent())

    def test_push_notification_defaults(self, dashboard):
        n = dashboard.push_notification("Minimal call")
        assert n.message == "Minimal call"
        assert n.severity == "INFO"
        assert n.category == "system"

    def test_push_notification_critical(self, dashboard):
        dashboard.push_notification("CRITICAL alert!", severity="CRITICAL", category="risk")
        crits = [n for n in dashboard._notifications.recent() if n["severity"] == "CRITICAL"]
        assert len(crits) >= 1
        assert crits[-1]["message"] == "CRITICAL alert!"
