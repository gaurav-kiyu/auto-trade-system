"""
Formal Execution State Machine - Item 1

Implements strict legal transitions for order lifecycle:
CREATED -> RISK_APPROVED -> SUBMITTING -> ACKNOWLEDGED -> FILLED
                                    |                  |
                                    v                  v
                               REJECTED          PARTIALLY_FILLED
                                                        |
                                                        v
                                                  CANCEL_PENDING
                                                        |
                                                        v
                                                    CANCELLED

Terminal states: FILLED, CANCELLED, REJECTED, FAILED_FINAL
Recovery states: UNKNOWN, RECONCILING

Benefits:
- Prevents invalid transitions
- Easier debugging
- Easier testing
- Easier recovery
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.time_provider import time_provider

# ── DEPRECATED MODULE ──────────────────────────────────────────────
# FormalOrderState and FormalOrderStateManager are deprecated.
# Use core/execution/deterministic_state_machine.py (ExecutionStateMachine
# and ExecutionStateMachineManager) for all new order lifecycle management.
# This module is kept only for backward compatibility with existing tests.
warnings.warn(
    "core/execution/execution_state.py is DEPRECATED. Use "
    "core/execution/deterministic_state_machine.py (ExecutionStateMachine) instead.",
    DeprecationWarning,
    stacklevel=2,
)

_log = logging.getLogger(__name__)


class ExecState(Enum):
    """Strict execution states - formal state machine"""
    CREATED = "CREATED"
    RISK_APPROVED = "RISK_APPROVED"
    SUBMITTING = "SUBMITTING"
    UNKNOWN = "UNKNOWN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    RECONCILING = "RECONCILING"
    FAILED_FINAL = "FAILED_FINAL"


class TransitionResult(Enum):
    """Result of state transition attempt"""
    SUCCESS = "SUCCESS"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    ALREADY_IN_STATE = "ALREADY_IN_STATE"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"


VALID_TRANSITIONS: dict[ExecState, list[ExecState]] = {
    ExecState.CREATED: [ExecState.RISK_APPROVED, ExecState.FAILED_FINAL],
    ExecState.RISK_APPROVED: [ExecState.SUBMITTING, ExecState.FAILED_FINAL],
    ExecState.SUBMITTING: [ExecState.ACKNOWLEDGED, ExecState.REJECTED, ExecState.UNKNOWN, ExecState.FAILED_FINAL],
    ExecState.UNKNOWN: [ExecState.RECONCILING],
    ExecState.RECONCILING: [ExecState.FILLED, ExecState.CANCELLED, ExecState.REJECTED, ExecState.FAILED_FINAL, ExecState.UNKNOWN],
    ExecState.ACKNOWLEDGED: [ExecState.PARTIALLY_FILLED, ExecState.FILLED, ExecState.CANCEL_PENDING, ExecState.FAILED_FINAL, ExecState.UNKNOWN],
    ExecState.PARTIALLY_FILLED: [ExecState.PARTIALLY_FILLED, ExecState.FILLED, ExecState.CANCEL_PENDING, ExecState.FAILED_FINAL, ExecState.UNKNOWN],
    ExecState.CANCEL_PENDING: [ExecState.CANCELLED, ExecState.FILLED, ExecState.FAILED_FINAL],
    ExecState.FILLED: [],
    ExecState.CANCELLED: [],
    ExecState.REJECTED: [],
    ExecState.FAILED_FINAL: [],
}


def is_terminal(state: ExecState) -> bool:
    """Check if state is terminal (no more transitions possible)"""
    return state in [ExecState.FILLED, ExecState.CANCELLED, ExecState.REJECTED, ExecState.FAILED_FINAL]


def is_active(state: ExecState) -> bool:
    """Check if order is still active (not terminal)"""
    return not is_terminal(state)


@dataclass
class FormalOrderState:
    """
    DEPRECATED: Use deterministic_state_machine.ExecutionStateMachine instead.

    Formal state machine for order execution lifecycle.
    Enforces strict legal transitions only.

    NOTE: This class is kept for backward compatibility with tests.
    Production code uses deterministic_state_machine.py (ExecutionStateMachineManager)
    as the single source of truth for order state transitions.
    Do NOT use this class in new code.
    """
    _deprecated = True
    intent_id: str
    client_order_id: str
    symbol: str
    quantity: int
    price: float
    direction: str

    state: ExecState = ExecState.CREATED
    broker_order_id: str | None = None
    filled_quantity: int = 0
    remaining_quantity: int = 0
    average_price: float = 0.0
    error_message: str | None = None

    created_at: str = field(default_factory=lambda: time_provider.format_ts())
    updated_at: str = field(default_factory=lambda: time_provider.format_ts())
    submitted_at: str | None = None
    acknowledged_at: str | None = None
    filled_at: str | None = None
    cancelled_at: str | None = None

    _persistence_callback: Callable | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _transition_history: list[dict[str, Any]] = field(default_factory=list)

    def validate_transition(self, new_state: ExecState) -> tuple[TransitionResult, str]:
        """Validate and execute state transition with strict rules"""
        with self._lock:
            if new_state == self.state:
                return TransitionResult.ALREADY_IN_STATE, f"Already in state {self.state.value}"

            if new_state not in VALID_TRANSITIONS.get(self.state, []):
                return TransitionResult.INVALID_TRANSITION, f"Cannot transition from {self.state.value} to {new_state.value}"

            old_state = self.state

            # Persist FIRST, then mutate in-memory state (avoids inconsistency on crash)
            if self._persistence_callback and new_state in [
                ExecState.RISK_APPROVED,
                ExecState.SUBMITTING,
                ExecState.ACKNOWLEDGED,
                ExecState.FILLED,
                ExecState.REJECTED,
                ExecState.FAILED_FINAL,
            ]:
                try:
                    self._persistence_callback(self)
                except (OSError, sqlite3.Error, AttributeError) as e:
                    _log.critical(f"PERSISTENCE FAILURE on transition to {new_state.value}: {e}")
                    return TransitionResult.PERSISTENCE_FAILED, f"Critical: {e}"

            self.state = new_state
            self.updated_at = time_provider.format_ts()

            self._transition_history.append({
                "from": old_state.value,
                "to": new_state.value,
                "timestamp": self.updated_at,
            })

            _log.info(f"[STATE] {self.client_order_id}: {old_state.value} -> {new_state.value}")

            return TransitionResult.SUCCESS, f"Transitioned to {new_state.value}"

    def try_transition(self, new_state: ExecState) -> bool:
        """Attempt transition, return success"""
        result, reason = self.validate_transition(new_state)
        return result == TransitionResult.SUCCESS

    def transition_to_risk_approved(self) -> bool:
        """CREATED -> RISK_APPROVED"""
        return self.try_transition(ExecState.RISK_APPROVED)

    def transition_to_submitting(self) -> bool:
        """RISK_APPROVED -> SUBMITTING"""
        return self.try_transition(ExecState.SUBMITTING)

    def transition_to_acknowledged(self, broker_order_id: str) -> bool:
        """SUBMITTING -> ACKNOWLEDGED"""
        if self.state == ExecState.SUBMITTING:
            self.broker_order_id = broker_order_id
            self.submitted_at = time_provider.format_ts()
            return self.try_transition(ExecState.ACKNOWLEDGED)
        return False

    def transition_to_rejected(self, reason: str) -> bool:
        """SUBMITTING -> REJECTED"""
        self.error_message = reason
        return self.try_transition(ExecState.REJECTED)

    def transition_to_unknown(self) -> bool:
        """SUBMITTING/ACKNOWLEDGED/PARTIALLY_FILLED -> UNKNOWN"""
        return self.try_transition(ExecState.UNKNOWN)

    def transition_to_reconciling(self) -> bool:
        """UNKNOWN -> RECONCILING"""
        return self.try_transition(ExecState.RECONCILING)

    def transition_to_partial_fill(self, filled_qty: int, price: float) -> bool:
        """ACKNOWLEDGED/PARTIALLY_FILLED -> PARTIALLY_FILLED"""
        self._update_fill(filled_qty, price)
        if self.state == ExecState.ACKNOWLEDGED:
            return self.try_transition(ExecState.PARTIALLY_FILLED)
        elif self.state == ExecState.PARTIALLY_FILLED:
            return True
        return False

    def transition_to_filled(self, filled_qty: int, price: float) -> bool:
        """ACKNOWLEDGED/PARTIALLY_FILLED -> FILLED"""
        self._update_fill(filled_qty, price)
        self.remaining_quantity = 0
        self.filled_at = time_provider.format_ts()

        if self.state == ExecState.ACKNOWLEDGED:
            return self.try_transition(ExecState.FILLED)
        elif self.state == ExecState.PARTIALLY_FILLED:
            if self.filled_quantity >= self.quantity:
                return self.try_transition(ExecState.FILLED)
        return False

    def transition_to_cancel_pending(self) -> bool:
        """ACKNOWLEDGED/PARTIALLY_FILLED -> CANCEL_PENDING"""
        return self.try_transition(ExecState.CANCEL_PENDING)

    def transition_to_cancelled(self) -> bool:
        """CANCEL_PENDING -> CANCELLED"""
        self.remaining_quantity = self.quantity - self.filled_quantity
        self.cancelled_at = time_provider.format_ts()
        return self.try_transition(ExecState.CANCELLED)

    def transition_to_failed(self, reason: str) -> bool:
        """Any non-terminal -> FAILED_FINAL"""
        self.error_message = reason
        return self.try_transition(ExecState.FAILED_FINAL)

    def _update_fill(self, filled_qty: int, price: float):
        """Update fill quantities and average price"""
        total_value = (self.average_price * self.filled_quantity) + (price * filled_qty)
        self.filled_quantity += filled_qty
        self.remaining_quantity = max(0, self.quantity - self.filled_quantity)
        self.average_price = total_value / self.filled_quantity if self.filled_quantity > 0 else 0.0

    def can_retry(self) -> bool:
        """Check if order can be retried (only from FAILED_FINAL or REJECTED)"""
        return self.state in [ExecState.FAILED_FINAL, ExecState.REJECTED]

    def is_terminal(self) -> bool:
        """Check if in terminal state"""
        return is_terminal(self.state)

    def is_submitted(self) -> bool:
        """Check if order has been submitted (prevent duplicate placement)"""
        return self.state in [
            ExecState.SUBMITTING,
            ExecState.ACKNOWLEDGED,
            ExecState.PARTIALLY_FILLED,
            ExecState.CANCEL_PENDING,
        ]

    def get_transition_history(self) -> list[dict[str, Any]]:
        """Get full transition history for debugging/replay"""
        return self._transition_history.copy()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for persistence/events"""
        return {
            "intent_id": self.intent_id,
            "client_order_id": self.client_order_id,
            "symbol": self.symbol,
            "quantity": self.quantity,
            "price": self.price,
            "direction": self.direction,
            "state": self.state.value,
            "broker_order_id": self.broker_order_id,
            "filled_quantity": self.filled_quantity,
            "remaining_quantity": self.remaining_quantity,
            "average_price": self.average_price,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "submitted_at": self.submitted_at,
            "acknowledged_at": self.acknowledged_at,
            "filled_at": self.filled_at,
            "cancelled_at": self.cancelled_at,
            "transition_history": self._transition_history,
        }

    def __repr__(self):
        return f"FormalOrderState(id={self.client_order_id}, state={self.state.value}, filled={self.filled_quantity}/{self.quantity})"


