"""Tests for IntelligentTestGenerator (Pillar 8)."""
from __future__ import annotations

import pytest
from core.intelligent_test_generator import (
    GeneratedTest,
    IntelligentTestGenerator,
    TestPlan,
    get_test_generator,
    reset_test_generator,
)


@pytest.fixture(autouse=True)
def reset_gen() -> None:
    """Reset the singleton before each test."""
    reset_test_generator()


class TestIntelligentTestGenerator:
    """Tests for the IntelligentTestGenerator class."""

    def test_singleton(self) -> None:
        """Test singleton pattern."""
        g1 = get_test_generator()
        g2 = get_test_generator()
        assert g1 is g2

    def test_reset(self) -> None:
        """Test reset clears the singleton."""
        g1 = get_test_generator()
        reset_test_generator()
        g2 = get_test_generator()
        assert g1 is not g2

    def test_analyze_change_nonexistent(self) -> None:
        """Test analyzing a nonexistent module."""
        gen = IntelligentTestGenerator()
        plan = gen.analyze_change("nonexistent_module.py")
        assert isinstance(plan, TestPlan)
        assert plan.target_module == "nonexistent_module.py"
        assert "not found" in plan.summary.lower()

    def test_analyze_change_existing(self) -> None:
        """Test analyzing an existing module."""
        gen = IntelligentTestGenerator()
        plan = gen.analyze_change("core/__init__.py")
        assert isinstance(plan, TestPlan)
        assert plan.target_module == "core/__init__.py"
        assert plan.summary != ""

    def test_analyze_change_add(self) -> None:
        """Test analyzing with ADD change type."""
        gen = IntelligentTestGenerator()
        plan = gen.analyze_change("core/__init__.py", "ADD")
        assert plan.change_type == "ADD"

    def test_analyze_change_delete(self) -> None:
        """Test analyzing with DELETE change type."""
        gen = IntelligentTestGenerator()
        plan = gen.analyze_change("core/__init__.py", "DELETE")
        assert plan.change_type == "DELETE"

    def test_generate_tests_for_module(self) -> None:
        """Test generating tests for a module."""
        gen = IntelligentTestGenerator()
        tests = gen.generate_tests("core/__init__.py")
        assert isinstance(tests, list)
        # May or may not find testable symbols depending on the module

    def test_generate_tests_for_nonexistent(self) -> None:
        """Test generating tests for nonexistent module."""
        gen = IntelligentTestGenerator()
        tests = gen.generate_tests("nonexistent.py")
        assert tests == []

    def test_generate_tests_with_target(self) -> None:
        """Test generating tests for specific symbols."""
        gen = IntelligentTestGenerator()
        tests = gen.generate_tests("core/__init__.py", target_symbols=["DataLineageEngine"])
        assert isinstance(tests, list)

    def test_generate_api_tests(self) -> None:
        """Test generating API tests."""
        gen = IntelligentTestGenerator()
        api_tests = gen.generate_api_tests("core/enterprise_dashboard/routes/intelligence.py")
        assert isinstance(api_tests, list)

    def test_generated_test_fields(self) -> None:
        """Test that generated tests have proper fields."""
        gen = IntelligentTestGenerator()
        tests = gen.generate_tests("core/__init__.py")
        for test in tests:
            assert isinstance(test, GeneratedTest)
            assert test.file_path.startswith("tests/")
            assert test.test_code != ""
            assert test.test_type in ("UNIT", "INTEGRATION", "API", "REGRESSION", "EDGE_CASE")
            assert isinstance(test.to_dict(), dict)

    def test_plan_to_dict(self) -> None:
        """Test plan serialization."""
        plan = TestPlan(target_module="test.py", change_type="MODIFY")
        d = plan.to_dict()
        assert d["target_module"] == "test.py"
        assert d["change_type"] == "MODIFY"
        assert isinstance(d["existing_tests"], list)
        assert isinstance(d["new_tests_needed"], list)

    def test_class_name_conversion(self) -> None:
        """Test class name conversion."""
        gen = IntelligentTestGenerator()
        assert gen._to_class_name("my_module") == "MyModule"
        assert gen._to_class_name("risk_service") == "RiskService"
        assert gen._to_class_name("test_api_routes") == "TestApiRoutes"

    def test_snake_case_conversion(self) -> None:
        """Test snake_case conversion."""
        gen = IntelligentTestGenerator()
        assert gen._to_snake_case("MyModule") == "my_module"
        assert gen._to_snake_case("RiskService") == "risk_service"

    def test_stats(self) -> None:
        """Test stats retrieval."""
        gen = IntelligentTestGenerator()
        stats = gen.get_test_generation_stats()
        assert isinstance(stats, dict)
        assert "total_generated" in stats


class TestGeneratedTest:
    """Tests for GeneratedTest dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        test = GeneratedTest(
            file_path="tests/test_foo.py",
            test_code="def test_foo(): pass",
            test_type="UNIT",
            target_module="core/foo.py",
            target_symbol="foo",
        )
        assert test.confidence == 0.7
        d = test.to_dict()
        assert d["file_path"] == "tests/test_foo.py"
        assert d["test_type"] == "UNIT"


class TestTestPlan:
    """Tests for TestPlan dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        plan = TestPlan(target_module="test.py", change_type="MODIFY")
        assert plan.existing_tests == []
        assert plan.new_tests_needed == []
        assert plan.uncovered_functions == []
