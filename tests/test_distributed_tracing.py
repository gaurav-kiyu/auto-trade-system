"""Tests for Distributed Tracing module (core/distributed_tracing.py)."""

from __future__ import annotations

import pytest
from core.distributed_tracing import Span, get_tracer, reset_tracer


@pytest.fixture(autouse=True)
def reset_t():
    reset_tracer()
    yield
    reset_tracer()


class TestTracer:
    def test_start_span(self, reset_t):
        tracer = get_tracer()
        with tracer.start_span("test.op") as span:
            span.set_attribute("key", "value")

        spans = tracer.get_spans(name="test.op")
        assert len(spans) == 1
        assert spans[0].attributes.get("key") == "value"

    def test_span_has_trace_id(self, reset_t):
        tracer = get_tracer()
        with tracer.start_span("trace.me") as span:
            tid = span.trace_id
        assert tid is not None
        assert len(tid) > 0

    def test_span_has_span_id(self, reset_t):
        tracer = get_tracer()
        with tracer.start_span("span.me") as span:
            sid = span.span_id
        assert sid is not None
        assert len(sid) > 0

    def test_nested_spans_share_trace_id(self, reset_t):
        tracer = get_tracer()
        with tracer.start_span("parent") as parent:
            with tracer.start_span("child") as child:
                assert child.trace_id == parent.trace_id

    def test_span_set_and_get_attributes(self, reset_t):
        tracer = get_tracer()
        with tracer.start_span("attr.test") as span:
            span.set_attribute("symbol", "NIFTY")
            span.set_attribute("qty", "50")

        spans = tracer.get_spans(name="attr.test")
        assert spans[0].attributes["symbol"] == "NIFTY"

    def test_span_set_status_error(self, reset_t):
        tracer = get_tracer()
        with tracer.start_span("fail.op") as span:
            span.set_status("ERROR", "something went wrong")

        spans = tracer.get_spans(name="fail.op")
        assert spans[0].status == "ERROR"
        assert "something went wrong" in spans[0].error

    def test_span_closes_and_records_duration(self, reset_t):
        tracer = get_tracer()
        with tracer.start_span("duration.test"):
            pass
        spans = tracer.get_spans(name="duration.test")
        assert spans[0].duration_ms > 0


class TestTraceDecorator:
    def test_trace_context_manager(self, reset_t):
        tracer = get_tracer()
        with tracer.trace("ctx.manager") as span:
            span.set_attribute("op", "test")

        spans = tracer.get_spans(name="ctx.manager")
        assert len(spans) == 1

    def test_trace_decorator(self, reset_t):
        tracer = get_tracer()

        @tracer.trace_decorator("decorated.func")
        def my_func():
            return 42

        result = my_func()
        assert result == 42
        spans = tracer.get_spans(name="decorated.func")
        assert len(spans) == 1

    def test_trace_exception_recorded(self, reset_t):
        tracer = get_tracer()

        with pytest.raises(ValueError):
            with tracer.trace("failing.op"):
                raise ValueError("oops")

        spans = tracer.get_spans(name="failing.op")
        assert len(spans) >= 1
        assert spans[-1].status == "ERROR"


class TestGetSpans:
    def test_get_spans_filter_by_name(self, reset_t):
        tracer = get_tracer()
        with tracer.start_span("op.a"):
            pass
        with tracer.start_span("op.b"):
            pass
        spans = tracer.get_spans(name="op.a")
        assert len(spans) == 1

    def test_get_spans_filter_by_trace(self, reset_t):
        tracer = get_tracer()
        with tracer.start_span("t1") as s1:
            trace_id = s1.trace_id
        with tracer.start_span("t2"):
            pass
        spans = tracer.get_spans(trace_id=trace_id)
        assert len(spans) == 1

    def test_get_trace(self, reset_t):
        tracer = get_tracer()
        with tracer.start_span("parent") as parent:
            with tracer.start_span("child"):
                pass
        trace_spans = tracer.get_trace(parent.trace_id)
        assert len(trace_spans) == 2


class TestReports:
    def test_get_report(self, reset_t):
        tracer = get_tracer()
        with tracer.start_span("report.op"):
            pass
        report = tracer.get_report()
        assert report.total_spans >= 1
        assert report.recent_spans, "report should include the recorded span"
        # avg_duration_ms is rounded to 2dp, so an ultra-fast span (e.g.
        # 0.004ms) rounds to 0.0 — assert on the raw span duration instead
        # to keep the test deterministic on fast machines.
        assert report.recent_spans[0].duration_ms > 0
        assert report.avg_duration_ms >= 0

    def test_get_stats(self, reset_t):
        tracer = get_tracer()
        with tracer.start_span("stat.op"):
            pass
        stats = tracer.get_stats()
        assert stats["total_spans"] >= 1
        assert stats["service"] == "opb"


class TestSpanModel:
    def test_span_to_dict(self):
        s = Span(span_id="s1", trace_id="t1", name="test", start_time=100.0,
                 end_time=200.0, status="OK", duration_ms=100.0)
        d = s.to_dict()
        assert d["span_id"] == "s1"
        assert d["name"] == "test"
        assert d["duration_ms"] == 100.0


class TestSingleton:
    def test_singleton(self):
        t1 = get_tracer()
        t2 = get_tracer()
        assert t1 is t2

    def test_reset(self):
        t1 = get_tracer()
        reset_tracer()
        t2 = get_tracer()
        assert t1 is not t2
