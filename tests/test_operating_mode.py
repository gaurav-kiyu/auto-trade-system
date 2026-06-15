"""Tests for OperatingModeManager — mode transitions and execution gating."""

from __future__ import annotations

import pytest
from datetime import datetime

from core.operating_mode import (
    OperatingMode,
    OperatingModeManager,
    OperatingModeViolationError,
    ExecutionAction,
)


class TestOperatingModeManager:
    """OperatingModeManager — mode transitions and authority checks."""

    def test_default_mode(self):
        mgr = OperatingModeManager()
        assert mgr.current_mode == OperatingMode.SIGNAL_ONLY

    def test_initial_mode(self):
        mgr = OperatingModeManager(initial_mode=OperatingMode.PAPER)
        assert mgr.current_mode == OperatingMode.PAPER

    def test_set_mode_normal(self):
        mgr = OperatingModeManager()
        mgr.set_mode(OperatingMode.PAPER, reason="Testing")
        assert mgr.current_mode == OperatingMode.PAPER

    def test_set_mode_frozen_raises(self):
        mgr = OperatingModeManager()
        mgr.freeze()
        with pytest.raises(OperatingModeViolationError):
            mgr.set_mode(OperatingMode.PAPER)

    def test_full_auto_without_flag_raises(self):
        mgr = OperatingModeManager()
        with pytest.raises(OperatingModeViolationError, match="FULL_AUTO"):
            mgr.set_mode(OperatingMode.FULL_AUTO)

    def test_full_auto_with_flag(self):
        mgr = OperatingModeManager(enable_full_auto=True)
        mgr.set_mode(OperatingMode.FULL_AUTO, reason="Authorized")
        assert mgr.current_mode == OperatingMode.FULL_AUTO

    def test_is_frozen(self):
        mgr = OperatingModeManager()
        assert mgr.is_frozen is False
        mgr.freeze()
        assert mgr.is_frozen is True

    def test_allows_execution_signal_only(self):
        mgr = OperatingModeManager()
        allowed, msg = mgr.allows_execution()
        assert not allowed
        assert "SIGNAL_ONLY" in msg

    def test_allows_execution_paper(self):
        mgr = OperatingModeManager(initial_mode=OperatingMode.PAPER)
        allowed, msg = mgr.allows_execution()
        assert allowed
        assert "PAPER" in msg

    def test_allows_execution_full_auto(self):
        mgr = OperatingModeManager(initial_mode=OperatingMode.FULL_AUTO)
        allowed, msg = mgr.allows_execution()
        assert allowed
        assert "FULL_AUTO" in msg

    def test_allows_live_execution_live_manual(self):
        mgr = OperatingModeManager(initial_mode=OperatingMode.LIVE_MANUAL_CONFIRM)
        allowed, msg = mgr.allows_live_execution()
        assert allowed
        assert "LIVE_MANUAL_CONFIRM" in msg

    def test_allows_live_execution_paper(self):
        mgr = OperatingModeManager(initial_mode=OperatingMode.PAPER)
        allowed, msg = mgr.allows_live_execution()
        assert not allowed

    def test_requires_live_broker_live(self):
        mgr = OperatingModeManager(initial_mode=OperatingMode.LIVE_MANUAL_CONFIRM)
        assert mgr.requires_live_broker() is True

    def test_requires_live_broker_paper(self):
        mgr = OperatingModeManager(initial_mode=OperatingMode.PAPER)
        assert mgr.requires_live_broker() is False

    def test_requires_manual_approval(self):
        mgr = OperatingModeManager(initial_mode=OperatingMode.LIVE_MANUAL_CONFIRM)
        assert mgr.requires_manual_approval() is True

    def test_requires_manual_approval_full_auto(self):
        mgr = OperatingModeManager(initial_mode=OperatingMode.FULL_AUTO)
        assert mgr.requires_manual_approval() is False

    def test_can_perform_submit_order_in_paper(self):
        mgr = OperatingModeManager(initial_mode=OperatingMode.PAPER)
        allowed, msg = mgr.can_perform(ExecutionAction.SUBMIT_ORDER)
        assert allowed

    def test_can_perform_submit_order_in_signal_only(self):
        mgr = OperatingModeManager()
        allowed, msg = mgr.can_perform(ExecutionAction.SUBMIT_ORDER)
        assert not allowed
        assert "SIGNAL_ONLY" in msg

    def test_can_perform_generate_signal_always(self):
        mgr = OperatingModeManager()
        allowed, _ = mgr.can_perform(ExecutionAction.GENERATE_SIGNAL)
        assert allowed

    def test_can_perform_live_live_manual(self):
        mgr = OperatingModeManager(initial_mode=OperatingMode.LIVE_MANUAL_CONFIRM)
        allowed, _ = mgr.can_perform_live(ExecutionAction.SUBMIT_ORDER)
        assert allowed

    def test_can_perform_live_paper(self):
        mgr = OperatingModeManager(initial_mode=OperatingMode.PAPER)
        allowed, msg = mgr.can_perform_live(ExecutionAction.SUBMIT_ORDER)
        assert not allowed

    def test_get_state_structure(self):
        mgr = OperatingModeManager()
        state = mgr.get_state()
        assert "mode" in state
        assert "frozen" in state
        assert "allows_execution" in state
        assert "transition_count" in state
        assert state["mode"] == "SIGNAL_ONLY"

    def test_get_history_records_transitions(self):
        mgr = OperatingModeManager()
        mgr.set_mode(OperatingMode.PAPER, reason="Test")
        history = mgr.get_history()
        assert len(history) == 1
        assert history[0].to_mode == OperatingMode.PAPER
        assert history[0].reason == "Test"
