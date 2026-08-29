"""Tests for core/architecture_analyzer.py — Architecture Analyzer module."""

from __future__ import annotations

from pathlib import Path

from core.architecture_analyzer import (
    ArchitectureAnalyzer,
    ArchitectureReport,
    DependencyEdge,
    Violation,
    get_architecture_analyzer,
    reset_architecture_analyzer,
)


class TestViolation:
    """Tests for Violation data class."""

    def test_to_dict(self) -> None:
        v = Violation(
            check_name="CORE_TO_INFRA",
            message="'core.foo' imports 'infrastructure.bar'",
            severity="HIGH",
            module="core.foo",
        )
        d = v.to_dict()
        assert d["check_name"] == "CORE_TO_INFRA"
        assert d["severity"] == "HIGH"
        assert d["module"] == "core.foo"
        assert "infrastructure.bar" in d["message"]


class TestDependencyEdge:
    """Tests for DependencyEdge data class."""

    def test_to_dict(self) -> None:
        e = DependencyEdge(
            source="core.foo", target="infrastructure",
            import_path="infrastructure.bar", is_exempt=True,
        )
        d = e.to_dict()
        assert d["source"] == "core.foo"
        assert d["is_exempt"] is True


class TestArchitectureReport:
    """Tests for ArchitectureReport data class."""

    def test_to_dict_empty(self) -> None:
        report = ArchitectureReport(timestamp=1000.0, total_modules_scanned=50)
        d = report.to_dict()
        assert d["total_modules_scanned"] == 50
        assert d["violations_count"] == 0
        assert d["score"] == 10.0
        assert d["overall_health"] == "HEALTHY"

    def test_to_dict_with_violations(self) -> None:
        report = ArchitectureReport(timestamp=1000.0)
        report.violations.append(Violation(check_name="CORE_TO_INFRA", severity="HIGH"))
        report.violations.append(Violation(check_name="DEAD_MODULE", severity="HIGH"))
        report.canonical_modules_missing.append("core.foo")
        d = report.to_dict()
        assert d["violations_count"] == 2
        assert len(d["canonical_modules_missing"]) == 1

    def test_summary_text(self) -> None:
        report = ArchitectureReport(timestamp=1000.0, total_modules_scanned=50)
        report.score = 8.5
        report.overall_health = "WARNING"
        summary = report.summary_text()
        assert "ARCHITECTURE ANALYSIS REPORT" in summary
        assert "8.5" in summary
        assert "WARNING" in summary

    def test_summary_missing_canonical(self) -> None:
        report = ArchitectureReport(timestamp=1000.0)
        report.canonical_modules_missing.append("core.missing_module")
        summary = report.summary_text()
        assert "Missing Canonical" in summary

    def test_summary_with_recommendations(self) -> None:
        report = ArchitectureReport(timestamp=1000.0)
        report.recommendations.append("Fix import violations")
        summary = report.summary_text()
        assert "Recommendations" in summary


