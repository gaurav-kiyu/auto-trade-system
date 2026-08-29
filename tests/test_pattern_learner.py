"""Tests for core/pattern_learner.py — Pattern Extraction (Pillar 7)."""

from __future__ import annotations

from core.knowledge_base import get_knowledge_base, reset_knowledge_base
from core.pattern_learner import (
    PatternLearner,
    PatternLearnerReport,
    get_pattern_learner,
    reset_pattern_learner,
)


class TestPatternLearner:
    """Tests for PatternLearner class."""

    def setup_method(self) -> None:
        reset_knowledge_base()
        reset_pattern_learner()
        kb = get_knowledge_base()
        kb.clear()
        self.learner = PatternLearner(kb=kb)

    def test_singleton(self) -> None:
        pl1 = get_pattern_learner()
        pl2 = get_pattern_learner()
        assert pl1 is pl2

    def test_reset(self) -> None:
        pl1 = get_pattern_learner()
        reset_pattern_learner()
        pl2 = get_pattern_learner()
        assert pl1 is not pl2

    def test_learn_from_incident(self) -> None:
        """Test learning from a simulated RootCauseResult."""
        class MockEvidence:
            category = "STACK_TRACE"
            description = "File 'core/broker.py' at line 42 in connect()"
            relevance = 0.9
            timestamp = 0.0
            details = {}
            source = "runtime"

        class MockResult:
            incident_type = "broker_disconnect"
            incident_message = "Connection refused"
            probable_cause = "Network outage blocking outbound connections"
            severity = "CRITICAL"
            recommended_fix = "Check firewall rules and broker status page"
            evidence = [MockEvidence()]
            impacted_modules = ["core/broker.py"]

        entries = self.learner.learn_from_incident(MockResult())
        assert len(entries) >= 1
        assert entries[0].pattern_type == "INCIDENT_PATTERN"

    def test_learn_from_incident_empty(self) -> None:
        """Test that empty results don't create entries."""
        class MockEmpty:
            incident_type = ""
            incident_message = ""
            probable_cause = ""
            severity = ""
            recommended_fix = ""
            evidence = []

        entries = self.learner.learn_from_incident(MockEmpty())
        assert entries == []

    def test_learn_from_code_review(self) -> None:
        comments = [
            "This function has circular dependencies with module A",
            "Please add error handling for the timeout case",
            "Consider using a cache here for better performance",
            "Naming is fine",
        ]
        entries = self.learner.learn_from_code_review(
            pr_id="PR-42",
            comments=comments,
            author="reviewer1",
            files_changed=["core/foo.py", "core/bar.py"],
        )
        assert len(entries) >= 1
        # Should have categorized the first comment as architecture
        assert any("architecture" in e.tags for e in entries)

    def test_learn_from_code_review_empty(self) -> None:
        entries = self.learner.learn_from_code_review(pr_id="PR-1", comments=[])
        assert entries == []

    def test_learn_from_code_review_security(self) -> None:
        entries = self.learner.learn_from_code_review(
            pr_id="PR-99",
            comments=["SQL injection vulnerability in query builder"],
        )
        assert len(entries) >= 1
        assert any("security" in e.tags for e in entries)

    def test_learn_from_code_review_short_comment(self) -> None:
        entries = self.learner.learn_from_code_review(
            pr_id="PR-1",
            comments=["LGTM"],  # Too short - should be skipped
        )
        assert entries == []

    def test_learn_from_test_failure(self) -> None:
        entries = self.learner.learn_from_test_failure(
            test_name="test_place_order",
            error_message="AssertionError: Expected 200, got 500",
            traceback="Traceback...",
            module="tests/test_broker.py",
        )
        assert len(entries) >= 1
        assert entries[0].pattern_type == "TEST_FAILURE_PATTERN"
        assert "assertion" in entries[0].tags or "test_failure" in entries[0].tags

    def test_learn_from_test_failure_timeout(self) -> None:
        entries = self.learner.learn_from_test_failure(
            test_name="test_websocket",
            error_message="TimeoutError: Connection timed out after 30s",
            module="tests/test_feeds.py",
        )
        assert len(entries) >= 1
        assert "timeout" in entries[0].tags

    def test_learn_from_test_failure_empty(self) -> None:
        entries = self.learner.learn_from_test_failure(test_name="", error_message="")
        assert entries == []

    def test_get_recommendations(self) -> None:
        # Add some patterns first
        self.learner.learn_from_incident(_make_mock_incident("broker_disconnect", "Network issue"))
        self.learner.learn_from_incident(_make_mock_incident("db_failure", "Disk full"))

        recs = self.learner.get_recommendations("broker")
        assert len(recs) >= 1

    def test_get_recommendations_empty(self) -> None:
        recs = self.learner.get_recommendations("nonexistent_error_type")
        assert recs == []

    def test_get_report(self) -> None:
        report = self.learner.get_report()
        assert isinstance(report, PatternLearnerReport)
        assert report.total_incidents_learned >= 0

    def test_get_report_after_learning(self) -> None:
        self.learner.learn_from_incident(_make_mock_incident("test", "Test cause"))
        report = self.learner.get_report()
        assert report.total_incidents_learned == 1
        assert report.knowledge_base_entries >= 1

    def test_confidence_from_severity(self) -> None:
        assert self.learner._confidence_from_severity("CRITICAL") == 0.9
        assert self.learner._confidence_from_severity("HIGH") == 0.8
        assert self.learner._confidence_from_severity("NORMAL") == 0.6
        assert self.learner._confidence_from_severity("UNKNOWN") == 0.5

    def test_pattern_trends(self) -> None:
        trends = self.learner.get_pattern_trends(days=30)
        assert "total_recent" in trends
        assert "by_type" in trends
        assert "most_frequent" in trends


def _make_mock_incident(error_type: str, cause: str) -> object:
    """Helper to create a mock incident result."""
    class MockEvidence:
        category = "GENERAL"
        description = "Test evidence " + cause
        relevance = 0.7
        timestamp = 0.0
        details = {}
        source = "test"

    class MockResult:
        incident_type = error_type
        incident_message = f"Error: {cause}"
        probable_cause = cause
        severity = "HIGH"
        recommended_fix = f"Fix for {cause}"
        evidence = [MockEvidence()]
        impacted_modules = ["core/test.py"]

    return MockResult()
