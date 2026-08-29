"""Mediator Pattern — Centralized Command/Query dispatch with middleware pipeline.

Implements the Mediator pattern from the Enterprise Architecture (Pillar 1)
vision document. Provides:

- **Command<TResult>** — Writes (mutate state). Sent to exactly one handler.
- **Query<TResult>** — Reads (no side effects). Sent to exactly one handler.
- **Event** — Notifications (fire-and-forget). Broadcast to multiple handlers.
- **CommandHandler<TCommand, TResult>** — Handles a single command type.
- **QueryHandler<TQuery, TResult>** — Handles a single query type.
- **Mediator** — Central dispatch engine with middleware pipeline.
- **Middleware** — Pipeline stages (logging, validation, timing, retry, auth).
- **EventBus integration** — Commands/Queries can publish domain events.

Usage:
    from core.patterns.mediator import (
        Command, Query, CommandHandler, QueryHandler,
        Mediator, MediatorConfig, LoggingMiddleware, TimingMiddleware,
        get_mediator,
    )

    # Define a command
    class PlaceOrder(Command):
        symbol: str
        quantity: int
        is_buy: bool

    # Define a handler
    class PlaceOrderHandler(CommandHandler[PlaceOrder, str]):
        async def handle(self, command: PlaceOrder) -> str:
            return f"Order placed: {command.symbol}"

    # Register and dispatch
    mediator = Mediator()
    mediator.register_handler(PlaceOrder, PlaceOrderHandler())
    result = await mediator.send(PlaceOrder(symbol="NIFTY", quantity=50, is_buy=True))
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

_log = logging.getLogger(__name__)

# ── Type Variables ──────────────────────────────────────────────────────────

TCommand = TypeVar("TCommand")
TQuery = TypeVar("TQuery")
TEvent = TypeVar("TEvent")
TResult = TypeVar("TResult")


# ── Result Wrapper ──────────────────────────────────────────────────────────


@dataclass
class Result(Generic[TResult]):
    """Wraps a command/query result with success/failure and metadata."""

    success: bool
    value: TResult | None = None
    error: str | None = None
    command_type: str = ""
    handler_name: str = ""
    duration_ms: float = 0.0
    correlation_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "value": str(self.value) if self.value is not None else None,
            "error": self.error,
            "command_type": self.command_type,
            "handler_name": self.handler_name,
            "duration_ms": round(self.duration_ms, 2),
            "correlation_id": self.correlation_id,
        }


# ── Base Command / Query / Event Classes ───────────────────────────────────


class Command(Generic[TResult]):
    """A command represents an intent to change state.

    Commands are named with a verb in the imperative (e.g., PlaceOrder,
    CancelTrade, UpdateConfig). They carry all data needed to perform
    the operation.

    A command is sent to EXACTLY ONE handler.

    Subclass fields can be passed as keyword arguments to ```__init__()```:
        cmd = PlaceOrder(symbol="NIFTY", quantity=50)
    Or use ```@dataclass``` on the subclass for proper type checking.
    """

    def __init__(self, **kwargs: Any) -> None:
        # Auto-generated fields
        self.command_id: str = kwargs.pop("command_id", f"cmd_{uuid.uuid4().hex[:12]}")
        self.correlation_id: str = kwargs.pop("correlation_id", f"corr_{uuid.uuid4().hex[:12]}")
        self.timestamp: float = kwargs.pop("timestamp", time.time())
        # Subclass fields passed as kwargs
        for k, v in kwargs.items():
            setattr(self, k, v)


class Query(Generic[TResult]):
    """A query represents a request for data without side effects.

    Queries are named with a noun (e.g., GetTradeHistory, OpenPositions,
    SystemHealth). They must NOT mutate any state.

    A query is sent to EXACTLY ONE handler.

    Subclass fields can be passed as keyword arguments to ```__init__()```:
        qry = GetTradeHistory(symbol="NIFTY", limit=10)
    """

    def __init__(self, **kwargs: Any) -> None:
        self.query_id: str = kwargs.pop("query_id", f"qry_{uuid.uuid4().hex[:12]}")
        self.correlation_id: str = kwargs.pop("correlation_id", f"corr_{uuid.uuid4().hex[:12]}")
        self.timestamp: float = kwargs.pop("timestamp", time.time())
        for k, v in kwargs.items():
            setattr(self, k, v)


class Event:
    """An event represents something that has already happened.

    Events are named in the past tense (e.g., OrderPlaced, TradeExecuted,
    RiskBreachDetected). They carry data about what happened.

    Unlike Commands, Events are broadcast to ALL registered handlers.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.event_id: str = kwargs.pop("event_id", f"evt_{uuid.uuid4().hex[:12]}")
        self.correlation_id: str = kwargs.pop("correlation_id", "")
        self.timestamp: float = kwargs.pop("timestamp", time.time())
        self.source_command: str = kwargs.pop("source_command", "")
        for k, v in kwargs.items():
            setattr(self, k, v)


