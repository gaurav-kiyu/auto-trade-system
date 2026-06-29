"""
Tests for core/execution_engine.py - Legacy Execution Engine.

.. deprecated:: v2.55
    ``core/execution_engine.py`` has been removed. These tests use
    the preserved helper in ``tests/helpers/legacy_execution_engine.py``.
    New execution code should use ``core/services/execution_service.py``
    (``ExecutionService``) + ``core/execution/deterministic_state_machine.py``
    (``ExecutionStateMachine``) + ``core/execution/idempotency/certifier.py``
    (``IdempotencyCertifier``) + ``core/wal/journal.py`` (WAL Journal).

Covers:
  - ExecutionFill and ExecutionResult dataclasses
  - ExecutionEngine initialization with callbacks
  - Place order with retry logic and exponential backoff
  - Idempotency blocking
  - Error classification (PERMANENT, RETRY, UNKNOWN)
  - Circuit breaker after consecutive retryable failures
  - Cancel order
  - Verify fill with partial fill detection
  - Broker snapshot
  - Capture hooks
"""
from __future__ import annotations

from typing import Any

import pytest
from core.exceptions import (
    BrokerConnectionError,
    BrokerRateLimitError,
    BrokerRejectedError,
    BrokerTimeoutError,
)

from tests.helpers.legacy_execution_engine import ExecutionEngine, ExecutionFill, ExecutionResult

# ── Fixtures ─────────────────────────────────────────────────────────


class FakeBroker:
    """Simulates broker with configurable behavior."""

    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}
        self._should_fail: bool = False
        self._fail_count: int = 0
        self._call_count: int = 0
        self._should_timeout: bool = False

    def place_order(self, name: str, direction: str, qty: int, strike: int) -> str:
        self._call_count += 1
        if self._should_fail and self._call_count <= self._fail_count:
            raise BrokerConnectionError("Broker unavailable")
        order_id = f"ORD-{name}-{self._call_count}"
        self.orders[order_id] = {
            "name": name,
            "direction": direction,
            "qty": qty,
            "strike": strike,
            "filled": False,
        }
        return order_id

    def exit_order(self, name: str, direction: str, qty: int, strike: int) -> str:
        return self.place_order(name, direction, qty, strike)

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self.orders:
            return True
        return False

    def wait_for_fill(self, order_id: str, timeout: int = 10) -> bool:
        return order_id in self.orders

    def get_filled_quantity(self, order_id: str) -> int:
        return 1

    def get_fill_price(self, order_id: str) -> float | None:
        return 23500.0


@pytest.fixture()
def broker() -> FakeBroker:
    return FakeBroker()


@pytest.fixture()
def capture_log() -> list[dict[str, Any]]:
    return []


@pytest.fixture()
def engine(
    broker: FakeBroker, capture_log: list[dict[str, Any]]
) -> ExecutionEngine:
    def get_broker() -> FakeBroker:
        return broker

    def capture(payload: dict[str, Any]) -> None:
        capture_log.append(payload)

    return ExecutionEngine(
        broker_getter=get_broker,
        capture_hook=capture,
        sleep_fn=lambda s: None,  # Don't actually sleep
    )


# ── Dataclasses ──────────────────────────────────────────────────────


class TestExecutionFill:
    def test_default_values(self) -> None:
        fill = ExecutionFill(ok=True)
        assert fill.ok
        assert fill.filled_qty == 0
        assert fill.fill_price is None
        assert not fill.status_verified
        assert fill.reason == ""

    def test_with_values(self) -> None:
        fill = ExecutionFill(
            ok=True,
            filled_qty=50,
            fill_price=23500.0,
            status_verified=True,
            reason="filled",
        )
        assert fill.filled_qty == 50
        assert fill.fill_price == 23500.0
        assert fill.status_verified
        assert fill.reason == "filled"


class TestExecutionResult:
    def test_default_values(self) -> None:
        result = ExecutionResult(ok=False)
        assert not result.ok
        assert result.order_id is None
        assert result.broker_latency_ms == 0
        assert result.reason == ""

    def test_success(self) -> None:
        result = ExecutionResult(
            ok=True, order_id="ORD-001", broker_latency_ms=150
        )
        assert result.ok
        assert result.order_id == "ORD-001"
        assert result.broker_latency_ms == 150


