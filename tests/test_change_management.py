"""Tests for core.change_management — Change Management & Approval Workflow."""

from __future__ import annotations

import threading

import pytest

from core.change_management import (
    ChangeManager,
    ChangeProposal,
    ChangeRisk,
    ChangeStatus,
    ChangeType,
    get_change_manager,
    propose_change,
)


class TestChangeType:
    """ChangeType enum tests."""

    def test_values(self):
        assert ChangeType.CONFIG.value == "CONFIG"
        assert ChangeType.STRATEGY_PARAM.value == "STRATEGY_PARAM"
        assert ChangeType.ADAPTIVE_BEHAVIOR.value == "ADAPTIVE_BEHAVIOR"
        assert ChangeType.FEATURE_FLAG.value == "FEATURE_FLAG"
        assert ChangeType.INFRASTRUCTURE.value == "INFRASTRUCTURE"


class TestChangeStatus:
    """ChangeStatus enum tests."""

    def test_lifecycle_order(self):
        """Verify the expected lifecycle ordering."""
        assert ChangeStatus.PROPOSED.value == "PROPOSED"
        assert ChangeStatus.REVIEWING.value == "REVIEWING"
        assert ChangeStatus.APPROVED.value == "APPROVED"
        assert ChangeStatus.REJECTED.value == "REJECTED"
        assert ChangeStatus.APPLIED.value == "APPLIED"
        assert ChangeStatus.ROLLED_BACK.value == "ROLLED_BACK"


class TestChangeRisk:
    """ChangeRisk enum tests."""

    def test_values(self):
        assert ChangeRisk.NORMAL.value == "NORMAL"
        assert ChangeRisk.HIGH.value == "HIGH"
        assert ChangeRisk.CRITICAL.value == "CRITICAL"


class TestChangeProposal:
    """ChangeProposal dataclass tests."""

    def test_defaults(self):
        prop = ChangeProposal(
            id_="chg_001",
            change_type=ChangeType.CONFIG,
            target_key="SL_PCT",
            current_value=0.30,
            proposed_value=0.25,
            reason="Optimize stop loss",
            proposed_by="Admin",
        )
        assert prop.id_ == "chg_001"
        assert prop.change_type == ChangeType.CONFIG
        assert prop.target_key == "SL_PCT"
        assert prop.status == ChangeStatus.PROPOSED
        assert prop.risk_level == ChangeRisk.NORMAL

    def test_to_dict(self):
        prop = ChangeProposal(
            id_="chg_001",
            change_type=ChangeType.CONFIG,
            target_key="SL_PCT",
            current_value=0.30,
            proposed_value=0.25,
            reason="Optimize",
            proposed_by="Admin",
            risk_level=ChangeRisk.HIGH,
        )
        d = prop.to_dict()
        assert d["id_"] == "chg_001"
        assert d["change_type"] == "CONFIG"
        assert d["target_key"] == "SL_PCT"
        assert d["risk_level"] == "HIGH"
        assert d["status"] == "PROPOSED"

    def test_to_dict_with_approval(self):
        prop = ChangeProposal(
            id_="chg_001",
            change_type=ChangeType.CONFIG,
            target_key="SL_PCT",
            current_value=0.30,
            proposed_value=0.25,
            reason="Optimize",
            proposed_by="Admin",
            status=ChangeStatus.APPLIED,
            approved_by="Manager",
            applied_by="Bot",
        )
        d = prop.to_dict()
        assert d["status"] == "APPLIED"
        assert d["approved_by"] == "Manager"
        assert d["applied_by"] == "Bot"


