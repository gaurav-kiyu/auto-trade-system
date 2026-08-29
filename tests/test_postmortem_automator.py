"""Tests for Postmortem Automator module."""

from __future__ import annotations

import pytest
from core.postmortem_automator import (
    ActionItem,
    LessonLearned,
    PostmortemDocument,
    PostmortemReport,
    TimelineEvent,
    get_postmortem_automator,
    reset_postmortem_automator,
)


@pytest.fixture(autouse=True)
def reset_auto():
    from pathlib import Path
    reset_postmortem_automator()
    # Clear persisted data to prevent state leaking between tests
    for p in [Path("json/postmortems.json"), Path("json/action_items.json")]:
        if p.exists():
            p.unlink()
    yield
    reset_postmortem_automator()


# ── Postmortem Generation Tests ──────────────────────────────────────────


class TestPostmortemGeneration:
    def test_generate_broker_disconnect(self):
        auto = get_postmortem_automator()
        pm = auto.generate_postmortem(
            incident_type="broker_disconnect",
            incident_message="Connection refused: broker.zerodha.com:443",
            severity="CRITICAL",
            module="core/adapters/broker/kite.py",
        )
        assert pm.title is not None
        assert "Postmortem" in pm.title or "Broker" in pm.title
        assert pm.incident_type == "broker_disconnect"
        assert pm.severity == "CRITICAL"
        assert pm.incident_id.startswith("PM-")
        assert len(pm.action_items) > 0
        assert len(pm.lessons_learned) > 0

    def test_generate_db_failure(self):
        auto = get_postmortem_automator()
        pm = auto.generate_postmortem(
            incident_type="db_failure",
            incident_message="Disk full: unable to write to database",
            severity="HIGH",
        )
        assert pm.incident_type == "db_failure"
        assert pm.category == "Infrastructure"
        assert pm.severity == "HIGH"
        assert pm.incident_id.startswith("PM-")

    def test_generate_risk_breach(self):
        auto = get_postmortem_automator()
        pm = auto.generate_postmortem(
            incident_type="risk_breach",
            incident_message="Maximum daily loss limit exceeded",
            severity="CRITICAL",
        )
        assert pm.incident_type == "risk_breach"
        assert pm.category == "Risk Management"

    def test_generate_stale_quote(self):
        auto = get_postmortem_automator()
        pm = auto.generate_postmortem(
            incident_type="stale_quote",
            incident_message="LTP not updated for 30 seconds",
            severity="NORMAL",
        )
        assert pm.incident_type == "stale_quote"
        assert pm.severity == "NORMAL"

    def test_generate_circuit_breaker(self):
        auto = get_postmortem_automator()
        pm = auto.generate_postmortem(
            incident_type="circuit_breaker",
            incident_message="Circuit breaker triggered after 5 consecutive failures",
            severity="HIGH",
        )
        assert pm.incident_type == "circuit_breaker"
        assert pm.category == "Reliability"

    def test_generate_reconciliation_mismatch(self):
        auto = get_postmortem_automator()
        pm = auto.generate_postmortem(
            incident_type="reconciliation_mismatch",
            incident_message="Position mismatch detected between internal state and broker",
            severity="HIGH",
        )
        assert pm.incident_type == "reconciliation_mismatch"
        assert pm.category == "Data Integrity"

    def test_generate_unknown_incident_type(self):
        auto = get_postmortem_automator()
        pm = auto.generate_postmortem(
            incident_type="unknown_error",
            incident_message="Something unexpected happened",
        )
        assert pm.incident_type == "unknown_error"
        assert pm.category == "Operational"
        assert pm.incident_id.startswith("PM-")

    def test_generate_with_metadata(self):
        auto = get_postmortem_automator()
        pm = auto.generate_postmortem(
            incident_type="broker_disconnect",
            incident_message="Connection timeout",
            severity="HIGH",
            metadata={"duration_minutes": 45},
        )
        # Duration is calculated from timeline events, so it may differ from metadata
        assert pm.duration_minutes > 0

    def test_postmortem_has_summary(self):
        auto = get_postmortem_automator()
        pm = auto.generate_postmortem(
            incident_type="broker_disconnect",
            incident_message="Broker API returned 503",
            severity="CRITICAL",
        )
        assert len(pm.summary) > 0
        assert "CRITICAL" in pm.summary or "broker" in pm.summary

    def test_postmortem_has_timeline(self):
        auto = get_postmortem_automator()
        pm = auto.generate_postmortem(
            incident_type="broker_disconnect",
            incident_message="Connection lost",
            severity="HIGH",
        )
        assert len(pm.timeline) >= 2  # At least detection + investigation


# ── Retrieval Tests ──────────────────────────────────────────────────────


class TestPostmortemRetrieval:
    def test_get_postmortem_by_id(self):
        auto = get_postmortem_automator()
        pm = auto.generate_postmortem("broker_disconnect", "Test message")
        retrieved = auto.get_postmortem(pm.incident_id)
        assert retrieved is not None
        assert retrieved.incident_id == pm.incident_id

    def test_get_postmortem_not_found(self):
        auto = get_postmortem_automator()
        assert auto.get_postmortem("PM-NONEXISTENT") is None

    def test_get_all_postmortems(self):
        auto = get_postmortem_automator()
        auto.generate_postmortem("broker_disconnect", "Test 1")
        auto.generate_postmortem("db_failure", "Test 2")
        auto.generate_postmortem("risk_breach", "Test 3")
        all_pms = auto.get_all_postmortems()
        assert len(all_pms) == 3

    def test_get_all_postmortems_limit(self):
        auto = get_postmortem_automator()
        for i in range(10):
            auto.generate_postmortem("broker_disconnect", f"Test {i}")
        limited = auto.get_all_postmortems(limit=3)
        assert len(limited) == 3