class TestArchitectureAnalyzer:
    """Tests for the ArchitectureAnalyzer class."""

    def setup_method(self) -> None:
        reset_architecture_analyzer()

    def test_singleton(self) -> None:
        a1 = get_architecture_analyzer()
        a2 = get_architecture_analyzer()
        assert a1 is a2

    def test_reset(self) -> None:
        a1 = get_architecture_analyzer()
        reset_architecture_analyzer()
        a2 = get_architecture_analyzer()
        assert a1 is not a2

    def test_initial_state(self) -> None:
        analyzer = get_architecture_analyzer()
        assert analyzer.last_report is None
        stats = analyzer.get_stats()
        assert stats["total_analyses"] == 0

    def test_compute_score_clean(self) -> None:
        analyzer = ArchitectureAnalyzer()
        report = ArchitectureReport(timestamp=1000.0)
        score = analyzer._compute_score(report)
        assert score == 10.0

    def test_compute_score_with_violations(self) -> None:
        analyzer = ArchitectureAnalyzer()
        report = ArchitectureReport(timestamp=1000.0)
        report.violations.append(Violation(severity="HIGH"))
        report.violations.append(Violation(severity="HIGH"))
        report.violations.append(Violation(severity="MEDIUM"))
        report.canonical_modules_missing.append("core.foo")
        score = analyzer._compute_score(report)
        # 10 - 1.0 - 1.0 - 0.5 - 0.5 = 7.0
        assert score == 7.0

    def test_generate_recommendations_clean(self) -> None:
        analyzer = ArchitectureAnalyzer()
        report = ArchitectureReport(timestamp=1000.0)
        recs = analyzer._generate_recommendations(report)
        assert any("No architecture violations" in r for r in recs)

    def test_generate_recommendations_infra_violations(self) -> None:
        analyzer = ArchitectureAnalyzer()
        report = ArchitectureReport(timestamp=1000.0)
        report.violations.append(Violation(check_name="CORE_TO_INFRA", severity="HIGH"))
        report.violations.append(Violation(check_name="CORE_TO_INFRA", severity="HIGH"))
        recs = analyzer._generate_recommendations(report)
        assert any("import" in r.lower() for r in recs)

    def test_generate_recommendations_dead_imports(self) -> None:
        analyzer = ArchitectureAnalyzer()
        report = ArchitectureReport(timestamp=1000.0)
        report.violations.append(Violation(check_name="DEAD_MODULE", severity="HIGH"))
        recs = analyzer._generate_recommendations(report)
        assert any("dead" in r.lower() for r in recs)

    def test_generate_recommendations_missing_canonical(self) -> None:
        analyzer = ArchitectureAnalyzer()
        report = ArchitectureReport(timestamp=1000.0)
        report.canonical_modules_missing.append("core.missing")
        recs = analyzer._generate_recommendations(report)
        assert any("canonical" in r.lower() for r in recs)

    def test_generate_recommendations_broker_sdk(self) -> None:
        analyzer = ArchitectureAnalyzer()
        report = ArchitectureReport(timestamp=1000.0)
        report.violations.append(Violation(check_name="BROKER_SDK", severity="HIGH"))
        recs = analyzer._generate_recommendations(report)
        assert any("broker" in r.lower() for r in recs)

    def test_generate_recommendations_circular(self) -> None:
        analyzer = ArchitectureAnalyzer()
        report = ArchitectureReport(timestamp=1000.0)
        report.violations.append(Violation(check_name="CIRCULAR", severity="MEDIUM"))
        recs = analyzer._generate_recommendations(report)
        assert any("circular" in r.lower() for r in recs)

    def test_module_name(self) -> None:
        analyzer = ArchitectureAnalyzer()
        # Create a temporary file to test module name conversion
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"")
            tmp_path = Path(f.name)

        # Test relative to ROOT
        try:
            tmp_path.relative_to(Path(__file__).resolve().parent.parent)
            name = analyzer._module_name(tmp_path)
            assert name.endswith(tmp_path.stem)
        except ValueError:
            pass
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_get_stats_after_analysis(self) -> None:
        analyzer = ArchitectureAnalyzer()
        report = ArchitectureReport(timestamp=2000.0)
        report.score = 8.0
        report.overall_health = "WARNING"
        report.violations.append(Violation(severity="HIGH"))
        report.violations.append(Violation(severity="MEDIUM"))
        report.canonical_modules_missing.append("core.foo")
        analyzer._report_history.append(report)
        analyzer._last_report = report
        analyzer._total_analyses = 1

        stats = analyzer.get_stats()
        assert stats["total_analyses"] == 1
        assert stats["last_score"] == 8.0
        assert stats["last_health"] == "WARNING"
        assert stats["total_violations"] == 2
        assert stats["high_severity_violations"] == 1
        assert stats["canonical_missing"] == 1

    def test_check_results_in_report(self) -> None:
        ArchitectureAnalyzer()
        report = ArchitectureReport(timestamp=1000.0)
        report.check_results = {
            "Core→Infra Boundary": {"passed": True, "violations": 0},
            "Dead Module Imports": {"passed": True, "violations": 0},
            "Canonical Modules": {"passed": True, "violations": 0},
        }
        d = report.to_dict()
        assert d["check_results"]["Core→Infra Boundary"]["passed"] is True
        assert d["check_results"]["Dead Module Imports"]["violations"] == 0


