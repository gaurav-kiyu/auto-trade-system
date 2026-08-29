"""Tests for Decision Memory module — including Q&A, timeline, reversal strategy, and tracking."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from core.decision_memory import (
    DecisionMemory,
    DecisionMemoryReport,
    DecisionRecord,
    DecisionSearchResult,
    DecisionTimelineEntry,
    QuestionAnswer,
    get_decision_memory,
    reset_decision_memory,
)


@pytest.fixture(autouse=True)
def reset_memory():
    reset_decision_memory()
    p = Path("json/decision_memory.json")
    if p.exists():
        p.unlink()
    yield
    reset_decision_memory()


# =============================================================================
# Decision Recording Tests
# =============================================================================


class TestDecisionRecording:
    def test_record_simple_decision(self):
        mem = get_decision_memory()
        record = mem.record_decision(
            title="Use PostgreSQL for production",
            context="SQLite handles dev but lacks production concurrency",
            decision="Adopt PostgreSQL with connection pooling",
            rationale="Better transactional guarantees",
        )
        assert record.decision_id.startswith("DEC-")
        assert record.title == "Use PostgreSQL for production"
        assert record.status == "ACCEPTED"
        assert record.priority == "MEDIUM"

    def test_record_decision_with_all_fields(self):
        mem = get_decision_memory()
        record = mem.record_decision(
            title="Adopt Mediator Pattern",
            context="Need better separation of concerns",
            decision="Use mediator for command/query handling",
            rationale="Reduces coupling between components",
            alternatives=["Direct service calls", "Event bus"],
            consequences=["More boilerplate", "Better testability"],
            reversal_strategy="Revert to direct calls if latency increases",
            tradeoffs="More indirection for better testability",
            module_paths=["core/patterns/mediator.py", "core/di_container.py"],
            impact_categories=["ARCHITECTURE", "MAINTAINABILITY"],
            priority="HIGH",
            author="Architect",
            approver="CTO",
            tags=["pattern", "architecture"],
            adr_path="docs/adr/0014-mediator-pattern.md",
        )
        assert record.author == "Architect"
        assert record.approver == "CTO"
        assert record.reversal_strategy == "Revert to direct calls if latency increases"
        assert record.tradeoffs == "More indirection for better testability"
        assert "ARCHITECTURE" in record.impact_categories
        assert "pattern" in record.tags
        assert record.adr_path.startswith("docs/adr/")

    def test_record_decision_with_custom_status(self):
        mem = get_decision_memory()
        record = mem.record_decision(
            title="Draft decision",
            context="Under discussion",
            decision="TBD",
            status="DRAFT",
            priority="LOW",
        )
        assert record.status == "DRAFT"
        assert record.priority == "LOW"

    def test_invalid_status_defaults_to_accepted(self):
        mem = get_decision_memory()
        record = mem.record_decision(title="Test", context="Test", decision="Test", status="INVALID_STATUS")
        assert record.status == "ACCEPTED"

    def test_record_multiple_decisions(self):
        mem = get_decision_memory()
        r1 = mem.record_decision("First", "Context 1", "Decision 1")
        r2 = mem.record_decision("Second", "Context 2", "Decision 2")
        r3 = mem.record_decision("Third", "Context 3", "Decision 3")
        assert r1.decision_id != r2.decision_id
        assert r2.decision_id != r3.decision_id
        assert mem.get_stats()["total_decisions"] == 3


# =============================================================================
# Approval & Reversal Tests
# =============================================================================


class TestApprovalAndReversal:
    def test_record_approval(self):
        mem = get_decision_memory()
        record = mem.record_decision("Test", "Ctx", "Dec", status="PROPOSED")
        assert record.approver == ""

        result = mem.record_approval(record.decision_id, "CTO")
        assert result is True

        updated = mem.get_decision(record.decision_id)
        assert updated is not None
        assert updated.approver == "CTO"
        assert updated.status == "ACCEPTED"
        assert updated.approval_date > 0

    def test_record_approval_not_found(self):
        mem = get_decision_memory()
        assert mem.record_approval("DEC-NONEXISTENT", "CTO") is False

    def test_reversal_strategy_persisted(self):
        mem = get_decision_memory()
        record = mem.record_decision(
            title="Use Redis Cache",
            context="Need faster response times",
            decision="Adopt Redis with persistence",
            reversal_strategy="Fall back to in-memory cache, flush Redis data",
        )
        retrieved = mem.get_decision(record.decision_id)
        assert retrieved is not None
        assert retrieved.reversal_strategy == "Fall back to in-memory cache, flush Redis data"

    def test_superseded_auto_mark(self):
        mem = get_decision_memory()
        r1 = mem.record_decision("Old Approach", "Ctx", "Old dec")
        assert mem.update_status(r1.decision_id, "SUPERSEDED") is True
        updated = mem.get_decision(r1.decision_id)
        assert updated is not None
        assert updated.status == "SUPERSEDED"
        assert updated.superseded_by != ""


# =============================================================================
# Q&A Engine Tests
# =============================================================================


class TestQAEngine:
    def test_ask_why_question(self):
        mem = get_decision_memory()
        mem.record_decision(
            title="PostgreSQL Database",
            context="Need a production database with ACID compliance",
            decision="Use PostgreSQL over MySQL",
            rationale="PostgreSQL has better transactional guarantees and mature Python support",
            alternatives=["MySQL", "SQLite"],
            impact_categories=["ARCHITECTURE"],
            tags=["database"],
        )
        answer = mem.ask_question("Why did we choose PostgreSQL?")
        assert answer.confidence > 0.3
        assert answer.intent == "why"
        assert "PostgreSQL" in answer.answer or "postgresql" in answer.answer.lower()
        assert answer.source_title == "PostgreSQL Database"

    def test_ask_alternatives_question(self):
        mem = get_decision_memory()
        mem.record_decision(
            title="Cache Solution",
            context="Need caching layer",
            decision="Use Redis",
            rationale="Redis is fastest and most flexible",
            alternatives=["Memcached", "Varnish", "Local in-memory"],
            tags=["cache"],
        )
        answer = mem.ask_question("What alternatives were considered for caching?")
        assert answer.intent == "alternatives" or answer.intent == "what"
        assert "Memcached" in answer.answer or "Redis" in answer.answer

    def test_ask_status_question(self):
        mem = get_decision_memory()
        mem.record_decision(
            title="Microservices Migration",
            context="Monolith needs splitting",
            decision="Incremental migration to services",
            status="DRAFT",
            tags=["architecture"],
        )
        answer = mem.ask_question("What is the status of the microservices migration?")
        assert answer.intent in ("status", "what")
        assert answer.confidence > 0
        assert answer.source_title == "Microservices Migration"

    def test_ask_reversal_question(self):
        mem = get_decision_memory()
        mem.record_decision(
            title="Move to Event Sourcing",
            context="Need audit trail for all state changes",
            decision="Adopt Event Sourcing pattern",
            reversal_strategy="Revert to state-based persistence; rebuild snapshots from event log",
            rationale="Complete audit trail requirement",
        )
        answer = mem.ask_question("How do we reverse the event sourcing decision?")
        assert answer.intent in ("reversal", "why")
        assert "reversal" in answer.answer.lower() or "revert" in answer.answer.lower()

    def test_ask_impact_question(self):
        mem = get_decision_memory()
        mem.record_decision(
            title="Vue.js Frontend Framework",
            context="Need new frontend framework",
            decision="Use Vue.js 3 with Composition API",
            rationale="Best developer experience and ecosystem fit",
            consequences=["Learning curve for team", "Faster development iteration", "Better TypeScript support"],
            impact_categories=["ARCHITECTURE", "MAINTAINABILITY"],
            module_paths=["frontend/src/"],
        )
        answer = mem.ask_question("What is the impact of using Vue.js?")
        assert answer.confidence > 0
        assert "consequences" in answer.answer.lower() or "impact" in answer.answer.lower() or "Vue" in answer.answer

    def test_ask_no_match_returns_low_confidence(self):
        mem = get_decision_memory()
        mem.record_decision(
            title="Database Choice",
            context="Production DB",
            decision="PostgreSQL",
            tags=["database"],
        )
        answer = mem.ask_question("What is the company holiday schedule?")
        # Recency bonus gives ~0.1 confidence even with no keyword match
        assert answer.confidence < 0.3, f"Expected low confidence, got {answer.confidence}"
        assert "No decisions" in answer.answer

    def test_ask_question_empty_memory_returns_no_match(self):
        mem = get_decision_memory()
        answer = mem.ask_question("Why did we choose PostgreSQL?")
        assert answer.confidence == 0.0
        assert "couldn't find" in answer.answer.lower()

    def test_ask_who_question(self):
        mem = get_decision_memory()
        mem.record_decision(
            title="Auth System Design",
            context="Need authentication",
            decision="Use OAuth 2.0 with JWT",
            author="Gaurav",
            approver="SecurityTeam",
        )
        answer = mem.ask_question("Who made the auth system decision?")
        assert answer.intent in ("who", "approval")
        assert "Gaurav" in answer.answer or "auth" in answer.answer.lower()

    def test_ask_question_confidence_scaling(self):
        """Verify that well-matched questions get higher confidence."""
        mem = get_decision_memory()
        mem.record_decision(
            title="Database: PostgreSQL in Production",
            context="Production DB choice with complex migration needs",
            decision="Adopt PostgreSQL with connection pooling, replication, and automated backups",
            rationale="PostgreSQL has better ACID compliance, replication support, and Python ecosystem",
            reversal_strategy="Migrate back to SQLite with WAL mode; export all data via pg_dump",
            alternatives=["MySQL 8.0", "MariaDB", "SQLite WAL", "MongoDB"],
            consequences=["Need DB migration script", "Connection pool tuning", "Backup automation"],
            tags=["database", "production", "critical"],
        )
        # A well-formed question about a well-documented decision = high confidence
        answer = mem.ask_question("Why did we choose PostgreSQL for our production database?")
        assert answer.confidence > 0.3
        assert answer.source_decision_id != ""

    def test_ask_question_no_decision_returned(self):
        mem = get_decision_memory()
        answer = mem.ask_question("Why did we pick the color scheme?")
        assert answer.confidence == 0.0
        assert answer.answer != ""


# =============================================================================
# Timeline Tests
# =============================================================================


class TestTimeline:
    def test_get_timeline_empty(self):
        mem = get_decision_memory()
        entries = mem.get_timeline()
        assert entries == []

    def test_get_timeline_with_decisions(self):
        mem = get_decision_memory()
        mem.record_decision("First Decision", "Ctx", "Dec")
        mem.record_decision("Second Decision", "Ctx", "Dec")
        entries = mem.get_timeline()
        assert len(entries) >= 2
        assert entries[0].event == "CREATED"

    def test_get_timeline_with_approval(self):
        mem = get_decision_memory()
        rec = mem.record_decision("Approved Decision", "Ctx", "Dec", status="PROPOSED", author="Dev")
        mem.record_approval(rec.decision_id, "CTO")
        entries = mem.get_timeline()
        events = [e.event for e in entries]
        assert "CREATED" in events
        assert "APPROVED" in events

    def test_timeline_entry_to_dict(self):
        entry = DecisionTimelineEntry(
            date="2026-07-29",
            decision_id="DEC-123",
            title="Test Decision",
            event="CREATED",
            detail="Priority: HIGH",
        )
        d = entry.to_dict()
        assert d["date"] == "2026-07-29"
        assert d["decision_id"] == "DEC-123"
        assert d["event"] == "CREATED"


# =============================================================================
# Retrieval Tests
# =============================================================================


class TestDecisionRetrieval:
    def test_get_decision_by_id(self):
        mem = get_decision_memory()
        record = mem.record_decision("Test", "Context", "Decision")
        retrieved = mem.get_decision(record.decision_id)
        assert retrieved is not None
        assert retrieved.decision_id == record.decision_id
        assert retrieved.title == "Test"

    def test_get_decision_not_found(self):
        mem = get_decision_memory()
        assert mem.get_decision("DEC-NONEXISTENT") is None

    def test_search_by_keyword(self):
        mem = get_decision_memory()
        mem.record_decision("PostgreSQL Database", "DB choice", "Use PostgreSQL")
        mem.record_decision("Redis Cache", "Cache choice", "Use Redis")
        results = mem.search(query="database")
        assert len(results) >= 1
        assert any("database" in r.title.lower() or "database" in r.excerpt.lower() for r in results)

    def test_search_by_multiple_keywords(self):
        mem = get_decision_memory()
        mem.record_decision("PostgreSQL Database", "DB for production", "Use PostgreSQL")
        mem.record_decision("Authentication Design", "Auth approach", "Use JWT tokens")
        results = mem.search(query="postgresql database")
        assert len(results) >= 1

    def test_search_empty_query_returns_all(self):
        mem = get_decision_memory()
        mem.record_decision("Decision A", "Ctx A", "Dec A")
        mem.record_decision("Decision B", "Ctx B", "Dec B")
        results = mem.search()
        assert len(results) == 2

    def test_search_filter_by_status(self):
        mem = get_decision_memory()
        mem.record_decision("Accepted", "Ctx", "Dec", status="ACCEPTED")
        mem.record_decision("Proposed", "Ctx", "Dec", status="PROPOSED")
        accepted = mem.search(status="ACCEPTED")
        proposed = mem.search(status="PROPOSED")
        assert len(accepted) >= 1
        assert len(proposed) >= 1

    def test_search_no_results(self):
        mem = get_decision_memory()
        mem.record_decision("Test", "Ctx", "Dec")
        results = mem.search(query="nonexistent_keyword_xyz")
        assert len(results) == 0


# =============================================================================
# Status Update Tests
# =============================================================================


class TestStatusUpdate:
    def test_update_status_valid(self):
        mem = get_decision_memory()
        record = mem.record_decision("Test", "Ctx", "Dec", status="DRAFT")
        assert mem.update_status(record.decision_id, "ACCEPTED") is True
        updated = mem.get_decision(record.decision_id)
        assert updated is not None
        assert updated.status == "ACCEPTED"

    def test_update_status_invalid(self):
        mem = get_decision_memory()
        record = mem.record_decision("Test", "Ctx", "Dec", status="DRAFT")
        assert mem.update_status(record.decision_id, "INVALID") is False
        updated = mem.get_decision(record.decision_id)
        assert updated is not None
        assert updated.status == "DRAFT"

    def test_update_status_not_found(self):
        mem = get_decision_memory()
        assert mem.update_status("DEC-NONEXISTENT", "ACCEPTED") is False


# =============================================================================
# Module & Tag Filtering Tests
# =============================================================================


class TestFiltering:
    def test_get_decisions_by_module(self):
        mem = get_decision_memory()
        mem.record_decision("DB Decision", "Ctx", "Dec", module_paths=["core/adapters/database/postgres_adapter.py"])
        mem.record_decision("Broker Decision", "Ctx", "Dec", module_paths=["core/adapters/broker/kite.py"])
        results = mem.get_decisions_by_module("database")
        assert len(results) >= 1
        assert mem.get_decisions_by_module("nonexistent") == []

    def test_get_decisions_by_tag(self):
        mem = get_decision_memory()
        mem.record_decision("Security Decision", "Ctx", "Dec", tags=["security", "auth"])
        mem.record_decision("Perf Decision", "Ctx", "Dec", tags=["performance"])
        results = mem.get_decisions_by_tag("security")
        assert len(results) >= 1
        assert mem.get_decisions_by_tag("nonexistent") == []

    def test_get_dependent_decisions(self):
        mem = get_decision_memory()
        r1 = mem.record_decision("Base Decision", "Ctx", "Dec")
        mem.record_decision("Dependent Decision", "Ctx", "Dec", related_decisions=[r1.decision_id])
        dependents = mem.get_dependent_decisions(r1.decision_id)
        assert len(dependents) >= 1
        assert dependents[0].title == "Dependent Decision"


# =============================================================================
# Related Decisions & Dependency Graph Tests
# =============================================================================


class TestDependencies:
    def test_get_related_decisions(self):
        mem = get_decision_memory()
        r1 = mem.record_decision("Base", "Ctx", "Dec")
        r2 = mem.record_decision("Related", "Ctx", "Dec", related_decisions=[r1.decision_id])
        related = mem.get_related_decisions(r2.decision_id)
        assert len(related) >= 1
        assert related[0].decision_id == r1.decision_id

    def test_no_related_decisions(self):
        mem = get_decision_memory()
        r = mem.record_decision("Alone", "Ctx", "Dec")
        assert mem.get_related_decisions(r.decision_id) == []

    def test_get_related_not_found(self):
        mem = get_decision_memory()
        assert mem.get_related_decisions("DEC-NONEXISTENT") == []

    def test_get_decision_graph(self):
        mem = get_decision_memory()
        r1 = mem.record_decision("Base", "Ctx", "Dec")
        r2 = mem.record_decision("Dependent", "Ctx", "Dec", related_decisions=[r1.decision_id])
        graph = mem.get_decision_graph()
        assert "nodes" in graph
        assert "edges" in graph
        assert len(graph["nodes"]) >= 2
        assert any(e["from"] == r2.decision_id and e["to"] == r1.decision_id for e in graph["edges"])


# =============================================================================
# Report & Stats Tests
# =============================================================================


class TestReportAndStats:
    def test_get_stats_initial(self):
        mem = get_decision_memory()
        stats = mem.get_stats()
        assert stats["total_decisions"] == 0

    def test_get_stats_after_recording(self):
        mem = get_decision_memory()
        mem.record_decision("A", "Ctx", "Dec")
        mem.record_decision("B", "Ctx", "Dec", tags=["important"])
        mem.record_decision("C", "Ctx", "Dec", status="DRAFT")
        stats = mem.get_stats()
        assert stats["total_decisions"] == 3
        assert stats["by_status"]["ACCEPTED"] == 2
        assert stats["by_status"]["DRAFT"] == 1
        assert stats["unique_tags"] >= 1

    def test_get_stats_with_tracking_fields(self):
        mem = get_decision_memory()
        mem.record_decision("A", "Ctx", "Dec", reversal_strategy="Rollback plan")
        mem.record_decision("B", "Ctx", "Dec", approver="CTO", tradeoffs="Speed vs accuracy")
        stats = mem.get_stats()
        assert stats["decisions_with_reversal"] >= 1
        assert stats["decisions_with_approval"] >= 1
        assert stats["decisions_with_tradeoffs"] >= 1

    def test_get_report(self):
        mem = get_decision_memory()
        mem.record_decision("Choose DB", "Production DB", "PostgreSQL", impact_categories=["ARCHITECTURE", "PERFORMANCE"])
        mem.record_decision("Auth Design", "Auth system", "JWT", impact_categories=["SECURITY"])
        report = mem.get_report()
        assert report.total_decisions == 2
        assert "ARCHITECTURE" in report.by_impact
        assert "SECURITY" in report.by_impact
        assert len(report.recent_decisions) == 2

    def test_report_summary_text(self):
        r = DecisionMemoryReport(
            total_decisions=10,
            by_status={"ACCEPTED": 7, "PROPOSED": 2, "DRAFT": 1},
            by_impact={"ARCHITECTURE": 5, "SECURITY": 3},
            decision_velocity_per_week=2.5,
            acceptance_rate=0.7,
        )
        text = r.summary_text()
        assert "DECISION MEMORY" in text
        assert "ACCEPTED: 7" in text
        assert "ARCHITECTURE" in text

    def test_clear_all(self):
        mem = get_decision_memory()
        mem.record_decision("Test", "Ctx", "Dec")
        assert mem.get_stats()["total_decisions"] == 1
        mem.clear_all()
        assert mem.get_stats()["total_decisions"] == 0

    def test_decision_record_to_dict(self):
        record = DecisionRecord(
            decision_id="DEC-123",
            title="Test Decision",
            status="ACCEPTED",
            priority="HIGH",
            reversal_strategy="Revert if needed",
            approver="CTO",
        )
        d = record.to_dict()
        assert d["decision_id"] == "DEC-123"
        assert d["status"] == "ACCEPTED"
        assert d["priority"] == "HIGH"
        assert d["reversal_strategy"] == "Revert if needed"
        assert d["approver"] == "CTO"

    def test_decision_search_result_to_dict(self):
        r = DecisionSearchResult(decision_id="DEC-123", title="Test", score=0.95, matched_keywords=["database"])
        d = r.to_dict()
        assert d["score"] == 0.95
        assert "database" in d["matched_keywords"]

    def test_question_answer_to_dict(self):
        qa = QuestionAnswer(
            question="Why PostgreSQL?",
            answer="Because ACID compliance",
            confidence=0.85,
            intent="why",
            source_decision_id="DEC-123",
            source_title="DB Choice",
            matched_terms=["postgresql"],
        )
        d = qa.to_dict()
        assert d["confidence"] == 0.85
        assert d["intent"] == "why"
        assert d["source_title"] == "DB Choice"

    def test_question_answer_summary_text(self):
        qa = QuestionAnswer(
            question="Why PostgreSQL?",
            answer="Because ACID compliance",
            confidence=0.85,
            source_title="DB Choice",
        )
        text = qa.summary_text()
        assert "Q: Why PostgreSQL?" in text
        assert "A: Because ACID compliance" in text
        assert "85%" in text


# =============================================================================
# ADR Import Tests
# =============================================================================


class TestADRImport:
    """Tests for ADR auto-import functionality."""

    def test_import_adr(self, tmp_path):
        mem = get_decision_memory()
        adr_file = tmp_path / "0001-test-decision.md"
        adr_file.write_text("""# ADR 0001: Test Decision

