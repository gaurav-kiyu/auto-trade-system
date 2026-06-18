"""
Contract tests for the RedisDatabaseAdapter.

Tests mirror the SQLiteDatabaseAdapter contract tests where applicable,
mapped to Redis equivalents. They are conditionally skipped if redis-py is
not installed or no Redis instance is available.

Usage:
    # Requires redis-py and a running Redis instance
    python -m pytest tests/test_database_redis_adapter.py -v

    # Skip Redis-dependent tests:
    python -m pytest tests/test_database_redis_adapter.py -v -k "not redis"
"""

from __future__ import annotations

import os
import threading
from typing import Any, Generator

import pytest

from core.adapters.database import RedisDatabaseAdapter
from core.adapters.database.redis_adapter import _parse_redis_dsn
from core.ports.database import DatabasePort, DatabaseStats

# ── Skip condition ─────────────────────────────────────────────────────────

redis_module = pytest.importorskip("redis", reason="redis not installed")

# Check if a Redis instance is available (via env vars or defaults)
REDIS_HOST = os.environ.get("REDIS_TEST_HOST", "")
REDIS_PORT = int(os.environ.get("REDIS_TEST_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_TEST_DB", "0"))
REDIS_PASSWORD = os.environ.get("REDIS_TEST_PASSWORD", "")

REDIS_AVAILABLE = bool(os.environ.get("REDIS_TEST_HOST"))

needs_redis = pytest.mark.skipif(
    not REDIS_AVAILABLE,
    reason="No Redis instance available. Set REDIS_TEST_HOST to enable.",
)


# ═════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════


def _redis_connect() -> DatabasePort:
    """Create and connect a Redis adapter using env vars or defaults."""
    adapter: DatabasePort = RedisDatabaseAdapter(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        socket_connect_timeout=3,
        decode_responses=True,
    )
    adapter.connect()
    return adapter


@pytest.fixture
def redis_db() -> Generator[DatabasePort, None, None]:
    """Provide a connected Redis adapter with a clean DB state."""
    adapter = _redis_connect()
    # Clear all keys for test isolation
    adapter.execute("FLUSHDB")
    yield adapter
    try:
        adapter.execute("FLUSHDB")
    except Exception:
        pass
    adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# Connection lifecycle
# ═════════════════════════════════════════════════════════════════════════


@needs_redis
class TestConnectionLifecycle:
    def test_connect_disconnect(self) -> None:
        adapter: DatabasePort = RedisDatabaseAdapter(
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
            password=REDIS_PASSWORD, socket_connect_timeout=3,
        )
        assert not adapter.is_connected()
        assert adapter.connect() is True
        assert adapter.is_connected()
        assert adapter.connect() is False  # already connected
        adapter.disconnect()
        assert not adapter.is_connected()
        adapter.disconnect()  # safe to call twice

    def test_reconnect(self) -> None:
        adapter = _redis_connect()
        adapter.execute("SET", ("test_key", "hello"))
        assert adapter.reconnect() is True
        assert adapter.is_connected()
        # Key should still exist (persisted on Redis server)
        val = adapter.fetchone("GET", ("test_key",))
        assert val == "hello"
        adapter.disconnect()

    def test_context_manager(self) -> None:
        with RedisDatabaseAdapter(
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
            password=REDIS_PASSWORD, socket_connect_timeout=3,
        ) as db:
            assert db.is_connected()
            db.execute("PING")
        assert not db.is_connected()

    def test_execute_without_connect_raises(self) -> None:
        adapter: DatabasePort = RedisDatabaseAdapter(
            host=REDIS_HOST, port=REDIS_PORT,
        )
        with pytest.raises(ConnectionError):
            adapter.execute("PING")

    def test_dsn_string(self) -> None:
        """Connect using a DSN string instead of keyword args."""
        dsn = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
        adapter: DatabasePort = RedisDatabaseAdapter(dsn=dsn, socket_connect_timeout=3)
        adapter.connect()
        assert adapter.is_connected()
        adapter.execute("PING")
        adapter.disconnect()

    def test_connection_refused(self) -> None:
        """Connecting to a non-existent host raises ConnectionError."""
        adapter: DatabasePort = RedisDatabaseAdapter(
            host="127.0.0.1", port=1, db=0, socket_connect_timeout=2,
        )
        with pytest.raises(ConnectionError):
            adapter.connect()


