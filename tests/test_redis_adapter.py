"""Tests for core/adapters/database/redis_adapter.py - Redis Database Adapter.

Covers:
- _parse_redis_dsn (various formats)
- RedisDatabaseAdapter init (DSN, kwargs)
- connect/disconnect/is_connected/reconnect
- execute/execute_many/fetchone/fetchall
- begin/commit/rollback
- table_exists/create_table
- health_check/stats
- Error handling (ImportError, ConnectionError)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import sys
from core.adapters.database.redis_adapter import (
    RedisDatabaseAdapter,
    _parse_redis_dsn,
)

# =============================================================================
# _parse_redis_dsn Tests
# =============================================================================

class TestParseRedisDSN:
    def test_standard_url(self):
        params = _parse_redis_dsn("redis://user:pass@host1:6380/1")
        assert params["host"] == "host1"
        assert params["port"] == 6380
        assert params["db"] == 1
        assert params["username"] == "user"
        assert params["password"] == "pass"

    def test_url_without_auth(self):
        params = _parse_redis_dsn("redis://host:6379/0")
        assert params["host"] == "host"
        assert params["port"] == 6379
        assert params["db"] == 0

    def test_traditional_format(self):
        params = _parse_redis_dsn("host:6379:0:password")
        assert params["host"] == "host"
        assert params["port"] == 6379
        assert params["db"] == 0
        assert params["password"] == "password"

    def test_traditional_format_without_db(self):
        params = _parse_redis_dsn("host:6379")
        assert params["host"] == "host"
        assert params["port"] == 6379

    def test_simple_hostname(self):
        params = _parse_redis_dsn("localhost")
        assert params["host"] == "localhost"
        assert params["port"] == 6379

    def test_traditional_format_without_password(self):
        params = _parse_redis_dsn("host:6379:0")
        assert params["host"] == "host"
        assert params["port"] == 6379
        assert params["db"] == 0

    def test_url_with_query_params(self):
        params = _parse_redis_dsn("redis://host:6379/0?ssl=true")
        assert params["host"] == "host"
        assert params["port"] == 6379
        assert params["db"] == 0


# =============================================================================
# RedisDatabaseAdapter Init Tests
# =============================================================================

class TestInit:
    def test_with_dsn(self):
        adapter = RedisDatabaseAdapter(dsn="localhost:6379")
        assert adapter._conn_params["host"] == "localhost"
        assert adapter._conn_params["port"] == 6379

    def test_with_kwargs(self):
        adapter = RedisDatabaseAdapter(host="myhost", port=6380, db=2)
        assert adapter._conn_params["host"] == "myhost"
        assert adapter._conn_params["port"] == 6380
        assert adapter._conn_params["db"] == 2

    def test_kwargs_override_dsn(self):
        adapter = RedisDatabaseAdapter(dsn="redis://host:6379/0", host="customhost")
        assert adapter._conn_params["host"] == "customhost"

    def test_decode_responses_default(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        assert adapter._conn_params.get("decode_responses") is True

    def test_no_params(self):
        """No params should leave _conn_params empty."""
        adapter = RedisDatabaseAdapter()
        assert adapter._conn_params == {"decode_responses": True}


# =============================================================================
# Connection Lifecycle (mocked)
# =============================================================================

@pytest.fixture
def mock_redis():
    """Patch the redis module so we don't need a real Redis server."""
    with patch.dict("sys.modules", {"redis": MagicMock()}):
        import redis
        redis_module_mock = MagicMock()
        redis.StrictRedis = MagicMock(return_value=MagicMock())
        sys.modules["redis"] = redis_module_mock
        # We need a better approach - let's use patch directly
        yield


@pytest.fixture
def adapter():
    """RedisDatabaseAdapter with no DSN (will fail connect unless mocked)."""
    return RedisDatabaseAdapter(host="localhost", port=6379, db=0)


class TestConnect:
    def test_fails_without_params(self):
        adapter = RedisDatabaseAdapter()
        with pytest.raises(ConnectionError):
            adapter.connect()

    def test_returns_false_if_already_connected(self, adapter):
        adapter._client = MagicMock()
        assert adapter.connect() is False

    def test_import_error_raised(self, adapter):
        """When redis is not installed, ImportError should bubble up."""
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "redis":
                raise ImportError("No module named redis")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(ImportError, match="redis is required"):
                adapter.connect()


# =============================================================================
# Operation Tests (mocked)
# =============================================================================

