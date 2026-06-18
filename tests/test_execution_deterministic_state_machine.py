"""Tests for core/execution/deterministic_state_machine.py - State Machine."""

from __future__ import annotations

from unittest.mock import MagicMock


from core.execution.deterministic_state_machine import (
    ExecutionState,
    ExecutionStateMachine,
    ExecutionStateMachineManager,
    TransitionResult,
    VALID_TRANSITIONS,
    get_execution_state_manager,
)


def make_machine(**overrides) -> ExecutionStateMachine:
    """Helper to create a state machine with sensible defaults."""
    params = {
        "intent_id": "intent_001",
        "client_order_id": "OPB-intent_001",
        "symbol": "NIFTY",
        "quantity": 50,
        "price": 23500.0,
        "direction": "BUY",
    }
    params.update(overrides)
    return ExecutionStateMachine(**params)


class TestExecutionState:
    """ExecutionState enum coverage."""

    def test_has_all_states(self):
        assert ExecutionState.INIT.value == "INIT"
        assert ExecutionState.PENDING_SUBMISSION.value == "PENDING_SUBMISSION"
        assert ExecutionState.VALIDATED.value == "VALIDATED"
        assert ExecutionState.PERSISTED.value == "PERSISTED"
        assert ExecutionState.SUBMITTED.value == "SUBMITTED"
        assert ExecutionState.ACKNOWLEDGED.value == "ACKNOWLEDGED"
        assert ExecutionState.PARTIAL_FILL.value == "PARTIAL_FILL"
        assert ExecutionState.FILLED.value == "FILLED"
        assert ExecutionState.REJECTED.value == "REJECTED"
        assert ExecutionState.CANCEL_PENDING.value == "CANCEL_PENDING"
        assert ExecutionState.CANCELLED.value == "CANCELLED"
        assert ExecutionState.FAILED.value == "FAILED"
        assert ExecutionState.UNKNOWN.value == "UNKNOWN"
        assert ExecutionState.RECONCILING.value == "RECONCILING"

    def test_terminal_states_have_no_transitions(self):
        terminal = [ExecutionState.FILLED, ExecutionState.REJECTED,
                    ExecutionState.CANCELLED, ExecutionState.FAILED]
        for s in terminal:
            assert VALID_TRANSITIONS[s] == []


class TestTransitionResult:
    """TransitionResult enum coverage."""

    def test_has_all_results(self):
        assert TransitionResult.SUCCESS.value == "SUCCESS"
        assert TransitionResult.INVALID_TRANSITION.value == "INVALID_TRANSITION"
        assert TransitionResult.ALREADY_IN_STATE.value == "ALREADY_IN_STATE"
        assert TransitionResult.PERSISTENCE_FAILED.value == "PERSISTENCE_FAILED"