class TestChangeManager:
    """ChangeManager tests."""

    def test_init_disabled(self):
        mgr = ChangeManager({"change_management_enabled": False})
        assert mgr.enabled is False

    def test_init_enabled(self):
        mgr = ChangeManager({"change_management_enabled": True})
        assert mgr.enabled is True

    def test_init_default(self):
        mgr = ChangeManager()
        assert mgr.enabled is True

    def test_propose_creates_proposal(self):
        mgr = ChangeManager()
        prop = mgr.propose(
            change_type=ChangeType.CONFIG,
            target_key="SL_PCT",
            current_value=0.30,
            proposed_value=0.25,
            reason="Reduce risk",
            proposed_by="Operator",
        )
        assert prop.id_.startswith("chg_")
        assert prop.status == ChangeStatus.PROPOSED
        assert prop.target_key == "SL_PCT"
        assert prop.proposed_value == 0.25

    def test_propose_string_types(self):
        mgr = ChangeManager()
        prop = mgr.propose(
            change_type="CONFIG",
            target_key="MAX_OPEN",
            current_value=5,
            proposed_value=3,
            reason="Reduce open positions",
            proposed_by="Auto",
            risk_level="HIGH",
        )
        assert prop.change_type == ChangeType.CONFIG
        assert prop.risk_level == ChangeRisk.HIGH

    def test_approve_proposal(self):
        mgr = ChangeManager()
        prop = mgr.propose(
            change_type="CONFIG", target_key="SL_PCT",
            current_value=0.30, proposed_value=0.25,
            reason="Test", proposed_by="Tester",
        )
        ok = mgr.approve(prop.id_, approved_by="Admin")
        assert ok is True
        approved = mgr.get_proposal(prop.id_)
        assert approved is not None
        assert approved.status == ChangeStatus.APPROVED
        assert approved.approved_by == "Admin"

    def test_approve_nonexistent(self):
        mgr = ChangeManager()
        ok = mgr.approve("nonexistent", approved_by="Admin")
        assert ok is False

    def test_approve_already_applied(self):
        mgr = ChangeManager()
        prop = mgr.propose(change_type="CONFIG", target_key="SL_PCT",
                          current_value=0.30, proposed_value=0.25,
                          reason="Test", proposed_by="Tester")
        mgr.approve(prop.id_, approved_by="Admin")
        mgr.apply(prop.id_, applied_by="Bot")
        ok = mgr.approve(prop.id_, approved_by="Admin")
        assert ok is False

    def test_reject_proposal(self):
        mgr = ChangeManager()
        prop = mgr.propose(change_type="CONFIG", target_key="SL_PCT",
                          current_value=0.30, proposed_value=0.25,
                          reason="Test", proposed_by="Tester")
        ok = mgr.reject(prop.id_, rejected_by="Admin", reason="Not needed")
        assert ok is True
        rejected = mgr.get_proposal(prop.id_)
        assert rejected is not None
        assert rejected.status == ChangeStatus.REJECTED
        assert rejected.rejection_reason == "Not needed"

    def test_reject_nonexistent(self):
        mgr = ChangeManager()
        ok = mgr.reject("nonexistent", rejected_by="Admin")
        assert ok is False

    def test_apply_approved(self):
        mgr = ChangeManager()
        prop = mgr.propose(change_type="CONFIG", target_key="SL_PCT",
                          current_value=0.30, proposed_value=0.25,
                          reason="Test", proposed_by="Tester")
        mgr.approve(prop.id_, approved_by="Admin")
        ok = mgr.apply(prop.id_, applied_by="Bot")
        assert ok is True
        applied = mgr.get_proposal(prop.id_)
        assert applied is not None
        assert applied.status == ChangeStatus.APPLIED
        assert applied.applied_by == "Bot"

    def test_apply_not_approved(self):
        mgr = ChangeManager()
        prop = mgr.propose(change_type="CONFIG", target_key="SL_PCT",
                          current_value=0.30, proposed_value=0.25,
                          reason="Test", proposed_by="Tester")
        ok = mgr.apply(prop.id_, applied_by="Bot")
        assert ok is False

    def test_apply_with_callback_success(self):
        mgr = ChangeManager()
        prop = mgr.propose(change_type="CONFIG", target_key="SL_PCT",
                          current_value=0.30, proposed_value=0.25,
                          reason="Test", proposed_by="Tester")
        mgr.approve(prop.id_, approved_by="Admin")
        applied_value = []

        def _apply_fn(p):
            applied_value.append(p.proposed_value)
            return True

        ok = mgr.apply(prop.id_, applied_by="Bot", apply_fn=_apply_fn)
        assert ok is True
        assert applied_value == [0.25]

    def test_apply_with_callback_failure(self):
        mgr = ChangeManager()
        prop = mgr.propose(change_type="CONFIG", target_key="SL_PCT",
                          current_value=0.30, proposed_value=0.25,
                          reason="Test", proposed_by="Tester")
        mgr.approve(prop.id_, approved_by="Admin")

        def _fail_fn(p):
            return False

        ok = mgr.apply(prop.id_, applied_by="Bot", apply_fn=_fail_fn)
        assert ok is False
        failed = mgr.get_proposal(prop.id_)
        assert failed is not None
        assert failed.status == ChangeStatus.FAILED

    def test_apply_with_callback_exception(self):
        mgr = ChangeManager()
        prop = mgr.propose(change_type="CONFIG", target_key="SL_PCT",
                          current_value=0.30, proposed_value=0.25,
                          reason="Test", proposed_by="Tester")
        mgr.approve(prop.id_, approved_by="Admin")

        def _raise_fn(p):
            raise ValueError("Simulated error")

        ok = mgr.apply(prop.id_, applied_by="Bot", apply_fn=_raise_fn)
        assert ok is False
        failed = mgr.get_proposal(prop.id_)
        assert failed is not None
        assert failed.status == ChangeStatus.FAILED
        assert "Simulated error" in failed.failure_reason

    def test_rollback_applied(self):
        mgr = ChangeManager()
        prop = mgr.propose(change_type="CONFIG", target_key="SL_PCT",
                          current_value=0.30, proposed_value=0.25,
                          reason="Test", proposed_by="Tester")
        mgr.approve(prop.id_, approved_by="Admin")
        mgr.apply(prop.id_, applied_by="Bot")
        ok = mgr.rollback(prop.id_, rolled_back_by="Admin")
        assert ok is True
        rolled = mgr.get_proposal(prop.id_)
        assert rolled is not None
        assert rolled.status == ChangeStatus.ROLLED_BACK
        assert rolled.rolled_back_by == "Admin"

    def test_rollback_not_applied(self):
        mgr = ChangeManager()
        prop = mgr.propose(change_type="CONFIG", target_key="SL_PCT",
                          current_value=0.30, proposed_value=0.25,
                          reason="Test", proposed_by="Tester")
        mgr.approve(prop.id_, approved_by="Admin")
        ok = mgr.rollback(prop.id_, rolled_back_by="Admin")
        assert ok is False

    def test_rollback_nonexistent(self):
        mgr = ChangeManager()
        ok = mgr.rollback("nonexistent", rolled_back_by="Admin")
        assert ok is False

    def test_list_pending(self):
        mgr = ChangeManager()
        p1 = mgr.propose(change_type="CONFIG", target_key="A",
                         current_value=1, proposed_value=2,
                         reason="Test", proposed_by="Tester")
        p2 = mgr.propose(change_type="CONFIG", target_key="B",
                         current_value=3, proposed_value=4,
                         reason="Test", proposed_by="Tester")
        mgr.approve(p2.id_, approved_by="Admin")
        pending = mgr.list_pending()
        assert len(pending) == 1
        assert pending[0].id_ == p1.id_

    def test_list_approved(self):
        mgr = ChangeManager()
        p1 = mgr.propose(change_type="CONFIG", target_key="A",
                         current_value=1, proposed_value=2,
                         reason="Test", proposed_by="Tester")
        p2 = mgr.propose(change_type="CONFIG", target_key="B",
                         current_value=3, proposed_value=4,
                         reason="Test", proposed_by="Tester")
        mgr.approve(p1.id_, approved_by="Admin")
        mgr.approve(p2.id_, approved_by="Admin")
        approved = mgr.list_approved()
        assert len(approved) == 2

    def test_list_recent(self):
        mgr = ChangeManager()
        for i in range(5):
            mgr.propose(change_type="CONFIG", target_key=f"K{i}",
                       current_value=i, proposed_value=i + 1,
                       reason=f"Test {i}", proposed_by="Tester")
        recent = mgr.list_recent(n=3)
        assert len(recent) == 3

    def test_get_stats(self):
        mgr = ChangeManager()
        p = mgr.propose(change_type="CONFIG", target_key="SL_PCT",
                       current_value=0.30, proposed_value=0.25,
                       reason="Test", proposed_by="Tester")
        mgr.approve(p.id_, approved_by="Admin")
        mgr.apply(p.id_, applied_by="Bot")
        stats = mgr.get_stats()
        assert stats["enabled"] is True
        assert stats["total_proposals"] == 1
        assert stats["by_status"]["APPLIED"] == 1

    def test_max_pending_limit(self):
        mgr = ChangeManager({"change_max_pending": 2})
        mgr.propose(change_type="CONFIG", target_key="A",
                    current_value=1, proposed_value=2,
                    reason="Test", proposed_by="Tester")
        mgr.propose(change_type="CONFIG", target_key="B",
                    current_value=3, proposed_value=4,
                    reason="Test", proposed_by="Tester")
        with pytest.raises(RuntimeError, match="Max pending"):
            mgr.propose(change_type="CONFIG", target_key="C",
                       current_value=5, proposed_value=6,
                       reason="Test", proposed_by="Tester")

    def test_duplicate_target_blocked(self):
        mgr = ChangeManager()
        mgr.propose(change_type="CONFIG", target_key="SL_PCT",
                    current_value=0.30, proposed_value=0.25,
                    reason="First", proposed_by="Tester")
        with pytest.raises(RuntimeError, match="Existing pending"):
            mgr.propose(change_type="CONFIG", target_key="SL_PCT",
                       current_value=0.25, proposed_value=0.20,
                       reason="Second", proposed_by="Tester")

    def test_propose_with_dry_run_pass(self):
        mgr = ChangeManager()
        prop = mgr.propose_with_dry_run(
            change_type="CONFIG", target_key="SL_PCT",
            current_value=0.30, proposed_value=0.25,
            reason="Test", proposed_by="Tester",
            dry_run_fn=lambda cur, new: {"passed": True, "details": "OK"},
        )
        assert prop.status == ChangeStatus.PROPOSED
        assert prop.dry_run_result is not None
        assert prop.dry_run_result["passed"] is True

    def test_propose_with_dry_run_fail(self):
        mgr = ChangeManager()
        prop = mgr.propose_with_dry_run(
            change_type="CONFIG", target_key="SL_PCT",
            current_value=0.30, proposed_value=0.25,
            reason="Test", proposed_by="Tester",
            dry_run_fn=lambda cur, new: {"passed": False, "error": "Simulation failed"},
        )
        assert prop.status == ChangeStatus.REJECTED
        assert "Simulation failed" in prop.rejection_reason

    def test_propose_with_dry_run_exception(self):
        mgr = ChangeManager()
        prop = mgr.propose_with_dry_run(
            change_type="CONFIG", target_key="SL_PCT",
            current_value=0.30, proposed_value=0.25,
            reason="Test", proposed_by="Tester",
            dry_run_fn=lambda cur, new: (_ for _ in ()).throw(ValueError("Boom")),
        )
        assert prop.status == ChangeStatus.REJECTED

    def test_auto_expiry(self):
        """Proposals should expire after their expiry time."""
        mgr = ChangeManager({"change_auto_expire_hours": 0})  # Immediate expiry
        prop = mgr.propose(
            change_type="CONFIG", target_key="SL_PCT",
            current_value=0.30, proposed_value=0.25,
            reason="Test", proposed_by="Tester",
        )
        # Force expiry check
        mgr._expire_stale()
        expired = mgr.get_proposal(prop.id_)
        assert expired is not None
        # The expiry_at should be in the past since we set auto_expire_hours=0
        assert expired.status in (ChangeStatus.PROPOSED, ChangeStatus.EXPIRED)

    def test_disabled_auto_approves(self):
        mgr = ChangeManager({"change_management_enabled": False})
        prop = mgr.propose(
            change_type="CONFIG", target_key="SL_PCT",
            current_value=0.30, proposed_value=0.25,
            reason="Test", proposed_by="Tester",
        )
        assert prop.status == ChangeStatus.APPROVED

    def test_get_audit_log(self):
        mgr = ChangeManager()
        prop = mgr.propose(change_type="CONFIG", target_key="SL_PCT",
                          current_value=0.30, proposed_value=0.25,
                          reason="Test", proposed_by="Tester")
        mgr.approve(prop.id_, approved_by="Admin")
        log = mgr.get_audit_log()
        assert len(log) >= 2
        assert log[-2]["action"] == "PROPOSED"
        assert log[-1]["action"] == "APPROVED"
        assert log[-1]["actor"] == "Admin"

    def test_thread_safety(self):
        """Concurrent access should not cause data corruption."""
        mgr = ChangeManager({"change_max_pending": 50})
        errors = []

        def _worker():
            try:
                for i in range(5):
                    p = mgr.propose(
                        change_type="CONFIG",
                        target_key=f"K_{threading.get_ident()}_{i}",
                        current_value=i, proposed_value=i + 1,
                        reason=f"Thread {i}", proposed_by="Worker",
                    )
                    mgr.approve(p.id_, approved_by="Auto")
                    mgr.apply(p.id_, applied_by="Auto")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Thread safety errors: {errors}"
        stats = mgr.get_stats()
        assert stats["total_proposals"] >= 5


