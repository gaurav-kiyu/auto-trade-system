"""Tests for core/cqrs/command_bus.py — CQRS Command Bus.

Covers:
- Command creation and validation
- Handler registration (explicit + decorator)
- Middleware pipeline (short-circuit, error handling)
- Command execution (success, error, no handler)
- Statistics tracking
- Thread safety (clear_all)
"""

from __future__ import annotations

from core.cqrs.command_bus import Command, CommandBus, CommandResult, MiddlewareContext

# ── Test Commands ────────────────────────────────────────────────────────────


class PlaceTradeCommand(Command):
    schema = {"symbol": str, "qty": int, "side": str}


class NoSchemaCommand(Command):
    schema = {}


class ExecuteStrategyCommand(Command):
    schema = {"strategy_name": str, "params": dict}


# ── Tests ────────────────────────────────────────────────────────────────────


class TestCommand:
    """Tests for Command base class."""

    def test_command_creation(self):
        """Command should accept kwargs and set them as attributes."""
        cmd = PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY")
        assert cmd.symbol == "NIFTY"
        assert cmd.qty == 50
        assert cmd.side == "BUY"

    def test_to_dict(self):
        """to_dict should return non-private attributes."""
        cmd = PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY")
        d = cmd.to_dict()
        assert d["symbol"] == "NIFTY"
        assert d["qty"] == 50
        assert d["side"] == "BUY"


class TestCommandBusRegistration:
    """Tests for handler registration."""

    def test_register_handler(self):
        """Explicit handler registration should work."""
        bus = CommandBus()

        def handler(cmd):
            return f"Executed {cmd.symbol}"

        bus.register_handler(PlaceTradeCommand, handler)
        stats = bus.get_stats()
        assert stats["registered_handlers"] == 1
        assert "PlaceTradeCommand" in stats["handler_names"]

    def test_decorator_registration(self):
        """Decorator-based handler registration should work."""
        bus = CommandBus()

        @bus.handler(PlaceTradeCommand)
        def handle_trade(cmd):
            return f"Trade: {cmd.symbol}"

        stats = bus.get_stats()
        assert stats["registered_handlers"] == 1

    def test_unregister_handler(self):
        """Unregister should remove handler and return True."""
        bus = CommandBus()
        bus.register_handler(PlaceTradeCommand, lambda c: None)
        assert bus.unregister_handler(PlaceTradeCommand) is True
        stats = bus.get_stats()
        assert stats["registered_handlers"] == 0

    def test_unregister_missing_handler(self):
        """Unregister missing handler should return False."""
        bus = CommandBus()
        assert bus.unregister_handler(PlaceTradeCommand) is False


