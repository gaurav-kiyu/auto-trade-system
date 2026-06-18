"""
Contract tests for the MongoDBDatabaseAdapter.

Tests mirror the SQLiteDatabaseAdapter contract tests where applicable,
mapped to MongoDB equivalents. Conditionally skipped if pymongo is
not installed or no MongoDB instance is available.

Usage:
    # Requires pymongo and a running MongoDB instance
    python -m pytest tests/test_database_mongodb_adapter.py -v
"""

from __future__ import annotations

import os
import threading
from typing import Any, Generator

import pytest

from core.adapters.database import MongoDBDatabaseAdapter
from core.adapters.database.mongodb_adapter import _parse_mongo_dsn
from core.ports.database import DatabasePort, DatabaseStats

# ── Skip condition ─────────────────────────────────────────────────────────

pymongo = pytest.importorskip("pymongo", reason="pymongo not installed")

MONGO_HOST = os.environ.get("MONGO_TEST_HOST", "")
MONGO_PORT = int(os.environ.get("MONGO_TEST_PORT", "27017"))
MONGO_DB = os.environ.get("MONGO_TEST_DATABASE", "test")
MONGO_USER = os.environ.get("MONGO_TEST_USER", "")
MONGO_PASSWORD = os.environ.get("MONGO_TEST_PASSWORD", "")

MONGO_AVAILABLE = bool(os.environ.get("MONGO_TEST_HOST"))

needs_mongo = pytest.mark.skipif(
    not MONGO_AVAILABLE,
    reason="No MongoDB instance available. Set MONGO_TEST_HOST to enable.",
)


# ═════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════


def _mongo_connect() -> DatabasePort:
    """Create and connect a MongoDB adapter."""
    kwargs: dict[str, Any] = {
        "host": MONGO_HOST,
        "port": MONGO_PORT,
        "database": MONGO_DB,
        "serverSelectionTimeoutMS": 3000,
    }
    if MONGO_USER:
        kwargs["username"] = MONGO_USER
    if MONGO_PASSWORD:
        kwargs["password"] = MONGO_PASSWORD
    adapter: DatabasePort = MongoDBDatabaseAdapter(**kwargs)
    adapter.connect()
    return adapter


@pytest.fixture
def mongo_db() -> Generator[DatabasePort, None, None]:
    """Provide a connected MongoDB adapter with clean test collection."""
    adapter = _mongo_connect()
    yield adapter
    try:
        adapter.execute("drop_collection", ("test_items",))
        adapter.execute("drop_collection", ("test_collection",))
    except Exception:
        pass
    adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# Connection lifecycle
# ═════════════════════════════════════════════════════════════════════════


@needs_mongo
class TestConnectionLifecycle:
    def test_connect_disconnect(self) -> None:
        adapter: DatabasePort = MongoDBDatabaseAdapter(
            host=MONGO_HOST, port=MONGO_PORT, database=MONGO_DB,
            serverSelectionTimeoutMS=3000,
        )
        assert not adapter.is_connected()
        assert adapter.connect() is True
        assert adapter.is_connected()
        assert adapter.connect() is False
        adapter.disconnect()
        assert not adapter.is_connected()
        adapter.disconnect()

    def test_context_manager(self) -> None:
        with MongoDBDatabaseAdapter(
            host=MONGO_HOST, port=MONGO_PORT, database=MONGO_DB,
        ) as db:
            assert db.is_connected()
            db.execute("command", ("ping",))
        assert not db.is_connected()

    def test_execute_without_connect_raises(self) -> None:
        adapter: DatabasePort = MongoDBDatabaseAdapter(
            host=MONGO_HOST, port=MONGO_PORT,
        )
        with pytest.raises(ConnectionError):
            adapter.execute("command", ("ping",))

    def test_connection_refused(self) -> None:
        adapter: DatabasePort = MongoDBDatabaseAdapter(
            host="127.0.0.1", port=1, database="test",
        )
        with pytest.raises(ConnectionError):
            adapter.connect()


# ═════════════════════════════════════════════════════════════════════════
# CRUD operations (MongoDB-adapted)
# ═════════════════════════════════════════════════════════════════════════


