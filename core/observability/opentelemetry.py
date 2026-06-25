"""
OpenTelemetry Integration — Distributed Tracing for Trading System.

Provides non-invasive OpenTelemetry instrumentation for the trading platform.
All tracing is opt-in via config and gracefully degrades to no-op if the
opentelemetry packages are not installed.

Usage
-----
    from core.observability.opentelemetry import get_tracer, trace_event

    # Trace a specific operation
    with trace_event("order_processing", {"symbol": "NIFTY", "side": "BUY"}):
        process_order()

    # Or use the tracer directly
    tracer = get_tracer("order_manager")
    with tracer.start_as_current_span("submit_order") as span:
        span.set_attribute("order_id", "ORD-001")
        submit_to_broker()

Design
------
- Lazy initialization: opentelemetry packages are imported only when enabled
- Config-driven: tracing_enabled, otlp_endpoint, service_name config keys
- Thread-safe singleton for the tracer provider
- Graceful fallback to no-op if packages are missing
- Compatible with OpenTelemetry SDK and OTLP, Jaeger, and Zipkin exporters
- Backend selection via ``tracing_backend`` config key (otlp / jaeger / zipkin)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

_log = logging.getLogger(__name__)

# ── Module-level state ───────────────────────────────────────────────────────

_tracer_provider = None
_service_name = "opb-trading-bot"
_tracing_enabled = False
_otel_available = False
_init_lock = threading.RLock()


def _check_otel_available() -> bool:
    """Check if opentelemetry packages are installed."""
    try:
        import opentelemetry  # noqa: F401
        return True
    except ImportError:
        return False


# ── Initialization ───────────────────────────────────────────────────────────


def init_tracing(config: dict[str, Any] | None = None) -> bool:
    """Initialize OpenTelemetry tracing from config.

    Args:
        config: Config dict with keys:
            - tracing_enabled (bool): Whether to enable tracing (default False).
            - otlp_endpoint (str): OTLP gRPC endpoint (default "http://localhost:4317").
            - service_name (str): Service name for traces (default "opb-trading-bot").
            - tracing_sample_rate (float): Sampling rate 0-1 (default 0.1).
            - tracing_console_exporter (bool): Also log to console (default True).

    Returns:
        True if tracing was initialized, False if disabled or unavailable.
    """
    global _tracer_provider, _service_name, _tracing_enabled, _otel_available

    cfg = config or {}
    if not cfg.get("tracing_enabled", False):
        _tracing_enabled = False
        _log.debug("[OTEL] Tracing disabled via config")
        return False

    with _init_lock:
        if _tracing_enabled and _tracer_provider is not None:
            return True  # Already initialized

        if not _check_otel_available():
            _log.warning(
                "[OTEL] opentelemetry packages not installed. "
                "Install with: pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp"
            )
            _otel_available = False
            _tracing_enabled = False
            return False

        _otel_available = True
        _service_name = cfg.get("service_name", "opb-trading-bot")

        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.resources import Resource

            # Create resource with service name
            resource = Resource.create({
                "service.name": _service_name,
                "service.version": cfg.get("software_version", "2.53.0"),
                "deployment.environment": cfg.get("ENVIRONMENT", "dev"),
            })

            provider = TracerProvider(
                resource=resource,
            )

            # Configure exporters
            exporters_configured = 0

            # Console exporter (for local debugging)
            if cfg.get("tracing_console_exporter", True):
                try:
                    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
                    from opentelemetry.sdk.trace.export.in_memory import ConsoleSpanExporter

                    console_exporter = ConsoleSpanExporter()
                    provider.add_span_processor(
                        SimpleSpanProcessor(console_exporter)
                    )
                    exporters_configured += 1
                    _log.debug("[OTEL] Console span exporter configured")
                except ImportError:
                    _log.debug("[OTEL] Console span exporter not available")

            # Select tracing backend: otlp (default), jaeger, or zipkin
            tracing_backend = cfg.get("tracing_backend", "otlp").lower()
            _log.debug("[OTEL] Tracing backend: %s", tracing_backend)

            if tracing_backend == "jaeger":
                exporters_configured += _configure_jaeger_exporter(provider, cfg)
            elif tracing_backend == "zipkin":
                exporters_configured += _configure_zipkin_exporter(provider, cfg)
            else:
                # Default: OTLP exporter (works with Jaeger, Zipkin, Grafana Tempo via OTLP protocol)
                exporters_configured += _configure_otlp_exporter(provider, cfg)

            trace.set_tracer_provider(provider)
            _tracer_provider = provider
            _tracing_enabled = True

            _log.info(
                "[OTEL] Tracing initialized: service=%s, exporters=%d",
                _service_name, exporters_configured,
            )
            return True

        except ImportError as exc:
            _log.warning("[OTEL] Failed to initialize tracing: %s", exc)
            _otel_available = False
            _tracing_enabled = False
            return False


def shutdown_tracing() -> None:
    """Shutdown the tracer provider, flushing all pending spans."""
    global _tracer_provider, _tracing_enabled
    if _tracer_provider is not None:
        try:
            from opentelemetry import trace
            _tracer_provider.shutdown()
            trace.set_tracer_provider(None)
        except (ImportError, AttributeError, Exception) as exc:
            _log.debug("[OTEL] Shutdown skipped: %s", exc)
    _tracer_provider = None
    _tracing_enabled = False


# ── Tracer access ────────────────────────────────────────────────────────────


def get_tracer(component: str = "default") -> Any:
    """Get an OpenTelemetry tracer for the given component.

    Returns a no-op tracer if tracing is disabled or unavailable.
    """
    if not _tracing_enabled or not _otel_available:
        return _NoOpTracer()

    try:
        from opentelemetry import trace
        return trace.get_tracer(_service_name, component)
    except ImportError:
        return _NoOpTracer()


def is_tracing_enabled() -> bool:
    """Check if tracing is currently enabled."""
    return _tracing_enabled and _otel_available


# ── Convenience context manager ─────────────────────────────────────────────


class trace_event:
    """Context manager for tracing a named event with attributes.

    Usage:
        with trace_event("process_order", {"symbol": "NIFTY", "side": "BUY"}):
            do_work()

    Gracefully degrades to no-op if tracing is disabled.
    """

    def __init__(self, span_name: str, attributes: dict[str, Any] | None = None):
        self._name = span_name
        self._attrs = attributes or {}
        self._span = None

    def __enter__(self) -> Any:
        if not _tracing_enabled or not _otel_available:
            return _NoOpSpan()

        tracer = get_tracer("trace_event")
        ctx_mgr = tracer.start_as_current_span(self._name)
        span = ctx_mgr.__enter__()  # Start span first
        if span and self._attrs:
            for key, value in self._attrs.items():
                try:
                    span.set_attribute(key, str(value))
                except (TypeError, ValueError, AttributeError):
                    pass
        self._span = ctx_mgr  # Store the context manager for __exit__
        return span

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._span:
            # Delegate to the span's context manager __exit__ which handles
            # exception recording and status setting from the SDK
            self._span.__exit__(exc_type, exc_val, exc_tb)


# ── No-op fallbacks ─────────────────────────────────────────────────────────


class _NoOpSpan:
    """No-op span that does nothing."""

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *args) -> None:
        pass

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: Any) -> None:
        pass

    def record_exception(self, exception: Exception) -> None:
        pass

    def add_event(self, name: str, attributes: dict | None = None) -> None:
        pass

    def end(self) -> None:
        pass


class _NoOpTracer:
    """No-op tracer that returns no-op spans."""

    def start_as_current_span(self, name: str, attributes: dict | None = None) -> _NoOpSpan:
        return _NoOpSpan()

    def start_span(self, name: str, attributes: dict | None = None) -> _NoOpSpan:
        return _NoOpSpan()


# ── Individual exporter configuration ───────────────────────────────────────


def _configure_otlp_exporter(provider: Any, cfg: dict[str, Any]) -> int:
    """Configure OTLP gRPC exporter (default backend — works with Jaeger, Zipkin, Tempo)."""
    count = 0
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    otlp_endpoint = cfg.get("otlp_endpoint", "http://localhost:4317")
    if not otlp_endpoint:
        return 0

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        insecure = cfg.get("otlp_insecure", True)
        kwargs = {"endpoint": otlp_endpoint, "insecure": insecure}
        if cfg.get("otlp_headers"):
            kwargs["headers"] = cfg["otlp_headers"]
        if cfg.get("otlp_timeout"):
            kwargs["timeout"] = cfg["otlp_timeout"]

        otlp_exporter = OTLPSpanExporter(**kwargs)
        provider.add_span_processor(
            BatchSpanProcessor(otlp_exporter)
        )
        count += 1
        _log.info("[OTEL] OTLP exporter configured for %s", otlp_endpoint)
    except ImportError:
        _log.debug(
            "[OTEL] OTLP exporter not available — "
            "install opentelemetry-exporter-otlp"
        )
    except Exception as exc:
        _log.warning("[OTEL] OTLP exporter init failed: %s", exc)

    return count


def _configure_jaeger_exporter(provider: Any, cfg: dict[str, Any]) -> int:
    """Configure Jaeger exporter via Thrift compact protocol.

    Requires: pip install opentelemetry-exporter-jaeger

    Config keys:
        - jaeger_agent_host (str): Jaeger agent host (default "localhost").
        - jaeger_agent_port (int): Jaeger agent compact port (default 6831).
        - jaeger_endpoint (str): Optional HTTP endpoint for collector (overrides agent).
    """
    count = 0
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    try:
        from opentelemetry.exporter.jaeger.thrift import JaegerExporter

        jaeger_kwargs: dict[str, Any] = {}
        http_endpoint = cfg.get("jaeger_endpoint", "")
        if http_endpoint:
            jaeger_kwargs["collector_endpoint"] = http_endpoint
            if cfg.get("jaeger_auth_token"):
                jaeger_kwargs["collector_token"] = cfg["jaeger_auth_token"]
        else:
            jaeger_kwargs["agent_host_name"] = cfg.get("jaeger_agent_host", "localhost")
            jaeger_kwargs["agent_port"] = cfg.get("jaeger_agent_port", 6831)

        jaeger_exporter = JaegerExporter(**jaeger_kwargs)
        provider.add_span_processor(
            BatchSpanProcessor(jaeger_exporter)
        )
        count += 1
        _log.info("[OTEL] Jaeger exporter configured: %s", jaeger_kwargs)
    except ImportError:
        _log.debug(
            "[OTEL] Jaeger exporter not available — "
            "install opentelemetry-exporter-jaeger"
        )
    except Exception as exc:
        _log.warning("[OTEL] Jaeger exporter init failed: %s", exc)

    return count


def _configure_zipkin_exporter(provider: Any, cfg: dict[str, Any]) -> int:
    """Configure Zipkin exporter via HTTP.

    Requires: pip install opentelemetry-exporter-zipkin

    Config keys:
        - zipkin_endpoint (str): Zipkin HTTP endpoint (default "http://localhost:9411/api/v2/spans").
        - zipkin_local_endpoint (dict): Local endpoint info (service_name, ipv4, port).
    """
    count = 0
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    try:
        from opentelemetry.exporter.zipkin.json import ZipkinExporter

        zipkin_endpoint = cfg.get("zipkin_endpoint", "http://localhost:9411/api/v2/spans")
        local_endpoint = cfg.get("zipkin_local_endpoint", {
            "service_name": _service_name,
        })

        zipkin_exporter = ZipkinExporter(
            endpoint=zipkin_endpoint,
            local_endpoint=local_endpoint,
        )
        provider.add_span_processor(
            SimpleSpanProcessor(zipkin_exporter)
        )
        count += 1
        _log.info("[OTEL] Zipkin exporter configured for %s", zipkin_endpoint)
    except ImportError:
        _log.debug(
            "[OTEL] Zipkin exporter not available — "
            "install opentelemetry-exporter-zipkin"
        )
    except Exception as exc:
        _log.warning("[OTEL] Zipkin exporter init failed: %s", exc)

    return count


# ── Manual timing helper ─────────────────────────────────────────────────────


class Timer:
    """Simple timer for manual latency tracking.

    Usage:
        timer = Timer("order_submit")
        # ... do work ...
        timer.stop()
        print(timer.duration_ms)  # elapsed milliseconds
    """

    def __init__(self, name: str = ""):
        self.name = name
        self._start = time.time()
        self._end: float | None = None

    def stop(self) -> float:
        """Stop the timer and record the duration."""
        self._end = time.time()
        duration = self.duration_ms
        attrs = {"duration_ms": duration, "name": self.name}

        # Also record as a tracing event if enabled
        if _tracing_enabled and _otel_available:
            tracer = get_tracer("timer")
            with tracer.start_as_current_span(f"timer.{self.name}") as span:
                span.set_attribute("duration_ms", duration)

        return duration

    @property
    def duration_ms(self) -> float:
        """Duration in milliseconds."""
        end = self._end or time.time()
        return (end - self._start) * 1000.0

    @property
    def duration_sec(self) -> float:
        """Duration in seconds."""
        return self.duration_ms / 1000.0

    def __enter__(self) -> Timer:
        return self

    def __exit__(self, *args) -> None:
        self.stop()


# ── Auto-initialization helper ───────────────────────────────────────────────

_auto_inited = False
_auto_init_lock = threading.RLock()


def auto_init(config: dict[str, Any] | None = None) -> bool:
    """Auto-initialize tracing from config (safe to call multiple times).

    Can be called at startup from the DI container or main entry point.
    Only initializes once; subsequent calls are no-ops.

    Args:
        config: Application config dict.

    Returns:
        True if tracing is active, False otherwise.
    """
    global _auto_inited
    if _auto_inited:
        return _tracing_enabled
    with _auto_init_lock:
        if _auto_inited:
            return _tracing_enabled
        _auto_inited = True
        return init_tracing(config)


__all__ = [
    "Timer",
    "auto_init",
    "get_tracer",
    "init_tracing",
    "is_tracing_enabled",
    "shutdown_tracing",
    "trace_event",
]