# ═════════════════════════════════════════════════════════════════════════
# CRUD operations (Redis-adapted — key-value semantics)
# ═════════════════════════════════════════════════════════════════════════


@needs_redis
class TestCrud:
    def test_set_and_get(self, redis_db: DatabasePort) -> None:
        redis_db.execute("SET", ("alpha", "10.5"))
        val = redis_db.fetchone("GET", ("alpha",))
        assert val == "10.5"

    def test_fetchone_no_match(self, redis_db: DatabasePort) -> None:
        val = redis_db.fetchone("GET", ("nonexistent_key_xyz",))
        assert val is None

    def test_fetchall_keys(self, redis_db: DatabasePort) -> None:
        redis_db.execute("SET", ("k1", "v1"))
        redis_db.execute("SET", ("k2", "v2"))
        keys = redis_db.fetchall("KEYS", ("*",))
        assert len(keys) == 2
        assert "k1" in keys
        assert "k2" in keys

    def test_execute_many(self, redis_db: DatabasePort) -> None:
        count = redis_db.execute_many(
            "SET",
            [("x", "1.0"), ("y", "2.0"), ("z", "3.0")],
        )
        assert count == 3
        assert redis_db.fetchone("GET", ("x",)) == "1.0"
        assert redis_db.fetchone("GET", ("y",)) == "2.0"
        assert redis_db.fetchone("GET", ("z",)) == "3.0"

    def test_del_key(self, redis_db: DatabasePort) -> None:
        redis_db.execute("SET", ("temp", "value"))
        assert redis_db.fetchone("GET", ("temp",)) == "value"
        redis_db.execute("DEL", ("temp",))
        assert redis_db.fetchone("GET", ("temp",)) is None

    def test_list_operations(self, redis_db: DatabasePort) -> None:
        redis_db.execute("LPUSH", ("mylist", "a"))
        redis_db.execute("LPUSH", ("mylist", "b"))
        redis_db.execute("LPUSH", ("mylist", "c"))
        vals = redis_db.fetchall("LRANGE", ("mylist", 0, -1))
        assert len(vals) == 3
        assert "a" in vals


# ═════════════════════════════════════════════════════════════════════════
# Transactions (Redis MULTI/EXEC/DISCARD)
# ═════════════════════════════════════════════════════════════════════════


@needs_redis
class TestTransactions:
    def test_multi_exec(self, redis_db: DatabasePort) -> None:
        redis_db.begin()  # MULTI
        redis_db.execute("SET", ("txn_key", "committed"))
        redis_db.commit()  # EXEC
        val = redis_db.fetchone("GET", ("txn_key",))
        assert val == "committed"

    def test_multi_discard(self, redis_db: DatabasePort) -> None:
        redis_db.begin()  # MULTI
        redis_db.execute("SET", ("rollback_key", "should_not_exist"))
        redis_db.rollback()  # DISCARD
        val = redis_db.fetchone("GET", ("rollback_key",))
        assert val is None


# ═════════════════════════════════════════════════════════════════════════
# DDL helpers (Redis-adapted)
# ═════════════════════════════════════════════════════════════════════════


@needs_redis
class TestDdl:
    def test_table_exists(self, redis_db: DatabasePort) -> None:
        redis_db.execute("SET", ("existing_key", "val"))
        assert redis_db.table_exists("existing_key") is True
        assert redis_db.table_exists("nonexistent_key") is False

    def test_create_table(self, redis_db: DatabasePort) -> None:
        # Redis has no DDL — create_table is a no-op
        result = redis_db.create_table("noop")
        assert result is True