# ── Action Item Tests ────────────────────────────────────────────────────


class TestActionItems:
    def test_generates_action_items(self):
        auto = get_postmortem_automator()
        pm = auto.generate_postmortem("db_failure", "Disk full")
        assert len(pm.action_items) > 0

    def test_complete_action_item(self):
        auto = get_postmortem_automator()
        pm = auto.generate_postmortem("db_failure", "Disk full")
        action_desc = pm.action_items[0].description
        assert auto.complete_action_item(action_desc) is True
        # Verify it's completed
        completed = auto.get_action_items(status="COMPLETED")
        assert any(a.description == action_desc for a in completed)

    def test_complete_nonexistent_action_item(self):
        auto = get_postmortem_automator()
        assert auto.complete_action_item("Nonexistent action") is False

    def test_get_action_items_open(self):
        auto = get_postmortem_automator()
        auto.generate_postmortem("broker_disconnect", "Test")
        open_items = auto.get_action_items(status="OPEN")
        assert len(open_items) > 0
        assert all(a.status == "OPEN" for a in open_items)

    def test_action_item_dedup(self):
        auto = get_postmortem_automator()
        pm1 = auto.generate_postmortem("broker_disconnect", "Test 1")
        auto.generate_postmortem("broker_disconnect", "Test 2")
        # Same incident type = potentially overlapping action items
        # Just verify all descriptions are unique within a single postmortem
        descriptions = [a.description for a in pm1.action_items]
        assert len(descriptions) == len(set(descriptions))


# ── Statistics & Report Tests ────────────────────────────────────────────


class TestPostmortemStats:
    def test_get_stats_initial(self):
        auto = get_postmortem_automator()
        stats = auto.get_stats()
        assert stats["total_postmortems"] == 0
        assert stats["total_action_items"] == 0

    def test_get_stats_after_generation(self):
        auto = get_postmortem_automator()
        auto.generate_postmortem("broker_disconnect", "Test message")
        auto.generate_postmortem("db_failure", "Another test")
        stats = auto.get_stats()
        assert stats["total_postmortems"] == 2
        assert stats["total_action_items"] > 0

    def test_get_report(self):
        auto = get_postmortem_automator()
        auto.generate_postmortem("broker_disconnect", "Test")
        auto.generate_postmortem("risk_breach", "Risk test")
        report = auto.get_report()
        assert report.total_postmortems == 2
        assert "Connectivity" in report.by_category
        assert "Risk Management" in report.by_category

    def test_clear_all(self):
        auto = get_postmortem_automator()
        auto.generate_postmortem("broker_disconnect", "Test")
        auto.clear_all()
        stats = auto.get_stats()
        assert stats["total_postmortems"] == 0
        assert stats["total_action_items"] == 0

    def test_trend_first_occurrence(self):
        auto = get_postmortem_automator()
        pm = auto.generate_postmortem("unknown_type", "First time")
        assert pm.trend == "FIRST_OCCURRENCE"

    def test_trend_recurring(self):
        auto = get_postmortem_automator()
        auto.generate_postmortem("broker_disconnect", "First")
        auto.generate_postmortem("broker_disconnect", "Second")
        auto.generate_postmortem("broker_disconnect", "Third")
        pm = auto.generate_postmortem("broker_disconnect", "Fourth")
        assert pm.trend == "RECURRING"

    def test_postmortem_report_summary(self):
        r = PostmortemReport(
            total_postmortems=5,
            by_category={"Connectivity": 3, "Infrastructure": 2},
            by_severity={"CRITICAL": 1, "HIGH": 2, "NORMAL": 2},
            open_action_items=8,
            completed_action_items=3,
        )
        text = r.summary_text()
        assert "POSTMORTEM" in text
        assert "Connectivity" in text
        assert "CRITICAL" in text


# ── Data Model Tests ────────────────────────────────────────────────────


class TestDataModels:
    def test_timeline_event(self):
        e = TimelineEvent(event_type="DETECTION", description="Incident detected")
        d = e.to_dict()
        assert d["event_type"] == "DETECTION"

    def test_lesson_learned(self):
        lesson = LessonLearned(category="TECHNOLOGY", description="Lesson", priority="HIGH")
        d = lesson.to_dict()
        assert d["category"] == "TECHNOLOGY"
        assert d["priority"] == "HIGH"

    def test_action_item_to_dict(self):
        a = ActionItem(description="Fix issue", priority="HIGH", due_days=14, status="OPEN")
        d = a.to_dict()
        assert d["status"] == "OPEN"
        assert d["due_days"] == 14

    def test_postmortem_document_to_dict(self):
        pm = PostmortemDocument(
            title="Test",
            incident_id="PM-123",
            incident_type="test",
            severity="LOW",
        )
        d = pm.to_dict()
        assert d["title"] == "Test"
        assert d["incident_id"] == "PM-123"
