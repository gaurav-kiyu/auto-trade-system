"""
Tests for core/constitution.py - Constitution Validation Engine.

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

import time
from pathlib import Path

import pytest
from core.constitution import (
    CategoryScore,
    ConstitutionValidator,
    ScoreEvidence,
    ScoreReport,
    get_validator,
    validate_and_report,
)

# CATEGORIES is defined as a class variable on ConstitutionValidator
CATEGORIES = ConstitutionValidator.CATEGORIES


# ── CategoryScore ─────────────────────────────────────────────────────────────


class TestCategoryScore:
    def test_default_score_is_85(self) -> None:
        cs = CategoryScore(category_id="TST-01", category_name="Test", max_score=9.0)
        assert cs.score == 8.5  # base starts at 8.5 (aligned with score_system.py)
        assert cs.effective_score == 8.0  # no-evidence cap: without evidence, max 8.0

    def test_evidence_bonus_increases_score(self) -> None:
        cs = CategoryScore(category_id="TST-01", category_name="Test", max_score=10.0)
        ev = ScoreEvidence(description="test pass", evidence_type="test_pass", weight=1.0, verified=True)
        cs.evidence.append(ev)
        assert cs.effective_score == 9.5

    def test_regression_penalty_lowers_score(self) -> None:
        cs = CategoryScore(category_id="TST-01", category_name="Test", max_score=9.0)
        cs.regressions.append("Test regression")
        assert cs.effective_score == 6.5

    def test_evidence_and_regression_cancel(self) -> None:
        cs = CategoryScore(category_id="TST-01", category_name="Test", max_score=9.0)
        ev = ScoreEvidence(description="test", evidence_type="test_pass", weight=2.0, verified=True)
        cs.evidence.append(ev)
        cs.regressions.append("regression")
        # 8.5 + 2.0 - 2.0 = 8.5
        assert cs.effective_score == 8.5

    def test_score_capped_at_max(self) -> None:
        cs = CategoryScore(category_id="TST-01", category_name="Test", max_score=6.0)
        ev = ScoreEvidence(description="lots of evidence", evidence_type="test_pass", weight=3.0, verified=True)
        cs.evidence.append(ev)
        # 5.0 + 3.0 = 8.0, but max is 6.0
        assert cs.effective_score == 6.0

    def test_score_floor_at_zero(self) -> None:
        cs = CategoryScore(category_id="TST-01", category_name="Test", max_score=9.0)
        for i in range(5):
            cs.regressions.append(f"r{i}")
        # 8.5 - 10.0 = -1.5, floor at 0.0
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
        assert cs.effective_score == 8.5  # unverified doesn't count


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
        # v4.0: 31 original + 12 LAY + 12 QGT + 13 PRN + 13 AST + 11 SGS + 6 PLS + 9 SRE + 4 KNW = 111
        assert len(v.CATEGORIES) == 111

    def test_each_category_has_name_and_max_score(self) -> None:
        for cid, (name, max_score) in CATEGORIES.items():
            assert isinstance(cid, str)
            assert isinstance(name, str)
            assert isinstance(max_score, float)
            assert max_score >= 5.0

    def test_risk_categories_have_highest_scores(self) -> None:
        # All 111 categories now share the 10.0 ceiling so a perfect
        # 10.0/10.0 overall score is achievable with verified evidence.
        assert CATEGORIES["RSK-01"][1] == 10.0
        assert CATEGORIES["RSK-02"][1] == 10.0

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
        [r for r in results if r.passed]
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
        assert len(cat.evidence) >= 1
        assert cat.evidence[-1].description == "Architecture review completed"
        assert cat.evidence[-1].evidence_type == "code_review"

    def test_add_evidence_to_invalid_category(self) -> None:
        v = ConstitutionValidator()
        result = v.add_evidence("INVALID", "test", "documentation", 0.5)
        assert result is False

    def test_evidence_does_not_decrease_score(self) -> None:
        """Test that adding evidence never decreases the score."""
        v = ConstitutionValidator()
        # Use a category that may be at max; verify score doesn't regress
        for cid in ("ARCH-01", "TST-02", "EXE-01"):
            cat = v.get_category_score(cid)
            assert cat is not None
            before = cat.effective_score
            v.add_evidence(cid, f"test evidence {time.time()}", "test_pass", 0.5)
            after = v.get_category_score(cid)
            assert after is not None
            assert after.effective_score >= before, f"Score decreased for {cid}"

    def test_add_regression_lowers_score(self) -> None:
        v = ConstitutionValidator()
        score_before = v.get_category_score("ARCH-01")
        assert score_before is not None
        before = score_before.effective_score
        # ARCH-01 may sit at its 10.0 cap; stack regressions until the score drops
        cur = score_before
        for i in range(10):
            v.add_regression("ARCH-01", f"regression {i}")
            cur = v.get_category_score("ARCH-01")
            assert cur is not None
            if cur.effective_score < before:
                break
        assert cur.effective_score < before

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
        # v4.0: 111 categories (107 classic + 4 KNW)
        assert len(report.categories) == 111

    def test_report_evidence_count(self) -> None:
        v = ConstitutionValidator()
        before = v.generate_report().total_evidence_items
        v.add_evidence("ARCH-01", "NEW unique report evidence", "documentation", 0.5)
        report = v.generate_report()
        assert report.total_evidence_items == before + 1

    def test_report_regression_count(self) -> None:
        v = ConstitutionValidator()
        v.add_regression("ARCH-01", "test regression")
        report = v.generate_report()
        assert report.open_regressions == 1

    def test_report_version(self) -> None:
        v = ConstitutionValidator()
        report = v.generate_report()
        # v4.0: version updated
        assert report.version == "4.1.0"


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


# ── v4.0: Enterprise Layer Validation ─────────────────────────────────────────


class TestEnterpriseLayerValidation:
    def test_valid_layer_passes(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_enterprise_layer(
            "LAY-01", documented=True, implemented=True, tested=True, monitored=True,
        )
        assert result.passed

    def test_layer_missing_documentation(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_enterprise_layer(
            "LAY-01", documented=False, implemented=True, tested=True, monitored=True,
        )
        assert not result.passed
        assert "documentation" in result.detail

    def test_layer_missing_all(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_enterprise_layer("LAY-01")
        assert not result.passed
        assert "documentation" in result.detail
        assert "implementation" in result.detail
        assert "testing" in result.detail
        assert "monitoring" in result.detail

    def test_unknown_layer(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_enterprise_layer("LAY-99")
        assert not result.passed
        assert "Unknown" in result.detail

    def test_validate_all_layers(self) -> None:
        v = ConstitutionValidator()
        layer_status = {
            lid: {"documented": True, "implemented": True, "tested": True, "monitored": True}
            for lid in v.ENTERPRISE_LAYERS
        }
        results = v.validate_all_enterprise_layers(layer_status)
        assert len(results) == 12
        assert all(r.passed for r in results)


# ── v4.0: Quality Gate Validation ─────────────────────────────────────────────


class TestQualityGateValidation:
    def test_valid_gate_passes(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_quality_gate("QGT-01", passed=True)
        assert result.passed
        assert "PASSED" in result.detail

    def test_gate_fails(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_quality_gate("QGT-01", passed=False)
        assert not result.passed
        assert "FAILED" in result.detail

    def test_unknown_gate(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_quality_gate("QGT-99")
        assert not result.passed

    def test_validate_all_gates_passed(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_all_quality_gates({gid: True for gid in v.QUALITY_GATES})
        assert len(results) == 12
        assert all(r.passed for r in results)

    def test_validate_all_gates_one_fails(self) -> None:
        v = ConstitutionValidator()
        gate_results = {gid: True for gid in v.QUALITY_GATES}
        gate_results["QGT-05"] = False
        results = v.validate_all_quality_gates(gate_results)
        failed = [r for r in results if not r.passed]
        assert len(failed) == 1
        assert "QGT-05" in failed[0].category


# ── v4.0: Success Metrics Validation ──────────────────────────────────────────


class TestSuccessMetricsValidation:
    def test_metric_achieved(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_success_metric("MET-01", current_value=99.99)
        assert result.passed
        assert "achieved" in result.detail

    def test_metric_not_achieved(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_success_metric("MET-01", current_value=50.0)
        assert not result.passed
        assert "target is" in result.detail

    def test_unknown_metric(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_success_metric("MET-99")
        assert not result.passed

    def test_validate_all_metrics(self) -> None:
        v = ConstitutionValidator()
        # MET-07 uses lower-is-better (Technical Debt Trending Down)
        metric_values = {
            "MET-01": 99.99,  # higher is better
            "MET-02": 99.5,   # higher is better
            "MET-03": 100.0,  # higher is better
            "MET-04": 96.0,   # higher is better
            "MET-05": 100.0,  # higher is better
            "MET-06": 100.0,  # higher is better
            "MET-07": 30.0,   # LOWER is better (trending down)
            "MET-08": 55.0,   # higher is better
        }
        results = v.validate_all_success_metrics(metric_values)
        assert len(results) == 8
        assert all(r.passed for r in results)


# ── v4.0: AI Specialist Role Validation ───────────────────────────────────────


class TestAISpecialistRoleValidation:
    def test_valid_role_acknowledged(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_ai_specialist_role(
            "ROL-01", acknowledged=True, completed_tasks=["plan", "estimate"],
        )
        assert result.passed
        assert "acknowledged" in result.detail

    def test_role_not_acknowledged(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_ai_specialist_role("ROL-01", acknowledged=False)
        assert not result.passed

    def test_unknown_role(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_ai_specialist_role("ROL-99")
        assert not result.passed

    def test_get_role_id_by_name(self) -> None:
        v = ConstitutionValidator()
        rid = v.get_ai_role_id_by_name("Planner")
        assert rid == "ROL-01"

    def test_get_role_id_by_name_not_found(self) -> None:
        v = ConstitutionValidator()
        rid = v.get_ai_role_id_by_name("Nonexistent")
        assert rid is None


# ── v4.0: Definition of Done Validation ───────────────────────────────────────


class TestDefinitionOfDone:
    def test_all_done_passes(self) -> None:
        v = ConstitutionValidator()
        # Must match the key transformation in validate_definition_of_done:
        # item.lower().replace(" ", "_").replace("&", "and")
        completed = {}
        for item in v.DEFINITION_OF_DONE:
            key = item.lower().replace(" ", "_").replace("&", "and")
            completed[key] = True
        results = v.validate_definition_of_done(completed)
        assert len(results) == 10
        assert all(r.passed for r in results)

    def test_none_done(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_definition_of_done({})
        assert all(not r.passed for r in results)

    def test_some_done(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_definition_of_done({"architecture_reviewed": True})
        passed = [r for r in results if r.passed]
        failed = [r for r in results if not r.passed]
        assert len(passed) == 1
        assert len(failed) == 9


# ── v4.0: Continuous Lifecycle Validation ─────────────────────────────────────


class TestContinuousLifecycle:
    def test_all_phases_completed(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_continuous_lifecycle(v.CONTINUOUS_LIFECYCLE)
        assert len(results) == 11
        assert all(r.passed for r in results)

    def test_no_phases_completed(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_continuous_lifecycle([])
        assert all(not r.passed for r in results)

    def test_some_phases_completed(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_continuous_lifecycle(["Requirements", "Architecture", "Development"])
        passed = [r for r in results if r.passed]
        assert len(passed) == 3


# ── v4.0: Comprehensive Health Check ──────────────────────────────────────────


class TestComprehensiveHealthCheck:
    def test_health_check_returns_dict(self) -> None:
        v = ConstitutionValidator()
        health = v.comprehensive_health_check()
        assert isinstance(health, dict)
        assert health["version"] == "4.1.0"
        assert "enterprise_layers" in health
        assert "quality_gates" in health
        assert "success_metrics" in health
        assert "ai_specialist_roles" in health
        assert "definition_of_done" in health
        assert "continuous_lifecycle" in health

    def test_health_check_counts(self) -> None:
        v = ConstitutionValidator()
        health = v.comprehensive_health_check()
        assert health["enterprise_layers"]["count"] == 12
        assert health["quality_gates"]["count"] == 12
        assert health["success_metrics"]["count"] == 8
        assert health["ai_specialist_roles"]["count"] == 18
        assert health["definition_of_done"]["items"] == 10
        assert health["continuous_lifecycle"]["phases"] == 11
        assert health["total_categories"] == 111


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
        actions = [entry["action"] for entry in log]
        assert "change_pipeline" in actions

    def test_audit_log_pre_implementation(self) -> None:
        v = ConstitutionValidator()
        v.validate_pre_implementation(constitution_read=True)
        log = v.get_audit_log()
        actions = [entry["action"] for entry in log]
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


# ── v4.0: Engineering Principles Validation ───────────────────────────────────


class TestEngineeringPrinciples:
    def test_principle_enforced_passes(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_engineering_principle("PRN-01", enforced=True, evidence="Security audit passes")
        assert result.passed
        assert "Security by Design" in result.detail

    def test_principle_not_enforced(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_engineering_principle("PRN-01", enforced=False)
        assert not result.passed
        assert "not enforced" in result.detail

    def test_unknown_principle(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_engineering_principle("PRN-99")
        assert not result.passed

    def test_validate_all_principles(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_all_engineering_principles({pid: True for pid in v.ENGINEERING_PRINCIPLES})
        assert len(results) == 13
        assert all(r.passed for r in results)

    def test_validate_all_principles_one_fails(self) -> None:
        v = ConstitutionValidator()
        status = {pid: True for pid in v.ENGINEERING_PRINCIPLES}
        status["PRN-05"] = False
        results = v.validate_all_engineering_principles(status)
        failed = [r for r in results if not r.passed]
        assert len(failed) == 1


# ── v4.0: Architecture Standards Validation ───────────────────────────────────


class TestArchitectureStandards:
    def test_standard_implemented_passes(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_architecture_standard("AST-01", implemented=True, evidence="DDD aggregates defined")
        assert result.passed
        assert "DDD" in result.detail

    def test_standard_not_implemented(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_architecture_standard("AST-01", implemented=False)
        assert not result.passed
        assert "not implemented" in result.detail

    def test_unknown_standard(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_architecture_standard("AST-99")
        assert not result.passed

    def test_validate_all_standards(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_all_architecture_standards({sid: True for sid in v.ARCHITECTURE_STANDARDS})
        assert len(results) == 13
        assert all(r.passed for r in results)


# ── v4.0: Security & Governance Validation ────────────────────────────────────


class TestSecurityGovernance:
    def test_security_standard_implemented(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_security_governance_standard("SGS-01", implemented=True, evidence="Zero Trust enforced")
        assert result.passed
        assert "Zero Trust" in result.detail

    def test_security_standard_not_implemented(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_security_governance_standard("SGS-01", implemented=False)
        assert not result.passed

    def test_unknown_security_standard(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_security_governance_standard("SGS-99")
        assert not result.passed

    def test_validate_all_security(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_all_security_governance({sid: True for sid in v.SECURITY_GOVERNANCE_STANDARDS})
        assert len(results) == 11
        assert all(r.passed for r in results)


# ── v4.0: Platform Engineering Validation ─────────────────────────────────────


class TestPlatformEngineering:
    def test_platform_standard_implemented(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_platform_engineering_standard("PLS-01", implemented=True, evidence="IDP active")
        assert result.passed

    def test_platform_standard_not_implemented(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_platform_engineering_standard("PLS-01", implemented=False)
        assert not result.passed

    def test_unknown_platform_standard(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_platform_engineering_standard("PLS-99")
        assert not result.passed

    def test_validate_all_platform(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_all_platform_engineering({sid: True for sid in v.PLATFORM_ENGINEERING_STANDARDS})
        assert len(results) == 6
        assert all(r.passed for r in results)


# ── v4.0: SRE/Reliability Validation ──────────────────────────────────────────


class TestSREReliability:
    def test_sre_standard_implemented(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_sre_standard("SRE-01", implemented=True, evidence="JSONL logging active")
        assert result.passed

    def test_sre_standard_not_implemented(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_sre_standard("SRE-01", implemented=False)
        assert not result.passed

    def test_unknown_sre_standard(self) -> None:
        v = ConstitutionValidator()
        result = v.validate_sre_standard("SRE-99")
        assert not result.passed

    def test_validate_all_sre(self) -> None:
        v = ConstitutionValidator()
        results = v.validate_all_sre_standards({sid: True for sid in v.SRE_STANDARDS})
        assert len(results) == 9
        assert all(r.passed for r in results)


# ── v4.0: Extended Health Check ───────────────────────────────────────────────


class TestExtendedHealthCheck:
    def test_health_check_includes_new_domains(self) -> None:
        v = ConstitutionValidator()
        health = v.comprehensive_health_check()
        assert health["engineering_principles"]["count"] == 13
        assert health["architecture_standards"]["count"] == 13
        assert health["security_governance"]["count"] == 11
        assert health["platform_engineering"]["count"] == 6
        assert health["sre_reliability"]["count"] == 9


# ── v4.0: Evidence Storage Verification ────────────────────────────────────────


class TestV4EvidenceStorage:
    """Verify that evidence for new v4.0 domains is properly stored (not silently dropped)."""

    def test_prn_evidence_stored(self) -> None:
        v = ConstitutionValidator()
        ok = v.add_evidence("PRN-01", "Security by Design evidence", "code_review", 0.5)
        assert ok is True, "PRN-01 evidence should be stored"
        cat = v.get_category_score("PRN-01")
        assert cat is not None
        assert len(cat.evidence) >= 1

    def test_ast_evidence_stored(self) -> None:
        v = ConstitutionValidator()
        ok = v.add_evidence("AST-01", "DDD aggregates defined", "code_review", 0.5)
        assert ok is True, "AST-01 evidence should be stored"
        cat = v.get_category_score("AST-01")
        assert cat is not None
        assert len(cat.evidence) >= 1

    def test_sgs_evidence_stored(self) -> None:
        v = ConstitutionValidator()
        ok = v.add_evidence("SGS-01", "Zero Trust enforced", "code_review", 0.5)
        assert ok is True, "SGS-01 evidence should be stored"
        cat = v.get_category_score("SGS-01")
        assert cat is not None
        assert len(cat.evidence) >= 1

    def test_pls_evidence_stored(self) -> None:
        v = ConstitutionValidator()
        ok = v.add_evidence("PLS-01", "IDP active", "code_review", 0.5)
        assert ok is True, "PLS-01 evidence should be stored"
        cat = v.get_category_score("PLS-01")
        assert cat is not None
        assert len(cat.evidence) >= 1

    def test_sre_evidence_stored(self) -> None:
        v = ConstitutionValidator()
        ok = v.add_evidence("SRE-01", "JSONL logging active", "code_review", 0.5)
        assert ok is True, "SRE-01 evidence should be stored"
        cat = v.get_category_score("SRE-01")
        assert cat is not None
        assert len(cat.evidence) >= 1

    def test_evidence_increases_score_for_new_categories(self) -> None:
        v = ConstitutionValidator()
        cat = v.get_category_score("PRN-01")
        assert cat is not None
        # PRN-01 is scored to its 10.0 cap via auto-collected evidence, so the
        # raw score is capped. Stack regressions (each -2.0) until there is
        # headroom below the cap, then verify evidence genuinely raises the
        # score back toward the cap.
        for i in range(10):
            v.add_regression("PRN-01", f"temporary regression to create headroom {i}")
            cat = v.get_category_score("PRN-01")
            assert cat is not None
            if cat.effective_score < cat.max_score:
                break
        before = cat.effective_score
        assert before < cat.max_score, "Regressions should have created headroom"
        v.add_evidence("PRN-01", f"New evidence at {time.time()}", "test_pass", 1.0)
        after = v.get_category_score("PRN-01")
        assert after is not None
        assert after.effective_score > before, "Evidence should increase score for PRN-01"
        assert after.effective_score <= after.max_score, "Score must stay capped at max"


# ── v4.0: Constitution Alert Bridge Tests ─────────────────────────────────────


class TestConstitutionAlertBridge:
    """Test the ConstitutionAlertBridge singleton and health check integration."""

    def test_get_bridge_returns_instance(self) -> None:
        from core.constitution_alert_bridge import get_constitution_alert_bridge
        bridge = get_constitution_alert_bridge({"enabled": False})
        assert bridge is not None

    def test_check_and_alert_returns_result(self) -> None:
        from core.constitution_alert_bridge import get_constitution_alert_bridge
        bridge = get_constitution_alert_bridge({"enabled": False})
        result = bridge.check_and_alert()
        assert result.overall_score > 0
        assert result.total_categories == 111
        assert result.health_status in ("HEALTHY", "WARNING", "CRITICAL")

    def test_alert_bridge_detects_critical(self) -> None:
        from core.constitution_alert_bridge import get_constitution_alert_bridge
        bridge = get_constitution_alert_bridge({
            "enabled": False,
            "health_warn_threshold": 100.0,
            "health_crit_threshold": 50.0,
            "notify_on_warning": False,
            "notify_on_critical": False,
        })
        result = bridge.check_and_alert()
        # With thresholds set impossibly high, score should be below crit
        assert result.health_status == "CRITICAL" or result.overall_score < 50.0

    def test_bridge_stats(self) -> None:
        from core.constitution_alert_bridge import get_constitution_alert_bridge
        bridge = get_constitution_alert_bridge({"enabled": False})
        stats = bridge.get_stats()
        assert "enabled" in stats
        assert "health_warn_threshold" in stats
        assert "health_crit_threshold" in stats

    def test_bridge_reset(self) -> None:
        from core.constitution_alert_bridge import reset_constitution_alert_bridge
        # Should not raise
        reset_constitution_alert_bridge()
        assert True
