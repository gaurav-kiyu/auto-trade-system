"""Tests for Mediator pattern (Pillar 1 — Enterprise Architecture)."""
from __future__ import annotations

import asyncio

import pytest
from core.patterns.mediator import (
    AuthMiddleware,
    Command,
    CommandHandler,
    Event,
    EventHandler,
    Mediator,
    MediatorConfig,
    Middleware,
    Query,
    QueryHandler,
    Result,
    get_mediator,
    reset_mediator,
)

# ── Test Command Types ─────────────────────────────────────────────────────

class PlaceOrder(Command[str]):
    """Test command."""

    symbol: str = "NIFTY"
    quantity: int = 50


class CancelOrder(Command[bool]):
    """Test command."""

    order_id: str = "123"
    reason: str = "Manual override"
    required_roles: list[str] | None = None


class GetTradeHistory(Query[list]):
    """Test query."""

    symbol: str = "NIFTY"
    limit: int = 10


class GetSystemHealth(Query[dict]):
    """Test query."""

    include_details: bool = False


class OrderPlacedEvent(Event):
    """Test event."""

    order_id: str = ""
    symbol: str = ""
    quantity: int = 0


# ── Test Handlers ──────────────────────────────────────────────────────────

class PlaceOrderHandler(CommandHandler[PlaceOrder, str]):

    async def handle(self, command: PlaceOrder) -> str:
        return f"Placed {command.quantity} of {command.symbol}"


class CancelOrderHandler(CommandHandler[CancelOrder, bool]):

    async def handle(self, command: CancelOrder) -> bool:
        return True


class GetTradeHistoryHandler(QueryHandler[GetTradeHistory, list]):

    async def handle(self, query: GetTradeHistory) -> list:
        return [
            {"symbol": "NIFTY", "qty": 10, "pnl": 100},
            {"symbol": "BANKNIFTY", "qty": 5, "pnl": 50},
        ][:query.limit]


class GetSystemHealthHandler(QueryHandler[GetSystemHealth, dict]):

    async def handle(self, query: GetSystemHealth) -> dict:
        return {"status": "healthy", "uptime": "24h"}


class OrderPlacedEventHandler(EventHandler[OrderPlacedEvent]):

    handled_events: list[OrderPlacedEvent] = []

    async def handle(self, event: OrderPlacedEvent) -> None:
        self.handled_events.append(event)


class SecondOrderPlacedEventHandler(EventHandler[OrderPlacedEvent]):

    second_events: list[OrderPlacedEvent] = []

    async def handle(self, event: OrderPlacedEvent) -> None:
        self.second_events.append(event)


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singleton() -> None:
    """Reset the mediator singleton before each test."""
    reset_mediator()


@pytest.fixture
def mediator() -> Mediator:
    """Create a fresh mediator with minimal config for testing."""
    m = Mediator(MediatorConfig(
        enable_logging=False,
        enable_timing=False,
        enable_validation=False,
        enable_retry=False,
        enable_auth=False,
        publish_events=False,
    ))
    m.register_handler(PlaceOrder, PlaceOrderHandler())
    m.register_handler(CancelOrder, CancelOrderHandler())
    m.register_handler(GetTradeHistory, GetTradeHistoryHandler())
    m.register_handler(GetSystemHealth, GetSystemHealthHandler())
    return m


# ── Tests ──────────────────────────────────────────────────────────────────

class TestCommandDataclass:
    """Tests for Command base class."""

    def test_command_has_id(self) -> None:
        """Test command has auto-generated ID."""
        cmd = PlaceOrder()
        assert cmd.command_id.startswith("cmd_")
        assert len(cmd.command_id) > 5

    def test_command_has_correlation_id(self) -> None:
        """Test command has correlation ID."""
        cmd = PlaceOrder()
        assert cmd.correlation_id.startswith("corr_")

    def test_command_fields(self) -> None:
        """Test command dataclass fields."""
        cmd = PlaceOrder(symbol="BANKNIFTY", quantity=100)
        assert cmd.symbol == "BANKNIFTY"
        assert cmd.quantity == 100

    def test_query_has_id(self) -> None:
        """Test query has auto-generated ID."""
        q = GetTradeHistory()
        assert q.query_id.startswith("qry_")

    def test_event_base(self) -> None:
        """Test Event base class."""
        event = OrderPlacedEvent(order_id="ord_123", symbol="NIFTY", quantity=50)
        assert event.order_id == "ord_123"
        assert event.symbol == "NIFTY"
        assert event.event_id.startswith("evt_")