class TestExecutionStateMachine:
    """ExecutionStateMachine coverage."""

    def test_initial_state(self):
        m = make_machine()
        assert m.state == ExecutionState.INIT
        assert m.filled_quantity == 0
        assert m.average_price == 0.0

    def test_valid_transition(self):
        m = make_machine()
        result, reason = m.validate_transition(ExecutionState.VALIDATED)
        assert result == TransitionResult.SUCCESS
        assert m.state == ExecutionState.VALIDATED

    def test_invalid_transition(self):
        m = make_machine()
        # Can't go from INIT to FILLED directly
        result, reason = m.validate_transition(ExecutionState.FILLED)
        assert result == TransitionResult.INVALID_TRANSITION
        assert m.state == ExecutionState.INIT

    def test_already_in_state(self):
        m = make_machine()
        m.state = ExecutionState.VALIDATED
        result, reason = m.validate_transition(ExecutionState.VALIDATED)
        assert result == TransitionResult.ALREADY_IN_STATE

    def test_full_lifecycle(self):
        m = make_machine()
        assert m.try_transition_to(ExecutionState.VALIDATED)
        assert m.try_transition_to(ExecutionState.PERSISTED)
        assert m.record_submission("BROKER_ORD_001")
        assert m.state == ExecutionState.SUBMITTED
        assert m.broker_order_id == "BROKER_ORD_001"
        assert m.record_acknowledgment()
        assert m.state == ExecutionState.ACKNOWLEDGED
        assert m.record_fill(50, 23500.0)
        assert m.state == ExecutionState.FILLED

    def test_full_lifecycle_partial_fill(self):
        m = make_machine()
        assert m.try_transition_to(ExecutionState.VALIDATED)
        assert m.try_transition_to(ExecutionState.PERSISTED)
        assert m.record_submission("BROKER_ORD_002")
        assert m.record_acknowledgment()
        assert m.record_fill(25, 23500.0)
        assert m.state == ExecutionState.PARTIAL_FILL
        assert m.filled_quantity == 25
        # Second partial fill to complete
        assert m.record_fill(25, 23500.0)
        assert m.state == ExecutionState.FILLED
        assert m.filled_quantity == 50

    def test_partial_fill_weighted_average_price(self):
        m = make_machine()
        m.try_transition_to(ExecutionState.VALIDATED)
        m.try_transition_to(ExecutionState.PERSISTED)
        m.record_submission("BROKER_ORD_003")
        m.record_acknowledgment()
        m.record_fill(25, 23400.0)
        m.record_fill(25, 23600.0)
        assert m.filled_quantity == 50
        # Weighted avg = (25*23400 + 25*23600) / 50 = 23500
        assert m.average_price == 23500.0

    def test_record_submission_wrong_state(self):
        m = make_machine()
        # Must be in PERSISTED state
        result = m.record_submission("BROKER_ORD_004")
        assert result is False

    def test_record_acknowledgment_wrong_state(self):
        m = make_machine()
        result = m.record_acknowledgment()
        assert result is False

    def test_record_rejection(self):
        m = make_machine()
        m.try_transition_to(ExecutionState.VALIDATED)
        m.try_transition_to(ExecutionState.PERSISTED)
        m.record_submission("BROKER_ORD_005")
        assert m.record_rejection("Insufficient margin")
        assert m.state == ExecutionState.REJECTED
        assert m.error_message == "Insufficient margin"

    def test_record_failure(self):
        m = make_machine()
        m.try_transition_to(ExecutionState.VALIDATED)
        m.record_failure("Network error")
        assert m.state == ExecutionState.FAILED
        assert m.error_message == "Network error"

    def test_can_retry(self):
        m = make_machine()
        m.state = ExecutionState.FAILED
        assert m.can_retry()
        m.state = ExecutionState.REJECTED
        assert m.can_retry()
        m.state = ExecutionState.FILLED
        assert not m.can_retry()

    def test_is_terminal(self):
        m = make_machine()
        assert not m.is_terminal()
        m.state = ExecutionState.FILLED
        assert m.is_terminal()
        m.state = ExecutionState.REJECTED
        assert m.is_terminal()
        m.state = ExecutionState.CANCELLED
        assert m.is_terminal()
        m.state = ExecutionState.FAILED
        assert m.is_terminal()

    def test_is_submitted(self):
        m = make_machine()
        assert not m.is_submitted()
        m.state = ExecutionState.SUBMITTED
        assert m.is_submitted()
        m.state = ExecutionState.ACKNOWLEDGED
        assert m.is_submitted()

    def test_persistence_callback_called(self):
        callback = MagicMock()
        m = make_machine()
        m._persistence_callback = callback
        m.try_transition_to(ExecutionState.VALIDATED)
        # VALIDATED is NOT in the persistence callback list
        callback.assert_not_called()
        m.try_transition_to(ExecutionState.PERSISTED)
        callback.assert_called_once_with(m)

    def test_persistence_callback_reverts_on_failure(self):
        def failing_callback(machine):
            raise RuntimeError("DB failure")

        m = make_machine()
        m.state = ExecutionState.VALIDATED
        m._persistence_callback = failing_callback
        result, reason = m.validate_transition(ExecutionState.PERSISTED)
        assert result == TransitionResult.PERSISTENCE_FAILED
        assert m.state == ExecutionState.VALIDATED  # Reverted

    def test_repr(self):
        m = make_machine()
        r = repr(m)
        assert "OPB-intent_001" in r
        assert "INIT" in r

    def test_record_partial_fill_delegates(self):
        m = make_machine()
        m.try_transition_to(ExecutionState.VALIDATED)
        m.try_transition_to(ExecutionState.PERSISTED)
        m.record_submission("BROKER_ORD_006")
        m.record_acknowledgment()
        assert m.record_partial_fill(25, 23500.0)
        assert m.filled_quantity == 25