# ── Handler Base Classes ───────────────────────────────────────────────────


class CommandHandler(ABC, Generic[TCommand, TResult]):
    """Handles a specific command type.

    Subclass and implement handle() for each command type.
    """

    @abstractmethod
    async def handle(self, command: TCommand) -> TResult:
        """Execute the command and return a result."""
        ...

    @property
    def name(self) -> str:
        return type(self).__name__


class QueryHandler(ABC, Generic[TQuery, TResult]):
    """Handles a specific query type.

    Subclass and implement handle() for each query type.
    """

    @abstractmethod
    async def handle(self, query: TQuery) -> TResult:
        """Execute the query and return data."""
        ...

    @property
    def name(self) -> str:
        return type(self).__name__


class EventHandler(ABC, Generic[TEvent]):
    """Handles a specific event type.

    Multiple handlers can subscribe to the same event type.
    """

    @abstractmethod
    async def handle(self, event: TEvent) -> None:
        """Process the event."""
        ...

    @property
    def name(self) -> str:
        return type(self).__name__


# ── Middleware ──────────────────────────────────────────────────────────────


class Middleware(ABC):
    """Middleware pipeline stage.

    Middleware wraps around command/query execution to add cross-cutting
    concerns like logging, validation, timing, retry, and authorization.
    """

    @abstractmethod
    async def invoke(
        self,
        message: Any,
        next_middleware: Any,
        context: dict[str, Any],
    ) -> Any:
        """Invoke the middleware.

        Args:
            message: The command or query being dispatched.
            next_middleware: The next middleware in the pipeline.
            context: Shared context dict (can be mutated by middleware).

        Returns:
            The result from the next middleware or handler.
        """
        ...


# ── Concrete Middleware ────────────────────────────────────────────────────


class LoggingMiddleware(Middleware):
    """Logs all commands/queries with timing info."""

    async def invoke(
        self,
        message: Any,
        next_middleware: Any,
        context: dict[str, Any],
    ) -> Any:
        msg_type = type(message).__name__
        corr_id = getattr(message, "correlation_id", "")
        _log.info("[MEDIATOR] %s (%s) started [corr=%s]", msg_type, type(message).__module__, corr_id[:12])

        t0 = time.time()
        try:
            result = await next_middleware.invoke(message, next_middleware, context)
            duration = (time.time() - t0) * 1000
            _log.info(
                "[MEDIATOR] %s completed in %.1fms [corr=%s]",
                msg_type, duration, corr_id[:12],
            )
            return result
        except Exception as exc:
            duration = (time.time() - t0) * 1000
            _log.error(
                "[MEDIATOR] %s failed in %.1fms: %s [corr=%s]",
                msg_type, duration, exc, corr_id[:12],
            )
            raise


