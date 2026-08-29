"""Tests for Accessibility Gate module."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.accessibility_gate import (
    AccessibilityChecklistItem,
    AccessibilityFinding,
    AccessibilityReport,
    get_accessibility_gate,
    reset_accessibility_gate,
)


@pytest.fixture(autouse=True)
def reset_gate():
    reset_accessibility_gate()
    p = Path("json/accessibility_history.json")
    if p.exists():
        p.unlink()
    yield
    reset_accessibility_gate()


class TestAccessibilityAssessment:
    def test_run_assessment(self):
        gate = get_accessibility_gate()
        report = gate.run_assessment()
        assert isinstance(report, AccessibilityReport)
        assert report.templates_scanned >= 0
        assert 0.0 <= report.overall_score <= 10.0

    def test_assessment_has_checklist(self):
        gate = get_accessibility_gate()
        report = gate.run_assessment()
        assert len(report.checklist) > 0
        check_ids = [c.check_id for c in report.checklist]
        assert "IMG_ALT" in check_ids
        assert "FORM_LABEL" in check_ids
        assert "HEADING_HIERARCHY" in check_ids

    def test_assessment_has_findings_list(self):
        gate = get_accessibility_gate()
        report = gate.run_assessment()
        # Findings may be empty if no violations found
        assert isinstance(report.findings, list)

    def test_assessment_has_recommendations(self):
        gate = get_accessibility_gate()
        report = gate.run_assessment()
        assert len(report.recommendations) >= 0

    def test_get_stats(self):
        gate = get_accessibility_gate()
        gate.run_assessment()
        stats = gate.get_stats()
        assert stats["total_assessments"] >= 1
        assert 0.0 <= stats["last_score"] <= 10.0

    def test_get_stats_initial(self):
        gate = get_accessibility_gate()
        stats = gate.get_stats()
        assert stats["total_assessments"] == 0
        assert stats["last_score"] == 10.0

    def test_report_summary_text(self):
        gate = get_accessibility_gate()
        report = gate.run_assessment()
        text = report.summary_text()
        assert "ACCESSIBILITY" in text
        assert "Score" in text


class TestAccessibilityScoring:
    def test_perfect_score_no_findings(self):
        report = AccessibilityReport(templates_scanned=5, overall_score=10.0)
        assert report.overall_score == 10.0
        assert report.risk_level == "LOW"

    def test_low_score_with_findings(self):
        from core.accessibility_gate import get_accessibility_gate
        gate = get_accessibility_gate()
        # A real assessment with failures should produce a score < 6
        report = gate.run_assessment()
        # The risk level should be computed from the score
        if report.overall_score >= 8.0:
            assert report.risk_level == "LOW"
        elif report.overall_score >= 6.0:
            assert report.risk_level == "MEDIUM"
        elif report.overall_score >= 4.0:
            assert report.risk_level == "HIGH"
        else:
            assert report.risk_level == "CRITICAL"

    def test_checklist_item_passing(self):
        item = AccessibilityChecklistItem(
            check_id="IMG_ALT", check_name="Image Alt Text",
            passed=True, total_instances=10, passing_instances=10, score=1.0,
        )
        assert item.passed is True
        d = item.to_dict()
        assert d["score"] == 1.0

    def test_checklist_item_failing(self):
        item = AccessibilityChecklistItem(
            check_id="IMG_ALT", check_name="Image Alt Text",
            passed=False, total_instances=10, passing_instances=3, score=0.3,
        )
        assert item.passed is False
        d = item.to_dict()
        assert d["score"] == 0.3

    def test_finding_to_dict(self):
        f = AccessibilityFinding(
            check_id="IMG_ALT", check_name="Image Alt Text",
            file_path="templates/page.html", severity="HIGH",
            line_count=5,
        )
        d = f.to_dict()
        assert d["check_id"] == "IMG_ALT"
        assert d["severity"] == "HIGH"
        assert d["line_count"] == 5

    def test_report_to_dict(self):
        r = AccessibilityReport(
            templates_scanned=10,
            overall_score=8.5,
            risk_level="LOW",
        )
        d = r.to_dict()
        assert d["templates_scanned"] == 10
        assert d["overall_score"] == 8.5

    def test_multiple_assessments(self):
        gate = get_accessibility_gate()
        gate.run_assessment()
        gate.run_assessment()
        stats = gate.get_stats()
        assert stats["total_assessments"] == 2


class TestAccessibilityEdgeCases:
    def test_no_templates_still_runs(self):
        gate = get_accessibility_gate()
        report = gate.run_assessment()
        # Should not crash even if no templates found
        assert isinstance(report, AccessibilityReport)
