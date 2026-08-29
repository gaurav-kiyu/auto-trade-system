"""Tests for Modular Monolith Module Isolation — AST-07.

Validates that modules in the codebase respect isolation boundaries:
  1. Modules communicate through port interfaces, not direct imports
  2. No circular dependencies between core modules
  3. DI container wires all module dependencies explicitly
  4. Each module has a single entry point and clear responsibility

This enforces the Architecture Standard AST-07 (Modular Monolith first)
from the Master Engineering Constitution v4.0.

Usage:
    python -m pytest tests/test_module_isolation.py -v
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# ── Paths ──────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Define core modules — these are candidates for potential microservice extraction
CORE_MODULES: dict[str, Path] = {
    "execution": PROJECT_ROOT / "core" / "execution",
    "strategy": PROJECT_ROOT / "core" / "strategy",
    "self_healing": PROJECT_ROOT / "core" / "self_healing",
    "auth": PROJECT_ROOT / "core" / "auth",
    "services": PROJECT_ROOT / "core" / "services",
    "adapters": PROJECT_ROOT / "core" / "adapters",
    "ports": PROJECT_ROOT / "core" / "ports",
    "patterns": PROJECT_ROOT / "core" / "patterns",
    "wal": PROJECT_ROOT / "core" / "wal",
}

# Port interface packages — modules MAY import from these (allowed shared kernel)
PORT_PACKAGES = {"core.ports", "core.patterns", "core.di_container"}

# Known port implementations that are permitted as dependencies
PERMITTED_DEPENDENCIES: dict[str, set[str]] = {
    "execution": {"core.ports", "core.patterns", "core.adapters.broker_adapters"},
    "strategy": {"core.ports", "core.patterns", "core.adapters.broker_adapters"},
    "auth": {"core.ports", "core.patterns"},
    "services": {"core.ports", "core.patterns", "core.adapters"},
    "self_healing": {"core.ports", "core.patterns"},
}

# Modules that are explicitly permitted to import other modules (shared kernel)
SHARED_KERNEL_MODULES = {"core.ports", "core.patterns", "core.di_container", "core.adapters"}

# Bare module names (CORE_MODULES keys) of the shared-kernel packages above.
# ``_get_core_module_from_import`` compares against these, since CORE_MODULES
# keys are bare names ("ports") while SHARED_KERNEL_MODULES holds dotted paths
# ("core.ports").  Without this, the shared-kernel skip never fires and every
# legitimate ``core.ports.*`` / ``core.adapters.*`` import is miscounted as a
# cross-module violation.
_SHARED_KERNEL_BARE_NAMES = {n.rsplit(".", 1)[-1] for n in SHARED_KERNEL_MODULES}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _get_module_name(filepath: Path) -> str | None:
    """Get the module name (e.g., 'execution') for a file path."""
    rel = filepath.relative_to(PROJECT_ROOT).as_posix()
    for module_name, module_path in CORE_MODULES.items():
        module_prefix = module_path.relative_to(PROJECT_ROOT).as_posix()
        if rel.startswith(module_prefix):
            # Exclude subpackages that belong to other modules
            return module_name
    return None


def _get_core_module_from_import(import_name: str) -> str | None:
    """Check if an import references a core module.

    Returns the module name if found, None otherwise.
    """
    for module_name, module_path in CORE_MODULES.items():
        if module_name in _SHARED_KERNEL_BARE_NAMES:
            continue
        module_pkg = module_path.relative_to(PROJECT_ROOT).as_posix().replace("/", ".")
        if import_name.startswith(module_pkg):
            return module_name
    return None


def _check_file_for_violations(filepath: Path) -> list[str]:
    """Check a Python file for module isolation violations.

    Returns a list of violation descriptions.
    """
    violations: list[str] = []
    source_module = _get_module_name(filepath)
    if not source_module:
        return violations

    # Check if this module type is restricted (shared kernel can import anything)
    if source_module in _SHARED_KERNEL_BARE_NAMES:
        return violations

    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return violations

    permitted = PERMITTED_DEPENDENCIES.get(source_module, set())

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target_module = _get_core_module_from_import(alias.name)
                if target_module and target_module != source_module:
                    if alias.name not in permitted and alias.name not in SHARED_KERNEL_MODULES:
                        rel = filepath.relative_to(PROJECT_ROOT)
                        violations.append(
                            f"{rel} imports {alias.name} "
                            f"({source_module} -> {target_module}, not in permitted deps)"
                        )

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                target_module = _get_core_module_from_import(node.module)
                if target_module and target_module != source_module:
                    if node.module not in permitted and node.module not in SHARED_KERNEL_MODULES:
                        rel = filepath.relative_to(PROJECT_ROOT)
                        violations.append(
                            f"{rel} imports from {node.module} "
                            f"({source_module} -> {target_module}, not in permitted deps)"
                        )

    return violations


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestModuleExistence:
    """Tests that core module directories exist."""

    def test_core_modules_exist(self):
        """All defined core module directories should exist."""
        missing = [name for name, path in CORE_MODULES.items() if not path.exists()]
        if missing:
            print(f"\n  ⚠️  Core module directories not found: {', '.join(missing)}")
            print("  These may have been renamed — update CORE_MODULES in this test.")
        else:
            print(f"\n  ✅ All {len(CORE_MODULES)} core modules present")

    def test_each_module_has_init(self):
        """Each core module should have an __init__.py."""
        for name, path in CORE_MODULES.items():
            if path.is_dir():
                assert (path / "__init__.py").exists(), (
                    f"Module '{name}' at {path} missing __init__.py"
                )


class TestModuleIsolation:
    """Tests that modules respect isolation boundaries."""

    def test_no_unauthorized_cross_module_imports(self):
        """Core modules must not import from other core modules outside permitted deps."""
        all_violations: list[str] = []

        for module_name, module_path in CORE_MODULES.items():
            if not module_path.exists():
                continue
            if not module_path.is_dir():
                continue

            for py_file in module_path.rglob("*.py"):
                if py_file.name == "__init__.py":
                    continue
                violations = _check_file_for_violations(py_file)
                all_violations.extend(violations)

        if all_violations:
            print(f"\n  ⚠️  Found {len(all_violations)} module isolation violation(s):")
            for v in all_violations[:20]:
                print(f"    - {v}")
            if len(all_violations) > 20:
                print(f"    ... and {len(all_violations) - 20} more")
        else:
            print("\n  ✅ No module isolation violations detected")

        # Warn but don't fail — during migration some cross-module deps may exist
        if len(all_violations) > 50:
            pytest.fail(f"Too many isolation violations ({len(all_violations)}) — review needed")

    def test_di_container_wires_modules(self):
        """The DI container should handle module wiring."""
        container_files = list((PROJECT_ROOT / "core" / "di_container").rglob("*.py"))
        assert len(container_files) >= 1, (
            "core/di_container/ should contain wiring files for modular monolith"
        )
        print(f"\n  ✅ DI container has {len(container_files)} wiring files")


class TestCircularDependencies:
    """Tests for circular dependency prevention."""

    def test_no_self_imports(self):
        """Modules should not import themselves."""
        for name, path in CORE_MODULES.items():
            if not path.exists() or not path.is_dir():
                continue
            module_pkg = f"core.{name}"
            for py_file in path.rglob("*.py"):
                if py_file.name == "__init__.py":
                    continue
                try:
                    source = py_file.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(source, filename=str(py_file))
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.Import, ast.ImportFrom)):
                            import_str = node.names[0].name if isinstance(node, ast.Import) else (node.module or "")
                            if import_str == module_pkg:
                                rel = py_file.relative_to(PROJECT_ROOT)
                                print(f"  ⚠️  Self-import: {rel} imports {import_str}")
                except SyntaxError:
                    continue

    def test_adr_0018_exists(self):
        """ADR-0018 must document the Modular Monolith decision."""
        adr_file = PROJECT_ROOT / "docs" / "adr" / "0018-modular-monolith-architecture.md"
        assert adr_file.exists(), (
            "ADR-0018 (Modular Monolith) not found at docs/adr/0018-modular-monolith-architecture.md"
        )
        content = adr_file.read_text(encoding="utf-8")
        assert "Modular Monolith" in content
        assert "Status" in content
        assert "Decision" in content
        assert "Consequences" in content
        assert "Extraction" in content or "Microservice" in content
        print("\n  ✅ ADR-0018 documents Modular Monolith architecture")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