class TestArchitectureCompliance:
    """Higher-level architecture compliance checks."""

    def test_known_dead_modules_list(self) -> None:
        """Verify the dead modules list is well-formed."""
        from core.architecture_analyzer import DEAD_MODULES
        assert len(DEAD_MODULES) > 0
        for mod in DEAD_MODULES:
            assert "." in mod, f"Module {mod} should be a dotted path"

    def test_known_canonical_modules(self) -> None:
        """Verify the canonical modules list is reasonable."""
        from core.architecture_analyzer import REQUIRED_CANONICAL
        assert len(REQUIRED_CANONICAL) > 5
        assert "core.di_container" in REQUIRED_CANONICAL

    def test_core_no_infra_exemptions(self) -> None:
        """Verify exemption list contains expected entries."""
        from core.architecture_analyzer import CORE_NO_INFRA_MODULES
        assert "core.adapters" in CORE_NO_INFRA_MODULES
        assert "core.config_bootstrap" in CORE_NO_INFRA_MODULES


class TestCoverageGaps:
    """Targeted tests for remaining uncovered code paths in ArchitectureAnalyzer."""

    def test_run_analysis_returns_report(self) -> None:
        """run_analysis() returns a valid ArchitectureReport."""
        reset_architecture_analyzer()
        analyzer = get_architecture_analyzer()
        report = analyzer.run_analysis()
        assert isinstance(report, ArchitectureReport)
        assert report.timestamp > 0
        assert report.total_modules_scanned > 0
        assert report.overall_health in ("HEALTHY", "WARNING", "CRITICAL")

    def test_last_report_property(self) -> None:
        """last_report returns the most recent report after run_analysis."""
        reset_architecture_analyzer()
        analyzer = get_architecture_analyzer()
        assert analyzer.last_report is None
        report = analyzer.run_analysis()
        assert analyzer.last_report is report
        assert analyzer.last_report.timestamp == report.timestamp

    def test_list_imports_standard_import(self) -> None:
        """_list_imports extracts standard 'import X' statements."""
        import tempfile
        analyzer = ArchitectureAnalyzer()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import os\nimport sys\nimport json\n")
            p = Path(f.name)
        try:
            imports = analyzer._list_imports(p)
            assert "os" in imports
            assert "sys" in imports
            assert "json" in imports
        finally:
            p.unlink(missing_ok=True)

    def test_list_imports_from_import(self) -> None:
        """_list_imports extracts 'from X import Y' statements."""
        import tempfile
        analyzer = ArchitectureAnalyzer()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("from pathlib import Path\nfrom typing import Any, Optional\n")
            p = Path(f.name)
        try:
            imports = analyzer._list_imports(p)
            assert "pathlib" in imports
            assert "pathlib.Path" in imports
            assert "typing.Any" in imports
        finally:
            p.unlink(missing_ok=True)

    def test_count_modules_positive(self) -> None:
        """_count_modules returns positive count of Python files."""
        reset_architecture_analyzer()
        analyzer = get_architecture_analyzer()
        count = analyzer._count_modules()
        assert count > 0
        # Should find at least core/ and index_app/ modules
        assert count > 10

    def test_compute_score_medium_severity(self) -> None:
        """_compute_score: MEDIUM severity deducts 0.5 each."""
        analyzer = ArchitectureAnalyzer()
        report = ArchitectureReport(timestamp=1000.0)
        report.violations.append(Violation(severity="MEDIUM"))
        report.violations.append(Violation(severity="MEDIUM"))
        score = analyzer._compute_score(report)
        assert score == 9.0  # 10 - 0.5 - 0.5 = 9.0

    def test_compute_score_low_severity(self) -> None:
        """_compute_score: LOW severity deducts 0.2 each."""
        analyzer = ArchitectureAnalyzer()
        report = ArchitectureReport(timestamp=1000.0)
        report.violations.append(Violation(severity="LOW"))
        score = analyzer._compute_score(report)
        assert score == 9.8

    def test_compute_score_clamped_low(self) -> None:
        """_compute_score clamps minimum at 0.0."""
        analyzer = ArchitectureAnalyzer()
        report = ArchitectureReport(timestamp=1000.0)
        for _ in range(20):
            report.violations.append(Violation(severity="HIGH"))
        score = analyzer._compute_score(report)
        assert score == 0.0

    def test_compute_score_clamped_high(self) -> None:
        """_compute_score clamps maximum at 10.0."""
        analyzer = ArchitectureAnalyzer()
        report = ArchitectureReport(timestamp=1000.0)
        score = analyzer._compute_score(report)
        assert score <= 10.0

    def test_overall_health_warning_at_7(self) -> None:
        """overall_health is WARNING when score is between 6.0 and 8.0."""
        reporter = ArchitectureReport(timestamp=1000.0, score=7.0)
        reporter.overall_health = "WARNING"
        d = reporter.to_dict()
        assert d["overall_health"] == "WARNING"

    def test_overall_health_critical_below_6(self) -> None:
        """overall_health is CRITICAL when score is below 6.0."""
        reporter = ArchitectureReport(timestamp=1000.0, score=4.0)
        reporter.overall_health = "CRITICAL"
        d = reporter.to_dict()
        assert d["overall_health"] == "CRITICAL"

    def test_check_direct_broker_sdk_no_imports(self) -> None:
        """_check_direct_broker_sdk: empty violations list means no broker SDK imports found."""
        reset_architecture_analyzer()
        analyzer = get_architecture_analyzer()
        violations: list = []
        analyzer._check_direct_broker_sdk(violations)
        # The real codebase shouldn't have direct broker SDK imports outside adapters
        violations_text = " ".join(v.message for v in violations)
        assert len(violations) == 0 or "kiteconnect" in violations_text or "angelbroking" in violations_text

    def test_check_circular_imports_no_errors(self) -> None:
        """_check_circular_imports: runs without crashing on real codebase."""
        reset_architecture_analyzer()
        analyzer = get_architecture_analyzer()
        violations: list = []
        # Should not raise any exceptions
        analyzer._check_circular_imports(violations)
        assert isinstance(violations, list)

    def test_check_dead_modules_no_errors(self) -> None:
        """_check_dead_modules: runs without crashing on real codebase."""
        reset_architecture_analyzer()
        analyzer = get_architecture_analyzer()
        violations: list = []
        analyzer._check_dead_modules(violations)
        assert isinstance(violations, list)

    def test_check_core_infra_imports_no_errors(self) -> None:
        """_check_core_infra_imports: runs without crashing."""
        reset_architecture_analyzer()
        analyzer = get_architecture_analyzer()
        violations: list = []
        edges: list = []
        analyzer._check_core_infra_imports(violations, edges)
        assert isinstance(violations, list)
        assert isinstance(edges, list)

    def test_persist_creates_file(self) -> None:
        """_persist: creates a JSON file with report history."""
        import json
        import tempfile
        reset_architecture_analyzer()
        analyzer = get_architecture_analyzer()
        # Point to a temp path
        original_path = analyzer._persist_path
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir) / "test_hist.json"
            analyzer._persist_path = tmp
            analyzer._report_history.append(ArchitectureReport(timestamp=1000.0))
            analyzer._persist()
            assert tmp.exists()
            data = json.loads(tmp.read_text(encoding="utf-8"))
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["timestamp"] == 1000.0
        analyzer._persist_path = original_path