@needs_mongo
class TestCrud:
    def test_insert_and_find(self, mongo_db: DatabasePort) -> None:
        mongo_db.execute("insert_one", ("test_items", {"name": "alpha", "value": 10.5}))
        doc = mongo_db.fetchone("find_one", ("test_items", {"name": "alpha"}))
        assert doc is not None
        assert doc["name"] == "alpha"
        assert doc["value"] == 10.5

    def test_fetchone_no_match(self, mongo_db: DatabasePort) -> None:
        doc = mongo_db.fetchone("find_one", ("test_items", {"name": "nonexistent"}))
        assert doc is None

    def test_fetchall(self, mongo_db: DatabasePort) -> None:
        mongo_db.execute("insert_one", ("test_items", {"name": "a", "val": 1.0}))
        mongo_db.execute("insert_one", ("test_items", {"name": "b", "val": 2.0}))
        docs = mongo_db.fetchall("find", ("test_items", {}))
        assert len(docs) == 2
        names = {d["name"] for d in docs}
        assert "a" in names
        assert "b" in names

    def test_execute_many(self, mongo_db: DatabasePort) -> None:
        count = mongo_db.execute_many(
            "insert_one",
            [("test_items", {"name": "x", "val": 1.0}),
             ("test_items", {"name": "y", "val": 2.0}),
             ("test_items", {"name": "z", "val": 3.0})],
        )
        assert count == 3
        total = mongo_db.fetchone("count_documents", ("test_items", {}))
        assert total == 3

    def test_update(self, mongo_db: DatabasePort) -> None:
        mongo_db.execute("insert_one", ("test_items", {"name": "updatable", "val": 1.0}))
        mongo_db.execute("update_one", ("test_items", {"name": "updatable"}, {"$set": {"val": 99.0}}))
        doc = mongo_db.fetchone("find_one", ("test_items", {"name": "updatable"}))
        assert doc["val"] == 99.0

    def test_delete(self, mongo_db: DatabasePort) -> None:
        mongo_db.execute("insert_one", ("test_items", {"name": "deletable", "val": 1.0}))
        mongo_db.execute("delete_one", ("test_items", {"name": "deletable"}))
        doc = mongo_db.fetchone("find_one", ("test_items", {"name": "deletable"}))
        assert doc is None


# ═════════════════════════════════════════════════════════════════════════
# DDL helpers
# ═════════════════════════════════════════════════════════════════════════


@needs_mongo
class TestDdl:
    def test_table_exists(self, mongo_db: DatabasePort) -> None:
        mongo_db.execute("insert_one", ("test_collection", {"x": 1}))
        assert mongo_db.table_exists("test_collection") is True
        assert mongo_db.table_exists("nonexistent_coll_xyz") is False

    def test_create_table(self, mongo_db: DatabasePort) -> None:
        result = mongo_db.create_table("explicit_collection")
        assert result is True
        assert mongo_db.table_exists("explicit_collection") is True


# ═════════════════════════════════════════════════════════════════════════
# Health & stats
# ═════════════════════════════════════════════════════════════════════════


@needs_mongo
class TestHealthAndStats:
    def test_health_check_connected(self, mongo_db: DatabasePort) -> None:
        hc = mongo_db.health_check()
        assert hc["status"] == "healthy"
        assert hc["connected"] is True
        assert hc["backend"] == "MongoDB"
        assert "latency_ms" in hc

    def test_health_check_disconnected(self) -> None:
        adapter: DatabasePort = MongoDBDatabaseAdapter(
            host=MONGO_HOST, port=MONGO_PORT,
        )
        hc = adapter.health_check()
        assert hc["status"] == "disconnected"
        assert hc["connected"] is False

    def test_stats(self, mongo_db: DatabasePort) -> None:
        mongo_db.execute("command", ("ping",))
        stats = mongo_db.stats()
        assert isinstance(stats, DatabaseStats)
        assert stats.is_connected is True
        assert stats.queries_executed >= 1
        assert stats.backend == "MongoDB"


# ═════════════════════════════════════════════════════════════════════════
# Thread safety
# ═════════════════════════════════════════════════════════════════════════


@needs_mongo
class TestThreadSafety:
    def test_concurrent_reads(self) -> None:
        adapter = _mongo_connect()
        for i in range(100):
            adapter.execute("insert_one", ("test_items", {"idx": i, "val": f"v_{i}"}))

        results: list[dict] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def reader() -> None:
            try:
                docs = adapter.fetchall("find", ("test_items", {}))
                with lock:
                    results.extend(docs)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)

        assert len(errors) == 0, f"Concurrent read errors: {errors}"
        assert len(results) >= 100, f"Expected >=100 docs, got {len(results)}"
        adapter.execute("drop_collection", ("test_items",))
        adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# DSN parsing
# ═════════════════════════════════════════════════════════════════════════


class TestDsnParsing:
    """Unit tests for MongoDB DSN parsing (no MongoDB connection needed)."""

    def test_full_dsn(self) -> None:
        params = _parse_mongo_dsn("mongodb://user:pass@host1:27017/mydb")
        assert "host1" in params.get("host", "")
        assert params.get("database") == "mydb"

    def test_dsn_no_database(self) -> None:
        params = _parse_mongo_dsn("mongodb://localhost:27017")
        assert "localhost" in params.get("host", "")
        assert params.get("database") is None

    def test_dsn_simple_host(self) -> None:
        params = _parse_mongo_dsn("localhost")
        assert params.get("host") == "localhost"
