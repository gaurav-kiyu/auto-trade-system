"""
Smoke tests for scripts.production_score_challenge — Adversarial Score Challenge.

Verifies:
- Module imports correctly
- Challenge functions run without errors
- Challenge reports have expected structure
- CLI runs without errors
"""

from __future__ import annotations

import os
import sys


def _import_module():
    """Import scripts.production_score_challenge with clean module state."""
    for mod in list(sys.modules.keys()):
        if "production_score_challenge" in mod:
            del sys.modules[mod]
    # Ensure project root is on path
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    import scripts.production_score_challenge as m
    return m


class TestModuleImports:
    """Verify module imports correctly."""

    def test_import(self):
        """Module imports without errors."""
        m = _import_module()
        assert m is not None
        assert hasattr(m, "ChallengeResult")
        assert hasattr(m, "ChallengeReport")
        assert hasattr(m, "run_challenge")
        assert hasattr(m, "run_full_challenge")
        assert hasattr(m, "CATEGORIES")
        assert hasattr(m, "ORIGINAL_SCORES")

    def test_categories_defined(self):
        """All expected categories are defined."""
        m = _import_module()
        assert "risk" in m.CATEGORIES
        assert "execution" in m.CATEGORIES
        assert "architecture" in m.CATEGORIES

    def test_original_scores_defined(self):
        """Original scores are defined for all categories."""
        m = _import_module()
        assert "risk" in m.ORIGINAL_SCORES
        assert "execution" in m.ORIGINAL_SCORES
        assert "architecture" in m.ORIGINAL_SCORES
        assert all(isinstance(v, (int, float)) for v in m.ORIGINAL_SCORES.values())


class TestChallengeResult:
    """Verify ChallengeResult dataclass."""

    def test_default_creation(self):
        """ChallengeResult creates with all fields."""
        m = _import_module()
        r = m.ChallengeResult(
            category="risk",
            challenge_name="Test Challenge",
            passed=True,
            severity="HIGH",
            description="A test challenge",
            evidence="test.py:42",
            recommendation="Do something",
        )
        assert r.category == "risk"
        assert r.challenge_name == "Test Challenge"
        assert r.passed is True
        assert r.severity == "HIGH"
        assert r.description == "A test challenge"


class TestChallengeReport:
    """Verify ChallengeReport dataclass."""

    def test_default_values(self):
        """Report initializes with defaults."""
        m = _import_module()
        r = m.ChallengeReport(category="risk")
        assert r.category == "risk"
        assert r.total == 0
        assert r.passed == 0
        assert r.failed == 0
        assert r.original_score == 0.0
        assert r.challenged_score == 0.0

    def test_summary_contains_verdict(self):
        """Summary includes verdict."""
        m = _import_module()
        r = m.ChallengeReport(category="risk", total=2, passed=2,
                              original_score=9.5, challenged_score=9.5,
                              verdict="CHALLENGE_PASSED")
        s = r.summary()
        assert "CHALLENGE_PASSED" in s
        assert "9.5" in s


class TestChallengeFunctions:
    """Verify individual challenge functions work."""

    def test_no_bare_excepts(self):
        """Bare excepts challenge finds typed exceptions."""
        m = _import_module()
        r = m._challenge_no_bare_excepts()
        assert isinstance(r, m.ChallengeResult)
        assert r.category == "risk"
        # Should pass since codebase has all typed exceptions
        assert r.passed is True or r.severity != "CRITICAL"

    def test_hard_halt(self):
        """Hard halt challenge completes."""
        m = _import_module()
        r = m._challenge_hard_halt()
        assert isinstance(r, m.ChallengeResult)
        assert r.category == "risk"

    def test_order_state_machine(self):
        """Order state machine challenge completes."""
        m = _import_module()
        r = m._challenge_order_state_machine()
        assert isinstance(r, m.ChallengeResult)
        assert r.category == "execution"

    def test_execution_timeout(self):
        """Execution timeout challenge completes."""
        m = _import_module()
        r = m._challenge_execution_timeout()
        assert isinstance(r, m.ChallengeResult)
        assert r.category == "execution"

    def test_capital_preservation(self):
        """Capital preservation challenge completes."""
        m = _import_module()
        r = m._challenge_capital_preservation()
        assert isinstance(r, m.ChallengeResult)
        assert r.category == "risk"

    def test_database_consistency(self):
        """Database consistency challenge completes."""
        m = _import_module()
        r = m._challenge_database_consistency()
        assert isinstance(r, m.ChallengeResult)
        assert r.category == "architecture"

    def test_lookahead_bias(self):
        """Look-ahead bias challenge completes."""
        m = _import_module()
        r = m._challenge_lookahead_bias()
        assert isinstance(r, m.ChallengeResult)
        assert r.category == "architecture"


class TestRunChallenge:
    """Verify run_challenge and run_full_challenge work."""

    def test_run_risk_challenge(self):
        """Risk challenge runs end-to-end."""
        m = _import_module()
        r = m.run_challenge("risk")
        assert isinstance(r, m.ChallengeReport)
        assert r.category == "risk"
        assert r.total >= 3  # At least 3 risk challenges
        assert r.total == r.passed + r.failed
        assert r.verdict != ""

    def test_run_execution_challenge(self):
        """Execution challenge runs end-to-end."""
        m = _import_module()
        r = m.run_challenge("execution")
        assert isinstance(r, m.ChallengeReport)
        assert r.category == "execution"
        assert r.total >= 2
        assert r.verdict != ""

    def test_run_architecture_challenge(self):
        """Architecture challenge runs end-to-end."""
        m = _import_module()
        r = m.run_challenge("architecture")
        assert isinstance(r, m.ChallengeReport)
        assert r.category == "architecture"
        assert r.total >= 1
        assert r.verdict != ""

    def test_run_full_challenge(self):
        """Full challenge runs all categories."""
        m = _import_module()
        reports = m.run_full_challenge()
        assert len(reports) >= 3
        categories = {r.category for r in reports}
        assert "risk" in categories
        assert "execution" in categories
        assert "architecture" in categories

    def test_report_to_dict(self):
        """ChallengeReport.to_dict has expected structure."""
        m = _import_module()
        r = m.run_challenge("risk")
        d = r.to_dict()
        assert d["category"] == "risk"
        assert "total" in d
        assert "passed" in d
        assert "failed" in d
        assert "original_score" in d
        assert "challenged_score" in d
        assert "verdict" in d
        assert "results" in d

    def test_cli_runs(self):
        """CLI entry point runs without crashing."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "scripts/production_score_challenge.py", "--json"],
            capture_output=True, text=True, timeout=30,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        print(f"CLI stdout: {result.stdout[:500]}")
        print(f"CLI stderr: {result.stderr[:500]}")
        # Should exit 0 (all passed), 1 (warnings), or 2 (failures)
        assert result.returncode in (0, 1, 2)
        # Should produce JSON output
        assert result.stdout.startswith("[") or result.stdout.startswith("{\n")
        assert "challenged_score" in result.stdout or "verdict" in result.stdout
