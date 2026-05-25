from __future__ import annotations

import logging
import random
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.execution.retry_policy.classifier import BrokerErrorClassifier, RetryDecision

_log = logging.getLogger(__name__)

warnings.warn(
    "DEPRECATED: core/execution_engine.py (legacy ExecutionEngine) is deprecated. "
    "Use core/execution/deterministic_state_machine.py (ExecutionStateMachine) + "
    "core/services/execution_service.py (ExecutionService) instead. "
    "This module will be removed in v2.55.",
    DeprecationWarning,
    stacklevel=2,
)
_log.warning("DEPRECATED: core/execution_engine.py loaded — migrate to execution_service + state machine")


@dataclass(frozen=True)
class ExecutionFill:
    ok: bool
    filled_qty: int = 0
    fill_price: float | None = None
    status_verified: bool = False
    reason: str = ""


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    order_id: str | None = None
    broker_latency_ms: int = 0
    reason: str = ""


class ExecutionEngine:
    """Broker/order layer with retry (exponential backoff + jitter), cancellation, and fill verification hooks."""

    def __init__(
        self,
        *,
        broker_getter: Callable[[], Any],
        verify_terminal_ok_fn: Callable[[str], bool] | None = None,
        broker_snapshot_fn: Callable[[], dict[str, Any] | list[dict[str, Any]]] | None = None,
        capture_hook: Callable[[dict[str, Any]], None] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        max_backoff_s: float = 8.0,
        jitter_pct: float = 0.25,
        idempotency_check_fn: Callable[[str], bool] | None = None,
    ) -> None:
        self._broker_getter = broker_getter
        self._verify_terminal_ok_fn = verify_terminal_ok_fn
        self._broker_snapshot_fn = broker_snapshot_fn
        self._capture_hook = capture_hook
        self._sleep_fn = sleep_fn or time.sleep
        self._max_backoff_s = max_backoff_s
        self._jitter_pct = jitter_pct
        self._idempotency_check_fn = idempotency_check_fn

    def _broker(self) -> Any:
        return self._broker_getter()

    def _capture(self, payload: dict[str, Any]) -> None:
        if not self._capture_hook:
            return
        try:
            self._capture_hook(dict(payload))
        except Exception:
            pass

    def place_order(
        self,
        *,
        name: str,
        direction: str,
        qty: int,
        strike: int,
        intent_id: str = "",
        retries: int = 3,
        retry_wait_s: float = 1.0,
        is_exit: bool = False,
    ) -> ExecutionResult:
        # Idempotency check: if intent already submitted, block duplicate
        if intent_id and self._idempotency_check_fn:
            already_submitted = self._idempotency_check_fn(intent_id)
            if already_submitted:
                self._capture({"event": "duplicate_intent_blocked", "intent_id": intent_id, "symbol": name})
                return ExecutionResult(False, reason=f"DUPLICATE_INTENT_BLOCKED: intent {intent_id} already submitted")

        broker = self._broker()
        if broker is None:
            self._capture({"event": "place_order_failed", "symbol": name, "direction": direction, "qty": qty, "strike": strike, "note": "broker unavailable"})
            return ExecutionResult(False, reason="broker unavailable")
        action = broker.exit_order if is_exit else broker.place_order
        last_reason = "broker returned no order id"

        _consecutive_retryable: int = 0

        for attempt in range(1, max(1, retries) + 1):
            start = time.monotonic()
            try:
                order_id = action(name, direction, qty, strike)
            except Exception as exc:
                order_id = None
                last_reason = str(exc)

                # Classify the error to determine retry strategy (Phase 0 fix)
                decision = BrokerErrorClassifier.classify(exc)

                # Circuit breaker: if 2 consecutive RETRYABLE failures
                # (regardless of exception type), escalate to UNKNOWN.
                if decision == RetryDecision.RETRY:
                    _consecutive_retryable += 1
                    if _consecutive_retryable >= 2:
                        decision = RetryDecision.UNKNOWN
                        last_reason = (
                            f"CIRCUIT_BREAKER: {_consecutive_retryable}x consecutive "
                            f"retryable errors — retry stopped: {type(exc).__name__}"
                        )
                        self._capture({
                            "event": "retry_circuit_breaker_opened",
                            "symbol": name,
                            "direction": direction,
                            "qty": qty,
                            "strike": strike,
                            "error_type": type(exc).__name__,
                            "consecutive_failures": _consecutive_retryable,
                        })

                if decision == RetryDecision.PERMANENT:
                    # PERMANENT errors should never be retried - could cause duplicates
                    self._capture({
                        "event": "place_order_permanent_failure",
                        "symbol": name,
                        "direction": direction,
                        "qty": qty,
                        "strike": strike,
                        "note": f"PERMANENT error - not retrying: {last_reason}",
                        "retry_decision": "PERMANENT",
                    })
                    self._capture({"event": "place_order_failed", "symbol": name, "direction": direction, "qty": qty, "strike": strike, "note": last_reason})
                    return ExecutionResult(False, broker_latency_ms=0, reason=f"PERMANENT: {last_reason}")

                if decision == RetryDecision.UNKNOWN:
                    # UNKNOWN errors require manual intervention - alert but don't retry blindly
                    self._capture({
                        "event": "place_order_unknown_failure",
                        "symbol": name,
                        "direction": direction,
                        "qty": qty,
                        "strike": strike,
                        "note": f"UNKNOWN error - manual intervention required: {last_reason}",
                        "retry_decision": "UNKNOWN",
                    })
                    self._capture({"event": "place_order_failed", "symbol": name, "direction": direction, "qty": qty, "strike": strike, "note": last_reason})
                    return ExecutionResult(False, broker_latency_ms=0, reason=f"UNKNOWN - needs investigation: {last_reason}")

                # RETRYABLE errors continue with backoff

            latency_ms = int(round((time.monotonic() - start) * 1000))
            if order_id:
                self._capture(
                    {
                        "event": "exit_order" if is_exit else "place_order",
                        "order_id": str(order_id),
                        "symbol": name,
                        "direction": direction,
                        "qty": qty,
                        "strike": strike,
                        "broker_latency_ms": latency_ms,
                        "attempt": attempt,
                    }
                )
                return ExecutionResult(True, order_id=str(order_id), broker_latency_ms=latency_ms)
            if attempt < retries:
                # Exponential backoff with jitter: base×2^(attempt-1) ± jitter%
                backoff = min(retry_wait_s * (2 ** (attempt - 1)), self._max_backoff_s)
                jitter = backoff * self._jitter_pct
                sleep_for = backoff - jitter + random.random() * 2 * jitter
                self._sleep_fn(sleep_for)
        self._capture(
            {
                "event": "place_order_failed",
                "symbol": name,
                "direction": direction,
                "qty": qty,
                "strike": strike,
                "note": last_reason,
            }
        )
        return ExecutionResult(False, broker_latency_ms=0, reason=last_reason)

    def cancel_order(self, order_id: str | None) -> bool:
        broker = self._broker()
        if broker is None or not order_id or not hasattr(broker, "cancel_order"):
            return False
        try:
            ok = bool(broker.cancel_order(order_id))
            self._capture({"event": "cancel_order", "order_id": str(order_id), "ok": ok})
            return ok
        except Exception:
            return False

    def verify_fill(self, order_id: str, timeout: int = 10, requested_qty: int = 0) -> ExecutionFill:
        broker = self._broker()
        if broker is None or not order_id:
            return ExecutionFill(False, reason="broker unavailable")
        try:
            fill_ok = bool(broker.wait_for_fill(order_id, timeout=timeout))
        except Exception as exc:
            return ExecutionFill(False, reason=str(exc))
        filled_qty = 0
        fill_price = None
        try:
            if hasattr(broker, "get_filled_quantity"):
                filled_qty = int(broker.get_filled_quantity(order_id) or 0)
        except Exception:
            filled_qty = 0
        try:
            if hasattr(broker, "get_fill_price"):
                raw_fill = broker.get_fill_price(order_id)
                if raw_fill:
                    fill_price = float(raw_fill)
        except Exception:
            fill_price = None
        verified = True
        if self._verify_terminal_ok_fn:
            try:
                verified = bool(self._verify_terminal_ok_fn(str(order_id)))
            except Exception:
                verified = False
        fill = ExecutionFill(
            ok=bool(fill_ok or filled_qty > 0),
            filled_qty=max(0, filled_qty),
            fill_price=fill_price,
            status_verified=verified,
            reason="" if (fill_ok or filled_qty > 0) else "order not filled",
        )
        if fill.ok and requested_qty > 0 and fill.filled_qty < requested_qty:
            self._capture({"event": "partial_fill_warning", "order_id": str(order_id),
                           "requested": requested_qty, "filled": fill.filled_qty})
        self._capture(
            {
                "event": "verify_fill",
                "order_id": str(order_id),
                "ok": fill.ok,
                "filled_qty": fill.filled_qty,
                "fill_price": fill.fill_price,
                "status_verified": fill.status_verified,
                "reason": fill.reason,
            }
        )
        return fill

    def broker_snapshot(self) -> dict[str, Any] | list[dict[str, Any]]:
        if not self._broker_snapshot_fn:
            return {}
        try:
            return self._broker_snapshot_fn() or {}
        except Exception:
            return {}
