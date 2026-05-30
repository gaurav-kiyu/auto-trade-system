"""
Tests for core/constitution.py — Constitution Validation Engine.

Covers:
  - CategoryScore evidence/regression calculations
  - ScoreReport generation
  - Change pipeline validation (10-step)
  - Pre-implementation checklist
  - Feature acceptance criteria
  - Repository hygiene
  - Evidence-based scoring enforcement
  - Singleton get_validator()
  - Feature acceptance
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from core.constitution import (
    CATEGORIES,
    CategoryScore,
    ConstitutionValidator,
    ScoreEvidence,
    ScoreReport,
    ValidationResult,
    get_validator,
    validate_and_report,
)


# ── CategoryScore ─────────────────────────────────────────────────────────────


class TestCategoryScore:
    def test_default_score_is_5(self) -> None:
        cs = CategoryScore(category_id="TST-01", category_name="Test", max_score=9.0)
        assert cs.effective_score == 5.0

    def test_evidence_bonus_increases_score(self) -> None:
        cs = CategoryScore(category_id="TST-01", category_name="Test", max_score=9.0)
        ev = ScoreEvidence(description="test pass", evidence_type="test_pass", weight=1.0, verified=True)
        cs.evidence.append(ev)
        assert cs.effective_score == 6.0

    def test_regression_penalty_lowers_score(self) -> None:
        cs = CategoryScore(category_id="TST-01", category_name="Test", max_score=9.0)
        cs.regressions.append("Test regression")
        assert cs.effective_score == 3.0

    def test_evidence_and_regression_cancel(self) -> None:
        cs = CategoryScore(category_id="TST-01", category_name="Test", max_score=9.0)
        ev = ScoreEvidence(description="test", evidence_type="test_pass", weight=2.0, verified=True)
        cs.evidence.append(ev)
        cs.regressions.append("regression")
        # 5.0 + 2.0 - 2.0 = 5.0
        assert cs.effective_score == 5.0

    def test_score_capped_at_max(self) -> None:
        cs = CategoryScore(category_id="TST-01", category_name="Test", max_score=6.0)
        ev = ScoreEvidence(description="lots of evidence", evidence_type="test_pass", weight=3.0, verified=True)
        cs.evidence.append(ev)
        # 5.0 + 3.0 = 8.0, but max is 6.0
        assert cs.effective_score == 6.0

    def test_score_floor_at_zero(self) -> None:
        cs = CategoryScore(category_id="TST-01", category_name="Test", max_score=9.0)
        cs.regressions.append("r1")
        cs.regressions.append("r2")
        cs.regressions.append("r3")
        # 5.0 - 6.0 = -1.0, floor at 0.0
        assert cs.effective_score == 0.0

    def test_no_evidence_caps_at_8(self) -> None:
        cs = CategoryScore(category_id="TST-01", category_name="Test", max_score=9.5)
        cs.score = 9.0  # set base higher
        assert cs.effective_score == 8.0  # capped because no evidence

    def test_needs_9_audit_threshold(self) -> None:
        cs = CategoryScore(category_id="TST-01", category_name="Test", max_score=9.9)
        ev = ScoreEvidence(description="test", evidence_type="test_pass", weight=4.5, verified=True)
        cs.evidence.append(ev)
        assert cs.effective_score >= 9.0
        assert cs.needs_9_audit is True

    def test_needs_95_audit_threshold(self) -> None:
        cs = CategoryScore(category_id="TST-01", category_name="Test", max_score=9.9)
        for i in range(5):
            ev = ScoreEvidence(description=f"evidence {i}", evidence_type="test_pass", weight=1.0, verified=True)
            cs.evidence.append(ev)
        assert cs.effective_score >= 9.5
        assert cs.needs_95_audit is True

    def test_evidence_timestamp_auto_set(self) -> None:
        ev = ScoreEvidence(description="test", evidence_type="test_pass")
        assert ev.timestamp > 0

    def test_unverified_evidence_not_counted(self) -> None:
        cs = CategoryScore(category_id="TST-01", category_name="Test", max_score=9.0)
        ev = ScoreEvidence(description="unverified", evidence_type="test_pass", weight=2.0, verified=False)
        cs.evidence.append(ev)
        assert cs.effective_score == 5.0  # unverified doesn't count


# ── ScoreReport ───────────────────────────────────────────────────────────────


class TestScoreReport:
    def test_report_has_overall_score(self) -> None:
        report = ScoreReport(
            timestamp=time.time(),
            version="1.0.0",
            categories={},
            overall_score=0.0,
            total_evidence_items=0,
            open_regressions=0,
        )
        assert report.overall_score == 0.0

    def test_report_to_dict_has_keys(self) -> None:
        report = ScoreReport(
            timestamp=time.time(),
            version="1.0.0",
            categories={},
            overall_score=5.0,
            total_evidence_items=3,
            open_regressions=1,
        )
        d = report.to_dict()
        assert "overall_score" in d
        assert "categories" in d
        assert d["overall_score"] == 5.0

    def test_report_to_dict_with_categories(self) -> None:
        cat = CategoryScore(category_id="TST-01", category_name="Test", max_score=9.0)
        cat.audits.append("security")
        cat.regressions.append("r1")
        report = ScoreReport(
            timestamp=time.time(),
            version="1.0.0",
            categories={"TST-01": cat},
            overall_score=5.0,
            total_evidence_items=0,
            open_regressions=1,
        )
        d = report.to_dict()
        assert d["categories"]["TST-01"]["audits"] == ["security"]
        assert d["categories"]["TST-01"]["regressions"] == ["r1"]

    def test_report_version(self) -> None:
        report = ScoreReport(
            timestamp=time.time(),
            version="2.0.0",
            categories={},
            overall_score=8.5,
            total_evidence_items=10,
            open_regressions=0,
        )
        assert report.version == "2.0.0"


# ── ConstitutionValidator ─────────────────────────────────────────────────────


class TestConstitutionValidatorInit:
    def test_init_has_all_categories(self) -> None:
        v = ConstitutionValidator()
        assert len(v.CATEGORIES) == 31

    def test_each_category_has_name_and_max_score(self) -> None:
        for cid, (name, max_score) in CATEGORIES.items():
            assert isinstance(cid, str)
            assert isinstance(name, str)
            assert isinstance(max_score, float)
            assert max_score >= 5.0

    def test_risk_categories_have_highest_scores(self) -> None:
        assert CATEGORIES["RSK-01"][1] == 9.9
        assert CATEGORIES["RSK-02"][1] == 9.9

    def test_all_scores_initialized(self) -> None:
        v = ConstitutionValidator()
        for cid in CATEGORIES:
            assert v.get_category_score(cid) is not None

    def test_unknown_category_returns_none(self) -> None:
        v = ConstitutionValidator()
        assert v.get_category_score("UNKNOWN") is None


class TestChangePipeline:
    def test_all_steps_passed(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_change_pipeline({
            "review": True,
            "impact_analysis": True,
            "design": True,
            "implementation": True,
            "testing": True,
            "validation": True,
            "documentation": True,
            "audit": True,
            "acceptance": True,
            "release": True,
        })
        assert len(results) == 10
        assert all(r.passed for r in results)

    def test_all_steps_missing(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_change_pipeline({})
        assert len(results) == 10
        assert all(not r.passed for r in results)

    def test_single_step_missing(self) -> None:
        v = ConstitutionValidator()
        evidence = {s: True for s in v.CHANGE_PIPELINE_STEPS}
        evidence["audit"] = False
        results = v.validate_change_pipeline(evidence)
        audit_result = [r for r in results if "audit" in r.category]
        assert len(audit_result) == 1
        assert not audit_result[0].passed
        assert audit_result[0].evidence_required == ["audit"]

    def test_pipeline_has_10_steps(self) -> None:
        v = ConstitutionValidator()
        assert len(v.CHANGE_PIPELINE_STEPS) == 10
        assert v.CHANGE_PIPELINE_STEPS[0] == "review"
        assert v.CHANGE_PIPELINE_STEPS[-1] == "release"


class TestPreImplementation:
    def test_all_checks_pass(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_pre_implementation(
            constitution_read=True,
            claude_read=True,
            architecture_reviewed=True,
            audit_history_reviewed=True,
            risk_controls_verified=True,
            affected_files_identified=["core/foo.py"],
        )
        assert all(r.passed for r in results)

    def test_all_checks_fail(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_pre_implementation()
        passed = [r for r in results if r.passed]
        # Only affected_files should fail since it's missing
        assert any(not r.passed for r in results)

    def test_missing_affected_files(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_pre_implementation(constitution_read=True)
        # affected_files_identified is None -> should fail
        affected = [r for r in results if "affected_files" in r.category]
        assert len(affected) == 1
        assert not affected[0].passed

    def test_affected_files_present(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_pre_implementation(
            affected_files_identified=["core/foo.py", "core/bar.py"]
        )
        affected = [r for r in results if "affected_files" in r.category]
        assert affected[0].passed
        assert "core/foo.py" in affected[0].detail
        assert "core/bar.py" in affected[0].detail


class TestAddEvidence:
    def test_add_evidence_to_valid_category(self) -> None:
        v = ConstitutionValidator()
        result = v.add_evidence("ARCH-01", "Architecture review completed", "code_review", 1.0)
        assert result is True
        cat = v.get_category_score("ARCH-01")
        assert cat is not None
        assert len(cat.evidence) == 1

    def test_add_evidence_to_invalid_category(self) -> None:
        v = ConstitutionValidator()
        result = v.add_evidence("INVALID", "test", "documentation", 0.5)
        assert result is False

    def test_evidence_increases_score(self) -> None:
        v = ConstitutionValidator()
        score_before = v.get_category_score("ARCH-01")
        assert score_before is not None
        before = score_before.effective_score
        v.add_evidence("ARCH-01", "evidence", "test_pass", 1.0)
        score_after = v.get_category_score("ARCH-01")
        assert score_after is not None
        assert score_after.effective_score > before

    def test_add_regression_lowers_score(self) -> None:
        v = ConstitutionValidator()
        score_before = v.get_category_score("ARCH-01")
        assert score_before is not None
        before = score_before.effective_score
        v.add_regression("ARCH-01", "regression")
        score_after = v.get_category_score("ARCH-01")
        assert score_after is not None
        assert score_after.effective_score < before

    def test_add_regression_invalid_category(self) -> None:
        v = ConstitutionValidator()
        result = v.add_regression("INVALID", "test")
        assert result is False

    def test_add_audit(self) -> None:
        v = ConstitutionValidator()
        result = v.add_audit("SEC-01", "security")
        assert result is True
        cat = v.get_category_score("SEC-01")
        assert cat is not None
        assert "security" in cat.audits

    def test_add_duplicate_audit(self) -> None:
        v = ConstitutionValidator()
        v.add_audit("SEC-01", "security")
        v.add_audit("SEC-01", "security")
        cat = v.get_category_score("SEC-01")
        assert cat is not None
        assert len(cat.audits) == 1  # deduplicated


class TestGenerateReport:
    def test_report_generated(self) -> None:
        v = ConstitutionValidator()
        report = v.generate_report()
        assert isinstance(report, ScoreReport)
        assert report.overall_score > 0

    def test_report_includes_all_categories(self) -> None:
        v = ConstitutionValidator()
        report = v.generate_report()
        assert len(report.categories) == 31

    def test_report_evidence_count(self) -> None:
        v = ConstitutionValidator()
        v.add_evidence("ARCH-01", "test", "documentation", 0.5)
        report = v.generate_report()
        assert report.total_evidence_items == 1

    def test_report_regression_count(self) -> None:
        v = ConstitutionValidator()
        v.add_regression("ARCH-01", "test regression")
        report = v.generate_report()
        assert report.open_regressions == 1

    def test_report_version(self) -> None:
        v = ConstitutionValidator()
        report = v.generate_report()
        assert report.version == "1.0.0"


class TestFeatureAcceptance:
    def test_all_criteria_met(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_feature_acceptance(
            fully_tested=True,
            fully_validated=True,
            beneficial=True,
            secure=True,
            replay_safe=True,
            risk_safe=True,
            maintainable=True,
            documented=True,
        )
        assert len(results) == 1
        assert results[0].passed

    def test_not_beneficial_rejected_immediately(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_feature_acceptance(beneficial=False)
        assert len(results) == 1
        assert not results[0].passed
        assert "REJECTED" in results[0].detail

    def test_not_tested_rejected(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_feature_acceptance(
            beneficial=True, fully_tested=False
        )
        assert any(not r.passed for r in results)
        assert any("REJECTED" in r.detail for r in results)

    def test_not_secure_rejected(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_feature_acceptance(
            beneficial=True, secure=False
        )
        assert any(not r.passed for r in results)
        assert any("REJECTED" in r.detail for r in results)

    def test_not_documented_rejected(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_feature_acceptance(
            beneficial=True, documented=False
        )
        assert any(not r.passed for r in results)

    def test_security_audit_trails(self) -> None:
        v = ConstitutionValidator()
        v.add_audit("SEC-04", "security")
        cat = v.get_category_score("SEC-04")
        assert cat is not None
        assert "security" in cat.audits


class TestRepositoryHygiene:
    def test_hygiene_on_tmp_dir(self, tmp_path: Path) -> None:
        v = ConstitutionValidator()
        results = v.validate_repository_hygiene(str(tmp_path))
        # Temp dir should be clean
        hygiene = [r for r in results if "prohibited_artifacts" in r.category]
        assert len(hygiene) == 1
        assert hygiene[0].passed

    def test_hygiene_gitignore_check(self, tmp_path: Path) -> None:
        v = ConstitutionValidator()
        results = v.validate_repository_hygiene(str(tmp_path))
        gitignore = [r for r in results if "gitignore" in r.category]
        assert len(gitignore) == 1
        assert not gitignore[0].passed  # tmp dir doesn't have .gitignore

    def test_hygiene_with_prohibited_artifacts(self, tmp_path: Path) -> None:
        # Create __pycache__ directory
        (tmp_path / "__pycache__").mkdir()
        v = ConstitutionValidator()
        results = v.validate_repository_hygiene(str(tmp_path))
        hygiene = [r for r in results if "prohibited_artifacts" in r.category]
        assert len(hygiene) == 1
        assert not hygiene[0].passed

    def test_hygiene_with_pyc_files(self, tmp_path: Path) -> None:
        (tmp_path / "test.pyc").write_text("")
        v = ConstitutionValidator()
        results = v.validate_repository_hygiene(str(tmp_path))
        hygiene = [r for r in results if "prohibited_artifacts" in r.category]
        assert not hygiene[0].passed

    def test_hygiene_gitignore_present(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("")
        v = ConstitutionValidator()
        results = v.validate_repository_hygiene(str(tmp_path))
        gitignore = [r for r in results if "gitignore" in r.category]
        assert gitignore[0].passed


class TestScoreEvidence:
    def test_score_below_9_without_evidence_passes(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_score_evidence(8.0, "ARCH-01", has_evidence=False)
        assert result.passed

    def test_score_above_9_without_evidence_fails(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_score_evidence(9.5, "ARCH-01", has_evidence=False)
        assert not result.passed

    def test_score_above_9_with_evidence_passes(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_score_evidence(9.5, "ARCH-01", has_evidence=True)
        assert result.passed

    def test_score_above_9_5_requires_audits(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_score_evidence(9.6, "RSK-01", has_evidence=True)
        # Missing audits -> should fail
        assert not result.passed

    def test_score_above_9_5_with_audits_passes(self) -> None:
        v = ConstitutionValidator()
        v.add_audit("RSK-01", "architecture")
        v.add_audit("RSK-01", "security")
        v.add_audit("RSK-01", "risk")
        v.add_audit("RSK-01", "execution")
        v.add_audit("RSK-01", "testing")
        v.add_audit("RSK-01", "observability")
        v.add_audit("RSK-01", "disaster_recovery")
        v.add_audit("RSK-01", "chaos")
        v.add_audit("RSK-01", "black_swan")
        result = v.validate_score_evidence(9.6, "RSK-01", has_evidence=True)
        assert result.passed

    def test_score_over_8_without_evidence_fails(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_score_evidence(8.5, "ARCH-01", has_evidence=False)
        assert not result.passed

    def test_score_over_8_with_evidence_passes(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_score_evidence(8.5, "ARCH-01", has_evidence=True)
        assert result.passed


class TestAuditLog:
    def test_audit_log_records_actions(self) -> None:
        v = ConstitutionValidator()
        v.add_evidence("ARCH-01", "test", "documentation", 0.5)
        log = v.get_audit_log()
        assert len(log) >= 1
        assert log[0]["action"] == "evidence_added"

    def test_audit_log_limit(self) -> None:
        v = ConstitutionValidator()
        for i in range(20):
            v.add_evidence("ARCH-01", f"evidence {i}", "documentation", 0.1)
        log = v.get_audit_log(limit=5)
        assert len(log) <= 5

    def test_audit_log_change_pipeline(self) -> None:
        v = ConstitutionValidator()
        v.validate_change_pipeline({"review": True, "release": True})
        log = v.get_audit_log()
        actions = [l["action"] for l in log]
        assert "change_pipeline" in actions

    def test_audit_log_pre_implementation(self) -> None:
        v = ConstitutionValidator()
        v.validate_pre_implementation(constitution_read=True)
        log = v.get_audit_log()
        actions = [l["action"] for l in log]
        assert "pre_implementation" in actions


class TestGetter:
    def test_get_validator_returns_singleton(self) -> None:
        v1 = get_validator()
        v2 = get_validator()
        assert v1 is v2

    def test_validator_is_constitution_validator(self) -> None:
        v = get_validator()
        assert isinstance(v, ConstitutionValidator)

    def test_validate_and_report_returns_dict(self) -> None:
        result = validate_and_report()
        assert isinstance(result, dict)
        assert "overall_score" in result
        assert "categories" in result


class TestPrintReport:
    def test_print_report_does_not_crash(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging
        caplog.set_level(logging.INFO)
        v = ConstitutionValidator()
        v.add_evidence("ARCH-01", "test", "documentation", 0.5)
        v.print_report()
        assert len(caplog.records) > 5
        assert any("CONSTITUTION SCORING REPORT" in r.message for r in caplog.records)