## Status
Accepted

## Date
2026-01-15

## Context
We need to make an important architectural decision.

## Decision
Adopt the test approach for all new modules.

## Consequences
- Better test coverage
- Slightly more development time
""", encoding="utf-8")

        record = mem.import_adr(str(adr_file))
        assert record is not None
        assert record.title == "ADR 0001: Test Decision"
        assert record.status == "ACCEPTED"
        assert "test approach" in record.decision
        assert record.adr_path == str(adr_file)
        assert "adr" in record.tags
        assert len(record.consequences) >= 1

    def test_import_adr_file_not_found(self):
        mem = get_decision_memory()
        record = mem.import_adr("nonexistent.md")
        assert record is None

    def test_import_adr_proposed_status(self, tmp_path):
        mem = get_decision_memory()
        adr_file = tmp_path / "0002-proposed.md"
        adr_file.write_text("""# ADR 0002: Proposed Change

## Status
Proposed

## Date
2026-03-01

## Context
Considering a change.

## Decision
Proceed with phased rollout.

## Consequences
- Requires migration
""", encoding="utf-8")

        record = mem.import_adr(str(adr_file))
        assert record is not None
        assert record.status == "PROPOSED"

    def test_import_adr_superseded_status(self, tmp_path):
        mem = get_decision_memory()
        adr_file = tmp_path / "0003-superseded.md"
        adr_file.write_text("""# ADR 0003: Old Approach

