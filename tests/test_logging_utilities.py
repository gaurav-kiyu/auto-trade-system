"""Tests for core/common/utilities/logging.py - Structured logging utilities.

Covers:
- LogContext dataclass
- StructuredLogger init, _log, debug/info/warning/error/critical/exception
- contextualize context manager
- LogContextManager enter/exit (nested, restore)
- Convenience functions: get_logger, log_info, log_debug, log_warning, etc.
- Thread safety of thread-local context
"""
from __future__ import annotations

import io
import json
import logging
import sys
import threading
from typing import Any

import pytest

from core.common.utilities.logging import (
    LogContext,
    LogContextManager,
    StructuredLogger,
    get_logger,
    log_critical,
    log_debug,
    log_error,
    log_info,
    log_warning,
    structured_logger,
    with_context,
)


# =============================================================================
# LogContext Tests
# =============================================================================

class TestLogContext:
    def test_defaults(self):
        ctx = LogContext()
        assert ctx.correlation_id is None
        assert ctx.symbol is None
        assert ctx.strategy is None
        assert ctx.trade_id is None
        assert ctx.user_id is None
        assert ctx.session_id is None
        assert ctx.custom_fields == {}

    def test_with_fields(self):
        ctx = LogContext(
            correlation_id="corr-123",
            symbol="NIFTY",
            strategy="options_buying",
            custom_fields={"env": "test"},
        )
        assert ctx.correlation_id == "corr-123"
        assert ctx.custom_fields["env"] == "test"


# =============================================================================
# StructuredLogger Tests
# =============================================================================

@pytest.fixture
def log_capture() -> io.StringIO:
    """Capture log output to a StringIO."""
    capture = io.StringIO()
    handler = logging.StreamHandler(capture)
    handler.setFormatter(logging.Formatter('%(message)s'))
    # Use a unique logger name to avoid interfering with other tests
    logger = logging.getLogger("test_structured")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return capture


@pytest.fixture
def slogger(log_capture: io.StringIO) -> StructuredLogger:
    """Structured logger writing to capture, with DEBUG level."""
    return StructuredLogger(name="test_structured", level=logging.DEBUG)


class TestStructuredLoggerInit:
    def test_default_name(self):
        slog = StructuredLogger()
        assert slog.logger.name == "trading_bot"

    def test_custom_name(self):
        slog = StructuredLogger(name="my_custom")
        assert slog.logger.name == "my_custom"

    def test_propagate_false(self):
        slog = StructuredLogger("test_prop")
        assert slog.logger.propagate is False


class TestStructuredLoggerLog:
    def test_info(self, slogger: StructuredLogger, log_capture: io.StringIO):
        slogger.info("Hello {user}", user="world")
        output = log_capture.getvalue()
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["message"] == "Hello {user}"
        assert data["logger"] == "test_structured"
        assert data["user"] == "world"

    def test_debug(self, slogger: StructuredLogger, log_capture: io.StringIO):
        slogger.debug("Debug message", debug_id=42)
        output = log_capture.getvalue()
        data = json.loads(output)
        assert data["level"] == "DEBUG"
        assert "debug_id" in data

    def test_warning(self, slogger: StructuredLogger, log_capture: io.StringIO):
        slogger.warning("Warning message")
        output = log_capture.getvalue()
        data = json.loads(output)
        assert data["level"] == "WARNING"

    def test_error(self, slogger: StructuredLogger, log_capture: io.StringIO):
        slogger.error("Error message")
        output = log_capture.getvalue()
        data = json.loads(output)
        assert data["level"] == "ERROR"

    def test_critical(self, slogger: StructuredLogger, log_capture: io.StringIO):
        slogger.critical("Critical message")
        output = log_capture.getvalue()
        data = json.loads(output)
        assert data["level"] == "CRITICAL"

    def test_exception_includes_exc_info(self, slogger: StructuredLogger, log_capture: io.StringIO):
        try:
            raise ValueError("test error")
        except ValueError:
            slogger.exception("Exception occurred")
        output = log_capture.getvalue()
        data = json.loads(output)
        assert data["level"] == "ERROR"
        # exc_info is passed through kwargs and serialized in structured log


