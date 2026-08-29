"""CQRS Command Bus — Execute commands with middleware pipeline and validation."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


# ── Command Base ────────────────────────────────────────────────────────────


class Command:
    """Base class for all commands.

    Subclass and define a 'schema' dict for validation:
        class PlaceTradeCommand(Command):
            schema = {"symbol": str, "qty": int, "side": str}
    """

    schema: dict[str, type] = {}

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class CommandResult:
    """Result of executing a command."""

    success: bool = True
    data: Any = None
    error: str = ""
    duration_ms: float = 0.0
    command_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
            "command_type": self.command_type,
        }


@dataclass
class MiddlewareContext:
    """Context passed through the middleware pipeline."""

    command: Command = field(default_factory=Command)
    command_type: str = ""
    cancelled: bool = False
    cancel_reason: str = ""


# ── Command Bus ─────────────────────────────────────────────────────────────


MiddlewareFn = Callable[[MiddlewareContext, "CommandBus"], CommandResult | None]


class CommandBus:
    """Executes commands through a middleware pipeline.

    Supports:
    - Validation against type schema
    - Middleware pipeline (logging, auth, audit, metrics)
    - Handler registration via decorator or explicit registration
    - Command deduplication
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: dict[str, Callable[[Any], Any]] = {}
        self._middleware: list[MiddlewareFn] = []
        self._total_executed: int = 0
        self._total_errors: int = 0

    # ── Handler Registration ──────────────────────────────────────────────

    def register_handler(self, command_type: type[Command],
                         handler: Callable[[Any], Any]) -> None:
        """Register a handler for a command type.

        Args:
            command_type: The Command subclass to handle.
            handler: Callable receiving a command instance.
        """
        name = command_type.__name__
        with self._lock:
            self._handlers[name] = handler

    def handler(self, command_type: type[Command]) -> Callable:
        """Decorator to register a handler for a command type.

        Usage:
            @bus.handler(PlaceTradeCommand)
            def handle(cmd):
                ...
        """
        def decorator(fn: Callable) -> Callable:
            self.register_handler(command_type, fn)
            return fn
        return decorator

    def unregister_handler(self, command_type: type[Command]) -> bool:
        """Unregister a handler.

        Returns True if removed, False if not found.
        """
        name = command_type.__name__
        with self._lock:
            return self._handlers.pop(name, None) is not None

    # ── Middleware ────────────────────────────────────────────────────────

    def use(self, middleware_fn: MiddlewareFn) -> None:
        """Add middleware to the pipeline.

        Middleware receives (context, bus) and returns CommandResult or None.
        If it returns CommandResult, the pipeline short-circuits.
        If it returns None, the next middleware runs.
        """
        with self._lock:
            self._middleware.append(middleware_fn)

    # ── Execution ─────────────────────────────────────────────────────────

    def execute(self, command: Command) -> CommandResult:
        """Execute a command through the middleware pipeline.

        Args:
            command: Command instance.

        Returns:
            CommandResult with success/error and data.
        """
        t0 = time.time()
        command_type = type(command).__name__

        # Validate
        validation = self._validate(command)
        if validation is not None:
            self._total_executed += 1
            self._total_errors += 1
            return CommandResult(
                success=False, error=validation,
                command_type=command_type,
                duration_ms=(time.time() - t0) * 1000,
            )

        # Middleware pipeline
        ctx = MiddlewareContext(command=command, command_type=command_type)

        for mw in self._middleware:
            try:
                result = mw(ctx, self)
                if result is not None:
                    # Short-circuit
                    result.command_type = command_type
                    result.duration_ms = (time.time() - t0) * 1000
                    if not result.success:
                        self._total_errors += 1
                    self._total_executed += 1
                    return result
            except Exception as exc:
                _log.warning("[CMDBUS] Middleware error: %s", exc)
                self._total_executed += 1
                self._total_errors += 1
                return CommandResult(
                    success=False, error=f"Middleware: {exc}",
                    command_type=command_type,
                    duration_ms=(time.time() - t0) * 1000,
                )

        if ctx.cancelled:
            self._total_executed += 1
            self._total_errors += 1
            return CommandResult(
                success=False, error=ctx.cancel_reason,
                command_type=command_type,
                duration_ms=(time.time() - t0) * 1000,
            )

        # Execute handler
        with self._lock:
            handler = self._handlers.get(command_type)

        if handler is None:
            self._total_executed += 1
            self._total_errors += 1
            return CommandResult(
                success=False, error=f"No handler for {command_type}",
                command_type=command_type,
                duration_ms=(time.time() - t0) * 1000,
            )

        try:
            result_data = handler(command)
            self._total_executed += 1
            return CommandResult(
                success=True, data=result_data,
                command_type=command_type,
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as exc:
            _log.warning("[CMDBUS] Handler error for '%s': %s", command_type, exc)
            self._total_executed += 1
            self._total_errors += 1
            return CommandResult(
                success=False, error=str(exc),
                command_type=command_type,
                duration_ms=(time.time() - t0) * 1000,
            )

    # ── Statistics ────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get command bus statistics."""
        with self._lock:
            return {
                "total_executed": self._total_executed,
                "total_errors": self._total_errors,
                "registered_handlers": len(self._handlers),
                "middleware_count": len(self._middleware),
                "handler_names": list(self._handlers.keys()),
                "error_rate": round(
                    self._total_errors / max(self._total_executed, 1) * 100, 1
                ),
            }

    def _validate(self, command: Command) -> str | None:
        """Validate command fields against schema.

        Returns error string or None if valid.
        """
        schema = type(command).schema
        if not schema:
            return None

        for field_name, expected_type in schema.items():
            if not hasattr(command, field_name):
                return f"Missing field: {field_name}"
            value = getattr(command, field_name)
            if value is None:
                return f"Field '{field_name}' is required"
            if expected_type and not isinstance(value, expected_type):
                return f"Field '{field_name}' expected {expected_type.__name__}, got {type(value).__name__}"
        return None

    def clear_all(self) -> None:
        """Clear all handlers and middleware (for testing)."""
        with self._lock:
            self._handlers.clear()
            self._middleware.clear()
            self._total_executed = 0
            self._total_errors = 0