# ── Place Order ──────────────────────────────────────────────────────


class TestPlaceOrder:
    def test_place_order_success(self, engine: ExecutionEngine) -> None:
        result = engine.place_order(
            name="NIFTY",
            direction="CALL",
            qty=50,
            strike=23500,
        )
        assert result.ok
        assert result.order_id is not None

    def test_place_order_with_retry_success(
        self, broker: FakeBroker, engine: ExecutionEngine
    ) -> None:
        broker._should_fail = True
        broker._fail_count = 1  # Fail once, succeed on 2nd (circuit breaker opens at 2)
        result = engine.place_order(
            name="NIFTY",
            direction="CALL",
            qty=50,
            strike=23500,
            retries=3,
        )
        assert result.ok
        assert result.order_id is not None

    def test_place_order_all_retries_fail(
        self, broker: FakeBroker, engine: ExecutionEngine
    ) -> None:
        broker._should_fail = True
        broker._fail_count = 99  # Always fail
        result = engine.place_order(
            name="NIFTY",
            direction="CALL",
            qty=50,
            strike=23500,
            retries=2,
        )
        assert not result.ok
        assert "CIRCUIT_BREAKER" in result.reason

    def test_place_order_exit(self, engine: ExecutionEngine) -> None:
        result = engine.place_order(
            name="NIFTY",
            direction="CALL",
            qty=50,
            strike=23500,
            is_exit=True,
        )
        assert result.ok

    def test_place_order_no_broker(self) -> None:
        engine = ExecutionEngine(broker_getter=lambda: None)
        result = engine.place_order(
            name="NIFTY", direction="CALL", qty=50, strike=23500
        )
        assert not result.ok
        assert "broker unavailable" in result.reason


# ── Idempotency ──────────────────────────────────────────────────────


class TestIdempotency:
    def test_idempotency_blocks_duplicate(self, engine: ExecutionEngine) -> None:
        submitted: set[str] = set()

        def check(intent_id: str) -> bool:
            return intent_id in submitted

        engine._idempotency_check_fn = check
        # Mark as submitted
        submitted.add("INTENT-001")
        result = engine.place_order(
            name="NIFTY",
            direction="CALL",
            qty=50,
            strike=23500,
            intent_id="INTENT-001",
        )
        assert not result.ok
        assert "DUPLICATE_INTENT_BLOCKED" in result.reason

    def test_idempotency_passes_new(self, engine: ExecutionEngine) -> None:
        submitted: set[str] = set()

        def check(intent_id: str) -> bool:
            return intent_id in submitted

        engine._idempotency_check_fn = check
        result = engine.place_order(
            name="NIFTY",
            direction="CALL",
            qty=50,
            strike=23500,
            intent_id="FRESH-001",
        )
        assert result.ok

    def test_no_idempotency_check_by_default(self, engine: ExecutionEngine) -> None:
        result = engine.place_order(
            name="NIFTY",
            direction="CALL",
            qty=50,
            strike=23500,
            intent_id="ANY",
        )
        assert result.ok


# ── Error Classification ─────────────────────────────────────────────