## Status
Superseded

## Date
2025-06-01

## Context
Old approach no longer valid.

## Decision
This approach has been replaced.

## Consequences
- Use new approach instead
""", encoding="utf-8")

        record = mem.import_adr(str(adr_file))
        assert record is not None
        assert record.status == "SUPERSEDED"

    def test_scan_adr_directory(self, tmp_path):
        mem = get_decision_memory()
        # Create several ADR files
        for i in range(3):
            adr = tmp_path / f"00{i+1}-test-{i}.md"
            adr.write_text(f"""# ADR 00{i+1}: Test Decision {i}

## Status
Accepted

## Date
2026-01-{i+1:02d}

## Context
Context for decision {i}.

## Decision
Decision content {i}.

## Consequences
- Consequence {i}
""", encoding="utf-8")

        imported = mem.scan_adr_directory(str(tmp_path))
        assert len(imported) == 3
        # Verify all three were imported
        stats = mem.get_stats()
        assert stats["total_decisions"] == 3

    def test_scan_adr_directory_skips_readme(self, tmp_path):
        mem = get_decision_memory()
        readme = tmp_path / "README.md"
        readme.write_text("# README\n\nNot an ADR", encoding="utf-8")
        adr = tmp_path / "0001-real.md"
        adr.write_text("""# ADR 0001: Real\n\n## Status\nAccepted\n\n## Date\n2026-01-01\n\n## Context\nCtx.\n\n## Decision\nDec.\n\n## Consequences\n- Cons\n""", encoding="utf-8")

        imported = mem.scan_adr_directory(str(tmp_path))
        assert len(imported) == 1
        assert imported[0].title == "ADR 0001: Real"

    def test_scan_adr_directory_skips_duplicates(self, tmp_path):
        mem = get_decision_memory()
        adr = tmp_path / "0001-dup.md"
        adr.write_text("""# ADR 0001: Unique\n\n## Status\nAccepted\n\n## Date\n2026-01-01\n\n## Context\nC.\n\n## Decision\nD.\n\n## Consequences\n- C\n""", encoding="utf-8")

        first = mem.scan_adr_directory(str(tmp_path))
        assert len(first) == 1
        # Second scan should skip duplicates (matched by adr_path)
        second = mem.scan_adr_directory(str(tmp_path))
        assert len(second) == 0

    def test_scan_adr_directory_not_found(self):
        mem = get_decision_memory()
        imported = mem.scan_adr_directory("nonexistent_dir")
        assert imported == []

    def test_extract_adr_section(self, tmp_path):
        """Test the _extract_adr_section static method directly."""
        text = """# ADR

## Status
Accepted

## Context
Some context here.

## Decision
The decision text.

## Consequences
- Cons 1
- Cons 2
"""
        ctx = DecisionMemory._extract_adr_section(text, "Context")
        assert "Some context here." in ctx

        dec = DecisionMemory._extract_adr_section(text, "Decision")
        assert "decision text" in dec

        cons = DecisionMemory._extract_adr_section(text, "Consequences")
        assert "Cons 1" in cons and "Cons 2" in cons

        # Missing section returns empty string
        missing = DecisionMemory._extract_adr_section(text, "References")
        assert missing == ""


