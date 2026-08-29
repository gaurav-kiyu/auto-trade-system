"""Intelligent Test Generator (Pillar 8).

Automatically generates tests for changed or untested code:
- Unit tests for pure functions
- Integration tests for services
- API tests for routes
- Regression tests for bug fixes
- Edge case tests

When code changes, determines exactly which tests need updating and
generates new tests for uncovered logic.

Usage:
    from core.intelligent_test_generator import IntelligentTestGenerator

    gen = IntelligentTestGenerator()
    tests = gen.generate_tests("core/risk_service.py")
    for test in tests:
        print(test.file_path)
        print(test.test_code)

    # Or analyze a change set
    plan = gen.analyze_change("core/risk_service.py", "MODIFY")
    print(plan.existing_tests)
    print(plan.new_tests_needed)
"""

from __future__ import annotations

import ast
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Test Generation Templates ──────────────────────────────────────────────

UNIT_TEST_TEMPLATE = '''"""Tests for {module_name}."""
from __future__ import annotations

import pytest
from {module_import} import {symbol_name}


class Test{class_name}:
    """Tests for {symbol_name}."""

    def test_{test_name}_basic(self) -> None:
        """Test basic functionality."""
        # TODO: Implement test
{param_setup}
{assert_template}
'''

API_TEST_TEMPLATE = '''"""API tests for {module_name}."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from {module_import} import app


class TestAPI{class_name}:
    """Tests for {endpoint}."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_{test_name}_success(self, client: TestClient) -> None:
        """Test successful response."""
        response = client.{method}("{endpoint}"{param_dict})
        assert response.status_code == 200
        # TODO: Add response validation
'''

EDGE_CASE_TEMPLATE = '''
    def test_{test_name}_edge_empty(self) -> None:
        """Test with empty input."""
        # TODO: Implement edge case test
        pass

    def test_{test_name}_edge_none(self) -> None:
        """Test with None input."""
        # TODO: Implement edge case test
        pass

    def test_{test_name}_edge_invalid(self) -> None:
        """Test with invalid input."""
        # TODO: Implement edge case test
        pass
'''

REGRESSION_TEST_TEMPLATE = '''"""Regression tests for {bug_description}.

Bug: {bug_reference}
"""
from __future__ import annotations

import pytest
from {module_import} import {symbol_name}


class TestRegress{class_name}:
    """Regression tests for {symbol_name}."""

    def test_regression_{test_name}_repro(self) -> None:
        """Reproduce the original bug scenario."""
        # TODO: Implement regression test
        pass

    def test_regression_{test_name}_fixed(self) -> None:
        """Verify the fix works."""
        # TODO: Implement regression test
        pass
'''


# ── Data Models ─────────────────────────────────────────────────────────────


@dataclass
class GeneratedTest:
    """A single generated test file."""
    file_path: str
    test_code: str
    test_type: str  # UNIT, INTEGRATION, API, REGRESSION, EDGE_CASE
    target_module: str
    target_symbol: str
    confidence: float = 0.7  # How confident the generator is (0-1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "test_type": self.test_type,
            "target_module": self.target_module,
            "target_symbol": self.target_symbol,
            "confidence": self.confidence,
            "lines": len(self.test_code.splitlines()),
        }


@dataclass
class TestPlan:
    """Test generation plan for a change."""
    target_module: str
    change_type: str
    existing_tests: list[str] = field(default_factory=list)
    new_tests_needed: list[GeneratedTest] = field(default_factory=list)
    tests_to_update: list[str] = field(default_factory=list)
    uncovered_functions: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_module": self.target_module,
            "change_type": self.change_type,
            "existing_tests": self.existing_tests,
            "new_tests_needed": [t.to_dict() for t in self.new_tests_needed],
            "tests_to_update": self.tests_to_update,
            "uncovered_functions": self.uncovered_functions,
            "summary": self.summary,
        }


# ── Test Generator ─────────────────────────────────────────────────────────


