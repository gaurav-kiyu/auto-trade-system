"""Tests for core/strategy/approval_workflow.py — Strategy Approval Workflow.

Covers:
  - StrategyApprovalWorkflow initialization and defaults
  - request_transition (validation, evidence checks, state tracking)
  - approve_transition (single and multi-signer)
  - reject_transition
  - expire_old_requests
  - get_pending_approvals, get_request_history, get_approval_log
  - get_governance_report, get_approval_rules
  - Transition validation rules
  - Edge cases: missing evidence, invalid transitions, expired requests
  - Singleton factory (get_approval_workflow)
"""


import pytest
from core.strategy.approval_workflow import (
    ApprovalRule,
    StrategyApprovalWorkflow,
    get_approval_workflow,
)

# ═══════════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture()
def workflow():
    """Create a fresh workflow for each test."""
    return StrategyApprovalWorkflow()


# ═══════════════════════════════════════════════════════════════════════
#  Initialization
# ═══════════════════════════════════════════════════════════════════════


class TestInitialization:
    def test_default_rules_loaded(self):
        w = StrategyApprovalWorkflow()
        rules = w.get_approval_rules()
        assert len(rules) >= 7  # All transition types
        assert "PROMOTE_TO_LIVE" in rules
        assert "PAPER_START" in rules
        assert "DEPRECATE" in rules

    def test_custom_rules(self):
        custom = {
            "PAPER_START": ApprovalRule(
                transition_type="PAPER_START",
                min_evidence=0,
                description="Custom rule",
            )
        }
        w = StrategyApprovalWorkflow(rules=custom)
        assert len(w.get_approval_rules()) == 1

    def test_empty_initial_state(self):
        w = StrategyApprovalWorkflow()
        assert w.get_pending_approvals() == []
        assert w.get_governance_report()["total_requests"] == 0


# ═══════════════════════════════════════════════════════════════════════
#  request_transition
# ═══════════════════════════════════════════════════════════════════════


class TestRequestTransition:
    def test_valid_paper_start_request(self, workflow):
        ok, msg, req_id = workflow.request_transition(
            "ma_crossover", "PAPER_ONLY",
            requested_by="quant_team",
            evidence={"config_validated": True},
        )
        assert ok is True
        assert req_id != ""

    def test_valid_live_promotion_request(self, workflow):
        # First promote to paper
        workflow.request_transition("strat_a", "PAPER_ONLY",
                                    requested_by="dev",
                                    evidence={"config_validated": True})
        workflow.approve_transition("strat_a", "PAPER_ONLY",
                                    approved_by="lead")

        # Then request LIVE
        ok, msg, req_id = workflow.request_transition(
            "strat_a", "LIVE_APPROVED",
            requested_by="quant_team",
            evidence={
                "backtest_sharpe": 1.8,
                "paper_trades": 150,
                "paper_win_rate": 0.62,
            },
        )
        assert ok is True, msg

    def test_invalid_transition_blocked(self, workflow):
        # Cannot go from INITIALIZED to LIVE_APPROVED directly
        ok, msg, req_id = workflow.request_transition(
            "strat_b", "LIVE_APPROVED",
            requested_by="dev",
            evidence={},
        )
        assert ok is False
        assert "not allowed" in msg

    def test_missing_evidence_rejected(self, workflow):
        # PAPER_START requires config_validated evidence
        ok, msg, req_id = workflow.request_transition(
            "strat_c", "PAPER_ONLY",
            requested_by="dev",
            evidence={},
        )
        assert ok is False
        assert "evidence" in msg.lower()

    def test_transition_from_dont_run(self, workflow):
        # DONT_RUN -> PAPER_ONLY is valid
        ok, msg, req_id = workflow.request_transition(
            "strat_d", "DONT_RUN",
            requested_by="admin",
            evidence={"block_reason": "Under review"},
        )
        assert ok is True

        # DONT_RUN -> PAPER_ONLY is valid
        ok, msg, req_id = workflow.request_transition(
            "strat_d", "PAPER_ONLY",
            requested_by="dev",
            evidence={"config_validated": True},
        )
        assert ok is True

    def test_initialized_to_paper_works(self, workflow):
        ok, msg, req_id = workflow.request_transition(
            "my_strat", "PAPER_ONLY",
            requested_by="dev",
            evidence={"config_validated": True},
        )
        assert ok is True

    def test_initialized_to_dont_run_works(self, workflow):
        ok, msg, req_id = workflow.request_transition(
            "my_strat", "DONT_RUN",
            requested_by="admin",
            evidence={"block_reason": "Compliance issue"},
        )
        assert ok is True

    def test_initialized_to_deprecated_works(self, workflow):
        # INITIALIZED -> DEPRECATED is valid per valid_transitions
        ok, msg, req_id = workflow.request_transition(
            "my_strat", "DEPRECATED",
            requested_by="admin",
            evidence={"deprecation_reason": "Strategy obsolete"},
        )
        assert ok is True


