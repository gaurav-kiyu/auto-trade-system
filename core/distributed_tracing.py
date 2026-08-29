"""Distributed Tracing — OpenTelemetry-Compatible Tracing (Constitution v4.0).

Provides lightweight distributed tracing with span context propagation,
hierarchical spans, and export. Designed to be OpenTelemetry-compatible
in API while keeping zero external dependencies.

Constitution Layer: Layer 8 — Reliability, Observability & SRE
Architecture Standard: Observe Everything

Usage:
    from core.distributed_tracing import get_tracer, TraceSpan

    tracer = get_tracer()

    # Create a root span
    with tracer.start_span("trade.execution") as span:
        span.set_attribute("symbol", "NIFTY")
        span.set_attribute("qty", 50)

        # Create a child span
        with tracer.start_span("broker.submit") as child:
            child.set_attribute("order_id", "12345")
            # ... do work ...

    # Or use as function decorator
    @tracer.trace("process_signal")
    def process(signal):
        pass
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class Span:
    """A single span in a trace."""

    span_id: str = ""
    trace_id: str = ""
    parent_span_id: str = ""
    name: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "OK"  # OK, ERROR
    error: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "attributes": dict(self.attributes),
            "status": self.status,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
        }

    def close(self) -> None:
        """Mark span as ended and compute duration."""
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000


@dataclass
class TraceReport:
    """Aggregated trace report."""

    total_spans: int = 0
    total_traces: int = 0
    avg_duration_ms: float = 0.0
    spans_by_name: dict[str, int] = field(default_factory=dict)
    spans_by_status: dict[str, int] = field(default_factory=dict)
    recent_spans: list[Span] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_spans": self.total_spans,
            "total_traces": self.total_traces,
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "spans_by_name": self.spans_by_name,
            "spans_by_status": self.spans_by_status,
            "recent_spans": [s.to_dict() for s in self.recent_spans[:10]],
        }


# ── Tracer ───────────────────────────────────────────────────────────────────


class TraceSpan:
    """Context manager for tracing spans.

    Usage:
        with tracer.start_span("name") as span:
            span.set_attribute("key", "value")
    """

    def __init__(self, name: str, tracer: Tracer, parent: Span | None = None, trace_id: str = "") -> None:
        self._tracer = tracer
        self._span = Span(
            span_id=str(uuid.uuid4()).replace("-", "")[:16],
            trace_id=trace_id or str(uuid.uuid4()).replace("-", "")[:16],
            parent_span_id=parent.span_id if parent else "",
            name=name,
            start_time=time.time(),
        )

    @property
    def span_id(self) -> str:
        return self._span.span_id

    @property
    def trace_id(self) -> str:
        return self._span.trace_id

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self._span.attributes[key] = str(value)

    def set_status(self, status: str, error: str = "") -> None:
        """Set span status (OK or ERROR)."""
        self._span.status = status
        self._span.error = error

    def get_span_data(self) -> Span:
        """Get the underlying Span data object."""
        return self._span

    def __enter__(self) -> TraceSpan:
        # Register this span as the active (current) span for the calling thread
        # so that nested ``start_span`` calls inherit this span's trace_id.
        self._tracer._push_current(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore
        # Unregister from the current-span stack first so a parent span that
        # exits after its children restores the correct nesting context.
        self._tracer._pop_current(self)
        if exc_type is not None:
            self._span.status = "ERROR"
            self._span.error = f"{exc_type.__name__}: {exc_val}"
        self._span.close()
        self._tracer._record_span(self._span)


class Tracer:
    """Lightweight distributed tracer with span context management.

    Thread-safe. Tracks parent-child span relationships and supports
    both context manager and decorator patterns.
    """

    def __init__(self, service_name: str = "opb") -> None:
        self._lock = threading.RLock()
        self._service_name = service_name
        self._spans: list[Span] = []
        self._max_spans = 10000
        self._thread_local = threading.local()

    # ── Span Creation ─────────────────────────────────────────────────────

    def start_span(self, name: str, trace_id: str = "", parent: Span | None = None) -> TraceSpan:
        """Start a new span.

        If called within an existing span context (via 'with tracer.start_span'),
        automatically becomes a child of the current span.

        Args:
            name: Span name (e.g., 'trade.execute', 'broker.submit').
            trace_id: Optional trace ID. Inherits from parent if nested.
            parent: Optional explicit parent span.

        Returns:
            TraceSpan context manager.
        """
        current = self._get_current_span()
        active_parent = parent or current
        if not trace_id and active_parent:
            trace_id = active_parent.trace_id

        return TraceSpan(name=name, tracer=self, parent=active_parent, trace_id=trace_id)

    @contextmanager
    def trace(self, name: str) -> Iterator[TraceSpan]:
        """Decorator/context manager for tracing a function.

        Usage:
            with tracer.trace("my_operation") as span:
                ...

            @tracer.trace("my_func")
            def my_func():
                ...
        """
        span_ctx = self.start_span(name)
        try:
            yield span_ctx
        except Exception as exc:
            span_ctx.set_status("ERROR", str(exc))
            raise
        finally:
            span_ctx.__exit__(None, None, None)

    def trace_decorator(self, name: str) -> Callable:
        """Decorator for tracing function calls.

        Usage:
            @tracer.trace_decorator("process_trade")
            def process_trade(trade):
                ...
        """

        def decorator(func: Callable) -> Callable:
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                with self.trace(name) as span:
                    span.set_attribute("function", func.__name__)
                    return func(*args, **kwargs)

            return wrapper

        return decorator

    # ── Span Queries ──────────────────────────────────────────────────────

    def get_spans(self, trace_id: str = "", name: str = "", limit: int = 100) -> list[Span]:
        """Get spans with optional filters."""
        with self._lock:
            spans = list(self._spans)
        if trace_id:
            spans = [s for s in spans if s.trace_id == trace_id]
        if name:
            spans = [s for s in spans if s.name == name]
        return spans[-limit:]

    def get_trace(self, trace_id: str) -> list[Span]:
        """Get all spans for a trace, in order."""
        return self.get_spans(trace_id=trace_id)

    def get_report(self) -> TraceReport:
        """Generate aggregated trace report."""
        with self._lock:
            spans = list(self._spans)
            if not spans:
                return TraceReport()

            avg_dur = sum(s.duration_ms for s in spans) / len(spans)
            by_name: dict[str, int] = defaultdict(int)
            by_status: dict[str, int] = defaultdict(int)
            traces = set(s.trace_id for s in spans)

            for s in spans:
                by_name[s.name] += 1
                by_status[s.status] += 1

            return TraceReport(
                total_spans=len(spans),
                total_traces=len(traces),
                avg_duration_ms=round(avg_dur, 2),
                spans_by_name=dict(by_name),
                spans_by_status=dict(by_status),
                recent_spans=spans[-20:],
            )

    def get_stats(self) -> dict[str, Any]:
        """Get tracer statistics."""
        with self._lock:
            spans = list(self._spans)
            if not spans:
                return {
                    "total_spans": 0,
                    "total_traces": 0,
                    "span_names": [],
                    "error_count": 0,
                    "service": self._service_name,
                }

            traces = set(s.trace_id for s in spans)
            errors = sum(1 for s in spans if s.status == "ERROR")
            names = list(set(s.name for s in spans))

            return {
                "total_spans": len(spans),
                "total_traces": len(traces),
                "span_names": names,
                "error_count": errors,
                "error_rate": round(errors / max(len(spans), 1) * 100, 1),
                "service": self._service_name,
            }

    # ── Internal ──────────────────────────────────────────────────────────

    def _record_span(self, span: Span) -> None:
        """Record a completed span."""
        with self._lock:
            self._spans.append(span)
            if len(self._spans) > self._max_spans:
                self._spans = self._spans[-self._max_spans :]

    def _push_current(self, span_ctx: TraceSpan) -> None:
        """Push a span as active for the current thread (during its ``with`` block)."""
        stack = getattr(self._thread_local, "span_stack", None)
        if stack is None:
            stack = []
            self._thread_local.span_stack = stack
        stack.append(span_ctx)

    def _pop_current(self, span_ctx: TraceSpan) -> None:
        """Pop a span from the current thread's active stack on exit."""
        stack = getattr(self._thread_local, "span_stack", None)
        if stack and stack and stack[-1] is span_ctx:
            stack.pop()

    def _get_current_span(self) -> Span | None:
        """Get the most recent active span in the current thread context."""
        stack = getattr(self._thread_local, "span_stack", None)
        if stack:
            return stack[-1].get_span_data()
        return None

    def clear_all(self) -> None:
        """Clear all spans (for testing)."""
        with self._lock:
            self._spans.clear()


# ── Singleton ──────────────────────────────────────────────────────────────

_instance: Tracer | None = None
_instance_lock = threading.RLock()


def get_tracer(service_name: str = "opb") -> Tracer:
    """Get the singleton Tracer instance.

    Args:
        service_name: Only used on first creation.
    """
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = Tracer(service_name=service_name)
        return _instance


def reset_tracer() -> None:
    """Force-reset singleton (for testing)."""
    global _instance
    with _instance_lock:
        _instance = None


__all__ = [
    "Span",
    "TraceReport",
    "TraceSpan",
    "Tracer",
    "get_tracer",
    "reset_tracer",
]