class FormalOrderStateManager:
    """
    Manages multiple formal order state machines with persistence.
    Enforces idempotency and strict transition rules.
    """

    PERSISTENCE_PATH = "formal_order_state.db"

    def __init__(self, persistence_callback: Callable | None = None):
        self._machines: dict[str, FormalOrderState] = {}
        self._lock = threading.Lock()
        self._persistence_callback = persistence_callback
        self._init_durable_storage()

    def _init_durable_storage(self) -> None:
        """Initialize SQLite persistence for formal order states"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=5000")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS formal_orders (
                        client_order_id TEXT PRIMARY KEY,
                        intent_id TEXT,
                        symbol TEXT,
                        quantity INTEGER,
                        price REAL,
                        direction TEXT,
                        state TEXT,
                        broker_order_id TEXT,
                        filled_quantity INTEGER,
                        remaining_quantity INTEGER,
                        average_price REAL,
                        error_message TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        submitted_at TEXT,
                        acknowledged_at TEXT,
                        filled_at TEXT,
                        cancelled_at TEXT,
                        transition_history_json TEXT
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_intent ON formal_orders(intent_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_state ON formal_orders(state)")
                conn.commit()
            _log.info("FormalOrderStateManager: Durable storage initialized")
        except (sqlite3.Error, OSError) as e:
            _log.error(f"FormalOrderStateManager: Failed to init storage: {e}")

    def create(
        self,
        intent_id: str,
        symbol: str,
        quantity: int,
        price: float,
        direction: str,
    ) -> FormalOrderState:
        """Create new formal order state"""
        client_order_id = f"OPB-{intent_id}"

        with self._lock:
            if client_order_id in self._machines:
                return self._machines[client_order_id]

            machine = FormalOrderState(
                intent_id=intent_id,
                client_order_id=client_order_id,
                symbol=symbol,
                quantity=quantity,
                price=price,
                direction=direction,
                remaining_quantity=quantity,
            )
            machine._persistence_callback = self._persistence_callback
            self._machines[client_order_id] = machine
            return machine

    def get(self, client_order_id: str) -> FormalOrderState | None:
        """Get existing machine"""
        return self._machines.get(client_order_id)

    def get_or_create(
        self,
        intent_id: str,
        symbol: str,
        quantity: int,
        price: float,
        direction: str,
    ) -> tuple[FormalOrderState, bool]:
        """Get existing or create new (idempotent)"""
        client_order_id = f"OPB-{intent_id}"

        with self._lock:
            if client_order_id in self._machines:
                return self._machines[client_order_id], False

            machine = self.create(intent_id, symbol, quantity, price, direction)
            return machine, True

    def persist(self, machine: FormalOrderState) -> bool:
        """Persist machine state to SQLite"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO formal_orders
                    (client_order_id, intent_id, symbol, quantity, price, direction, state,
                     broker_order_id, filled_quantity, remaining_quantity, average_price,
                     error_message, created_at, updated_at, submitted_at, acknowledged_at,
                     filled_at, cancelled_at, transition_history_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    machine.client_order_id,
                    machine.intent_id,
                    machine.symbol,
                    machine.quantity,
                    machine.price,
                    machine.direction,
                    machine.state.value,
                    machine.broker_order_id,
                    machine.filled_quantity,
                    machine.remaining_quantity,
                    machine.average_price,
                    machine.error_message,
                    machine.created_at,
                    machine.updated_at,
                    machine.submitted_at,
                    machine.acknowledged_at,
                    machine.filled_at,
                    machine.cancelled_at,
                    json.dumps(machine._transition_history),
                ))
                conn.commit()
            return True
        except (sqlite3.Error, OSError, json.JSONDecodeError) as e:
            _log.error(f"Failed to persist machine {machine.client_order_id}: {e}")
            return False

    def load_inflight(self) -> int:
        """Load non-terminal orders from disk on startup"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                cursor = conn.execute("""
                    SELECT client_order_id, intent_id, symbol, quantity, price, direction,
                           state, broker_order_id, filled_quantity, remaining_quantity,
                           average_price, error_message, created_at, updated_at,
                           submitted_at, acknowledged_at, filled_at, cancelled_at
                    FROM formal_orders
                    WHERE state NOT IN ('FILLED', 'CANCELLED', 'REJECTED', 'FAILED_FINAL')
                """)

                count = 0
                for row in cursor:
                    client_order_id = row[0]
                    machine = FormalOrderState(
                        intent_id=row[1],
                        client_order_id=client_order_id,
                        symbol=row[2],
                        quantity=row[3],
                        price=row[4],
                        direction=row[5],
                        state=ExecState(row[6]),
                        broker_order_id=row[7],
                        filled_quantity=row[8],
                        remaining_quantity=row[9],
                        average_price=row[10],
                        error_message=row[11],
                        created_at=row[12],
                        updated_at=row[13],
                        submitted_at=row[14],
                        acknowledged_at=row[15],
                        filled_at=row[16],
                        cancelled_at=row[17],
                    )
                    self._machines[client_order_id] = machine
                    count += 1
                    _log.warning(f"Loaded in-flight order: {client_order_id} in state {machine.state.value}")
                return count
        except (sqlite3.Error, OSError, KeyError, ValueError) as e:
            _log.error(f"Failed to load in-flight orders: {e}")
            return 0


_formal_order_manager: FormalOrderStateManager | None = None
_manager_lock = threading.Lock()


def get_formal_order_manager(persistence_callback: Callable | None = None) -> FormalOrderStateManager:
    """Get singleton formal order state manager"""
    global _formal_order_manager
    with _manager_lock:
        if _formal_order_manager is None:
            _formal_order_manager = FormalOrderStateManager(persistence_callback)
        return _formal_order_manager
