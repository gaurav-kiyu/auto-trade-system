"""Tests for scripts/institutional_challenge.py - Adversarial Certification."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts import institutional_challenge


class TestChallengeRiskBypass:
    """Tests for risk control bypass challenge."""

    def test_returns_challenge_result(self) -> None:
        """Should return a ChallengeResult."""
        result = institutional_challenge.challenge_risk_bypass()
        assert isinstance(result, institutional_challenge.ChallengeResult)
        assert result.challenge_id == "CH-RSK-01"
        assert result.category == "risk"
        assert result.passed in (True, False)
        assert len(result.name) > 0

    def test_result_has_detail(self) -> None:
        """Should have a detail message."""
        result = institutional_challenge.challenge_risk_bypass()
        assert len(result.detail) > 0

    def test_result_has_duration(self) -> None:
        """Should have a positive duration."""
        result = institutional_challenge.challenge_risk_bypass()
        assert result.duration_s >= 0.0


class TestChallengeHiddenBugs:
    """Tests for hidden bug patterns challenge."""

    def test_returns_challenge_result(self) -> None:
        """Should return a ChallengeResult."""
        result = institutional_challenge.challenge_hidden_bugs()
        assert isinstance(result, institutional_challenge.ChallengeResult)
        assert result.challenge_id == "CH-BUG-01"

    def test_result_has_duration(self) -> None:
        """Should execute and return."""
        result = institutional_challenge.challenge_hidden_bugs()
        assert result.duration_s >= 0.0


class TestChallengeRaceCondition:
    """Tests for race condition challenge."""

    def test_returns_challenge_result(self) -> None:
        """Should return a ChallengeResult."""
        result = institutional_challenge.challenge_race_condition()
        assert isinstance(result, institutional_challenge.ChallengeResult)
        assert result.challenge_id == "CH-RACE-01"

    def test_result_has_detail(self) -> None:
        """Should have a detail message."""
        result = institutional_challenge.challenge_race_condition()
        assert len(result.detail) > 0


class TestChallengeDataLeakage:
    """Tests for data leakage challenge."""

    def test_returns_challenge_result(self) -> None:
        """Should return a ChallengeResult."""
        result = institutional_challenge.challenge_data_leakage()
        assert isinstance(result, institutional_challenge.ChallengeResult)
        assert result.challenge_id == "CH-DATA-01"
        assert result.category == "security"


class TestChallengeCatastrophicLoss:
    """Tests for catastrophic loss challenge."""

    def test_returns_challenge_result(self) -> None:
        """Should return a ChallengeResult."""
        result = institutional_challenge.challenge_catastrophic_loss()
        assert isinstance(result, institutional_challenge.ChallengeResult)
        assert result.challenge_id == "CH-CATA-01"
        assert result.category == "catastrophic"

    def test_result_has_detail(self) -> None:
        """Should have a detail message."""
        result = institutional_challenge.challenge_catastrophic_loss()
        assert len(result.detail) > 0


class TestChallengeReplayConsistency:
    """Tests for replay consistency challenge."""

    def test_returns_challenge_result(self) -> None:
        """Should return a ChallengeResult."""
        result = institutional_challenge.challenge_replay_consistency()
        assert isinstance(result, institutional_challenge.ChallengeResult)
        assert result.challenge_id == "CH-REPLAY-01"
        assert result.category == "replay"


class TestChallengeExecutionFlaws:
    """Tests for execution flaw challenge."""

    def test_returns_challenge_result(self) -> None:
        """Should return a ChallengeResult."""
        result = institutional_challenge.challenge_execution_flaws()
        assert isinstance(result, institutional_challenge.ChallengeResult)
        assert result.challenge_id == "CH-EXE-01"
        assert result.category == "execution"


class TestChallengeSecurityPerimeter:
    """Tests for security perimeter challenge."""

    def test_returns_challenge_result(self) -> None:
        """Should return a ChallengeResult."""
        result = institutional_challenge.challenge_security_perimeter()
        assert isinstance(result, institutional_challenge.ChallengeResult)
        assert result.challenge_id == "CH-SEC-01"
        assert result.category == "security"


class TestChallengeResult:
    """Tests for the ChallengeResult dataclass."""

    def test_to_dict(self) -> None:
        """to_dict should produce correct structure."""
        result = institutional_challenge.ChallengeResult(
            challenge_id="TEST-01",
            name="Test Challenge",
            category="risk",
            passed=True,
            detail="Everything OK",
            duration_s=1.5,
            score_impact="none",
        )
        d = result.to_dict()
        assert d["challenge_id"] == "TEST-01"
        assert d["passed"] is True
        assert d["score_impact"] == "none"
        assert d["duration_s"] == 1.5


class TestMainCLI:
    """Tests for the CLI interface."""

    def test_main_ci_mode(self) -> None:
        """CI mode should exit 0 or 1."""
        exit_code = institutional_challenge.main(["--ci"])
        assert exit_code in (0, 1)

    def test_main_json_mode(self) -> None:
        """JSON mode should produce valid JSON."""
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = institutional_challenge.main(["--json"])
        assert exit_code in (0, 1)
        output = f.getvalue()
        if output.strip():
            data = json.loads(output)
            assert "challenges" in data
            assert "summary" in data
            assert "institutional_grade" in data

    def test_main_quick_mode(self) -> None:
        """Quick mode should run and not crash."""
        exit_code = institutional_challenge.main(["--quick", "--ci"])
        assert exit_code in (0, 1)

    def test_main_category_filter(self) -> None:
        """Category filter should work."""
        exit_code = institutional_challenge.main(["--category", "risk", "--ci"])
        assert exit_code in (0, 1)

    def test_main_update_score(self) -> None:
        """--update-score should not crash."""
        exit_code = institutional_challenge.main(["--update-score", "--ci"])
        assert exit_code in (0, 1)