# =============================================================================
# DecisionRecord Summary Tests
# =============================================================================


class TestDecisionRecord:
    def test_summary_text_with_reversal_and_approval(self):
        record = DecisionRecord(
            decision_id="DEC-123",
            title="Use Redis Cache",
            status="ACCEPTED",
            decision="Adopt Redis with persistence",
            rationale="Redis is fastest",
            impact_categories=["PERFORMANCE"],
            reversal_strategy="Fall back to in-memory cache",
            approver="CTO",
            created_at=time.time(),
        )
        text = record.summary_text()
        assert "Reversal:" in text
        assert "Approved by: CTO" in text

    def test_qa_text_includes_all_fields(self):
        record = DecisionRecord(
            decision_id="DEC-123",
            title="DB Choice",
            context="Need a DB",
            decision="PostgreSQL",
            rationale="ACID",
            tradeoffs="Complexity vs consistency",
            reversal_strategy="Migrate back",
            approver="Architect",
            alternatives=["MySQL", "SQLite"],
            consequences=["Migration needed"],
            module_paths=["core/db.py"],
            tags=["database"],
        )
        text = record.qa_text()
        assert "Title: DB Choice" in text
        assert "Alternatives considered: MySQL; SQLite" in text
        assert "Reversal strategy: Migrate back" in text
        assert "Approved by: Architect" in text
        assert "Modules affected: core/db.py" in text


