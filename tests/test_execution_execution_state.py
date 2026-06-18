"""
Tests for core/execution/execution_state.py - Formal Execution State Machine.

NOTE: This module is DEPRECATED in favor of deterministic_state_machine.py.
Tests are kept for backward compatibility with existing code.

Covers:
- ExecState and TransitionResult enums
- is_terminal, is_active helpers
- FormalOrderState (validation, transitions, fill tracking, persistence callback)
- FormalOrderStateManager (create, get, get_or_create, persist, load_inflight)
- Singleton get_formal_order_manager
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from core.execution.execution_state import (
    ExecState,
    FormalOrderState,
    FormalOrderStateManager,
    TransitionResult,
    get_formal_order_manager,
    is_active,
    is_terminal,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def machine():
    """Fresh FormalOrderState in CREATED state."""
    return FormalOrderState(
        intent_id="int-1",
        client_order_id="OPB-int-1",
        symbol="NIFTY",
        quantity=50,
        price=150.0,
        direction="BUY",
        remaining_quantity=50,
    )


@pytest.fixture
def manager(tmp_path):
    """FormalOrderStateManager with isolated temp DB."""
    mgr = FormalOrderStateManager()
    original_path = FormalOrderStateManager.PERSISTENCE_PATH
    FormalOrderStateManager.PERSISTENCE_PATH = str(tmp_path / "test_formal.db")
    mgr._init_durable_storage()
    yield mgr
    FormalOrderStateManager.PERSISTENCE_PATH = original_path


# ── ExecState Enum Tests ──────────────────────────────────────────────────────


class TestExecState:
    """ExecState enum - 12 states covering the full order lifecycle."""

    def test_values(self):
        assert ExecState.CREATED.value == "CREATED"
        assert ExecState.RISK_APPROVED.value == "RISK_APPROVED"
        assert ExecState.SUBMITTING.value == "SUBMITTING"
        assert ExecState.UNKNOWN.value == "UNKNOWN"
        assert ExecState.ACKNOWLEDGED.value == "ACKNOWLEDGED"
        assert ExecState.PARTIALLY_FILLED.value == "PARTIALLY_FILLED"
        assert ExecState.FILLED.value == "FILLED"
        assert ExecState.CANCEL_PENDING.value == "CANCEL_PENDING"
        assert ExecState.CANCELLED.value == "CANCELLED"
        assert ExecState.REJECTED.value == "REJECTED"
        assert ExecState.RECONCILING.value == "RECONCILING"
        assert ExecState.FAILED_FINAL.value == "FAILED_FINAL"


class TestTransitionResult:
    """TransitionResult enum - 4 possible results."""

    def test_values(self):
        assert TransitionResult.SUCCESS.value == "SUCCESS"
        assert TransitionResult.INVALID_TRANSITION.value == "INVALID_TRANSITION"
        assert TransitionResult.ALREADY_IN_STATE.value == "ALREADY_IN_STATE"
        assert TransitionResult.PERSISTENCE_FAILED.value == "PERSISTENCE_FAILED"


# ── Helper Function Tests ─────────────────────────────────────────────────────


class TestHelpers:
    """is_terminal and is_active helper functions."""

    def test_is_terminal_filled(self):
        assert is_terminal(ExecState.FILLED) is True

    def test_is_terminal_cancelled(self):
        assert is_terminal(ExecState.CANCELLED) is True

    def test_is_terminal_rejected(self):
        assert is_terminal(ExecState.REJECTED) is True

    def test_is_terminal_failed_final(self):
        assert is_terminal(ExecState.FAILED_FINAL) is True

    def test_is_terminal_created(self):
        assert is_terminal(ExecState.CREATED) is False

    def test_is_terminal_acknowledged(self):
        assert is_terminal(ExecState.ACKNOWLEDGED) is False

    def test_is_active_non_terminal(self):
        assert is_active(ExecState.CREATED) is True

    def test_is_active_terminal(self):
        assert is_active(ExecState.FILLED) is False


# ── Transition Validation Tests ───────────────────────────────────────────────


class TestValidateTransition:
    """FormalOrderState.validate_transition - strict transition rules."""

    def test_created_to_risk_approved(self, machine):
        result, msg = machine.validate_transition(ExecState.RISK_APPROVED)
        assert result == TransitionResult.SUCCESS

    def test_created_to_failed_final(self, machine):
        result, msg = machine.validate_transition(ExecState.FAILED_FINAL)
        assert result == TransitionResult.SUCCESS

    def test_created_to_filled_invalid(self, machine):
        """CREATED -> FILLED is not a valid direct transition."""
        result, msg = machine.validate_transition(ExecState.FILLED)
        assert result == TransitionResult.INVALID_TRANSITION

    def test_already_in_state(self, machine):
        result, msg = machine.validate_transition(ExecState.CREATED)
        assert result == TransitionResult.ALREADY_IN_STATE

    def test_full_lifecycle_valid(self, machine):
        """Validate a full happy-path lifecycle."""
        assert machine.validate_transition(ExecState.RISK_APPROVED)[0] == TransitionResult.SUCCESS
        machine.state = ExecState.RISK_APPROVED
        assert machine.validate_transition(ExecState.SUBMITTING)[0] == TransitionResult.SUCCESS
        machine.state = ExecState.SUBMITTING
        assert machine.validate_transition(ExecState.ACKNOWLEDGED)[0] == TransitionResult.SUCCESS
        machine.state = ExecState.ACKNOWLEDGED
        assert machine.validate_transition(ExecState.FILLED)[0] == TransitionResult.SUCCESS

    def test_partial_fill_valid(self, machine):
        """ACKNOWLEDGED -> PARTIALLY_FILLED is valid."""
        machine.state = ExecState.ACKNOWLEDGED
        result, msg = machine.validate_transition(ExecState.PARTIALLY_FILLED)
        assert result == TransitionResult.SUCCESS

    def test_cancel_pending_from_acknowledged(self, machine):
        """ACKNOWLEDGED -> CANCEL_PENDING is valid."""
        machine.state = ExecState.ACKNOWLEDGED
        assert machine.validate_transition(ExecState.CANCEL_PENDING)[0] == TransitionResult.SUCCESS

    def test_reconciling_from_unknown(self, machine):
        """UNKNOWN -> RECONCILING is valid."""
        machine.state = ExecState.UNKNOWN
        assert machine.validate_transition(ExecState.RECONCILING)[0] == TransitionResult.SUCCESS

    def test_terminal_no_transitions(self, machine):
        """Terminal states should have no valid outgoing transitions."""
        machine.state = ExecState.FILLED
        for state in ExecState:
            if state != ExecState.FILLED:
                result, _ = machine.validate_transition(state)
                assert result == TransitionResult.INVALID_TRANSITION


# ── Named Transition Method Tests ─────────────────────────────────────────────


class TestNamedTransitions:
    """Named transition convenience methods."""

    def test_transition_to_risk_approved(self, machine):
        assert machine.transition_to_risk_approved() is True
        assert machine.state == ExecState.RISK_APPROVED

    def test_transition_to_submitting(self, machine):
        machine.state = ExecState.RISK_APPROVED
        assert machine.transition_to_submitting() is True
        assert machine.state == ExecState.SUBMITTING

    def test_transition_to_acknowledged(self, machine):
        machine.state = ExecState.SUBMITTING
        assert machine.transition_to_acknowledged("brk-123") is True
        assert machine.state == ExecState.ACKNOWLEDGED
        assert machine.broker_order_id == "brk-123"
        assert machine.submitted_at is not None

    def test_transition_to_rejected(self, machine):
        machine.state = ExecState.SUBMITTING
        assert machine.transition_to_rejected("insufficient funds") is True
        assert machine.state == ExecState.REJECTED
        assert machine.error_message == "insufficient funds"

    def test_transition_to_unknown(self, machine):
        machine.state = ExecState.SUBMITTING
        assert machine.transition_to_unknown() is True
        assert machine.state == ExecState.UNKNOWN

    def test_transition_to_reconciling(self, machine):
        machine.state = ExecState.UNKNOWN
        assert machine.transition_to_reconciling() is True
        assert machine.state == ExecState.RECONCILING

    def test_transition_to_partial_fill_from_acknowledged(self, machine):
        machine.state = ExecState.ACKNOWLEDGED
        assert machine.transition_to_partial_fill(25, 150.0) is True
        assert machine.state == ExecState.PARTIALLY_FILLED
        assert machine.filled_quantity == 25

    def test_transition_to_partial_fill_from_partial(self, machine):
        """PARTIALLY_FILLED -> PARTIALLY_FILLED should succeed (accumulate)."""
        machine.state = ExecState.PARTIALLY_FILLED
        machine.filled_quantity = 25
        assert machine.transition_to_partial_fill(15, 152.0) is True
        assert machine.state == ExecState.PARTIALLY_FILLED
        assert machine.filled_quantity == 40

    def test_transition_to_filled_from_acknowledged(self, machine):
        machine.state = ExecState.ACKNOWLEDGED
        assert machine.transition_to_filled(50, 151.0) is True
        assert machine.state == ExecState.FILLED
        assert machine.remaining_quantity == 0
        assert machine.filled_at is not None

    def test_transition_to_filled_from_partial(self, machine):
        """PARTIALLY_FILLED -> FILLED when full quantity reached."""
        machine.state = ExecState.PARTIALLY_FILLED
        machine.filled_quantity = 25
        machine.average_price = 150.0  # First fill at 150.0
        assert machine.transition_to_filled(25, 152.0) is True
        assert machine.state == ExecState.FILLED
        assert machine.filled_quantity == 50
        assert machine.average_price == 151.0  # (25*150 + 25*152) / 50

    def test_transition_to_cancel_pending(self, machine):
        machine.state = ExecState.ACKNOWLEDGED
        assert machine.transition_to_cancel_pending() is True
        assert machine.state == ExecState.CANCEL_PENDING

    def test_transition_to_cancelled(self, machine):
        machine.state = ExecState.CANCEL_PENDING
        assert machine.transition_to_cancelled() is True
        assert machine.state == ExecState.CANCELLED
        assert machine.cancelled_at is not None

    def test_transition_to_failed(self, machine):
        assert machine.transition_to_failed("system crash") is True
        assert machine.state == ExecState.FAILED_FINAL
        assert machine.error_message == "system crash"

    def test_transition_to_acknowledged_wrong_state(self, machine):
        """transition_to_acknowledged should fail if not in SUBMITTING."""
        assert machine.transition_to_acknowledged("brk-1") is False

    def test_transition_to_filled_wrong_state(self, machine):
        """transition_to_filled should fail from wrong state."""
        assert machine.transition_to_filled(50, 150.0) is False


# ── Fill Tracking Tests ───────────────────────────────────────────────────────


class TestFillTracking:
    """Fill quantity and average price tracking."""

    def test_fill_updates_remaining(self, machine):
        machine.filled_quantity = 25
        machine.state = ExecState.PARTIALLY_FILLED
        machine.transition_to_filled(25, 150.0)
        assert machine.remaining_quantity == 0

    def test_weighted_average_price(self, machine):
        machine.filled_quantity = 10
        machine.average_price = 100.0
        machine.state = ExecState.PARTIALLY_FILLED
        machine.transition_to_filled(20, 110.0)
        expected = (10 * 100.0 + 20 * 110.0) / 30
        assert machine.average_price == expected


# ── Query Method Tests ────────────────────────────────────────────────────────


class TestQueryMethods:
    """can_retry, is_terminal, is_submitted, get_transition_history."""

    def test_can_retry_from_failed(self, machine):
        machine.state = ExecState.FAILED_FINAL
        assert machine.can_retry() is True

    def test_can_retry_from_rejected(self, machine):
        machine.state = ExecState.REJECTED
        assert machine.can_retry() is True

    def test_can_retry_from_created(self, machine):
        assert machine.can_retry() is False

    def test_is_terminal_filled(self, machine):
        machine.state = ExecState.FILLED
        assert machine.is_terminal() is True

    def test_is_terminal_created(self, machine):
        assert machine.is_terminal() is False

    def test_is_submitted_submitting(self, machine):
        machine.state = ExecState.SUBMITTING
        assert machine.is_submitted() is True

    def test_is_submitted_created(self, machine):
        assert machine.is_submitted() is False

    def test_get_transition_history(self, machine):
        machine.validate_transition(ExecState.RISK_APPROVED)
        machine.state = ExecState.RISK_APPROVED  # simulate success
        history = machine.get_transition_history()
        assert len(history) >= 1
        assert history[0]["from"] == "CREATED"
        assert history[0]["to"] == "RISK_APPROVED"


# ── Persistence Callback Tests ────────────────────────────────────────────────


class TestPersistenceCallback:
    """Persistence callback on critical transitions."""

    def test_callback_called_on_risk_approved(self, machine):
        callback = MagicMock()
        machine._persistence_callback = callback
        machine.validate_transition(ExecState.RISK_APPROVED)
        callback.assert_called_once()

    def test_persistence_failure_blocks_transition(self, machine):
        callback = MagicMock(side_effect=sqlite3.Error("disk full"))
        machine._persistence_callback = callback
        result, msg = machine.validate_transition(ExecState.RISK_APPROVED)
        assert result == TransitionResult.PERSISTENCE_FAILED


# ── Serialization Tests ───────────────────────────────────────────────────────


class TestToDict:
    """FormalOrderState.to_dict serialization."""

    def test_to_dict_includes_all_fields(self, machine):
        d = machine.to_dict()
        assert d["intent_id"] == "int-1"
        assert d["client_order_id"] == "OPB-int-1"
        assert d["state"] == "CREATED"
        assert d["filled_quantity"] == 0
        assert d["transition_history"] == []


# ── FormalOrderStateManager Tests ─────────────────────────────────────────────


class TestFormalOrderStateManager:
    """FormalOrderStateManager - manages multiple order state machines."""

    def test_create_simple(self, manager):
        machine = manager.create("int-1", "NIFTY", 50, 150.0, "BUY")
        assert machine.client_order_id == "OPB-int-1"
        assert machine.state == ExecState.CREATED

    def test_create_duplicate_returns_same(self, manager):
        m1 = manager.create("int-1", "NIFTY", 50, 150.0, "BUY")
        m2 = manager.create("int-1", "NIFTY", 50, 150.0, "BUY")
        assert m1 is m2

    def test_get_existing(self, manager):
        manager.create("int-1", "NIFTY", 50, 150.0, "BUY")
        machine = manager.get("OPB-int-1")
        assert machine is not None
        assert machine.intent_id == "int-1"

    def test_get_nonexistent(self, manager):
        machine = manager.get("OPB-nonexistent")
        assert machine is None

    def test_get_or_create_new(self, manager):
        machine, created = manager.get_or_create("int-1", "NIFTY", 50, 150.0, "BUY")
        assert created is True
        assert machine.state == ExecState.CREATED

    def test_get_or_create_existing(self, manager):
        manager.create("int-1", "NIFTY", 50, 150.0, "BUY")
        machine, created = manager.get_or_create("int-1", "NIFTY", 50, 150.0, "BUY")
        assert created is False

    def test_persist_machine(self, manager):
        machine = manager.create("int-1", "NIFTY", 50, 150.0, "BUY")
        result = manager.persist(machine)
        assert result is True

        # Verify in DB
        with sqlite3.connect(FormalOrderStateManager.PERSISTENCE_PATH) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM formal_orders")
            assert cursor.fetchone()[0] == 1

    def test_persist_and_load_inflight(self, manager):
        machine = manager.create("int-1", "NIFTY", 50, 150.0, "BUY")
        manager.persist(machine)

        # Create second manager and load in-flight
        mgr2 = FormalOrderStateManager()
        count = mgr2.load_inflight()
        assert count == 1
        loaded = mgr2.get("OPB-int-1")
        assert loaded is not None
        assert loaded.intent_id == "int-1"

    def test_load_inflight_skips_terminal(self, manager):
        m1 = manager.create("int-1", "NIFTY", 50, 150.0, "BUY")
        m1.state = ExecState.FILLED
        manager.persist(m1)

        m2 = manager.create("int-2", "BANKNIFTY", 25, 300.0, "SELL")
        manager.persist(m2)

        mgr2 = FormalOrderStateManager()
        count = mgr2.load_inflight()
        assert count == 1
        assert mgr2.get("OPB-int-2") is not None

    def test_persist_failure_returns_false(self, manager):
        machine = manager.create("int-1", "NIFTY", 50, 150.0, "BUY")
        with patch.object(sqlite3, "connect", side_effect=sqlite3.Error("mock")):
            result = manager.persist(machine)
            assert result is False

    def test_init_creates_table(self, manager):
        with sqlite3.connect(FormalOrderStateManager.PERSISTENCE_PATH) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='formal_orders'"
            )
            assert cursor.fetchone() is not None


# ── Singleton Tests ───────────────────────────────────────────────────────────


class TestSingleton:
    """Module-level singleton get_formal_order_manager."""

    def test_returns_manager(self):
        mgr = get_formal_order_manager()
        assert isinstance(mgr, FormalOrderStateManager)

    def test_singleton_identity(self):
        mgr1 = get_formal_order_manager()
        mgr2 = get_formal_order_manager()
        assert mgr1 is mgr2
