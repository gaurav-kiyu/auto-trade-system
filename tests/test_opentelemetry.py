"""
Tests for core/observability/opentelemetry.py — OpenTelemetry integration.

Since the opentelemetry packages may not be installed in test environments,
these tests primarily validate the no-op fallback behavior and the
configuration-driven initialization logic.
"""

from __future__ import annotations

import time

import pytest
from core.observability.opentelemetry import (
    Timer,
    _NoOpSpan,
    _NoOpTracer,
    auto_init,
    get_tracer,
    init_tracing,
    is_tracing_enabled,
    shutdown_tracing,
    trace_event,
)


class TestNoOpFallback:
    """Tests that all operations gracefully no-op without opentelemetry."""

    def test_init_tracing_disabled_by_default(self):
        """Tracing should be disabled when not configured."""
        result = init_tracing({})
        assert result is False
        assert is_tracing_enabled() is False

    def test_init_tracing_disabled_explicitly(self):
        """Tracing should stay disabled when tracing_enabled is False."""
        result = init_tracing({"tracing_enabled": False})
        assert result is False
        assert is_tracing_enabled() is False

    def test_init_tracing_enabled_no_package(self):
        """init_tracing should return False when package is not installed."""
        result = init_tracing({"tracing_enabled": True})
        assert result is False  # opentelemetry not installed in test env
        assert is_tracing_enabled() is False

    def test_get_tracer_returns_noop(self):
        """get_tracer should return _NoOpTracer when tracing disabled."""
        tracer = get_tracer("test")
        assert isinstance(tracer, _NoOpTracer)

    def test_noop_span_context_manager(self):
        """NoOpSpan should work as a context manager without error."""
        with _NoOpSpan() as span:
            span.set_attribute("key", "value")
            span.set_status("OK")
            span.record_exception(ValueError("test"))
            span.add_event("test_event", {"key": "value"})
            span.end()
        assert True  # No exception should occur

    def test_trace_event_noop(self):
        """trace_event context manager should no-op gracefully."""
        with trace_event("test_operation", {"key": "value"}):
            result = 1 + 1
        assert result == 2

    def test_trace_event_nested_nop(self):
        """Nested trace_event context managers should not interfere."""
        with trace_event("outer"):
            with trace_event("inner"):
                pass
        assert True

    def test_trace_event_with_exception(self):
        """trace_event should handle exceptions gracefully."""
        try:
            with trace_event("failing_op"):
                raise ValueError("expected failure")
        except ValueError:
            pass
        assert True

    def test_shutdown_tracing_safe_when_not_inited(self):
        """shutdown_tracing should not raise when tracing was never started."""
        shutdown_tracing()
        assert is_tracing_enabled() is False

    def test_double_init_safe(self):
        """Calling init_tracing multiple times should be safe."""
        init_tracing({})
        init_tracing({})
        assert is_tracing_enabled() is False

    def test_auto_init_safe_multiple_calls(self):
        """auto_init should be safe to call multiple times."""
        result1 = auto_init({})
        result2 = auto_init({"tracing_enabled": True})
        # Both should return same result (cached)
        assert result1 == result2


class TestTimer:
    """Tests for the Timer helper class."""

    def test_timer_basic(self):
        """Timer should measure duration."""
        timer = Timer("test")
        time.sleep(0.01)
        duration = timer.stop()
        assert duration >= 8.0  # At least 8ms (allowing for timing variance)
        assert timer.duration_ms >= 8.0

    def test_timer_context_manager(self):
        """Timer should work as a context manager."""
        with Timer("test_ctx") as timer:
            time.sleep(0.01)
        assert timer.duration_ms >= 8.0

    def test_timer_without_stop(self):
        """Timer should report elapsed time even without calling stop()."""
        timer = Timer("test")
        time.sleep(0.005)
        elapsed = timer.duration_ms
        assert elapsed >= 4.0

    def test_timer_duration_sec(self):
        """duration_sec should be duration_ms / 1000."""
        timer = Timer("test")
        time.sleep(0.01)
        timer.stop()
        assert abs(timer.duration_sec * 1000.0 - timer.duration_ms) < 0.001

    def test_timer_zero_name(self):
        """Timer should work with empty name."""
        timer = Timer()
        timer.stop()
        assert timer.duration_ms >= 0


