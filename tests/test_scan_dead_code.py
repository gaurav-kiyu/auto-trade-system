#!/usr/bin/env python3
"""Tests for scripts/scan_dead_code.py - Dead code and duplicate code scanning."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from scripts.scan_dead_code import (
    DeadCodeFinding,
    DuplicateFinding,
    _update_section_in_file,
    collect_module_exports,
    main,
)


class TestDeadCodeFinding:
    """Test DeadCodeFinding data class (fast - no I/O)."""

    def test_default_severity(self) -> None:
        f = DeadCodeFinding(category="UNUSED_IMPORT", file_path="test.py", line=1, name="foo", description="unused")
        assert f.severity == "MEDIUM"

    def test_to_dict(self) -> None:
        f = DeadCodeFinding(category="ORPHANED_FUNC", file_path="mod.py", line=10, name="bar", description="orphaned", severity="HIGH")
        d = f.to_dict()
        assert d["category"] == "ORPHANED_FUNC"
        assert d["severity"] == "HIGH"
        assert d["line"] == 10

    def test_defaults(self) -> None:
        f = DeadCodeFinding(category="EMPTY_BLOCK", file_path="empty.py", line=5, name="nothing", description="empty")
        assert f.severity == "MEDIUM"
        assert f.to_dict()["severity"] == "MEDIUM"


class TestDuplicateFinding:
    """Test DuplicateFinding data class (fast - no I/O)."""

    def test_default_severity(self) -> None:
        f = DuplicateFinding(
            category="DUPLICATE_FUNC", file_a="a.py", line_a=1, file_b="b.py", line_b=2,
            name="func", similarity=0.8, description="duplicate",
        )
        assert f.severity == "MEDIUM"
        assert f.similarity == 0.8

    def test_to_dict(self) -> None:
        f = DuplicateFinding(
            category="DUPLICATE_CLASS", file_a="x.py", line_a=5, file_b="y.py", line_b=10,
            name="MyClass", similarity=1.0, description="exact copy", severity="HIGH",
        )
        d = f.to_dict()
        assert d["similarity"] == 1.0
        assert d["severity"] == "HIGH"

    def test_round_trip(self) -> None:
        f = DuplicateFinding(
            category="DUPLICATE_SYMBOL", file_a="mod1.py", line_a=3, file_b="mod2.py", line_b=7,
            name="shared_func", similarity=0.95, description="potential duplicate",
        )
        d = f.to_dict()
        assert d["file_a"] == "mod1.py"
        assert d["file_b"] == "mod2.py"
        assert d["name"] == "shared_func"


class TestCollectModuleExports:
    """Test AST-based export collection (fast - single file with tempfile)."""

    def test_finds_functions(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
            f.write("def foo(): pass\ndef bar(): pass\n")
            path = Path(f.name)

        try:
            exports = collect_module_exports(path)
            assert "foo" in exports
            assert "bar" in exports
            assert len(exports) == 2
        finally:
            path.unlink(missing_ok=True)

    def test_finds_classes(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
            f.write("class MyClass: pass\nclass OtherClass: pass\n")
            path = Path(f.name)

        try:
            exports = collect_module_exports(path)
            assert "MyClass" in exports
            assert "OtherClass" in exports
        finally:
            path.unlink(missing_ok=True)

    def test_skips_dunders(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
            f.write("def __init__(): pass\ndef public_func(): pass\n")
            path = Path(f.name)

        try:
            exports = collect_module_exports(path)
            assert "__init__" not in exports
            assert "public_func" in exports
        finally:
            path.unlink(missing_ok=True)

    def test_handles_syntax_error(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
            f.write("def broken(:\n")
            path = Path(f.name)

        try:
            exports = collect_module_exports(path)
            assert exports == set()  # Should return empty set on syntax error
        finally:
            path.unlink(missing_ok=True)

    def test_finds_assignments(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
            f.write("PI = 3.14\nCONFIG = {'key': 'value'}\n_privat = 'hidden'\n")
            path = Path(f.name)

        try:
            exports = collect_module_exports(path)
            assert "PI" in exports
            assert "CONFIG" in exports
            assert "_privat" not in exports  # Private names excluded
        finally:
            path.unlink(missing_ok=True)


class TestUpdateSectionInFile:
    """Test the append-only register update helper (fast - tempfile)."""

    def test_preserves_existing_content(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, encoding="utf-8") as f:
            f.write("# Test Header\n\nManual entry preserved.\n\n## Scan Results\n\nOld results\n")
            path = Path(f.name)

        try:
            ok = _update_section_in_file(path, "Scan Results", ["## Scan Results\n", "\n", "New results\n"])
            assert ok
            content = path.read_text(encoding="utf-8")
            assert "Manual entry preserved." in content
            assert "New results" in content
            assert "Old results" not in content
        finally:
            path.unlink(missing_ok=True)

    def test_creates_section_if_missing(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, encoding="utf-8") as f:
            f.write("# Test Header\n\nExisting content.\n")
            path = Path(f.name)

        try:
            ok = _update_section_in_file(path, "Scan Results", ["## Scan Results\n", "\n", "Fresh scan results\n"])
            assert ok
            content = path.read_text(encoding="utf-8")
            assert "Fresh scan results" in content
            assert "Existing content." in content
        finally:
            path.unlink(missing_ok=True)

    def test_handles_empty_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, encoding="utf-8") as f:
            path = Path(f.name)

        try:
            ok = _update_section_in_file(path, "Scan Results", ["## Scan Results\n", "New content\n"])
            assert ok
            content = path.read_text(encoding="utf-8")
            assert "New content" in content
        finally:
            path.unlink(missing_ok=True)


class TestMainCLI:
    """Test the CLI entry point (uses targeted flags to avoid full scan timeout)."""

    def test_main_ci_check_imports(self) -> None:
        """--ci --check-imports is faster than full scan."""
        exit_code = main(["--ci", "--check-imports"])
        assert exit_code in (0, 1)

    def test_main_ci_check_duplicates(self) -> None:
        """--ci --check-duplicates is faster than full scan."""
        exit_code = main(["--ci", "--check-duplicates"])
        assert exit_code in (0, 1)

    def test_main_json_check_imports(self) -> None:
        exit_code = main(["--json", "--check-imports"])
        assert exit_code in (0, 1)

    def test_main_json_check_duplicates(self) -> None:
        exit_code = main(["--json", "--check-duplicates"])
        assert exit_code in (0, 1)

    def test_main_update_registers(self) -> None:
        """--update-registers should not crash."""
        exit_code = main(["--update-registers"])
        assert exit_code in (0, 1)

    def test_main_help(self) -> None:
        with pytest.raises(SystemExit):
            main(["--help"])

    def test_main_remove_dry_run(self) -> None:
        """--remove works with --check-imports (dry-run test)."""
        exit_code = main(["--remove", "--check-imports", "--ci"])
        assert exit_code in (0, 1)

    def test_main_remove_json(self) -> None:
        """--remove works with --json output (ci flag prevents actual file modification)."""
        exit_code = main(["--remove", "--check-imports", "--json", "--ci"])
        assert exit_code in (0, 1)

    def test_main_ci_orphans(self) -> None:
        """--ci --check-orphans is faster than full scan."""
        exit_code = main(["--ci", "--check-orphans"])
        assert exit_code in (0, 1)