class TestExecutionStateMachineManager:
    """ExecutionStateMachineManager coverage."""

    def test_create_new_machine(self):
        mgr = ExecutionStateMachineManager()
        machine, is_new = mgr.create_or_get(
            "intent_101", "NIFTY", 50, 23500.0, "BUY",
        )
        assert is_new
        assert machine.client_order_id == "OPB-intent_101"
        assert machine.state == ExecutionState.INIT

    def test_get_existing_machine(self):
        mgr = ExecutionStateMachineManager()
        m1, _ = mgr.create_or_get("intent_102", "NIFTY", 50, 23500.0, "BUY")
        m2, is_new = mgr.create_or_get("intent_102", "NIFTY", 50, 23500.0, "BUY")
        assert not is_new
        assert m1 is m2

    def test_get_machine_by_id(self):
        mgr = ExecutionStateMachineManager()
        m1, _ = mgr.create_or_get("intent_103", "NIFTY", 50, 23500.0, "BUY")
        m2 = mgr.get_machine("OPB-intent_103")
        assert m1 is m2

    def test_get_machine_unknown(self):
        mgr = ExecutionStateMachineManager()
        assert mgr.get_machine("unknown") is None

    def test_get_all_empty(self):
        mgr = ExecutionStateMachineManager()
        assert mgr.get_all() == []

    def test_get_all_with_machines(self):
        mgr = ExecutionStateMachineManager()
        mgr.create_or_get("intent_104", "NIFTY", 50, 23500.0, "BUY")
        mgr.create_or_get("intent_105", "BANKNIFTY", 30, 50000.0, "SELL")
        all_m = mgr.get_all()
        assert len(all_m) == 2

    def test_prune_terminals(self):
        mgr = ExecutionStateMachineManager()
        m1, _ = mgr.create_or_get("intent_106", "NIFTY", 50, 23500.0, "BUY")
        m2, _ = mgr.create_or_get("intent_107", "BANKNIFTY", 30, 50000.0, "SELL")
        # Mark both as terminal and set created_at to match strptime format
        m1.state = ExecutionState.FILLED
        m2.state = ExecutionState.REJECTED
        # Set created_at well in the past so prune works
        m1.created_at = "Thu Jun 10 12:00:00 2026"  # Match strptime default format
        m2.created_at = "Thu Jun 10 12:00:00 2026"
        # Prune with 0 max age to force removal
        removed = mgr.prune_terminals(max_age_hours=0)
        assert removed == 2
        assert mgr.get_all() == []

    def test_prune_skips_non_terminal(self):
        mgr = ExecutionStateMachineManager()
        m1, _ = mgr.create_or_get("intent_108", "NIFTY", 50, 23500.0, "BUY")
        m2, _ = mgr.create_or_get("intent_109", "BANKNIFTY", 30, 50000.0, "SELL")
        m1.state = ExecutionState.FILLED  # Terminal
        m1.created_at = "Thu Jun 10 12:00:00 2026"  # Match strptime default format
        # m2 stays in INIT (non-terminal)
        removed = mgr.prune_terminals(max_age_hours=0)
        assert removed == 1
        assert len(mgr.get_all()) == 1

    def test_record_broker_query_result_unexpected(self):
        mgr = ExecutionStateMachineManager()
        result = mgr.record_broker_query_result("unknown", "BROKER_ORD", "FILLED")
        assert result is False

    def test_record_broker_query_result_filled(self):
        mgr = ExecutionStateMachineManager()
        m, _ = mgr.create_or_get("intent_110", "NIFTY", 50, 23500.0, "BUY")
        m.state = ExecutionState.ACKNOWLEDGED
        m.broker_order_id = "BROKER_ORD_110"
        result = mgr.record_broker_query_result(
            "OPB-intent_110", "BROKER_ORD_110", "FILLED", 50, 23500.0,
        )
        assert result is True

    def test_recover_from_store_no_store(self):
        mgr = ExecutionStateMachineManager()
        count = mgr.recover_from_store(None)
        assert count == 0

    def test_recover_from_store_empty_store(self):
        mgr = ExecutionStateMachineManager()
        store = MagicMock()
        store.get_non_terminal_executions.return_value = []
        count = mgr.recover_from_store(store)
        assert count == 0

    def test_recover_from_store_exception(self):
        mgr = ExecutionStateMachineManager()
        store = MagicMock()
        store.get_non_terminal_executions.side_effect = RuntimeError("Store error")
        count = mgr.recover_from_store(store)
        assert count == 0


class TestGetStateManager:
    """Singleton get_execution_state_manager coverage."""

    def test_get_default(self):
        mgr = get_execution_state_manager()
        assert isinstance(mgr, ExecutionStateMachineManager)

    def test_singleton_behavior(self):
        mgr1 = get_execution_state_manager()
        mgr2 = get_execution_state_manager()
        assert mgr1 is mgr2
