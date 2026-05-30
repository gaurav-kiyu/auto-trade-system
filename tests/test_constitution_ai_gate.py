"""
Tests for core/constitution_ai_gate.py — AI Governance Gate.

Covers:
  - AIGateResult construction
  - AIGovernanceGate.validate() with various param combinations
  - Forbidden file modification detection
  - Risk control keyword scanning
  - Broker SDK pattern detection
  - Score evidence enforcement
  - Constitution acknowledgement
  - Forbidden action detection
  - Audit log recording
  - Singleton get_gate()
  - validate_ai_action helper
"""
from __future__ import annotations

from pathlib import Path

import pytest
from core.constitution_ai_gate import (
    AIGateResult,
    AIGovernanceGate,
    BYPASS_PATTERNS,
    FORBIDDEN_FILE_TARGETS,
    RISK_CONTROL_KEYWORDS,
    get_gate,
    validate_ai_action,
)


# ── AIGateResult ──────────────────────────────────────────────────────────────


class TestAIGateResult:
    def test_default_passed_is_false(self) -> None:
        r = AIGateResult()
        assert r.passed is False

    def test_passed_result(self) -> None:
        r = AIGateResult(passed=True, reason="OK")
        assert r.passed
        assert r.reason == "OK"

    def test_timestamp_auto_set(self) -> None:
        r = AIGateResult(passed=True)
        assert r.timestamp > 0

    def test_failures_list(self) -> None:
        r = AIGateResult(passed=False, failures=["err1", "err2"])
        assert len(r.failures) == 2
        assert "err1" in r.failures

    def test_identity(self) -> None:
        r = AIGateResult(passed=True, identity="test_agent")
        assert r.identity == "test_agent"


# ── AIGovernanceGate — validate ───────────────────────────────────────────────


