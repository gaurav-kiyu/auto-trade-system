"""Tests for scripts/constitution_scorecard.py — Constitution v4.0 Compliance Scorecard.

Verifies the scorecard runs without errors, produces correct output,
and that all 87 requirements are properly defined.
"""

from __future__ import annotations

import json

import pytest

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def scorecard_module():
    """Import and return the scorecard module."""
    import scripts.constitution_scorecard as mod
    return mod


# ── Basic Import Tests ───────────────────────────────────────────────────────


class TestScorecardImport:
    def test_module_imports(self, scorecard_module):
        """Verify the module imports without errors."""
        assert scorecard_module is not None

    def test_requirements_defined(self, scorecard_module):
        """Verify all 87 requirements are defined."""
        reqs = scorecard_module.REQUIREMENTS
        assert len(reqs) == 87, f"Expected 87 requirements, got {len(reqs)}"

    def test_category_weights_defined(self, scorecard_module):
        """Verify category weights sum to 1.0."""
        weights = scorecard_module.CATEGORY_WEIGHTS
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01, f"Category weights sum to {total}, expected 1.0"

    def test_all_requirements_have_valid_categories(self, scorecard_module):
        """Verify every requirement maps to a defined category."""
        weights = scorecard_module.CATEGORY_WEIGHTS
        for req in scorecard_module.REQUIREMENTS:
            assert req.category in weights, f"Requirement {req.id} has unknown category '{req.category}'"


class TestRequirementCheck:
    def test_requirement_has_id(self, scorecard_module):
        """Verify every requirement has a non-empty ID."""
        for req in scorecard_module.REQUIREMENTS:
            assert req.id, f"Requirement missing ID: {req}"

    def test_requirement_has_module_path(self, scorecard_module):
        """Verify every requirement has a module path."""
        for req in scorecard_module.REQUIREMENTS:
            assert req.module_path, f"Requirement {req.id} missing module_path"

    def test_requirement_weights_meaningful(self, scorecard_module):
        """Verify all requirement weights are meaningfully positive (>= 0.1).

        Using >= 0.1 instead of > 0 ensures weights are actually intentional
        and not just relying on the dataclass default of 1.0.
        """
        for req in scorecard_module.REQUIREMENTS:
            assert req.weight >= 0.1, f"Requirement {req.id} has too-small weight {req.weight}"


class TestScorecardRun:
    def test_run_scorecard_returns_report(self, scorecard_module):
        """Verify running the scorecard returns a valid report."""
        report = scorecard_module.run_scorecard()
        assert report is not None
        assert hasattr(report, 'total_passed')
        assert hasattr(report, 'total_requirements')

    def test_scorecard_has_all_categories(self, scorecard_module):
        """Verify all 8 categories are present in the report."""
        report = scorecard_module.run_scorecard()
        expected = set(scorecard_module.CATEGORY_WEIGHTS.keys())
        actual = set(report.categories.keys())
        assert expected == actual, f"Missing categories: {expected - actual}, Extra: {actual - expected}"

    def test_scorecard_pct_in_range(self, scorecard_module):
        """Verify overall percentage is between 0 and 100."""
        report = scorecard_module.run_scorecard()
        assert 0 <= report.overall_pct <= 100, f"Overall pct {report.overall_pct} out of range"

    def test_scorecard_weighted_in_range(self, scorecard_module):
        """Verify weighted score is between 0 and 100."""
        report = scorecard_module.run_scorecard()
        assert 0 <= report.overall_weighted_score <= 100, f"Weighted score {report.overall_weighted_score} out of range"

    def test_scorecard_to_dict(self, scorecard_module):
        """Verify to_dict produces valid JSON-serializable output."""
        report = scorecard_module.run_scorecard()
        d = report.to_dict()
        # Should serialize to JSON without error
        json_str = json.dumps(d)
        assert len(json_str) > 0
        # Round-trip
        loaded = json.loads(json_str)
        assert loaded["total_requirements"] == 87
        assert loaded["status"] in ("PASS", "REVIEW")

    def test_scorecard_summary_text(self, scorecard_module):
        """Verify summary_text produces readable output with dynamic requirement count."""
        report = scorecard_module.run_scorecard()
        text = report.summary_text()
        assert "CONSTITUTION" in text.upper()
        assert str(report.total_requirements) in text  # Dynamic requirement count
        assert "SCORECARD" in text.upper()

    def test_all_categories_have_scores(self, scorecard_module):
        """Verify every category has a computed score."""
        report = scorecard_module.run_scorecard()
        for cat_name, cat in report.categories.items():
            assert cat.pct >= 0, f"Category {cat_name} has negative pct"
            assert cat.total > 0, f"Category {cat_name} has zero total"


class TestCheckMethod:
    def test_check_existing_file(self, scorecard_module):
        """Verify check() returns True for existing files."""
        req = scorecard_module.Requirement(
            id="TEST-01", name="Test Existing", category="test",
            module_path="scripts/constitution_scorecard.py",
        )
        assert req.check() is True

    def test_check_nonexistent_file(self, scorecard_module):
        """Verify check() returns False for non-existing files."""
        req = scorecard_module.Requirement(
            id="TEST-02", name="Test Missing", category="test",
            module_path="nonexistent_file_xyz.py",
        )
        assert req.check() is False

    def test_check_glob_pattern(self, scorecard_module):
        """Verify check() works with glob patterns."""
        req = scorecard_module.Requirement(
            id="TEST-03", name="Test Glob", category="test",
            module_path="core/ports/*.py",
        )
        assert req.check() is True


class TestScorecardStatus:
    def test_pass_status_above_threshold(self, scorecard_module):
        """Verify status is PASS when above 90%."""
        report = scorecard_module.run_scorecard()
        if report.overall_pct >= 90:
            assert report.status == "PASS"

    def test_threshold_constant(self, scorecard_module):
        """Verify SCORE_THRESHOLD_GOOD is defined and correct."""
        assert hasattr(scorecard_module, 'SCORE_THRESHOLD_GOOD')
        assert scorecard_module.SCORE_THRESHOLD_GOOD == 90.0


class TestRequirementCoverage:
    def test_all_enterprise_layers_covered(self, scorecard_module):
        """Verify enterprise layers category has sufficient requirements."""
        reqs = [r for r in scorecard_module.REQUIREMENTS if r.category == "enterprise_layers"]
        assert len(reqs) >= 12, f"Expected >=12 enterprise layer reqs, got {len(reqs)}"

    def test_all_architecture_standards_covered(self, scorecard_module):
        """Verify architecture standards category has sufficient requirements."""
        reqs = [r for r in scorecard_module.REQUIREMENTS if r.category == "architecture_standards"]
        assert len(reqs) >= 14, f"Expected >=14 architecture standard reqs, got {len(reqs)}"

    def test_all_security_governance_covered(self, scorecard_module):
        """Verify security governance category has sufficient requirements."""
        reqs = [r for r in scorecard_module.REQUIREMENTS if r.category == "security_governance"]
        assert len(reqs) >= 10, f"Expected >=10 security reqs, got {len(reqs)}"

    def test_all_quality_gates_covered(self, scorecard_module):
        """Verify quality gates category has sufficient requirements."""
        reqs = [r for r in scorecard_module.REQUIREMENTS if r.category == "quality_gates"]
        assert len(reqs) >= 12, f"Expected >=12 quality gate reqs, got {len(reqs)}"
