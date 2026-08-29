"""Decision Memory — Enterprise Decision Memory & Retrieval (Constitution v4.0).

Provides structured capture, storage, and retrieval of engineering decisions:
- ADR-aware decision recording
- Semantic search over decision history
- Q&A engine: ask "Why did we choose PostgreSQL?" and get the answer
- Decision reversal strategy tracking
- Approval workflow recording
- Impact tracking (which decisions affected which modules)
- Decision lifecycle management (DRAFT -> PROPOSED -> ACCEPTED -> DEPRECATED -> SUPERSEDED)
- Trend analysis (decision velocity, quality, coverage)
- Knowledge Base integration (decisions auto-fed to KB)

Integrates with:
- DecisionAnalyzer for decision scoring & ROI estimation
- KnowledgeBase for cross-domain pattern learning
- RootCauseAnalyzer for incident-decision correlation
- BIDashboard for decision quality trending
- LivingDocumentation for automated doc generation

Usage:
    from core.decision_memory import get_decision_memory

    memory = get_decision_memory()
    memory.record_decision(
        title="Use PostgreSQL for production database",
        context="SQLite handles development but lacks concurrency for production",
        decision="Adopt PostgreSQL with connection pooling",
        alternatives=["MySQL", "SQLite with WAL mode", "MongoDB"],
        rationale="PostgreSQL has best transactional guarantees and mature Python support",
        consequences=["Migration script needed", "Connection pool tuning required"],
        module_paths=["core/adapters/database/postgres_adapter.py"],
        reversal_strategy="Migrate back to SQLite with WAL mode if performance < 80% of SQLite",
    )
    # Q&A
    answer = memory.ask_question("Why did we choose PostgreSQL?")
    print(answer.answer)
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.datetime_ist import IST_OFFSET

IST_TZ = timezone(IST_OFFSET)
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

VALID_STATUSES = ("DRAFT", "PROPOSED", "ACCEPTED", "DEPRECATED", "SUPERSEDED", "REJECTED")
DEFAULT_STATUS = "ACCEPTED"

IMPACT_CATEGORIES = (
    "ARCHITECTURE",
    "SECURITY",
    "PERFORMANCE",
    "RELIABILITY",
    "MAINTAINABILITY",
    "SCALABILITY",
    "COST",
    "COMPLIANCE",
)

PRIORITY_WEIGHTS = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}

# Common question intents for the Q&A engine
_QUESTION_PATTERNS: dict[str, list[str]] = {
    "why": [
        r"why (did|was|is|are|were) ",
        r"reason for ",
        r"rationale behind ",
        r"what.*rationale",
    ],
    "what": [
        r"what (was|is|are|were) ",
        r"what decision",
        r"tell me about ",
    ],
    "alternatives": [
        r"alternatives?",
        r"other option",
        r"what else",
        r"why not ",
    ],
    "impact": [
        r"impact",
        r"consequence",
        r"affected",
        r"what changed",
        r"side effect",
    ],
    "status": [
        r"status of ",
        r"is .* (accepted|approved|rejected|deprecated)",
        r"what.*status",
    ],
    "reversal": [
        r"revers",
        r"rollback",
        r"undo",
        r"revert",
        r"back out",
    ],
    "when": [
        r"when (was|is|did) ",
        r"date of ",
    ],
    "who": [
        r"who (made|decided|approved|authored)",
        r"author of ",
        r"decided by",
    ],
    "approval": [
        r"approv",
        r"who approved",
        r"signed off",
        r"reviewer",
    ],
    "dependencies": [
        r"depends? on",
        r"relat(ed|ion)",
        r"prerequisite",
        r"blocks?",
    ],
}


# ── Data Models ────────────────────────────────────────────────────────────


@dataclass
class DecisionRecord:
    """A single engineering decision.

    Extended with reversal_strategy, approver, approval_date, and tradeoffs
    to support full Enterprise Decision Memory (Vision Level 4).
    """

    decision_id: str = ""
    title: str = ""
    status: str = DEFAULT_STATUS
    priority: str = "MEDIUM"
    context: str = ""
    decision: str = ""
    alternatives: list[str] = field(default_factory=list)
    rationale: str = ""
    tradeoffs: str = ""  # NEW: explicit trade-offs description
    consequences: list[str] = field(default_factory=list)
    reversal_strategy: str = ""  # NEW: how to reverse this decision
    module_paths: list[str] = field(default_factory=list)
    impact_categories: list[str] = field(default_factory=list)
    adr_path: str = ""
    author: str = ""
    approver: str = ""  # NEW: who approved this decision
    approval_date: float = 0.0  # NEW: when it was approved
    tags: list[str] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0
    superseded_by: str = ""
    related_decisions: list[str] = field(default_factory=list)  # dependencies

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "title": self.title,
            "status": self.status,
            "priority": self.priority,
            "context": self.context[:200],
            "decision": self.decision[:200],
            "alternatives": self.alternatives,
            "rationale": self.rationale[:200],
            "tradeoffs": self.tradeoffs[:200],
            "consequences": self.consequences,
            "reversal_strategy": self.reversal_strategy[:200],
            "module_paths": self.module_paths,
            "impact_categories": self.impact_categories,
            "adr_path": self.adr_path,
            "author": self.author,
            "approver": self.approver,
            "approval_date": self.approval_date,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "superseded_by": self.superseded_by,
            "related_decisions": self.related_decisions,
            "age_days": round((time.time() - self.created_at) / 86400, 1) if self.created_at else 0,
        }

    def summary_text(self) -> str:
        date_str = datetime.fromtimestamp(self.created_at).strftime("%Y-%m-%d") if self.created_at else "?"
        lines = [
            f"[{self.status}] {self.title} ({date_str})",
            f"  Decision: {self.decision[:100]}",
            f"  Rationale: {self.rationale[:100]}",
            f"  Impact: {', '.join(self.impact_categories) if self.impact_categories else 'None listed'}",
        ]
        if self.reversal_strategy:
            lines.append(f"  Reversal: {self.reversal_strategy[:100]}")
        if self.approver:
            lines.append(f"  Approved by: {self.approver}")
        return "\n".join(lines)

    def qa_text(self) -> str:
        """Full text for Q&A processing — combines all searchable fields."""
        parts = [
            f"Title: {self.title}",
            f"Status: {self.status}",
            f"Priority: {self.priority}",
            f"Context: {self.context}",
            f"Decision: {self.decision}",
            f"Rationale: {self.rationale}",
        ]
        if self.tradeoffs:
            parts.append(f"Trade-offs: {self.tradeoffs}")
        if self.alternatives:
            parts.append(f"Alternatives considered: {'; '.join(self.alternatives)}")
        if self.consequences:
            parts.append(f"Consequences: {'; '.join(self.consequences)}")
        if self.reversal_strategy:
            parts.append(f"Reversal strategy: {self.reversal_strategy}")
        if self.approver:
            parts.append(f"Approved by: {self.approver}")
        if self.module_paths:
            parts.append(f"Modules affected: {'; '.join(self.module_paths)}")
        if self.tags:
            parts.append(f"Tags: {', '.join(self.tags)}")
        return " | ".join(parts)


@dataclass
class DecisionSearchResult:
    """A search result from the decision memory."""

    decision_id: str = ""
    title: str = ""
    score: float = 0.0
    matched_keywords: list[str] = field(default_factory=list)
    excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "title": self.title,
            "score": round(self.score, 3),
            "matched_keywords": self.matched_keywords,
            "excerpt": self.excerpt[:200],
        }


@dataclass
class QuestionAnswer:
    """A natural language Q&A result from the decision memory.

    Answers questions like "Why did we choose PostgreSQL?" by finding
    the most relevant decision and extracting the answer from its fields.
    """

    question: str = ""
    answer: str = ""
    confidence: float = 0.0
    intent: str = ""  # why, what, alternatives, impact, status, reversal, when, who
    source_decision_id: str = ""
    source_title: str = ""
    matched_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer[:500],
            "confidence": round(self.confidence, 3),
            "intent": self.intent,
            "source_decision_id": self.source_decision_id,
            "source_title": self.source_title,
            "matched_terms": self.matched_terms,
        }

    def summary_text(self) -> str:
        lines = [
            f"Q: {self.question}",
            f"A: {self.answer}",
            f"  (confidence: {self.confidence:.0%}, from: {self.source_title})",
        ]
        return "\n".join(lines)


@dataclass
class DecisionTimelineEntry:
    """A single entry in the decision timeline."""

    date: str = ""
    decision_id: str = ""
    title: str = ""
    event: str = ""  # CREATED, STATUS_CHANGED, APPROVED, SUPERSEDED
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "decision_id": self.decision_id,
            "title": self.title,
            "event": self.event,
            "detail": self.detail,
        }


@dataclass
class DecisionMemoryReport:
    """Aggregated decision memory report."""

    timestamp: float = 0.0
    total_decisions: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    by_impact: dict[str, int] = field(default_factory=dict)
    by_priority: dict[str, int] = field(default_factory=dict)
    recent_decisions: list[DecisionRecord] = field(default_factory=list)
    top_modules_by_decisions: list[dict[str, Any]] = field(default_factory=list)
    decision_velocity_per_week: float = 0.0
    acceptance_rate: float = 0.0
    avg_resolution_days: float = 0.0
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_decisions": self.total_decisions,
            "by_status": self.by_status,
            "by_impact": self.by_impact,
            "by_priority": self.by_priority,
            "recent_decisions": [d.to_dict() for d in self.recent_decisions[:10]],
            "top_modules_by_decisions": self.top_modules_by_decisions[:10],
            "decision_velocity_per_week": round(self.decision_velocity_per_week, 2),
            "acceptance_rate": round(self.acceptance_rate, 3),
            "avg_resolution_days": round(self.avg_resolution_days, 1),
            "recommendations": self.recommendations,
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  DECISION MEMORY REPORT",
            "═" * 60,
            f"  Total Decisions: {self.total_decisions}",
            f"  Velocity: {self.decision_velocity_per_week:.1f}/week",
            f"  Acceptance Rate: {self.acceptance_rate:.0%}",
            f"  Avg Resolution: {self.avg_resolution_days:.0f} days",
            "",
        ]
        if self.by_status:
            lines.append("  By Status:")
            for status, count in sorted(self.by_status.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"    {status}: {count}")
        if self.by_impact:
            lines.append("  By Impact Category:")
            for cat, count in sorted(self.by_impact.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"    {cat}: {count}")
        if self.recommendations:
            lines.append("  Recommendations:")
            for r in self.recommendations:
                lines.append(f"    -> {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Decision Memory ───────────────────────────────────────────────────────


class DecisionMemory:
    """Enterprise Decision Memory — Capture, Retrieval & Q&A.

    Stores engineering decisions with structured metadata for:
    - Full-text search over decision history
    - Q&A engine: ask natural language questions about past decisions
    - Impact analysis (which modules affected by which decisions)
    - Decision lifecycle management
    - Reversal strategy tracking
    - Approval workflow recording
    - Trend analytics (velocity, quality, coverage)

    Thread-safe. Persisted to JSON.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._decisions: list[DecisionRecord] = []
        self._max_decisions = 1000
        self._persist_path = Path("json/decision_memory.json")
        self._load_decisions()

    # ── Public API ────────────────────────────────────────────────────────

    def record_decision(
        self,
        title: str,
        context: str,
        decision: str,
        rationale: str = "",
        alternatives: list[str] | None = None,
        consequences: list[str] | None = None,
        reversal_strategy: str = "",
        tradeoffs: str = "",
        module_paths: list[str] | None = None,
        impact_categories: list[str] | None = None,
        priority: str = "MEDIUM",
        status: str = "ACCEPTED",
        author: str = "",
        approver: str = "",
        approval_date: float | None = None,
        tags: list[str] | None = None,
        adr_path: str = "",
        related_decisions: list[str] | None = None,
        created_at: float | None = None,
        feed_to_kb: bool = True,
    ) -> DecisionRecord:
        """Record a new engineering decision.

        Args:
            title: Short decision title.
            context: Background context for the decision.
            decision: The actual decision made.
            rationale: Why this decision was chosen over alternatives.
            alternatives: Other options that were considered.
            consequences: Expected consequences (positive and negative).
            reversal_strategy: How to reverse this decision if needed.
            tradeoffs: Explicit description of trade-offs made.
            module_paths: Affected module paths.
            impact_categories: Impact categories (ARCHITECTURE, SECURITY, etc.).
            priority: Priority level (LOW, MEDIUM, HIGH, CRITICAL).
            status: Decision lifecycle status.
            author: Person/system who made the decision.
            approver: Who approved this decision.
            approval_date: When the decision was approved (timestamp).
            tags: Freeform tags for search/filtering.
            adr_path: Path to ADR document if applicable.
            related_decisions: IDs of related decisions (dependencies).
            created_at: Optional override for creation timestamp (for ADR imports).
            feed_to_kb: If True, automatically feed to Knowledge Base.

        Returns:
            DecisionRecord with assigned decision_id.
        """
        now = created_at or time.time()
        record = DecisionRecord(
            decision_id=f"DEC-{int(now)}-{len(self._decisions) + 1}",
            title=title.strip(),
            status=status.upper() if status.upper() in VALID_STATUSES else DEFAULT_STATUS,
            priority=priority.upper() if priority.upper() in PRIORITY_WEIGHTS else "MEDIUM",
            context=context.strip(),
            decision=decision.strip(),
            rationale=rationale.strip(),
            tradeoffs=tradeoffs.strip(),
            reversal_strategy=reversal_strategy.strip(),
            alternatives=[a.strip() for a in (alternatives or [])],
            consequences=[c.strip() for c in (consequences or [])],
            module_paths=[m.strip() for m in (module_paths or [])],
            impact_categories=[c.upper() for c in (impact_categories or [])
                               if c.upper() in IMPACT_CATEGORIES],
            adr_path=adr_path.strip(),
            author=author.strip(),
            approver=approver.strip(),
            approval_date=approval_date or 0.0,
            tags=[t.strip().lower() for t in (tags or []) if t.strip()],
            created_at=now,
            updated_at=now,
            related_decisions=[r.strip() for r in (related_decisions or []) if r.strip()],
        )

        with self._lock:
            self._decisions.append(record)
            if len(self._decisions) > self._max_decisions:
                self._decisions = self._decisions[-self._max_decisions:]
            self._persist()

        _log.info("[DEC_MEM] Recorded decision '%s' (id=%s)", title, record.decision_id)

        # Optionally feed to Knowledge Base
        if feed_to_kb:
            self._feed_to_knowledge_base(record)

        return record

    def record_approval(
        self,
        decision_id: str,
        approver: str,
        approval_date: float | None = None,
    ) -> bool:
        """Record approval for a decision.

        Args:
            decision_id: The decision ID to approve.
            approver: Name/ID of the approving entity.
            approval_date: When approved (defaults to now).

        Returns:
            True if updated, False if not found.
        """
        with self._lock:
            for record in self._decisions:
                if record.decision_id == decision_id:
                    record.approver = approver.strip()
                    record.approval_date = approval_date or time.time()
                    record.updated_at = time.time()
                    if record.status == "PROPOSED":
                        record.status = "ACCEPTED"
                    self._persist()
                    _log.info("[DEC_MEM] Approved decision '%s' by %s", decision_id, approver)
                    return True
            return False

    def update_status(self, decision_id: str, new_status: str) -> bool:
        """Update the status of an existing decision.

        Args:
            decision_id: The decision ID to update.
            new_status: New status (DRAFT, PROPOSED, ACCEPTED, DEPRECATED, SUPERSEDED, REJECTED).

        Returns:
            True if updated, False if not found or invalid status.
        """
        clean_status = new_status.upper()
        if clean_status not in VALID_STATUSES:
            return False

        with self._lock:
            for record in self._decisions:
                if record.decision_id == decision_id:
                    old_status = record.status
                    record.status = clean_status
                    record.updated_at = time.time()
                    # If superseded, mark the superseding decision
                    if clean_status == "SUPERSEDED" and not record.superseded_by:
                        record.superseded_by = f"Auto-{int(time.time())}"
                    self._persist()
                    _log.info("[DEC_MEM] Decision '%s' status: %s -> %s",
                              decision_id, old_status, clean_status)
                    return True
            return False

    def get_decision(self, decision_id: str) -> DecisionRecord | None:
        """Get a specific decision by ID."""
        with self._lock:
            for d in self._decisions:
                if d.decision_id == decision_id:
                    return d
            return None

    # ── Q&A Engine ───────────────────────────────────────────────────────

    def ask_question(self, question: str) -> QuestionAnswer:
        """Ask a natural language question about past decisions.

        Analyzes the question intent, searches through all decisions,
        and returns a structured answer with confidence score.

        Args:
            question: Natural language question (e.g., "Why did we choose PostgreSQL?").

        Returns:
            QuestionAnswer with extracted answer.
        """
        q_lower = question.lower().strip()

        # Detect intent
        intent = self._detect_intent(q_lower)

        # Extract key terms from the question (skip stop words)
        stop_words = {
            "what", "why", "when", "where", "who", "how", "is", "was", "are",
            "were", "did", "does", "do", "the", "a", "an", "in", "on", "at",
            "to", "for", "of", "with", "by", "from", "we", "you", "they",
            "our", "your", "its", "their",
        }
        key_terms = [w for w in re.findall(r'\w+', q_lower) if w not in stop_words and len(w) > 2]

        # Score each decision against the question
        scored: list[tuple[DecisionRecord, float, list[str]]] = []
        with self._lock:
            decisions = list(self._decisions)

        for d in decisions:
            qa_text = d.qa_text().lower()
            score = 0.0
            matched: list[str] = []

            # Keyword matching (weighted by field)
            for term in key_terms:
                if term in qa_text:
                    count = qa_text.count(term)
                    score += count * 2.0

                    # Bonus for title matches
                    if term in d.title.lower():
                        score += 5.0
                        matched.append(term)

                    # Bonus for rationale matches
                    if term in d.rationale.lower():
                        score += 3.0
                        if term not in matched:
                            matched.append(term)

                    # Bonus for decision field matches
                    if term in d.decision.lower():
                        score += 2.0
                        if term not in matched:
                            matched.append(term)

            # Intent-specific scoring bonuses
            if intent == "why" and d.rationale:
                score += 3.0
            if intent == "alternatives" and d.alternatives:
                score += 4.0
            if intent == "impact" and d.consequences:
                score += 3.0
            if intent == "reversal" and d.reversal_strategy:
                score += 5.0
            if intent == "approval" and d.approver:
                score += 4.0
            if intent == "dependencies" and d.related_decisions:
                score += 3.0
            if intent == "status":
                score += 2.0
            if intent == "who" and d.author:
                score += 3.0

            # Only include if there's keyword match or intent-specific match
            # (recency alone is not enough to consider a decision relevant)
            keyword_score = score

            # Recency bonus (only added if there's already a keyword score)
            if keyword_score > 0:
                age_days = (time.time() - d.created_at) / 86400 if d.created_at else 999
                recency_bonus = max(0, 5.0 - (age_days / 30))  # up to 5.0 for recent decisions
                score += recency_bonus

            if keyword_score > 0:
                scored.append((d, score, matched))

        if not scored:
            return QuestionAnswer(
                question=question,
                answer=self._generate_no_answer(intent),
                confidence=0.0,
                intent=intent,
            )

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        best_d, best_score, best_matched = scored[0]

        # Normalize confidence to 0-1 range
        confidence = min(1.0, best_score / 50.0)

        # Build answer based on intent
        answer = self._build_answer(best_d, intent, best_matched)

        return QuestionAnswer(
            question=question,
            answer=answer,
            confidence=confidence,
            intent=intent,
            source_decision_id=best_d.decision_id,
            source_title=best_d.title,
            matched_terms=best_matched,
        )

    # ── Timeline ─────────────────────────────────────────────────────────

    def get_timeline(self, limit: int = 50) -> list[DecisionTimelineEntry]:
        """Get a chronological timeline of all decision events.

        Returns:
            List of DecisionTimelineEntry sorted by date descending.
        """
        entries: list[DecisionTimelineEntry] = []
        with self._lock:
            for d in self._decisions:
                created = datetime.fromtimestamp(d.created_at).strftime("%Y-%m-%d %H:%M") if d.created_at else "?"
                entries.append(DecisionTimelineEntry(
                    date=created,
                    decision_id=d.decision_id,
                    title=d.title,
                    event="CREATED",
                    detail=f"Status: {d.status}, Priority: {d.priority}",
                ))
                if d.approver and d.approval_date:
                    app_date = datetime.fromtimestamp(d.approval_date).strftime("%Y-%m-%d %H:%M")
                    entries.append(DecisionTimelineEntry(
                        date=app_date,
                        decision_id=d.decision_id,
                        title=d.title,
                        event="APPROVED",
                        detail=f"Approved by: {d.approver}",
                    ))
                if d.superseded_by:
                    entries.append(DecisionTimelineEntry(
                        date=created,
                        decision_id=d.decision_id,
                        title=d.title,
                        event="SUPERSEDED",
                        detail=f"Superseded by: {d.superseded_by}",
                    ))

        # Sort by date descending (most recent first)
        entries.sort(key=lambda e: e.date, reverse=True)
        return entries[:limit]

    # ── Search ───────────────────────────────────────────────────────────

    def search(
        self,
        query: str = "",
        status: str = "",
        impact_category: str = "",
        module_path: str = "",
        tag: str = "",
        limit: int = 20,
    ) -> list[DecisionSearchResult]:
        """Search decisions by keywords and filters.

        Uses simple keyword matching with score ranking.
        Supports filtering by status, impact category, module path, and tags.

        Args:
            query: Free-text search query.
            status: Filter by status (e.g., "ACCEPTED").
            impact_category: Filter by impact category.
            module_path: Filter by affected module path.
            tag: Filter by tag.
            limit: Maximum results to return.

        Returns:
            List of DecisionSearchResult with relevance scores.
        """
        with self._lock:
            candidates = list(self._decisions)

        # Apply filters
        if status:
            clean_status = status.upper()
            candidates = [d for d in candidates if d.status == clean_status]
        if impact_category:
            clean_cat = impact_category.upper()
            candidates = [d for d in candidates if clean_cat in d.impact_categories]
        if module_path:
            candidates = [d for d in candidates if any(
                module_path.lower() in mp.lower() for mp in d.module_paths
            )]
        if tag:
            clean_tag = tag.lower()
            candidates = [d for d in candidates if clean_tag in d.tags]

        # Search and score
        results: list[DecisionSearchResult] = []
        query_terms = [q.lower() for q in re.findall(r'\w+', query)] if query else []

        for d in candidates:
            if not query_terms:
                # No query: return all filtered results sorted by recency
                results.append(DecisionSearchResult(
                    decision_id=d.decision_id,
                    title=d.title,
                    score=1.0,
                    excerpt=d.decision[:200],
                ))
                continue

            score = 0.0
            matched_keywords: list[str] = []
            search_text = (
                f"{d.title} {d.context} {d.decision} {d.rationale} "
                f"{' '.join(d.consequences)} {' '.join(d.tags)}"
            ).lower()

            for term in query_terms:
                if term in search_text:
                    count = search_text.count(term)
                    score += count * 2.0
                    matched_keywords.append(term)

                # Bonus for title matches
                if term in d.title.lower():
                    score += 5.0

            if score > 0:
                # Find excerpt
                excerpt = self._find_excerpt(d, query_terms)
                results.append(DecisionSearchResult(
                    decision_id=d.decision_id,
                    title=d.title,
                    score=score,
                    matched_keywords=matched_keywords,
                    excerpt=excerpt,
                ))

        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def get_decisions_by_module(self, module_path: str) -> list[DecisionRecord]:
        """Get all decisions affecting a specific module."""
        with self._lock:
            return [d for d in self._decisions
                    if any(module_path.lower() in mp.lower() for mp in d.module_paths)]

    def get_decisions_by_tag(self, tag: str) -> list[DecisionRecord]:
        """Get all decisions with a specific tag."""
        clean_tag = tag.lower()
        with self._lock:
            return [d for d in self._decisions if clean_tag in d.tags]

    def get_related_decisions(self, decision_id: str) -> list[DecisionRecord]:
        """Get decisions related to (depending on) a given decision."""
        with self._lock:
            decision = self._get_decision_unlocked(decision_id)
            if not decision:
                return []
            related_ids = set(decision.related_decisions)
            return [d for d in self._decisions if d.decision_id in related_ids]

    def get_dependent_decisions(self, decision_id: str) -> list[DecisionRecord]:
        """Get decisions that depend on this decision (reverse relationship)."""
        with self._lock:
            return [d for d in self._decisions
                    if decision_id in d.related_decisions]

    # ── Report & Stats ───────────────────────────────────────────────────

    def get_report(self) -> DecisionMemoryReport:
        """Generate aggregated decision memory report."""
        with self._lock:
            report = DecisionMemoryReport(
                timestamp=time.time(),
                total_decisions=len(self._decisions),
            )

            # By status
            by_status: dict[str, int] = {}
            for d in self._decisions:
                by_status[d.status] = by_status.get(d.status, 0) + 1
            report.by_status = by_status

            # By impact
            by_impact: dict[str, int] = {}
            for d in self._decisions:
                for c in d.impact_categories:
                    by_impact[c] = by_impact.get(c, 0) + 1
            report.by_impact = by_impact

            # By priority
            by_priority: dict[str, int] = {}
            for d in self._decisions:
                by_priority[d.priority] = by_priority.get(d.priority, 0) + 1
            report.by_priority = by_priority

            # Recent decisions
            sorted_decisions = sorted(self._decisions, key=lambda d: d.created_at, reverse=True)
            report.recent_decisions = sorted_decisions[:10]

            # Top modules
            module_counts: dict[str, int] = {}
            for d in self._decisions:
                for mp in d.module_paths:
                    module_counts[mp] = module_counts.get(mp, 0) + 1
            report.top_modules_by_decisions = [
                {"module": mod, "count": count}
                for mod, count in sorted(module_counts.items(), key=lambda x: x[1], reverse=True)
            ]

            # Velocity (decisions per week over last 90 days)
            cutoff_90 = time.time() - (90 * 86400)
            recent_90 = [d for d in self._decisions if d.created_at >= cutoff_90]
            report.decision_velocity_per_week = len(recent_90) / 12.86  # ~90 days in weeks

            # Acceptance rate
            if self._decisions:
                accepted = sum(1 for d in self._decisions if d.status == "ACCEPTED")
                report.acceptance_rate = accepted / len(self._decisions)

            # Average resolution days (time from PROPOSED to ACCEPTED)
            proposed_dates: dict[str, float] = {}
            accepted_dates: dict[str, float] = {}
            for d in self._decisions:
                if d.status == "PROPOSED" and d.created_at:
                    proposed_dates[d.decision_id] = d.created_at
                elif d.status == "ACCEPTED" and d.updated_at:
                    accepted_dates[d.decision_id] = d.updated_at

            resolved = 0
            total_days = 0.0
            for dec_id in set(proposed_dates) & set(accepted_dates):
                days = (accepted_dates[dec_id] - proposed_dates[dec_id]) / 86400
                if days > 0:
                    total_days += days
                    resolved += 1
            report.avg_resolution_days = total_days / max(resolved, 1)

            # Recommendations
            report.recommendations = self._generate_recommendations(report)

            return report

    def get_stats(self) -> dict[str, Any]:
        """Get decision memory statistics."""
        with self._lock:
            total = len(self._decisions)
            return {
                "total_decisions": total,
                "by_status": {
                    status: sum(1 for d in self._decisions if d.status == status)
                    for status in VALID_STATUSES
                },
                "total_modules_mapped": len(set(
                    mp for d in self._decisions for mp in d.module_paths
                )),
                "latest_decision": self._decisions[-1].to_dict() if self._decisions else None,
                "unique_tags": len(set(t for d in self._decisions for t in d.tags)),
                "decisions_with_reversal": sum(1 for d in self._decisions if d.reversal_strategy),
                "decisions_with_approval": sum(1 for d in self._decisions if d.approver),
                "decisions_with_tradeoffs": sum(1 for d in self._decisions if d.tradeoffs),
                "total_related_links": sum(len(d.related_decisions) for d in self._decisions),
            }

    def clear_all(self) -> None:
        """Clear all decision records."""
        with self._lock:
            self._decisions.clear()
            if self._persist_path.exists():
                self._persist_path.unlink()

    # ── Q&A Internal ─────────────────────────────────────────────────────

    def _detect_intent(self, question: str) -> str:
        """Detect the intent of a natural language question."""
        for intent, patterns in _QUESTION_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, question):
                    return intent
        return "general"

    def _build_answer(self, decision: DecisionRecord, intent: str, matched: list[str]) -> str:
        """Build a natural language answer from a decision record based on intent."""
        title = decision.title
        date_str = datetime.fromtimestamp(decision.created_at).strftime("%Y-%m-%d") if decision.created_at else "unknown date"

        if intent == "why":
            parts = [f"The decision to {decision.decision[:150].lower().rstrip('.')} was made"]
            if decision.rationale:
                parts.append(f"because {decision.rationale[:200].lower().rstrip('.')}")
            if decision.tradeoffs:
                parts.append(f"Trade-offs: {decision.tradeoffs[:200]}")
            if decision.context:
                parts.append(f"Context: {decision.context[:200]}")
            return ". ".join(parts) + f". (Decision: '{title}', {date_str})"

        elif intent == "alternatives":
            parts = [f"The following alternatives were considered for '{title}'"]
            if decision.alternatives:
                alt_list = "; ".join(decision.alternatives[:5])
                parts.append(f"Alternatives: {alt_list}")
            else:
                parts.append("No alternatives were documented")
            if decision.rationale:
                parts.append(f"The chosen option was selected because {decision.rationale[:200]}")
            return f"{'. '.join(parts)}. (Decision: '{title}', {date_str})"

        elif intent == "impact":
            parts = [f"The decision to '{title}' has the following impacts"]
            if decision.impact_categories:
                parts.append(f"Categories: {', '.join(decision.impact_categories[:6])}")
            if decision.consequences:
                cons_list = "; ".join(decision.consequences[:5])
                parts.append(f"Consequences: {cons_list}")
            if decision.module_paths:
                mod_list = "; ".join(decision.module_paths[:5])
                parts.append(f"Modules affected: {mod_list}")
            return f"{'. '.join(parts)}. ({date_str})"

        elif intent == "status":
            return (f"The status of '{title}' is {decision.status}. "
                    f"Priority: {decision.priority}. Created: {date_str}.")

        elif intent == "reversal":
            if decision.reversal_strategy:
                return (f"Reversal strategy for '{title}': {decision.reversal_strategy[:300]}. "
                        f"Status: {decision.status}. ({date_str})")
            return (f"No reversal strategy documented for '{title}'. "
                    f"Consider adding one if this decision may need to be reversed.")

        elif intent == "who" or intent == "approval":
            parts = [f"Decision '{title}'"]
            if decision.author:
                parts.append(f"was authored by {decision.author}")
            if decision.approver:
                parts.append(f"and approved by {decision.approver}")
            if not decision.author and not decision.approver:
                parts.append("has no author or approver recorded")
            return f"{' '.join(parts)}. ({date_str})"

        elif intent == "when":
            return (f"'{title}' was created on {date_str}. "
                    f"Status: {decision.status}. "
                    f"Last updated: {datetime.fromtimestamp(decision.updated_at).strftime('%Y-%m-%d') if decision.updated_at else '?'}.")

        elif intent == "dependencies":
            dep_count = len(decision.related_decisions)
            if dep_count > 0:
                dep_ids = ", ".join(decision.related_decisions[:6])
                return (f"'{title}' has {dep_count} related/dependency decision(s): {dep_ids}. ")
            return f"'{title}' has no documented dependencies on other decisions."

        else:
            return (
                f"The decision '{title}' ({date_str}) was: {decision.decision[:200]}. "
                f"Rationale: {decision.rationale[:200]}. "
                f"Status: {decision.status}."
            )

    def _generate_no_answer(self, intent: str) -> str:
        """Generate a response when no matching decision is found."""
        if intent == "why":
            return "I couldn't find a decision with a documented rationale matching your question."
        elif intent == "alternatives":
            return "No decisions with documented alternatives matched your question."
        elif intent == "status":
            return "No decisions matching your question were found."
        elif intent == "reversal":
            return "No decisions with reversal strategies matched your question."
        else:
            return "No decisions matched your question. Try searching with different terms."

    # ── Timeline & Dependency Internal ──────────────────────────────────

    def get_decision_graph(self) -> dict[str, Any]:
        """Get the decision dependency graph as nodes and edges."""
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        with self._lock:
            for d in self._decisions:
                nodes.append({
                    "id": d.decision_id,
                    "label": d.title[:60],
                    "status": d.status,
                    "priority": d.priority,
                })
                for rel_id in d.related_decisions:
                    edges.append({"from": d.decision_id, "to": rel_id, "type": "depends_on"})
                if d.superseded_by:
                    edges.append({"from": d.decision_id, "to": d.superseded_by, "type": "superseded_by"})
        return {"nodes": nodes, "edges": edges}

    # ── Internal ─────────────────────────────────────────────────────────

    def _get_decision_unlocked(self, decision_id: str) -> DecisionRecord | None:
        """Get a decision without locking (caller must hold lock)."""
        for d in self._decisions:
            if d.decision_id == decision_id:
                return d
        return None

    def _find_excerpt(self, decision: DecisionRecord, query_terms: list[str]) -> str:
        """Find the most relevant excerpt containing query terms."""
        fields = [
            (decision.context, 200),
            (decision.decision, 200),
            (decision.rationale, 200),
        ]
        for text, max_len in fields:
            for term in query_terms:
                idx = text.lower().find(term)
                if idx >= 0:
                    start = max(0, idx - 60)
                    end = min(len(text), idx + 140)
                    excerpt = text[start:end].strip()
                    if start > 0:
                        excerpt = "..." + excerpt
                    if end < len(text):
                        excerpt = excerpt + "..."
                    return excerpt[:max_len]
        # Fallback: first chars of decision
        return decision.decision[:200]

    def _generate_recommendations(self, report: DecisionMemoryReport) -> list[str]:
        """Generate recommendations based on decision analytics."""
        recs: list[str] = []

        if report.total_decisions == 0:
            recs.append("No decisions recorded — start capturing engineering decisions")
            return recs

        # Status distribution
        draft_count = report.by_status.get("DRAFT", 0)
        proposed_count = report.by_status.get("PROPOSED", 0)
        if draft_count > 5:
            recs.append(f"{draft_count} decisions still in DRAFT — resolve to PROPOSED or ACCEPTED")
        if proposed_count > 5:
            recs.append(f"{proposed_count} decisions still in PROPOSED — schedule review and acceptance")

        # Impact coverage
        for cat in IMPACT_CATEGORIES:
            if cat not in report.by_impact:
                recs.append(f"No decisions recorded for impact category '{cat}' — consider if coverage is needed")

        # Velocity
        if report.decision_velocity_per_week < 1 and report.total_decisions > 10:
            recs.append("Decision velocity is low — ensure significant technical decisions are captured")

        # Superseded decisions (technical debt indicator)
        superseded = report.by_status.get("SUPERSEDED", 0)
        deprecated = report.by_status.get("DEPRECATED", 0)
        if superseded > 3 or deprecated > 3:
            recs.append(f"{superseded + deprecated} decisions superseded or deprecated — "
                        "review if migration plans are documented")

        # Reversal strategy coverage (new recommendation)
        stats = self.get_stats()
        if stats["decisions_with_reversal"] < stats["total_decisions"] * 0.3 and stats["total_decisions"] > 5:
            recs.append(f"Only {stats['decisions_with_reversal']}/{stats['total_decisions']} decisions have a "
                        "reversal strategy — consider documenting rollback plans for critical decisions")

        if not recs:
            recs.append("Decision health looks good — continue capturing decisions")

        return recs[:8]

    # ── ADR Auto-Import ───────────────────────────────────────────────

    def import_adr(
        self,
        adr_path: str | Path,
        feed_to_kb: bool = True,
    ) -> DecisionRecord | None:
        """Import a single ADR (Architecture Decision Record) markdown file.

        Parses the standard ADR format: Title, Status, Date, Context, Decision,
        Consequences sections. Records it as a DecisionMemory entry.

        Args:
            adr_path: Path to the ADR markdown file.
            feed_to_kb: If True, feed to Knowledge Base.

        Returns:
            DecisionRecord if parsed successfully, None otherwise.
        """
        adr_path = Path(adr_path)
        if not adr_path.is_file():
            _log.warning("[DEC_MEM] ADR not found: %s", adr_path)
            return None

        try:
            text = adr_path.read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.warning("[DEC_MEM] ADR read error %s: %s", adr_path, exc)
            return None

        # Parse title from first heading
        title_match = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else adr_path.stem

        # Parse status
        status = "ACCEPTED"
        status_match = re.search(
            r'##\s+Status\s*\n+(.+?)(?:\n|$)', text, re.IGNORECASE | re.MULTILINE
        )
        if status_match:
            raw_status = status_match.group(1).strip().lower()
            if "accepted" in raw_status:
                status = "ACCEPTED"
            elif "proposed" in raw_status or "draft" in raw_status:
                status = "PROPOSED"
            elif "deprecated" in raw_status:
                status = "DEPRECATED"
            elif "superseded" in raw_status or "replaced" in raw_status:
                status = "SUPERSEDED"
            elif "rejected" in raw_status:
                status = "REJECTED"

        # Parse date
        created_at = 0.0
        date_match = re.search(
            r'##\s+Date\s*\n+(.+?)(?:\n|$)', text, re.IGNORECASE | re.MULTILINE
        )
        if date_match:
            date_str = date_match.group(1).strip()
            # Handle multi-line dates like "2026-05-22 (Initial)\n2026-05-22 (Updated)"
            first_date = date_str.split("\n")[0].split()[0].strip()
            try:
                # Date-only strings are interpreted as midnight IST; attach the
                # zone explicitly so .timestamp() is host-TZ independent (naive
                # strptime uses the machine's local zone, shifting epochs ~5.5h
                # on UTC hosts).
                created_at = (
                    datetime.strptime(first_date, "%Y-%m-%d")
                    .replace(tzinfo=IST_TZ)
                    .timestamp()
                )
            except ValueError:
                pass

        # Parse context section
        context = self._extract_adr_section(text, "Context")

        # Parse decision section
        decision = self._extract_adr_section(text, "Decision")

        # Parse consequences
        consequences_text = self._extract_adr_section(text, "Consequences")
        consequences = [c.strip() for c in consequences_text.split("\n")
                       if c.strip().startswith("-") or c.strip().startswith("*")]
        if not consequences:
            consequences = [consequences_text[:200]] if consequences_text else []

        return self.record_decision(
            title=title,
            context=context[:1000],
            decision=decision[:1000],
            status=status,
            module_paths=[str(adr_path)],
            adr_path=str(adr_path),
            tags=["adr", adr_path.stem.lower().replace("-", "_")],
            consequences=consequences[:10],
            created_at=created_at or time.time(),
            feed_to_kb=feed_to_kb,
        )

    def scan_adr_directory(
        self,
        adr_dir: str | Path = "docs/adr",
        feed_to_kb: bool = True,
    ) -> list[DecisionRecord]:
        """Scan a directory for ADR markdown files and import all of them.

        Skips README.md and any already-imported ADRs (matching by adr_path).

        Args:
            adr_dir: Directory containing ADR markdown files.
            feed_to_kb: If True, feed imported ADRs to Knowledge Base.

        Returns:
            List of newly imported DecisionRecords.
        """
        adr_dir = Path(adr_dir)
        if not adr_dir.is_dir():
            _log.warning("[DEC_MEM] ADR directory not found: %s", adr_dir)
            return []

        # Get already-imported ADR paths
        with self._lock:
            imported_paths = {d.adr_path for d in self._decisions if d.adr_path}

        imported: list[DecisionRecord] = []
        for adr_file in sorted(adr_dir.glob("*.md")):
            if adr_file.name.lower() == "readme.md":
                continue
            if str(adr_file) in imported_paths:
                continue
            record = self.import_adr(adr_file, feed_to_kb=feed_to_kb)
            if record:
                imported.append(record)
                _log.info("[DEC_MEM] Imported ADR: %s", adr_file.name)

        return imported

    @staticmethod
    def _extract_adr_section(text: str, section_name: str) -> str:
        """Extract a section from an ADR markdown file.

        Looks for '## <section_name>' heading and captures text until
        the next '##' heading or end of file.
        """
        pattern = rf'##\s*{re.escape(section_name)}\s*\n(.*?)(?=\n##\s|\Z)'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            result = match.group(1).strip()
            # Remove trailing references section
            ref_pattern = r'\n##\s*References'
            result = re.split(ref_pattern, result, flags=re.IGNORECASE)[0].strip()
            return result
        return ""

    # ── Decision Comparison ────────────────────────────────────────────

    def compare_decisions(
        self,
        decision_id_1: str,
        decision_id_2: str,
    ) -> dict[str, Any]:
        """Compare two decisions side by side.

        Highlights differences in status, priority, impact, alternatives,
        rationale length, consequences, and module paths.

        Args:
            decision_id_1: First decision ID.
            decision_id_2: Second decision ID.

        Returns:
            Dict with comparison data.
        """
        d1 = self.get_decision(decision_id_1)
        d2 = self.get_decision(decision_id_2)

        if not d1 and not d2:
            return {"error": "Both decisions not found"}
        if not d1:
            return {"error": f"Decision '{decision_id_1}' not found"}
        if not d2:
            return {"error": f"Decision '{decision_id_2}' not found"}

        return {
            "decision_1": {
                "id": d1.decision_id,
                "title": d1.title,
                "status": d1.status,
                "priority": d1.priority,
                "author": d1.author,
                "approver": d1.approver,
                "age_days": round((time.time() - d1.created_at) / 86400, 1) if d1.created_at else 0,
                "rationale_length": len(d1.rationale),
                "n_alternatives": len(d1.alternatives),
                "n_consequences": len(d1.consequences),
                "n_modules": len(d1.module_paths),
                "impact_categories": d1.impact_categories,
                "has_reversal": bool(d1.reversal_strategy),
                "has_tradeoffs": bool(d1.tradeoffs),
                "n_tags": len(d1.tags),
                "n_related": len(d1.related_decisions),
                "adr": bool(d1.adr_path),
            },
            "decision_2": {
                "id": d2.decision_id,
                "title": d2.title,
                "status": d2.status,
                "priority": d2.priority,
                "author": d2.author,
                "approver": d2.approver,
                "age_days": round((time.time() - d2.created_at) / 86400, 1) if d2.created_at else 0,
                "rationale_length": len(d2.rationale),
                "n_alternatives": len(d2.alternatives),
                "n_consequences": len(d2.consequences),
                "n_modules": len(d2.module_paths),
                "impact_categories": d2.impact_categories,
                "has_reversal": bool(d2.reversal_strategy),
                "has_tradeoffs": bool(d2.tradeoffs),
                "n_tags": len(d2.tags),
                "n_related": len(d2.related_decisions),
                "adr": bool(d2.adr_path),
            },
            "differences": {
                "same_status": d1.status == d2.status,
                "same_priority": d1.priority == d2.priority,
                "same_author": bool(d1.author == d2.author and d1.author),
                "shared_impact_categories": list(set(d1.impact_categories) & set(d2.impact_categories)),
                "unique_to_1": {
                    "impact": list(set(d1.impact_categories) - set(d2.impact_categories)),
                    "modules": [m for m in d1.module_paths if m not in d2.module_paths],
                    "tags": [t for t in d1.tags if t not in d2.tags],
                },
                "unique_to_2": {
                    "impact": list(set(d2.impact_categories) - set(d1.impact_categories)),
                    "modules": [m for m in d2.module_paths if m not in d1.module_paths],
                    "tags": [t for t in d2.tags if t not in d1.tags],
                },
            },
            "age_difference_days": round(
                abs((d1.created_at - d2.created_at) / 86400), 1
            ) if d1.created_at and d2.created_at else 0,
        }

    # ── Batch Export/Import ───────────────────────────────────────────────

    def export_decisions(
        self,
        output_path: str | Path = "json/decisions_export.json",
        status_filter: str = "",
        tag_filter: str = "",
        limit: int = 0,
    ) -> int:
        """Export decisions to a JSON file with optional filters.

        Args:
            output_path: Path to export file.
            status_filter: Optional status filter (e.g., "ACCEPTED").
            tag_filter: Optional tag filter.
            limit: Max decisions to export (0 = all).

        Returns:
            Number of decisions exported.
        """
        with self._lock:
            candidates = list(self._decisions)

        if status_filter:
            candidates = [d for d in candidates if d.status == status_filter.upper()]
        if tag_filter:
            candidates = [d for d in candidates if tag_filter.lower() in d.tags]

        if limit > 0:
            candidates = candidates[:limit]

        data = {
            "exported_at": time.time(),
            "total": len(candidates),
            "decisions": [d.to_dict() for d in candidates],
        }

        try:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            _log.info("[DEC_MEM] Exported %d decisions to %s", len(candidates), output_path)
        except (OSError, ValueError) as exc:
            _log.warning("[DEC_MEM] Export failed: %s", exc)
            return 0

        return len(candidates)

    def import_decisions(
        self,
        input_path: str | Path,
        skip_existing: bool = True,
    ) -> int:
        """Import decisions from a JSON export file.

        Args:
            input_path: Path to import file.
            skip_existing: If True, skip decisions with IDs that already exist.

        Returns:
            Number of decisions imported.
        """
        path = Path(input_path)
        if not path.is_file():
            _log.warning("[DEC_MEM] Import file not found: %s", input_path)
            return 0

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.warning("[DEC_MEM] Import read error: %s", exc)
            return 0

        raw_decisions = data.get("decisions", [])
        if not raw_decisions:
            _log.warning("[DEC_MEM] No decisions found in import file")
            return 0

        imported = 0
        with self._lock:
            existing_ids = {d.decision_id for d in self._decisions}

            for item in raw_decisions:
                if skip_existing and item.get("decision_id", "") in existing_ids:
                    continue
                try:
                    valid_keys = DecisionRecord.__dataclass_fields__.keys()
                    filtered = {k: v for k, v in item.items() if k in valid_keys}
                    record = DecisionRecord(**filtered)
                    self._decisions.append(record)
                    imported += 1
                except (TypeError, ValueError) as exc:
                    _log.debug("[DEC_MEM] Import skip: %s", exc)

            if imported > 0:
                self._persist()

        _log.info("[DEC_MEM] Imported %d/%d decisions from %s", imported, len(raw_decisions), input_path)
        return imported

    # ── Timeline by Date Range ───────────────────────────────────────────

    def get_timeline_by_date(
        self,
        start_date: str = "",
        end_date: str = "",
        limit: int = 50,
    ) -> list[DecisionTimelineEntry]:
        """Get decision timeline filtered by date range.

        Args:
            start_date: Start date (YYYY-MM-DD). Empty = no lower bound.
            end_date: End date (YYYY-MM-DD). Empty = no upper bound.
            limit: Max entries to return.

        Returns:
            Filtered timeline entries.
        """
        start_ts = 0.0
        end_ts = time.time()

        if start_date:
            try:
                start_ts = (
                    datetime.strptime(start_date, "%Y-%m-%d")
                    .replace(tzinfo=IST_TZ)
                    .timestamp()
                )
            except ValueError:
                pass
        if end_date:
            try:
                end_ts = (
                    datetime.strptime(end_date, "%Y-%m-%d")
                    .replace(tzinfo=IST_TZ)
                    .timestamp()
                    + 86400
                )
            except ValueError:
                pass

        with self._lock:
            filtered = [d for d in self._decisions
                       if start_ts <= d.created_at <= end_ts]

        # Build entries for filtered decisions
        entries: list[DecisionTimelineEntry] = []
        for d in filtered:
            created = datetime.fromtimestamp(d.created_at).strftime("%Y-%m-%d %H:%M") if d.created_at else "?"
            entries.append(DecisionTimelineEntry(
                date=created,
                decision_id=d.decision_id,
                title=d.title,
                event="CREATED",
                detail=f"Status: {d.status}, Priority: {d.priority}",
            ))
            if d.approver and d.approval_date:
                app_date = datetime.fromtimestamp(d.approval_date).strftime("%Y-%m-%d %H:%M")
                entries.append(DecisionTimelineEntry(
                    date=app_date,
                    decision_id=d.decision_id,
                    title=d.title,
                    event="APPROVED",
                    detail=f"Approved by: {d.approver}",
                ))

        entries.sort(key=lambda e: e.date, reverse=True)
        return entries[:limit]

    def find_similar(
        self,
        decision_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Find decisions similar to a given decision.

        Uses overlap scoring on impact_categories, tags, modules, and
        keyword overlap in title/context.

        Args:
            decision_id: The decision to find matches for.
            limit: Max similar decisions to return.

        Returns:
            List of similar decisions with similarity scores.
        """
        source = self.get_decision(decision_id)
        if not source:
            return []

        source_impacts = set(source.impact_categories)
        source_tags = set(source.tags)
        source_modules = set(source.module_paths)
        source_words = set(re.findall(r'\w+', (source.title + " " + source.context).lower()))

        scored: list[tuple[DecisionRecord, float]] = []
        with self._lock:
            for d in self._decisions:
                if d.decision_id == decision_id:
                    continue

                score = 0.0

                # Impact overlap
                d_impacts = set(d.impact_categories)
                if source_impacts and d_impacts:
                    overlap = source_impacts & d_impacts
                    score += len(overlap) * 5.0

                # Tag overlap
                d_tags = set(d.tags)
                if source_tags and d_tags:
                    tag_overlap = source_tags & d_tags
                    score += len(tag_overlap) * 4.0

                # Module overlap
                d_modules = set(d.module_paths)
                if source_modules and d_modules:
                    mod_overlap = source_modules & d_modules
                    score += len(mod_overlap) * 3.0

                # Word overlap in title/context
                d_words = set(re.findall(r'\w+', (d.title + " " + d.context).lower()))
                word_overlap = source_words & d_words
                score += len(word_overlap) * 0.5

                # Same author bonus
                if source.author and d.author and source.author == d.author:
                    score += 2.0

                if score > 0:
                    scored.append((d, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            {
                "decision_id": d.decision_id,
                "title": d.title,
                "status": d.status,
                "similarity_score": round(score, 1),
            }
            for d, score in scored[:limit]
        ]

    # ── Knowledge Base Integration ──────────────────────────────────────

    def _feed_to_knowledge_base(self, record: DecisionRecord) -> None:
        """Feed a decision record into the Knowledge Base for cross-domain learning.

        Attempts to import KnowledgeBase; silently continues if unavailable.
        """
        try:
            from core.knowledge_base import BEST_PRACTICE, get_knowledge_base

            kb = get_knowledge_base()
            kb.add_entry(
                pattern_type=BEST_PRACTICE,
                pattern=f"Decision: {record.title} — {record.decision[:200]}",
                solution=(
                    f"Rationale: {record.rationale[:200]}\n"
                    f"Alternatives: {'; '.join(record.alternatives[:3])}\n"
                    f"Trade-offs: {record.tradeoffs[:200]}\n"
                    f"Reversal: {record.reversal_strategy[:200]}"
                ),
                source=f"decision_memory:{record.decision_id}",
                confidence=0.8,
                tags=record.tags + [record.status.lower(), "decision"],
            )
        except ImportError:
            pass  # KB not available — non-critical
        except Exception as exc:
            _log.debug("[DEC_MEM] KB feed: %s", exc)

    # ── Persistence ──────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Persist decisions to disk."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = [d.to_dict() for d in self._decisions[-self._max_decisions:]]
            self._persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.debug("[DEC_MEM] Persist: %s", exc)

    def _load_decisions(self) -> None:
        """Load decisions from disk with backward compatibility for legacy fields."""
        try:
            if self._persist_path.is_file():
                data = json.loads(self._persist_path.read_text(encoding="utf-8"))
                for item in data:
                    try:
                        # Backward compat: use all fields that exist on DecisionRecord
                        valid_keys = DecisionRecord.__dataclass_fields__.keys()
                        filtered = {k: v for k, v in item.items() if k in valid_keys}
                        d = DecisionRecord(**filtered)
                        self._decisions.append(d)
                    except (TypeError, ValueError) as exc:
                        _log.debug("[DEC_MEM] Load skip: %s", exc)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.debug("[DEC_MEM] Load failed: %s", exc)


# ── Singleton ──────────────────────────────────────────────────────────────

_memory: DecisionMemory | None = None
_memory_lock = threading.RLock()


def get_decision_memory() -> DecisionMemory:
    """Get the singleton DecisionMemory instance."""
    global _memory
    with _memory_lock:
        if _memory is None:
            _memory = DecisionMemory()
        return _memory


def reset_decision_memory() -> None:
    """Force-reset singleton (for testing)."""
    global _memory
    with _memory_lock:
        _memory = None


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m core.decision_memory",
        description="Decision Memory — Capture, retrieve and ask questions about engineering decisions",
    )
    ap.add_argument("--search", type=str, help="Search decisions by keyword")
    ap.add_argument("--ask", type=str, help="Ask a natural language question about decisions")
    ap.add_argument("--record", type=str, help="Record a new decision (title:context:decision)")
    ap.add_argument("--report", action="store_true", help="Show decision memory report")
    ap.add_argument("--stats", action="store_true", help="Show statistics")
    ap.add_argument("--timeline", action="store_true", help="Show decision timeline")
    ap.add_argument("--graph", action="store_true", help="Show decision dependency graph (JSON)")
    ap.add_argument("--adr-import", type=str, metavar="PATH",
                    help="Import a single ADR markdown file")
    ap.add_argument("--adr-scan", type=str, nargs="?", const="docs/adr", metavar="DIR",
                    help="Scan directory and import all ADR files (default: docs/adr)")
    ap.add_argument("--compare", type=str, nargs=2, metavar=("ID1", "ID2"),
                    help="Compare two decisions side by side")
    ap.add_argument("--export", type=str, nargs="?", const="json/decisions_export.json",
                    metavar="PATH", help="Export decisions to JSON file (default: json/decisions_export.json)")
    ap.add_argument("--import", dest="import_path", type=str, metavar="PATH",
                    help="Import decisions from JSON file")
    ap.add_argument("--find-similar", type=str, metavar="ID",
                    help="Find decisions similar to a given decision ID")
    ap.add_argument("--timeline-by-date", type=str, nargs=2, metavar=("START", "END"),
                    help="Filter timeline by date range (YYYY-MM-DD YYYY-MM-DD)")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    mem = get_decision_memory()

    if args.ask:
        answer = mem.ask_question(args.ask)
        if args.json:
            print(json.dumps(answer.to_dict(), indent=2))
        else:
            print(answer.summary_text())
        return

    if args.search:
        results = mem.search(query=args.search)
        if args.json:
            print(json.dumps([r.to_dict() for r in results], indent=2))
        else:
            print(f"Search results for '{args.search}': {len(results)} found")
            for r in results[:10]:
                print(f"  [{r.score:.1f}] {r.title}")
                print(f"       {r.excerpt[:80]}...")
        return

    if args.record:
        parts = args.record.split(":", 2)
        if len(parts) < 3:
            print("Usage: title:context:decision")
            return
        title, context, decision = parts
        record = mem.record_decision(title=title, context=context, decision=decision)
        if args.json:
            print(json.dumps(record.to_dict(), indent=2))
        else:
            print(f"Recorded: {record.decision_id} - {record.title}")
        return

    if args.report:
        report = mem.get_report()
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(report.summary_text())
        return

    if args.stats:
        stats = mem.get_stats()
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print(f"Total Decisions: {stats['total_decisions']}")
            for status, count in stats['by_status'].items():
                print(f"  {status}: {count}")
            if stats['decisions_with_reversal']:
                print(f"With Reversal Strategy: {stats['decisions_with_reversal']}")
            if stats['decisions_with_approval']:
                print(f"With Approval: {stats['decisions_with_approval']}")
        return

    if args.timeline:
        entries = mem.get_timeline()
        if args.json:
            print(json.dumps([e.to_dict() for e in entries], indent=2))
        else:
            print(f"Decision Timeline ({len(entries)} events):")
            print("-" * 60)
            for e in entries[:20]:
                print(f"  [{e.date}] {e.event}: {e.title}")
                print(f"           {e.detail}")
                print()
        return

    if args.adr_import:
        path = args.adr_import
        record = mem.import_adr(path)
        if record:
            if args.json:
                print(json.dumps(record.to_dict(), indent=2))
            else:
                print(f"Imported ADR: {record.decision_id} - {record.title}")
        else:
            print(f"Failed to import ADR from: {path}")
        return

    if args.adr_scan is not None:
        directory = args.adr_scan if args.adr_scan else "docs/adr"
        imported = mem.scan_adr_directory(directory)
        if args.json:
            print(json.dumps([r.to_dict() for r in imported], indent=2))
        else:
            print(f"ADR Scan: {len(imported)} imported from {directory}")
            for r in imported[:10]:
                print(f"  {r.decision_id}: {r.title}")
        return

    if args.graph:
        print(json.dumps(mem.get_decision_graph(), indent=2))
        return

    if args.compare:
        comparison = mem.compare_decisions(args.compare[0], args.compare[1])
        if args.json:
            print(json.dumps(comparison, indent=2))
        else:
            if "error" in comparison:
                print(f"Error: {comparison['error']}")
            else:
                d1, d2 = comparison["decision_1"], comparison["decision_2"]
                print("=" * 60)
                print(f"  DECISION COMPARISON: {d1['title']} vs {d2['title']}")
                print("=" * 60)
                print(f"  {'Field':<25} {'Decision 1':<25} {'Decision 2':<25}")
                print("  " + "-" * 75)
                for field in ("status", "priority", "author", "approver"):
                    print(f"  {field:<25} {d1[field]:<25} {d2[field]:<25}")
                print(f"  {'age (days)':<25} {d1['age_days']:<25} {d2['age_days']:<25}")
                print(f"  {'rationale length':<25} {d1['rationale_length']:<25} {d2['rationale_length']:<25}")
                print(f"  {'alternatives':<25} {d1['n_alternatives']:<25} {d2['n_alternatives']:<25}")
                print(f"  {'modules':<25} {d1['n_modules']:<25} {d2['n_modules']:<25}")
                diff = comparison["differences"]
                print()
                print(f"  Same status: {diff['same_status']}, Same priority: {diff['same_priority']}")
                if diff["shared_impact_categories"]:
                    print(f"  Shared impact: {', '.join(diff['shared_impact_categories'])}")
                print(f"  Age difference: {comparison['age_difference_days']} days")
        return

    if args.export:
        path = args.export
        count = mem.export_decisions(output_path=path)
        print(f"Exported {count} decisions to {path}")
        return

    if args.import_path:
        count = mem.import_decisions(input_path=args.import_path)
        print(f"Imported {count} decisions from {args.import_path}")
        return

    if args.find_similar:
        similar = mem.find_similar(args.find_similar)
        if args.json:
            print(json.dumps(similar, indent=2))
        else:
            print(f"Similar decisions to '{args.find_similar}': {len(similar)} found")
            for s in similar:
                print(f"  [{s['similarity_score']:.0f}] {s['title']} ({s['status']})")
        return

    if args.timeline_by_date:
        start, end = args.timeline_by_date
        entries = mem.get_timeline_by_date(start_date=start, end_date=end)
        if args.json:
            print(json.dumps([e.to_dict() for e in entries], indent=2))
        else:
            print(f"Timeline ({start} to {end}): {len(entries)} events")
            for e in entries[:20]:
                print(f"  [{e.date}] {e.event}: {e.title}")
                print(f"           {e.detail}")
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()


__all__ = [
    "DecisionMemory",
    "DecisionMemoryReport",
    "DecisionRecord",
    "DecisionSearchResult",
    "DecisionTimelineEntry",
    "QuestionAnswer",
    "get_decision_memory",
    "reset_decision_memory",
]