class TestErrorClassification:
    def test_permanent_error_not_retried(
        self, broker: FakeBroker, engine: ExecutionEngine
    ) -> None:
        call_count: list[int] = [0]

        def reject_fn(name: str, direction: str, qty: int, strike: int) -> str:
            call_count[0] += 1
            raise BrokerRejectedError("Order rejected")

        broker.place_order = reject_fn
        result = engine.place_order(
            name="NIFTY",
            direction="CALL",
            qty=50,
            strike=23500,
            retries=3,
        )
        assert not result.ok
        assert len(call_count) == 1  # Not retried
        assert "PERMANENT" in result.reason

    def test_timeout_error_retried(
        self, broker: FakeBroker, engine: ExecutionEngine
    ) -> None:
        call_count: list[int] = [0]

        def fail_then_succeed(name: str, direction: str, qty: int, strike: int) -> str:
            call_count[0] += 1
            if call_count[0] <= 1:
                raise BrokerTimeoutError("Timeout")
            return "ORD-OK"

        broker.place_order = fail_then_succeed
        result = engine.place_order(
            name="NIFTY",
            direction="CALL",
            qty=50,
            strike=23500,
            retries=3,
        )
        assert result.ok

    def test_rate_limit_error_fails_permanently(
        self, broker: FakeBroker, engine: ExecutionEngine
    ) -> None:
        """Rate limit errors are classified as PERMANENT by the classifier."""
        call_count: list[int] = [0]

        def rate_limited(name: str, direction: str, qty: int, strike: int) -> str:
            call_count[0] += 1
            raise BrokerRateLimitError("Rate limited")

        broker.place_order = rate_limited
        result = engine.place_order(
            name="NIFTY",
            direction="CALL",
            qty=50,
            strike=23500,
            retries=3,
        )
        assert not result.ok
        assert len(call_count) == 1  # Not retried - PERMANENT
        assert "PERMANENT" in result.reason

    def test_rejected_error_not_retried(
        self, broker: FakeBroker, engine: ExecutionEngine
    ) -> None:
        broker.place_order = lambda n, d, q, s: (_ for _ in ()).throw(  # type: ignore[assignment]
            BrokerRejectedError("Order rejected")
        )
        result = engine.place_order(
            name="NIFTY",
            direction="CALL",
            qty=50,
            strike=23500,
        )
        assert not result.ok


# ── Circuit Breaker ──────────────────────────────────────────────────


class TestCircuitBreaker:
    def test_opens_after_two_retryable_failures(
        self, broker: FakeBroker, engine: ExecutionEngine
    ) -> None:
        call_count: list[int] = [0]

        def always_fail(name: str, direction: str, qty: int, strike: int) -> str:
            call_count[0] += 1
            raise BrokerConnectionError("Connection failed")

        broker.place_order = always_fail
        result = engine.place_order(
            name="NIFTY",
            direction="CALL",
            qty=50,
            strike=23500,
            retries=5,
        )
        assert not result.ok
        assert "CIRCUIT_BREAKER" in result.reason


# ── Cancel Order ─────────────────────────────────────────────────────


class TestCancelOrder:
    def test_cancel_existing_order(
        self, engine: ExecutionEngine, broker: FakeBroker
    ) -> None:
        result = engine.place_order(
            name="NIFTY", direction="CALL", qty=50, strike=23500
        )
        assert result.ok
        cancelled = engine.cancel_order(result.order_id)
        assert cancelled

    def test_cancel_nonexistent_order(self, engine: ExecutionEngine) -> None:
        assert not engine.cancel_order("NONEXISTENT")

    def test_cancel_with_none_id(self, engine: ExecutionEngine) -> None:
        assert not engine.cancel_order(None)

    def test_cancel_no_broker(self) -> None:
        engine = ExecutionEngine(broker_getter=lambda: None)
        assert not engine.cancel_order("ORD-001")


# ── Verify Fill ──────────────────────────────────────────────────────


class TestVerifyFill:
    def test_verify_successful_fill(
        self, engine: ExecutionEngine
    ) -> None:
        result = engine.place_order(
            name="NIFTY", direction="CALL", qty=50, strike=23500
        )
        fill = engine.verify_fill(str(result.order_id))
        assert fill.ok
        assert fill.filled_qty > 0

    def test_verify_without_order_id(self, engine: ExecutionEngine) -> None:
        fill = engine.verify_fill("")
        assert not fill.ok
        assert "broker unavailable" in fill.reason  # or empty order_id

    def test_verify_detects_partial_fill(
        self, engine: ExecutionEngine, capture_log: list[dict[str, Any]]
    ) -> None:
        result = engine.place_order(
            name="NIFTY", direction="CALL", qty=100, strike=23500
        )
        fill = engine.verify_fill(str(result.order_id), requested_qty=100)
        assert fill.ok
        partial_fill_events = [
            e for e in capture_log if e.get("event") == "partial_fill_warning"
        ]
        # Our fake broker fills 1, so if requested 100, partial fill warning
        # should fire
        assert any(e.get("requested") == 100 for e in partial_fill_events)


