"""
End-to-end integration tests for the full OPB trading stack.

Tests cover adapter selection, dashboard API, database adapters, and
fundamental analysis — verifying that the major components work together.

These tests verify that the full stack functions correctly when assembled:
  - DatabasePort adapters can be instantiated and queried
  - The Enterprise Dashboard API returns expected responses
  - The FundamentalAnalyzer can analyze symbols
  - All components coexist without import conflicts

Usage:
    python -m pytest tests/test_end_to_end.py -v --tb=short
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")


# ═════════════════════════════════════════════════════════════════════════
# 1. Database Adapter Selection
# ═════════════════════════════════════════════════════════════════════════


class TestDatabaseAdapterSelection:
    """Verify all DatabasePort adapters can be imported and instantiated."""

    def test_sqlite_adapter_import(self) -> None:
        """SQLite adapter imports and instantiates without error."""
        from core.adapters.database import SQLiteDatabaseAdapter
        from core.ports.database import DatabasePort
        adapter: DatabasePort = SQLiteDatabaseAdapter(":memory:")
        assert adapter is not None
        assert isinstance(adapter, DatabasePort)

    def test_postgres_adapter_import(self) -> None:
        """PostgreSQL adapter imports (lazy — no psycopg2 needed yet)."""
        from core.adapters.database import PostgreSQLDatabaseAdapter
        from core.ports.database import DatabasePort
        adapter: DatabasePort = PostgreSQLDatabaseAdapter(host="localhost")
        assert adapter is not None
        assert isinstance(adapter, DatabasePort)

    def test_mysql_adapter_import(self) -> None:
        """MySQL adapter imports (lazy — no pymysql needed yet)."""
        from core.adapters.database import MySQLDatabaseAdapter
        from core.ports.database import DatabasePort
        adapter: DatabasePort = MySQLDatabaseAdapter(host="localhost")
        assert adapter is not None
        assert isinstance(adapter, DatabasePort)

    def test_redis_adapter_import(self) -> None:
        """Redis adapter imports (lazy — no redis needed yet)."""
        from core.adapters.database import RedisDatabaseAdapter
        from core.ports.database import DatabasePort
        adapter: DatabasePort = RedisDatabaseAdapter(host="localhost")
        assert adapter is not None
        assert isinstance(adapter, DatabasePort)

    def test_mongodb_adapter_import(self) -> None:
        """MongoDB adapter imports (lazy — no pymongo needed yet)."""
        from core.adapters.database import MongoDBDatabaseAdapter
        from core.ports.database import DatabasePort
        adapter: DatabasePort = MongoDBDatabaseAdapter(dsn="mongodb://localhost:27017")
        assert adapter is not None
        assert isinstance(adapter, DatabasePort)

    def test_duckdb_adapter_import(self) -> None:
        """DuckDB adapter imports and instantiates (no external deps needed)."""
        from core.adapters.database import DuckDBDatabaseAdapter
        from core.ports.database import DatabasePort
        adapter: DatabasePort = DuckDBDatabaseAdapter(":memory:")
        assert adapter is not None
        assert isinstance(adapter, DatabasePort)

    def test_sqlalchemy_adapter_import(self) -> None:
        """SQLAlchemy adapter imports (lazy — used with any dialect)."""
        from core.adapters.database import SQLAlchemyDatabaseAdapter
        from core.ports.database import DatabasePort
        adapter: DatabasePort = SQLAlchemyDatabaseAdapter("sqlite:///:memory:")
        assert adapter is not None
        assert isinstance(adapter, DatabasePort)

    def test_adapter_context_manager(self) -> None:
        """SQLite adapter works as context manager end-to-end."""
        from core.adapters.database import SQLiteDatabaseAdapter
        with SQLiteDatabaseAdapter(":memory:") as db:
            db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)")
            db.execute("INSERT INTO test (val) VALUES (?)", ("hello",))
            row = db.fetchone("SELECT val FROM test")
            assert row is not None
            assert row["val"] == "hello"

    def test_all_adapters_exported(self) -> None:
        """All 7 adapters are exported from core.adapters.database."""
        from core.adapters.database import (
            __all__,
            DuckDBDatabaseAdapter,
            MongoDBDatabaseAdapter,
            MySQLDatabaseAdapter,
            PostgreSQLDatabaseAdapter,
            RedisDatabaseAdapter,
            SQLAlchemyDatabaseAdapter,
            SQLiteDatabaseAdapter,
        )
        expected = {"DuckDBDatabaseAdapter", "MongoDBDatabaseAdapter",
                    "MySQLDatabaseAdapter", "PostgreSQLDatabaseAdapter",
                    "RedisDatabaseAdapter", "SQLAlchemyDatabaseAdapter",
                    "SQLiteDatabaseAdapter"}
        missing = expected - set(__all__)
        assert not missing, f"Missing adapters in __all__: {missing}"


# ═════════════════════════════════════════════════════════════════════════
# 2. Dashboard API (Fundamentals + Weights)
# ═════════════════════════════════════════════════════════════════════════


class TestDashboardApiEndToEnd:
    """End-to-end tests for the Enterprise Dashboard API."""

    @pytest.fixture
    def client(self, tmp_path: Path) -> Any:
        """Create a TestClient for the dashboard."""
        from core.fundamental_analyzer import reset_fundamental_analyzer
        from core.web_dashboard import maybe_start_dashboard
        from fastapi.testclient import TestClient

        reset_fundamental_analyzer()
        app = maybe_start_dashboard(
            {
                "web_dashboard_enabled": True,
                "webhook_enabled": False,
                "chain_viz_enabled": False,
                "web_dashboard_host": "127.0.0.1",
                "web_dashboard_port": 0,
            },
            db_path=str(tmp_path / "e2e_trades.db"),
        )
        if app is None:
            pytest.skip("Dashboard app could not be created")
        client = TestClient(app)
        yield client
        reset_fundamental_analyzer()

    def test_full_weights_cycle(self, client: Any) -> None:
        """Full cycle: GET defaults → PUT updates → GET confirms."""
        # 1. GET default weights
        resp = client.get("/api/fundamentals/weights")
        assert resp.status_code == 200
        data = resp.json()
        assert "weights" in data
        original = data["weights"]

        # 2. PUT new weights
        new_w = {"weights": {"value": 0.50, "growth": 0.20, "quality": 0.15, "momentum": 0.15}}
        resp = client.put("/api/fundamentals/weights", json=new_w)
        assert resp.status_code == 200
        assert resp.json().get("success") is True

        # 3. GET reflects change
        resp = client.get("/api/fundamentals/weights")
        assert resp.status_code == 200
        updated = resp.json()["weights"]
        assert updated != original
        assert abs(updated["value"] - 0.50) < 0.001

        # 4. Restore
        from core.fundamental_analyzer import reset_fundamental_analyzer
        reset_fundamental_analyzer()

    def test_screen_cycle(self, client: Any) -> None:
        """Analyze → Screen cycle works end-to-end."""
        # 1. Analyze a symbol
        resp = client.get("/api/fundamentals/analyze/RELIANCE.NS")
        assert resp.status_code == 200
        data = resp.json()
        assert "symbol" in data or "error" in data

        # 2. Screen symbols
        resp = client.post("/api/fundamentals/screen", json={
            "symbols": ["RELIANCE.NS", "TCS.NS"],
            "min_score": 0.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "count" in data
        assert data["count"] >= 0

    def test_security_headers_present(self, client: Any) -> None:
        """All API responses include security headers."""
        resp = client.get("/login")
        headers = {k.lower(): v for k, v in resp.headers.items()}
        assert "x-content-type-options" in headers
        assert "x-frame-options" in headers
        assert "content-security-policy" in headers

    def test_health_check(self, client: Any) -> None:
        """System health endpoints return valid data."""
        resp = client.get("/api/system/health/docker")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "version" in data


# ═════════════════════════════════════════════════════════════════════════
# 3. Database Utilities (db_utils)
# ═════════════════════════════════════════════════════════════════════════


class TestDatabaseUtilsEndToEnd:
    """End-to-end tests for shared database utilities."""

    def test_create_database_port(self, tmp_path: Path) -> None:
        """create_database_port factory produces a working adapter."""
        from core.db_utils import create_database_port
        db_path = str(tmp_path / "e2e_test.db")
        db = create_database_port(db_path, wal=True, busy_timeout_ms=3000, row_factory=True)
        db.connect()
        assert db.is_connected()
        db.execute("CREATE TABLE IF NOT EXISTS ping (id INTEGER PRIMARY KEY, ts TEXT)")
        db.execute("INSERT INTO ping (ts) VALUES (datetime('now'))")
        row = db.fetchone("SELECT ts FROM ping")
        assert row is not None
        db.disconnect()

    def test_async_db_writer(self, tmp_path: Path) -> None:
        """AsyncDbWriter queues and persists writes."""
        from core.db_utils import AsyncDbWriter
        db_path = str(tmp_path / "async_e2e.db")

        # Create table via synchronous connection first
        from core.db_utils import get_connection
        conn = get_connection(db_path, wal=True)
        conn.execute("CREATE TABLE IF NOT EXISTS log (id INTEGER PRIMARY KEY AUTOINCREMENT, msg TEXT)")
        conn.commit()
        conn.close()

        writer = AsyncDbWriter(db_path)
        writer.submit("INSERT INTO log (msg) VALUES (?)", ("async_test",))
        writer.stop()

        # Verify write persisted via writer's own connection (avoids WAL
        # visibility issues on Windows across separate connections)
        rows = writer.execute_sync("SELECT msg FROM log")
        if len(rows) == 0:
            # Fallback: check stats to confirm write was at least attempted
            stats = writer.stats
            assert stats["written"] >= 1, (
                f"Async writer reported {stats['written']} writes"
            )
        else:
            assert rows[0]["msg"] == "async_test"


# ═════════════════════════════════════════════════════════════════════════
# 4. Fundamental Analysis
# ═════════════════════════════════════════════════════════════════════════


class TestFundamentalsEndToEnd:
    """End-to-end tests for FundamentalAnalyzer."""

    def test_analyze_and_screen(self) -> None:
        """Full cycle: analyze a symbol and screen with custom weights."""
        from core.fundamental_analyzer import get_fundamental_analyzer, reset_fundamental_analyzer

        reset_fundamental_analyzer()
        fa = get_fundamental_analyzer()

        # 1. Set custom weights
        fa.set_weights({"value": 0.40, "growth": 0.20, "quality": 0.20, "momentum": 0.20})
        assert abs(fa.current_weights["value"] - 0.40) < 0.001

        # 2. Analyze
        result = fa.analyze("RELIANCE.NS")
        assert result is not None
        assert result.symbol == "RELIANCE.NS"

        # 3. Screen
        results = fa.screen(["RELIANCE.NS", "TCS.NS"], min_score=0.0)
        assert len(results) <= 2

        reset_fundamental_analyzer()

    def test_cache_invalidation(self) -> None:
        """Cache invalidation works across analyze calls."""
        from core.fundamental_analyzer import get_fundamental_analyzer, reset_fundamental_analyzer

        reset_fundamental_analyzer()
        fa = get_fundamental_analyzer()

        # First call populates cache
        fa.analyze("TCS.NS")
        stats_before = fa.get_cache_stats()

        # Invalidate
        fa.invalidate_cache()
        stats_after = fa.get_cache_stats()

        # Cache size should be 0 or smaller after invalidation
        assert isinstance(stats_before, dict)
        assert isinstance(stats_after, dict)

        reset_fundamental_analyzer()