class TestGateValidate:
    def test_all_checks_pass(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.validate(
            constitution_acknowledged=True,
            claude_read=True,
            architecture_reviewed=True,
            audit_history_reviewed=True,
            risk_controls_verified=True,
            changed_files=["core/foo.py"],
        )
        assert result.passed, f"Expected passed, got: {result.failures}"

    def test_all_checks_fail(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.validate()
        assert not result.passed
        assert len(result.failures) >= 5  # 5 context checks + affected files

    def test_constitution_not_acknowledged(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.validate(constitution_acknowledged=False)
        assert not result.passed
        assert any("Constitution not acknowledged" in f for f in result.failures)

    def test_claude_not_read(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.validate(constitution_acknowledged=True, claude_read=False)
        assert not result.passed
        assert any("CLAUDE.md" in f for f in result.failures)

    def test_architecture_not_reviewed(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.validate(
            constitution_acknowledged=True,
            claude_read=True,
            architecture_reviewed=False,
        )
        assert not result.passed
        assert any("Architecture" in f for f in result.failures)

    def test_audit_history_not_reviewed(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.validate(
            constitution_acknowledged=True,
            claude_read=True,
            audit_history_reviewed=False,
        )
        assert not result.passed
        assert any("audit history" in f.lower() for f in result.failures)

    def test_risk_controls_not_verified(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.validate(
            constitution_acknowledged=True,
            claude_read=True,
            risk_controls_verified=False,
        )
        assert not result.passed
        assert any("risk" in f.lower() for f in result.failures)


class TestGateForbiddenFiles:
    def test_forbidden_file_detection(self) -> None:
        gate = AIGovernanceGate(identity="test")
        # Use a file target from FORBIDDEN_FILE_TARGETS
        target = FORBIDDEN_FILE_TARGETS[0]
        result = gate.validate(
            constitution_acknowledged=True,
            claude_read=True,
            architecture_reviewed=True,
            audit_history_reviewed=True,
            risk_controls_verified=True,
            changed_files=[target],
        )
        assert not result.passed
        assert any("Forbidden file" in f for f in result.failures)

    def test_non_forbidden_file_ok(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.validate(
            constitution_acknowledged=True,
            claude_read=True,
            architecture_reviewed=True,
            audit_history_reviewed=True,
            risk_controls_verified=True,
            changed_files=["core/safe_file.py"],
        )
        assert result.passed


class TestGateRiskControlScanning:
    def test_risk_control_detected(self, tmp_path: Path) -> None:
        # Create a temp file with risk control keyword
        risky_file = tmp_path / "risky.py"
        risky_file.write_text("def _trip_hard_halt(): pass")
        gate = AIGovernanceGate(identity="test")
        result = gate.validate(
            constitution_acknowledged=True,
            claude_read=True,
            architecture_reviewed=True,
            audit_history_reviewed=True,
            risk_controls_verified=True,
            changed_files=[str(risky_file)],
        )
        assert not result.passed
        assert any("_trip_hard_halt" in f for f in result.failures)

    def test_clean_file_no_risk_issues(self, tmp_path: Path) -> None:
        clean_file = tmp_path / "clean.py"
        clean_file.write_text("def hello(): print('hi')")
        gate = AIGovernanceGate(identity="test")
        result = gate.validate(
            constitution_acknowledged=True,
            claude_read=True,
            architecture_reviewed=True,
            audit_history_reviewed=True,
            risk_controls_verified=True,
            changed_files=[str(clean_file)],
        )
        assert result.passed

    def test_non_python_file_skipped(self) -> None:
        gate = AIGovernanceGate(identity="test")
        # .md files have no .py suffix, so scanning should not fail
        result = gate.validate(
            constitution_acknowledged=True,
            claude_read=True,
            architecture_reviewed=True,
            audit_history_reviewed=True,
            risk_controls_verified=True,
            changed_files=["README.md"],
        )
        assert result.passed


class TestGateBrokerSDK:
    def test_broker_sdk_detected(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("from kiteconnect import KiteTicker")
        gate = AIGovernanceGate(identity="test")
        result = gate.validate(
            constitution_acknowledged=True,
            claude_read=True,
            architecture_reviewed=True,
            audit_history_reviewed=True,
            risk_controls_verified=True,
            changed_files=[str(bad_file)],
        )
        assert not result.passed
        assert any("kiteconnect" in f.lower() for f in result.failures)


class TestGateBypassPatterns:
    def test_datetime_now_detected(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "timefile.py"
        bad_file.write_text("from datetime import datetime; dt = datetime.now()")
        gate = AIGovernanceGate(identity="test")
        result = gate.validate(
            constitution_acknowledged=True,
            claude_read=True,
            architecture_reviewed=True,
            audit_history_reviewed=True,
            risk_controls_verified=True,
            changed_files=[str(bad_file)],
        )
        assert not result.passed
        assert any("datetime.now" in f for f in result.failures)


class TestGateScoreEvidence:
    def test_score_above_9_without_evidence_fails(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.validate(
            constitution_acknowledged=True,
            claude_read=True,
            architecture_reviewed=True,
            audit_history_reviewed=True,
            risk_controls_verified=True,
            score_changes={"ARCH-01": 9.5},
            has_evidence=False,
        )
        assert not result.passed
        assert any("9.0" in f for f in result.failures)

    def test_score_above_9_with_evidence_passes(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.validate(
            constitution_acknowledged=True,
            claude_read=True,
            architecture_reviewed=True,
            audit_history_reviewed=True,
            risk_controls_verified=True,
            score_changes={"ARCH-01": 9.5},
            has_evidence=True,
        )
        assert result.passed

    def test_score_above_8_without_evidence_fails(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.validate(
            constitution_acknowledged=True,
            claude_read=True,
            architecture_reviewed=True,
            audit_history_reviewed=True,
            risk_controls_verified=True,
            score_changes={"ARCH-01": 8.5},
            has_evidence=False,
        )
        assert not result.passed
        assert any("8.0" in f for f in result.failures)

    def test_no_score_changes_ok(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.validate(
            constitution_acknowledged=True,
            claude_read=True,
            architecture_reviewed=True,
            audit_history_reviewed=True,
            risk_controls_verified=True,
            score_changes=None,
        )
        assert result.passed

    def test_score_below_8_without_evidence_ok(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.validate(
            constitution_acknowledged=True,
            claude_read=True,
            architecture_reviewed=True,
            audit_history_reviewed=True,
            risk_controls_verified=True,
            score_changes={"ARCH-01": 7.5},
            has_evidence=False,
        )
        assert result.passed


# ── AIGovernanceGate — acknowledge_constitution ───────────────────────────────


class TestGateAcknowledge:
    def test_acknowledge_returns_dict(self) -> None:
        gate = AIGovernanceGate(identity="test")
        ack = gate.acknowledge_constitution()
        assert isinstance(ack, dict)
        assert "acknowledgment" in ack
        assert "timestamp" in ack

    def test_acknowledge_records_audit(self) -> None:
        gate = AIGovernanceGate(identity="test")
        gate.acknowledge_constitution()
        log = gate.get_audit_log()
        assert any(l["action"] == "acknowledge" for l in log)


# ── AIGovernanceGate — check_forbidden_action ─────────────────────────────────


class TestGateForbiddenAction:
    def test_safe_action_allowed(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.check_forbidden_action("Add new feature")
        assert result.passed

    def test_bypass_risk_detected(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.check_forbidden_action("bypass risk controls")
        assert not result.passed
        assert any("bypass risk" in f.lower() for f in result.failures)

    def test_disable_hard_halt_detected(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.check_forbidden_action("disable hard halt for testing")
        assert not result.passed

    def test_skip_documentation_detected(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.check_forbidden_action("skip documentation update")
        assert not result.passed

    def test_commit_without_tests_detected(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.check_forbidden_action("commit without tests")
        assert not result.passed

    def test_modify_ai_governance_detected(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.check_forbidden_action("modify ai governance code")
        assert not result.passed

    def test_case_insensitive_matching(self) -> None:
        gate = AIGovernanceGate(identity="test")
        result = gate.check_forbidden_action("BYPASS RISK CONTROLS NOW")
        assert not result.passed


# ── AIGovernanceGate — audit log ──────────────────────────────────────────────


class TestGateAuditLog:
    def test_validate_records_audit(self) -> None:
        gate = AIGovernanceGate(identity="test")
        gate.validate(constitution_acknowledged=True, claude_read=True,
                       architecture_reviewed=True, audit_history_reviewed=True,
                       risk_controls_verified=True)
        log = gate.get_audit_log()
        assert len(log) >= 1
        assert log[0]["action"] == "validate"

    def test_audit_log_limit(self) -> None:
        gate = AIGovernanceGate(identity="test")
        for _ in range(10):
            gate.acknowledge_constitution()
        log = gate.get_audit_log(limit=3)
        assert len(log) <= 3

    def test_audit_log_format(self) -> None:
        gate = AIGovernanceGate(identity="test")
        gate.validate(constitution_acknowledged=True, claude_read=True,
                       architecture_reviewed=True, audit_history_reviewed=True,
                       risk_controls_verified=True)
        log = gate.get_audit_log()
        entry = log[0]
        assert "ts" in entry
        assert "action" in entry
        assert "identity" in entry
        assert "result" in entry


# ── AIGovernanceGate — identity ───────────────────────────────────────────────


class TestGateIdentity:
    def test_default_identity(self) -> None:
        gate = AIGovernanceGate()
        assert gate.identity == "unknown"

    def test_custom_identity(self) -> None:
        gate = AIGovernanceGate(identity="buffy")
        assert gate.identity == "buffy"

    def test_identity_setter(self) -> None:
        gate = AIGovernanceGate(identity="old")
        gate.identity = "new"
        assert gate.identity == "new"


# ── Constants ─────────────────────────────────────────────────────────────────


class TestConstants:
    def test_risk_control_keywords_not_empty(self) -> None:
        assert len(RISK_CONTROL_KEYWORDS) > 0
        assert "_trip_hard_halt" in RISK_CONTROL_KEYWORDS
        assert "MAX_DAILY_LOSS" in RISK_CONTROL_KEYWORDS

    def test_forbidden_file_targets_not_empty(self) -> None:
        assert len(FORBIDDEN_FILE_TARGETS) > 0

    def test_bypass_patterns_not_empty(self) -> None:
        assert len(BYPASS_PATTERNS) > 0
        assert "datetime.now()" in BYPASS_PATTERNS

    def test_constitution_acknowledgment_present(self) -> None:
        gate = AIGovernanceGate()
        assert "CORRECTNESS > FEATURES" in gate.CONSTITUTION_ACKNOWLEDGMENT
        assert "SAFETY > SPEED" in gate.CONSTITUTION_ACKNOWLEDGMENT

    def test_required_readings_present(self) -> None:
        gate = AIGovernanceGate()
        assert "CLAUDE.md" in gate.REQUIRED_READINGS
        assert "docs/constitution_scoring_framework.md" in gate.REQUIRED_READINGS


# ── Helpers: get_gate / validate_ai_action ────────────────────────────────────


class TestHelpers:
    def test_get_gate_returns_singleton(self) -> None:
        g1 = get_gate()
        g2 = get_gate()
        assert g1 is g2

    def test_get_gate_is_governance_gate(self) -> None:
        gate = get_gate()
        assert isinstance(gate, AIGovernanceGate)

    def test_validate_ai_action_passes_with_good_params(self) -> None:
        result = validate_ai_action(
            constitution_acknowledged=True,
            claude_read=True,
        )
        assert result.passed

    def test_validate_ai_action_fails_without_acknowledgment(self) -> None:
        result = validate_ai_action(constitution_acknowledged=False)
        assert not result.passed

    def test_validate_ai_action_with_files(self) -> None:
        result = validate_ai_action(
            constitution_acknowledged=True,
            claude_read=True,
            changed_files=["core/foo.py"],
        )
        assert result.passed
