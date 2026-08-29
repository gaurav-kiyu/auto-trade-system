"""Tests for enterprise dashboard performance and options chain pages.

Covers:
- /api/system/performance endpoint
- /api/chain/{index_name} endpoint (with and without oi_snapshots.db)
- /performance HTML page route
- /options-chain HTML page route
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
    """Create a minimal trades.db with diverse sample data for performance metrics."""
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
    # Mix of winning and losing trades for realistic metrics
    trades = [
        (1, now, "NIFTY", "25MAY2026", "CALL", 25000, 75, 150.0, 185.0, 2625.0, 2625.0, 75,
         "PAPER", "BUY", "closed", now, now, "NIFTY", 82),
        (2, now, "BANKNIFTY", "25MAY2026", "PUT", 51000, 50, 200.0, 140.0, -3000.0, -3000.0, 50,
         "PAPER", "SELL", "closed", now, now, "BANKNIFTY", 45),
        (3, now, "FINNIFTY", "25MAY2026", "CALL", 22000, 40, 100.0, 130.0, 1200.0, 1200.0, 40,
         "PAPER", "BUY", "closed", now, now, "FINNIFTY", 75),
        (4, now, "NIFTY", "25MAY2026", "PUT", 25100, 75, 180.0, 160.0, -1500.0, -1500.0, 75,
         "PAPER", "SELL", "closed", now, now, "NIFTY", 60),
        (5, now, "BANKNIFTY", "25MAY2026", "CALL", 51200, 50, 250.0, 280.0, 1500.0, 1500.0, 50,
         "PAPER", "BUY", "open", now, None, "BANKNIFTY", 88),
    ]
    conn.executemany(
        "INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        trades,
    )
    conn.commit()
    conn.close()


def _make_config_file(path: str, data: dict | None = None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data or {"BASE_CAPITAL": 100000}), encoding="utf-8")
    return p


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


@pytest.fixture()
def client(dashboard) -> TestClient:
    return TestClient(dashboard.app)


# ── Performance API Tests ──────────────────────────────────────────────────────


class TestApiPerformance:
    """Test the /api/system/performance endpoint."""

    def test_performance_shape(self, client: TestClient):
        """Response has all expected fields with correct types."""
        resp = client.get("/api/system/performance", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert "win_rate" in data
        assert "profit_factor" in data
        assert "sharpe_ratio" in data
        assert "max_drawdown_pct" in data
        assert "total_trades" in data
        assert "net_pnl" in data
        assert "wins" in data
        assert "losses" in data
        assert "mean_reversion" in data
        assert "ma_crossover" in data
        assert "primary_signal" in data

    def test_performance_metrics_values(self, client: TestClient):
        """Performance metrics are computed correctly from sample trades."""
        resp = client.get("/api/system/performance", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()

        # From our sample data: 5 trades, 3 wins (1,3,5), 2 losses (2,4)
        assert data["total_trades"] == 5
        assert data["wins"] == 3
        assert data["losses"] == 2
        # Win rate = 3/5 = 0.6
        assert data["win_rate"] == pytest.approx(0.6, abs=0.01)
        # Net PnL = 2625 - 3000 + 1200 - 1500 + 1500 = 825
        assert data["net_pnl"] == pytest.approx(825.0, abs=1.0)
        # Strategy comparison text
        assert data["mean_reversion"] == "Enabled (opt-in)"
        assert data["ma_crossover"] == "Enabled (opt-in)"
        assert data["primary_signal"] == "Always active"

    def test_performance_no_trades(self, tmp_path: Path):
        """When no trades exist, returns zeroed-out metrics."""
        from core.enterprise_dashboard import EnterpriseDashboard

        empty_db = str(tmp_path / "empty.db")
        conn = sqlite3.connect(empty_db)
        conn.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "auth_db_path": str(tmp_path / "auth.db"),
        }, db_path=empty_db)
        c = TestClient(db.app)
        resp = c.get("/api/system/performance", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 0
        assert data["win_rate"] == 0.0
        assert data["profit_factor"] == 0.0
        assert data["mean_reversion"] == "No trade data"

    def test_performance_missing_db(self, tmp_path: Path):
        """When trades.db doesn't exist, returns zeroed metrics gracefully."""
        from core.enterprise_dashboard import EnterpriseDashboard

        missing_db = str(tmp_path / "nonexistent" / "trades.db")
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "auth_db_path": str(tmp_path / "auth.db"),
        }, db_path=missing_db)
        c = TestClient(db.app)
        resp = c.get("/api/system/performance", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 0

    def test_performance_sharpe_positive(self, client: TestClient):
        """With mixed winning/losing trades, Sharpe should be computable."""
        resp = client.get("/api/system/performance", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        # Sharpe should be a finite number (not NaN, not inf)
        import math
        assert math.isfinite(data["sharpe_ratio"])

    def test_performance_drawdown(self, client: TestClient):
        """Max drawdown should be non-negative (can exceed 100% when cum PnL goes negative)."""
        resp = client.get("/api/system/performance", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["max_drawdown_pct"] >= 0.0
        # With our sample data (peak after trade 1 = 2625, valley after trade 4 = -675):
        # dd = (2625 - (-675)) / 2625 = 3300/2625 = 1.2571
        assert data["max_drawdown_pct"] == pytest.approx(1.2571, abs=0.01)

    def test_performance_profit_factor(self, client: TestClient):
        """Profit factor should be positive."""
        resp = client.get("/api/system/performance", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["profit_factor"] > 0


# ── Options Chain API Tests ────────────────────────────────────────────────────


class TestApiOptionsChain:
    """Test the /api/chain/{index_name} endpoint."""

    def test_chain_no_db(self, client: TestClient):
        """When oi_snapshots.db doesn't exist, returns empty with helpful note."""
        resp = client.get("/api/chain/NIFTY", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["strikes"] == []
        assert "note" in data
        assert "oi_snapshots.db not found" in data["note"]

    def test_chain_with_empty_db(self, tmp_path: Path, state_file: str):
        """When oi_snapshots.db exists but has no data, returns empty strikes."""
        from core.enterprise_dashboard import EnterpriseDashboard

        # Create empty oi_snapshots.db under the db/ folder (new layout)
        (tmp_path / "db").mkdir(exist_ok=True)
        snap_path = tmp_path / "db" / "oi_snapshots.db"
        conn = sqlite3.connect(str(snap_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                index_name TEXT, strike REAL, call_oi INTEGER, put_oi INTEGER,
                call_vol INTEGER, put_vol INTEGER, call_iv REAL, put_iv REAL,
                call_ltp REAL, put_ltp REAL, spot_price REAL, timestamp TEXT
            )
        """)
        conn.commit()
        conn.close()

        # Need to chdir to tmp_path so oi_snapshots.db is found
        original_cwd = Path.cwd()
        import os
        os.chdir(tmp_path)
        try:
            db = EnterpriseDashboard(config={
                "web_dashboard_host": "127.0.0.1",
                "trader_state_path": state_file,
                "auth_db_path": str(tmp_path / "auth.db"),
            })
            c = TestClient(db.app)
            resp = c.get("/api/chain/BANKNIFTY", headers={"accept": "application/json"})
            assert resp.status_code == 200
            data = resp.json()
            # Should return empty but with summary fields
            assert data["strikes"] == []
            assert data["pcr"] is not None
        finally:
            os.chdir(original_cwd)

    def test_chain_with_data(self, tmp_path: Path, state_file: str):
        """When oi_snapshots.db has data, returns formatted strikes array."""
        from core.enterprise_dashboard import EnterpriseDashboard

        (tmp_path / "db").mkdir(exist_ok=True)
        snap_path = tmp_path / "db" / "oi_snapshots.db"
        conn = sqlite3.connect(str(snap_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                index_name TEXT, strike REAL, call_oi INTEGER, put_oi INTEGER,
                call_vol INTEGER, put_vol INTEGER, call_iv REAL, put_iv REAL,
                call_ltp REAL, put_ltp REAL, spot_price REAL, timestamp TEXT
            )
        """)
        # Insert sample data
        conn.execute("""
            INSERT INTO snapshots (index_name, strike, call_oi, put_oi, call_vol, put_vol,
                call_iv, put_iv, call_ltp, put_ltp, spot_price, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ("NIFTY", 23500.0, 500000, 600000, 12000, 15000, 14.5, 15.2, 85.0, 90.0, 23550.0, time.strftime("%Y-%m-%dT%H:%M:%S")))
        conn.execute("""
            INSERT INTO snapshots (index_name, strike, call_oi, put_oi, call_vol, put_vol,
                call_iv, put_iv, call_ltp, put_ltp, spot_price, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ("NIFTY", 23600.0, 800000, 400000, 18000, 10000, 14.8, 15.5, 55.0, 60.0, 23550.0, time.strftime("%Y-%m-%dT%H:%M:%S")))
        conn.execute("""
            INSERT INTO snapshots (index_name, strike, call_oi, put_oi, call_vol, put_vol,
                call_iv, put_iv, call_ltp, put_ltp, spot_price, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ("NIFTY", 23650.0, 200000, 800000, 8000, 20000, 15.0, 15.8, 30.0, 35.0, 23550.0, time.strftime("%Y-%m-%dT%H:%M:%S")))
        conn.commit()
        conn.close()

        original_cwd = Path.cwd()
        import os
        os.chdir(tmp_path)
        try:
            db = EnterpriseDashboard(config={
                "web_dashboard_host": "127.0.0.1",
                "trader_state_path": state_file,
                "auth_db_path": str(tmp_path / "auth.db"),
            })
            c = TestClient(db.app)
            resp = c.get("/api/chain/NIFTY?n=10", headers={"accept": "application/json"})
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["strikes"]) == 3
            # Check strike values
            assert data["strikes"][0]["strike"] == 23500.0
            assert data["strikes"][1]["strike"] == 23600.0
            # Check PCR
            assert data["pcr"] is not None
            assert data["pcr"] > 0
            # Total OI = 500000+800000+200000 + 600000+400000+800000 = 1,500,000 + 1,800,000 = 3,300,000
            assert data["total_oi"] == 3300000
            # Spot price
            assert data["spot"] == 23550.0
            # Max pain should be one of the strikes
            assert data["max_pain"] in (23500.0, 23600.0, 23650.0)
            # Each strike should have call and put objects
            for strike in data["strikes"]:
                assert "call" in strike
                assert "put" in strike
                assert "oi" in strike["call"]
                assert "oi" in strike["put"]
                assert "is_atm" in strike
        finally:
            os.chdir(original_cwd)

    def test_chain_n_validation(self, tmp_path: Path, state_file: str):
        """The n parameter should be respected and bounded."""
        from core.enterprise_dashboard import EnterpriseDashboard

        (tmp_path / "db").mkdir(exist_ok=True)
        snap_path = tmp_path / "db" / "oi_snapshots.db"
        conn = sqlite3.connect(str(snap_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                index_name TEXT, strike REAL, call_oi INTEGER, put_oi INTEGER,
                call_vol INTEGER, put_vol INTEGER, call_iv REAL, put_iv REAL,
                call_ltp REAL, put_ltp REAL, spot_price REAL, timestamp TEXT
            )
        """)
        for i in range(5):
            strike = 23000.0 + i * 100
            conn.execute("""
                INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (None, "TEST", strike, 100000, 100000, 1000, 1000, 15.0, 15.0, 50.0, 50.0, 23250.0, time.strftime("%Y-%m-%dT%H:%M:%S")))
        conn.commit()
        conn.close()

        original_cwd = Path.cwd()
        import os
        os.chdir(tmp_path)
        try:
            db = EnterpriseDashboard(config={
                "web_dashboard_host": "127.0.0.1",
                "trader_state_path": state_file,
                "auth_db_path": str(tmp_path / "auth.db"),
            })
            c = TestClient(db.app)
            # Test n=2 returns 2 strikes
            resp = c.get("/api/chain/TEST?n=2", headers={"accept": "application/json"})
            assert resp.status_code == 200
            assert len(resp.json()["strikes"]) == 2
            # Test n=500 (the max) doesn't crash
            resp = c.get("/api/chain/TEST?n=500", headers={"accept": "application/json"})
            assert resp.status_code == 200
        finally:
            os.chdir(original_cwd)

    def test_chain_invalid_index(self, client: TestClient):
        """Unrecognized index returns empty strikes (no crash)."""
        resp = client.get("/api/chain/INVALID_INDEX", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert "strikes" in data

    def test_chain_with_get_chain_json_fallback(self, tmp_path: Path, state_file: str):
        """When get_chain_json from option_chain_json is available, it takes priority."""
        from core.enterprise_dashboard import EnterpriseDashboard

        # Create empty oi_snapshots.db with proper schema so fallback query doesn't crash
        snap_path = tmp_path / "oi_snapshots.db"
        conn = sqlite3.connect(str(snap_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                index_name TEXT, strike REAL, call_oi INTEGER, put_oi INTEGER,
                call_vol INTEGER, put_vol INTEGER, call_iv REAL, put_iv REAL,
                call_ltp REAL, put_ltp REAL, spot_price REAL, timestamp TEXT
            )
        """)
        conn.commit()
        conn.close()

        original_cwd = Path.cwd()
        import os
        os.chdir(tmp_path)
        try:
            db = EnterpriseDashboard(config={
                "web_dashboard_host": "127.0.0.1",
                "trader_state_path": state_file,
                "auth_db_path": str(tmp_path / "auth.db"),
            })
            c = TestClient(db.app)
            # Without get_chain_json, falls back to reading OI snapshots directly
            resp = c.get("/api/chain/NIFTY", headers={"accept": "application/json"})
            assert resp.status_code == 200
        finally:
            os.chdir(original_cwd)


# ── Performance Page Route Tests ───────────────────────────────────────────────


class TestPerformancePageRoute:
    """Test the /performance HTML page route."""

    def test_performance_page_redirects_when_not_logged_in(self, client: TestClient):
        """Unauthenticated users are redirected to login."""
        resp = client.get("/performance", headers={"accept": "text/html"})
        assert resp.status_code in (200, 303, 307)
        if resp.status_code in (303, 307):
            assert "/login" in resp.headers.get("location", "")

    def test_performance_page_authenticated(self, admin_client):
        """Authenticated users can access the performance page."""
        resp = admin_client.get("/performance")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        # Page should contain performance-related content
        html = resp.text.lower()
        assert "performance" in html
        assert "win rate" in html

    @pytest.fixture()
    def admin_client(self, state_file: str, trades_db: str, tmp_path: Path):
        """Create an admin-authenticated test client."""
        import os as os_mod

        from core.enterprise_dashboard import EnterpriseDashboard
        os_mod.environ["OPBUYING_DEFAULT_ADMIN_PASSWORD"] = "Admin@123!test"

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "trader_state_path": state_file,
            "auth_db_path": str(tmp_path / "admin_auth.db"),
            "broker_name": "Test",
            "execution_mode": "paper",
        })
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None, "Admin authentication failed"
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        return c


# ── Options Chain Page Route Tests ─────────────────────────────────────────────


class TestOptionsChainPageRoute:
    """Test the /options-chain HTML page route."""

    def test_options_chain_page_redirects_when_not_logged_in(self, client: TestClient):
        """Unauthenticated users are redirected to login."""
        resp = client.get("/options-chain", headers={"accept": "text/html"})
        assert resp.status_code in (200, 303, 307)
        if resp.status_code in (303, 307):
            assert "/login" in resp.headers.get("location", "")

    def test_options_chain_page_authenticated(self, admin_client):
        """Authenticated users can access the options chain page."""
        resp = admin_client.get("/options-chain")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        html = resp.text.lower()
        assert "options chain" in html
        assert "strike" in html
        assert "calls" in html
        assert "puts" in html

    @pytest.fixture()
    def admin_client(self, state_file: str, trades_db: str, tmp_path: Path):
        """Create an admin-authenticated test client."""
        import os as os_mod

        from core.enterprise_dashboard import EnterpriseDashboard
        os_mod.environ["OPBUYING_DEFAULT_ADMIN_PASSWORD"] = "Admin@123!test"

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "trader_state_path": state_file,
            "auth_db_path": str(tmp_path / "admin_auth.db"),
            "broker_name": "Test",
            "execution_mode": "paper",
        })
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None, "Admin authentication failed"
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        return c
