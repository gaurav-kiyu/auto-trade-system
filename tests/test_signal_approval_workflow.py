"""Tests for SignalApprovalWorkflow - signal routing and approval logic."""

from __future__ import annotations

from unittest.mock import MagicMock

from core.signal_approval_workflow import (
    EXECUTE,
    FULLY_AUTO,
    FULL_MANUAL,
    MANUAL_PRIORITY,
    NOTIFY_ONLY,
    QUEUE,
    SIGNALS_ONLY,
    SIG_AUTO,
    SIG_MANUAL,
    SKIP,
    AUTO_WITH_OVERRIDE,
    SignalApprovalWorkflow,
    SignalDecision,
    build_workflow,
)


class TestSignalDecision:
    """SignalDecision dataclass properties."""

    def test_should_execute_true_for_execute(self):
        d = SignalDecision(action=EXECUTE)
        assert d.should_execute is True

    def test_should_execute_false_for_notify(self):
        d = SignalDecision(action=NOTIFY_ONLY)
        assert d.should_execute is False

    def test_should_queue_true_for_queue(self):
        d = SignalDecision(action=QUEUE)
        assert d.should_queue is True

    def test_should_queue_false_for_skip(self):
        d = SignalDecision(action=SKIP)
        assert d.should_queue is False

    def test_should_notify_for_execute(self):
        assert SignalDecision(action=EXECUTE).should_notify is True

    def test_should_notify_for_queue(self):
        assert SignalDecision(action=QUEUE).should_notify is True

    def test_should_notify_for_notify_only(self):
        assert SignalDecision(action=NOTIFY_ONLY).should_notify is True

    def test_should_notify_false_for_skip(self):
        assert SignalDecision(action=SKIP).should_notify is False