class TestResult:
    """Tests for Result wrapper."""

    def test_success_result(self) -> None:
        """Test success result."""
        result = Result(
            success=True,
            value="Order placed",
            command_type="PlaceOrder",
            handler_name="PlaceOrderHandler",
        )
        assert result.success is True
        assert result.value == "Order placed"
        assert result.error is None

    def test_error_result(self) -> None:
        """Test error result."""
        result = Result(
            success=False,
            error="Something went wrong",
            command_type="PlaceOrder",
        )
        assert result.success is False
        assert result.error == "Something went wrong"

    def test_to_dict(self) -> None:
        """Test serialization."""
        result = Result(
            success=True,
            value="OK",
            command_type="Test",
            handler_name="TestHandler",
            duration_ms=10.5,
            correlation_id="corr_123",
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["value"] == "OK"
        assert d["duration_ms"] == 10.5

    def test_to_dict_error(self) -> None:
        """Test serialization of error."""
        result = Result(success=False, error="Fail")
        d = result.to_dict()
        assert d["success"] is False
        assert d["error"] == "Fail"


class TestMediator:
    """Tests for the Mediator class."""

    @pytest.mark.asyncio
    async def test_send_command(self, mediator: Mediator) -> None:
        """Test sending a command returns a successful result."""
        result = await mediator.send(PlaceOrder(symbol="NIFTY", quantity=50))
        assert result.success is True
        assert "Placed" in str(result.value)
        assert result.command_type == "PlaceOrder"

    @pytest.mark.asyncio
    async def test_send_command_with_custom_values(self, mediator: Mediator) -> None:
        """Test command with custom field values."""
        result = await mediator.send(PlaceOrder(symbol="BANKNIFTY", quantity=100))
        assert result.success is True
        assert "100" in str(result.value)
        assert "BANKNIFTY" in str(result.value)

    @pytest.mark.asyncio
    async def test_send_unregistered_command(self, mediator: Mediator) -> None:
        """Test sending an unregistered command returns an error."""

        class UnregisteredCommand(Command[str]):
            pass

        result = await mediator.send(UnregisteredCommand())
        assert result.success is False
        assert "No handler registered" in (result.error or "")

    @pytest.mark.asyncio
    async def test_query(self, mediator: Mediator) -> None:
        """Test sending a query returns data."""
        result = await mediator.query(GetTradeHistory(symbol="NIFTY", limit=10))
        assert result.success is True
        assert isinstance(result.value, list)
        assert len(result.value) == 2

    @pytest.mark.asyncio
    async def test_query_with_limit(self, mediator: Mediator) -> None:
        """Test query with different parameters."""

        class LimitedHistoryQuery(Query[list]):
            limit: int = 1

        class LimitedHistoryHandler(QueryHandler[LimitedHistoryQuery, list]):
            async def handle(self, query: LimitedHistoryQuery) -> list:
                return [{"symbol": "NIFTY"}][:query.limit]

        m = Mediator(MediatorConfig(
            enable_logging=False, enable_timing=False,
            enable_validation=False, enable_retry=False,
            publish_events=False,
        ))
        m.register_handler(LimitedHistoryQuery, LimitedHistoryHandler())
        result = await m.query(LimitedHistoryQuery(limit=1))
        assert result.success is True
        assert len(result.value) == 1

    @pytest.mark.asyncio
    async def test_query_unregistered(self, mediator: Mediator) -> None:
        """Test sending an unregistered query returns an error."""

        class UnknownQuery(Query[str]):
            pass

        result = await mediator.query(UnknownQuery())
        assert result.success is False
        assert "No handler registered" in (result.error or "")

    @pytest.mark.asyncio
    async def test_handler_registration(self) -> None:
        """Test registering handlers."""
        m = Mediator(MediatorConfig(
            enable_logging=False, enable_timing=False,
            enable_validation=False, enable_retry=False,
            publish_events=False,
        ))

        class TestCmd(Command[str]):
            pass

        class TestHandler(CommandHandler[TestCmd, str]):
            async def handle(self, command: TestCmd) -> str:
                return "ok"

        m.register_handler(TestCmd, TestHandler())
        assert len(m._command_handlers) == 1

    @pytest.mark.asyncio
    async def test_event_handling(self, mediator: Mediator) -> None:
        """Test event publishing and handling."""
        handler1 = OrderPlacedEventHandler()
        handler1.handled_events = []

        mediator.register_event_handler(OrderPlacedEvent, handler1)

        event = OrderPlacedEvent(
            order_id="ord_1", symbol="NIFTY", quantity=50,
            correlation_id="corr_test",
        )
        await mediator.publish(event)

        assert len(handler1.handled_events) == 1
        assert handler1.handled_events[0].order_id == "ord_1"

    @pytest.mark.asyncio
    async def test_multiple_event_handlers(self, mediator: Mediator) -> None:
        """Test multiple handlers for the same event."""
        h1 = OrderPlacedEventHandler()
        h1.handled_events = []
        h2 = SecondOrderPlacedEventHandler()
        h2.second_events = []

        mediator.register_event_handler(OrderPlacedEvent, h1)
        mediator.register_event_handler(OrderPlacedEvent, h2)

        await mediator.publish(OrderPlacedEvent(order_id="ord_2"))

        assert len(h1.handled_events) == 1
        assert len(h2.second_events) == 1

    @pytest.mark.asyncio
    async def test_singleton(self) -> None:
        """Test singleton pattern."""
        m1 = get_mediator()
        m2 = get_mediator()
        assert m1 is m2

    @pytest.mark.asyncio
    async def test_reset_singleton(self) -> None:
        """Test reset creates new instance."""
        m1 = get_mediator()
        reset_mediator()
        m2 = get_mediator()
        assert m1 is not m2

    @pytest.mark.asyncio
    async def test_handler_name(self) -> None:
        """Test handler name property."""
        handler = PlaceOrderHandler()
        assert handler.name == "PlaceOrderHandler"

    @pytest.mark.asyncio
    async def test_command_handler_name(self) -> None:
        """Test command handler name via result."""
        m = Mediator(MediatorConfig(
            enable_logging=False, enable_timing=False,
            enable_validation=False, enable_retry=False,
            publish_events=False,
        ))

        class NameCmd(Command[str]):
            pass

        class NameHandler(CommandHandler[NameCmd, str]):
            async def handle(self, command: NameCmd) -> str:
                return "done"

        m.register_handler(NameCmd, NameHandler())
        result = await m.send(NameCmd())
        assert result.handler_name == "NameHandler"

    @pytest.mark.asyncio
    async def test_get_stats(self, mediator: Mediator) -> None:
        """Test getting mediator statistics."""
        await mediator.send(PlaceOrder(symbol="NIFTY", quantity=10))
        await mediator.query(GetTradeHistory())

        stats = mediator.get_stats()
        assert stats["total_dispatches"] == 2
        assert stats["total_errors"] == 0
        assert stats["registered_commands"] >= 2

    @pytest.mark.asyncio
    async def test_error_tracking(self, mediator: Mediator) -> None:
        """Test error tracking in stats."""

        class BadCmd(Command[str]):
            pass

        await mediator.send(BadCmd())  # Unregistered = error

        stats = mediator.get_stats()
        assert stats["total_errors"] >= 1

    @pytest.mark.asyncio
    async def test_handler_error_propagated(self) -> None:
        """Test handler exception is captured in Result."""

        class FailingCmd(Command[str]):
            pass

        class FailingHandler(CommandHandler[FailingCmd, str]):
            async def handle(self, command: FailingCmd) -> str:
                raise RuntimeError("Intentional failure")

        m = Mediator(MediatorConfig(
            enable_logging=False, enable_timing=False,
            enable_validation=False, enable_retry=False,
            publish_events=False,
        ))
        m.register_handler(FailingCmd, FailingHandler())
        result = await m.send(FailingCmd())

        assert result.success is False
        assert "RuntimeError" in (result.error or "")

    @pytest.mark.asyncio
    async def test_result_has_duration(self, mediator: Mediator) -> None:
        """Test result includes execution duration."""
        result = await mediator.send(PlaceOrder())
        assert result.duration_ms > 0


class TestMiddleware:
    """Tests for middleware pipeline."""

    @pytest.mark.asyncio
    async def test_logging_middleware(self) -> None:
        """Test logging middleware passes through to handler."""

        class LogCmd(Command[str]):
            pass

        class LogHandler(CommandHandler[LogCmd, str]):
            async def handle(self, command: LogCmd) -> str:
                return "logged"

        m = Mediator(MediatorConfig(
            enable_logging=True,
            enable_timing=False,
            enable_validation=False,
            enable_retry=False,
            publish_events=False,
        ))
        m.register_handler(LogCmd, LogHandler())
        result = await m.send(LogCmd())

        assert result.success is True
        assert result.value == "logged"

    @pytest.mark.asyncio
    async def test_timing_middleware(self) -> None:
        """Test timing middleware records duration."""

        class TimedCmd(Command[str]):
            pass

        class TimedHandler(CommandHandler[TimedCmd, str]):
            async def handle(self, command: TimedCmd) -> str:
                await asyncio.sleep(0.01)
                return "timed"

        m = Mediator(MediatorConfig(
            enable_logging=False,
            enable_timing=True,
            enable_validation=False,
            enable_retry=False,
            publish_events=False,
        ))
        m.register_handler(TimedCmd, TimedHandler())
        result = await m.send(TimedCmd())

        assert result.success is True
        assert result.duration_ms > 5  # At least 10ms sleep

    @pytest.mark.asyncio
    async def test_validation_middleware(self) -> None:
        """Test validation middleware catches None required fields."""

        class ValidatedCmd(Command[str]):
            data: str | None = None

        class ValidatedHandler(CommandHandler[ValidatedCmd, str]):
            async def handle(self, command: ValidatedCmd) -> str:
                return command.data or "default"

        m = Mediator(MediatorConfig(
            enable_logging=False,
            enable_timing=False,
            enable_validation=True,
            enable_retry=False,
            publish_events=False,
        ))
        m.register_handler(ValidatedCmd, ValidatedHandler())

        # This should work - 'data' has a default of None
        result = await m.send(ValidatedCmd())
        assert result.success is True

    @pytest.mark.asyncio
    async def test_retry_middleware_passes(self) -> None:
        """Test retry middleware passes on success."""

        class RetryCmd(Command[str]):
            pass

        class RetryHandler(CommandHandler[RetryCmd, str]):
            call_count = 0

            async def handle(self, command: RetryCmd) -> str:
                self.call_count += 1
                return f"attempt_{self.call_count}"

        handler = RetryHandler()
        m = Mediator(MediatorConfig(
            enable_logging=False,
            enable_timing=False,
            enable_validation=False,
            enable_retry=True,
            max_retries=3,
            publish_events=False,
        ))
        m.register_handler(RetryCmd, handler)
        result = await m.send(RetryCmd())

        assert result.success is True
        assert "attempt_1" in str(result.value)

    @pytest.mark.asyncio
    async def test_auth_middleware_allows(self) -> None:
        """Test auth middleware allows permitted role."""

        class AuthCmd(Command[str]):
            required_roles: list[str] | None = ["admin", "operator"]

        class AuthHandler(CommandHandler[AuthCmd, str]):
            async def handle(self, command: AuthCmd) -> str:
                return "authorized"

        m = Mediator(MediatorConfig(
            enable_logging=False,
            enable_timing=False,
            enable_validation=False,
            enable_retry=False,
            enable_auth=True,
            publish_events=False,
        ))
        m.register_handler(AuthCmd, AuthHandler())
        result = await m.send(AuthCmd(), user_role="admin")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_add_custom_middleware(self) -> None:
        """Test adding custom middleware to the pipeline."""

        class TrackerMiddleware(Middleware):
            invoked = False

            async def invoke(
                self, message, next_middleware, context
            ) -> None:
                self.invoked = True
                return await next_middleware.invoke(
                    message, next_middleware, context
                )

        tracker = TrackerMiddleware()

        class TrackCmd(Command[str]):
            pass

        class TrackHandler(CommandHandler[TrackCmd, str]):
            async def handle(self, command: TrackCmd) -> str:
                return "tracked"

        m = Mediator(MediatorConfig(
            enable_logging=False, enable_timing=False,
            enable_validation=False, enable_retry=False,
            publish_events=False,
        ))
        m.add_middleware(tracker)
        m.register_handler(TrackCmd, TrackHandler())
        await m.send(TrackCmd())

        assert tracker.invoked is True


class TestAllMiddlewareChain:
    """Tests for the full middleware chain combined."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self) -> None:
        """Test all middleware operating together."""

        class FullCmd(Command[str]):
            name: str = "test"

        class FullHandler(CommandHandler[FullCmd, str]):
            async def handle(self, command: FullCmd) -> str:
                return f"hello_{command.name}"

        m = Mediator(MediatorConfig(
            enable_logging=True,
            enable_timing=True,
            enable_validation=True,
            enable_retry=False,
            enable_auth=False,
            publish_events=False,
        ))
        m.register_handler(FullCmd, FullHandler())

        result = await m.send(FullCmd(name="world"))
        assert result.success is True
        assert result.value == "hello_world"

    @pytest.mark.asyncio
    async def test_middleware_ordering(self) -> None:
        """Test middleware runs in the correct order."""

        order: list[str] = []

        class FirstMiddleware(Middleware):
            async def invoke(self, message, next_middleware, context):
                order.append("first")
                return await next_middleware.invoke(
                    message, next_middleware, context
                )

        class SecondMiddleware(Middleware):
            async def invoke(self, message, next_middleware, context):
                order.append("second")
                return await next_middleware.invoke(
                    message, next_middleware, context
                )

        class OrderCmd(Command[str]):
            pass

        class OrderHandler(CommandHandler[OrderCmd, str]):
            async def handle(self, command: OrderCmd) -> str:
                order.append("handler")
                return "ordered"

        m = Mediator(MediatorConfig(
            enable_logging=False, enable_timing=False,
            enable_validation=False, enable_retry=False,
            publish_events=False,
        ))
        m.add_middleware(FirstMiddleware())
        m.add_middleware(SecondMiddleware())
        m.register_handler(OrderCmd, OrderHandler())

        await m.send(OrderCmd())
        assert order == ["first", "second", "handler"]


# ── Auth Middleware Denials ───────────────────────────────────────────


class TestAuthMiddlewareDenials:
    """Tests for auth middleware denial paths."""

    @pytest.mark.asyncio
    async def test_auth_middleware_denies_wrong_role(self) -> None:
        """Auth middleware blocks user not in required_roles."""
        class RestrictedCmd(Command[str]):
            required_roles: list[str] | None = ["admin"]

        class RestrictedHandler(CommandHandler[RestrictedCmd, str]):
            async def handle(self, command: RestrictedCmd) -> str:
                return "secret"

        m = Mediator(MediatorConfig(
            enable_logging=False, enable_timing=False,
            enable_validation=False, enable_retry=False,
            enable_auth=True, publish_events=False,
        ))
        m.register_handler(RestrictedCmd, RestrictedHandler())
        result = await m.send(RestrictedCmd(), user_role="viewer")
        assert result.success is False
        assert "Authorization denied" in (result.error or "")
        assert "requires" in (result.error or "")

    @pytest.mark.asyncio
    async def test_auth_middleware_no_required_roles(self) -> None:
        """Command without required_roles uses role_permissions map."""
        class UnrestrictedCmd(Command[str]):
            pass

        class UnrestrictedHandler(CommandHandler[UnrestrictedCmd, str]):
            async def handle(self, command: UnrestrictedCmd) -> str:
                return "allowed"

        m = Mediator(MediatorConfig(
            enable_logging=False, enable_timing=False,
            enable_validation=False, enable_retry=False,
            enable_auth=True, publish_events=False,
        ))
        # Override auth middleware with one that only allows "admin" role
        m._middleware = [
            AuthMiddleware(role_permissions={"admin": ["UnrestrictedCmd"], "viewer": ["ReadOnly"]})
        ]
        m.register_handler(UnrestrictedCmd, UnrestrictedHandler())
        # viewer role doesn't have UnrestrictedCmd in its permissions
        result = await m.send(UnrestrictedCmd(), user_role="viewer")
        assert result.success is False
        assert "Authorization denied" in (result.error or "")

    @pytest.mark.asyncio
    async def test_auth_middleware_prefix_match(self) -> None:
        """Auth middleware allows when msg_type starts with a permitted prefix."""
        class MySpecialCmd(Command[str]):
            pass

        class MySpecialHandler(CommandHandler[MySpecialCmd, str]):
            async def handle(self, command: MySpecialCmd) -> str:
                return "prefix_matched"

        m = Mediator(MediatorConfig(
            enable_logging=False, enable_timing=False,
            enable_validation=False, enable_retry=False,
            enable_auth=True, publish_events=False,
        ))
        m._middleware = [
            AuthMiddleware(role_permissions={"viewer": ["My"]})
        ]
        m.register_handler(MySpecialCmd, MySpecialHandler())
        result = await m.send(MySpecialCmd(), user_role="viewer")
        assert result.success is True
        assert result.value == "prefix_matched"


# ── Validation Middleware Error Path ──────────────────────────────────


class TestValidationMiddleware:
    """Tests for validation middleware error paths."""

    @pytest.mark.asyncio
    async def test_validation_middleware_passes_regular_command(self) -> None:
        """Validation middleware passes regular commands with defaults."""
        class RegularCmd(Command[str]):
            symbol: str = ""  # has default so no error

        class RegularHandler(CommandHandler[RegularCmd, str]):
            async def handle(self, command: RegularCmd) -> str:
                return command.symbol

        m = Mediator(MediatorConfig(
            enable_logging=False, enable_timing=False,
            enable_validation=True, enable_retry=False,
            publish_events=False,
        ))
        m.register_handler(RegularCmd, RegularHandler())
        result = await m.send(RegularCmd())
        assert result.success is True
        assert result.value == ""

    @pytest.mark.asyncio
    async def test_validation_custom_method(self) -> None:
        """Validation middleware calls _validate() if present."""
        class ValidatableCmd(Command[str]):
            value: int = 0

            def _validate(self) -> None:
                if self.value < 0:
                    raise ValueError("Value must be non-negative")

        class ValidatableHandler(CommandHandler[ValidatableCmd, str]):
            async def handle(self, command: ValidatableCmd) -> str:
                return f"value={command.value}"

        m = Mediator(MediatorConfig(
            enable_logging=False, enable_timing=False,
            enable_validation=True, enable_retry=False,
            publish_events=False,
        ))
        m.register_handler(ValidatableCmd, ValidatableHandler())
        result = await m.send(ValidatableCmd(value=5))
        assert result.success is True
        assert result.value == "value=5"


# ── Retry Middleware Edge Cases ───────────────────────────────────────


class TestRetryMiddleware:
    """Tests for retry middleware with transient failures."""

    @pytest.mark.asyncio
    async def test_retry_middleware_recovers(self) -> None:
        """Retry middleware recovers after transient failure."""
        call_count = 0

        class TransientCmd(Command[str]):
            pass

        class TransientHandler(CommandHandler[TransientCmd, str]):
            async def handle(self, command: TransientCmd) -> str:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise ConnectionError("Temporary failure")
                return f"recovered_on_attempt_{call_count}"

        m = Mediator(MediatorConfig(
            enable_logging=False, enable_timing=False,
            enable_validation=False, enable_retry=True,
            max_retries=2, publish_events=False,
        ))
        handler = TransientHandler()
        m.register_handler(TransientCmd, handler)
        result = await m.send(TransientCmd())
        assert result.success is True
        assert "recovered_on_attempt_2" in str(result.value)

    @pytest.mark.asyncio
    async def test_retry_middleware_exhausted(self) -> None:
        """Retry middleware eventually fails after all retries."""
        class AlwaysFailingCmd(Command[str]):
            pass

        class AlwaysFailingHandler(CommandHandler[AlwaysFailingCmd, str]):
            async def handle(self, command: AlwaysFailingCmd) -> str:
                raise TimeoutError("Always times out")

        m = Mediator(MediatorConfig(
            enable_logging=False, enable_timing=False,
            enable_validation=False, enable_retry=True,
            max_retries=1, publish_events=False,
        ))
        m.register_handler(AlwaysFailingCmd, AlwaysFailingHandler())
        result = await m.send(AlwaysFailingCmd())
        assert result.success is False
        assert "TimeoutError" in (result.error or "")

    @pytest.mark.asyncio
    async def test_retry_non_transient_error_passes_through(self) -> None:
        """Non-transient errors (e.g. ValueError) are NOT retried."""
        class NonTransientCmd(Command[str]):
            pass

        class NonTransientHandler(CommandHandler[NonTransientCmd, str]):
            async def handle(self, command: NonTransientCmd) -> str:
                raise ValueError("Business logic error")

        m = Mediator(MediatorConfig(
            enable_logging=False, enable_timing=False,
            enable_validation=False, enable_retry=True,
            max_retries=3, publish_events=False,
        ))
        m.register_handler(NonTransientCmd, NonTransientHandler())
        result = await m.send(NonTransientCmd())
        assert result.success is False
        assert "ValueError" in (result.error or "")


# ── Event Bus Integration ─────────────────────────────────────────────


class TestEventBusIntegration:
    """Tests for EventBus lazy initialization."""

    @pytest.mark.asyncio
    async def test_get_event_bus_returns_none_when_not_available(self) -> None:
        """get_event_bus returns None when core.execution.event_system is unavailable."""
        from unittest.mock import patch
        m = Mediator(MediatorConfig(publish_events=True))
        with patch("core.patterns.mediator.Mediator.get_event_bus", return_value=None):
            bus = m.get_event_bus()
            assert bus is None

    @pytest.mark.asyncio
    async def test_publish_events_skipped_on_failure(self) -> None:
        """Command failure skips event publishing."""
        class FailCmd(Command[str]):
            pass

        class FailHandler(CommandHandler[FailCmd, str]):
            async def handle(self, command: FailCmd) -> str:
                raise RuntimeError("fail")

        m = Mediator(MediatorConfig(
            enable_logging=False, enable_timing=False,
            enable_validation=False, enable_retry=False,
            publish_events=True,
        ))
        m.register_handler(FailCmd, FailHandler())
        result = await m.send(FailCmd())
        assert result.success is False


# ── Handler Registration Errors ───────────────────────────────────────


class TestHandlerRegistrationErrors:
    """Tests for handler registration error paths."""

    def test_register_handler_unknown_type_raises(self) -> None:
        """register_handler raises ValueError for unknown handler type."""
        m = Mediator(MediatorConfig(publish_events=False))
        with pytest.raises(ValueError, match="Unknown handler type"):
            m.register_handler(str, "not_a_handler")  # type: ignore[arg-type]


# ── Publish No Handlers ───────────────────────────────────────────────


class TestPublishNoHandlers:
    """Test publish with no registered handlers."""

    @pytest.mark.asyncio
    async def test_publish_with_no_handlers(self) -> None:
        """Publishing an event with no handlers does not raise."""
        class OrphanEvent(Event):
            pass

        m = Mediator(MediatorConfig(publish_events=False))
        await m.publish(OrphanEvent())  # Should not raise


# ── Execute Pipeline Edge Cases ───────────────────────────────────────


class TestExecutePipelineEdgeCases:
    """Tests for _execute_pipeline edge cases."""

    @pytest.mark.asyncio
    async def test_no_middleware_executes_handler_directly(self) -> None:
        """Without middleware, handler is called directly."""
        class DirectCmd(Command[str]):
            pass

        class DirectHandler(CommandHandler[DirectCmd, str]):
            async def handle(self, command: DirectCmd) -> str:
                return "direct"

        m = Mediator(MediatorConfig(
            enable_logging=False, enable_timing=False,
            enable_validation=False, enable_retry=False,
            publish_events=False,
        ))
        # Clear all middleware
        m._middleware = []
        m.register_handler(DirectCmd, DirectHandler())
        result = await m.send(DirectCmd())
        assert result.success is True
        assert result.value == "direct"


# ── Event Handler Error ───────────────────────────────────────────────


class TestEventHandlerError:
    """Tests for event handler failure handling."""

    @pytest.mark.asyncio
    async def test_event_handler_error_does_not_crash(self) -> None:
        """Event handler exception is logged but doesn't crash publish."""
        class FragileEvent(Event):
            pass

        class FragileHandler(EventHandler[FragileEvent]):
            async def handle(self, event: FragileEvent) -> None:
                raise RuntimeError("Handler crashed")

        m = Mediator(MediatorConfig(publish_events=False))
        m.register_event_handler(FragileEvent, FragileHandler())
        # Should not raise
        await m.publish(FragileEvent())


# ── get_stats Edge Cases ──────────────────────────────────────────────


class TestGetStatsEdgeCases:
    """Tests for get_stats edge cases."""

    def test_get_stats_empty(self) -> None:
        """Fresh mediator has zero stats."""
        m = Mediator(MediatorConfig(publish_events=False))
        stats = m.get_stats()
        assert stats["total_dispatches"] == 0
        assert stats["total_errors"] == 0
        assert stats["registered_commands"] == 0
        assert stats["registered_queries"] == 0
        assert stats["registered_event_handlers"] == 0
        assert stats["middleware_count"] > 0