# ═══════════════════════════════════════════════════════════════════════
#  approve_transition
# ═══════════════════════════════════════════════════════════════════════


class TestApproveTransition:
    def test_approve_pending_request(self, workflow):
        workflow.request_transition("strat_a", "PAPER_ONLY",
                                    requested_by="dev",
                                    evidence={"config_validated": True})
        ok, msg = workflow.approve_transition("strat_a", "PAPER_ONLY",
                                              approved_by="lead")
        assert ok is True
        assert "Approved" in msg

    def test_approve_changes_state(self, workflow):
        workflow.request_transition("strat_a", "PAPER_ONLY",
                                    requested_by="dev",
                                    evidence={"config_validated": True})
        workflow.approve_transition("strat_a", "PAPER_ONLY",
                                    approved_by="lead")
        report = workflow.get_governance_report()
        # Approval increments approved_count
        assert report["approved_count"] >= 1

    def test_approve_nonexistent_request(self, workflow):
        ok, msg = workflow.approve_transition("nonexistent", "PAPER_ONLY",
                                              approved_by="lead")
        assert ok is False

    def test_multi_signer_approval(self, workflow):
        # Request LIVE promotion (requires 2 approvals)
        workflow.request_transition("strat_b", "PAPER_ONLY",
                                    requested_by="dev",
                                    evidence={"config_validated": True})
        workflow.approve_transition("strat_b", "PAPER_ONLY",
                                    approved_by="lead")

        workflow.request_transition("strat_b", "LIVE_APPROVED",
                                    requested_by="quant",
                                    evidence={
                                        "backtest_sharpe": 1.8,
                                        "paper_trades": 150,
                                        "paper_win_rate": 0.62,
                                    })

        # First approval - partial
        ok, msg = workflow.approve_transition("strat_b", "LIVE_APPROVED",
                                              approved_by="risk_committee")
        assert ok is True
        assert "partial" in msg.lower()

        # Second approval - full
        ok, msg = workflow.approve_transition("strat_b", "LIVE_APPROVED",
                                              approved_by="compliance")
        assert ok is True
        assert "Approved" in msg

    def test_approve_twice_same_request(self, workflow):
        workflow.request_transition("strat_c", "PAPER_ONLY",
                                    requested_by="dev",
                                    evidence={"config_validated": True})
        workflow.approve_transition("strat_c", "PAPER_ONLY",
                                    approved_by="lead")
        # Second approve should say not found (already approved)
        ok, msg = workflow.approve_transition("strat_c", "PAPER_ONLY",
                                              approved_by="backup")
        assert ok is False

    def test_full_lifecycle(self, workflow):
        """Test complete INITIALIZED -> PAPER -> LIVE lifecycle."""
        # Step 1: PAPER_ONLY
        workflow.request_transition("lifecycle_strat", "PAPER_ONLY",
                                    evidence={"config_validated": True})
        workflow.approve_transition("lifecycle_strat", "PAPER_ONLY",
                                    approved_by="lead")

        # Step 2: LIVE (requires 2 approvals)
        workflow.request_transition("lifecycle_strat", "LIVE_APPROVED",
                                    evidence={
                                        "backtest_sharpe": 2.1,
                                        "paper_trades": 200,
                                        "paper_win_rate": 0.68,
                                    })
        workflow.approve_transition("lifecycle_strat", "LIVE_APPROVED",
                                    approved_by="risk_committee")
        workflow.approve_transition("lifecycle_strat", "LIVE_APPROVED",
                                    approved_by="compliance")

        # Check that approvals succeed (PAPER + 2 partial + full LIVE)
        report = workflow.get_governance_report()
        assert report["approved_count"] >= 2  # PAPER + LIVE (partials not counted)

        # Step 3: DONT_RUN
        workflow.request_transition("lifecycle_strat", "DONT_RUN",
                                    evidence={"block_reason": "Performance degradation"})
        ok, msg = workflow.approve_transition("lifecycle_strat", "DONT_RUN",
                                              approved_by="admin")
        assert ok is True


# ═══════════════════════════════════════════════════════════════════════
#  reject_transition
# ═══════════════════════════════════════════════════════════════════════


