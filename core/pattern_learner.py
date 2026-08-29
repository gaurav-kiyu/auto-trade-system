"""Pattern Learner — Extracts and learns patterns from incidents, code reviews, test failures (Pillar 7).

Integrates with:
  - RootCauseAnalyzer (learns from incident investigations)
  - KnowledgeBase (stores and retrieves patterns)
  - RootCauseResult (extracts evidence-based patterns)
  - AutoLearner (cross-domain learning signals)

Capabilities:
  - Learn from incident investigations (RootCauseResult)
  - Learn from code review comments
  - Learn from test failures
  - Get recommendations for known error types
  - Correlate patterns across domains
  - Track pattern effectiveness over time

Usage:
    from core.pattern_learner import get_pattern_learner

    learner = get_pattern_learner()

    # Learn from an incident
    learner.learn_from_incident(result)

    # Learn from code review
    learner.learn_from_code_review(pr_id="PR-42", comments=["..."])

    # Get recommendations for an error
    recs = learner.get_recommendations("broker_disconnect")
    for r in recs:
        print(f"  [{r.confidence:.0%}] {r.solution}")
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from core.knowledge_base import (
    CODE_REVIEW_PATTERN,
    INCIDENT_PATTERN,
    LESSON_LEARNED,
    OPTIMIZATION_PATTERN,
    TEST_FAILURE_PATTERN,
    KnowledgeBase,
    KnowledgeEntry,
    get_knowledge_base,
)

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

MIN_PATTERN_LENGTH = 20
MAX_PATTERN_LENGTH = 500


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class LearnedPattern:
    """A pattern extracted from a learning source.

    Attributes:
        pattern_id: Unique identifier.
        category: Source category (incident, code_review, test_failure).
        description: Pattern description.
        evidence: Supporting evidence details.
        frequency: Times this pattern has been observed.
        confidence: Confidence level 0.0-1.0.
        tags: Classification tags.
        source_module: Module where the pattern originates.
        solution: Recommended fix or action.
    """

    pattern_id: str = ""
    category: str = "incident"
    description: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    frequency: int = 1
    confidence: float = 0.5
    tags: list[str] = field(default_factory=list)
    source_module: str = ""
    solution: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "category": self.category,
            "description": self.description[:100],
            "frequency": self.frequency,
            "confidence": round(self.confidence, 3),
            "tags": self.tags,
            "source_module": self.source_module,
        }


@dataclass
class PatternLearnerReport:
    """Statistics from the pattern learner."""

    total_incidents_learned: int = 0
    total_reviews_learned: int = 0
    total_failures_learned: int = 0
    total_patterns_extracted: int = 0
    knowledge_base_entries: int = 0
    top_patterns: list[dict[str, Any]] = field(default_factory=list)
    avg_extraction_time_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_incidents_learned": self.total_incidents_learned,
            "total_reviews_learned": self.total_reviews_learned,
            "total_failures_learned": self.total_failures_learned,
            "total_patterns_extracted": self.total_patterns_extracted,
            "knowledge_base_entries": self.knowledge_base_entries,
            "top_patterns": self.top_patterns[:5],
            "avg_extraction_time_ms": round(self.avg_extraction_time_ms, 1),
            "timestamp": self.timestamp,
        }


# ── Pattern Learner ──────────────────────────────────────────────────────────


class PatternLearner:
    """Extracts patterns from incidents, code reviews, and test failures.

    Learns from:
      - RootCauseResult objects (incident investigations)
      - Code review comments (PR feedback)
      - Test failure reports
      - Auto-tuner recommendations

    Stores learned patterns in the shared KnowledgeBase.
    """

    def __init__(self, kb: KnowledgeBase | None = None) -> None:
        self._lock = threading.RLock()
        self._kb = kb or get_knowledge_base()
        self._stats = {
            "incidents_learned": 0,
            "reviews_learned": 0,
            "failures_learned": 0,
            "total_time_ms": 0.0,
        }

    # ── Learning Sources ────────────────────────────────────────────────────

    def learn_from_incident(self, result: Any) -> list[KnowledgeEntry]:
        """Extract patterns from a RootCauseResult incident investigation.

        Creates KnowledgeBase entries for:
          - The incident type and probable cause (INCIDENT_PATTERN)
          - Specific evidence categories (as sub-patterns)
          - Recovery actions (as BEST_PRACTICE)

        Args:
            result: A RootCauseResult object (from core.root_cause_analyzer).

        Returns:
            List of KnowledgeEntry objects created or updated.
        """
        start = time.time()
        entries: list[KnowledgeEntry] = []

        try:
            incident_type = getattr(result, "incident_type", "UNKNOWN")
            probable_cause = getattr(result, "probable_cause", "")
            recommended_fix = getattr(result, "recommended_fix", "")
            severity = getattr(result, "severity", "NORMAL")
            evidence = getattr(result, "evidence", [])

            # Main incident pattern
            if incident_type and probable_cause:
                tags = ["incident", incident_type.lower(), severity.lower()]
                entry = self._kb.add_entry(
                    pattern_type=INCIDENT_PATTERN,
                    pattern=f"{incident_type}: {probable_cause[:200]}",
                    solution=recommended_fix[:300] if recommended_fix else "Investigate manually",
                    source="pattern_learner.learn_from_incident",
                    confidence=self._confidence_from_severity(severity),
                    tags=tags,
                    metadata={
                        "incident_type": incident_type,
                        "severity": severity,
                        "evidence_count": len(evidence),
                    },
                )
                entries.append(entry)

            # Extract sub-patterns from evidence
            for ev in evidence:
                ev_category = getattr(ev, "category", "")
                ev_description = getattr(ev, "description", "")
                ev_relevance = getattr(ev, "relevance", 0.5)

                if ev_category and ev_description and len(ev_description) > MIN_PATTERN_LENGTH:
                    sub_entry = self._kb.add_entry(
                        pattern_type=INCIDENT_PATTERN,
                        pattern=f"[{ev_category}] {ev_description[:200]}",
                        source="pattern_learner.evidence",
                        confidence=ev_relevance,
                        tags=["incident", ev_category.lower(), incident_type.lower()],
                    )
                    entries.append(sub_entry)

            # Link related entries
            if len(entries) > 1:
                main_id = entries[0].entry_id
                for e in entries[1:]:
                    if main_id not in e.related_entries:
                        e.related_entries.append(main_id)

        except Exception as exc:
            _log.debug("[PATTERN] learn_from_incident failed: %s", exc)

        elapsed = (time.time() - start) * 1000
        with self._lock:
            self._stats["incidents_learned"] += 1
            self._stats["total_time_ms"] += elapsed

        return entries

    def learn_from_code_review(
        self,
        pr_id: str,
        comments: list[str],
        author: str = "",
        files_changed: list[str] | None = None,
    ) -> list[KnowledgeEntry]:
        """Extract patterns from code review comments.

        Analyzes review comments to identify recurring themes:
          - Architecture concerns
          - Security issues
          - Performance issues
          - Style/naming patterns
          - Error handling patterns

        Args:
            pr_id: Pull request identifier.
            comments: List of review comment texts.
            author: Optional reviewer author name.
            files_changed: Optional list of files changed.

        Returns:
            List of KnowledgeEntry objects created or updated.
        """
        start = time.time()
        entries: list[KnowledgeEntry] = []

        if not comments:
            return entries

        files_changed = files_changed or []

        # Categorize comments by topic
        for i, comment in enumerate(comments):
            if not comment or len(comment) < MIN_PATTERN_LENGTH:
                continue

            comment_lower = comment.lower()
            tags = ["code_review"]

            # Detect architecture concerns
            if any(kw in comment_lower for kw in ["architecture", "dependency", "coupling", "circular"]):
                tags.extend(["architecture", "refactoring"])
                pattern_type = CODE_REVIEW_PATTERN
                confidence = 0.7

            # Detect security concerns
            elif any(kw in comment_lower for kw in ["security", "injection", "xss", "csrf", "auth"]):
                tags.extend(["security", "vulnerability"])
                pattern_type = CODE_REVIEW_PATTERN
                confidence = 0.9

            # Detect performance concerns
            elif any(kw in comment_lower for kw in ["performance", "slow", "n+1", "cache", "optimize"]):
                tags.extend(["performance", "optimization"])
                pattern_type = OPTIMIZATION_PATTERN if "optimize" in comment_lower else CODE_REVIEW_PATTERN  # type: ignore[possibly-undefined]
                confidence = 0.7

            # Detect error handling concerns
            elif any(kw in comment_lower for kw in ["error handling", "exception", "try/except", "fail"]):
                tags.extend(["error_handling", "resilience"])
                pattern_type = CODE_REVIEW_PATTERN
                confidence = 0.8

            # Detect testing concerns
            elif any(kw in comment_lower for kw in ["test", "coverage", "assert", "mock"]):
                tags.extend(["testing", "coverage"])
                pattern_type = CODE_REVIEW_PATTERN
                confidence = 0.6

            else:
                pattern_type = LESSON_LEARNED
                confidence = 0.5

            tags.append(f"pr:{pr_id}")

            entry = self._kb.add_entry(
                pattern_type=str(pattern_type),
                pattern=f"Code Review [{pr_id}] ({i}): {comment[:200]}",
                source="pattern_learner.learn_from_code_review",
                confidence=confidence,
                tags=tags,
                metadata={
                    "pr_id": pr_id,
                    "comment_index": i,
                    "author": author,
                    "files_changed": files_changed[:5],
                },
            )
            entries.append(entry)

        elapsed = (time.time() - start) * 1000
        with self._lock:
            self._stats["reviews_learned"] += 1
            self._stats["total_time_ms"] += elapsed

        return entries

    def learn_from_test_failure(
        self,
        test_name: str,
        error_message: str,
        traceback: str = "",
        module: str = "",
    ) -> list[KnowledgeEntry]:
        """Extract patterns from a test failure.

        Creates KnowledgeBase entries that capture:
          - The failing test and error type
          - Common failure patterns (assertion, timeout, import, etc.)

        Args:
            test_name: Name of the failing test.
            error_message: Error message from the failure.
            traceback: Optional traceback string.
            module: Optional module where the test failed.

        Returns:
            List of KnowledgeEntry objects created or updated.
        """
        start = time.time()
        entries: list[KnowledgeEntry] = []

        if not test_name or not error_message:
            return entries

        tags = ["test_failure", module] if module else ["test_failure"]
        error_lower = error_message.lower()
        confidence = 0.7

        # Classify error type
        if "assert" in error_lower and "assertionerror" not in error_lower:
            tags.append("assertion")
            pattern = f"Test assertion failed: {test_name} — {error_message[:150]}"
        elif "timeout" in error_lower:
            tags.append("timeout")
            confidence = 0.8
            pattern = f"Test timeout: {test_name} — {error_message[:150]}"
        elif "importerror" in error_lower or "modulenotfound" in error_lower:
            tags.append("import")
            confidence = 0.9
            pattern = f"Import error in test: {test_name} — {error_message[:150]}"
        elif "attributeerror" in error_lower:
            tags.append("api_change")
            confidence = 0.8
            pattern = f"Attribute error (API change?): {test_name} — {error_message[:150]}"
        elif "typeerror" in error_lower or "valueerror" in error_lower:
            tags.append("type_mismatch")
            confidence = 0.6
            pattern = f"Type/value error: {test_name} — {error_message[:150]}"
        else:
            pattern = f"Test failure: {test_name} — {error_message[:150]}"

        entry = self._kb.add_entry(
            pattern_type=TEST_FAILURE_PATTERN,
            pattern=pattern[:MAX_PATTERN_LENGTH],
            source="pattern_learner.learn_from_test_failure",
            confidence=confidence,
            tags=tags,
            metadata={
                "test_name": test_name,
                "module": module,
                "has_traceback": bool(traceback),
            },
        )
        entries.append(entry)

        elapsed = (time.time() - start) * 1000
        with self._lock:
            self._stats["failures_learned"] += 1
            self._stats["total_time_ms"] += elapsed

        return entries

    # ── Recommendation & Query ──────────────────────────────────────────────

    def get_recommendations(
        self,
        error_type: str,
        max_results: int = 10,
    ) -> list[KnowledgeEntry]:
        """Find known solutions for a given error type.

        Searches the KnowledgeBase for similar patterns and returns
        the most relevant solutions.

        Args:
            error_type: The error type or message to find solutions for.
            max_results: Maximum recommendations to return.

        Returns:
            List of KnowledgeEntry objects with known solutions.
        """
        return self._kb.find_similar(
            query=error_type,
            pattern_type=INCIDENT_PATTERN,
            min_confidence=0.3,
            max_results=max_results,
        )

    def get_pattern_trends(self, days: int = 30) -> dict[str, Any]:
        """Analyze pattern trends over time.

        Args:
            days: Lookback period in days.

        Returns:
            Dict with trend analysis data.
        """
        cutoff = time.time() - (days * 86400)
        report = self._kb.get_report()

        # Get recent patterns
        recent = [
            e for e in self._kb._entries  # type: ignore[attr-defined]
            if e.created_at >= cutoff
        ]

        return {
            "total_recent": len(recent),
            "by_type": report.by_type,
            "total_all_time": report.total_entries,
            "most_frequent": report.top_patterns[:5],
            "avg_confidence": report.avg_confidence,
        }

    # ── Reporting ───────────────────────────────────────────────────────────

    def get_report(self) -> PatternLearnerReport:
        """Get current learning statistics."""
        kb_report = self._kb.get_report()

        with self._lock:
            total_extractions = (
                self._stats["incidents_learned"]
                + self._stats["reviews_learned"]
                + self._stats["failures_learned"]
            )
            avg_time = (
                self._stats["total_time_ms"] / max(total_extractions, 1)
            )

        return PatternLearnerReport(
            total_incidents_learned=self._stats["incidents_learned"],
            total_reviews_learned=self._stats["reviews_learned"],
            total_failures_learned=self._stats["failures_learned"],
            total_patterns_extracted=total_extractions,
            knowledge_base_entries=kb_report.total_entries,
            top_patterns=kb_report.top_patterns,
            avg_extraction_time_ms=avg_time,
        )

    # ── Internal ────────────────────────────────────────────────────────────

    def _confidence_from_severity(self, severity: str) -> float:
        """Map incident severity to pattern confidence."""
        mapping = {
            "CRITICAL": 0.9,
            "HIGH": 0.8,
            "MEDIUM": 0.7,
            "NORMAL": 0.6,
            "LOW": 0.5,
        }
        return mapping.get(severity.upper(), 0.5)

# ── Singleton ────────────────────────────────────────────────────────────────

_learner_instance: PatternLearner | None = None
_learner_lock = threading.RLock()


def get_pattern_learner() -> PatternLearner:
    """Get the singleton PatternLearner instance."""
    global _learner_instance
    with _learner_lock:
        if _learner_instance is None:
            _learner_instance = PatternLearner()
        return _learner_instance


def reset_pattern_learner() -> None:
    """Force-reset singleton (for testing)."""
    global _learner_instance
    with _learner_lock:
        _learner_instance = None


# ── CLI ──────────────────────────────────────────────────────────────────────


def _pl_cli() -> None:
    """Pattern Learner CLI entry point. Run with: python -m core.pattern_learner"""
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(
        prog="python -m core.pattern_learner",
        description="Pattern Learner — Extract patterns from incidents, reviews, failures (Pillar 7)",
    )
    ap.add_argument("--recommend", type=str, metavar="ERROR_TYPE",
                    help="Find recommendations for an error type")
    ap.add_argument("--learn-incident", type=str, metavar="TYPE:CAUSE:FIX",
                    help="Learn from an incident (type:cause:fix)")
    ap.add_argument("--learn-review", type=str, metavar="PR_ID:COMMENTS",
                    help="Learn from code review (PR_ID:comment1 | comment2)")
    ap.add_argument("--learn-failure", type=str, metavar="TEST:ERROR:MODULE",
                    help="Learn from test failure (test_name:error_msg:module)")
    ap.add_argument("--report", action="store_true", help="Show pattern learning statistics")
    ap.add_argument("--trends", type=int, nargs="?", const=30, metavar="DAYS",
                    help="Show pattern trends (default: 30 days)")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    learner = get_pattern_learner()

    if args.recommend:
        results = learner.get_recommendations(args.recommend, max_results=10)
        if args.json:
            print(_json.dumps([r.to_dict() for r in results], indent=2))
        else:
            print(f"[PATTERN] Recommendations for '{args.recommend}':\n")
            if not results:
                print("  No recommendations found.")
            for r in results:
                print(f"  [{r.confidence:.0%}] {r.summary()}")
        return

    if args.learn_incident:
        parts = args.learn_incident.split(":", 2)
        if len(parts) != 3:
            print("Error: --learn-incident format must be TYPE:CAUSE:FIX")
            raise SystemExit(1)
        class _MockResult:
            incident_type = parts[0]
            probable_cause = parts[1]
            recommended_fix = parts[2]
            severity = "MEDIUM"
            incident_message = parts[1]
            evidence = []
            impacted_modules = []
        entries = learner.learn_from_incident(_MockResult())
        print(f"[PATTERN] Learned {len(entries)} patterns from incident '{parts[0]}'")
        return

    if args.learn_review:
        pr_parts = args.learn_review.split(":", 1)
        if len(pr_parts) != 2:
            print("Error: --learn-review format must be PR_ID:comment1 | comment2")
            raise SystemExit(1)
        pr_id = pr_parts[0]
        comments = [c.strip() for c in pr_parts[1].split("|") if c.strip()]
        entries = learner.learn_from_code_review(pr_id=pr_id, comments=comments)
        print(f"[PATTERN] Learned {len(entries)} patterns from review {pr_id}")
        return

    if args.learn_failure:
        parts = args.learn_failure.split(":", 2)
        if len(parts) != 3:
            print("Error: --learn-failure format must be TEST:ERROR:MODULE")
            raise SystemExit(1)
        entries = learner.learn_from_test_failure(
            test_name=parts[0], error_message=parts[1], module=parts[2],
        )
        print(f"[PATTERN] Learned {len(entries)} patterns from failure '{parts[0]}'")
        return

    if args.trends:
        trends = learner.get_pattern_trends(days=args.trends)
        if args.json:
            print(_json.dumps(trends, indent=2))
        else:
            print(f"[PATTERN] Trends (last {args.trends} days):")
            print(f"  Recent entries:   {trends['total_recent']}")
            print(f"  All time:         {trends['total_all_time']}")
            print(f"  Avg confidence:   {trends['avg_confidence']:.3f}")
            print(f"  Most frequent:    {trends['most_frequent']}")
        return

    if args.report or not any([args.recommend, args.learn_incident,
                                args.learn_review, args.learn_failure, args.trends]):
        r = learner.get_report()
        if args.json:
            print(_json.dumps(r.to_dict(), indent=2))
        else:
            print("Pattern Learner Report")
            print("======================")
            print(f"  Incidents learned:  {r.total_incidents_learned}")
            print(f"  Reviews learned:    {r.total_reviews_learned}")
            print(f"  Failures learned:   {r.total_failures_learned}")
            print(f"  Patterns extracted: {r.total_patterns_extracted}")
            print(f"  KB entries:         {r.knowledge_base_entries}")
            print(f"  Avg extraction:     {r.avg_extraction_time_ms:.1f}ms")
            if r.top_patterns:
                print("  \nTop patterns:")
                for p in r.top_patterns[:5]:
                    print(f"    [{p['type']}] ({p['frequency']}x) {p['pattern']}")
        return

    ap.print_help()


if __name__ == "__main__":
    _pl_cli()


__all__ = [
    "LearnedPattern",
    "PatternLearner",
    "PatternLearnerReport",
    "get_pattern_learner",
    "reset_pattern_learner",
]