class TimingMiddleware(Middleware):
    """Records execution timing in the context."""

    async def invoke(
        self,
        message: Any,
        next_middleware: Any,
        context: dict[str, Any],
    ) -> Any:
        t0 = time.time()
        try:
            result = await next_middleware.invoke(message, next_middleware, context)
            context["duration_ms"] = (time.time() - t0) * 1000
            return result
        except Exception:
            context["duration_ms"] = (time.time() - t0) * 1000
            raise


class ValidationMiddleware(Middleware):
    """Validates commands/queries before dispatch.

    Checks for required attributes (non-None values) on the message.
    Commands/Queries can implement _validate() for custom validation.
    """

    async def invoke(
        self,
        message: Any,
        next_middleware: Any,
        context: dict[str, Any],
    ) -> Any:
        # Basic validation: check for None required fields
        if hasattr(message, "__dataclass_fields__"):
            for field_name, field_def in message.__dataclass_fields__.items():
                value = getattr(message, field_name, None)
                # Check if field is required (no default value)
                if (
                    value is None
                    and field_def.default is field_def.default_factory  # no default
                    and not field_name.endswith("_id")  # auto-generated IDs are OK
                    and field_name != "timestamp"
                ):
                    raise ValueError(
                        f"Validation failed for {type(message).__name__}: "
                        f"field '{field_name}' is required but None"
                    )

        # Custom validation via _validate() method (optional)
        if hasattr(message, "_validate") and callable(getattr(message, "_validate", None)):
            message._validate()

        return await next_middleware.invoke(message, next_middleware, context)


