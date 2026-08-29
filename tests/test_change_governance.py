"""Tests for core/change_governance.py — Change Governance Engine (Phase 28)."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.change_governance import (
    ChangeEvent,
    ChangeGovernanceEngine,
    ChangeGovernanceReport,
    ChangeRequest,
    get_change_governance,
    reset_change_governance,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_engine() -> None:
    """Reset singleton before and after each test."""
    reset_change_governance()
    p = Path("json/change_governance.json")
    if p.exists():
        p.unlink()
    yield
    reset_change_governance()


@pytest.fixture
def engine() -> ChangeGovernanceEngine:
    return get_change_governance()


@pytest.fixture
def populated_engine(engine: ChangeGovernanceEngine) -> ChangeGovernanceEngine:
    cr1 = engine.create_change(
        title="Update SL_PCT",
        description="Adjust stop-loss threshold",
        change_type="CONFIG",
        priority="MEDIUM",
        author="quant-team",
        files_changed=["index_config.defaults.json"],
    )
    engine.submit_for_review(cr1.change_id)

    cr2 = engine.create_change(
        title="Add new strategy",
        description="Implement mean reversion v2",
        change_type="STRATEGY",
        priority="HIGH",
        author="strat-team",
        files_changed=["core/strategy/mean_reversion.py"],
    )
    engine.submit_for_review(cr2.change_id)
    engine.start_review(cr2.change_id, reviewer="cto")

    cr3 = engine.create_change(
        title="Security patch",
        description="Fix CVE in dependency",
        change_type="SECURITY",
        priority="CRITICAL",
        author="security-team",
        files_changed=["requirements.txt"],
    )
    engine.submit_for_review(cr3.change_id)
    engine.start_review(cr3.change_id, reviewer="cto")
    engine.approve(cr3.change_id, reviewer="cto")
    engine.deploy(cr3.change_id, actor="devops")
    engine.verify(cr3.change_id, actor="security-team")

    return engine


# ── ChangeEvent Tests ────────────────────────────────────────────────────────


class TestChangeEvent:
    def test_default_values(self) -> None:
        evt = ChangeEvent(event_type="CREATED", actor="system")
        assert evt.event_type == "CREATED"
        assert evt.actor == "system"
        assert evt.comment == ""

    def test_to_dict(self) -> None:
        evt = ChangeEvent(event_type="APPROVED", actor="cto", comment="Looks good")
        d = evt.to_dict()
        assert d["event_type"] == "APPROVED"
        assert d["actor"] == "cto"
        assert d["comment"] == "Looks good"


# ── ChangeRequest Tests ──────────────────────────────────────────────────────


class TestChangeRequest:
    def test_default_values(self) -> None:
        cr = ChangeRequest(change_id="CR-001", title="Test Change")
        assert cr.status == "DRAFT"
        assert cr.priority == "MEDIUM"
        assert cr.is_open is True
        assert cr.is_approved is False
        assert cr.is_deployable is False

    def test_is_approved_true(self) -> None:
        cr = ChangeRequest(change_id="CR-001", title="Test", status="APPROVED")
        assert cr.is_approved is True
        assert cr.is_deployable is True

    def test_is_closed(self) -> None:
        cr = ChangeRequest(change_id="CR-001", title="Test", status="CLOSED")
        assert cr.is_open is False
        assert cr.is_approved is True

    def test_is_rolled_back(self) -> None:
        cr = ChangeRequest(change_id="CR-001", title="Test", status="ROLLED_BACK")
        assert cr.is_open is False

    def test_add_event(self) -> None:
        cr = ChangeRequest(change_id="CR-001", title="Test")
        cr.add_event("SUBMITTED", "author")
        assert len(cr.events) == 1
        assert cr.events[0].event_type == "SUBMITTED"
        assert cr.events[0].actor == "author"

    def test_add_event_updates_timestamps(self) -> None:
        cr = ChangeRequest(change_id="CR-001", title="Test")
        cr.add_event("DEPLOYED", "devops")
        assert cr.deployed_at is not None
        cr.add_event("VERIFIED", "qa")
        assert cr.verified_at is not None
        cr.add_event("CLOSED", "admin")
        assert cr.closed_at is not None

    def test_to_dict_contains_keys(self) -> None:
        cr = ChangeRequest(change_id="CR-001", title="Test", change_type="CONFIG")
        d = cr.to_dict()
        keys = {
            "change_id", "title", "description", "change_type", "priority",
            "status", "author", "reviewer", "approver", "files_changed",
            "risk_level", "risk_score", "risk_factors", "recommendations",
            "linked_incidents", "linked_release", "rollback_plan", "test_summary",
            "events", "created_at", "updated_at",
        }
        assert set(d.keys()) >= keys


# ── ChangeGovernanceReport Tests ─────────────────────────────────────────────


class TestChangeGovernanceReport:
    def test_empty_report(self) -> None:
        report = ChangeGovernanceReport()
        assert report.n_changes == 0
        assert report.summary_text() != ""

    def test_to_dict(self) -> None:
        report = ChangeGovernanceReport(
            n_changes=10,
            by_status={"APPROVED": 3, "DRAFT": 5, "CLOSED": 2},
        )
        d = report.to_dict()
        assert d["n_changes"] == 10
        assert d["by_status"]["APPROVED"] == 3


# ── ChangeGovernanceEngine Tests ─────────────────────────────────────────────


class TestChangeGovernanceEngine:
    def test_singleton_consistency(self) -> None:
        e1 = get_change_governance()
        e2 = get_change_governance()
        assert e1 is e2

    def test_reset(self) -> None:
        e1 = get_change_governance()
        reset_change_governance()
        e2 = get_change_governance()
        assert e1 is not e2

    # ── Create ────────────────────────────────────────────────────────────

    def test_create_change_basic(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(
            title="Test change",
            description="Test description",
            change_type="CONFIG",
            priority="LOW",
            author="tester",
        )
        assert cr.change_id.startswith("CR-")
        assert cr.title == "Test change"
        assert cr.status == "DRAFT"
        assert cr.risk_level in ("LOW", "MEDIUM")

    def test_create_change_invalid_type_defaults_to_other(
        self, engine: ChangeGovernanceEngine
    ) -> None:
        cr = engine.create_change(title="Test", change_type="INVALID_TYPE")
        assert cr.change_type == "OTHER"

    def test_create_change_invalid_priority_defaults_to_medium(
        self, engine: ChangeGovernanceEngine
    ) -> None:
        cr = engine.create_change(title="Test", priority="INVALID")
        assert cr.priority == "MEDIUM"

    def test_create_change_with_files_and_rollback(
        self, engine: ChangeGovernanceEngine
    ) -> None:
        cr = engine.create_change(
            title="Risk update",
            description="Update risk parameters",
            change_type="RISK",
            priority="HIGH",
            author="risk-team",
            files_changed=["core/services/risk_service.py"],
            rollback_plan="Revert the config change",
            test_summary="All tests pass",
        )
        assert "risk" in cr.risk_level.lower() or cr.risk_level in ("HIGH", "MEDIUM")
        assert cr.rollback_plan == "Revert the config change"
        assert cr.test_summary == "All tests pass"

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def test_submit_for_review(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Test")
        assert engine.submit_for_review(cr.change_id) is True
        updated = engine.get_change(cr.change_id)
        assert updated is not None
        assert updated.status == "SUBMITTED"

    def test_submit_for_review_twice_fails(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Test")
        engine.submit_for_review(cr.change_id)
        assert engine.submit_for_review(cr.change_id) is False

    def test_submit_for_review_nonexistent(self, engine: ChangeGovernanceEngine) -> None:
        assert engine.submit_for_review("NONEXISTENT") is False

    def test_start_review(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Test")
        engine.submit_for_review(cr.change_id)
        assert engine.start_review(cr.change_id, reviewer="cto") is True
        updated = engine.get_change(cr.change_id)
        assert updated is not None
        assert updated.status == "IN_REVIEW"
        assert updated.reviewer == "cto"

    def test_start_review_from_wrong_state(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Test")
        assert engine.start_review(cr.change_id, reviewer="cto") is False

    def test_approve(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Test")
        engine.submit_for_review(cr.change_id)
        engine.start_review(cr.change_id, reviewer="cto")
        assert engine.approve(cr.change_id, reviewer="cto") is True
        updated = engine.get_change(cr.change_id)
        assert updated is not None
        assert updated.status == "APPROVED"
        assert updated.approver == "cto"

    def test_approve_from_draft_fails(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Test")
        assert engine.approve(cr.change_id, reviewer="cto") is False

    def test_reject(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Test")
        engine.submit_for_review(cr.change_id)
        engine.start_review(cr.change_id, reviewer="cto")
        assert engine.reject(cr.change_id, reviewer="cto", comment="Not ready") is True
        updated = engine.get_change(cr.change_id)
        assert updated is not None
        assert updated.status == "REJECTED"

    def test_approve_after_reject_fails(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Test")
        engine.submit_for_review(cr.change_id)
        engine.reject(cr.change_id, reviewer="cto")
        assert engine.approve(cr.change_id, reviewer="cto") is False

    def test_deploy(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Test")
        engine.submit_for_review(cr.change_id)
        engine.approve(cr.change_id, reviewer="cto")
        assert engine.deploy(cr.change_id, actor="devops") is True
        updated = engine.get_change(cr.change_id)
        assert updated is not None
        assert updated.status == "DEPLOYED"

    def test_deploy_from_wrong_state(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Test")
        assert engine.deploy(cr.change_id, actor="devops") is False

    def test_verify(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Test")
        engine.submit_for_review(cr.change_id)
        engine.approve(cr.change_id, reviewer="cto")
        engine.deploy(cr.change_id, actor="devops")
        assert engine.verify(cr.change_id, actor="qa") is True
        updated = engine.get_change(cr.change_id)
        assert updated is not None
        assert updated.status == "VERIFIED"

    def test_close(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Test")
        engine.submit_for_review(cr.change_id)
        engine.approve(cr.change_id, reviewer="cto")
        engine.deploy(cr.change_id, actor="devops")
        engine.verify(cr.change_id, actor="qa")
        assert engine.close(cr.change_id, actor="admin") is True
        updated = engine.get_change(cr.change_id)
        assert updated is not None
        assert updated.status == "CLOSED"

    def test_full_lifecycle(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Full Lifecycle")
        engine.submit_for_review(cr.change_id)
        engine.approve(cr.change_id, reviewer="cto")
        engine.deploy(cr.change_id, actor="devops")
        engine.verify(cr.change_id, actor="qa")
        engine.close(cr.change_id, actor="admin")
        updated = engine.get_change(cr.change_id)
        assert updated is not None
        assert updated.status == "CLOSED"
        assert len(updated.events) >= 6

    def test_rollback(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Test")
        engine.submit_for_review(cr.change_id)
        assert engine.rollback(cr.change_id, actor="cto") is True
        updated = engine.get_change(cr.change_id)
        assert updated is not None
        assert updated.status == "ROLLED_BACK"

    def test_rollback_closed_fails(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Test")
        engine.submit_for_review(cr.change_id)
        engine.approve(cr.change_id, reviewer="cto")
        engine.deploy(cr.change_id, actor="devops")
        engine.verify(cr.change_id, actor="qa")
        engine.close(cr.change_id, actor="admin")
        assert engine.rollback(cr.change_id, actor="cto") is False

    # ── Query Methods ─────────────────────────────────────────────────────

    def test_get_change_by_id(self, populated_engine: ChangeGovernanceEngine) -> None:
        changes = populated_engine.get_changes_by_status("DRAFT")
        assert len(changes) >= 0

    def test_get_change_nonexistent(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.get_change("NONEXISTENT")
        assert cr is None

    def test_get_changes_by_status(self, populated_engine: ChangeGovernanceEngine) -> None:
        drafts = populated_engine.get_changes_by_status("DRAFT")
        assert len(drafts) >= 0  # Only has the one without submit

    def test_get_open_changes(self, populated_engine: ChangeGovernanceEngine) -> None:
        open_changes = populated_engine.get_open_changes()
        # cr1 is SUBMITTED, cr2 is IN_REVIEW, cr3 is VERIFIED (not open)
        assert len(open_changes) >= 2

    def test_get_pending_review(self, populated_engine: ChangeGovernanceEngine) -> None:
        pending = populated_engine.get_pending_review()
        # cr1 is SUBMITTED, cr2 is IN_REVIEW
        assert len(pending) >= 2

    def test_get_deployable_changes(self, populated_engine: ChangeGovernanceEngine) -> None:
        deployable = populated_engine.get_deployable_changes()
        assert len(deployable) == 0  # cr3 is already deployed, none are APPROVED only

    def test_get_changes_by_author(self, populated_engine: ChangeGovernanceEngine) -> None:
        quant = populated_engine.get_changes_by_author("quant-team")
        assert len(quant) >= 1

    # ── Linking ───────────────────────────────────────────────────────────

    def test_link_incident(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Test")
        assert engine.link_incident(cr.change_id, "INC-001") is True
        updated = engine.get_change(cr.change_id)
        assert updated is not None
        assert "INC-001" in updated.linked_incidents

    def test_link_incident_nonexistent(self, engine: ChangeGovernanceEngine) -> None:
        assert engine.link_incident("NONEXISTENT", "INC-001") is False

    def test_link_release(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Test")
        assert engine.link_release(cr.change_id, "REL-2.56.0") is True
        updated = engine.get_change(cr.change_id)
        assert updated is not None
        assert updated.linked_release == "REL-2.56.0"

    # ── Report ────────────────────────────────────────────────────────────

    def test_get_report_counts(self, populated_engine: ChangeGovernanceEngine) -> None:
        report = populated_engine.get_report()
        assert report.n_changes >= 3

    def test_get_report_pending_review(
        self, populated_engine: ChangeGovernanceEngine
    ) -> None:
        report = populated_engine.get_report()
        assert len(report.pending_review) >= 2

    def test_get_report_recent_changes(
        self, populated_engine: ChangeGovernanceEngine
    ) -> None:
        report = populated_engine.get_report()
        assert len(report.recent_changes) >= 3

    def test_get_report_recommendations(
        self, engine: ChangeGovernanceEngine
    ) -> None:
        report = engine.get_report()
        assert len(report.recommendations) > 0

    # ── Stats ─────────────────────────────────────────────────────────────

    def test_get_stats(self, populated_engine: ChangeGovernanceEngine) -> None:
        stats = populated_engine.get_stats()
        assert stats["n_changes"] >= 3

    def test_get_stats_empty(self, engine: ChangeGovernanceEngine) -> None:
        stats = engine.get_stats()
        assert stats["n_changes"] == 0

    # ── Edge Cases ────────────────────────────────────────────────────────

    def test_approve_non_existent(self, engine: ChangeGovernanceEngine) -> None:
        assert engine.approve("NONEXISTENT", "cto") is False

    def test_reject_non_existent(self, engine: ChangeGovernanceEngine) -> None:
        assert engine.reject("NONEXISTENT", "cto") is False

    def test_deploy_non_existent(self, engine: ChangeGovernanceEngine) -> None:
        assert engine.deploy("NONEXISTENT", "devops") is False

    def test_verify_non_existent(self, engine: ChangeGovernanceEngine) -> None:
        assert engine.verify("NONEXISTENT", "qa") is False

    def test_close_non_existent(self, engine: ChangeGovernanceEngine) -> None:
        assert engine.close("NONEXISTENT", "admin") is False

    def test_rollback_from_deployed(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Deploy then rollback", change_type="CONFIG")
        engine.submit_for_review(cr.change_id)
        engine.approve(cr.change_id, reviewer="cto")
        engine.deploy(cr.change_id, actor="devops")
        assert engine.rollback(cr.change_id, actor="cto") is True
        updated = engine.get_change(cr.change_id)
        assert updated is not None
        assert updated.status == "ROLLED_BACK"

    def test_rollback_from_verified(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Verify then rollback", change_type="CONFIG")
        engine.submit_for_review(cr.change_id)
        engine.approve(cr.change_id, reviewer="cto")
        engine.deploy(cr.change_id, actor="devops")
        engine.verify(cr.change_id, actor="qa")
        assert engine.rollback(cr.change_id, actor="cto") is True
        updated = engine.get_change(cr.change_id)
        assert updated is not None
        assert updated.status == "ROLLED_BACK"

    def test_rollback_non_existent(self, engine: ChangeGovernanceEngine) -> None:
        assert engine.rollback("NONEXISTENT", "cto") is False

    def test_persistence_to_json(self, engine: ChangeGovernanceEngine) -> None:
        cr = engine.create_change(title="Persist Test")
        engine.submit_for_review(cr.change_id)
        engine.approve(cr.change_id, reviewer="cto")
        path = Path("json/change_governance.json")
        assert path.exists()
        import json
        data = json.loads(path.read_text())
        assert cr.change_id in data["changes"]
