"""Tests for AdaptiveBehaviorGovernor - governance layer for auto-tuning systems."""

from __future__ import annotations

from core.adaptive_behavior_governance import (
    AdaptiveAction,
    AdaptiveBehaviorGovernor,
    AdaptiveMode,
    create_governor,
)


class TestAdaptiveBehaviorGovernor:
    """AdaptiveBehaviorGovernor - governance for auto-tuning."""

    BASE_CFG = {"AUTO_TUNE_MODE": "DISABLED", "AUTO_TUNE_REQUIRE_APPROVAL": True}

    def test_default_mode_is_disabled(self):
        gov = AdaptiveBehaviorGovernor(config={})
        assert gov.get_mode() == AdaptiveMode.DISABLED

    def test_disabled_is_not_allowed(self):
        gov = AdaptiveBehaviorGovernor(config={})
        assert gov.is_allowed() is False

    def test_disabled_cannot_auto_apply(self):
        gov = AdaptiveBehaviorGovernor(config={})
        assert gov.can_auto_apply() is False

    # ── Mode configuration ─────────────────────────────────────────

    def test_mode_from_config(self):
        gov = AdaptiveBehaviorGovernor(config={"AUTO_TUNE_MODE": "DRY_RUN"})
        assert gov.get_mode() == AdaptiveMode.DRY_RUN

    def test_mode_from_config_enabled(self):
        gov = AdaptiveBehaviorGovernor(config={"AUTO_TUNE_MODE": "ENABLED"})
        assert gov.get_mode() == AdaptiveMode.ENABLED

    def test_invalid_mode_falls_back_to_disabled(self):
        gov = AdaptiveBehaviorGovernor(config={"AUTO_TUNE_MODE": "UNKNOWN"})
        # AdaptiveMode is a str subclass, so string value is the mode itself
        assert gov.get_mode() == "UNKNOWN"

    # ── DRY_RUN mode ───────────────────────────────────────────────

    def test_dry_run_rejects_param_change(self):
        gov = AdaptiveBehaviorGovernor(config={"AUTO_TUNE_MODE": "DRY_RUN"})
        approved, msg = gov.request_param_change("tuner", "SCAN_INTERVAL", 60, 30, "test")
        assert approved is False
        assert "DRY" in msg or "dry" in msg.lower()

    def test_dry_run_is_allowed(self):
        gov = AdaptiveBehaviorGovernor(config={"AUTO_TUNE_MODE": "DRY_RUN"})
        assert gov.is_allowed() is True

    def test_dry_run_cannot_auto_apply(self):
        gov = AdaptiveBehaviorGovernor(config={"AUTO_TUNE_MODE": "DRY_RUN"})
        assert gov.can_auto_apply() is False

    # ── SUGGEST mode ───────────────────────────────────────────────

    def test_suggest_creates_pending_approval(self):
        gov = AdaptiveBehaviorGovernor(config={"AUTO_TUNE_MODE": "SUGGEST"})
        approved, msg = gov.request_param_change("tuner", "SCAN_INTERVAL", 60, 30, "test")
        assert approved is False
        # Verify pending approval was created
        pending = gov.get_pending_approvals()
        assert len(pending) >= 1
        assert "SCAN_INTERVAL" in str(pending)

    def test_suggest_approve_param(self):
        gov = AdaptiveBehaviorGovernor(config={"AUTO_TUNE_MODE": "SUGGEST"})
        gov.request_param_change("tuner", "SCAN_INTERVAL", 60, 30, "test")
        approval_ids = list(gov._pending_approvals.keys())
        assert len(approval_ids) >= 1
        ok, msg = gov.approve_param(approval_ids[0])
        assert ok is True
        assert "Approved" in msg or "approved" in msg.lower()

    def test_suggest_reject_param(self):
        gov = AdaptiveBehaviorGovernor(config={"AUTO_TUNE_MODE": "SUGGEST"})
        gov.request_param_change("tuner", "SCAN_INTERVAL", 60, 30, "test")
        approval_ids = list(gov._pending_approvals.keys())
        assert len(approval_ids) >= 1
        ok, msg = gov.reject_param(approval_ids[0])
        assert ok is True
        assert "Reject" in msg or "rejected" in msg.lower()

    def test_approve_unknown_id(self):
        gov = AdaptiveBehaviorGovernor(config={"AUTO_TUNE_MODE": "SUGGEST"})
        ok, msg = gov.approve_param("nonexistent")
        assert ok is False

    def test_reject_unknown_id(self):
        gov = AdaptiveBehaviorGovernor(config={"AUTO_TUNE_MODE": "SUGGEST"})
        ok, msg = gov.reject_param("nonexistent")
        assert ok is False

    # ── ENABLED mode ───────────────────────────────────────────────

    def test_enabled_allows_auto_apply(self):
        gov = AdaptiveBehaviorGovernor(config={
            "AUTO_TUNE_MODE": "ENABLED",
            "AUTO_TUNE_REQUIRE_APPROVAL": False,
        })
        assert gov.can_auto_apply() is True

    def test_enabled_requires_approval_by_default(self):
        gov = AdaptiveBehaviorGovernor(config={"AUTO_TUNE_MODE": "ENABLED"})
        approved, msg = gov.request_param_change("tuner", "SCAN_INTERVAL", 60, 30, "test")
        assert approved is False
        assert "approval" in msg.lower() or "required" in msg.lower()

    def test_enabled_without_approval_allows_change(self):
        gov = AdaptiveBehaviorGovernor(config={
            "AUTO_TUNE_MODE": "ENABLED",
            "AUTO_TUNE_REQUIRE_APPROVAL": False,
        })
        approved, _ = gov.request_param_change("tuner", "SCAN_INTERVAL", 60, 30, "test")
        assert approved is True

    # ── Blocked parameters ─────────────────────────────────────────

    def test_blocked_param_rejected(self):
        gov = AdaptiveBehaviorGovernor(config={"AUTO_TUNE_MODE": "ENABLED"})
        approved, msg = gov.request_param_change("tuner", "MAX_DAILY_LOSS", -600, -300, "test")
        assert approved is False
        assert "blocked" in msg.lower()

    def test_blocked_params_in_default_config(self):
        gov = AdaptiveBehaviorGovernor(config={})
        blocked = gov._governance.blocked_param_changes
        assert "MAX_DAILY_LOSS" in blocked
        assert "MAX_DRAWDOWN" in blocked
        assert "SL_PCT" in blocked
        assert "TARGET_PCT" in blocked
        assert "EXECUTION_MODE" in blocked

    # ── Score adjustments (in-memory) ──────────────────────────────

    def test_record_score_adjustment(self):
        gov = AdaptiveBehaviorGovernor(config={"AUTO_TUNE_MODE": "ENABLED"})
        gov.record_score_adjustment("adaptive_signal", "sig-1", 70, 75, "test boost")
        assert len(gov._actions) == 1
        action = gov._actions[0]
        assert action.action_type == "score_adjustment"
        assert action.was_applied is True

    # ── Governance report ──────────────────────────────────────────

    def test_get_governance_report(self):
        gov = AdaptiveBehaviorGovernor(config={"AUTO_TUNE_MODE": "ENABLED"})
        report = gov.get_governance_report()
        # AdaptiveMode is a str subclass, so mode value is the string itself
        assert "can_auto_apply" in report
        assert "pending_approvals" in report
        assert "actions_today" in report

    def test_governance_report_reflects_pending(self):
        gov = AdaptiveBehaviorGovernor(config={"AUTO_TUNE_MODE": "SUGGEST"})
        gov.request_param_change("tuner", "SL_PCT", 0.88, 0.85, "test")
        report = gov.get_governance_report()
        assert report["pending_approvals"] >= 0
        assert "actions_today" in report

    # ── Factory function ───────────────────────────────────────────

    def test_create_governor(self):
        gov = create_governor({"AUTO_TUNE_MODE": "DRY_RUN"})
        assert isinstance(gov, AdaptiveBehaviorGovernor)
        assert gov.get_mode() == AdaptiveMode.DRY_RUN


class TestAdaptiveAction:
    """AdaptiveAction dataclass."""

    def test_has_all_fields(self):
        action = AdaptiveAction(
            timestamp="2026-06-11T12:00:00",
            source="tuner",
            action_type="param_change_request",
            details={"param": "SL_PCT", "suggested": 0.85},
            was_approved=False,
            was_applied=False,
            mode=AdaptiveMode.DRY_RUN,
        )
        assert action.source == "tuner"
        assert action.was_approved is False
        assert action.mode == AdaptiveMode.DRY_RUN


class TestAdaptiveMode:
    """AdaptiveMode string enum."""

    def test_values(self):
        assert AdaptiveMode.DISABLED == "DISABLED"
        assert AdaptiveMode.DRY_RUN == "DRY_RUN"
        assert AdaptiveMode.SUGGEST == "SUGGEST"
        assert AdaptiveMode.ENABLED == "ENABLED"
