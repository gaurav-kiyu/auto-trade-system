"""Tests for CQRS module (core/cqrs/)."""

from __future__ import annotations

import pytest
from core.cqrs import Command, CommandBus, Query, QueryBus


@pytest.fixture
def cmd_bus():
    bus = CommandBus()
    yield bus
    bus.clear_all()


@pytest.fixture
def qry_bus():
    bus = QueryBus()
    yield bus
    bus.clear_all()


# ── Command Bus ──────────────────────────────────────────────────────────


class TestCommandBus:
    def test_register_handler(self, cmd_bus):
        class TestCmd(Command):
            pass

        results = []

        def handler(cmd):
            results.append("executed")

        cmd_bus.register_handler(TestCmd, handler)
        cmd_bus.execute(TestCmd())
        assert len(results) == 1

    def test_decorator_handler(self, cmd_bus):
        class TestCmd(Command):
            pass

        @cmd_bus.handler(TestCmd)
        def handle(cmd):
            return "done"

        result = cmd_bus.execute(TestCmd())
        assert result.success is True
        assert result.data == "done"

    def test_no_handler(self, cmd_bus):
        class UnhandledCmd(Command):
            pass

        result = cmd_bus.execute(UnhandledCmd())
        assert result.success is False
        assert "No handler" in result.error

    def test_command_validation_passes(self, cmd_bus):
        class ValidatedCmd(Command):
            schema = {"name": str, "value": int}

        @cmd_bus.handler(ValidatedCmd)
        def handle(cmd):
            return f"{cmd.name}={cmd.value}"

        result = cmd_bus.execute(ValidatedCmd(name="test", value=42))
        assert result.success is True
        assert result.data == "test=42"

    def test_command_validation_fails(self, cmd_bus):
        class ValidatedCmd(Command):
            schema = {"name": str, "value": int}

        result = cmd_bus.execute(ValidatedCmd(name="test", value="not_int"))
        assert result.success is False

    def test_command_validation_missing_field(self, cmd_bus):
        class ValidatedCmd(Command):
            schema = {"name": str, "required_field": str}

        result = cmd_bus.execute(ValidatedCmd(name="test"))
        assert result.success is False

    def test_middleware_short_circuit(self, cmd_bus):
        class TestCmd(Command):
            pass

        def auth_mw(ctx, bus):
            # Short-circuit with error
            from core.cqrs.command_bus import CommandResult
            return CommandResult(success=False, error="Unauthorized")

        cmd_bus.use(auth_mw)
        result = cmd_bus.execute(TestCmd())
        assert result.success is False
        assert "Unauthorized" in result.error

    def test_middleware_passthrough(self, cmd_bus):
        class TestCmd(Command):
            pass

        results = []

        def logging_mw(ctx, bus):
            results.append("mw_passed")
            return None  # Continue pipeline

        @cmd_bus.handler(TestCmd)
        def handle(cmd):
            return "handled"

        cmd_bus.use(logging_mw)
        result = cmd_bus.execute(TestCmd())
        assert result.success is True
        assert result.data == "handled"
        assert len(results) == 1

    def test_unregister_handler(self, cmd_bus):
        class TestCmd(Command):
            pass

        def handler(cmd):
            return "ok"

        cmd_bus.register_handler(TestCmd, handler)
        cmd_bus.unregister_handler(TestCmd)
        result = cmd_bus.execute(TestCmd())
        assert result.success is False

    def test_get_stats(self, cmd_bus):
        stats = cmd_bus.get_stats()
        assert stats["total_executed"] == 0
        assert stats["registered_handlers"] == 0


# ── Query Bus ────────────────────────────────────────────────────────────


class TestQueryBus:
    def test_register_handler(self, qry_bus):
        class GetDataQuery(Query):
            def __init__(self, key=""):
                self.key = key

        def handler(query):
            return {"key": query.key, "value": 42}

        qry_bus.register_handler(GetDataQuery, handler)
        result = qry_bus.execute(GetDataQuery(key="test"))
        assert result.success is True
        assert result.data["value"] == 42

    def test_decorator_handler(self, qry_bus):
        class GetValueQuery(Query):
            def __init__(self, n=0):
                self.n = n

        @qry_bus.handler(GetValueQuery)
        def handle(query):
            return query.n * 2

        result = qry_bus.execute(GetValueQuery(n=5))
        assert result.success is True
        assert result.data == 10

    def test_no_handler(self, qry_bus):
        class UnhandledQuery(Query):
            pass

        result = qry_bus.execute(UnhandledQuery())
        assert result.success is False
        assert "No handler" in result.error

    def test_cache_hit(self, qry_bus):
        class CachedQuery(Query):
            def __init__(self, x=0):
                self.x = x

        call_count = [0]

        @qry_bus.handler(CachedQuery)
        def handle(query):
            call_count[0] += 1
            return query.x * 2

        # First call - cache miss
        r1 = qry_bus.execute(CachedQuery(x=5), use_cache=True, cache_ttl=60)
        assert r1.data == 10
        assert call_count[0] == 1

        # Second call - cache hit
        r2 = qry_bus.execute(CachedQuery(x=5), use_cache=True, cache_ttl=60)
        assert r2.data == 10
        assert r2.cached is True
        assert call_count[0] == 1  # Handler not called again

    def test_cache_miss_different_params(self, qry_bus):
        class DiffQuery(Query):
            def __init__(self, x=0):
                self.x = x

        call_count = [0]

        @qry_bus.handler(DiffQuery)
        def handle(query):
            call_count[0] += 1
            return query.x

        qry_bus.execute(DiffQuery(x=1), use_cache=True)
        qry_bus.execute(DiffQuery(x=2), use_cache=True)
        assert call_count[0] == 2  # Different params = different cache keys

    def test_invalidate_cache(self, qry_bus):
        class TestQuery(Query):
            def __init__(self, x=0):
                self.x = x

        @qry_bus.handler(TestQuery)
        def handle(query):
            return query.x

        qry_bus.execute(TestQuery(x=1), use_cache=True)
        assert qry_bus.invalidate_cache() >= 1
        stats = qry_bus.get_stats()
        assert stats["cache_entries"] == 0

    def test_get_stats(self, qry_bus):
        stats = qry_bus.get_stats()
        assert stats["total_queries"] == 0
        assert stats["registered_handlers"] == 0
