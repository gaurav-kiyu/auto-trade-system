"""
Legacy ExecutionEngine, ExecutionFill, ExecutionResult — preserved for test backward-compatibility.

This is a copy of the old ``core/execution_engine.py`` shim, kept in the test helper
package so existing test files can continue to import these classes without
depending on the (now removed) production module.

Migration guide:
    - Replace ``ExecutionEngine(...)`` with ``ExecutionService(broker_port=...)``
    - Replace ``engine.place_order(...)`` with ``service.execute_order(OrderRequest(...))``
    - Replace ``engine.verify_fill(...)`` with ``service.verify_order_fill(...)``
    - Replace ``engine.cancel_order(...)`` with ``service.cancel_order(...)``
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.exceptions import (
    BrokerAuthError,
    BrokerConnectionError,
    BrokerException,
    BrokerRateLimitError,
    BrokerRejectedError,
    BrokerTimeoutError,
)


@dataclass(frozen=True)
class ExecutionResult:
    """Backward-compat replacement matching original ExecutionResult shape."""
    ok: bool
    order_id: str | None = None
    broker_latency_ms: int = 0
    reason: str = ""


@dataclass(frozen=True)
class ExecutionFill:
    """Backward-compat replacement matching original ExecutionFill shape."""
    ok: bool
    filled_qty: int = 0
    fill_price: float | None = None
    status_verified: bool = False
    reason: str = ""


class ExecutionEngine:
    """
    DEPRECATED — test backward-compatibility shim.

    Delegates to a broker adapter internally so existing test fixtures
    continue to work. New tests should use ExecutionService instead.
    """

    def __init__(
        self,
        *,
        broker_getter: Callable[[], Any] | None = None,
        verify_terminal_ok_fn: Callable[[str], bool] | None = None,
        broker_snapshot_fn: Callable[[], dict | list] | None = None,
        capture_hook: Callable[[dict], None] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        max_backoff_s: float = 8.0,
        jitter_pct: float = 0.25,
        idempotency_check_fn: Callable[[str], bool] | None = None,
    ):
        self._broker_getter = broker_getter or (lambda: None)
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
        except (ValueError, TypeError, KeyError):
            pass

    @staticmethod
    def _classify_error(exc: Exception) -> str:
        """Classify a broker exception as PERMANENT, RETRY, or UNKNOWN.

        Mirrors the original BrokerErrorClassifier behavior.
        """
        # Permanent — no retry
        if isinstance(exc, (BrokerRejectedError, BrokerRateLimitError, BrokerAuthError)):
            return "PERMANENT"
        # Retryable
        if isinstance(exc, (BrokerConnectionError, BrokerTimeoutError)):
            return "RETRY"
        # Standard library exceptions — treat as retryable
        if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            return "RETRY"
        if isinstance(exc, (RuntimeError, ValueError, TypeError)):
            return "RETRY"
        # Fallback: treat unknown BrokerException as PERMANENT, everything else as RETRY
        if isinstance(exc, BrokerException):
            return "PERMANENT"
        return "RETRY"

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
        # Idempotency check — block duplicates immediately
        if intent_id and self._idempotency_check_fn:
            try:
                if self._idempotency_check_fn(intent_id):
                    self._capture({
                        "event": "duplicate_intent_blocked",
                        "intent_id": intent_id,
                        "symbol": name,
                    })
                    return ExecutionResult(False, reason="DUPLICATE_INTENT_BLOCKED")
            except (ValueError, TypeError, RuntimeError):
                pass  # If check fails, let through

        broker = self._broker()
        if broker is None:
            self._capture({"event": "place_order_failed", "symbol": name, "note": "broker unavailable"})
            return ExecutionResult(False, reason="broker unavailable")

        action = broker.exit_order if is_exit else broker.place_order
        last_reason = "broker returned no order id"
        consecutive_exception_failures = 0
        max_attempts = max(1, retries)

        for attempt in range(1, max_attempts + 1):
            start = time.monotonic()
            try:
                order_id = action(name, direction, qty, strike)
            except Exception as exc:
                classification = self._classify_error(exc)
                last_reason = classification + ": " + str(exc)

                # Permanent — no retry, return immediately
                if classification == "PERMANENT":
                    if isinstance(exc, BrokerRejectedError):
                        self._capture({
                            "event": "order_rejected",
                            "symbol": name,
                            "reason": str(exc),
                            "attempt": attempt,
                        })
                    self._capture({
                        "event": "place_order_failed",
                        "symbol": name,
                        "note": str(exc),
                        "attempt": attempt,
                    })
                    return ExecutionResult(False, reason=last_reason)

                # Retryable — count consecutive exception failures for circuit breaker
                consecutive_exception_failures += 1
                if consecutive_exception_failures >= 2:
                    # Circuit breaker opens after 2 consecutive retryable failures
                    self._capture({
                        "event": "place_order_failed",
                        "symbol": name,
                        "note": f"CIRCUIT_BREAKER after {consecutive_exception_failures} failures",
                        "attempt": attempt,
                    })
                    return ExecutionResult(False, reason="CIRCUIT_BREAKER")

                # Retry with backoff
                if attempt < max_attempts:
                    backoff = min(retry_wait_s * (2 ** (attempt - 1)), self._max_backoff_s)
                    jitter = backoff * self._jitter_pct
                    sleep_for = backoff - jitter + random.random() * 2 * jitter
                    self._sleep_fn(sleep_for)
                continue

            latency_ms = int(round((time.monotonic() - start) * 1000))
            if order_id:
                self._capture({
                    "event": "exit_order" if is_exit else "place_order",
                    "order_id": str(order_id),
                    "symbol": name,
                    "broker_latency_ms": latency_ms,
                    "attempt": attempt,
                })
                return ExecutionResult(True, order_id=str(order_id), broker_latency_ms=latency_ms)

            # None returned — retry without circuit breaker (original behavior)
            if attempt < max_attempts:
                backoff = min(retry_wait_s * (2 ** (attempt - 1)), self._max_backoff_s)
                jitter = backoff * self._jitter_pct
                sleep_for = backoff - jitter + random.random() * 2 * jitter
                self._sleep_fn(sleep_for)

        self._capture({"event": "place_order_failed", "symbol": name, "note": last_reason})
        return ExecutionResult(False, reason=last_reason)

    def cancel_order(self, order_id: str | None) -> bool:
        broker = self._broker()
        if broker is None or not order_id:
            return False
        try:
            result = bool(broker.cancel_order(order_id))
            if result:
                self._capture({"event": "cancel_order", "order_id": order_id})
            return result
        except (ValueError, AttributeError, OSError, TypeError):
            return False

    def verify_fill(
        self, order_id: str, timeout: int = 10, requested_qty: int = 0
    ) -> ExecutionFill:
        broker = self._broker()
        if broker is None or not order_id:
            return ExecutionFill(False, reason="broker unavailable")
        try:
            fill_ok = bool(broker.wait_for_fill(order_id, timeout=timeout))
        except (ConnectionError, OSError, ValueError, TypeError, RuntimeError) as exc:
            return ExecutionFill(False, reason=str(exc))
        filled_qty = 0
        fill_price: float | None = None
        try:
            if hasattr(broker, "get_filled_quantity"):
                filled_qty = int(broker.get_filled_quantity(order_id) or 0)
        except (ValueError, TypeError):
            filled_qty = 0
        try:
            if hasattr(broker, "get_fill_price"):
                raw = broker.get_fill_price(order_id)
                if raw:
                    fill_price = float(raw)
        except (ValueError, TypeError):
            fill_price = None
        verified = True
        if self._verify_terminal_ok_fn:
            try:
                verified = bool(self._verify_terminal_ok_fn(str(order_id)))
            except (ValueError, TypeError, RuntimeError):
                verified = False

        # Partial fill warning
        if fill_ok and requested_qty > 0 and filled_qty < requested_qty:
            self._capture({
                "event": "partial_fill_warning",
                "order_id": order_id,
                "requested": requested_qty,
                "filled": filled_qty,
            })

        return ExecutionFill(
            ok=bool(fill_ok or filled_qty > 0),
            filled_qty=max(0, filled_qty),
            fill_price=fill_price,
            status_verified=verified,
            reason="" if (fill_ok or filled_qty > 0) else "order not filled",
        )

    def broker_snapshot(self) -> dict | list:
        if not self._broker_snapshot_fn:
            return {}
        try:
            return self._broker_snapshot_fn() or {}
        except (ValueError, TypeError, KeyError, OSError):
            return {}