class TestSignalApprovalWorkflow:
    """SignalApprovalWorkflow - evaluates signals and returns decisions."""

    BASE_CFG = {
        "manual_signal_workflow_mode": SIGNALS_ONLY,
        "manual_signal_min_score": 50,
        "manual_signal_max_score": 100,
        "TIER_STRONG_MIN": 80,
        "TIER_MODERATE_MIN": 70,
        "BROKER_API_ENABLED": False,
        "EXECUTION_MODE": "MANUAL",
    }

    def test_default_mode_is_signals_only(self):
        workflow = SignalApprovalWorkflow(cfg={})
        assert workflow.mode == SIGNALS_ONLY

    def test_unknown_mode_defaults_to_signals_only(self):
        workflow = SignalApprovalWorkflow(cfg={"manual_signal_workflow_mode": "INVALID"})
        assert workflow.mode == SIGNALS_ONLY

    # ── SIGNALS_ONLY mode ──────────────────────────────────────────

    def test_signals_only_always_notifies(self):
        workflow = SignalApprovalWorkflow(cfg=self.BASE_CFG)
        decision = workflow.process_signal(SIG_AUTO, 95, "STRONG")
        assert decision.action == NOTIFY_ONLY

    def test_signals_only_never_executes(self):
        workflow = SignalApprovalWorkflow(cfg=self.BASE_CFG)
        decision = workflow.process_signal(SIG_AUTO, 100, "STRONG")
        assert decision.should_execute is False

    def test_signals_only_manual_also_notifies(self):
        workflow = SignalApprovalWorkflow(cfg=self.BASE_CFG)
        decision = workflow.process_signal(SIG_MANUAL, 80, "STRONG")
        assert decision.action == NOTIFY_ONLY

    def test_signals_only_strong_gets_higher_priority(self):
        workflow = SignalApprovalWorkflow(cfg=self.BASE_CFG)
        weak = workflow.process_signal(SIG_AUTO, 60, "WEAK")
        strong = workflow.process_signal(SIG_AUTO, 95, "STRONG")
        assert strong.priority < weak.priority

    # ── FULL_MANUAL mode ───────────────────────────────────────────

    def test_full_manual_queues_valid_signal(self):
        mock_queue = MagicMock()
        mock_queue.submit.return_value.signal_id = "sig-001"
        config = {**self.BASE_CFG, "manual_signal_workflow_mode": FULL_MANUAL}
        workflow = SignalApprovalWorkflow(cfg=config, queue=mock_queue)
        decision = workflow.process_signal(SIG_AUTO, 75)
        assert decision.action == QUEUE
        assert decision.queue_signal_id == "sig-001"
        mock_queue.submit.assert_called_once()

    def test_full_manual_skips_below_min_score(self):
        config = {**self.BASE_CFG, "manual_signal_workflow_mode": FULL_MANUAL}
        workflow = SignalApprovalWorkflow(cfg=config)
        decision = workflow.process_signal(SIG_AUTO, 30)
        assert decision.action == SKIP

    def test_full_manual_notifies_when_no_queue(self):
        config = {**self.BASE_CFG, "manual_signal_workflow_mode": FULL_MANUAL}
        workflow = SignalApprovalWorkflow(cfg=config, queue=None)
        decision = workflow.process_signal(SIG_AUTO, 75)
        assert decision.action == NOTIFY_ONLY

    def test_full_manual_uses_existing_id(self):
        mock_queue = MagicMock()
        config = {**self.BASE_CFG, "manual_signal_workflow_mode": FULL_MANUAL}
        workflow = SignalApprovalWorkflow(cfg=config, queue=mock_queue)
        decision = workflow.process_signal(SIG_MANUAL, 75, manual_signal_id="existing-1")
        assert decision.action == QUEUE
        assert decision.queue_signal_id == "existing-1"
        # Should not call submit for existing ID
        mock_queue.submit.assert_not_called()

    # ── MANUAL_PRIORITY mode ───────────────────────────────────────

    def test_manual_priority_queues_manual_signal(self):
        mock_queue = MagicMock()
        mock_queue.submit.return_value.signal_id = "sig-002"
        config = {**self.BASE_CFG, "manual_signal_workflow_mode": MANUAL_PRIORITY}
        workflow = SignalApprovalWorkflow(cfg=config, queue=mock_queue)
        decision = workflow.process_signal(SIG_MANUAL, 85)
        assert decision.action == QUEUE

    def test_manual_priority_executes_strong_auto(self):
        config = {
            **self.BASE_CFG,
            "manual_signal_workflow_mode": MANUAL_PRIORITY,
            "BROKER_API_ENABLED": True,
            "EXECUTION_MODE": "AUTO",
        }
        workflow = SignalApprovalWorkflow(cfg=config)
        decision = workflow.process_signal(SIG_AUTO, 85, "STRONG")
        assert decision.action == EXECUTE

    def test_manual_priority_queues_moderate_auto(self):
        mock_queue = MagicMock()
        mock_queue.submit.return_value.signal_id = "sig-003"
        config = {
            **self.BASE_CFG,
            "manual_signal_workflow_mode": MANUAL_PRIORITY,
        }
        workflow = SignalApprovalWorkflow(cfg=config, queue=mock_queue)
        decision = workflow.process_signal(SIG_AUTO, 75, "MODERATE")
        assert decision.action == QUEUE

    def test_manual_priority_notifies_weak_auto(self):
        config = {**self.BASE_CFG, "manual_signal_workflow_mode": MANUAL_PRIORITY}
        workflow = SignalApprovalWorkflow(cfg=config)
        decision = workflow.process_signal(SIG_AUTO, 60, "WEAK")
        assert decision.action == NOTIFY_ONLY

    # ── AUTO_WITH_OVERRIDE mode ────────────────────────────────────

    def test_auto_with_override_executes_manual(self):
        config = {
            **self.BASE_CFG,
            "manual_signal_workflow_mode": AUTO_WITH_OVERRIDE,
            "BROKER_API_ENABLED": True,
            "EXECUTION_MODE": "AUTO",
        }
        workflow = SignalApprovalWorkflow(cfg=config)
        decision = workflow.process_signal(SIG_MANUAL, 90, "STRONG")
        assert decision.action == EXECUTE

    def test_auto_with_override_executes_auto(self):
        config = {
            **self.BASE_CFG,
            "manual_signal_workflow_mode": AUTO_WITH_OVERRIDE,
            "BROKER_API_ENABLED": True,
            "EXECUTION_MODE": "AUTO",
        }
        workflow = SignalApprovalWorkflow(cfg=config)
        decision = workflow.process_signal(SIG_AUTO, 80)
        assert decision.action == EXECUTE

    def test_auto_with_override_notifies_when_broker_disabled(self):
        config = {
            **self.BASE_CFG,
            "manual_signal_workflow_mode": AUTO_WITH_OVERRIDE,
            "BROKER_API_ENABLED": False,
        }
        workflow = SignalApprovalWorkflow(cfg=config)
        decision = workflow.process_signal(SIG_AUTO, 80)
        assert decision.action == NOTIFY_ONLY

    # ── FULLY_AUTO mode ────────────────────────────────────────────

    def test_fully_auto_executes_with_broker(self):
        config = {
            **self.BASE_CFG,
            "manual_signal_workflow_mode": FULLY_AUTO,
            "BROKER_API_ENABLED": True,
            "EXECUTION_MODE": "AUTO",
        }
        workflow = SignalApprovalWorkflow(cfg=config)
        decision = workflow.process_signal(SIG_AUTO, 85)
        assert decision.action == EXECUTE

    def test_fully_auto_notifies_without_broker(self):
        config = {
            **self.BASE_CFG,
            "manual_signal_workflow_mode": FULLY_AUTO,
            "BROKER_API_ENABLED": False,
        }
        workflow = SignalApprovalWorkflow(cfg=config)
        decision = workflow.process_signal(SIG_AUTO, 85)
        assert decision.action == NOTIFY_ONLY

    def test_fully_auto_skips_below_min_score(self):
        config = {
            **self.BASE_CFG,
            "manual_signal_workflow_mode": FULLY_AUTO,
            "BROKER_API_ENABLED": True,
            "EXECUTION_MODE": "AUTO",
        }
        workflow = SignalApprovalWorkflow(cfg=config)
        decision = workflow.process_signal(SIG_AUTO, 30)
        assert decision.action == SKIP

    # ── Tier scoring ───────────────────────────────────────────────

    def test_score_to_tier_strong(self):
        config = {**self.BASE_CFG, "TIER_STRONG_MIN": 80}
        workflow = SignalApprovalWorkflow(cfg=config)
        assert workflow._score_to_tier(85) == "STRONG"

    def test_score_to_tier_moderate(self):
        config = {**self.BASE_CFG, "TIER_MODERATE_MIN": 70}
        workflow = SignalApprovalWorkflow(cfg=config)
        assert workflow._score_to_tier(75) == "MODERATE"

    def test_score_to_tier_weak(self):
        workflow = SignalApprovalWorkflow(cfg=self.BASE_CFG)
        assert workflow._score_to_tier(60) == "WEAK"

    # ── Factory function ───────────────────────────────────────────

    def test_build_workflow_returns_instance(self):
        workflow = build_workflow(self.BASE_CFG)
        assert isinstance(workflow, SignalApprovalWorkflow)

    def test_build_workflow_fallback_on_error(self):
        class BrokenQueue:
            def submit(self, *a, **kw):
                raise RuntimeError("Broken")

        workflow = build_workflow(self.BASE_CFG, BrokenQueue())
        assert isinstance(workflow, SignalApprovalWorkflow)
        # Should fall back to SIGNALS_ONLY
        decision = workflow.process_signal(SIG_AUTO, 80)
        assert decision.action == NOTIFY_ONLY

    # ── can_execute helper ─────────────────────────────────────────

    def test_can_execute_true_with_broker_and_auto(self):
        config = {
            **self.BASE_CFG,
            "BROKER_API_ENABLED": True,
            "EXECUTION_MODE": "AUTO",
        }
        workflow = SignalApprovalWorkflow(cfg=config)
        assert workflow._can_execute() is True

    def test_can_execute_false_without_broker(self):
        config = {**self.BASE_CFG, "BROKER_API_ENABLED": False}
        workflow = SignalApprovalWorkflow(cfg=config)
        assert workflow._can_execute() is False

    def test_can_execute_false_with_wrong_mode(self):
        config = {
            **self.BASE_CFG,
            "BROKER_API_ENABLED": True,
            "EXECUTION_MODE": "MANUAL",
        }
        workflow = SignalApprovalWorkflow(cfg=config)
        assert workflow._can_execute() is False