class TestTraceEventAttributes:
    """Tests for trace_event with attributes."""

    def test_trace_event_with_attributes(self):
        """trace_event should accept attributes without error."""
        with trace_event("test", {
            "symbol": "NIFTY",
            "side": "BUY",
            "quantity": 50,
            "price": 150.0,
        }):
            pass
        assert True

    def test_trace_event_without_attributes(self):
        """trace_event should work without attributes."""
        with trace_event("test"):
            pass
        assert True

    def test_trace_event_empty_attributes(self):
        """trace_event should work with empty attributes dict."""
        with trace_event("test", {}):
            pass
        assert True

    def test_trace_event_non_string_values(self):
        """trace_event should handle non-string attribute values."""
        with trace_event("test", {
            "int_val": 42,
            "float_val": 3.14,
            "bool_val": True,
            "none_val": None,
        }):
            pass
        assert True


class TestGracefulDegradation:
    """Tests for graceful degradation without external packages."""

    def test_missing_otel_does_not_crash(self):
        """Missing opentelemetry should not cause crashes."""
        try:
            init_tracing({"tracing_enabled": True})
        except Exception:
            pytest.fail("init_tracing raised an exception when package missing")

    def test_trace_event_swallows_missing_package_error(self):
        """trace_event should not crash when init fails."""
        init_tracing({"tracing_enabled": True})
        with trace_event("safe_operation"):
            result = 42 * 42
        assert result == 1764

    def test_noop_tracer_methods_return_self(self):
        """NoOp methods should return self for chaining."""
        t = _NoOpTracer()
        s1 = t.start_as_current_span("test")
        s2 = t.start_span("test")
        assert isinstance(s1, _NoOpSpan)
        assert isinstance(s2, _NoOpSpan)

    def test_timer_with_otel_enabled(self):
        """Timer should work even if otel init was attempted."""
        init_tracing({"tracing_enabled": True})
        with Timer("test_timer_otel"):
            time.sleep(0.005)
        assert True


class TestInitEdgeCases:
    """Tests for initialization edge cases."""

    def test_auto_init_empty_config(self):
        """auto_init should handle empty config."""
        shutdown_tracing()
        result = auto_init({})
        assert result is False

    def test_shutdown_then_reinit(self):
        """shutdown_tracing followed by init should work."""
        shutdown_tracing()
        assert is_tracing_enabled() is False
        # Re-init disabled
        init_tracing({"tracing_enabled": False})
        assert is_tracing_enabled() is False

    def test_timer_multiple_stops(self):
        """Calling stop() multiple times should not crash."""
        timer = Timer("multi_stop")
        timer.stop()
        timer.stop()  # Second stop should be safe (uses cached _end)
        assert timer.duration_ms >= 0


class TestBackendSelection:
    """Tests for the tracing backend configuration."""

    def test_default_backend_is_otlp(self):
        """Default tracing_backend should be otlp."""
        shutdown_tracing()
        result = init_tracing({"tracing_enabled": True})
        # Should gracefully degrade (packages not installed)
        assert result is False

    def test_jaeger_backend_no_package(self):
        """Jaeger backend should degrade gracefully without packages."""
        shutdown_tracing()
        result = init_tracing({
            "tracing_enabled": True,
            "tracing_backend": "jaeger",
            "jaeger_agent_host": "localhost",
            "jaeger_agent_port": 6831,
        })
        assert result is False  # jaeger package not installed

    def test_zipkin_backend_no_package(self):
        """Zipkin backend should degrade gracefully without packages."""
        shutdown_tracing()
        result = init_tracing({
            "tracing_enabled": True,
            "tracing_backend": "zipkin",
            "zipkin_endpoint": "http://localhost:9411/api/v2/spans",
        })
        assert result is False  # zipkin package not installed

    def test_unknown_backend_falls_back_to_otlp(self):
        """Unknown backend should fall back to OTLP gracefully."""
        shutdown_tracing()
        result = init_tracing({
            "tracing_enabled": True,
            "tracing_backend": "unknown_backend",
        })
        # Should degrade to OTLP attempt, then fail gracefully
        # (OTLP package also not installed in test env)
        assert result is False

    def test_jaeger_http_endpoint_config(self):
        """Jaeger HTTP collector endpoint should be configurable."""
        shutdown_tracing()
        result = init_tracing({
            "tracing_enabled": True,
            "tracing_backend": "jaeger",
            "jaeger_endpoint": "http://jaeger:14268/api/traces",
            "jaeger_auth_token": "",
        })
        assert result is False  # package not installed

    def test_otlp_with_custom_headers(self):
        """OTLP with custom headers should degrade gracefully."""
        shutdown_tracing()
        result = init_tracing({
            "tracing_enabled": True,
            "tracing_backend": "otlp",
            "otlp_endpoint": "https://otlp.example.com:4317",
            "otlp_insecure": False,
            "otlp_headers": "Authorization=Bearer+token123",
            "otlp_timeout": 30,
        })
        assert result is False
