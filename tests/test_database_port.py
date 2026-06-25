"""Tests for core/ports/database.py - DatabasePort interface contract.

Covers:
- DatabaseStats dataclass defaults and custom values
- DatabasePort abstract methods are all defined
- Context manager protocol (__enter__/__exit__)
- A concrete mock implementation validates all methods work
- Contract: connect/disconnect lifecycle, SQL execution, transactions, DDL
"""

from __future__ import annotations

from typing import Any


from core.ports.database import DatabasePort, DatabaseStats


# ── DatabaseStats Tests ──────────────────────────────────────────────────────


class TestDatabaseStats:
    def test_defaults(self):
        stats = DatabaseStats(db_path="test.db", is_connected=False)
        assert stats.db_path == "test.db"
        assert stats.is_connected is False
        assert stats.total_connections == 0
        assert stats.queries_executed == 0
        assert stats.errors == 0
        assert stats.last_error == ""
        assert stats.backend == "unknown"

    def test_custom_values(self):
        stats = DatabaseStats(
            db_path="prod.db",
            is_connected=True,
            total_connections=5,
            queries_executed=100,
            errors=2,
            last_error="timeout",
            backend="sqlite",
        )
        assert stats.total_connections == 5
        assert stats.queries_executed == 100
        assert stats.errors == 2
        assert stats.backend == "sqlite"

    def test_immutable_like(self):
        """Dataclass fields should be mutable."""
        stats = DatabaseStats(db_path="test.db", is_connected=False)
        stats.is_connected = True
        assert stats.is_connected is True


# ── Mock Implementation (for contract testing) ──────────────────────────────


class MockDatabasePort(DatabasePort):
    """Minimal concrete implementation of DatabasePort for testing."""

    def __init__(self):
        self._connected = False
        self._stats = DatabaseStats(db_path=":memory:", is_connected=False, backend="mock")

    def connect(self) -> bool:
        if self._connected:
            return False
        self._connected = True
        self._stats.is_connected = True
        self._stats.total_connections += 1
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._stats.is_connected = False

    def is_connected(self) -> bool:
        return self._connected

    def reconnect(self) -> bool:
        self.disconnect()
        return self.connect()

    def execute(self, sql: str, params: tuple | dict = ()) -> Any:
        self._stats.queries_executed += 1
        return True

    def execute_many(self, sql: str, params_list: list[tuple | dict]) -> int:
        self._stats.queries_executed += len(params_list)
        return len(params_list)

    def fetchone(self, sql: str, params: tuple | dict = ()) -> Any | None:
        self._stats.queries_executed += 1
        return None

    def fetchall(self, sql: str, params: tuple | dict = ()) -> list[Any]:
        self._stats.queries_executed += 1
        return []

    def begin(self) -> None:
        pass

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def table_exists(self, table_name: str) -> bool:
        return False

    def create_table(self, sql: str) -> bool:
        return True

    def health_check(self) -> dict[str, Any]:
        return {"status": "healthy", "latency_ms": 0.5}

    def stats(self) -> DatabaseStats:
        return self._stats


# ── Contract Tests (via MockDatabasePort) ────────────────────────────────────


class TestDatabasePortContract:
    def test_all_abstract_methods_exist(self):
        """The DatabasePort abstract class should define all required methods."""
        methods = [
            "connect", "disconnect", "is_connected", "reconnect",
            "execute", "execute_many", "fetchone", "fetchall",
            "begin", "commit", "rollback",
            "table_exists", "create_table",
            "health_check", "stats",
        ]
        for m in methods:
            assert hasattr(DatabasePort, m), f"Missing abstract method: {m}"


class TestMockDatabasePort:
    """Test the mock implementation to verify the contract is implementable."""

    def setup_method(self):
        self.db = MockDatabasePort()

    def test_initial_state(self):
        assert self.db.is_connected() is False

    def test_connect(self):
        assert self.db.connect() is True
        assert self.db.is_connected() is True

    def test_connect_twice_returns_false(self):
        self.db.connect()
        assert self.db.connect() is False  # Already connected

    def test_disconnect(self):
        self.db.connect()
        self.db.disconnect()
        assert self.db.is_connected() is False

    def test_disconnect_when_not_connected(self):
        self.db.disconnect()  # Should not raise

    def test_reconnect(self):
        self.db.connect()
        assert self.db.is_connected() is True
        assert self.db.reconnect() is True
        assert self.db.is_connected() is True

    def test_execute(self):
        self.db.connect()
        result = self.db.execute("SELECT 1")
        assert result is True

    def test_execute_many(self):
        self.db.connect()
        count = self.db.execute_many("INSERT INTO t VALUES (?)", [(1,), (2,)])
        assert count == 2

    def test_fetchone(self):
        self.db.connect()
        result = self.db.fetchone("SELECT 1")
        assert result is None  # Mock returns None

    def test_fetchall(self):
        self.db.connect()
        results = self.db.fetchall("SELECT 1")
        assert results == []

    def test_begin_commit_rollback(self):
        self.db.connect()
        self.db.begin()
        self.db.commit()
        self.db.begin()
        self.db.rollback()

    def test_table_exists(self):
        assert self.db.table_exists("users") is False

    def test_create_table(self):
        assert self.db.create_table("CREATE TABLE t (id INT)") is True

    def test_health_check(self):
        result = self.db.health_check()
        assert result["status"] == "healthy"

    def test_stats_tracks_queries(self):
        self.db.connect()
        self.db.execute("SELECT 1")
        self.db.execute_many("INSERT", [(1,), (2,)])
        stats = self.db.stats()
        assert stats.queries_executed >= 3

    def test_stats_tracks_connections(self):
        self.db.connect()
        stats = self.db.stats()
        assert stats.total_connections >= 1
        assert stats.is_connected is True


class TestDatabasePortContextManager:
    """Test the __enter__/__exit__ protocol."""

    def test_context_manager_connect_and_disconnect(self):
        db = MockDatabasePort()
        assert db.is_connected() is False

        with db as d:
            assert d is db
            assert db.is_connected() is True

        # After exit, should be disconnected
        assert db.is_connected() is False

    def test_context_manager_execute_inside(self):
        with MockDatabasePort() as db:
            result = db.execute("SELECT 1")
            assert result is True

    def test_context_manager_rollback_on_error(self):
        db = MockDatabasePort()
        try:
            with db:
                raise ValueError("test error")
        except ValueError:
            pass
        # After exception should still disconnect
        assert db.is_connected() is False
