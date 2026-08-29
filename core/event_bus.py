"""Event Bus — In-Process Publish/Subscribe (Constitution v4.0 Architecture Standard).

Provides a lightweight in-process event bus for decoupled module communication.
Supports synchronous and asynchronous handlers, wildcard patterns, and event
filtering. Foundation for Event Sourcing and CQRS integration.

Architecture Standard: Event Bus
Constitution Layer: Layer 3 — Enterprise Architecture

Usage:
    from core.event_bus import get_event_bus

    bus = get_event_bus()

    # Subscribe to events
    @bus.on("trade.executed")
    def handle_trade(event):
        print(f"Trade executed: {event.data}")

    # Subscribe with wildcard
    @bus.on("trade.*")
    def handle_all_trade_events(event):
        print(f"Trade event: {event.name}")

    # Publish event
    bus.publish("trade.executed", {"symbol": "NIFTY", "qty": 50})

    # Publish async (non-blocking)
    await bus.publish_async("trade.executed", {"symbol": "NIFTY", "qty": 50})
"""

from __future__ import annotations

import fnmatch
import logging
import threading
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class Event:
    """A single event published on the bus."""

    name: str
    data: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    timestamp: float = 0.0
    event_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "data": self.data,
            "source": self.source,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
        }


@dataclass
class SubscriptionStats:
    """Statistics for a single subscription."""

    pattern: str
    handler_name: str
    is_async: bool
    invocation_count: int = 0
    error_count: int = 0
    last_invoked: float = 0.0
    avg_duration_ms: float = 0.0


HandlerFn = Callable[[Event], Any]
AsyncHandlerFn = Callable[[Event], Coroutine]


# ── Event Bus ───────────────────────────────────────────────────────────────


