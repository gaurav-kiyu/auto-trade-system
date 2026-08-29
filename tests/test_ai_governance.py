"""Tests for AIGovernanceBoard — central AI governance for model lifecycle."""

from __future__ import annotations

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def governance():
    """Create an AIGovernanceBoard with default sub-components."""
    from core.ai.governance import AIGovernanceBoard
    return AIGovernanceBoard()


@pytest.fixture
def governance_with_model(governance):
    """Create a governance board with a registered DRAFT model."""
    governance.register_model(
        model_id="model-v1",
        version="1.0.0",
        name="signal_classifier",
        source_path="/models/v1.pkl",
        checksum="abc123",
        metrics={"accuracy": 0.85, "f1": 0.82},
        metadata={"author": "ml-team", "dataset": "training_2026"},
    )
    return governance


# ──────────────────────────────────────────────────────────────────────────────
# Model Registration
# ──────────────────────────────────────────────────────────────────────────────


class TestModelRegistration:
    def test_register_model(self, governance):
        governance.register_model(
            model_id="model-v1",
            version="1.0.0",
            name="signal_classifier",
        )
        status = governance.get_status("model-v1")
        assert status["model_id"] == "model-v1"
        assert status["version"] == "1.0.0"
        assert status["status"] == "DRAFT"

    def test_register_model_with_metadata(self, governance):
        governance.register_model(
            model_id="model-v2",
            version="2.0.0",
            name="exit_classifier",
            source_path="/models/v2.pkl",
            checksum="def456",
            metrics={"accuracy": 0.88},
            metadata={"train_date": "2026-07-01"},
        )
        status = governance.get_status("model-v2")
        assert status["name"] == "exit_classifier"
        assert "metrics" in status
        # Verify source_path is stored in the registry
        rec = governance.model_registry.get("model-v2")
        assert rec is not None
        assert rec.source_path == "/models/v2.pkl"

    def test_register_duplicate_model_id(self, governance_with_model):
        """Registering with same ID should update (upsert)."""
        governance_with_model.register_model(
            model_id="model-v1",
            version="1.0.1",
            name="signal_classifier",
        )
        status = governance_with_model.get_status("model-v1")
        assert status["version"] == "1.0.1"

    def test_get_nonexistent_model(self, governance):
        status = governance.get_status("nonexistent")
        assert "error" in status

    def test_register_multiple_versions(self, governance):
        governance.register_model("m1", "1.0", "classifier")
        governance.register_model("m2", "2.0", "classifier")
        assert governance.get_status("m1") is not None
        assert governance.get_status("m2") is not None


# ──────────────────────────────────────────────────────────────────────────────
# Canary Approval & Rollout
# ──────────────────────────────────────────────────────────────────────────────


