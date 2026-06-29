#!/usr/bin/env python3
"""
Register comprehensive evidence for all 31 constitution categories.

This script uses the shared evidence definitions from
core/constitution_evidence_data.py and registers them into the
constitution validator singleton.

Usage:
    python scripts/register_constitution_evidence.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.constitution import get_validator
from core.constitution_evidence_data import Evidence, collect_all_evidence


def register_all_evidence(evidence: Evidence) -> dict[str, int]:
    """Register all evidence items into the constitution validator.

    Returns:
        Dict mapping category_id -> number of evidence items registered.
    """
    validator = get_validator()
    counts: dict[str, int] = {}

    for category_id, items in sorted(evidence.items()):
        count = 0
        for item in items:
            ok = validator.add_evidence(
                category_id=category_id,
                description=item["desc"],
                evidence_type=item["type"],
                weight=item["weight"],
            )
            if ok:
                count += 1
        counts[category_id] = count

    return counts


def print_report(evidence: Evidence, counts: dict[str, int]) -> None:
    """Print a summary of registered evidence."""
    print("=" * 70)
    print("  CONSTITUTION EVIDENCE REGISTRATION REPORT")
    print("=" * 70)

    total_evidence = sum(counts.values())
    categories_with_evidence = sum(1 for c in counts.values() if c > 0)
    print(f"  Categories with evidence: {categories_with_evidence} / {len(evidence)}")
    print(f"  Total evidence items: {total_evidence}")
    print()

    for category_id, items in sorted(evidence.items()):
        c = counts.get(category_id, 0)
        weight_total = sum(item["weight"] for item in items if item.get("desc"))
        status = "[OK]" if c > 0 else "[--]"
        print(f"  {status} {category_id}: {c} items (total weight: {weight_total:.1f})")
        for item in items:
            print(f"       [{item['type']}] ({item['weight']}) {item['desc'][:90]}...")
    print()
    print("=" * 70)


def main() -> int:
    print("Collecting evidence from codebase...")
    evidence = collect_all_evidence()

    print(f"Registering evidence for {len(evidence)} categories...")
    counts = register_all_evidence(evidence)

    print_report(evidence, counts)

    # Print the new constitution scores
    print("\nUpdated Constitution Scores:")
    print("-" * 70)

    validator = get_validator()
    report = validator.generate_report()
    for cid in sorted(report.categories.keys()):
        cat = report.categories[cid]
        evidence_count = len(cat.evidence)
        status = "[OK]" if evidence_count > 0 else "[--]"
        print(f"  {status} {cid} [{cat.category_name:30s}] {cat.effective_score:.2f}/{cat.max_score}  ({evidence_count} evidence items)")

    print(f"\n  Overall score: {report.overall_score:.2f}")
    print(f"  Total evidence: {report.total_evidence_items}")
    print(f"  Open regressions: {report.open_regressions}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
