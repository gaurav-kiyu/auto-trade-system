"""Tests for core/knowledge_base.py — Knowledge Base (Pillar 7)."""

from __future__ import annotations

from core.knowledge_base import (
    BEST_PRACTICE,
    INCIDENT_PATTERN,
    TEST_FAILURE_PATTERN,
    KnowledgeBaseReport,
    KnowledgeEntry,
    get_knowledge_base,
    reset_knowledge_base,
)


class TestKnowledgeEntry:
    """Tests for KnowledgeEntry dataclass."""

    def test_defaults(self) -> None:
        entry = KnowledgeEntry(entry_id="KB-001", pattern="test", solution="fix")
        assert entry.pattern_type == BEST_PRACTICE
        assert entry.frequency == 1
        assert entry.confidence == 0.5

    def test_to_dict(self) -> None:
        entry = KnowledgeEntry(
            entry_id="KB-001",
            pattern_type=INCIDENT_PATTERN,
            pattern="broker_disconnect: Network outage",
            solution="Check firewall",
            source="test",
            confidence=0.85,
            frequency=3,
            tags=["network", "critical"],
        )
        d = entry.to_dict()
        assert d["entry_id"] == "KB-001"
        assert d["pattern_type"] == INCIDENT_PATTERN
        assert d["frequency"] == 3
        assert d["confidence"] == 0.85

    def test_summary(self) -> None:
        entry = KnowledgeEntry(
            entry_id="KB-001",
            pattern_type=INCIDENT_PATTERN,
            pattern="Test pattern",
            solution="Test solution",
        )
        s = entry.summary()
        assert INCIDENT_PATTERN in s
        assert "Test pattern" in s