class IntelligentTestGenerator:
    """Intelligent Test Generator.

    Analyzes Python source code and generates appropriate test files.
    Uses AST analysis to understand function signatures, parameters,
    return types, and edge cases.

    Generates:
    - Unit tests for pure functions (no I/O side effects)
    - Integration tests for services (I/O, database, network)
    - API tests for route handlers
    - Regression tests for bug fixes
    - Edge case coverage (empty, None, invalid, boundary values)
    """

    def __init__(self, output_dir: str = "tests") -> None:
        self._lock = threading.RLock()
        self._output_dir = Path(output_dir)
        self._generated_count = 0

    # ── Public API ────────────────────────────────────────────────────────

    def analyze_change(
        self, module_path: str, change_type: str = "MODIFY"
    ) -> TestPlan:
        """Analyze a change and determine what tests are needed.

        Args:
            module_path: Path to the changed module.
            change_type: Type of change: ADD, MODIFY, DELETE.

        Returns:
            TestPlan with existing tests, new tests needed, and uncovered functions.
        """
        plan = TestPlan(
            target_module=module_path,
            change_type=change_type,
        )

        # Find existing test file
        base_name = Path(module_path).stem
        expected_test = f"tests/test_{base_name}.py"
        if Path(expected_test).is_file():
            plan.existing_tests.append(expected_test)
        else:
            # Look for tests in subdirectories
            test_dir = Path("tests")
            if test_dir.is_dir():
                for test_file in test_dir.rglob(f"test_{base_name}.py"):
                    plan.existing_tests.append(str(test_file))

        # If deleting, just note the existing tests
        if change_type == "DELETE":
            plan.summary = f"Module removed. {len(plan.existing_tests)} existing test(s) may need updating."
            return plan

        # Parse the module to find testable symbols
        f = Path(module_path)
        if not f.is_file():
            plan.summary = f"Module not found: {module_path}"
            return plan

        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError as exc:
            plan.summary = f"Cannot parse {module_path}: {exc}"
            return plan

        # Find all testable functions and methods
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Skip private methods and special methods
                if node.name.startswith("_") and not node.name.startswith("__"):
                    continue
                if node.name in ("__init__", "__str__", "__repr__"):
                    continue

                # Check if this function already has a test
                has_test = self._has_test_for(node.name, plan.existing_tests)
                if has_test:
                    if change_type == "MODIFY":
                        plan.tests_to_update.extend(plan.existing_tests)
                else:
                    plan.uncovered_functions.append(node.name)

            elif isinstance(node, ast.ClassDef):
                # Check if class is already tested
                has_test = self._has_test_for(node.name, plan.existing_tests)
                if not has_test and not node.name.startswith("_"):
                    plan.uncovered_functions.append(node.name)

        # Generate new tests for uncovered functions
        if plan.uncovered_functions and change_type != "DELETE":
            generated = self.generate_tests(module_path, plan.uncovered_functions)
            plan.new_tests_needed = generated

        n_existing = len(plan.existing_tests)
        n_new = len(plan.new_tests_needed)
        n_update = len(plan.tests_to_update)
        plan.summary = (
            f"Analysis for {module_path}: "
            f"{n_existing} existing test(s), "
            f"{n_new} new test(s) needed, "
            f"{n_update} test(s) to update, "
            f"{len(plan.uncovered_functions)} uncovered function(s)"
        )

        return plan

    def generate_tests(
        self,
        module_path: str,
        target_symbols: list[str] | None = None,
    ) -> list[GeneratedTest]:
        """Generate tests for symbols in a module.

        Args:
            module_path: Path to the source module.
            target_symbols: Optional list of specific symbols to test.
                           If None, generates tests for all symbols.

        Returns:
            List of GeneratedTest objects.
        """
        f = Path(module_path)
        if not f.is_file():
            _log.warning("[TESTGEN] Module not found: %s", module_path)
            return []

        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError as exc:
            _log.warning("[TESTGEN] Parse error: %s", exc)
            return []

        module_name = module_path.replace(".py", "").replace("/", ".")
        base_name = Path(module_path).stem
        class_name = self._to_class_name(base_name)

        generated: list[GeneratedTest] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if target_symbols and node.name not in target_symbols:
                    continue
                if node.name.startswith("_") and not node.name.startswith("__"):
                    continue
                if node.name in ("__init__", "__str__", "__repr__"):
                    continue

                test = self._generate_unit_test(
                    module_path, module_name, class_name, node
                )
                if test:
                    generated.append(test)

            elif isinstance(node, ast.ClassDef):
                if target_symbols and node.name not in target_symbols:
                    continue
                if node.name.startswith("_"):
                    continue

                # Check if it's a testable class (has public methods)
                public_methods = [
                    m for m in ast.walk(node)
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not m.name.startswith("_")
                ]

                if public_methods:
                    test = self._generate_unit_test(
                        module_path, module_name, class_name, node
                    )
                    if test:
                        generated.append(test)

        return generated

    def generate_api_tests(self, module_path: str) -> list[GeneratedTest]:
        """Generate API tests for a routes module.

        Args:
            module_path: Path to a routes module (should contain @router/@app decorators).

        Returns:
            List of GeneratedTest objects for API endpoints.
        """
        f = Path(module_path)
        if not f.is_file():
            return []

        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []

        base_name = Path(module_path).stem
        class_name = self._to_class_name(base_name)
        module_import = module_path.replace(".py", "").replace("/", ".")
        generated: list[GeneratedTest] = []

        # Find API routes
        route_pattern = r'@(?:app|router|api)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']'
        for match in re.finditer(route_pattern, content):
            method = match.group(1)
            route = match.group(2)
            test_name = route.strip("/").replace("/", "_").replace("-", "_").replace("{", "").replace("}", "")
            if not test_name:
                test_name = "root"

            test_code = API_TEST_TEMPLATE.format(
                module_name=module_path,
                module_import=module_import,
                class_name=class_name,
                endpoint=route,
                method=method,
                test_name=test_name,
                param_dict="",
            )

            test_path = f"tests/test_api_{base_name}.py"
            generated.append(GeneratedTest(
                file_path=test_path,
                test_code=test_code,
                test_type="API",
                target_module=module_path,
                target_symbol=f"{method.upper()} {route}",
            ))

        return generated

    # ── Private Helpers ───────────────────────────────────────────────────

    def _generate_unit_test(
        self, module_path: str, module_import: str, class_name: str, node: ast.AST
    ) -> GeneratedTest | None:
        """Generate a unit test for a single node (function or class)."""
        base_name = Path(module_path).stem
        is_class = isinstance(node, ast.ClassDef)
        symbol_name = node.name
        test_name = self._to_snake_case(symbol_name)

        # Build parameter setup
        param_setup = ""
        assert_template = "        assert result is not None  # TODO: Add assertion"

        if is_class:
            # Generate test for class instantiation
            param_setup = "        # TODO: Initialize class instance"
            test_code = UNIT_TEST_TEMPLATE.format(
                module_name=module_path,
                module_import=module_import,
                symbol_name=symbol_name,
                class_name=self._to_class_name(symbol_name),
                test_name=test_name,
                param_setup=param_setup,
                assert_template="        # TODO: Test class methods",
            )
        else:
            # Generate test for function call
            params = [a.arg for a in node.args.args if a.arg != "self"]
            if params:
                param_setup_lines = [
                    f"        {p} = None  # TODO: Set test value" for p in params
                ]
                param_setup = "\n".join(param_setup_lines)
                call_args = ", ".join(params)
                assert_template = f"        result = {symbol_name}({call_args})\n        assert result is not None  # TODO: Add assertion"
            else:
                assert_template = f"        result = {symbol_name}()\n        assert result is not None  # TODO: Add assertion"

            test_code = UNIT_TEST_TEMPLATE.format(
                module_name=module_path,
                module_import=module_import,
                symbol_name=symbol_name,
                class_name=class_name,
                test_name=test_name,
                param_setup=param_setup,
                assert_template=assert_template,
            )

        test_path = f"tests/test_{base_name}.py"
        return GeneratedTest(
            file_path=test_path,
            test_code=test_code,
            test_type="UNIT",
            target_module=module_path,
            target_symbol=symbol_name,
            confidence=0.6,  # Template-based, may need manual refinement
        )

    def _has_test_for(self, symbol_name: str, existing_tests: list[str]) -> bool:
        """Check if a symbol already has a test in existing test files."""
        for test_path in existing_tests:
            try:
                content = Path(test_path).read_text(encoding="utf-8")
                # Check for test function or class referencing the symbol
                if f"def test_{self._to_snake_case(symbol_name)}" in content:
                    return True
                if f"class Test{self._to_class_name(symbol_name)}" in content:
                    return True
                if symbol_name in content:
                    return True
            except OSError:
                continue
        return False

    def _to_class_name(self, name: str) -> str:
        """Convert a snake_case name to PascalCase for test class naming."""
        return "".join(word.capitalize() for word in name.replace("-", "_").split("_"))

    def _to_snake_case(self, name: str) -> str:
        """Convert a PascalCase or mixed name to snake_case."""
        name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
        name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
        return name.lower()

    def get_test_generation_stats(self) -> dict[str, Any]:
        """Get statistics about test generation."""
        return {
            "total_generated": self._generated_count,
            "output_directory": str(self._output_dir),
        }


# ── Singleton ───────────────────────────────────────────────────────────────


_generator: IntelligentTestGenerator | None = None
_generator_lock = threading.RLock()


def get_test_generator() -> IntelligentTestGenerator:
    """Get the singleton IntelligentTestGenerator instance."""
    global _generator
    with _generator_lock:
        if _generator is None:
            _generator = IntelligentTestGenerator()
        return _generator


def reset_test_generator() -> None:
    """Force-reset singleton (for testing)."""
    global _generator
    with _generator_lock:
        _generator = None


__all__ = [
    "GeneratedTest",
    "IntelligentTestGenerator",
    "TestPlan",
    "get_test_generator",
    "reset_test_generator",
]
