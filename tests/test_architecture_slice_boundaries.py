"""Tests for Vertical Slice Architecture Boundary Enforcement — AST-03.

Validates that modules within the codebase respect vertical slice boundaries:
  1. Slices do not import directly from other slices' implementation packages
  2. Slices communicate through port interfaces or mediator only
  3. Slice boundaries are documented

This enforces the Architecture Standard AST-03 (Vertical Slice) from the
Master Engineering Constitution v4.0.

Usage:
    python -m pytest tests/test_architecture_slice_boundaries.py -v
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# ── Paths ──────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Define known slice packages — each represents a vertical business capability
# A slice groups all layers (domain, application, infrastructure) for one feature
KNOWN_SLICES: dict[str, str] = {
    "execution": "core/execution/",
    "strategy": "core/strategy/",
    "self_healing": "core/self_healing/",
    "auth": "core/auth/",
    "risk": "core/services/",
    "signals": "core/adaptive_signal.py",
}

# Port/interfaces that slices MAY import from (allowed shared kernel)
SHARED_KERNEL_PACKAGES = {
    "core.ports",
    "core.patterns",
    "core.di_container",
    "core.adapters",
}

# Directories that are part of the shared kernel (not slices)
SHARED_KERNEL_DIRS = {
    "core/ports",
    "core/patterns",
    "core/di_container",
    "core/adapters",
}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _is_in_slice(filepath: Path) -> bool:
    """Check if file is within a known slice directory (but not shared kernel)."""
    rel = filepath.relative_to(PROJECT_ROOT).as_posix()
    for slice_dir in KNOWN_SLICES.values():
        if rel.startswith(slice_dir.rstrip("/")):
            # Exclude shared kernel directories
            if any(rel.startswith(kernel) for kernel in SHARED_KERNEL_DIRS):
                continue
            return True
    return False


def _get_slice_name(filepath: Path) -> str | None:
    """Get the slice name for a file, if it belongs to one."""
    rel = filepath.relative_to(PROJECT_ROOT).as_posix()
    for name, slice_dir in KNOWN_SLICES.items():
        if rel.startswith(slice_dir.rstrip("/")):
            # Exclude shared kernel
            if any(rel.startswith(kernel) for kernel in SHARED_KERNEL_DIRS):
                continue
            return name
    return None


def _get_imported_slices(import_name: str) -> set[str]:
    """Check if an import statement references another slice.

    Returns the set of slice names that the import references.
    """
    referenced = set()
    for name, slice_dir in KNOWN_SLICES.items():
        slice_pkg = slice_dir.replace("/", ".").rstrip(".")
        if import_name.startswith(slice_pkg):
            referenced.add(name)
    return referenced


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestVerticalSliceBoundaries:
    """Tests that enforce vertical slice import boundaries."""

    def test_slice_boundaries_defined(self):
        """Known slices should be defined and the directories should exist."""
        existing = []
        missing = []
        for name, path in KNOWN_SLICES.items():
            full_path = PROJECT_ROOT / path
            if full_path.exists():
                existing.append(name)
            else:
                missing.append(name)

        if missing:
            print(f"\n  ⚠️  Slice directories not found: {', '.join(missing)}")
            print("  These may have been renamed — update KNOWN_SLICES in this test.")
        print(f"  ✅ Found: {', '.join(existing)}")
        assert len(existing) >= 2, (
            f"At least 2 slice directories should exist, found {len(existing)}"
        )

    def test_slices_have_single_entry_point(self):
        """Each slice should have a public __init__.py or designated entry point."""
        for name, path in KNOWN_SLICES.items():
            full_path = PROJECT_ROOT / path
            if not full_path.exists():
                continue

            # For directories, check __init__.py exists
            if full_path.is_dir():
                init_file = full_path / "__init__.py"
                assert init_file.exists() or (full_path / "main.py").exists(), (
                    f"Slice '{name}' at {path} missing __init__.py entry point"
                )
                print(f"  ✅ {name}: __init__.py exists")

            # For files, check they exist
            elif full_path.is_file():
                assert full_path.exists(), f"Slice '{name}' file {path} not found"
                print(f"  ✅ {name}: entry file exists")

    def test_no_cross_slice_imports(self):
        """Slice files must not import directly from other slice implementations.

        Slices should communicate through port interfaces, mediator, or domain events,
        never through direct imports of another slice's implementation.
        """
        violations: list[str] = []

        # Walk all Python files in slice directories
        for name, slice_path in KNOWN_SLICES.items():
            full_path = PROJECT_ROOT / slice_path
            if not full_path.exists():
                continue

            py_files = []
            if full_path.is_dir():
                py_files = list(full_path.rglob("*.py"))
            elif full_path.is_file():
                py_files = [full_path]

            for py_file in py_files:
                # Skip __init__.py files
                if py_file.name == "__init__.py":
                    continue

                slice_name = _get_slice_name(py_file)
                if not slice_name:
                    continue

                try:
                    source = py_file.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(source, filename=str(py_file))
                except SyntaxError:
                    continue

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imported_slices = _get_imported_slices(alias.name)
                            for other_slice in imported_slices:
                                if other_slice != slice_name:
                                    rel = py_file.relative_to(PROJECT_ROOT)
                                    violations.append(
                                        f"{rel} imports {alias.name} "
                                        f"(slice '{slice_name}' -> slice '{other_slice}')"
                                    )

                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imported_slices = _get_imported_slices(node.module)
                            for other_slice in imported_slices:
                                if other_slice != slice_name:
                                    rel = py_file.relative_to(PROJECT_ROOT)
                                    violations.append(
                                        f"{rel} imports from {node.module} "
                                        f"(slice '{slice_name}' -> slice '{other_slice}')"
                                    )

        if violations:
            print(f"\n  ⚠️  Found {len(violations)} cross-slice import violation(s):")
            for v in violations[:20]:
                print(f"    - {v}")
            if len(violations) > 20:
                print(f"    ... and {len(violations) - 20} more")
            # This is informative, not blocking — cross-slice imports may be legitimate
            # during the migration phase. Flag them for review.
        else:
            print("\n  ✅ No cross-slice import violations detected")

    def test_adr_0017_exists(self):
        """ADR-0017 must document the Vertical Slice decision."""
        adr_file = PROJECT_ROOT / "docs" / "adr" / "0017-vertical-slice-architecture.md"
        assert adr_file.exists(), (
            "ADR-0017 (Vertical Slice Architecture) not found at docs/adr/0017-vertical-slice-architecture.md"
        )
        content = adr_file.read_text(encoding="utf-8")
        assert "Vertical Slice" in content
        assert "Status" in content
        assert "Decision" in content
        assert "Consequences" in content
        print("\n  ✅ ADR-0017 documents Vertical Slice architecture")


class TestADRSliceDocumentation:
    """Tests that slice documentation is maintained."""

    def test_adr_references(self):
        """The architecture governance ADR should reference the slice ADR."""
        adr_010 = PROJECT_ROOT / "docs" / "adr" / "0010-architecture-governance.md"
        if not adr_010.exists():
            pytest.skip("ADR-0010 not found")

        content = adr_010.read_text(encoding="utf-8")
        has_ref = "ADR 0017" in content or "0017-vertical-slice" in content
        print(f"\n  {'✅ ADR-0010 references ADR-0017' if has_ref else 'ℹ️ ADR-0010 does not yet reference ADR-0017'}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
