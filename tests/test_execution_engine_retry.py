"""Tests for execution_engine retry logic with exponential backoff + jitter.

.. deprecated:: v2.55
    ``core/execution_engine.py`` has been removed. These tests use
    the preserved helper in ``tests/helpers/legacy_execution_engine.py``.
    See ``tests/test_execution_service.py`` for equivalent new-path tests.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from tests.helpers.legacy_execution_engine import ExecutionEngine


class TestExecutionEngineRetry:
    def test_success_on_first_attempt(self) -> None:
        broker = MagicMock()
        broker.place_order.return_value = "order_123"
        engine = ExecutionEngine(broker_getter=lambda: broker)
        result = engine.place_order(name="NIFTY", direction="CALL", qty=50, strike=25000)
        assert result.ok
        assert result.order_id == "order_123"

    def test_retry_on_failure_eventually_succeeds(self) -> None:
        broker = MagicMock()
        broker.place_order.side_effect = [None, None, "order_456"]
        engine = ExecutionEngine(broker_getter=lambda: broker)
        result = engine.place_order(name="NIFTY", direction="CALL", qty=50, strike=25000, retries=3)
        assert result.ok
        assert result.order_id == "order_456"
        assert broker.place_order.call_count == 3

    def test_all_retries_fail(self) -> None:
        broker = MagicMock()
        broker.place_order.return_value = None
        engine = ExecutionEngine(broker_getter=lambda: broker)
        result = engine.place_order(name="NIFTY", direction="CALL", qty=50, strike=25000, retries=2)
        assert not result.ok

    def test_exponential_backoff_applied(self) -> None:
        """With retries=3, 2 sleep calls happen (after attempt 1 & 2)."""
        broker = MagicMock()
        broker.place_order.return_value = None
        sleep_times: list[float] = []

        def _track_sleep(s: float) -> None:
            sleep_times.append(s)

        engine = ExecutionEngine(broker_getter=lambda: broker, sleep_fn=_track_sleep, max_backoff_s=8.0)
        result = engine.place_order(name="NIFTY", direction="CALL", qty=50, strike=25000, retries=3, retry_wait_s=1.0)
        assert not result.ok
        assert len(sleep_times) == 2
        assert sleep_times[0] >= 0.5
        assert sleep_times[1] >= 1.0

    def test_backoff_increases_with_each_retry(self) -> None:
        broker = MagicMock()
        broker.place_order.return_value = None
        sleep_times: list[float] = []

        def _track_sleep(s: float) -> None:
            sleep_times.append(s)

        engine = ExecutionEngine(
            broker_getter=lambda: broker,
            sleep_fn=_track_sleep,
            max_backoff_s=10.0,
            jitter_pct=0.0,
        )
        engine.place_order(name="NIFTY", direction="CALL", qty=50, strike=25000, retries=4, retry_wait_s=1.0)
        assert len(sleep_times) == 3
        assert sleep_times[0] < sleep_times[1] < sleep_times[2]

    def test_backoff_capped_at_max(self) -> None:
        broker = MagicMock()
        broker.place_order.return_value = None
        sleep_times: list[float] = []

        def _track_sleep(s: float) -> None:
            sleep_times.append(s)

        engine = ExecutionEngine(
            broker_getter=lambda: broker,
            sleep_fn=_track_sleep,
            max_backoff_s=3.0,
            jitter_pct=0.0,
        )
        engine.place_order(name="NIFTY", direction="CALL", qty=50, strike=25000, retries=5, retry_wait_s=1.0)
        for s in sleep_times:
            assert s <= 3.5

    def test_broker_unavailable(self) -> None:
        engine = ExecutionEngine(broker_getter=lambda: None)
        result = engine.place_order(name="NIFTY", direction="CALL", qty=50, strike=25000)
        assert not result.ok
        assert "broker unavailable" in result.reason

    def test_exception_during_order_triggers_retry(self) -> None:
        broker = MagicMock()
        broker.place_order.side_effect = [RuntimeError("API timeout"), ConnectionError("connection refused"), "order_789"]
        engine = ExecutionEngine(broker_getter=lambda: broker)
        # 2 consecutive retryable errors open circuit breaker (C2 fix)
        result = engine.place_order(name="NIFTY", direction="CALL", qty=50, strike=25000, retries=3)
        assert not result.ok
        assert "CIRCUIT_BREAKER" in result.reason

    def test_cancel_order_returns_bool(self) -> None:
        broker = MagicMock()
        broker.cancel_order.return_value = True
        engine = ExecutionEngine(broker_getter=lambda: broker)
        assert engine.cancel_order("order_123") is True

    def test_cancel_order_no_broker(self) -> None:
        engine = ExecutionEngine(broker_getter=lambda: None)
        assert engine.cancel_order("order_123") is False
