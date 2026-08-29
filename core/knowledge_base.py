"""Knowledge Base — Persistent store for learned patterns and solutions (Pillar 7).

A shared, cross-domain knowledge store that captures:
  - Incident patterns (from RootCauseAnalyzer)
  - Code review patterns (from PR feedback)
  - Test failure patterns (from test runs)
  - Optimization patterns (from auto_tuner / autonomous_optimizer)
  - Proven solutions and workarounds

Provides:
  - Thread-safe CRUD with JSON persistence
  - Similarity search by pattern or error type
  - Frequency tracking (which patterns recur most)
  - Confidence scoring per entry
  - Tag-based categorization

Usage:
    from core.knowledge_base import get_knowledge_base

    kb = get_knowledge_base()
    kb.add_entry(
        pattern_type="INCIDENT_PATTERN",
        pattern="broker_disconnect due to token expiry",
        solution="Refresh API token before expiry window",
        source="root_cause_analyzer",
    )
    results = kb.find_similar("broker_disconnect")
    for r in results:
        print(f"  [{r.frequency}x] {r.pattern} -> {r.solution}")
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

KNOWLEDGE_DB_PATH = Path("json/knowledge_base.json")
MAX_ENTRIES = 2000

# Pattern type constants
INCIDENT_PATTERN = "INCIDENT_PATTERN"
CODE_REVIEW_PATTERN = "CODE_REVIEW_PATTERN"
TEST_FAILURE_PATTERN = "TEST_FAILURE_PATTERN"
OPTIMIZATION_PATTERN = "OPTIMIZATION_PATTERN"
BEST_PRACTICE = "BEST_PRACTICE"
LESSON_LEARNED = "LESSON_LEARNED"

VALID_TYPES = frozenset({
    INCIDENT_PATTERN,
    CODE_REVIEW_PATTERN,
    TEST_FAILURE_PATTERN,
    OPTIMIZATION_PATTERN,
    BEST_PRACTICE,
    LESSON_LEARNED,
})


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class KnowledgeEntry:
    """A single learned pattern with its solution.

    Attributes:
        entry_id: Unique identifier.
        pattern_type: Category (INCIDENT_PATTERN, CODE_REVIEW_PATTERN, etc.).
        pattern: Description of the pattern observed.
        solution: Known solution or recommended action.
        source: Where this pattern was learned from (module name).
        confidence: Confidence score 0.0-1.0 based on evidence strength.
        frequency: How many times this pattern has been observed.
        tags: Classification tags for filtering.
        created_at: When the entry was first created.
        updated_at: When the entry was last updated.
        related_entries: IDs of related knowledge entries.
        metadata: Additional structured data.
    """

    entry_id: str = ""
    pattern_type: str = BEST_PRACTICE
    pattern: str = ""
    solution: str = ""
    source: str = ""
    confidence: float = 0.5
    frequency: int = 1
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    related_entries: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "pattern_type": self.pattern_type,
            "pattern": self.pattern,
            "solution": self.solution,
            "source": self.source,
            "confidence": round(self.confidence, 3),
            "frequency": self.frequency,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "related_entries": self.related_entries,
            "metadata": self.metadata,
        }

    def summary(self) -> str:
        return (
            f"[{self.pattern_type}] ({self.frequency}x, conf={self.confidence:.0%}) "
            f"{self.pattern[:80]} → {self.solution[:80]}"
        )


@dataclass
class KnowledgeBaseReport:
    """Snapshot of knowledge base statistics."""

    total_entries: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_tag: dict[str, int] = field(default_factory=dict)
    top_patterns: list[dict[str, Any]] = field(default_factory=list)
    top_solutions: list[dict[str, Any]] = field(default_factory=list)
    avg_confidence: float = 0.0
    total_frequency: int = 0
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_entries": self.total_entries,
            "by_type": self.by_type,
            "by_tag": self.by_tag,
            "top_patterns": self.top_patterns[:10],
            "top_solutions": self.top_solutions[:10],
            "avg_confidence": round(self.avg_confidence, 3),
            "total_frequency": self.total_frequency,
            "timestamp": self.timestamp,
        }


# ── Knowledge Base ───────────────────────────────────────────────────────────


class KnowledgeBase:
    """Persistent, thread-safe knowledge store for patterns and solutions.

    Supports:
      - Add new entries (auto-deduplication)
      - Find similar entries by pattern or error type
      - Tag-based and type-based filtering
      - Frequency tracking for recurring patterns
      - JSON persistence with atomic writes
    """

    def __init__(self, db_path: str | Path = KNOWLEDGE_DB_PATH) -> None:
        self._lock = threading.RLock()
        self._db_path = Path(db_path)
        self._entries: list[KnowledgeEntry] = []
        self._next_id = 1
        self._load()

    # ── Public API ──────────────────────────────────────────────────────────

    def add_entry(
        self,
        pattern_type: str,
        pattern: str,
        solution: str = "",
        source: str = "",
        confidence: float = 0.5,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeEntry:
        """Add a new pattern entry, or increment frequency if similar exists.

        Args:
            pattern_type: Category constant (INCIDENT_PATTERN, etc.).
            pattern: Description of the pattern.
            solution: Known solution or recommendation.
            source: Module or origin of this pattern.
            confidence: Confidence score 0.0-1.0.
            tags: Optional classification tags.
            metadata: Optional additional structured data.

        Returns:
            The created or updated KnowledgeEntry.
        """
        ptype = pattern_type if pattern_type in VALID_TYPES else BEST_PRACTICE
        tags = tags or []

        with self._lock:
            # Check for similar existing entry (same type + fuzzy pattern match)
            existing = self._find_duplicate(ptype, pattern)
            if existing:
                existing.frequency += 1
                existing.updated_at = time.time()
                # Boost confidence with repeated observations
                existing.confidence = min(1.0, existing.confidence + 0.05)
                # Merge tags
                for t in tags:
                    if t not in existing.tags:
                        existing.tags.append(t)
                if solution and not existing.solution:
                    existing.solution = solution
                self._save()
                return existing

            # Create new entry
            entry = KnowledgeEntry(
                entry_id=f"KB-{self._next_id:06d}",
                pattern_type=ptype,
                pattern=pattern,
                solution=solution,
                source=source,
                confidence=min(1.0, max(0.1, confidence)),
                frequency=1,
                tags=tags,
                metadata=metadata or {},
            )
            self._next_id += 1
            self._entries.append(entry)

            # Enforce max entries
            if len(self._entries) > MAX_ENTRIES:
                # Remove oldest, lowest-frequency entries
                self._entries.sort(key=lambda e: (e.frequency, e.created_at))
                self._entries = self._entries[-MAX_ENTRIES:]

            self._save()
            return entry

    def find_similar(
        self,
        query: str,
        pattern_type: str | None = None,
        min_confidence: float = 0.0,
        max_results: int = 20,
    ) -> list[KnowledgeEntry]:
        """Find similar entries by keyword matching.

        Args:
            query: Search text (will match against pattern, solution, tags).
            pattern_type: Optional filter by type.
            min_confidence: Minimum confidence threshold.
            max_results: Maximum results to return.

        Returns:
            List of matching KnowledgeEntry objects, sorted by relevance.
        """
        query_lower = query.lower()
        query_keywords = set(query_lower.split())

        with self._lock:
            candidates = self._entries
            if pattern_type:
                candidates = [e for e in candidates if e.pattern_type == pattern_type]
            if min_confidence > 0:
                candidates = [e for e in candidates if e.confidence >= min_confidence]

            scored: list[tuple[float, KnowledgeEntry]] = []
            for entry in candidates:
                score = 0.0
                text = (entry.pattern + " " + entry.solution + " " + " ".join(entry.tags)).lower()

                # Exact phrase match (highest weight)
                if query_lower in text:
                    score += 3.0

                # Keyword matches
                tokens = set(text.split())
                matches = query_keywords & tokens
                score += len(matches) * 1.5

                # Frequency bonus
                score += min(2.0, entry.frequency * 0.2)

                # Confidence bonus
                score += entry.confidence

                if score > 0:
                    scored.append((score, entry))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [entry for _, entry in scored[:max_results]]

    def get_by_type(self, pattern_type: str) -> list[KnowledgeEntry]:
        """Get all entries of a given type."""
        with self._lock:
            return [e for e in self._entries if e.pattern_type == pattern_type]

    def get_by_tag(self, tag: str) -> list[KnowledgeEntry]:
        """Get all entries with a specific tag."""
        with self._lock:
            return [e for e in self._entries if tag in e.tags]

    def get_by_id(self, entry_id: str) -> KnowledgeEntry | None:
        """Get a single entry by ID."""
        with self._lock:
            for e in self._entries:
                if e.entry_id == entry_id:
                    return e
            return None

    def remove_entry(self, entry_id: str) -> bool:
        """Remove an entry by ID. Returns True if found and removed."""
        with self._lock:
            for i, e in enumerate(self._entries):
                if e.entry_id == entry_id:
                    del self._entries[i]
                    self._save()
                    return True
            return False

    def update_entry(
        self,
        entry_id: str,
        solution: str | None = None,
        confidence: float | None = None,
        tags: list[str] | None = None,
    ) -> KnowledgeEntry | None:
        """Update an existing entry's solution, confidence, or tags."""
        with self._lock:
            entry = self.get_by_id(entry_id)
            if entry is None:
                return None
            if solution is not None:
                entry.solution = solution
            if confidence is not None:
                entry.confidence = min(1.0, max(0.1, confidence))
            if tags is not None:
                entry.tags = list(set(entry.tags + tags))
            entry.updated_at = time.time()
            self._save()
            return entry

    def get_report(self) -> KnowledgeBaseReport:
        """Generate statistics report about the knowledge base."""
        with self._lock:
            by_type: dict[str, int] = {}
            by_tag: dict[str, int] = {}
            total_conf = 0.0
            total_freq = 0

            for e in self._entries:
                by_type[e.pattern_type] = by_type.get(e.pattern_type, 0) + 1
                for t in e.tags:
                    by_tag[t] = by_tag.get(t, 0) + 1
                total_conf += e.confidence
                total_freq += e.frequency

            # Top patterns by frequency
            sorted_by_freq = sorted(self._entries, key=lambda e: e.frequency, reverse=True)
            top_patterns = [
                {"pattern": e.pattern[:80], "frequency": e.frequency, "type": e.pattern_type}
                for e in sorted_by_freq[:10]
            ]

            # Top solutions by confidence
            sorted_by_conf = sorted(self._entries, key=lambda e: e.confidence, reverse=True)
            top_solutions = [
                {"pattern": e.pattern[:60], "solution": e.solution[:60], "confidence": e.confidence}
                for e in sorted_by_conf[:10]
            ]

            return KnowledgeBaseReport(
                total_entries=len(self._entries),
                by_type=by_type,
                by_tag=by_tag,
                top_patterns=top_patterns,
                top_solutions=top_solutions,
                avg_confidence=total_conf / max(len(self._entries), 1),
                total_frequency=total_freq,
            )

    def clear(self) -> None:
        """Clear all entries (for testing)."""
        with self._lock:
            self._entries.clear()
            self._next_id = 1
            self._save()

    # ── Internal ────────────────────────────────────────────────────────────

    def _find_duplicate(self, pattern_type: str, pattern: str) -> KnowledgeEntry | None:
        """Find a duplicate entry by type and pattern similarity."""
        pattern_lower = pattern.lower()
        pattern_keywords = set(pattern_lower.split())

        for entry in self._entries:
            if entry.pattern_type != pattern_type:
                continue
            entry_lower = entry.pattern.lower()

            # Exact match
            if entry_lower == pattern_lower:
                return entry

            # High keyword overlap (70%+)
            entry_keywords = set(entry_lower.split())
            if len(pattern_keywords) > 0 and len(entry_keywords) > 0:
                overlap = len(pattern_keywords & entry_keywords)
                smaller = min(len(pattern_keywords), len(entry_keywords))
                if smaller > 0 and overlap / smaller >= 0.7:
                    return entry

        return None

    def _load(self) -> None:
        """Load entries from JSON file."""
        try:
            if self._db_path.is_file():
                data = json.loads(self._db_path.read_text(encoding="utf-8"))
                self._entries = [KnowledgeEntry(**item) for item in data.get("entries", [])]
                self._next_id = data.get("next_id", len(self._entries) + 1)
                _log.info("[KB] Loaded %d entries from %s", len(self._entries), self._db_path)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            _log.debug("[KB] Load failed: %s", exc)

    def _save(self) -> None:
        """Save entries to JSON file atomically."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db_path.write_text(
                json.dumps({
                    "next_id": self._next_id,
                    "entries": [e.to_dict() for e in self._entries],
                }, indent=2),
                encoding="utf-8",
            )
        except (OSError, TypeError) as exc:
            _log.debug("[KB] Save failed: %s", exc)


# ── Singleton ────────────────────────────────────────────────────────────────

_kb_instance: KnowledgeBase | None = None
_kb_lock = threading.RLock()


def get_knowledge_base() -> KnowledgeBase:
    """Get the singleton KnowledgeBase instance."""
    global _kb_instance
    with _kb_lock:
        if _kb_instance is None:
            _kb_instance = KnowledgeBase()
        return _kb_instance


def reset_knowledge_base() -> None:
    """Force-reset singleton (for testing)."""
    global _kb_instance
    with _kb_lock:
        _kb_instance = None


# ── CLI ──────────────────────────────────────────────────────────────────────


def _kb_cli() -> None:
    """Knowledge Base CLI entry point. Run with: python -m core.knowledge_base"""
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m core.knowledge_base",
        description="Knowledge Base — Persistent pattern and solution store (Pillar 7)",
    )
    ap.add_argument("--query", type=str, help="Search patterns by keyword")
    ap.add_argument("--search", type=str, help="Alias for --query: search patterns by keyword")
    ap.add_argument("--add", type=str, metavar="TYPE:PATTERN:SOLUTION",
                    help="Add a new entry (e.g. BEST_PRACTICE:Use caching:Cache API responses)")
    ap.add_argument("--report", action="store_true", help="Show knowledge base statistics")
    ap.add_argument("--type", type=str, default="", help="Filter by pattern type (with --query / --search)")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    ap.add_argument("--clear", action="store_true", help="Clear all entries")
    args = ap.parse_args()

    kb = get_knowledge_base()

    if args.clear:
        kb.clear()
        print("[KB] All entries cleared")
        return

    if args.add:
        parts = args.add.split(":", 2)
        if len(parts) != 3:
            print("Error: --add format must be TYPE:PATTERN:SOLUTION")
            raise SystemExit(1)
        e = kb.add_entry(pattern_type=parts[0], pattern=parts[1], solution=parts[2], source="cli")
        print(f"[KB] Added: {e.summary()}")
        return

    # Resolve search query from --query or --search
    search_query = args.query or args.search
    if search_query:
        ptype = args.type if args.type else None
        results = kb.find_similar(search_query, pattern_type=ptype, max_results=20)
        if args.json:
            print(json.dumps([r.to_dict() for r in results], indent=2))
        else:
            print(f"[KB] Found {len(results)} matching patterns for '{search_query}':\n")
            for r in results:
                print(f"  {r.summary()}")
        return

    if args.report or not any([search_query, args.add, args.clear]):
        r = kb.get_report()
        if args.json:
            print(json.dumps(r.to_dict(), indent=2))
        else:
            print("Knowledge Base Report")
            print("=====================")
            print(f"  Total entries:    {r.total_entries}")
            print(f"  By type:          {r.by_type}")
            print(f"  By tag:           {dict(list(r.by_tag.items())[:10])}")
            print(f"  Avg confidence:   {r.avg_confidence:.3f}")
            print(f"  Total frequency:  {r.total_frequency}")
            print("  \nTop patterns:")
            for p in r.top_patterns[:5]:
                print(f"    [{p['type']}] ({p['frequency']}x) {p['pattern']}")
            print("  \nTop solutions:")
            for s in r.top_solutions[:3]:
                print(f"    [{s['confidence']:.0%}] {s['solution']}")
        return

    ap.print_help()


if __name__ == "__main__":
    _kb_cli()


__all__ = [
    "BEST_PRACTICE",
    "CODE_REVIEW_PATTERN",
    "INCIDENT_PATTERN",
    "KNOWLEDGE_DB_PATH",
    "LESSON_LEARNED",
    "MAX_ENTRIES",
    "OPTIMIZATION_PATTERN",
    "TEST_FAILURE_PATTERN",
    "VALID_TYPES",
    "KnowledgeBase",
    "KnowledgeBaseReport",
    "KnowledgeEntry",
    "get_knowledge_base",
    "reset_knowledge_base",
]
