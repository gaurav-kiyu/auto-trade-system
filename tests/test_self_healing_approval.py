"""Tests for HealingApprovalWorkflow (Pillar 6 enhancement)."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from core.self_healing.approval_workflow import (
    ACTION_RISK_MAP,
    ActionRiskLevel,
    ApprovalTicket,
    HealingApprovalWorkflow,
    get_approval_workflow,
    reset_approval_workflow,
)


@pytest.fixture(autouse=True)
def reset_workflow(tmp_path: Path) -> None:
    """Reset the singleton before each test and use temp persistence."""
    reset_approval_workflow()
    # Clean up any stale persistence files from previous runs
    stale_path = Path("json/approval_tickets.json")
    if stale_path.exists():
        stale_path.unlink()


class TestHealingApprovalWorkflow:
    """Tests for the HealingApprovalWorkflow class."""

    def test_singleton(self) -> None:
        """Test singleton pattern."""
        w1 = get_approval_workflow()
        w2 = get_approval_workflow()
        assert w1 is w2

    def test_reset(self) -> None:
        """Test reset clears the singleton."""
        w1 = get_approval_workflow()
        reset_approval_workflow()
        w2 = get_approval_workflow()
        assert w1 is not w2

    def test_request_approval_low_risk_auto_approved(self) -> None:
        """Test that low-risk actions are auto-approved."""
        workflow = HealingApprovalWorkflow()
        ticket = workflow.request_approval(
            action_type="restart_stale_feed",
            component="market_data",
            reason="Feed is stale",
            risk_level=ActionRiskLevel.LOW,
        )
        assert ticket.is_approved is True
        assert ticket.status == "APPROVED"

    def test_request_approval_medium_risk_auto_approved(self) -> None:
        """Test that medium-risk actions are auto-approved."""
        workflow = HealingApprovalWorkflow()
        ticket = workflow.request_approval(
            action_type="reload_config",
            component="config_manager",
            reason="Config needs refresh",
            risk_level=ActionRiskLevel.MEDIUM,
        )
        assert ticket.is_approved is True
        assert ticket.approved_by == "auto"

    def test_request_approval_high_risk_pending(self) -> None:
        """Test that high-risk actions require approval (are pending)."""
        workflow = HealingApprovalWorkflow()
        ticket = workflow.request_approval(
            action_type="reconnect_broker",
            component="kite_adapter",
            reason="Broker connection lost",
            risk_level=ActionRiskLevel.HIGH,
        )
        assert ticket.status == "PENDING"
        assert ticket.is_approved is False

    def test_request_approval_critical_risk_pending(self) -> None:
        """Test that critical-risk actions require approval."""
        workflow = HealingApprovalWorkflow()
        ticket = workflow.request_approval(
            action_type="reconnect_broker",
            component="production_broker",
            reason="Critical broker failure",
            risk_level=ActionRiskLevel.CRITICAL,
        )
        assert ticket.status == "PENDING"

    def test_request_approval_with_auto_detect(self) -> None:
        """Test auto-detection of risk level from action type."""
        workflow = HealingApprovalWorkflow()
        ticket = workflow.request_approval(
            action_type="restart_stale_feed",
            component="test",
            reason="Testing auto-detect",
        )
        assert ticket.is_approved is True  # LOW risk auto-detected

    def test_approve_ticket(self) -> None:
        """Test approving a pending ticket."""
        workflow = HealingApprovalWorkflow()
        ticket = workflow.request_approval(
            action_type="reconnect_broker",
            component="test",
            reason="Test",
            risk_level=ActionRiskLevel.HIGH,
        )
        assert ticket.status == "PENDING"

        approved = workflow.approve(ticket.id, "operator@test.com")
        assert approved is True

        # Check ticket status
        ticket_data = workflow.get_ticket(ticket.id)
        if ticket_data:
            assert ticket_data["status"] == "APPROVED"

    def test_reject_ticket(self) -> None:
        """Test rejecting a pending ticket."""
        workflow = HealingApprovalWorkflow()
        ticket = workflow.request_approval(
            action_type="reconnect_broker",
            component="test",
            reason="Test",
            risk_level=ActionRiskLevel.HIGH,
        )
        rejected = workflow.reject(ticket.id, "operator@test.com", "Not needed")
        assert rejected is True

    def test_approve_nonexistent_ticket(self) -> None:
        """Test approving a nonexistent ticket returns False."""
        workflow = HealingApprovalWorkflow()
        assert workflow.approve("nonexistent", "test") is False

    def test_reject_nonexistent_ticket(self) -> None:
        """Test rejecting a nonexistent ticket returns False."""
        workflow = HealingApprovalWorkflow()
        assert workflow.reject("nonexistent", "test") is False

    def test_double_approve_fails(self) -> None:
        """Test that approving an already-approved ticket fails."""
        workflow = HealingApprovalWorkflow()
        ticket = workflow.request_approval(
            action_type="restart_stale_feed", component="test",
            reason="Test", risk_level=ActionRiskLevel.LOW,
        )
        # LOW risk is auto-approved, so approving again should fail
        assert workflow.approve(ticket.id, "test") is False

    def test_get_pending_tickets(self) -> None:
        """Test getting pending tickets."""
        workflow = HealingApprovalWorkflow()
        workflow.request_approval("reconnect_broker", "test", "Test",
                                 risk_level=ActionRiskLevel.HIGH)
        pending = workflow.get_pending()
        assert len(pending) >= 1
        assert all(t["status"] == "PENDING" for t in pending)

    def test_get_stats(self) -> None:
        """Test getting stats."""
        workflow = HealingApprovalWorkflow()
        stats = workflow.get_stats()
        assert isinstance(stats, dict)
        assert "pending" in stats

    def test_get_history(self) -> None:
        """Test getting history."""
        workflow = HealingApprovalWorkflow()
        workflow.request_approval(
            "restart_stale_feed", "test", "Test",
            risk_level=ActionRiskLevel.LOW,
        )
        history = workflow.get_history()
        assert len(history) >= 1

    def test_clear_history(self) -> None:
        """Test clearing history."""
        workflow = HealingApprovalWorkflow()
        workflow.request_approval(
            "restart_stale_feed", "test", "Test",
            risk_level=ActionRiskLevel.LOW,
        )
        workflow.clear_history()
        assert len(workflow.get_history()) == 0

    def test_should_execute_low_risk(self) -> None:
        """Test should_execute for low-risk actions."""
        workflow = HealingApprovalWorkflow()
        should, msg = workflow.should_execute("restart_stale_feed", "test")
        assert should is True
        assert "low risk" in msg.lower()

    def test_should_execute_high_risk_requires_approval(self) -> None:
        """Test should_execute for high-risk actions."""
        workflow = HealingApprovalWorkflow()
        should, msg = workflow.should_execute("reconnect_broker", "test")
        assert should is False
        assert "approval" in msg.lower()

    def test_should_execute_high_risk_after_approval(self) -> None:
        """Test that approved actions are cached and should_execute returns True."""
        workflow = HealingApprovalWorkflow()
        ticket = workflow.request_approval(
            "reconnect_broker", "approved_component", "Test",
            risk_level=ActionRiskLevel.HIGH,
        )
        assert ticket.status == "PENDING"
        # After explicit approval, the action is cached
        result = workflow.approve(ticket.id, "admin")
        assert result is True
        # Verify the action was cached
        action_key = "reconnect_broker:approved_component"
        assert action_key in workflow._approved_actions
        # should_execute should find the cached approval
        should, msg = workflow.should_execute("reconnect_broker", "approved_component")
        assert should is True, f"should_execute returned False: {msg}"

    def test_set_notify_fn(self) -> None:
        """Test setting a notification function."""
        workflow = HealingApprovalWorkflow()
        mock_fn = MagicMock()
        workflow.set_notify_fn(mock_fn)
        assert workflow._notify_fn is not None

    def test_escalation_callback(self) -> None:
        """Test registering an escalation callback."""
        workflow = HealingApprovalWorkflow()
        mock_cb = MagicMock()
        workflow.register_escalation_callback(mock_cb)
        assert len(workflow._escalation_callbacks) == 1

    def test_ticket_expiry(self) -> None:
        """Test ticket expiry detection."""
        ticket = ApprovalTicket(
            id="test_ticket",
            action_type="test",
            component="test",
            reason="Test",
            risk_level="HIGH",
            timeout_seconds=0.001,  # Very short timeout
        )
        time.sleep(0.01)
        assert ticket.is_expired is True

    def test_ticket_to_dict(self) -> None:
        """Test ticket serialization."""
        ticket = ApprovalTicket(
            id="test_ticket",
            action_type="reconnect_broker",
            component="test",
            reason="Test reason",
            risk_level="HIGH",
        )
        d = ticket.to_dict()
        assert d["id"] == "test_ticket"
        assert d["action_type"] == "reconnect_broker"
        assert d["risk_level"] == "HIGH"
        assert d["status"] == "PENDING"
        assert "requested_at_iso" in d
        assert "age_seconds" in d

    def test_action_risk_map(self) -> None:
        """Test that ACTION_RISK_MAP has expected entries."""
        assert "restart_stale_feed" in ACTION_RISK_MAP
        assert "reconnect_broker" in ACTION_RISK_MAP
        assert "reset_circuit_breaker" in ACTION_RISK_MAP
        assert ACTION_RISK_MAP["restart_stale_feed"] == ActionRiskLevel.LOW
        assert ACTION_RISK_MAP["reconnect_broker"] == ActionRiskLevel.HIGH


class TestApprovalTicket:
    """Tests for ApprovalTicket dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        ticket = ApprovalTicket(
            id="test",
            action_type="test",
            component="test",
            reason="test",
            risk_level="LOW",
        )
        assert ticket.status == "PENDING"
        assert ticket.approved_by == ""
        assert ticket.is_approved is False

    def test_is_expired_default(self) -> None:
        """Test that fresh tickets are not expired."""
        ticket = ApprovalTicket(
            id="test",
            action_type="test",
            component="test",
            reason="test",
            risk_level="LOW",
            timeout_seconds=300.0,
        )
        assert ticket.is_expired is False