class EventBus:
    """In-process publish/subscribe event bus.

    Thread-safe. Supports synchronous and async handlers, wildcard patterns,
    and per-subscription statistics.

    Handler signature: handler(event: Event) -> None
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sync_handlers: list[tuple[str, HandlerFn]] = []
        self._async_handlers: list[tuple[str, AsyncHandlerFn]] = []
        self._history: list[Event] = []
        self._max_history = 1000
        self._subscription_stats: dict[str, SubscriptionStats] = {}
        self._total_published: int = 0
        self._total_errors: int = 0

    # ── Subscription ──────────────────────────────────────────────────────

    def on(self, pattern: str) -> Callable[[HandlerFn], HandlerFn]:
        """Decorator to register a synchronous event handler.

        Args:
            pattern: Event name or wildcard pattern (e.g., 'trade.executed', 'trade.*').

        Returns:
            Decorator function.
        """
        def decorator(handler: HandlerFn) -> HandlerFn:
            self.subscribe(pattern, handler)
            return handler
        return decorator

    def subscribe(self, pattern: str, handler: HandlerFn) -> bool:
        """Register a synchronous event handler.

        Args:
            pattern: Event name or wildcard pattern.
            handler: Callable accepting an Event.

        Returns:
            True if registered.
        """
        handler_name = getattr(handler, "__name__", str(handler))
        with self._lock:
            self._sync_handlers.append((pattern, handler))
            stats_key = f"{pattern}:{handler_name}"
            self._subscription_stats[stats_key] = SubscriptionStats(
                pattern=pattern,
                handler_name=handler_name,
                is_async=False,
            )
        _log.debug("[EVENT_BUS] Subscribed sync handler '%s' to '%s'", handler_name, pattern)
        return True

    def subscribe_async(self, pattern: str, handler: AsyncHandlerFn) -> bool:
        """Register an async event handler.

        Args:
            pattern: Event name or wildcard pattern.
            handler: Async callable accepting an Event.

        Returns:
            True if registered.
        """
        handler_name = getattr(handler, "__name__", str(handler))
        with self._lock:
            self._async_handlers.append((pattern, handler))
            stats_key = f"{pattern}:{handler_name}"
            self._subscription_stats[stats_key] = SubscriptionStats(
                pattern=pattern,
                handler_name=handler_name,
                is_async=True,
            )
        _log.debug("[EVENT_BUS] Subscribed async handler '%s' to '%s'", handler_name, pattern)
        return True

    def unsubscribe(self, pattern: str, handler: HandlerFn | AsyncHandlerFn) -> bool:
        """Unregister a handler from a pattern.

        Args:
            pattern: The pattern the handler was registered on.
            handler: The handler function to unregister.

        Returns:
            True if found and removed.
        """
        handler_name = getattr(handler, "__name__", str(handler))
        with self._lock:
            # Check sync handlers
            for i, (pat, h) in enumerate(self._sync_handlers):
                if pat == pattern and h == handler:
                    self._sync_handlers.pop(i)
                    stats_key = f"{pattern}:{handler_name}"
                    self._subscription_stats.pop(stats_key, None)
                    return True
            # Check async handlers
            for i, (pat, h) in enumerate(self._async_handlers):
                if pat == pattern and h == handler:
                    self._async_handlers.pop(i)
                    stats_key = f"{pattern}:{handler_name}"
                    self._subscription_stats.pop(stats_key, None)
                    return True
            return False

    # ── Publishing ────────────────────────────────────────────────────────

    def publish(self, name: str, data: dict[str, Any] | None = None,
                source: str = "") -> int:
        """Publish an event to all matching handlers (synchronous).

        Args:
            name: Event name (e.g., 'trade.executed').
            data: Optional event payload.
            source: Optional source identifier.

        Returns:
            Number of handlers that were invoked.
        """
        event = Event(
            name=name,
            data=data or {},
            source=source,
            timestamp=time.time(),
            event_id=f"evt-{int(time.time() * 1000000)}",
        )

        with self._lock:
            self._total_published += 1
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

            # Get matching handlers
            matched = [(pat, h) for pat, h in self._sync_handlers if self._matches(pat, name)]

        count = 0
        for pattern, handler in matched:
            try:
                t0 = time.time()
                handler(event)
                duration = (time.time() - t0) * 1000
                count += 1

                # Update stats
                handler_name = getattr(handler, "__name__", str(handler))
                stats_key = f"{pattern}:{handler_name}"
                with self._lock:
                    stats = self._subscription_stats.get(stats_key)
                    if stats:
                        stats.invocation_count += 1
                        stats.last_invoked = time.time()
                        if stats.avg_duration_ms == 0:
                            stats.avg_duration_ms = duration
                        else:
                            stats.avg_duration_ms = (stats.avg_duration_ms + duration) / 2
            except Exception as exc:
                _log.warning("[EVENT_BUS] Handler error for '%s': %s", name, exc)
                with self._lock:
                    self._total_errors += 1
                    handler_name = getattr(handler, "__name__", str(handler))
                    stats_key = f"{pattern}:{handler_name}"
                    stats = self._subscription_stats.get(stats_key)
                    if stats:
                        stats.error_count += 1

        _log.debug("[EVENT_BUS] Published '%s' -> %d handlers", name, count)
        return count

    async def publish_async(self, name: str, data: dict[str, Any] | None = None,
                            source: str = "") -> int:
        """Publish an event to all matching handlers (async-aware).

        Invokes sync handlers synchronously and async handlers with await.

        Args:
            name: Event name.
            data: Optional event payload.
            source: Optional source identifier.

        Returns:
            Number of handlers that were invoked.
        """
        event = Event(
            name=name,
            data=data or {},
            source=source,
            timestamp=time.time(),
            event_id=f"evt-{int(time.time() * 1000000)}",
        )

        with self._lock:
            self._total_published += 1
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

            sync_matched = [(pat, h) for pat, h in self._sync_handlers if self._matches(pat, name)]
            async_matched = [(pat, h) for pat, h in self._async_handlers if self._matches(pat, name)]

        count = 0

        # Run sync handlers
        for pattern, handler in sync_matched:
            try:
                t0 = time.time()
                handler(event)
                count += 1
                self._update_stats(pattern, handler, (time.time() - t0) * 1000)
            except Exception as exc:
                _log.warning("[EVENT_BUS] Sync handler error for '%s': %s", name, exc)
                with self._lock:
                    self._total_errors += 1

        # Run async handlers
        for pattern, handler in async_matched:
            try:
                t0 = time.time()
                await handler(event)
                count += 1
                self._update_stats(pattern, handler, (time.time() - t0) * 1000)
            except Exception as exc:
                _log.warning("[EVENT_BUS] Async handler error for '%s': %s", name, exc)
                with self._lock:
                    self._total_errors += 1

        return count

    def _update_stats(self, pattern: str, handler: Any, duration_ms: float) -> None:
        """Update handler statistics."""
        handler_name = getattr(handler, "__name__", str(handler))
        stats_key = f"{pattern}:{handler_name}"
        with self._lock:
            stats = self._subscription_stats.get(stats_key)
            if stats:
                stats.invocation_count += 1
                stats.last_invoked = time.time()
                if stats.avg_duration_ms == 0:
                    stats.avg_duration_ms = duration_ms
                else:
                    stats.avg_duration_ms = (stats.avg_duration_ms + duration_ms) / 2

    def get_history(self, name: str = "", limit: int = 50) -> list[Event]:
        """Get recent event history, optionally filtered by name."""
        with self._lock:
            events = list(self._history)
        if name:
            events = [e for e in events if self._matches(name, e.name)]
        return events[-limit:]

    def clear_history(self) -> None:
        """Clear event history."""
        with self._lock:
            self._history.clear()

    # ── Statistics ─────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get event bus statistics."""
        with self._lock:
            return {
                "total_published": self._total_published,
                "total_errors": self._total_errors,
                "sync_handlers": len(self._sync_handlers),
                "async_handlers": len(self._async_handlers),
                "history_size": len(self._history),
                "max_history": self._max_history,
                "subscriptions": {
                    k: {
                        "pattern": v.pattern,
                        "handler": v.handler_name,
                        "is_async": v.is_async,
                        "invocations": v.invocation_count,
                        "errors": v.error_count,
                        "avg_duration_ms": round(v.avg_duration_ms, 2),
                    }
                    for k, v in self._subscription_stats.items()
                },
            }

    # ── Internal ──────────────────────────────────────────────────────────

    def _matches(self, pattern: str, event_name: str) -> bool:
        """Check if an event name matches a pattern (supports wildcards)."""
        if pattern == "*":
            return True
        if pattern == event_name:
            return True
        if "*" in pattern:
            return fnmatch.fnmatch(event_name, pattern)
        return False


# ── Singleton ──────────────────────────────────────────────────────────────

_instance: EventBus | None = None
_instance_lock = threading.RLock()


def get_event_bus() -> EventBus:
    """Get the singleton EventBus instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = EventBus()
        return _instance


def reset_event_bus() -> None:
    """Force-reset singleton (for testing)."""
    global _instance
    with _instance_lock:
        _instance = None


__all__ = [
    "Event",
    "EventBus",
    "SubscriptionStats",
    "get_event_bus",
    "reset_event_bus",
]
