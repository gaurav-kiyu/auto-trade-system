"""Tests for DependencyAnalyzer (Vision Module — Dependency Mapper)."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.dependency_analyzer import (
    DependencyAnalyzer,
    DependencyNode,
    DependencyReport,
    get_dependency_analyzer,
    reset_dependency_analyzer,
)


class TestDependencyNode:
    """Tests for DependencyNode dataclass."""

    def test_defaults(self) -> None:
        node = DependencyNode(module_path="core/test.py")
        assert node.module_path == "core/test.py"
        assert node.imports == set()
        assert node.imported_by == set()
        assert node.category == "core"
        assert node.fan_in == 0
        assert node.fan_out == 0
        assert node.instability == 0.0  # 0 / max(1, 0+0) = 0

    def test_instability_stable(self) -> None:
        node = DependencyNode(
            module_path="core/stable.py",
            imports=set(),
            imported_by={"core/a.py", "core/b.py"},
        )
        assert node.fan_in == 2
        assert node.fan_out == 0
        assert node.instability == 0.0  # 0/(2+0) = 0

    def test_instability_unstable(self) -> None:
        node = DependencyNode(
            module_path="core/unstable.py",
            imports={"core/a.py", "core/b.py"},
            imported_by=set(),
        )
        assert node.fan_in == 0
        assert node.fan_out == 2
        assert node.instability == 1.0  # 2/(0+2) = 1

    def test_instability_balanced(self) -> None:
        node = DependencyNode(
            module_path="core/balanced.py",
            imports={"core/a.py"},
            imported_by={"core/b.py", "core/c.py", "core/d.py"},
        )
        assert node.fan_in == 3
        assert node.fan_out == 1
        assert node.instability == 0.25  # 1/(3+1) = 0.25

    def test_is_init(self) -> None:
        node = DependencyNode(
            module_path="core/__init__.py", is_init=True
        )
        assert node.is_init is True


class TestDependencyReport:
    """Tests for DependencyReport dataclass."""

    def test_defaults(self) -> None:
        report = DependencyReport()
        assert report.total_modules == 0
        assert report.total_edges == 0
        assert report.circular_dependencies == []
        assert report.coupling_score == 0.0

    def test_to_dict(self) -> None:
        report = DependencyReport(
            total_modules=100,
            total_edges=500,
            coupling_score=0.45,
            stability_score=0.72,
        )
        d = report.to_dict()
        assert d["total_modules"] == 100
        assert d["total_edges"] == 500
        assert d["coupling_score"] == 0.45

    def test_summary_text(self) -> None:
        report = DependencyReport(total_modules=50, total_edges=200)
        text = report.summary_text()
        assert "DEPENDENCY ANALYSIS REPORT" in text
        assert "50" in text

    def test_summary_with_circular(self) -> None:
        report = DependencyReport(
            total_modules=10,
            total_edges=20,
            circular_dependencies=[["a.py", "b.py", "a.py"]],
        )
        text = report.summary_text()
        assert "Circular" in text

    def test_summary_with_dead_modules(self) -> None:
        report = DependencyReport(
            total_modules=10,
            total_edges=5,
            dead_modules=["core/dead.py"],
        )
        text = report.summary_text()
        assert "Dead Modules" in text

    def test_summary_with_external_deps(self) -> None:
        report = DependencyReport(
            total_modules=10,
            total_edges=15,
            external_dependencies={"numpy": ["core/a.py"]},
        )
        text = report.summary_text()
        assert "External Packages" in text


class TestDependencyAnalyzerBuild:
    """Tests for building the dependency graph."""

    @pytest.fixture(autouse=True)
    def reset(self) -> None:
        reset_dependency_analyzer()

    def test_build_runs(self) -> None:
        """Building the full graph should not raise."""
        analyzer = DependencyAnalyzer()
        analyzer.build()
        assert analyzer._built is True

    def test_analyze_returns_report(self) -> None:
        """Analyze returns a DependencyReport."""
        analyzer = DependencyAnalyzer()
        report = analyzer.analyze()
        assert isinstance(report, DependencyReport)
        assert report.total_modules > 0

    def test_reset_clears(self) -> None:
        """Reset clears the built graph."""
        analyzer = DependencyAnalyzer()
        analyzer.build()
        assert analyzer._built is True
        analyzer.reset()
        assert analyzer._built is False

    def test_idempotent_build(self) -> None:
        """Build is idempotent (second call is no-op)."""
        analyzer = DependencyAnalyzer()
        analyzer.build()
        n1 = len(analyzer._nodes)
        analyzer.build()  # Should be no-op
        n2 = len(analyzer._nodes)
        assert n1 == n2

    def test_categorizes_correctly(self) -> None:
        """Modules are categorized correctly by path."""
        analyzer = DependencyAnalyzer()
        assert analyzer._categorize("core/foo.py") == "core"
        assert analyzer._categorize("core/ports/foo.py") == "core:ports"
        assert analyzer._categorize("core/patterns/foo.py") == "core:patterns"
        assert analyzer._categorize("tests/test_foo.py") == "test"
        assert analyzer._categorize("infrastructure/foo.py") == "infrastructure"
        assert analyzer._categorize("scripts/foo.py") == "scripts"
        assert analyzer._categorize("index_app/foo.py") == "app"


class TestDependencyAnalyzerQueries:
    """Tests for query methods on a built graph."""

    @pytest.fixture(autouse=True)
    def reset(self) -> None:
        reset_dependency_analyzer()

    def test_get_stats(self) -> None:
        """get_stats returns dict with expected keys."""
        analyzer = DependencyAnalyzer()
        stats = analyzer.get_stats()
        assert "total_modules" in stats
        assert "total_edges" in stats
        assert "built" in stats
        assert stats["total_modules"] > 0

    def test_get_report(self) -> None:
        """get_report returns DependencyReport."""
        analyzer = DependencyAnalyzer()
        report = analyzer.get_report()
        assert isinstance(report, DependencyReport)

    def test_get_module_dependencies(self) -> None:
        """get_module_dependencies returns list for known module."""
        analyzer = DependencyAnalyzer()
        deps = analyzer.get_module_dependencies("core/dependency_analyzer.py")
        assert isinstance(deps, list)

    def test_get_module_dependents(self) -> None:
        """get_module_dependents returns list for known module."""
        analyzer = DependencyAnalyzer()
        deps = analyzer.get_module_dependents("core/dependency_analyzer.py")
        assert isinstance(deps, list)

    def test_get_circular_dependencies(self) -> None:
        """get_circular_dependencies returns list of cycles."""
        analyzer = DependencyAnalyzer()
        cycles = analyzer.get_circular_dependencies()
        assert isinstance(cycles, list)

    def test_unknown_module_returns_empty(self) -> None:
        """Unknown module returns empty list."""
        analyzer = DependencyAnalyzer()
        deps = analyzer.get_module_dependencies("does/not/exist.py")
        assert deps == []
        dependents = analyzer.get_module_dependents("does/not/exist.py")
        assert dependents == []


class TestDependencyAnalyzerSingleton:
    """Tests for singleton factory."""

    def test_get_returns_instance(self) -> None:
        reset_dependency_analyzer()
        instance = get_dependency_analyzer()
        assert isinstance(instance, DependencyAnalyzer)

    def test_singleton(self) -> None:
        reset_dependency_analyzer()
        a = get_dependency_analyzer()
        b = get_dependency_analyzer()
        assert a is b

    def test_reset_clears(self) -> None:
        reset_dependency_analyzer()
        a = get_dependency_analyzer()
        reset_dependency_analyzer()
        b = get_dependency_analyzer()
        assert a is not b


class TestDependencyAnalyzerFullAnalysis:
    """Full integration tests for the analyze method."""

    @pytest.fixture(autouse=True)
    def reset(self) -> None:
        reset_dependency_analyzer()

    def test_report_has_modules(self) -> None:
        """Full analysis returns modules."""
        analyzer = DependencyAnalyzer()
        report = analyzer.analyze()
        assert report.total_modules > 50  # Should find at least 50 modules
        assert report.total_edges > 0

    def test_report_has_category_counts(self) -> None:
        """Category counts are populated."""
        analyzer = DependencyAnalyzer()
        report = analyzer.analyze()
        assert len(report.category_counts) >= 3  # At least core, test, app
        assert report.category_counts.get("core", 0) > 0

    def test_report_has_top_imported(self) -> None:
        """Top imported list is populated."""
        analyzer = DependencyAnalyzer()
        report = analyzer.analyze()
        assert len(report.top_imported) > 0

    def test_report_has_external_deps(self) -> None:
        """External dependencies are detected."""
        analyzer = DependencyAnalyzer()
        report = analyzer.analyze()
        # The project uses pytest, typing, etc.
        external = report.external_dependencies
        assert isinstance(external, dict)

    def test_coupling_score_range(self) -> None:
        """Coupling score is between 0 and 1."""
        analyzer = DependencyAnalyzer()
        report = analyzer.analyze()
        assert 0 <= report.coupling_score <= 1

    def test_stability_score_range(self) -> None:
        """Stability score is between 0 and 1."""
        analyzer = DependencyAnalyzer()
        report = analyzer.analyze()
        assert 0 <= report.stability_score <= 1


class TestDependencyAnalyzerEdgeCases:
    """Edge case tests."""

    def test_count_loc_empty(self, tmp_path: Path) -> None:
        """_count_loc handles empty files."""
        f = tmp_path / "empty.py"
        f.write_text("")
        analyzer = DependencyAnalyzer()
        count = analyzer._count_loc(f)
        assert count == 0

    def test_count_loc_with_content(self, tmp_path: Path) -> None:
        """_count_loc counts non-empty, non-comment lines."""
        f = tmp_path / "test.py"
        f.write_text("# comment\n\ndef foo():\n    pass\n")
        analyzer = DependencyAnalyzer()
        count = analyzer._count_loc(f)
        assert count == 2  # def foo():, pass

    def test_parse_imports_empty(self, tmp_path: Path) -> None:
        """_parse_imports returns empty for empty file."""
        f = tmp_path / "empty.py"
        f.write_text("")
        analyzer = DependencyAnalyzer()
        imports = analyzer._parse_imports(f)
        assert imports == set()

    def test_parse_imports_standard_lib(self, tmp_path: Path) -> None:
        """_parse_imports detects standard library imports."""
        f = tmp_path / "std.py"
        f.write_text("import os\nimport sys\nfrom pathlib import Path\n")
        analyzer = DependencyAnalyzer()
        imports = analyzer._parse_imports(f)
        assert "os" in imports
        assert "sys" in imports
        assert "pathlib" in imports

    def test_parse_imports_with_from(self, tmp_path: Path) -> None:
        """_parse_imports detects from-style imports."""
        f = tmp_path / "from_test.py"
        f.write_text("from typing import Any, Optional\nfrom collections.abc import Callable\n")
        analyzer = DependencyAnalyzer()
        imports = analyzer._parse_imports(f)
        assert "typing" in imports
        assert "collections.abc" in imports

    def test_parse_imports_skips_future(self, tmp_path: Path) -> None:
        """_parse_imports skips __future__ imports."""
        f = tmp_path / "fut.py"
        f.write_text("from __future__ import annotations\nimport os\n")
        analyzer = DependencyAnalyzer()
        imports = analyzer._parse_imports(f)
        assert "__future__" not in imports
        assert "os" in imports

    def test_resolve_import_direct(self) -> None:
        """_resolve_import finds direct match."""
        analyzer = DependencyAnalyzer()
        analyzer.build()
        result = analyzer._resolve_import("core.dependency_analyzer", "core/something.py")
        assert result is not None
        assert "dependency_analyzer" in result

    def test_categorize_other(self) -> None:
        """_categorize returns 'other' for unknown paths."""
        analyzer = DependencyAnalyzer()
        assert analyzer._categorize("vendor/some_lib.py") == "other"