# =============================================================================
# Decision Comparison Tests
# =============================================================================


class TestDecisionComparison:
    def test_compare_two_decisions(self):
        mem = get_decision_memory()
        r1 = mem.record_decision("Use PostgreSQL", "DB choice", "PostgreSQL",
                                 status="ACCEPTED", priority="HIGH",
                                 impact_categories=["ARCHITECTURE", "PERFORMANCE"],
                                 module_paths=["core/db.py"],
                                 tags=["database"])
        r2 = mem.record_decision("Use Redis", "Cache choice", "Redis",
                                 status="ACCEPTED", priority="MEDIUM",
                                 impact_categories=["PERFORMANCE", "COST"],
                                 module_paths=["core/cache.py"],
                                 tags=["cache"])
        comparison = mem.compare_decisions(r1.decision_id, r2.decision_id)
        assert "decision_1" in comparison
        assert "decision_2" in comparison
        assert "differences" in comparison
        assert comparison["differences"]["same_status"] is True
        assert comparison["differences"]["same_priority"] is False
        assert "PERFORMANCE" in comparison["differences"]["shared_impact_categories"]

    def test_compare_decision_not_found(self):
        mem = get_decision_memory()
        result = mem.compare_decisions("DEC-NONEXISTENT-1", "DEC-NONEXISTENT-2")
        assert "error" in result