class RetryMiddleware(Middleware):
    """Retries failed commands with exponential backoff.

    Configurable max retries and base delay.
    Only retries on transient errors (ConnectionError, TimeoutError).
    """

    def __init__(self, max_retries: int = 3, base_delay_ms: float = 100.0) -> None:
        self._max_retries = max_retries
        self._base_delay_ms = base_delay_ms

    async def invoke(
        self,
        message: Any,
        next_middleware: Any,
        context: dict[str, Any],
    ) -> Any:
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                return await next_middleware.invoke(message, next_middleware, context)
            except (ConnectionError, TimeoutError, OSError) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    delay = self._base_delay_ms * (2 ** attempt) / 1000.0
                    msg_type = type(message).__name__
                    _log.warning(
                        "[MEDIATOR] %s attempt %d/%d failed, retrying in %.1fs: %s",
                        msg_type, attempt + 1, self._max_retries + 1, delay, exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
            except Exception:
                # Non-retryable errors propagate immediately
                raise

        # Should not reach here, but handle defensively
        if last_exc:
            raise last_exc
        return None


class AuthMiddleware(Middleware):
    """Authorization middleware for commands/queries.

    Checks if the user/role in context has permission to execute
    the command/query. Commands can define required_roles.
    """

    def __init__(self, role_permissions: dict[str, list[str]] | None = None) -> None:
        self._role_permissions = role_permissions or {}

    async def invoke(
        self,
        message: Any,
        next_middleware: Any,
        context: dict[str, Any],
    ) -> Any:
        user_role = context.get("user_role", "viewer")
        msg_type = type(message).__name__

        # Check if this message type has role restrictions
        required_roles = getattr(message, "required_roles", None)
        if required_roles and user_role not in required_roles:
            raise PermissionError(
                f"Authorization denied for {msg_type}: "
                f"requires {required_roles}, got '{user_role}'"
            )

        # Check role permissions map
        allowed = self._role_permissions.get(user_role, [])
        if allowed and msg_type not in allowed:
            if not any(msg_type.startswith(a) for a in allowed):
                raise PermissionError(
                    f"Authorization denied for {msg_type}: "
                    f"role '{user_role}' not permitted"
                )

        return await next_middleware.invoke(message, next_middleware, context)


# ── Mediator ────────────────────────────────────────────────────────────────


@dataclass
class MediatorConfig:
    """Configuration for the Mediator."""

    enable_logging: bool = True
    enable_timing: bool = True
    enable_validation: bool = True
    enable_retry: bool = False
    enable_auth: bool = False
    publish_events: bool = True
    max_retries: int = 3
    retry_base_delay_ms: float = 100.0


class Mediator:
    """Central command/query dispatch engine with middleware pipeline.

    The Mediator:
    - Routes commands to their registered handlers
    - Routes queries to their registered handlers
    - Broadcasts events to all registered handlers
    - Runs a middleware pipeline for cross-cutting concerns
    - Publishes domain events to the EventBus when configured
    - Provides a Result wrapper for consistent success/failure handling

    Thread-safe. Singleton via get_mediator().
    """

    def __init__(self, config: MediatorConfig | None = None) -> None:
        self._config = config or MediatorConfig()
        self._lock = threading.RLock()

        # Handler registries
        self._command_handlers: dict[type, CommandHandler] = {}
        self._query_handlers: dict[type, QueryHandler] = {}
        self._event_handlers: dict[type, list[EventHandler]] = {}

        # Middleware pipeline (built from config)
        self._middleware: list[Middleware] = []
        self._build_middleware()

        # Event bus integration (lazy-initialized)
        self._event_bus: Any = None

        # Statistics
        self._dispatch_count: int = 0
        self._error_count: int = 0

        _log.info(
            "[MEDIATOR] Initialized with %d middleware stages",
            len(self._middleware),
        )

    def _build_middleware(self) -> None:
        """Build the middleware pipeline from config."""
        if self._config.enable_auth:
            self._middleware.append(AuthMiddleware())
        if self._config.enable_validation:
            self._middleware.append(ValidationMiddleware())
        if self._config.enable_logging:
            self._middleware.append(LoggingMiddleware())
        if self._config.enable_timing:
            self._middleware.append(TimingMiddleware())
        if self._config.enable_retry:
            self._middleware.append(
                RetryMiddleware(
                    max_retries=self._config.max_retries,
                    base_delay_ms=self._config.retry_base_delay_ms,
                )
            )

    def add_middleware(self, middleware: Middleware) -> None:
        """Add custom middleware to the pipeline."""
        with self._lock:
            self._middleware.append(middleware)

    def get_event_bus(self) -> Any | None:
        """Lazy-initialize and return the EventBus."""
        if self._event_bus is None:
            try:
                from core.execution.event_system import get_event_bus
                self._event_bus = get_event_bus()
            except ImportError:
                _log.debug("[MEDIATOR] EventBus not available")
        return self._event_bus

    # ── Handler Registration ──────────────────────────────────────────────

    def register_handler(
        self,
        message_type: type,
        handler: CommandHandler | QueryHandler,
    ) -> None:
        """Register a handler for a command or query type.

        Args:
            message_type: The Command or Query class to handle.
            handler: Handler instance.

        Raises:
            ValueError: If handler type is unknown.
        """
        with self._lock:
            if isinstance(handler, CommandHandler):
                self._command_handlers[message_type] = handler
                _log.info(
                    "[MEDIATOR] Registered %s for command %s",
                    handler.name, message_type.__name__,
                )
            elif isinstance(handler, QueryHandler):
                self._query_handlers[message_type] = handler
                _log.info(
                    "[MEDIATOR] Registered %s for query %s",
                    handler.name, message_type.__name__,
                )
            else:
                raise ValueError(
                    f"Unknown handler type: {type(handler).__name__}. "
                    "Must be CommandHandler or QueryHandler."
                )

    def register_event_handler(
        self, event_type: type, handler: EventHandler
    ) -> None:
        """Register a handler for an event type.

        Multiple handlers can be registered for the same event type.

        Args:
            event_type: The Event class to handle.
            handler: EventHandler instance.
        """
        with self._lock:
            if event_type not in self._event_handlers:
                self._event_handlers[event_type] = []
            self._event_handlers[event_type].append(handler)
            _log.info(
                "[MEDIATOR] Registered %s for event %s",
                handler.name, event_type.__name__,
            )

    # ── Dispatch ──────────────────────────────────────────────────────────

    async def send(self, command: Command[TResult], **context_kwargs: Any) -> Result[TResult]:
        """Send a command to its registered handler through the middleware pipeline.

        Args:
            command: The command to execute.
            **context_kwargs: Additional context values passed to the middleware pipeline
                           (e.g., user_role="admin" for auth middleware).

        Returns:
            Result containing the handler's return value or error.
        """
        with self._lock:
            self._dispatch_count += 1

        command_type = type(command)
        handler = self._command_handlers.get(command_type)

        if handler is None:
            self._error_count += 1
            return Result(
                success=False,
                error=f"No handler registered for command '{command_type.__name__}'",
                command_type=command_type.__name__,
                handler_name="none",
                correlation_id=command.correlation_id,
            )

        context: dict[str, Any] = {
            "command_type": command_type.__name__,
            "correlation_id": command.correlation_id,
            "duration_ms": 0.0,
            **context_kwargs,
        }

        t0 = time.time()
        try:
            # Execute through middleware pipeline, then to handler
            result_value = await self._execute_pipeline(command, handler, context)

            duration = (time.time() - t0) * 1000
            result = Result(
                success=True,
                value=result_value,
                command_type=command_type.__name__,
                handler_name=handler.name,
                duration_ms=duration,
                correlation_id=command.correlation_id,
            )

            # Publish domain events if configured
            if self._config.publish_events:
                await self._publish_command_events(command, result)

            return result

        except Exception as exc:
            duration = (time.time() - t0) * 1000
            self._error_count += 1
            return Result(
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                command_type=command_type.__name__,
                handler_name=handler.name,
                duration_ms=duration,
                correlation_id=command.correlation_id,
            )

    async def query(self, query: Query[TResult], **context_kwargs: Any) -> Result[TResult]:
        """Send a query to its registered handler through the middleware pipeline.

        Args:
            query: The query to execute.
            **context_kwargs: Additional context values passed to the middleware pipeline
                           (e.g., user_role="admin" for auth middleware).

        Returns:
            Result containing the handler's return value or error.
        """
        with self._lock:
            self._dispatch_count += 1

        query_type = type(query)
        handler = self._query_handlers.get(query_type)

        if handler is None:
            self._error_count += 1
            return Result(
                success=False,
                error=f"No handler registered for query '{query_type.__name__}'",
                command_type=query_type.__name__,
                handler_name="none",
                correlation_id=query.correlation_id,
            )

        context: dict[str, Any] = {
            "query_type": query_type.__name__,
            "correlation_id": query.correlation_id,
            "duration_ms": 0.0,
            **context_kwargs,
        }

        t0 = time.time()
        try:
            result_value = await self._execute_pipeline(query, handler, context)
            duration = (time.time() - t0) * 1000

            return Result(
                success=True,
                value=result_value,
                command_type=query_type.__name__,
                handler_name=handler.name,
                duration_ms=duration,
                correlation_id=query.correlation_id,
            )
        except Exception as exc:
            duration = (time.time() - t0) * 1000
            self._error_count += 1
            return Result(
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                command_type=query_type.__name__,
                handler_name=handler.name,
                duration_ms=duration,
                correlation_id=query.correlation_id,
            )

    async def publish(self, event: Event) -> None:
        """Publish an event to all registered handlers.

        Args:
            event: The event to publish.
        """
        event_type = type(event)
        handlers = self._event_handlers.get(event_type, []).copy()

        if not handlers:
            _log.debug("[MEDIATOR] No handlers for event %s", event_type.__name__)
            return

        for handler in handlers:
            try:
                await handler.handle(event)
            except Exception as exc:
                _log.error(
                    "[MEDIATOR] Event handler %s failed for %s: %s",
                    handler.name, event_type.__name__, exc,
                )

    # ── Internal ──────────────────────────────────────────────────────────

    class _PipelineLink:
        """Bridges the middleware chain with proper .invoke() method.

        Middleware implementations expect ``next_middleware`` to be a
        Middleware-like object with an ``.invoke(message, next_middleware, context)``
        method. This class wraps the next pipeline step so the chain works
        correctly without requiring closures to have .invoke().
        """

        def __init__(self, middleware: Middleware, next_link: Any) -> None:
            self._middleware = middleware
            self._next = next_link

        async def invoke(self, message: Any, _next: Any, context: dict[str, Any]) -> Any:
            return await self._middleware.invoke(message, self._next, context)

    class _HandlerLink:
        """Terminal link in the middleware chain — calls the actual handler."""

        def __init__(self, handler: Any) -> None:
            self._handler = handler

        async def invoke(self, message: Any, _next: Any, context: dict[str, Any]) -> Any:
            return await self._handler.handle(message)

    async def _execute_pipeline(
        self,
        message: Any,
        handler: CommandHandler | QueryHandler,
        context: dict[str, Any],
    ) -> Any:
        """Execute the middleware pipeline and then the handler.

        Builds a chain: middleware[0] -> middleware[1] -> ... -> handler.
        Each link in the chain exposes .invoke() so middleware implementations
        can properly call ``next_middleware.invoke(message, next_middleware, context)``.
        """
        if not self._middleware:
            return await handler.handle(message)

        # Build chain: start with handler at the end, wrap with middlewares
        current: Any = self._HandlerLink(handler)
        for mw in reversed(self._middleware):
            current = self._PipelineLink(mw, current)

        return await current.invoke(message, None, context)

    async def _publish_command_events(
        self, command: Command, result: Result
    ) -> None:
        """Publish domain events to the EventBus after command execution."""
        if not result.success:
            return

        # Publish to EventBus for persistent event sourcing
        event_bus = self.get_event_bus()
        if event_bus is not None:
            try:
                # Create a domain event from the command result
                from core.execution.event_system import EventType, TradingEvent

                domain_event = TradingEvent(
                    event_type=EventType.STRATEGY_UPDATED,
                    source="mediator",
                    correlation_id=command.correlation_id,
                    metadata={
                        "command": type(command).__name__,
                        "result": str(result.value),
                        "duration_ms": result.duration_ms,
                    },
                )
                event_bus.publish(domain_event)
            except (ImportError, ValueError, TypeError, AttributeError) as exc:
                _log.debug("[MEDIATOR] EventBus publish skipped: %s", exc)

    # ── Statistics ────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get mediator dispatch statistics."""
        with self._lock:
            return {
                "total_dispatches": self._dispatch_count,
                "total_errors": self._error_count,
                "registered_commands": len(self._command_handlers),
                "registered_queries": len(self._query_handlers),
                "registered_event_handlers": sum(
                    len(v) for v in self._event_handlers.values()
                ),
                "middleware_count": len(self._middleware),
                "config": {
                    "enable_logging": self._config.enable_logging,
                    "enable_timing": self._config.enable_timing,
                    "enable_validation": self._config.enable_validation,
                    "enable_retry": self._config.enable_retry,
                    "publish_events": self._config.publish_events,
                },
            }


# ── Singleton ──────────────────────────────────────────────────────────────

_mediator: Mediator | None = None
_mediator_lock = threading.RLock()


def get_mediator(config: MediatorConfig | None = None) -> Mediator:
    """Get the singleton Mediator instance.

    Args:
        config: Optional config. Only used on first call.

    Returns:
        Shared Mediator instance.
    """
    global _mediator
    with _mediator_lock:
        if _mediator is None:
            _mediator = Mediator(config=config)
        return _mediator


def reset_mediator() -> None:
    """Force-reset singleton (for testing)."""
    global _mediator
    with _mediator_lock:
        _mediator = None


__all__ = [
    "AuthMiddleware",
    "Command",
    "CommandHandler",
    "Event",
    "EventHandler",
    "LoggingMiddleware",
    "Mediator",
    "MediatorConfig",
    "Middleware",
    "Query",
    "QueryHandler",
    "Result",
    "RetryMiddleware",
    "TimingMiddleware",
    "ValidationMiddleware",
    "get_mediator",
    "reset_mediator",
]
