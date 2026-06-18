"""
Tests for core.certification.report_generators - Certification Reports (Phases 3/4/5/14/19).

Validates:
  - Architecture Certification (Phase 3)
  - Risk Certification (Phase 4)
  - Security Certification (Phase 14)
  - Production Certification (Phase 19)
  - Greeks Certification (Phase 5)
  - All reports are evidence-based
  - Report scores are correctly calculated
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.certification.report_generators import (
    CertificationReport,
    CertCriteria,
    generate_all_reports,
    generate_architecture_certification,
    generate_greeks_certification,
    generate_production_certification,
    generate_risk_certification,
    generate_security_certification,
    save_reports_to_disk,
)


class TestCertCriteria:
    """Test CertCriteria dataclass."""

    def test_create_passed(self) -> None:
        c = CertCriteria(id="TEST-01", description="Test", passed=True, evidence="OK", score=1.0)
        assert c.passed
        assert c.score == 1.0

    def test_create_failed(self) -> None:
        c = CertCriteria(id="TEST-02", description="Test fail", passed=False, evidence="Failed", score=0.3)
        assert not c.passed
        assert c.recommendation == ""

    def test_to_dict(self) -> None:
        c = CertCriteria(id="TEST-03", description="Test", passed=True, evidence="OK", score=0.9, recommendation="Fix it")
        d = c.to_dict()
        assert d["id"] == "TEST-03"
        assert d["passed"] is True
        assert d["recommendation"] == "Fix it"


class TestCertificationReport:
    """Test CertificationReport dataclass."""

    def test_empty_criteria(self) -> None:
        r = CertificationReport(
            title="Test", phase="T", generated_at="now", version="1.0",
            certifier="test", criteria=[],
        )
        assert r.score == 0.0
        assert not r.passed

    def test_all_passed(self) -> None:
        r = CertificationReport(
            title="Test", phase="T", generated_at="now", version="1.0",
            certifier="test",
            criteria=[
                CertCriteria(id="C1", description="", passed=True, evidence="", score=1.0),
                CertCriteria(id="C2", description="", passed=True, evidence="", score=1.0),
            ],
        )
        assert r.score == 10.0
        assert r.passed

    def test_mixed_scores(self) -> None:
        r = CertificationReport(
            title="Test", phase="T", generated_at="now", version="1.0",
            certifier="test",
            criteria=[
                CertCriteria(id="C1", description="", passed=True, evidence="", score=1.0),
                CertCriteria(id="C2", description="", passed=False, evidence="", score=0.5),
            ],
        )
        assert r.score == 7.5  # (1.0 + 0.5) / 2 * 10 = 7.5
        assert not r.passed

    def test_summary(self) -> None:
        r = CertificationReport(
            title="Test Report", phase="T", generated_at="now", version="1.0",
            certifier="test",
            criteria=[
                CertCriteria(id="C1", description="Check 1", passed=True, evidence="OK", score=1.0),
            ],
        )
        summary = r.summary()
        assert isinstance(summary, str)
        assert "Test Report" in summary
        assert "10.00" in summary

    def test_to_json(self) -> None:
        r = CertificationReport(
            title="JSON Test", phase="T", generated_at="now", version="1.0",
            certifier="test", criteria=[],
        )
        j = r.to_json()
        data = json.loads(j)
        assert data["title"] == "JSON Test"


class TestArchitectureCertification:
    """Phase 3: Architecture Certification."""

    def test_generates(self) -> None:
        r = generate_architecture_certification()
        assert r.title == "Architecture Certification"
        assert r.phase == "3"
        assert len(r.criteria) > 0
        assert r.score >= 0

    def test_criteria_have_evidence(self) -> None:
        r = generate_architecture_certification()
        for c in r.criteria:
            assert len(c.evidence) > 0

    def test_config_passed(self) -> None:
        r = generate_architecture_certification(config={"KEY": "VAL"})
        assert r.score >= 0

    def test_all_criteria_ids(self) -> None:
        r = generate_architecture_certification()
        ids = [c.id for c in r.criteria]
        assert "ARCH-01" in ids
        assert "ARCH-02" in ids
        assert "ARCH-06" in ids


class TestRiskCertification:
    """Phase 4: Risk Certification."""

    def test_generates(self) -> None:
        r = generate_risk_certification()
        assert r.title == "Risk Certification"
        assert r.phase == "4"
        assert len(r.criteria) > 0

    def test_with_config(self) -> None:
        r = generate_risk_certification(
            config={
                "MAX_DAILY_LOSS": -2000,
                "MAX_DRAWDOWN": 0.20,
                "MAX_CONSECUTIVE_LOSSES": 3,
            },
        )
        assert r.score >= 0

    def test_all_criteria_ids(self) -> None:
        r = generate_risk_certification()
        ids = [c.id for c in r.criteria]
        assert "RSK-01" in ids
        assert "RSK-07" in ids


class TestSecurityCertification:
    """Phase 14: Security Certification."""

    def test_generates(self) -> None:
        r = generate_security_certification()
        assert r.title == "Security Certification"
        assert r.phase == "14"
        assert len(r.criteria) > 0

    def test_all_criteria_ids(self) -> None:
        r = generate_security_certification()
        ids = [c.id for c in r.criteria]
        assert "SEC-01" in ids
        assert "SEC-06" in ids

    def test_criteria_have_evidence(self) -> None:
        r = generate_security_certification()
        for c in r.criteria:
            assert len(c.evidence) > 0


class TestGreeksCertification:
    """Phase 5: Options Greeks Risk Certification."""

    def test_generates(self) -> None:
        r = generate_greeks_certification()
        assert r.title == "Options Greeks Risk Certification"
        assert r.phase == "5"
        assert len(r.criteria) > 0
        assert r.score > 0

    def test_all_criteria_ids(self) -> None:
        r = generate_greeks_certification()
        ids = [c.id for c in r.criteria]
        assert "GRK-01" in ids
        assert "GRK-05" in ids


class TestProductionCertification:
    """Phase 19: Production Certification."""

    def test_generates(self) -> None:
        r = generate_production_certification()
        assert r.title == "Production Certification"
        assert r.phase == "19"
        assert len(r.criteria) > 0

    def test_all_criteria_ids(self) -> None:
        r = generate_production_certification()
        ids = [c.id for c in r.criteria]
        assert "PROD-01" in ids
        assert "PROD-11" in ids


class TestAllReports:
    """Test the all-reports generator."""

    def test_generates_all(self) -> None:
        reports = generate_all_reports()
        assert len(reports) == 5
        assert "architecture" in reports
        assert "risk" in reports
        assert "security" in reports
        assert "production" in reports
        assert "greeks" in reports

    def test_all_have_scores(self) -> None:
        reports = generate_all_reports()
        for name, r in reports.items():
            assert r.score >= 0, f"{name} has invalid score {r.score}"
            assert len(r.criteria) > 0, f"{name} has no criteria"

    def test_with_config(self) -> None:
        reports = generate_all_reports(config={"MAX_DAILY_LOSS": -2000})
        assert len(reports) == 5


class TestSaveReports:
    """Test saving reports to disk."""

    def test_save(self, tmp_path) -> None:
        saved = save_reports_to_disk(output_dir=str(tmp_path))
        assert len(saved) == 6  # 5 individual + 1 combined
        for path in saved:
            p = Path(path)
            assert p.exists()
            content = p.read_text(encoding="utf-8")
            data = json.loads(content)
            assert len(data) > 0