class TestExecute:
    def test_raises_when_not_connected(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        with pytest.raises(ConnectionError, match="Redis not connected"):
            adapter.execute("PING")

    def test_tracks_queries(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        client.execute_command.return_value = "PONG"
        adapter._client = client
        result = adapter.execute("PING")
        assert result == "PONG"
        assert adapter._queries == 1

    def test_tracks_errors(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        client.execute_command.side_effect = RuntimeError("Failed")
        adapter._client = client
        with pytest.raises(RuntimeError):
            adapter.execute("PING")
        assert adapter._errors == 1
        assert "Failed" in adapter._last_error


class TestExecuteMany:
    def test_executes_multi_with_pipeline(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        pipe = MagicMock()
        pipe.execute.return_value = ["OK", "OK"]
        client.pipeline.return_value = pipe
        adapter._client = client

        result = adapter.execute_many("SET", [("k1", "v1"), ("k2", "v2")])
        assert result == 2
        assert adapter._queries == 2

    def test_tracks_errors(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        pipe = MagicMock()
        pipe.execute.side_effect = RuntimeError("Pipeline failed")
        client.pipeline.return_value = pipe
        adapter._client = client

        with pytest.raises(RuntimeError):
            adapter.execute_many("SET", [("k1", "v1")])
        assert adapter._errors == 1


class TestFetchOne:
    def test_returns_result(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        client.execute_command.return_value = "value1"
        adapter._client = client
        result = adapter.fetchone("GET", ("key1",))
        assert result == "value1"

    def test_returns_none_on_error(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        client.execute_command.side_effect = RuntimeError("Failed")
        adapter._client = client
        result = adapter.fetchone("GET", ("key1",))
        assert result is None


class TestFetchAll:
    def test_returns_list(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        client.execute_command.return_value = ["k1", "k2", "k3"]
        adapter._client = client
        result = adapter.fetchall("KEYS", ("*",))
        assert result == ["k1", "k2", "k3"]

    def test_returns_empty_on_none(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        client.execute_command.return_value = None
        adapter._client = client
        result = adapter.fetchall("KEYS", ("*",))
        assert result == []

    def test_wraps_scalar_in_list(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        client.execute_command.return_value = "single"
        adapter._client = client
        result = adapter.fetchall("GET", ("key",))
        assert result == ["single"]

    def test_returns_empty_on_error(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        client.execute_command.side_effect = RuntimeError("Failed")
        adapter._client = client
        result = adapter.fetchall("KEYS", ("*",))
        assert result == []


# =============================================================================
# Transaction Tests
# =============================================================================

class TestTransactions:
    def test_begin_calls_multi(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        adapter._client = client
        adapter.begin()
        client.execute_command.assert_called_with("MULTI")

    def test_commit_calls_exec(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        adapter._client = client
        adapter.commit()
        client.execute_command.assert_called_with("EXEC")

    def test_rollback_calls_discard(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        adapter._client = client
        adapter.rollback()
        client.execute_command.assert_called_with("DISCARD")

    def test_rollback_handles_error(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        client.execute_command.side_effect = RuntimeError("No transaction")
        adapter._client = client
        # Should not raise
        adapter.rollback()
        assert True


# =============================================================================
# DDL Helper Tests
# =============================================================================

class TestDDL:
    def test_table_exists_returns_true(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        client.execute_command.return_value = 1
        adapter._client = client
        assert adapter.table_exists("mykey") is True

    def test_table_exists_returns_false(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        client.execute_command.return_value = 0
        adapter._client = client
        assert adapter.table_exists("nonexistent") is False

    def test_table_exists_error_returns_false(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        client.execute_command.side_effect = RuntimeError("Error")
        adapter._client = client
        assert adapter.table_exists("key") is False

    def test_create_table_always_true(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        assert adapter.create_table("irrelevant") is True


# =============================================================================
# Health Check Tests
# =============================================================================

class TestHealthCheck:
    def test_healthy_when_connected(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        client = MagicMock()
        client.ping.return_value = True
        client.execute_command.side_effect = ["PONG", {"redis_version": "7.0.0"}]
        adapter._client = client
        result = adapter.health_check()
        assert result["status"] == "healthy"
        assert result["backend"] == "Redis"

    def test_disconnected_when_not_connected(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        result = adapter.health_check()
        assert result["status"] == "disconnected"

    def test_unhealthy_on_error(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        with patch.object(adapter, "is_connected", side_effect=RuntimeError("Failed")):
            result = adapter.health_check()
            assert result["status"] == "unhealthy"


# =============================================================================
# Stats Tests
# =============================================================================

class TestStats:
    def test_returns_stats(self):
        adapter = RedisDatabaseAdapter(host="redis1", port=6379, db=0)
        client = MagicMock()
        adapter._client = client
        adapter._queries = 10
        adapter._errors = 1
        stats = adapter.stats()
        assert stats.backend == "Redis"
        assert stats.queries_executed == 10
        assert stats.errors == 1

    def test_not_connected_stats(self):
        adapter = RedisDatabaseAdapter()
        stats = adapter.stats()
        assert stats.is_connected is False


# =============================================================================
# _parse_redis_version Tests
# =============================================================================

class TestParseRedisVersion:
    def test_from_dict(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        version = adapter._parse_redis_version({"redis_version": "7.0.0"})
        assert version == "7.0.0"

    def test_from_string(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        info = "redis_version:6.2.6\nos:Linux\n"
        version = adapter._parse_redis_version(info)
        assert version == "6.2.6"

    def test_from_string_not_found(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        version = adapter._parse_redis_version("some other info")
        assert version is None

    def test_unknown_type(self):
        adapter = RedisDatabaseAdapter(host="localhost")
        version = adapter._parse_redis_version(42)
        assert version is None
