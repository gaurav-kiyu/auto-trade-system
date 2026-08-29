"""Tests for RootCauseAnalyzer (Pillar 5)."""
from __future__ import annotations

import pytest
from core.root_cause_analyzer import (
    KNOWN_INCIDENT_PATTERNS,
    EvidenceItem,
    RootCauseResult,
    get_root_cause_analyzer,
    investigate_incident,
    reset_root_cause_analyzer,
)


@pytest.fixture(autouse=True)
def reset_analyzer() -> None:
    """Reset the singleton before each test."""
    reset_root_cause_analyzer()


class TestRootCauseAnalyzer:
    """Tests for the RootCauseAnalyzer class."""

    def test_singleton(self) -> None:
        """Test singleton pattern."""
        a1 = get_root_cause_analyzer()
        a2 = get_root_cause_analyzer()
        assert a1 is a2

    def test_reset(self) -> None:
        """Test reset clears the singleton."""
        a1 = get_root_cause_analyzer()
        reset_root_cause_analyzer()
        a2 = get_root_cause_analyzer()
        assert a1 is not a2

    def test_investigate_broker_disconnect(self) -> None:
        """Test investigation of a broker disconnect incident."""
        result = get_root_cause_analyzer().investigate(
            error_type="broker_disconnect",
            error_message="Connection refused: broker.zerodha.com:443",
        )
        assert isinstance(result, RootCauseResult)
        assert result.incident_type == "broker_disconnect"
        assert result.severity == "CRITICAL"
        assert result.probable_cause != ""
        assert result.confidence > 0
        assert result.recommended_fix != ""

    def test_investigate_db_failure(self) -> None:
        """Test investigation of a database failure."""
        result = get_root_cause_analyzer().investigate(
            error_type="db_failure",
            error_message="SQLite disk I/O error",
            stack_trace='File "core/db_utils.py", line 42, in get_connection',
        )
        assert result.incident_type == "db_failure"
        assert result.severity == "HIGH"
        assert result.impacted_modules is not None

    def test_investigate_with_stack_trace(self) -> None:
        """Test that stack traces are analyzed."""
        stack = '''Traceback (most recent call last):
  File "core/services/risk_service.py", line 150, in get_position_size
    raise ValueError("Invalid size")
ValueError: Invalid size'''
        result = get_root_cause_analyzer().investigate(
            error_type="risk_breach",
            error_message="Position size exceeded limit",
            stack_trace=stack,
        )
        assert len(result.evidence) >= 1
        # Should have stack trace evidence
        stack_evidence = [e for e in result.evidence if e.category == "STACK_TRACE"]
        assert len(stack_evidence) >= 1
        # Should have extracted modules
        assert any("risk_service.py" in mod for mod in result.impacted_modules)

    def test_investigate_with_module(self) -> None:
        """Test investigation with module context."""
        result = get_root_cause_analyzer().investigate(
            error_type="stale_quote",
            error_message="Yahoo Finance data not updating",
            module="core/yf_data_provider.py",
        )
        assert result.incident_type == "stale_quote"
        assert result.severity == "NORMAL"

    def test_investigate_unknown_type(self) -> None:
        """Test investigation with an unknown error type."""
        result = get_root_cause_analyzer().investigate(
            error_type="unknown_error_type",
            error_message="Something unexpected happened",
        )
        assert result.incident_type == "unknown_error_type"
        assert result.probable_cause != ""  # Should still get a cause

    def test_investigate_from_classified_error(self) -> None:
        """Test investigation from a classified error."""
        # Simulate an ErrorClassification-like object
        class MockClassification:
            category = type("Cat", (), {"value": "RETRIABLE"})()
            message = "Connection timeout"

        result = get_root_cause_analyzer().investigate_from_classified_error(
            MockClassification(),
            module="core/broker_adapters.py",
        )
        assert result.incident_type == "RETRIABLE"

    def test_evidence_item_creation(self) -> None:
        """Test that evidence items are created correctly."""
        evidence = EvidenceItem(
            category="STACK_TRACE",
            description="Test evidence",
            source="test",
            relevance=0.8,
        )
        assert evidence.category == "STACK_TRACE"
        assert evidence.relevance == 0.8
        d = evidence.to_dict()
        assert d["category"] == "STACK_TRACE"

    def test_get_incident_history(self) -> None:
        """Test getting incident history."""
        analyzer = get_root_cause_analyzer()
        # Investigate an incident to populate history
        analyzer.investigate("test_error", "Test message")
        history = analyzer.get_incident_history()
        assert isinstance(history, list)

    def test_get_incident_history_filtered(self) -> None:
        """Test getting filtered incident history."""
        analyzer = get_root_cause_analyzer()
        analyzer.investigate("error_a", "First error")
        analyzer.investigate("error_b", "Second error")
        history = analyzer.get_incident_history(incident_type="error_a")
        all_h = analyzer.get_incident_history()
        assert len(history) <= len(all_h)

    def test_get_incident_stats(self) -> None:
        """Test getting incident stats."""
        analyzer = get_root_cause_analyzer()
        stats = analyzer.get_incident_stats()
        assert isinstance(stats, dict)
        assert "total" in stats

    def test_clear_history(self) -> None:
        """Test clearing history."""
        analyzer = get_root_cause_analyzer()
        analyzer.investigate("test", "Test")
        analyzer.clear_history()
        stats = analyzer.get_incident_stats()
        assert stats["total"] == 0

    def test_known_patterns_exist(self) -> None:
        """Test that known incident patterns are defined."""
        assert len(KNOWN_INCIDENT_PATTERNS) > 0
        assert "broker_disconnect" in KNOWN_INCIDENT_PATTERNS
        assert "db_failure" in KNOWN_INCIDENT_PATTERNS
        assert "risk_breach" in KNOWN_INCIDENT_PATTERNS
        assert "circuit_breaker" in KNOWN_INCIDENT_PATTERNS

    def test_pattern_has_fields(self) -> None:
        """Test that each pattern has required fields."""
        for name, pattern in KNOWN_INCIDENT_PATTERNS.items():
            assert "description" in pattern
            assert "common_causes" in pattern
            assert "recovery_actions" in pattern
            assert "severity" in pattern
            assert len(pattern["common_causes"]) > 0
            assert len(pattern["recovery_actions"]) > 0

    def test_result_to_dict(self) -> None:
        """Test serialization of results."""
        result = get_root_cause_analyzer().investigate(
            "test_error", "Test message"
        )
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "incident_type" in d
        assert "probable_cause" in d
        assert "confidence" in d
        assert "evidence_count" in d

    def test_result_summary_text(self) -> None:
        """Test summary text generation."""
        result = get_root_cause_analyzer().investigate(
            "test_error", "Test message"
        )
        text = result.summary_text()
        assert "ROOT CAUSE ANALYSIS" in text.upper()
        assert "Test message" in text

    def test_convenience_function(self) -> None:
        """Test the investigate_incident convenience function."""
        result = investigate_incident(
            "broker_disconnect",
            "Connection lost",
            module="core/broker_adapters.py",
        )
        assert isinstance(result, RootCauseResult)

    def test_suggested_rollback_on_risk_breach(self) -> None:
        """Test that risk breaches suggest rollback."""
        result = get_root_cause_analyzer().investigate(
            "risk_breach", "Daily loss limit exceeded"
        )
        # Risk breaches should suggest rollback
        assert result.suggested_rollback is True

    def test_new_pattern_auth_expiry(self) -> None:
        """Test auth_expiry pattern exists and has correct severity."""
        assert "auth_expiry" in KNOWN_INCIDENT_PATTERNS
        assert KNOWN_INCIDENT_PATTERNS["auth_expiry"]["severity"] == "CRITICAL"

    def test_new_pattern_network_outage(self) -> None:
        """Test network_outage pattern exists and has correct severity."""
        assert "network_outage" in KNOWN_INCIDENT_PATTERNS
        assert KNOWN_INCIDENT_PATTERNS["network_outage"]["severity"] == "HIGH"

    def test_new_pattern_memory_pressure(self) -> None:
        """Test memory_pressure pattern exists and has severity HIGH."""
        assert "memory_pressure" in KNOWN_INCIDENT_PATTERNS
        assert KNOWN_INCIDENT_PATTERNS["memory_pressure"]["severity"] == "HIGH"

    def test_investigate_auth_expiry(self) -> None:
        """Test investigation of an auth expiry incident."""
        result = get_root_cause_analyzer().investigate(
            error_type="auth_expiry",
            error_message="Token expired for broker.zerodha.com",
        )
        assert result.incident_type == "auth_expiry"
        assert result.severity == "CRITICAL"
        assert result.probable_cause != ""

    def test_investigate_network_outage(self) -> None:
        """Test investigation of a network outage incident."""
        result = get_root_cause_analyzer().investigate(
            error_type="network_outage",
            error_message="Connection timeout after 30s",
        )
        assert result.incident_type == "network_outage"
        assert result.severity == "HIGH"

    def test_confidence_bayesian_diversity(self) -> None:
        """Test that more diverse evidence increases confidence."""
        analyzer = get_root_cause_analyzer()
        # Investigate with stack trace (diverse evidence)
        result_with_stack = analyzer.investigate(
            error_type="db_failure",
            error_message="Database error",
            stack_trace='File "core/db.py", line 10, in query',
        )
        # Investigate without stack trace (less diverse)
        result_without = analyzer.investigate(
            error_type="db_failure",
            error_message="Database error",
        )
        # With stack trace, we should have more evidence categories
        assert result_with_stack.confidence >= result_without.confidence

    def test_infrastructure_evidence_collection(self) -> None:
        """Test infrastructure evidence collection method exists."""
        analyzer = get_root_cause_analyzer()
        evidence = analyzer._collect_infrastructure_evidence()
        # This should not raise
        assert isinstance(evidence, list)

    def test_db_schema_evidence_collection(self) -> None:
        """Test DB schema evidence collection method exists."""
        analyzer = get_root_cause_analyzer()
        evidence = analyzer._collect_db_schema_evidence()
        # This should not raise
        assert isinstance(evidence, list)

    def test_dependency_evidence_collection(self) -> None:
        """Test dependency evidence collection method exists."""
        analyzer = get_root_cause_analyzer()
        evidence = analyzer._collect_dependency_evidence()
        # This should not raise
        assert isinstance(evidence, list)

    def test_new_patterns_have_all_fields(self) -> None:
        """Test that new patterns have required fields."""
        for name in ("auth_expiry", "network_outage", "memory_pressure"):
            pattern = KNOWN_INCIDENT_PATTERNS[name]
            assert "description" in pattern
            assert "common_causes" in pattern
            assert "recovery_actions" in pattern
            assert "severity" in pattern
            assert len(pattern["common_causes"]) > 0

    def test_new_pattern_recovery_actions(self) -> None:
        """Test that new patterns have actionable recovery steps."""
        for name in ("auth_expiry", "network_outage", "memory_pressure"):
            pattern = KNOWN_INCIDENT_PATTERNS[name]
            actions = pattern["recovery_actions"]
            assert len(actions) >= 3
            assert all(isinstance(a, str) for a in actions)


class TestRootCauseResult:
    """Tests for RootCauseResult dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        result = RootCauseResult(
            incident_type="test",
            incident_message="test message",
        )
        assert result.confidence == 0.0
        assert result.evidence == []
        assert result.impacted_modules == []
        assert result.suggested_rollback is False
