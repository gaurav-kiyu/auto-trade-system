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
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, Callable
from core.time_provider import time_provider

_log = logging.getLogger(__name__)


class ExecutionState(Enum):
    """Deterministic execution states - no ambiguity allowed"""
    INIT = "INIT"
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


class TransitionResult(Enum):
    SUCCESS = "SUCCESS"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    ALREADY_IN_STATE = "ALREADY_IN_STATE"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"


VALID_TRANSITIONS: Dict[ExecutionState, list[ExecutionState]] = {
    ExecutionState.INIT: [ExecutionState.VALIDATED, ExecutionState.FAILED],
    ExecutionState.VALIDATED: [ExecutionState.PERSISTED, ExecutionState.FAILED],
    ExecutionState.PERSISTED: [ExecutionState.SUBMITTED, ExecutionState.FAILED],
    ExecutionState.SUBMITTED: [ExecutionState.ACKNOWLEDGED, ExecutionState.REJECTED, ExecutionState.FAILED],
    ExecutionState.ACKNOWLEDGED: [ExecutionState.PARTIAL_FILL, ExecutionState.FILLED, ExecutionState.CANCEL_PENDING, ExecutionState.FAILED],
    ExecutionState.PARTIAL_FILL: [ExecutionState.PARTIAL_FILL, ExecutionState.FILLED, ExecutionState.CANCEL_PENDING, ExecutionState.FAILED],
    ExecutionState.CANCEL_PENDING: [ExecutionState.CANCELLED, ExecutionState.FILLED, ExecutionState.FAILED],
    # Terminal states - no further transitions
    ExecutionState.FILLED: [],
    ExecutionState.REJECTED: [],
    ExecutionState.CANCELLED: [],
    ExecutionState.FAILED: [],
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
    broker_order_id: Optional[str] = None
    filled_quantity: int = 0
    average_price: float = 0.0
    error_message: Optional[str] = None

    created_at: str = field(default_factory=lambda: time_provider.format_ts())
    updated_at: str = field(default_factory=lambda: time_provider.format_ts())
    submitted_at: Optional[str] = None
    acknowledged_at: Optional[str] = None
    filled_at: Optional[str] = None

    # Persistence hook
    _persistence_callback: Optional[Callable] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def validate_transition(self, new_state: ExecutionState) -> tuple[TransitionResult, str]:
        """Validate and execute state transition deterministically"""
        with self._lock:
            if new_state == self.state:
                return TransitionResult.ALREADY_IN_STATE, f"Already in state {self.state.value}"

            if new_state not in VALID_TRANSITIONS.get(self.state, []):
                return TransitionResult.INVALID_TRANSITION, f"Cannot transition from {self.state.value} to {new_state.value}"

            # Execute transition
            old_state = self.state
            self.state = new_state
            self.updated_at = time_provider.format_ts()

            _log.info(f"State transition: {old_state.value} -> {new_state.value} for intent {self.client_order_id}")

            # Persistence hook for critical transitions
            if self._persistence_callback and new_state in [
                ExecutionState.PERSISTED,
                ExecutionState.SUBMITTED,
                ExecutionState.ACKNOWLEDGED,
                ExecutionState.FILLED,
                ExecutionState.FAILED,
            ]:
                try:
                    self._persistence_callback(self)
                except Exception as e:
                    _log.critical(f"PERSISTENCE FAILURE on transition to {new_state.value}: {e}")
                    return TransitionResult.PERSISTENCE_FAILED, f"Critical: {e}"

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
            return self.try_transition_to(ExecutionState.SUBMITTED)

    def record_acknowledgment(self) -> bool:
        """Record broker acknowledgment"""
        if self.state == ExecutionState.SUBMITTED:
            self.acknowledged_at = time_provider.format_ts()
            return self.try_transition_to(ExecutionState.ACKNOWLEDGED)
        return False

    def record_fill(self, filled_qty: int, price: float) -> bool:
        """Record complete fill"""
        self.filled_quantity = filled_qty
        self.average_price = price
        self.filled_at = time_provider.format_ts()

        if self.state == ExecutionState.ACKNOWLEDGED:
            return self.try_transition_to(ExecutionState.FILLED)
        elif self.state == ExecutionState.PARTIAL_FILL:
            if filled_qty >= self.quantity:
                return self.try_transition_to(ExecutionState.FILLED)
        return False

    def record_partial_fill(self, filled_qty: int, price: float) -> bool:
        """Record partial fill"""
        self.filled_quantity = filled_qty
        self.average_price = price

        if self.state == ExecutionState.ACKNOWLEDGED:
            return self.try_transition_to(ExecutionState.PARTIAL_FILL)
        elif self.state == ExecutionState.PARTIAL_FILL:
            # Can stay in partial fill
            return True
        return False

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
    """

    def __init__(self, persistence_callback: Optional[Callable] = None):
        self._machines: Dict[str, ExecutionStateMachine] = {}  # client_order_id -> machine
        self._lock = threading.Lock()
        self._persistence_callback = persistence_callback

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

    def get_machine(self, client_order_id: str) -> Optional[ExecutionStateMachine]:
        """Get existing machine"""
        return self._machines.get(client_order_id)

    def record_broker_query_result(
        self,
        client_order_id: str,
        broker_order_id: Optional[str],
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
_state_machine_manager: Optional[ExecutionStateMachineManager] = None
_manager_lock = threading.Lock()


def get_execution_state_manager(persistence_callback: Optional[Callable] = None) -> ExecutionStateMachineManager:
    """Get singleton execution state machine manager"""
    global _state_machine_manager
    with _manager_lock:
        if _state_machine_manager is None:
            _state_machine_manager = ExecutionStateMachineManager(persistence_callback)
        return _state_machine_manager