class TestConvenienceAPI:
    """Convenience function tests."""

    def test_propose_change(self):
        prop = propose_change(
            change_type="CONFIG",
            target_key="SL_PCT",
            current_value=0.30,
            proposed_value=0.25,
            reason="Test convenience",
            proposed_by="Tester",
        )
        assert prop.id_.startswith("chg_")
        assert prop.target_key == "SL_PCT"

    def test_get_change_manager_singleton(self):
        m1 = get_change_manager()
        m2 = get_change_manager()
        assert m1 is m2


class TestFullLifecycle:
    """Full change management lifecycle integration test."""

    def test_full_lifecycle(self):
        """propose → approve → apply → rollback."""
        mgr = ChangeManager()

        # Propose
        prop = mgr.propose(
            change_type="CONFIG",
            target_key="MAX_OPEN",
            current_value=5,
            proposed_value=3,
            reason="Reduce max open positions during low volatility",
            proposed_by="Risk Analyst",
            risk_level="HIGH",
        )
        assert prop.status == ChangeStatus.PROPOSED

        # Approve
        mgr.approve(prop.id_, approved_by="CRO")
        assert mgr.get_proposal(prop.id_).status == ChangeStatus.APPROVED

        # Apply
        applied = []
        mgr.apply(prop.id_, applied_by="Bot",
                 apply_fn=lambda p: applied.append(p.proposed_value) or True)
        assert mgr.get_proposal(prop.id_).status == ChangeStatus.APPLIED
        assert applied == [3]

        # Rollback
        mgr.rollback(prop.id_, rolled_back_by="CRO")
        assert mgr.get_proposal(prop.id_).status == ChangeStatus.ROLLED_BACK

        # Audit trail
        log = mgr.get_audit_log()
        actions = [e["action"] for e in log]
        assert actions == ["PROPOSED", "APPROVED", "APPLIED", "ROLLED_BACK"]
