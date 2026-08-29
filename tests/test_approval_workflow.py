"""Tests for approval workflow modules.

Covers both core/strategy/approval_workflow.py (StrategyApprovalWorkflow)
and core/self_healing/approval_workflow.py (HealingApprovalWorkflow).
"""
from __future__ import annotations

from core.strategy.approval_workflow import (
    ApprovalStatus,
    StrategyApprovalWorkflow,
    get_approval_workflow,
)


def test_strategy_get_approval_workflow_returns_instance():
    """get_approval_workflow must return a StrategyApprovalWorkflow."""
    workflow = get_approval_workflow()
    assert isinstance(workflow, StrategyApprovalWorkflow)


def test_strategy_approval_status_enum():
    """ApprovalStatus enum must contain the expected states."""
    assert ApprovalStatus.PENDING is not None
    assert ApprovalStatus.APPROVED is not None
    assert ApprovalStatus.REJECTED is not None


def test_strategy_governance_report_returns_dict():
    """get_governance_report must return a dict."""
    workflow = get_approval_workflow()
    report = workflow.get_governance_report()
    assert isinstance(report, dict)


def test_strategy_get_pending_approvals_returns_list():
    """get_pending_approvals must return a list."""
    workflow = get_approval_workflow()
    pending = workflow.get_pending_approvals()
    assert isinstance(pending, list)


def test_healing_approval_workflow_importable():
    """The healing approval workflow module must import cleanly."""
    from core.self_healing.approval_workflow import (
        HealingApprovalWorkflow,
    )
    from core.self_healing.approval_workflow import (
        get_approval_workflow as get_healing_workflow,
    )

    workflow = get_healing_workflow()
    assert isinstance(workflow, HealingApprovalWorkflow)
