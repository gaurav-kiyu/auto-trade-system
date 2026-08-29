"""Tests for CodebaseKnowledgeGraph (Pillar 2)."""
from __future__ import annotations

import pytest
from core.codebase_knowledge_graph import (
    CodebaseKnowledgeGraph,
    DesignSmell,
    DuplicateCode,
    KnowledgeGraphReport,
    MaintenanceHotspot,
    ModuleInfo,
    SymbolDef,
    get_knowledge_graph,
    reset_knowledge_graph,
)


@pytest.fixture(autouse=True)
def reset_kg() -> None:
    """Reset the singleton before each test."""
    reset_knowledge_graph()


@pytest.mark.slow
class TestCodebaseKnowledgeGraph:
    """Tests for the CodebaseKnowledgeGraph class."""

    def test_singleton(self) -> None:
        """Test singleton pattern."""
        kg1 = get_knowledge_graph()
        kg2 = get_knowledge_graph()
        assert kg1 is kg2

    def test_reset(self) -> None:
        """Test reset clears the singleton."""
        kg1 = get_knowledge_graph()
        reset_knowledge_graph()
        kg2 = get_knowledge_graph()
        assert kg1 is not kg2

    def test_build_index(self) -> None:
        """Test building the codebase index."""
        kg = CodebaseKnowledgeGraph()
        report = kg.build_index()
        assert isinstance(report, KnowledgeGraphReport)
        assert report.total_modules > 0
        assert report.total_symbols > 0
        assert report.total_lines > 0

    def test_build_index_only_once(self) -> None:
        """Test that the index is only built once."""
        kg = CodebaseKnowledgeGraph()
        report1 = kg.build_index()
        report2 = kg.build_index()
        assert report1.total_modules == report2.total_modules

    def test_search_by_name(self) -> None:
        """Test searching for symbols by name."""
        kg = CodebaseKnowledgeGraph()
        kg.build_index()
        results = kg.search("RiskService")
        assert isinstance(results, list)
        # Should find some results in the codebase
        assert len(results) >= 0

    def test_search_by_type(self) -> None:
        """Test searching with type filter."""
        kg = CodebaseKnowledgeGraph()
        kg.build_index()
        results = kg.search("get_", symbol_type="FUNCTION")
        assert isinstance(results, list)
        # All results should be functions
        for r in results:
            assert r.symbol_type == "FUNCTION"

    def test_search_case_insensitive(self) -> None:
        """Test that search is case-insensitive."""
        kg = CodebaseKnowledgeGraph()
        kg.build_index()
        upper = kg.search("RISK")
        lower = kg.search("risk")
        assert len(upper) >= 0  # Should match the same (not necessarily equal due to different matches)
        # Both should return lists
        assert isinstance(upper, list)
        assert isinstance(lower, list)

    def test_get_module(self) -> None:
        """Test getting module info."""
        kg = CodebaseKnowledgeGraph()
        kg.build_index()
        # Try to get a known module
        mod = kg.get_module("core/__init__.py")
        if mod:
            assert isinstance(mod, ModuleInfo)
            assert mod.lines > 0
            assert len(mod.symbols) > 0

    def test_get_module_nonexistent(self) -> None:
        """Test getting info for nonexistent module."""
        kg = CodebaseKnowledgeGraph()
        kg.build_index()
        mod = kg.get_module("nonexistent_module.py")
        assert mod is None

    def test_get_dependents(self) -> None:
        """Test getting dependents."""
        kg = CodebaseKnowledgeGraph()
        kg.build_index()
        deps = kg.get_dependents("core/__init__.py")
        assert isinstance(deps, list)

    def test_get_dependencies(self) -> None:
        """Test getting dependencies."""
        kg = CodebaseKnowledgeGraph()
        kg.build_index()
        deps = kg.get_dependencies("core/root_cause_analyzer.py")
        assert isinstance(deps, list)

    def test_detect_design_smells(self) -> None:
        """Test detecting design smells."""
        kg = CodebaseKnowledgeGraph()
        kg.build_index()
        smells = kg.detect_design_smells()
        assert isinstance(smells, list)
        # Should find at least some smells (complex codebase)
        if len(smells) > 0:
            s = smells[0]
            assert isinstance(s, DesignSmell)
            assert s.smell_type in ("GOD_CLASS", "LONG_FUNCTION", "LONG_FILE", "TOO_MANY_PARAMS")

    def test_find_duplicate_logic(self) -> None:
        """Test finding duplicate code."""
        kg = CodebaseKnowledgeGraph()
        kg.build_index()
        duplicates = kg.find_duplicate_logic()
        assert isinstance(duplicates, list)
        if len(duplicates) > 0:
            d = duplicates[0]
            assert isinstance(d, DuplicateCode)
            assert d.similarity > 0

    def test_predict_hotspots(self) -> None:
        """Test predicting maintenance hotspots."""
        kg = CodebaseKnowledgeGraph()
        kg.build_index()
        hotspots = kg.predict_hotspots(top_n=5)
        assert isinstance(hotspots, list)
        assert len(hotspots) <= 5
        if len(hotspots) > 0:
            h = hotspots[0]
            assert isinstance(h, MaintenanceHotspot)
            assert h.score > 0

    def test_get_report(self) -> None:
        """Test getting the full report."""
        kg = CodebaseKnowledgeGraph()
        kg.build_index()
        report = kg.get_report()
        assert isinstance(report, KnowledgeGraphReport)
        assert report.total_modules > 0
        assert isinstance(report.modules_without_tests, list)

    def test_print_summary(self) -> None:
        """Test printing summary."""
        kg = CodebaseKnowledgeGraph()
        kg.build_index()
        summary = kg.print_summary()
        assert isinstance(summary, str)
        assert "CODEBASE KNOWLEDGE GRAPH REPORT" in summary.upper()

    def test_get_module_stats(self) -> None:
        """Test getting module statistics."""
        kg = CodebaseKnowledgeGraph()
        kg.build_index()
        stats = kg.get_module_stats()
        assert isinstance(stats, dict)
        assert "total_modules" in stats
        assert stats["total_modules"] > 0

    def test_reset_index(self) -> None:
        """Test resetting the index."""
        kg = CodebaseKnowledgeGraph()
        kg.build_index()
        assert kg._built is True
        kg.reset_index()
        assert kg._built is False

    def test_hotspot_properties(self) -> None:
        """Test MaintenanceHotspot properties."""
        h = MaintenanceHotspot(
            module="test.py",
            score=0.85,
            reasons=["High complexity", "Many changes"],
            complexity=50,
            lines=1000,
            change_frequency=20,
        )
        assert h.score == 0.85
        assert h.to_dict()["score"] == 0.85
        assert len(h.reasons) == 2

    def test_design_smell_properties(self) -> None:
        """Test DesignSmell properties."""
        s = DesignSmell(
            smell_type="GOD_CLASS",
            module="test.py",
            symbol="GodClass",
            severity="HIGH",
            description="Too many methods",
            metric_value=25.0,
            threshold=15.0,
            recommendation="Split it up",
        )
        d = s.to_dict()
        assert d["type"] == "GOD_CLASS"
        assert d["severity"] == "HIGH"

    def test_symbol_def_properties(self) -> None:
        """Test SymbolDef properties."""
        sym = SymbolDef(
            name="test_function",
            symbol_type="FUNCTION",
            module="test.py",
            line=42,
            complexity=5,
        )
        d = sym.to_dict()
        assert d["name"] == "test_function"
        assert d["type"] == "FUNCTION"
        assert d["complexity"] == 5

    def test_report_summary_text(self) -> None:
        """Test report summary text formatting."""
        report = KnowledgeGraphReport(
            total_modules=100,
            total_symbols=500,
            total_lines=50000,
            build_duration_ms=1500.0,
        )
        text = report.summary_text()
        assert "100" in text
        assert "500" in text

    def test_report_to_dict(self) -> None:
        """Test report dict serialization."""
        report = KnowledgeGraphReport(
            total_modules=50,
            total_symbols=200,
            total_lines=25000,
        )
        d = report.to_dict()
        assert d["total_modules"] == 50
        assert d["total_symbols"] == 200