class TestCanaryApproval:
    def test_approve_for_canary(self, governance_with_model):
        governance_with_model.approve_for_canary("model-v1", approved_by="admin")
        status = governance_with_model.get_status("model-v1")
        assert status["status"] == "CANARY"

    def test_approve_nonexistent_model(self, governance):
        from core.ai.governance import AIGovernanceError
        with pytest.raises(AIGovernanceError, match="not found"):
            governance.approve_for_canary("nonexistent", approved_by="admin")

    def test_approve_already_canary(self, governance_with_model):
        from core.ai.governance import AIGovernanceError
        governance_with_model.approve_for_canary("model-v1")
        with pytest.raises(AIGovernanceError, match="expected DRAFT"):
            governance_with_model.approve_for_canary("model-v1")

    def test_canary_tracks_trades(self, governance_with_model):
        governance_with_model.approve_for_canary("model-v1")
        status = governance_with_model.get_status("model-v1")
        assert status["canary"] is not None
        assert status["canary"]["trades_seen"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# Promotion to Active
# ──────────────────────────────────────────────────────────────────────────────


class TestPromotion:
    def test_promote_to_active(self, governance_with_model):
        governance_with_model.approve_for_canary("model-v1")
        # Simulate enough canary trades by setting internal state
        canary = governance_with_model.canary_manager.get_state("model-v1")
        if canary:
            canary.trades_seen = 20
            canary.trades_won = 12  # 60% win rate

        governance_with_model.promote_to_active("model-v1", min_trades=20, min_win_rate=0.55)
        status = governance_with_model.get_status("model-v1")
        assert status["status"] == "ACTIVE"

    def test_promote_not_enough_trades(self, governance_with_model):
        governance_with_model.approve_for_canary("model-v1")
        from core.ai.governance import AIGovernanceError
        with pytest.raises(AIGovernanceError, match="not ready"):
            governance_with_model.promote_to_active("model-v1", min_trades=20, min_win_rate=0.55)

    def test_promote_nonexistent(self, governance):
        from core.ai.governance import AIGovernanceError
        with pytest.raises(AIGovernanceError):
            governance.promote_to_active("nonexistent")

    def test_promote_draft_model(self, governance_with_model):
        """DRAFT models should not be promotable — must go through canary first."""
        from core.ai.governance import AIGovernanceError
        with pytest.raises(AIGovernanceError, match="expected CANARY"):
            governance_with_model.promote_to_active("model-v1")

    def test_promote_deprecates_previous_active(self, governance_with_model):
        """Promoting a new model should deprecate the previous active one."""
        # Register v1, approve, promote
        governance_with_model.approve_for_canary("model-v1")
        canary = governance_with_model.canary_manager.get_state("model-v1")
        if canary:
            canary.trades_seen = 20
            canary.trades_won = 12
        governance_with_model.promote_to_active("model-v1")

        # Register v2, approve, promote
        governance_with_model.register_model("model-v2", "2.0", "signal_classifier")
        governance_with_model.approve_for_canary("model-v2")
        canary2 = governance_with_model.canary_manager.get_state("model-v2")
        if canary2:
            canary2.trades_seen = 20
            canary2.trades_won = 12
        governance_with_model.promote_to_active("model-v2")

        # v1 should now be DEPRECATED
        v1 = governance_with_model.get_status("model-v1")
        assert v1["status"] == "DEPRECATED"


# ──────────────────────────────────────────────────────────────────────────────
# Rollback
# ──────────────────────────────────────────────────────────────────────────────


class TestRollback:
    def test_manual_rollback(self, governance_with_model):
        governance_with_model.approve_for_canary("model-v1")
        canary = governance_with_model.canary_manager.get_state("model-v1")
        if canary:
            canary.trades_seen = 20
            canary.trades_won = 12
        governance_with_model.promote_to_active("model-v1")
        governance_with_model.rollback("model-v1", reason="test rollback")
        status = governance_with_model.get_status("model-v1")
        assert status["status"] == "ROLLED_BACK"

    def test_rollback_nonexistent(self, governance):
        from core.ai.governance import AIGovernanceError
        with pytest.raises(AIGovernanceError):
            governance.rollback("nonexistent")

    def test_auto_rollback_on_drift(self, governance_with_model):
        """Auto-rollback should trigger when metrics breach thresholds."""
        governance_with_model.approve_for_canary("model-v1")
        triggered = governance_with_model.evaluate_and_auto_rollback(
            "model-v1",
            {"accuracy": 0.3, "drift_score": 2.5},
        )
        assert triggered
        status = governance_with_model.get_status("model-v1")
        assert status["status"] == "ROLLED_BACK"

    def test_auto_rollback_healthy_metrics(self, governance_with_model):
        """Healthy metrics should not trigger rollback."""
        governance_with_model.approve_for_canary("model-v1")
        triggered = governance_with_model.evaluate_and_auto_rollback(
            "model-v1",
            {"accuracy": 0.85, "f1": 0.82},
        )
        assert not triggered

    def test_auto_rollback_nonexistent(self, governance):
        triggered = governance.evaluate_and_auto_rollback("nonexistent", {})
        assert not triggered


# ──────────────────────────────────────────────────────────────────────────────
# Audit Logging
# ──────────────────────────────────────────────────────────────────────────────


class TestAuditLog:
    def test_audit_log_records_actions(self, governance_with_model):
        log = governance_with_model.get_audit_log()
        assert len(log) >= 1  # register action
        assert log[0]["action"] == "register"
        assert log[0]["model_id"] == "model-v1"

    def test_audit_log_approval(self, governance_with_model):
        governance_with_model.approve_for_canary("model-v1", approved_by="admin")
        log = governance_with_model.get_audit_log()
        actions = [entry["action"] for entry in log]
        assert "approve_canary" in actions

    def test_audit_log_promotion(self, governance_with_model):
        governance_with_model.approve_for_canary("model-v1")
        canary = governance_with_model.canary_manager.get_state("model-v1")
        if canary:
            canary.trades_seen = 20
            canary.trades_won = 12
        governance_with_model.promote_to_active("model-v1")
        log = governance_with_model.get_audit_log()
        actions = [entry["action"] for entry in log]
        assert "promote_active" in actions

    def test_audit_log_rollback(self, governance_with_model):
        governance_with_model.approve_for_canary("model-v1")
        canary = governance_with_model.canary_manager.get_state("model-v1")
        if canary:
            canary.trades_seen = 20
            canary.trades_won = 12
        governance_with_model.promote_to_active("model-v1")
        governance_with_model.rollback("model-v1", reason="degradation")
        log = governance_with_model.get_audit_log()
        actions = [entry["action"] for entry in log]
        assert "rollback" in actions

    def test_audit_log_limit(self, governance_with_model):
        for i in range(10):
            governance_with_model.register_model(f"m{i}", "1.0", "test")
        log = governance_with_model.get_audit_log(limit=3)
        assert len(log) <= 3

    def test_audit_log_thread_safety(self, governance):
        """Multiple registrations should not corrupt audit log."""
        import threading
        errors = []

        def register():
            try:
                for i in range(20):
                    governance.register_model(f"t{i}", "1.0", "test")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        log = governance.get_audit_log()
        assert len(log) >= 100  # 5 threads x 20 models each


# ──────────────────────────────────────────────────────────────────────────────
# Governance Status
# ──────────────────────────────────────────────────────────────────────────────


class TestGovernanceStatus:
    def test_status_draft(self, governance_with_model):
        status = governance_with_model.get_status("model-v1")
        assert status["status"] == "DRAFT"
        assert "canary" in status
        assert "recent_rollbacks" in status

    def test_status_includes_metrics(self, governance_with_model):
        status = governance_with_model.get_status("model-v1")
        assert "metrics" in status

    def test_status_of_promoted_model(self, governance_with_model):
        governance_with_model.approve_for_canary("model-v1")
        canary = governance_with_model.canary_manager.get_state("model-v1")
        if canary:
            canary.trades_seen = 20
            canary.trades_won = 12
        governance_with_model.promote_to_active("model-v1")
        status = governance_with_model.get_status("model-v1")
        assert status["status"] == "ACTIVE"
        assert status["canary"] is None  # Canary ended after promotion


# ──────────────────────────────────────────────────────────────────────────────
# Error Handling
# ──────────────────────────────────────────────────────────────────────────────


class TestErrorHandling:
    def test_governance_error_is_exception(self):
        from core.ai.governance import AIGovernanceError
        assert issubclass(AIGovernanceError, Exception)

    def test_approve_canary_without_approver(self, governance_with_model):
        """approve_for_canary should work without approved_by."""
        governance_with_model.approve_for_canary("model-v1")  # Should not raise
        status = governance_with_model.get_status("model-v1")
        assert status["status"] == "CANARY"

    def test_multiple_models_independent(self, governance):
        """Different models should have independent state."""
        governance.register_model("m1", "1.0", "model_a")
        governance.register_model("m2", "1.0", "model_b")
        governance.approve_for_canary("m1")
        s1 = governance.get_status("m1")
        s2 = governance.get_status("m2")
        assert s1["status"] == "CANARY"
        assert s2["status"] == "DRAFT"

    def test_full_lifecycle(self, governance):
        """Complete DRAFT -> CANARY -> ACTIVE -> ROLLED_BACK lifecycle."""
        governance.register_model("lifecycle", "1.0.0", "test_model")
        assert governance.get_status("lifecycle")["status"] == "DRAFT"

        governance.approve_for_canary("lifecycle")
        assert governance.get_status("lifecycle")["status"] == "CANARY"

        canary = governance.canary_manager.get_state("lifecycle")
        if canary:
            canary.trades_seen = 20
            canary.trades_won = 12
        governance.promote_to_active("lifecycle")
        assert governance.get_status("lifecycle")["status"] == "ACTIVE"

        governance.rollback("lifecycle", reason="performance_degradation")
        assert governance.get_status("lifecycle")["status"] == "ROLLED_BACK"
