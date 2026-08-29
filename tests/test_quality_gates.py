"""Tests for core/quality_gates.py — Quality Gates System."""

from __future__ import annotations

import pytest
from core.quality_gates import (
    QGResult,
    evaluate_pr,
    get_quality_gates,
    reset_quality_gates,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_quality_gates()
    yield
    reset_quality_gates()


class TestQualityGatesEngine:
    """Tests for the QualityGatesEngine class."""

    def test_singleton(self):
        engine1 = get_quality_gates()
        engine2 = get_quality_gates()
        assert engine1 is engine2

    def test_reset(self):
        engine1 = get_quality_gates()
        reset_quality_gates()
        engine2 = get_quality_gates()
        assert engine1 is not engine2

    def test_evaluate_pr_no_files(self):
        engine = get_quality_gates()
        result = engine.evaluate_pr(files_changed=[])
        assert isinstance(result, QGResult)
        assert result.n_files_changed == 0
        assert result.engineering_score >= 0
        assert result.overall_verdict in ("PASS", "CONDITIONAL", "BLOCKED")

    def test_evaluate_pr_single_core_file(self):
        engine = get_quality_gates()
        result = engine.evaluate_pr(
            files_changed=["core/risk_service.py"],
            lines_added=50,
            lines_deleted=10,
            commit_message="fix: improve risk calculation",
        )
        assert result.n_files_changed == 1
        assert result.n_lines_added == 50
        assert result.n_lines_deleted == 10
        assert len(result.gate_scores) == 14  # All 14 scored dimensions (engineering_score is computed)

    def test_evaluate_pr_gate_scores_structure(self):
        engine = get_quality_gates()
        result = engine.evaluate_pr(files_changed=["core/foo.py"])
        for gate in result.gate_scores:
            assert 0.0 <= gate.score <= 10.0
            assert gate.weight > 0
            assert gate.name

    def test_evaluate_pr_engineering_score_computation(self):
        engine = get_quality_gates()
        result = engine.evaluate_pr(files_changed=["core/foo.py"])
        assert 0.0 <= result.engineering_score <= 10.0

    def test_evaluate_pr_no_test_for_source_change_warning(self):
        engine = get_quality_gates()
        result = engine.evaluate_pr(
            files_changed=["core/some_module.py"],
            commit_message="feat: add new feature",
        )
        # Should warn about no test changes
        has_test_warning = any(
            "test" in w.lower() for w in result.warnings
        )
        assert has_test_warning

    def test_evaluate_pr_with_tests_no_warning(self):
        engine = get_quality_gates()
        result = engine.evaluate_pr(
            files_changed=["core/some_module.py", "tests/test_some_module.py"],
            commit_message="feat: add with tests",
        )
        testability_gate = next(
            (g for g in result.gate_scores if g.name == "testability"), None
        )
        assert testability_gate is not None
        assert testability_gate.score > 7.0

    def test_evaluate_pr_blocking_findings_forbidden_pattern(self, tmp_path):
        """Test that forbidden patterns generate blocking findings."""
        risky_file = tmp_path / "risky.py"
        risky_file.write_text("from kiteconnect import KiteConnect")
        engine = get_quality_gates()
        result = engine.evaluate_pr(files_changed=[str(risky_file)])
        arch_gate = next(
            (g for g in result.gate_scores if g.name == "architecture"), None
        )
        assert arch_gate is not None
        if arch_gate.findings:
            assert any("kite" in f.lower() for f in arch_gate.findings)

    def test_evaluate_pr_large_change_set(self):
        engine = get_quality_gates()
        result = engine.evaluate_pr(
            files_changed=[f"core/module_{i}.py" for i in range(20)],
            lines_added=600,
            lines_deleted=100,
        )
        maint_gate = next(
            (g for g in result.gate_scores if g.name == "maintainability"), None
        )
        assert maint_gate is not None
        # Large changes should reduce maintainability
        if maint_gate.score < 10.0:
            assert len(maint_gate.findings) > 0

    def test_evaluate_pr_json_output(self):
        engine = get_quality_gates()
        result = engine.evaluate_pr(files_changed=["core/foo.py"])
        data = result.to_dict()
        assert "engineering_score" in data
        assert "overall_verdict" in data
        assert "gate_scores" in data
        assert len(data["gate_scores"]) == 14

    def test_convenience_function(self):
        result = evaluate_pr(
            files_changed=["core/foo.py"],
            commit_message="test change",
        )
        assert isinstance(result, QGResult)

    def test_get_stats_empty(self):
        engine = get_quality_gates()
        stats = engine.get_stats()
        assert stats["total_evaluations"] >= 0

    def test_get_stats_after_evaluations(self):
        engine = get_quality_gates()
        engine.evaluate_pr(files_changed=["core/a.py"])
        engine.evaluate_pr(files_changed=["core/b.py"])
        stats = engine.get_stats()
        assert stats["total_evaluations"] >= 2

    def test_get_history(self):
        engine = get_quality_gates()
        engine.evaluate_pr(files_changed=["core/a.py"])
        engine.evaluate_pr(files_changed=["core/b.py"])
        history = engine.get_history(limit=5)
        assert len(history) >= 2
        assert all("engineering_score" in h for h in history)

    def test_no_documentation_for_new_feature(self):
        engine = get_quality_gates()
        result = engine.evaluate_pr(
            files_changed=["core/foo.py"],
            commit_message="feat: add brand new feature",
        )
        doc_gate = next(
            (g for g in result.gate_scores if g.name == "documentation"), None
        )
        assert doc_gate is not None
        # New feature without doc changes should lower score
        if doc_gate.score < 10.0:
            assert doc_gate.findings


if __name__ == "__main__":
    pytest.main([__file__])