# =============================================================================
# Export/Import Tests
# =============================================================================


class TestExportImport:
    def test_export_decisions(self, tmp_path):
        mem = get_decision_memory()
        mem.record_decision("Decision A", "Ctx A", "Dec A", tags=["alpha"])
        mem.record_decision("Decision B", "Ctx B", "Dec B", tags=["beta"])
        export_path = tmp_path / "export.json"
        count = mem.export_decisions(output_path=str(export_path))
        assert count == 2
        assert export_path.exists()
        data = json.loads(export_path.read_text())
        assert data["total"] == 2

    def test_export_with_status_filter(self, tmp_path):
        mem = get_decision_memory()
        mem.record_decision("Accepted", "Ctx", "Dec", status="ACCEPTED")
        mem.record_decision("Proposed", "Ctx", "Dec", status="PROPOSED")
        export_path = tmp_path / "filtered.json"
        count = mem.export_decisions(output_path=str(export_path), status_filter="ACCEPTED")
        assert count == 1

    def test_import_decisions(self, tmp_path):
        mem = get_decision_memory()
        export_path = tmp_path / "to_import.json"
        mem.record_decision("Original", "Ctx", "Dec")
        count = mem.export_decisions(output_path=str(export_path))
        assert count == 1
        mem.clear_all()
        assert mem.get_stats()["total_decisions"] == 0
        imported = mem.import_decisions(input_path=str(export_path))
        assert imported == 1
        assert mem.get_stats()["total_decisions"] == 1

    def test_import_file_not_found(self):
        mem = get_decision_memory()
        imported = mem.import_decisions("nonexistent.json")
        assert imported == 0