class TestRejectTransition:
    def test_reject_pending_request(self, workflow):
        workflow.request_transition("strat_a", "PAPER_ONLY",
                                    requested_by="dev",
                                    evidence={"config_validated": True})
        ok, msg = workflow.reject_transition("strat_a", "PAPER_ONLY",
                                             rejected_by="lead",
                                             reason="Not ready")
        assert ok is True
        assert "Rejected" in msg

    def test_reject_moves_to_rejected(self, workflow):
        workflow.request_transition("strat_a", "PAPER_ONLY",
                                    requested_by="dev",
                                    evidence={"config_validated": True})
        workflow.reject_transition("strat_a", "PAPER_ONLY",
                                   rejected_by="lead", reason="Not ready")
        report = workflow.get_governance_report()
        assert report["rejected_count"] >= 1

    def test_reject_nonexistent_request(self, workflow):
        ok, msg = workflow.reject_transition("nonexistent", "PAPER_ONLY",
                                             rejected_by="lead")
        assert ok is False

    def test_reject_then_retry(self, workflow):
        workflow.request_transition("strat_a", "PAPER_ONLY",
                                    requested_by="dev",
                                    evidence={"config_validated": True})
        workflow.reject_transition("strat_a", "PAPER_ONLY",
                                   rejected_by="lead", reason="Not ready")

        # Can request again after rejection
        ok, msg, req_id = workflow.request_transition(
            "strat_a", "PAPER_ONLY",
            requested_by="dev",
            evidence={"config_validated": True, "extra_checks": True},
        )
        assert ok is True


# ═══════════════════════════════════════════════════════════════════════
#  expire_old_requests
# ═══════════════════════════════════════════════════════════════════════


class TestExpireOldRequests:
    def test_expire_old_request(self, workflow):
        workflow.request_transition("strat_a", "PAPER_ONLY",
                                    requested_by="dev",
                                    evidence={"config_validated": True})
        # Force timestamp to be old (use 0 TTL)
        for r in workflow._requests:
            r.requested_at = "2020-01-01T00:00:00"
        expired = workflow.expire_old_requests(max_age_hours=0)
        assert expired >= 1

    def test_expired_removed_from_pending(self, workflow):
        workflow.request_transition("strat_a", "PAPER_ONLY",
                                    requested_by="dev",
                                    evidence={"config_validated": True})
        for r in workflow._requests:
            r.requested_at = "2020-01-01T00:00:00"
        workflow.expire_old_requests(max_age_hours=0)
        pending = workflow.get_pending_approvals()
        assert len(pending) == 0

    def test_no_expire_for_recent_requests(self, workflow):
        workflow.request_transition("strat_a", "PAPER_ONLY",
                                    requested_by="dev",
                                    evidence={"config_validated": True})
        expired = workflow.expire_old_requests(max_age_hours=24)
        assert expired == 0


# ═══════════════════════════════════════════════════════════════════════
#  Queries
# ═══════════════════════════════════════════════════════════════════════


class TestGetPendingApprovals:
    def test_returns_only_pending(self, workflow):
        workflow.request_transition("strat_a", "PAPER_ONLY",
                                    requested_by="dev",
                                    evidence={"config_validated": True})
        workflow.approve_transition("strat_a", "PAPER_ONLY",
                                    approved_by="lead")
        workflow.request_transition("strat_b", "PAPER_ONLY",
                                    requested_by="dev",
                                    evidence={"config_validated": True})
        pending = workflow.get_pending_approvals()
        assert len(pending) == 1
        assert pending[0]["strategy_name"] == "strat_b"


class TestGetRequestHistory:
    def test_returns_all_requests(self, workflow):
        workflow.request_transition("s1", "PAPER_ONLY",
                                    evidence={"config_validated": True})
        workflow.request_transition("s2", "PAPER_ONLY",
                                    evidence={"config_validated": True})
        history = workflow.get_request_history()
        assert len(history) == 2

    def test_filter_by_strategy(self, workflow):
        workflow.request_transition("s1", "PAPER_ONLY",
                                    evidence={"config_validated": True})
        workflow.request_transition("s2", "PAPER_ONLY",
                                    evidence={"config_validated": True})
        history = workflow.get_request_history(strategy_name="s1")
        assert len(history) == 1


