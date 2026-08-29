"""Tests for ImpactAnalysisEngine (Pillar 4)."""
from __future__ import annotations

from pathlib import Path

import pytest
from core.impact_analysis_engine import (
    ImpactAnalysisEngine,
    ImpactReport,
    analyze_change,
    get_impact_engine,
    reset_impact_engine,
)


@pytest.fixture(autouse=True)
def reset_engine() -> None:
    """Reset the singleton before each test."""
    reset_impact_engine()


@pytest.mark.slow
class TestImpactAnalysisEngine:
    """Tests for the ImpactAnalysisEngine class."""

    def test_singleton(self) -> None:
        """Test singleton pattern."""
        engine1 = get_impact_engine()
        engine2 = get_impact_engine()
        assert engine1 is engine2

    def test_reset(self) -> None:
        """Test reset clears the singleton."""
        engine1 = get_impact_engine()
        reset_impact_engine()
        engine2 = get_impact_engine()
        assert engine1 is not engine2

    def test_initial_state(self) -> None:
        """Test initial state before graph is built."""
        engine = ImpactAnalysisEngine()
        assert engine._graph_built is False
        assert len(engine._dependency_graph) == 0

    def test_build_dependency_graph(self) -> None:
        """Test building the dependency graph."""
        engine = ImpactAnalysisEngine()
        engine.build_dependency_graph()
        assert engine._graph_built is True
        # Should have found core modules
        assert len(engine._dependency_graph) > 0
        # Should have found Python files
        assert any("core/" in key for key in engine._dependency_graph)

    def test_build_only_once(self) -> None:
        """Test that the graph is only built once."""
        engine = ImpactAnalysisEngine()
        engine.build_dependency_graph()
        n = len(engine._dependency_graph)
        engine.build_dependency_graph()
        assert len(engine._dependency_graph) == n  # No new modules added

    def test_get_dependents(self) -> None:
        """Test getting dependents returns a list."""
        engine = ImpactAnalysisEngine()
        engine.build_dependency_graph()
        # Test with a known module
        dependents = engine.get_dependents("core/services/risk_service.py")
        assert isinstance(dependents, list)

    def test_get_dependencies(self) -> None:
        """Test getting dependencies returns a list."""
        engine = ImpactAnalysisEngine()
        engine.build_dependency_graph()
        deps = engine.get_dependencies("core/impact_analysis_engine.py")
        assert isinstance(deps, list)

    def test_analyze_change_basic(self) -> None:
        """Test basic change analysis."""
        engine = ImpactAnalysisEngine()
        report = engine.analyze_change("core/impact_analysis_engine.py", "MODIFY")
        assert isinstance(report, ImpactReport)
        assert report.changed_file == "core/impact_analysis_engine.py"
        assert report.change_type == "MODIFY"
        # Should have export dependencies (what it imports)
        assert len(report.export_dependencies) > 0

    def test_analyze_change_return_fields(self) -> None:
        """Test that all report fields are populated."""
        engine = ImpactAnalysisEngine()
        report = engine.analyze_change("core/impact_analysis_engine.py")
        # Check all fields exist
        assert report.summary != ""
        assert report.business_impact in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert report.technical_impact in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert report.regression_risk in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert report.estimated_effort_minutes > 0

    def test_analyze_change_add_type(self) -> None:
        """Test analysis with ADD change type."""
        engine = ImpactAnalysisEngine()
        report = engine.analyze_change("core/impact_analysis_engine.py", "ADD")
        assert report.change_type == "ADD"

    def test_analyze_change_delete_type(self) -> None:
        """Test analysis with DELETE change type."""
        engine = ImpactAnalysisEngine()
        report = engine.analyze_change("core/impact_analysis_engine.py", "DELETE")
        assert report.change_type == "DELETE"

    def test_analyze_nonexistent_file(self) -> None:
        """Test analyzing a nonexistent file."""
        engine = ImpactAnalysisEngine()
        report = engine.analyze_change("nonexistent_module.py")
        assert report is not None
        assert report.changed_file == "nonexistent_module.py"

    def test_report_to_dict(self) -> None:
        """Test report serialization to dict."""
        engine = ImpactAnalysisEngine()
        report = engine.analyze_change("core/impact_analysis_engine.py")
        data = report.to_dict()
        assert isinstance(data, dict)
        assert "changed_file" in data
        assert "change_type" in data
        assert "business_impact" in data
        assert "technical_impact" in data
        assert "regression_risk" in data
        assert "affected_services" in data
        assert "recommended_actions" in data

    def test_report_summary_text(self) -> None:
        """Test report text summary."""
        engine = ImpactAnalysisEngine()
        report = engine.analyze_change("core/impact_analysis_engine.py")
        summary = report.summary_text()
        assert isinstance(summary, str)
        assert len(summary) > 20
        assert "IMPACT ANALYSIS" in summary.upper()

    def test_parse_imports(self) -> None:
        """Test import parsing from a Python file."""
        engine = ImpactAnalysisEngine()
        imports = engine._parse_imports(Path("core/impact_analysis_engine.py"))
        assert isinstance(imports, set)
        assert len(imports) > 0
        # Should find standard library and project imports
        assert any("ast" in i or "threading" in i for i in imports)

    def test_parse_api_routes(self) -> None:
        """Test API route parsing."""
        engine = ImpactAnalysisEngine()
        # Test with the dashboard intelligence routes
        router_path = Path("core/enterprise_dashboard/routes/intelligence.py")
        if router_path.is_file():
            routes = engine._parse_api_routes(router_path)
            assert isinstance(routes, list)
            # Should have found intelligence routes
            assert len(routes) > 0
            assert all("method" in r and "route" in r for r in routes)

    def test_parse_api_routes_nonexistent(self) -> None:
        """Test API route parsing with nonexistent file."""
        engine = ImpactAnalysisEngine()
        routes = engine._parse_api_routes(Path("nonexistent.py"))
        assert routes == []

    def test_get_module_stats(self) -> None:
        """Test module statistics."""
        engine = ImpactAnalysisEngine()
        engine.build_dependency_graph()
        stats = engine.get_module_stats()
        assert isinstance(stats, dict)
        assert "total_modules" in stats
        assert stats["total_modules"] > 0
        assert "total_apis" in stats
        assert "total_tests_mapped" in stats

    def test_find_dead_modules_returns_list(self) -> None:
        """Test dead module detection returns a list."""
        engine = ImpactAnalysisEngine()
        engine.build_dependency_graph()
        dead = engine.find_dead_modules()
        assert isinstance(dead, list)

    def test_reset_graph(self) -> None:
        """Test resetting the dependency graph."""
        engine = ImpactAnalysisEngine()
        engine.build_dependency_graph()
        assert engine._graph_built is True
        engine.reset_graph()
        assert engine._graph_built is False
        assert len(engine._dependency_graph) == 0

    def test_convenience_function(self) -> None:
        """Test the analyze_change convenience function."""
        report = analyze_change("core/impact_analysis_engine.py")
        assert isinstance(report, ImpactReport)
        assert report.changed_file == "core/impact_analysis_engine.py"

    def test_impact_high_for_critical_module(self) -> None:
        """Test that critical modules get HIGH business impact."""
        # Mock critical module
        engine = ImpactAnalysisEngine()
        engine.build_dependency_graph()
        report = engine.analyze_change("core/services/risk_service.py")
        assert report.business_impact in ("HIGH", "CRITICAL")

    def test_recommendations_generated(self) -> None:
        """Test that recommendations are generated."""
        engine = ImpactAnalysisEngine()
        report = engine.analyze_change("core/impact_analysis_engine.py")
        assert isinstance(report.recommended_actions, list)

    def test_to_rel_conversion(self) -> None:
        """Test path to relative conversion."""
        engine = ImpactAnalysisEngine()
        rel = engine._to_rel(Path("core/test_file.py"))
        assert "core/test_file.py" in rel or "core\\test_file.py" in rel


class TestImpactReport:
    """Tests for the ImpactReport dataclass."""

    def test_default_values(self) -> None:
        """Test default values of a new report."""
        report = ImpactReport(changed_file="test.py", change_type="MODIFY")
        assert report.business_impact == "LOW"
        assert report.technical_impact == "LOW"
        assert report.regression_risk == "LOW"
        assert report.affected_apis == []
        assert report.affected_tests == []

    def test_to_dict_complete(self) -> None:
        """Test dict serialization with complete data."""
        report = ImpactReport(
            changed_file="test.py",
            change_type="MODIFY",
            business_impact="HIGH",
            technical_impact="MEDIUM",
            regression_risk="MEDIUM",
            summary="Test summary",
        )
        data = report.to_dict()
        assert data["business_impact"] == "HIGH"
        assert data["technical_impact"] == "MEDIUM"
        assert data["summary"] == "Test summary"

    def test_summary_text_contains_file(self) -> None:
        """Test summary contains the file name."""
        report = ImpactReport(changed_file="core/foo.py", change_type="MODIFY")
        text = report.summary_text()
        assert "core/foo.py" in text or "foo.py" in text
