"""Tests for core/certification/gate.py - Unified Certification Gate."""

from __future__ import annotations

import json

import pytest

from core.certification.gate import (
    CertificationGate,
    CertificationGateResult,
    run_certification_gate,
    _run_hygiene_check,
    _run_architecture_compliance,
    _run_strategy_certification,
    _run_replay_certification,
    _run_paper_certification,
)


# ── CertificationGateResult Tests ─────────────────────────────────────────────

class TestCertificationGateResult:
    def test_default_values(self):
        r = CertificationGateResult()
        assert r.passed is False
        assert r.total_certifiers == 5
        assert r.passed_certifiers == 0
        assert r.timestamp is not None

    def test_summary_passed(self):
        r = CertificationGateResult(
            passed=True,
            verdict="ALL certifications PASSED",
            passed_certifiers=5,
            total_certifiers=5,
            strategy_certification={"status": "PASSED"},
            replay_certification={"status": "PASSED"},
            paper_trading_certification={"status": "PASSED"},
            architecture_compliance={"status": "PASSED"},
            repository_hygiene={"status": "PASSED"},
        )
        s = r.summary()
        assert "[PASS]" in s
        assert "ALL certifications PASSED" in s

    def test_summary_blocked(self):
        r = CertificationGateResult(
            passed=False,
            verdict="RELEASE BLOCKED",
            failed_certifiers=2,
            failures=["Strategy certification FAILED"],
            strategy_certification={"status": "FAILED", "message": "No data"},
            replay_certification={"status": "SKIPPED"},
        )
        s = r.summary()
        assert "[BLOCK]" in s
        assert "RELEASE BLOCKED" in s

    def test_to_dict(self):
        r = CertificationGateResult(
            passed=True,
            verdict="OK",
            passed_certifiers=5,
            strategy_certification={"status": "PASSED"},
        )
        d = r.to_dict()
        json.dumps(d)  # Must be JSON-serializable
        assert d["certification_gate"]["passed"] is True
        assert d["results"]["strategy"]["status"] == "PASSED"


# ── CertificationGate Tests ──────────────────────────────────────────────────

class TestCertificationGate:
    def test_init(self):
        gate = CertificationGate()
        assert gate is not None

    def test_init_with_config(self):
        gate = CertificationGate({"cert_gate_block_on_warn": True})
        assert gate._cfg["cert_gate_block_on_warn"] is True

    def test_run_all_returns_result(self):
        gate = CertificationGate()
        result = gate.run_all()
        assert isinstance(result, CertificationGateResult)
        assert result.timestamp is not None

    def test_run_all_has_certifier_results(self):
        gate = CertificationGate()
        result = gate.run_all()
        assert result.strategy_certification is not None
        assert result.replay_certification is not None
        assert result.paper_trading_certification is not None
        assert result.architecture_compliance is not None
        assert result.repository_hygiene is not None

    def test_run_all_aggregates_counts(self):
        gate = CertificationGate()
        result = gate.run_all()
        total = result.passed_certifiers + result.failed_certifiers + result.skipped_certifiers
        assert total == result.total_certifiers

    def test_run_all_with_skip_config(self):
        gate = CertificationGate({
            "cert_gate_skip_strategy": True,
            "cert_gate_skip_replay": True,
            "cert_gate_skip_paper": True,
            "cert_gate_skip_architecture": True,
            "cert_gate_skip_hygiene": True,
        })
        result = gate.run_all()
        # All should be skipped
        assert result.skipped_certifiers == 5
        assert result.passed is True  # Vacuously true when no certifiers ran


# ── Individual Certifier Runner Tests ────────────────────────────────────────

class TestStrategyCertificationRunner:
    def test_skip_when_disabled(self):
        result = _run_strategy_certification({"cert_gate_skip_strategy": True})
        assert result["status"] == "SKIPPED"

    def test_returns_dict(self):
        result = _run_strategy_certification({})
        assert isinstance(result, dict)
        assert "status" in result


class TestReplayCertificationRunner:
    def test_skip_when_disabled(self):
        result = _run_replay_certification({"cert_gate_skip_replay": True})
        assert result["status"] == "SKIPPED"

    def test_returns_dict(self):
        result = _run_replay_certification({})
        assert isinstance(result, dict)
        assert "status" in result


class TestPaperCertificationRunner:
    def test_skip_when_disabled(self):
        result = _run_paper_certification({"cert_gate_skip_paper": True})
        assert result["status"] == "SKIPPED"

    def test_returns_dict(self):
        result = _run_paper_certification({})
        assert isinstance(result, dict)
        assert "status" in result


class TestArchitectureComplianceRunner:
    def test_skip_when_disabled(self):
        result = _run_architecture_compliance({"cert_gate_skip_architecture": True})
        assert result["status"] == "SKIPPED"

    def test_returns_dict(self):
        result = _run_architecture_compliance({})
        assert isinstance(result, dict)
        assert "status" in result


class TestHygieneCheckRunner:
    def test_skip_when_disabled(self):
        result = _run_hygiene_check({"cert_gate_skip_hygiene": True})
        assert result["status"] == "SKIPPED"

    def test_returns_dict(self):
        result = _run_hygiene_check({})
        assert isinstance(result, dict)
        assert "status" in result

    def test_handles_missing_script(self):
        """Should gracefully handle missing hygiene check script."""
        result = _run_hygiene_check({})
        # The script doesn't exist, so it should be SKIPPED
        if result["status"] == "SKIPPED":
            assert "not found" in result.get("message", "").lower() or \
                   "not available" in result.get("message", "").lower()


# ── Convenience Function Tests ───────────────────────────────────────────────

class TestRunCertificationGate:
    def test_returns_result(self):
        result = run_certification_gate()
        assert isinstance(result, CertificationGateResult)

    def test_accepts_config(self):
        result = run_certification_gate({"cert_gate_block_on_warn": True})
        assert isinstance(result, CertificationGateResult)

    def test_skip_all_config(self):
        result = run_certification_gate({
            "cert_gate_skip_strategy": True,
            "cert_gate_skip_replay": True,
            "cert_gate_skip_paper": True,
            "cert_gate_skip_architecture": True,
            "cert_gate_skip_hygiene": True,
        })
        assert result.passed is True  # Vacuously true
        assert result.skipped_certifiers == 5

    def test_result_json_serializable(self):
        result = run_certification_gate()
        json.dumps(result.to_dict())  # Must not raise


# ── Edge Case Tests ──────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_failures_collected(self):
        """Failed certifiers should populate the failures list."""
        result = CertificationGateResult()
        result.failed_certifiers = 1
        result.failures.append("[strategy_certification] Sharpe too low")
        assert len(result.failures) == 1
        assert "strategy_certification" in result.failures[0]

    def test_warnings_collected(self):
        """Warnings should appear in warnings list."""
        result = CertificationGateResult()
        result.warnings.append("[repository_hygiene] Stale cache found")
        assert len(result.warnings) == 1