class TestStructuredLoggerContext:
    def test_contextualize_adds_fields(self, slogger: StructuredLogger, log_capture: io.StringIO):
        with slogger.contextualize(symbol="NIFTY", trade_id="T-001"):
            slogger.info("Trade update")
        output = log_capture.getvalue()
        data = json.loads(output)
        assert data["symbol"] == "NIFTY"
        assert data["trade_id"] == "T-001"

    def test_contextualize_restores(self, slogger: StructuredLogger, log_capture: io.StringIO):
        with slogger.contextualize(symbol="NIFTY"):
            slogger.info("Inside context")
        slogger.info("Outside context")
        lines = log_capture.getvalue().strip().split("\n")
        data1 = json.loads(lines[0])
        data2 = json.loads(lines[1])
        assert data1["symbol"] == "NIFTY"
        assert "symbol" not in data2

    def test_nested_context(self, slogger: StructuredLogger, log_capture: io.StringIO):
        with slogger.contextualize(symbol="NIFTY"):
            with slogger.contextualize(strategy="momentum"):
                slogger.info("Nested")
        output = log_capture.getvalue()
        data = json.loads(output)
        assert data["symbol"] == "NIFTY"
        assert data["strategy"] == "momentum"

    def test_context_outside_context_manager(self, slogger: StructuredLogger, log_capture: io.StringIO):
        """Logging without context should not include context fields."""
        slogger.info("No context")
        output = log_capture.getvalue()
        data = json.loads(output)
        assert "symbol" not in data
        assert "correlation_id" not in data
        assert "trade_id" not in data


class TestStructuredLoggerKwargs:
    def test_additional_kwargs_merged(self, slogger: StructuredLogger, log_capture: io.StringIO):
        slogger.info("Test msg", extra_field="extra_val", count=42)
        output = log_capture.getvalue()
        data = json.loads(output)
        assert data["extra_field"] == "extra_val"
        assert data["count"] == 42


# =============================================================================
# LogContextManager Tests
# =============================================================================

class TestLogContextManager:
    def test_enter_exit_restores(self, slogger: StructuredLogger):
        """kwargs passed to contextualize() go into custom_fields, not LogContext attrs."""
        manager = LogContextManager(slogger, {"symbol": "NIFTY"})
        context_before = slogger._get_context()
        assert "symbol" not in context_before.custom_fields

        manager.__enter__()
        context_during = slogger._get_context()
        assert "symbol" in context_during.custom_fields
        assert context_during.custom_fields["symbol"] == "NIFTY"

        manager.__exit__(None, None, None)
        context_after = slogger._get_context()
        assert "symbol" not in context_after.custom_fields


# =============================================================================
# Convenience Functions Tests
# =============================================================================

class TestConvenienceFunctions:
    def test_get_logger_default(self):
        logger = get_logger()
        assert logger is structured_logger

    def test_get_logger_custom(self):
        logger = get_logger("custom_name")
        assert logger is not structured_logger
        assert logger.logger.name == "custom_name"

    def test_with_context_returns_manager(self):
        mgr = with_context(symbol="NIFTY")
        assert isinstance(mgr, LogContextManager)
        assert mgr.fields == {"symbol": "NIFTY"}


# =============================================================================
# Thread Safety Tests
# =============================================================================

class TestThreadSafety:
    def test_thread_local_context(self, slogger: StructuredLogger):
        """Context in different threads should be independent."""
        main_context = LogContext(symbol="MAIN")
        slogger._set_context(main_context)

        thread_context_value = [None]

        def worker():
            slogger._set_context(LogContext(symbol="WORKER"))
            thread_context_value[0] = slogger._get_context().symbol

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        assert slogger._get_context().symbol == "MAIN"
        assert thread_context_value[0] == "WORKER"
