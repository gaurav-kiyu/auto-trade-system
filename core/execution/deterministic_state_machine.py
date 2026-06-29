"""
Deterministic Execution State Machine - CRITICAL FIX #1
Prevents duplicate order execution by implementing strict state transitions.

State Flow:
INIT -> VALIDATED -> PERSISTED -> SUBMITTED -> ACKNOWLEDGED -> FILLED
    |         |           |           |            |
    v         v           v           v            v
  FAILED    FAILED     FAILED     REJECTED    PARTIAL_FILL
                                      |            |
                                      v            v
                                   CANCELLED   CANCEL_PENDING
                                                  |
                                                  v
                                               CANCELLED

Key guarantees:
- Never re-place after SUBMITTED/PENDING/PARTIAL_FILL
- Broker-native idempotency where supported
- Deterministic recovery on ambiguity
- Stale acknowledgment recovery
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.execution.durable_state import ExecutionState as DurableExecState
from core.time_provider import time_provider

_log = logging.getLogger(__name__)


class ExecutionState(Enum):
    """Deterministic execution states - no ambiguity allowed.

    UNKNOWN means: "do not retry automatically" - requires manual intervention.
    RECONCILING means: "awaiting broker sync" - reconciliation in progress.
    """
    INIT = "INIT"
    PENDING_SUBMISSION = "PENDING_SUBMISSION"
    VALIDATED = "VALIDATED"
    PERSISTED = "PERSISTED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    RECONCILING = "RECONCILING"


class TransitionResult(Enum):
    SUCCESS = "SUCCESS"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    ALREADY_IN_STATE = "ALREADY_IN_STATE"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"


VALID_TRANSITIONS: dict[ExecutionState, list[ExecutionState]] = {
    ExecutionState.INIT: [ExecutionState.VALIDATED, ExecutionState.FAILED],
    ExecutionState.PENDING_SUBMISSION: [ExecutionState.VALIDATED, ExecutionState.FAILED, ExecutionState.UNKNOWN],
    ExecutionState.VALIDATED: [ExecutionState.PERSISTED, ExecutionState.FAILED],
    ExecutionState.PERSISTED: [ExecutionState.SUBMITTED, ExecutionState.FAILED],
    ExecutionState.SUBMITTED: [ExecutionState.ACKNOWLEDGED, ExecutionState.REJECTED, ExecutionState.FAILED, ExecutionState.UNKNOWN],
    ExecutionState.ACKNOWLEDGED: [ExecutionState.PARTIAL_FILL, ExecutionState.FILLED, ExecutionState.CANCEL_PENDING, ExecutionState.FAILED, ExecutionState.UNKNOWN],
    ExecutionState.PARTIAL_FILL: [ExecutionState.PARTIAL_FILL, ExecutionState.FILLED, ExecutionState.CANCEL_PENDING, ExecutionState.FAILED, ExecutionState.UNKNOWN],
    ExecutionState.CANCEL_PENDING: [ExecutionState.CANCELLED, ExecutionState.FILLED, ExecutionState.FAILED],
    # Terminal states - no further transitions
    ExecutionState.FILLED: [],
    ExecutionState.REJECTED: [],
    ExecutionState.CANCELLED: [],
    ExecutionState.FAILED: [],
    ExecutionState.UNKNOWN: [ExecutionState.RECONCILING],
    ExecutionState.RECONCILING: [ExecutionState.FILLED, ExecutionState.CANCELLED, ExecutionState.FAILED, ExecutionState.UNKNOWN],
}


@dataclass
class ExecutionStateMachine:
    """
    Deterministic execution state machine with persistence guarantees.
    Prevents duplicate order placement through strict state management.
    """
    intent_id: str
    client_order_id: str  # Deterministic ID for broker idempotency
    symbol: str
    quantity: int
    price: float
    direction: str  # BUY/SELL

    state: ExecutionState = ExecutionState.INIT
    broker_order_id: str | None = None
    filled_quantity: int = 0
    average_price: float = 0.0
    error_message: str | None = None

    created_at: str = field(default_factory=lambda: time_provider.format_ts())
    updated_at: str = field(default_factory=lambda: time_provider.format_ts())
    submitted_at: str | None = None
    acknowledged_at: str | None = None
    filled_at: str | None = None

    # Persistence hook
    _persistence_callback: Callable | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def validate_transition(self, new_state: ExecutionState) -> tuple[TransitionResult, str]:
        """Validate and execute state transition deterministically"""
        with self._lock:
            if new_state == self.state:
                return TransitionResult.ALREADY_IN_STATE, f"Already in state {self.state.value}"

            if new_state not in VALID_TRANSITIONS.get(self.state, []):
                return TransitionResult.INVALID_TRANSITION, f"Cannot transition from {self.state.value} to {new_state.value}"

            old_state = self.state

            # Set state FIRST so persistence callback sees the new state
            self.state = new_state

            if self._persistence_callback and new_state in [
                ExecutionState.PERSISTED,
                ExecutionState.SUBMITTED,
                ExecutionState.ACKNOWLEDGED,
                ExecutionState.FILLED,
                ExecutionState.FAILED,
            ]:
                try:
                    self._persistence_callback(self)
                except (KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
                    self.state = old_state  # Revert on persistence failure
                    _log.critical(f"PERSISTENCE FAILURE on transition to {new_state.value}: {e} (type: {type(e).__name__})")
                    return TransitionResult.PERSISTENCE_FAILED, f"Critical: {e}"

            self.updated_at = time_provider.format_ts()

            _log.info(f"State transition: {old_state.value} -> {new_state.value} for intent {self.client_order_id}")

            return TransitionResult.SUCCESS, f"Transitioned to {new_state.value}"

    def try_transition_to(self, new_state: ExecutionState) -> bool:
        """Attempt transition, return success"""
        result, reason = self.validate_transition(new_state)
        return result == TransitionResult.SUCCESS

    def record_submission(self, broker_order_id: str) -> bool:
        """Record broker order ID after submission"""
        with self._lock:
            if self.state != ExecutionState.PERSISTED:
                _log.warning(f"Cannot record submission from state {self.state.value}")
                return False

            self.broker_order_id = broker_order_id
            self.submitted_at = time_provider.format_ts()
            return self.try_transition_to(ExecutionState.SUBMITTED)

    def record_acknowledgment(self) -> bool:
        """Record broker acknowledgment"""
        with self._lock:
            if self.state == ExecutionState.SUBMITTED:
                self.acknowledged_at = time_provider.format_ts()
                return self.try_transition_to(ExecutionState.ACKNOWLEDGED)
        return False

    def record_fill(self, filled_qty: int, price: float) -> bool:
        """Record complete fill - accumulative (handles multiple fills)"""
        with self._lock:
            # Accumulate filled qty and compute weighted average price
            total_value = (self.average_price * self.filled_quantity) + (price * filled_qty)
            new_total_qty = self.filled_quantity + filled_qty
            self.average_price = total_value / new_total_qty if new_total_qty > 0 else 0.0
            self.filled_quantity = new_total_qty
            self.filled_at = time_provider.format_ts()

            if self.state == ExecutionState.ACKNOWLEDGED:
                if filled_qty >= self.quantity:
                    return self.try_transition_to(ExecutionState.FILLED)
                else:
                    return self.try_transition_to(ExecutionState.PARTIAL_FILL)
            elif self.state == ExecutionState.PARTIAL_FILL:
                if self.filled_quantity >= self.quantity:
                    return self.try_transition_to(ExecutionState.FILLED)
                return True  # Stay in PARTIAL_FILL, no state change needed
        return False

    def record_partial_fill(self, filled_qty: int, price: float) -> bool:
        """Record partial fill - delegates to record_fill for consistency"""
        # Delegates to record_fill which handles accumulative weighted-average logic
        return self.record_fill(filled_qty, price)

    def record_rejection(self, reason: str) -> bool:
        """Record order rejection"""
        self.error_message = reason
        if self.state == ExecutionState.SUBMITTED:
            return self.try_transition_to(ExecutionState.REJECTED)
        return False

    def record_failure(self, reason: str) -> bool:
        """Record failure"""
        self.error_message = reason
        return self.try_transition_to(ExecutionState.FAILED)

    def can_retry(self) -> bool:
        """Check if order can be retried (only from FAILED/REJECTED)"""
        return self.state in [ExecutionState.FAILED, ExecutionState.REJECTED]

    def is_terminal(self) -> bool:
        """Check if in terminal state (no more transitions possible)"""
        return self.state in [
            ExecutionState.FILLED,
            ExecutionState.REJECTED,
            ExecutionState.CANCELLED,
            ExecutionState.FAILED,
        ]

    def is_submitted(self) -> bool:
        """Check if order has been submitted (prevent duplicate placement)"""
        return self.state in [
            ExecutionState.SUBMITTED,
            ExecutionState.ACKNOWLEDGED,
            ExecutionState.PARTIAL_FILL,
        ]

    def __repr__(self):
        return f"ExecutionStateMachine(intent={self.client_order_id}, state={self.state.value}, broker_id={self.broker_order_id})"


class ExecutionStateMachineManager:
    """
    Manages multiple execution state machines with persistence.
    Ensures idempotency across the system.

    Phase 5D / C7: On startup, loads non-terminal state machines from the
    DurableExecutionStore so state survives restarts and crashes.
    """

    def __init__(self, persistence_callback: Callable | None = None):
        self._machines: dict[str, ExecutionStateMachine] = {}  # client_order_id -> machine
        self._lock = threading.RLock()
        self._persistence_callback = persistence_callback

    # ── Phase 5D / C7: Crash recovery ───────────────────────────────────────

    def recover_from_store(self, store: Any) -> int:
        """
        Load non-terminal execution records from DurableExecutionStore into
        in-memory state machines. Call once at startup before processing orders.

        Returns the number of machines recovered.
        """
        if store is None:
            return 0
        try:
            records = store.get_non_terminal_executions()
        except (KeyError, ValueError, TypeError, OSError, AttributeError, RuntimeError) as ex:
            _log.warning("Could not recover state machines from durable store: %s", ex)
            return 0

        recovered = 0
        for rec in records:
            client_id = f"OPB-{rec.intent_id}"
            with self._lock:
                if client_id in self._machines:
                    continue  # Already loaded
                machine = ExecutionStateMachine(
                    intent_id=rec.intent_id,
                    client_order_id=client_id,
                    symbol=rec.symbol,
                    quantity=rec.quantity,
                    price=rec.strike_price,
                    direction=rec.direction,
                )
                machine._persistence_callback = self._persistence_callback
                # Map durable state back to execution state
                # NOTE: Keys use DurableExecState (durable_state.py enum), values use ExecutionState (machine enum)
                # PENDING → PENDING_SUBMISSION (not VALIDATED): PENDING means no submission
                # happened yet, so the normal flow re-runs validation + submission.
                state_map = {
                    DurableExecState.PENDING.value: ExecutionState.PENDING_SUBMISSION,
                    DurableExecState.SUBMITTED.value: ExecutionState.SUBMITTED,
                    DurableExecState.PARTIALLY_FILLED.value: ExecutionState.PARTIAL_FILL,
                    DurableExecState.FILLED.value: ExecutionState.FILLED,
                    DurableExecState.CANCELLED.value: ExecutionState.CANCELLED,
                    DurableExecState.REJECTED.value: ExecutionState.REJECTED,
                    DurableExecState.FAILED.value: ExecutionState.FAILED,
                }
                recovered_state = state_map.get(rec.state.value, ExecutionState.UNKNOWN)
                machine.state = recovered_state
                machine.broker_order_id = rec.broker_order_id
                machine.filled_quantity = rec.filled_quantity
                machine.average_price = rec.average_price
                machine.error_message = rec.reject_reason
                self._machines[client_id] = machine
                _log.info(
                    "Recovered state machine %s: state=%s, broker_id=%s",
                    client_id, rec.state.value, rec.broker_order_id,
                )
                recovered += 1

        if recovered:
            _log.info("Crash recovery: loaded %d state machines from durable store", recovered)
        return recovered

    # ────────────────────────────────────────────────────────────────────────

    def create_or_get(
        self,
        intent_id: str,
        symbol: str,
        quantity: int,
        price: float,
        direction: str,
    ) -> tuple[ExecutionStateMachine, bool]:
        """
        Create new execution or return existing (idempotent).
        Returns (machine, is_new) tuple.
        """
        # Generate deterministic client_order_id for broker idempotency
        client_order_id = self._generate_client_order_id(intent_id)

        with self._lock:
            if client_order_id in self._machines:
                existing = self._machines[client_order_id]
                _log.info(f"Returning existing machine for {client_order_id}, state: {existing.state}")
                return existing, False

            machine = ExecutionStateMachine(
                intent_id=intent_id,
                client_order_id=client_order_id,
                symbol=symbol,
                quantity=quantity,
                price=price,
                direction=direction,
            )
            machine._persistence_callback = self._persistence_callback
            self._machines[client_order_id] = machine
            return machine, True

    def _generate_client_order_id(self, intent_id: str) -> str:
        """Generate deterministic client order ID from intent_id only"""
        # Use intent_id directly - no random component for true idempotency
        return f"OPB-{intent_id}"

    def get_machine(self, client_order_id: str) -> ExecutionStateMachine | None:
        """Get existing machine"""
        return self._machines.get(client_order_id)

    def get_all(self) -> list[ExecutionStateMachine]:
        """Return a snapshot copy of all machines."""
        with self._lock:
            return list(self._machines.values())

    def prune_terminals(self, max_age_hours: float = 24) -> int:
        """Remove terminal-state machines older than max_age_hours to prevent unbounded growth."""
        import time as _time
        now_ts = _time.time()
        terminal_states = {
            ExecutionState.FILLED, ExecutionState.REJECTED,
            ExecutionState.CANCELLED, ExecutionState.FAILED,
        }
        removed = 0
        with self._lock:
            keys = list(self._machines.keys())
            for k in keys:
                m = self._machines.get(k)
                if m is None:
                    continue
                if m.state in terminal_states:
                    # created_at uses time_provider.format_ts() which returns ISO format: %Y-%m-%d %H:%M:%S
                    try:
                        created_ts = _time.mktime(_time.strptime(m.created_at, "%Y-%m-%d %H:%M:%S")) if m.created_at else 0
                    except (ValueError, OverflowError, OSError):
                        created_ts = 0
                    if created_ts > 0 and (now_ts - created_ts) > max_age_hours * 3600:
                        del self._machines[k]
                        removed += 1
        if removed:
            _log.info("Pruned %d terminal state machines", removed)
        return removed

    def record_broker_query_result(
        self,
        client_order_id: str,
        broker_order_id: str | None,
        status: str,
        filled_qty: int = 0,
        avg_price: float = 0.0,
    ) -> bool:
        """
        Record result of broker query - used for recovery on ambiguous states.
        This is the ambiguity-safe recovery mechanism.
        """
        with self._lock:
            machine = self._machines.get(client_order_id)
            if not machine:
                _log.warning(f"Unknown client_order_id for broker query: {client_order_id}")
                return False

            # If we got a broker order ID but machine has none, reconcile
            if broker_order_id and not machine.broker_order_id:
                machine.broker_order_id = broker_order_id

            # Transition based on broker's authoritative state
            if status == "FILLED":
                return machine.record_fill(filled_qty, avg_price)
            elif status == "REJECTED":
                return machine.record_rejection("Broker rejected")
            elif status == "CANCELLED":
                return machine.try_transition_to(ExecutionState.CANCELLED)
            else:
                # Unknown state - maintain current or mark failed
                if machine.state == ExecutionState.SUBMITTED:
                    return machine.record_acknowledgment()
                return False


# Singleton instance
_state_machine_manager: ExecutionStateMachineManager | None = None
_manager_lock = threading.RLock()


def get_execution_state_manager(persistence_callback: Callable | None = None) -> ExecutionStateMachineManager:
    """Get singleton execution state machine manager"""
    global _state_machine_manager
    with _manager_lock:
        if _state_machine_manager is None:
            _state_machine_manager = ExecutionStateMachineManager(persistence_callback)
        return _state_machine_manager


def reset_execution_state_manager() -> None:
    """Reset the singleton. Used exclusively by tests to ensure isolation."""
    global _state_machine_manager
    with _manager_lock:
        _state_machine_manager = None


__all__ = [
    "ExecutionState",
    "TransitionResult",
    "VALID_TRANSITIONS",
    "ExecutionStateMachine",
    "ExecutionStateMachineManager",
    "get_execution_state_manager",
    "reset_execution_state_manager",
]