class TestCommandBusExecution:
    """Tests for command execution."""

    def test_execute_success(self):
        """Successful command execution should return data."""
        bus = CommandBus()
        bus.register_handler(PlaceTradeCommand, lambda c: {"order_id": "ORD-001"})

        result = bus.execute(PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY"))
        assert result.success is True
        assert result.data["order_id"] == "ORD-001"
        assert "PlaceTradeCommand" in result.command_type

    def test_execute_no_handler(self):
        """Command with no handler should return error."""
        bus = CommandBus()
        result = bus.execute(PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY"))
        assert result.success is False
        assert "No handler" in result.error

    def test_execute_handler_error(self):
        """Handler exception should be caught."""
        bus = CommandBus()

        def failing_handler(cmd):
            raise ValueError("Insufficient margin")

        bus.register_handler(PlaceTradeCommand, failing_handler)
        result = bus.execute(PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY"))
        assert result.success is False
        assert "Insufficient margin" in result.error

    def test_execute_duration_recorded(self):
        """Duration should be recorded in CommandResult."""
        bus = CommandBus()
        bus.register_handler(PlaceTradeCommand, lambda c: "done")
        result = bus.execute(PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY"))
        assert result.duration_ms >= 0


class TestCommandBusValidation:
    """Tests for command validation against schema."""

    def test_validation_passes(self):
        """Valid command should pass validation."""
        bus = CommandBus()
        bus.register_handler(PlaceTradeCommand, lambda c: "ok")
        result = bus.execute(PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY"))
        assert result.success is True

    def test_validation_no_schema_passes(self):
        """Command with empty schema should skip validation."""
        bus = CommandBus()
        bus.register_handler(NoSchemaCommand, lambda c: "ok")
        result = bus.execute(NoSchemaCommand())
        assert result.success is True  # Empty schema = no validation needed

    def test_validation_type_mismatch(self):
        """Command with wrong type should fail validation."""
        bus = CommandBus()
        result = bus.execute(PlaceTradeCommand(symbol="NIFTY", qty="fifty", side="BUY"))
        assert result.success is False

    def test_no_schema_skips_validation(self):
        """Command without schema should skip validation."""
        bus = CommandBus()
        bus.register_handler(NoSchemaCommand, lambda c: "ok")
        result = bus.execute(NoSchemaCommand())
        assert result.success is True


class TestCommandBusMiddleware:
    """Tests for middleware pipeline."""

    def test_middleware_passes_through(self):
        """Middleware that returns None should pass through to handler."""
        bus = CommandBus()

        def pass_through(ctx, b):
            return None  # Let next middleware/handler run

        bus.use(pass_through)
        bus.register_handler(PlaceTradeCommand, lambda c: "handled")
        result = bus.execute(PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY"))
        assert result.success is True
        assert result.data == "handled"

    def test_middleware_short_circuits(self):
        """Middleware that returns CommandResult should short-circuit."""
        bus = CommandBus()

        def auth_check(ctx, b):
            return CommandResult(success=False, error="Unauthorized")

        bus.use(auth_check)
        bus.register_handler(PlaceTradeCommand, lambda c: "should not reach")
        result = bus.execute(PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY"))
        assert result.success is False
        assert "Unauthorized" in result.error

    def test_middleware_error_handled(self):
        """Middleware exception should be caught and return error."""
        bus = CommandBus()

        def broken_mw(ctx, b):
            raise RuntimeError("Middleware crashed")

        bus.use(broken_mw)
        result = bus.execute(PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY"))
        assert result.success is False
        assert "Middleware" in result.error

    def test_multiple_middleware_order(self):
        """Multiple middleware should execute in registration order."""
        bus = CommandBus()
        order = []

        def mw1(ctx, b):
            order.append("mw1")
            return None

        def mw2(ctx, b):
            order.append("mw2")
            return None

        bus.use(mw1)
        bus.use(mw2)
        bus.register_handler(PlaceTradeCommand, lambda c: order.append("handler"))
        bus.execute(PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY"))
        assert order == ["mw1", "mw2", "handler"]

    def test_middleware_cancels_command(self):
        """Middleware can cancel a command via context."""
        bus = CommandBus()

        def cancelling_mw(ctx, b):
            ctx.cancelled = True
            ctx.cancel_reason = "Risk check failed"
            return None

        bus.use(cancelling_mw)
        result = bus.execute(PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY"))
        assert result.success is False
        assert "Risk check failed" in result.error


class TestCommandBusStats:
    """Tests for statistics tracking."""

    def test_stats_empty(self):
        """Empty bus should have zero counts."""
        bus = CommandBus()
        stats = bus.get_stats()
        assert stats["total_executed"] == 0
        assert stats["total_errors"] == 0
        assert stats["registered_handlers"] == 0

    def test_stats_after_execution(self):
        """Stats should track executed and errored commands."""
        bus = CommandBus()
        bus.register_handler(PlaceTradeCommand, lambda c: "ok")
        bus.execute(PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY"))
        bus.execute(PlaceTradeCommand(symbol="BANKNIFTY", qty=25, side="SELL"))
        stats = bus.get_stats()
        assert stats["total_executed"] == 2
        assert stats["total_errors"] == 0

    def test_stats_tracks_errors(self):
        """Stats should track failed commands."""
        bus = CommandBus()
        bus.execute(PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY"))  # No handler
        stats = bus.get_stats()
        assert stats["total_executed"] >= 1
        assert stats["total_errors"] >= 1


class TestCommandBusEdgeCases:
    """Tests for edge cases."""

    def test_clear_all(self):
        """Clear should reset all state."""
        bus = CommandBus()
        bus.register_handler(PlaceTradeCommand, lambda c: None)
        bus.use(lambda ctx, b: None)
        bus.execute(PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY"))

        bus.clear_all()
        stats = bus.get_stats()
        assert stats["total_executed"] == 0
        assert stats["total_errors"] == 0
        assert stats["registered_handlers"] == 0
        assert stats["middleware_count"] == 0

    def test_multiple_handler_registration(self):
        """Multiple handlers can be registered for different commands."""
        bus = CommandBus()
        bus.register_handler(PlaceTradeCommand, lambda c: "trade")
        bus.register_handler(ExecuteStrategyCommand, lambda c: "strategy")
        stats = bus.get_stats()
        assert stats["registered_handlers"] == 2

    def test_middleware_context_attributes(self):
        """MiddlewareContext should carry command and type info."""
        cmd = PlaceTradeCommand(symbol="NIFTY", qty=50, side="BUY")
        ctx = MiddlewareContext(command=cmd, command_type="PlaceTradeCommand")
        assert ctx.command.symbol == "NIFTY"
        assert ctx.command_type == "PlaceTradeCommand"
        assert ctx.cancelled is False
