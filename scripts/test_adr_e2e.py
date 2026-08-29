#!/usr/bin/env python3
"""End-to-End ADR Import, Q&A, and Decision Graph Validation Test.

Tests the complete Decision Memory pipeline:
  1. Reset memory to clean state (including persistence file)
  2. Import all 21 ADR documents from docs/adr/
  3. Verify every ADR was imported with correct metadata
  4. Run Q&A queries against imported decisions
  5. Validate the decision dependency graph output
  6. Verify search functionality
  7. Test import idempotency (no duplicates)

Usage:
    python scripts/test_adr_e2e.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Ensure project root in sys.path
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── Imports ──────────────────────────────────────────────────────────────────

from core.decision_memory import (
    get_decision_memory,
    reset_decision_memory,
)

# ── Test harness ─────────────────────────────────────────────────────────────

_PASSED = 0
_FAILED = 0
_TOTAL = 0


def _assert(condition: bool, message: str) -> None:
    global _PASSED, _FAILED, _TOTAL
    _TOTAL += 1
    if condition:
        _PASSED += 1
        print(f"  [PASS] {message}")
    else:
        _FAILED += 1
        print(f"  [FAIL] {message}")


def print_header(title: str) -> None:
    w = 70
    print()
    print("=" * w)
    print(f"  {title}")
    print("=" * w)


def print_summary() -> None:
    w = 70
    print()
    print("=" * w)
    print(f"  RESULTS: {_PASSED}/{_TOTAL} passed, {_FAILED} failed")
    print("=" * w)
    if _FAILED == 0:
        print("  ALL TESTS PASSED")
    else:
        print(f"  {_FAILED} TEST(S) FAILED")


# ── Test: ADR Import ─────────────────────────────────────────────────────────

def test_import_all_adrs() -> object:
    """Import all ADRs and return the memory instance."""
    reset_decision_memory()
    mem = get_decision_memory()
    mem.clear_all()  # Ensure clean state (deletes persistence file)

    adr_dir = Path("docs/adr")
    assert adr_dir.is_dir(), f"ADR directory not found: {adr_dir}"

    # Count ADR files (exclude README.md)
    adr_files = sorted([f for f in adr_dir.glob("*.md") if f.name.lower() != "readme.md"])
    print(f"\n  Found {len(adr_files)} ADR files in {adr_dir}")

    # Import all ADRs
    imported = mem.scan_adr_directory("docs/adr")
    _assert(len(imported) == len(adr_files),
            f"Imported {len(imported)}/{len(adr_files)} ADRs")

    # Verify memory state
    report = mem.get_report()
    _assert(report.total_decisions == len(adr_files),
            f"Memory has {report.total_decisions} decisions (expected {len(adr_files)})")
    _assert(report.by_status.get("ACCEPTED", 0) >= len(adr_files) - 3,
            f"Most ADRs should be ACCEPTED (found {report.by_status.get('ACCEPTED', 0)} accepted)")

    return mem


def test_individual_adr_imports(mem) -> None:
    """Verify each ADR has correct metadata."""
    report = mem.get_report()
    recent = sorted(report.recent_decisions, key=lambda d: d.created_at)

    # Check every decision has required fields
    for i, d in enumerate(recent):
        _assert(bool(d.title), f"ADR #{i+1} has a title")
        _assert(bool(d.decision) or bool(d.context),
                f"ADR #{i+1} ('{str(d.title)[:40]}') has decision or context")
        _assert(bool(d.adr_path), f"ADR #{i+1} has adr_path set")
        _assert(d.status in ("ACCEPTED", "PROPOSED", "DEPRECATED", "SUPERSEDED", "REJECTED"),
                f"ADR #{i+1} has valid status: {d.status}")
        _assert("adr" in d.tags,
                f"ADR #{i+1} has 'adr' tag")

    print(f"\n  Verified all {len(recent)} ADRs have correct metadata")


def test_qa_queries(mem) -> None:
    """Run Q&A queries against the imported ADRs and verify answers."""
    print_header("Q&A Queries")

    qa_tests = [
        ("Why did we adopt the state machine?", "state machine", "why"),
        ("What is the broker abstraction?", "broker", "what"),
        ("When was the event-driven architecture decision made?", "architecture", "when"),
        ("Who approved the architecture governance?", "governance", "who"),
        ("What alternatives were considered for the database?", "PostgreSQL", "alternatives"),
        ("What is the status of the replay engine?", "replay", "status"),
        ("What is the impact of the broker abstraction?", "broker", "impact"),
        ("What decisions depend on the formal state machine?", "state machine", "dependencies"),
        ("Why was SQLite with WAL chosen?", "SQLite", "why"),
        ("What is the reversal strategy for blue-green deployment?", "deployment", "reversal"),
    ]

    for question, keyword, expected_intent in qa_tests:
        answer = mem.ask_question(question)
        has_answer = bool(answer.answer) and answer.confidence > 0
        _assert(has_answer,
                f"Q: '{question[:50]}...' answered (conf={answer.confidence:.0%}, intent={answer.intent})")
        if has_answer:
            matched_intent = answer.intent == expected_intent
            _assert(matched_intent or answer.confidence > 0.3,
                    f"  Intent match: got '{answer.intent}', expected '{expected_intent}' (conf={answer.confidence:.0%})")
            if answer.source_decision_id:
                _assert(answer.source_title != "",
                        f"  Source: {str(answer.source_title)[:50]}")

    # Non-matching question test (should return low confidence < 50%)
    no_match = mem.ask_question("What is the color of the trading bot?")
    _assert(no_match.confidence < 0.5,
            f"Non-matching question returns low confidence (got {no_match.confidence:.0%})")


def test_decision_graph(mem) -> None:
    """Validate the decision dependency graph output."""
    print_header("Decision Graph Validation")

    graph = mem.get_decision_graph()

    _assert("nodes" in graph, "Graph has 'nodes' key")
    _assert("edges" in graph, "Graph has 'edges' key")

    nodes = graph["nodes"]
    edges = graph["edges"]

    _assert(len(nodes) >= 20, f"Graph has {len(nodes)} nodes (expected >= 20)")
    _assert(isinstance(edges, list), "Edges is a list")

    # Verify node structure
    if nodes:
        first = nodes[0]
        _assert("id" in first, "Node has 'id'")
        _assert("label" in first, "Node has 'label'")
        _assert("status" in first, "Node has 'status'")
        _assert("priority" in first, "Node has 'priority'")

    # Verify edge structure
    if edges:
        first_edge = edges[0]
        _assert("from" in first_edge, "Edge has 'from'")
        _assert("to" in first_edge, "Edge has 'to'")
        _assert("type" in first_edge, "Edge has 'type'")

    # Check all node IDs are valid decision IDs
    node_ids = {n["id"] for n in nodes}
    report = mem.get_report()
    for d in report.recent_decisions[:5]:
        _assert(d.decision_id in node_ids,
                f"Decision '{d.decision_id}' is in graph nodes")

    print(f"\n  Graph: {len(nodes)} nodes, {len(edges)} edges")


def test_report_analytics(mem) -> None:
    """Validate the decision memory report analytics."""
    print_header("Report Analytics")

    report = mem.get_report()

    _assert(report.total_decisions >= 20,
            f"Total decisions: {report.total_decisions}")
    _assert(len(report.by_status) >= 1,
            f"Status distribution: {report.by_status}")
    _assert(len(report.recent_decisions) >= 10,
            f"Recent decisions: {len(report.recent_decisions)}")
    _assert(report.decision_velocity_per_week > 0,
            f"Decision velocity: {report.decision_velocity_per_week:.1f}/week")
    _assert(report.acceptance_rate > 0,
            f"Acceptance rate: {report.acceptance_rate:.0%}")

    # Verify stats
    stats = mem.get_stats()
    _assert(stats["total_decisions"] >= 20,
            f"Stats total: {stats['total_decisions']}")
    _assert(stats["decisions_with_reversal"] >= 0,
            "Stats reversal count valid")
    _assert(stats["unique_tags"] >= 2,
            f"Unique tags: {stats['unique_tags']}")

    # Timeline
    timeline = mem.get_timeline(limit=30)
    _assert(len(timeline) >= 20,
            f"Timeline entries: {len(timeline)}")
    if timeline:
        _assert(bool(timeline[0].date), "Timeline entry has date")
        _assert(bool(timeline[0].title), "Timeline entry has title")

    print(f"\n  Report: {report.total_decisions} decisions, "
          f"{report.decision_velocity_per_week:.1f}/week velocity, "
          f"{report.acceptance_rate:.0%} acceptance")


def test_search_functionality(mem) -> None:
    """Validate search functionality."""
    print_header("Search Functionality")

    # Search by keyword
    results = mem.search(query="broker")
    _assert(len(results) > 0,
            f"Search 'broker' found {len(results)} results")

    # Search with status filter
    accepted = mem.search(query="", status="ACCEPTED")
    _assert(len(accepted) > 0,
            f"Search status=ACCEPTED found {len(accepted)} results")

    # Search with tag
    adr_tagged = mem.search(query="", tag="adr")
    _assert(len(adr_tagged) >= 20,
            f"Search tag=adr found {len(adr_tagged)} results")

    # Verify result structure
    if results:
        r = results[0]
        _assert(bool(r.decision_id), "Search result has decision_id")
        _assert(bool(r.title), "Search result has title")
        _assert(r.score > 0, f"Search result has score: {r.score}")
        _assert(len(r.matched_keywords) > 0,
                f"Search result has matched keywords: {r.matched_keywords[:3]}")


def test_import_idempotency(mem) -> None:
    """Verify that re-importing same ADRs doesn't create duplicates."""
    print_header("Import Idempotency")

    # Get decision count via stats
    stats = mem.get_stats()
    count_before = stats["total_decisions"]

    # Scan again -- should skip already-imported ADRs
    second_batch = mem.scan_adr_directory("docs/adr")
    _assert(len(second_batch) == 0,
            f"Second import produced {len(second_batch)} new ADRs (expected 0)")

    stats_after = mem.get_stats()
    _assert(stats_after["total_decisions"] == count_before,
            f"Decision count unchanged: {count_before} -> {stats_after['total_decisions']}")

    print(f"\n  Idempotency verified: count stays at {count_before}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    print()
    print("=" * 70)
    print("  ADR END-TO-END TEST")
    print("  Decision Memory: Import, Q&A, Graph, and Analytics")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Step 1: Import all ADRs
    print_header("Step 1: Import All 21 ADRs")
    mem = test_import_all_adrs()

    # Step 2: Verify individual ADRs
    print_header("Step 2: Verify Individual ADR Metadata")
    test_individual_adr_imports(mem)

    # Step 3: Q&A
    print_header("Step 3: Q&A Engine")
    test_qa_queries(mem)

    # Step 4: Decision Graph
    print_header("Step 4: Decision Graph")
    test_decision_graph(mem)

    # Step 5: Search
    print_header("Step 5: Search")
    test_search_functionality(mem)

    # Step 6: Report Analytics
    print_header("Step 6: Report Analytics")
    test_report_analytics(mem)

    # Step 7: Idempotency
    print_header("Step 7: Import Idempotency")
    test_import_idempotency(mem)

    # Summary
    print_summary()

    # Export graph to JSON for inspection
    graph = mem.get_decision_graph()
    graph_path = Path("docs/decision_graph.json")
    graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    print(f"\n  Decision graph exported to: {graph_path}")

    # Cleanup: reset memory for subsequent runs
    reset_decision_memory()

    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