# ═════════════════════════════════════════════════════════════════════════
# Health & stats
# ═════════════════════════════════════════════════════════════════════════


@needs_redis
class TestHealthAndStats:
    def test_health_check_connected(self, redis_db: DatabasePort) -> None:
        hc = redis_db.health_check()
        assert hc["status"] == "healthy"
        assert hc["connected"] is True
        assert hc["backend"] == "Redis"
        assert "latency_ms" in hc

    def test_health_check_disconnected(self) -> None:
        adapter: DatabasePort = RedisDatabaseAdapter(
            host=REDIS_HOST, port=REDIS_PORT,
        )
        hc = adapter.health_check()
        assert hc["status"] == "disconnected"
        assert hc["connected"] is False

    def test_stats(self, redis_db: DatabasePort) -> None:
        redis_db.execute("PING")
        stats = redis_db.stats()
        assert isinstance(stats, DatabaseStats)
        assert stats.is_connected is True
        assert stats.queries_executed >= 1
        assert stats.backend == "Redis"

    def test_health_check_after_error(self, redis_db: DatabasePort) -> None:
        with pytest.raises(Exception):
            redis_db.execute("INVALID_COMMAND")
        hc = redis_db.health_check()
        assert hc["status"] in ("healthy", "unhealthy")


# ═════════════════════════════════════════════════════════════════════════
# Thread safety
# ═════════════════════════════════════════════════════════════════════════


@needs_redis
class TestThreadSafety:
    def test_concurrent_reads(self) -> None:
        adapter = _redis_connect()
        # Populate 100 keys
        for i in range(100):
            adapter.execute("SET", (f"conc:{i}", f"val_{i}"))
        adapter.execute("SET", ("conc:done", "1"))

        results: list[str] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def reader() -> None:
            try:
                keys = adapter.fetchall("KEYS", ("conc:*",))
                with lock:
                    results.extend(keys)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)

        assert len(errors) == 0, f"Concurrent read errors: {errors}"
        # Each thread gets ~100+ keys, so 4 threads × 101+ keys
        assert len(results) >= 100, f"Expected >=100 results, got {len(results)}"
        adapter.execute("FLUSHDB")
        adapter.disconnect()


# ═════════════════════════════════════════════════════════════════════════
# DSN parsing
# ═════════════════════════════════════════════════════════════════════════


class TestDsnParsing:
    """Unit tests for Redis DSN parsing (no Redis connection needed)."""

    def test_full_dsn(self) -> None:
        params = _parse_redis_dsn("redis://user:pass@host1:6379/0")
        assert params["host"] == "host1"
        assert params["port"] == 6379
        assert params["db"] == 0
        assert params["username"] == "user"
        assert params["password"] == "pass"

    def test_dsn_no_password(self) -> None:
        params = _parse_redis_dsn("redis://user@host/1")
        assert params["host"] == "host"
        assert params["username"] == "user"
        assert params["db"] == 1
        assert "password" not in params or params.get("password") is None

    def test_dsn_simple_host(self) -> None:
        params = _parse_redis_dsn("localhost")
        assert params["host"] == "localhost"
        assert params["port"] == 6379

    def test_dsn_traditional_format(self) -> None:
        params = _parse_redis_dsn("localhost:6379:0:secret")
        assert params["host"] == "localhost"
        assert params["port"] == 6379
        assert params["db"] == 0
        assert params["password"] == "secret"

    def test_dsn_url_no_prefix(self) -> None:
        params = _parse_redis_dsn("user:pass@host:6379/0")
        assert params["host"] == "host"
        assert params["username"] == "user"
        assert params["password"] == "pass"
        assert params["db"] == 0

    def test_dsn_minimal(self) -> None:
        params = _parse_redis_dsn("redis://host/2")
        assert params["host"] == "host"
        assert params["db"] == 2

    def test_dsn_no_port(self) -> None:
        params = _parse_redis_dsn("redis://host/0")
        assert params["host"] == "host"
        assert params["db"] == 0
        assert params["port"] == 6379