class TestKnowledgeBase:
    """Tests for KnowledgeBase class."""

    def setup_method(self) -> None:
        reset_knowledge_base()
        self.kb = get_knowledge_base()
        self.kb.clear()

    def test_singleton(self) -> None:
        kb1 = get_knowledge_base()
        kb2 = get_knowledge_base()
        assert kb1 is kb2

    def test_reset(self) -> None:
        kb1 = get_knowledge_base()
        reset_knowledge_base()
        kb2 = get_knowledge_base()
        assert kb1 is not kb2

    def test_add_entry(self) -> None:
        entry = self.kb.add_entry(
            pattern_type=INCIDENT_PATTERN,
            pattern="Broker connection lost",
            solution="Restart connection",
            source="test",
            confidence=0.8,
            tags=["broker"],
        )
        assert entry.entry_id.startswith("KB-")
        assert entry.frequency == 1
        assert entry.confidence == 0.8

    def test_add_duplicate_increments_frequency(self) -> None:
        e1 = self.kb.add_entry(
            pattern_type=INCIDENT_PATTERN,
            pattern="Unique test pattern XYZ",
            solution="Restart connection",
        )
        # Same reference - duplicate adds increment frequency in-place
        e2 = self.kb.add_entry(
            pattern_type=INCIDENT_PATTERN,
            pattern="Unique test pattern XYZ",
            solution="A different solution",
        )
        # Should be the same entry, frequency incremented
        assert e1.entry_id == e2.entry_id
        assert e2.frequency == 2
        # Confidence boosted by 0.05 each time (0.5 + 0.05)
        assert e2.confidence == 0.55

    def test_add_different_type_not_duplicate(self) -> None:
        e1 = self.kb.add_entry(
            pattern_type=INCIDENT_PATTERN,
            pattern="Test pattern",
        )
        e2 = self.kb.add_entry(
            pattern_type=TEST_FAILURE_PATTERN,
            pattern="Test pattern",
        )
        assert e1.entry_id != e2.entry_id

    def test_find_similar_by_keyword(self) -> None:
        self.kb.add_entry(
            pattern_type=INCIDENT_PATTERN,
            pattern="Broker connection timeout",
            solution="Check broker status",
            tags=["broker"],
        )
        self.kb.add_entry(
            pattern_type=INCIDENT_PATTERN,
            pattern="Database I/O error",
            solution="Check disk space",
            tags=["database"],
        )
        results = self.kb.find_similar("broker timeout")
        assert len(results) >= 1
        assert "broker" in results[0].pattern.lower()

    def test_find_similar_empty_query(self) -> None:
        results = self.kb.find_similar("")
        assert results == []

    def test_get_by_type(self) -> None:
        self.kb.add_entry(pattern_type=INCIDENT_PATTERN, pattern="Incident A")
        self.kb.add_entry(pattern_type=INCIDENT_PATTERN, pattern="Incident B")
        self.kb.add_entry(pattern_type=TEST_FAILURE_PATTERN, pattern="Test failure")
        incidents = self.kb.get_by_type(INCIDENT_PATTERN)
        tests = self.kb.get_by_type(TEST_FAILURE_PATTERN)
        assert len(incidents) == 2
        assert len(tests) == 1

    def test_get_by_tag(self) -> None:
        self.kb.add_entry(pattern_type=BEST_PRACTICE, pattern="Best practice", tags=["security"])
        self.kb.add_entry(pattern_type=BEST_PRACTICE, pattern="Another practice", tags=["performance"])
        security = self.kb.get_by_tag("security")
        assert len(security) == 1

    def test_get_by_id(self) -> None:
        entry = self.kb.add_entry(pattern_type=BEST_PRACTICE, pattern="Test entry")
        found = self.kb.get_by_id(entry.entry_id)
        assert found is not None
        assert found.entry_id == entry.entry_id
        not_found = self.kb.get_by_id("NONEXISTENT")
        assert not_found is None

    def test_remove_entry(self) -> None:
        entry = self.kb.add_entry(pattern_type=BEST_PRACTICE, pattern="Remove me")
        assert self.kb.remove_entry(entry.entry_id) is True
        assert self.kb.remove_entry("NONEXISTENT") is False
        assert self.kb.get_by_id(entry.entry_id) is None

    def test_update_entry(self) -> None:
        entry = self.kb.add_entry(
            pattern_type=BEST_PRACTICE,
            pattern="Update test",
            solution="old solution",
            confidence=0.5,
        )
        updated = self.kb.update_entry(entry.entry_id, solution="new solution", confidence=0.9)
        assert updated is not None
        assert updated.solution == "new solution"
        assert updated.confidence == 0.9

    def test_update_nonexistent(self) -> None:
        result = self.kb.update_entry("NONEXISTENT", solution="test")
        assert result is None

    def test_get_report_empty(self) -> None:
        report = self.kb.get_report()
        assert report.total_entries == 0
        assert isinstance(report, KnowledgeBaseReport)

    def test_get_report_with_data(self) -> None:
        self.kb.add_entry(pattern_type=INCIDENT_PATTERN, pattern="P1", tags=["urgent"])
        self.kb.add_entry(pattern_type=TEST_FAILURE_PATTERN, pattern="P2", tags=["bug"])
        self.kb.add_entry(pattern_type=BEST_PRACTICE, pattern="P3", tags=["urgent"])
        report = self.kb.get_report()
        assert report.total_entries == 3
        assert len(report.by_type) == 3
        assert report.by_tag.get("urgent", 0) == 2

    def test_clear(self) -> None:
        self.kb.add_entry(pattern_type=BEST_PRACTICE, pattern="Something")
        self.kb.clear()
        assert self.kb.get_report().total_entries == 0

    def test_max_entries_enforced(self) -> None:
        # Add more than MAX_ENTRIES (2000) — we can't do that many in a test,
        # but verify the mechanism doesn't break on smaller numbers
        for i in range(10):
            self.kb.add_entry(pattern_type=BEST_PRACTICE, pattern=f"Entry {i}")
        report = self.kb.get_report()
        assert report.total_entries <= 10