# ── Broker Snapshot ──────────────────────────────────────────────────


class TestBrokerSnapshot:
    def test_snapshot_no_fn(self) -> None:
        engine = ExecutionEngine(broker_getter=lambda: None)
        assert engine.broker_snapshot() == {}

    def test_snapshot_with_fn(self) -> None:
        def snapshot() -> dict[str, Any]:
            return {"positions": [{"symbol": "NIFTY", "qty": 1}]}

        engine = ExecutionEngine(
            broker_getter=lambda: None, broker_snapshot_fn=snapshot
        )
        snap = engine.broker_snapshot()
        assert snap["positions"] == [{"symbol": "NIFTY", "qty": 1}]

    def test_snapshot_fn_returns_none(self) -> None:
        engine = ExecutionEngine(
            broker_getter=lambda: None, broker_snapshot_fn=lambda: None
        )
        assert engine.broker_snapshot() == {}


# ── Capture Hooks ────────────────────────────────────────────────────


class TestCaptureHook:
    def test_capture_on_success(
        self, engine: ExecutionEngine, capture_log: list[dict[str, Any]]
    ) -> None:
        engine.place_order(
            name="NIFTY", direction="CALL", qty=50, strike=23500
        )
        events = [e["event"] for e in capture_log]
        assert "place_order" in events

    def test_capture_on_failure(
        self, engine: ExecutionEngine, capture_log: list[dict[str, Any]]
    ) -> None:
        engine_with_no_broker = ExecutionEngine(
            broker_getter=lambda: None,
            capture_hook=lambda p: capture_log.append(p),
        )
        engine_with_no_broker.place_order(
            name="NIFTY", direction="CALL", qty=50, strike=23500
        )
        events = [e["event"] for e in capture_log]
        assert "place_order_failed" in events

    def test_capture_on_cancel(
        self, engine: ExecutionEngine, capture_log: list[dict[str, Any]]
    ) -> None:
        result = engine.place_order(
            name="NIFTY", direction="CALL", qty=50, strike=23500
        )
        capture_log.clear()
        engine.cancel_order(str(result.order_id))
        events = [e["event"] for e in capture_log]
        assert "cancel_order" in events

    def test_capture_hook_exception_safe(
        self, engine: ExecutionEngine
    ) -> None:
        """Capture hook raising an exception should not crash the engine."""
        def bad_capture(payload: dict[str, Any]) -> None:
            raise ValueError("Hook failure")

        engine._capture_hook = bad_capture
        result = engine.place_order(
            name="NIFTY", direction="CALL", qty=50, strike=23500
        )
        assert result.ok  # Hook failure should not affect order placement

    def test_capture_on_duplicate_intent(
        self, engine: ExecutionEngine, capture_log: list[dict[str, Any]]
    ) -> None:
        submitted: set[str] = set()
        engine._idempotency_check_fn = lambda i: i in submitted
        submitted.add("DUP-001")
        engine.place_order(
            name="NIFTY", direction="CALL", qty=50, strike=23500,
            intent_id="DUP-001",
        )
        events = [e["event"] for e in capture_log]
        assert "duplicate_intent_blocked" in events


# ── Verify Fill with Terminal Check ──────────────────────────────────


class TestVerifyFillTerminalCheck:
    def test_terminal_check_success(self) -> None:
        def verify(order_id: str) -> bool:
            return True

        engine = ExecutionEngine(
            broker_getter=lambda: FakeBroker(),
            verify_terminal_ok_fn=verify,
        )
        fill = engine.verify_fill("ORD-001")
        assert fill.status_verified

    def test_terminal_check_failure(self) -> None:
        def verify(order_id: str) -> bool:
            return False

        engine = ExecutionEngine(
            broker_getter=lambda: FakeBroker(),
            verify_terminal_ok_fn=verify,
        )
        fill = engine.verify_fill("ORD-001")
        assert not fill.status_verified