# =============================================================================
# Timeline by Date Tests
# =============================================================================


class TestTimelineByDate:
    def test_timeline_by_date_empty(self):
        mem = get_decision_memory()
        entries = mem.get_timeline_by_date("2020-01-01", "2020-12-31")
        assert entries == []

    def test_timeline_by_date_filters(self):
        mem = get_decision_memory()
        mem.record_decision("Recent", "Ctx", "Dec")
        entries = mem.get_timeline_by_date("2020-01-01", "2099-12-31")
        assert len(entries) >= 1
        entries_future = mem.get_timeline_by_date("2099-01-01", "2099-12-31")
        assert entries_future == []


# =============================================================================
# Similarity Search Tests
# =============================================================================


class TestSimilarity:
    def test_find_similar_returns_matches(self):
        mem = get_decision_memory()
        r1 = mem.record_decision("Database: PostgreSQL", "DB for production", "PostgreSQL",
                                 impact_categories=["ARCHITECTURE", "PERFORMANCE"],
                                 tags=["database", "storage"],
                                 module_paths=["core/db.py"])
        mem.record_decision("Database: MySQL", "Alternative DB", "MySQL",
                            impact_categories=["ARCHITECTURE", "PERFORMANCE"],
                            tags=["database", "storage"],
                            module_paths=["core/db.py"])
        mem.record_decision("Auth System", "Auth choice", "JWT",
                            impact_categories=["SECURITY"],
                            tags=["security"])
        similar = mem.find_similar(r1.decision_id)
        assert len(similar) >= 1
        assert similar[0]["similarity_score"] > 0

    def test_find_similar_not_found(self):
        mem = get_decision_memory()
        result = mem.find_similar("DEC-NONEXISTENT")
        assert result == []

    def test_find_similar_no_matches(self):
        mem = get_decision_memory()
        r1 = mem.record_decision("Sole Decision", "Ctx", "Dec")
        result = mem.find_similar(r1.decision_id)
        assert result == []