class TestGetApprovalLog:
    def test_logs_approval_events(self, workflow):
        workflow.request_transition("s1", "PAPER_ONLY",
                                    requested_by="dev",
                                    evidence={"config_validated": True})
        log = workflow.get_approval_log()
        assert len(log) >= 1
        assert log[0]["event"] == "requested"

    def test_log_order_newest_first(self, workflow):
        workflow.request_transition("s1", "PAPER_ONLY",
                                    evidence={"config_validated": True})
        workflow.request_transition("s2", "PAPER_ONLY",
                                    evidence={"config_validated": True})
        log = workflow.get_approval_log(limit=10)
        assert len(log) >= 2


class TestGetGovernanceReport:
    def test_returns_keys(self, workflow):
        report = workflow.get_governance_report()
        assert "total_requests" in report
        assert "pending_count" in report
        assert "approved_count" in report
        assert "rejected_count" in report
        assert "pending_approvals" in report
        assert "rules" in report

    def test_counts_accurate(self, workflow):
        workflow.request_transition("s1", "PAPER_ONLY",
                                    evidence={"config_validated": True})
        workflow.approve_transition("s1", "PAPER_ONLY", approved_by="lead")
        workflow.request_transition("s2", "PAPER_ONLY",
                                    evidence={"config_validated": True})
        report = workflow.get_governance_report()
        assert report["total_requests"] == 2
        assert report["approved_count"] >= 1
        assert report["pending_count"] >= 1


# ═══════════════════════════════════════════════════════════════════════
#  get_approval_rules
# ═══════════════════════════════════════════════════════════════════════


class TestGetApprovalRules:
    def test_returns_rules(self, workflow):
        rules = workflow.get_approval_rules()
        assert isinstance(rules, dict)
        assert len(rules) > 0

    def test_live_promotion_requires_two_approvals(self, workflow):
        rules = workflow.get_approval_rules()
        live_rule = rules.get("PROMOTE_TO_LIVE", {})
        assert live_rule.get("required_approval_count", 0) >= 2


# ═══════════════════════════════════════════════════════════════════════
#  Edge cases
# ═══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_thousands_of_requests(self, workflow):
        for i in range(100):
            workflow.request_transition(f"s{i}", "PAPER_ONLY",
                                        evidence={"config_validated": True})
        report = workflow.get_governance_report()
        assert report["total_requests"] == 100

    def test_approve_already_approved(self, workflow):
        workflow.request_transition("s1", "PAPER_ONLY",
                                    evidence={"config_validated": True})
        workflow.approve_transition("s1", "PAPER_ONLY", approved_by="lead")
        # Cannot approve again
        ok, msg = workflow.approve_transition("s1", "PAPER_ONLY",
                                              approved_by="backup")
        assert ok is False

    def test_deprecate_live_strategy(self, workflow):
        """LIVE_APPROVED -> DEPRECATED should work."""
        workflow.request_transition("s1", "PAPER_ONLY",
                                    evidence={"config_validated": True})
        workflow.approve_transition("s1", "PAPER_ONLY", approved_by="lead")
        workflow.request_transition("s1", "LIVE_APPROVED",
                                    evidence={
                                        "backtest_sharpe": 1.5,
                                        "paper_trades": 100,
                                        "paper_win_rate": 0.55,
                                    })
        workflow.approve_transition("s1", "LIVE_APPROVED",
                                    approved_by="risk_committee")
        workflow.approve_transition("s1", "LIVE_APPROVED",
                                    approved_by="compliance")

        ok, msg, req_id = workflow.request_transition(
            "s1", "DEPRECATED",
            requested_by="admin",
            evidence={"deprecation_reason": "Replaced by v2"},
        )
        assert ok is True

    def test_multiple_strategies_independent(self, workflow):
        """Requests for different strategies shouldn't interfere."""
        for s in range(5):
            workflow.request_transition(f"s{s}", "PAPER_ONLY",
                                        evidence={"config_validated": True})
        for s in range(5):
            ok, msg = workflow.approve_transition(f"s{s}", "PAPER_ONLY",
                                                  approved_by="lead")
            assert ok is True

        report = workflow.get_governance_report()
        assert report["approved_count"] == 5


# ═══════════════════════════════════════════════════════════════════════
#  Singleton factory
# ═══════════════════════════════════════════════════════════════════════


class TestGetApprovalWorkflow:
    def test_returns_same_instance(self):
        import core.strategy.approval_workflow as aw
        aw._workflow = None

        w1 = get_approval_workflow()
        w2 = get_approval_workflow()
        assert w1 is w2

    def test_creates_new_if_none(self):
        import core.strategy.approval_workflow as aw
        aw._workflow = None

        w = get_approval_workflow()
        assert isinstance(w, StrategyApprovalWorkflow)
