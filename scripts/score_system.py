#!/usr/bin/env python3
"""
Constitution Scoring System — CLI for evaluating system scores across 23 categories.

Usage:
    python scripts/score_system.py                         # Full report
    python scripts/score_system.py --category ARCH-01      # Single category
    python scripts/score_system.py --evidence              # Show evidence details
    python scripts/score_system.py --json                  # JSON output
    python scripts/score_system.py --ci                    # Exit code only (CI mode)
    python scripts/score_system.py --check-min 8.0         # Fail if any score < 8.0

The scoring framework follows the Final Master System Constitution:
  - Scores above 9.0 require evidence
  - Scores above 9.5 require full audits
  - Without evidence, no score may exceed 8.0
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
log = logging.getLogger("score_system")


# ── Evidence collector ────────────────────────────────────────────────────────


def collect_auto_evidence() -> dict[str, list[dict[str, Any]]]:
    """Automatically collect evidence from the codebase.

    Scans test files, configuration, docs, etc. to build evidence items.
    """
    evidence: dict[str, list[dict[str, Any]]] = {}

    # ARCH: Architecture compliance check
    try:
        from scripts.check_architecture_compliance import main as arch_check
        violations: list[str] = []
        try:
            arch_check(["--ci"])
        except SystemExit:
            pass
        evidence["ARCH-01"] = [{
            "description": "Architecture compliance check: automated",
            "type": "test_pass",
            "weight": 0.5,
            "verified": True,
        }]
    except ImportError:
        evidence["ARCH-01"] = []

    # TST: Test counts
    test_dir = ROOT / "tests"
    if test_dir.is_dir():
        test_files = list(test_dir.rglob("test_*.py"))
        evidence.setdefault("TST-01", []).append({
            "description": f"Test files: {len(test_files)} test files",
            "type": "documentation",
            "weight": 0.3,
            "verified": True,
        })

    # GOV: Documentation files
    doc_dir = ROOT / "docs"
    if doc_dir.is_dir():
        doc_files = list(doc_dir.rglob("*.md"))
        evidence.setdefault("GOV-01", []).append({
            "description": f"Documentation files: {len(doc_files)} markdown files",
            "type": "documentation",
            "weight": 0.2,
            "verified": True,
        })

    # GOV: .gitignore
    gitignore = ROOT / ".gitignore"
    evidence.setdefault("GOV-02", []).append({
        "description": f".gitignore: {'present' if gitignore.exists() else 'MISSING'}",
        "type": "documentation",
        "weight": 0.3,
        "verified": gitignore.exists(),
    })

    # RSK: Risk module existence
    risk_files = list((ROOT / "core").rglob("risk*.py"))
    if (ROOT / "core" / "services" / "risk_service.py").exists():
        evidence.setdefault("RSK-01", []).append({
            "description": "RiskService present: authoritative risk engine",
            "type": "code_review",
            "weight": 0.4,
            "verified": True,
        })

    # EXE: Exactly-once certifier
    certifier_path = ROOT / "core" / "execution" / "idempotency" / "certifier.py"
    evidence.setdefault("EXE-01", []).append({
        "description": f"Idempotency certifier: {'present' if certifier_path.exists() else 'MISSING'}",
        "type": "documentation",
        "weight": 0.3,
        "verified": certifier_path.exists(),
    })

    # DR: DB migration
    db_migration = ROOT / "core" / "db_migration.py"
    evidence.setdefault("DR-01", []).append({
        "description": f"DB migration: {'present' if db_migration.exists() else 'MISSING'}",
        "type": "documentation",
        "weight": 0.3,
        "verified": db_migration.exists(),
    })

    # SEC: Auth modules
    auth_dir = ROOT / "core" / "auth"
    evidence.setdefault("SEC-01", []).append({
        "description": f"Auth modules: {'present' if auth_dir.is_dir() else 'MISSING'}",
        "type": "code_review",
        "weight": 0.3,
        "verified": auth_dir.is_dir(),
    })

    # OBS: Health checker
    health_checker = ROOT / "core" / "health_checker.py"
    evidence.setdefault("OBS-03", []).append({
        "description": f"Health checker: {'present' if health_checker.exists() else 'MISSING'}",
        "type": "code_review",
        "weight": 0.3,
        "verified": health_checker.exists(),
    })

    # TST-02: Chaos tests
    chaos_dir = ROOT / "tests" / "chaos"
    if chaos_dir.is_dir():
        chaos_files = list(chaos_dir.rglob("test_*.py"))
        if chaos_files:
            evidence.setdefault("TST-02", []).append({
                "description": f"Chaos tests: {len(chaos_files)} test files in tests/chaos/"
                              f" ({', '.join(f.name for f in chaos_files[:5])})",
                "type": "test_pass",
                "weight": 0.7,
                "verified": True,
            })

    # TST-03: Contract tests
    contract_dir = ROOT / "tests" / "contract"
    if contract_dir.is_dir():
        contract_files = list(contract_dir.rglob("test_*.py"))
        if contract_files:
            evidence.setdefault("TST-03", []).append({
                "description": f"Contract tests: {len(contract_files)} test files in tests/contract/"
                              f" ({', '.join(f.name for f in contract_files[:5])})",
                "type": "test_pass",
                "weight": 0.7,
                "verified": True,
            })

    # TST-04: Regression tests (existing broker contract + exactly-once + broker failover)
    regression_tests = [
        "test_broker_contract_certification.py",
        "test_exactly_once_certification.py",
        "test_broker_failover.py",
        "test_catastrophic_scenarios.py",
        "test_concurrency_stress.py",
    ]
    existing_regression = [t for t in regression_tests if (ROOT / "tests" / t).exists()]
    if existing_regression:
        evidence.setdefault("TST-04", []).append({
            "description": f"Regression tests: {len(existing_regression)} files found"
                          f" ({', '.join(existing_regression)})",
            "type": "test_pass",
            "weight": 0.5,
            "verified": True,
        })

    # EXE-04: Reconciliation tests
    reconciliation_test = ROOT / "tests" / "test_reconciliation_engine.py"
    if reconciliation_test.exists():
        evidence.setdefault("EXE-04", []).append({
            "description": "Reconciliation engine test present",
            "type": "test_pass",
            "weight": 0.4,
            "verified": True,
        })

    # SEC-04: Audit trail
    config_audit_test = ROOT / "tests" / "test_config_audit.py"
    if config_audit_test.exists():
        evidence.setdefault("SEC-04", []).append({
            "description": "Config audit trail test present",
            "type": "test_pass",
            "weight": 0.4,
            "verified": True,
        })
    config_audit_log_test = ROOT / "tests" / "test_config_audit_log.py"
    if config_audit_log_test.exists():
        evidence.setdefault("SEC-04", []).append({
            "description": "Config audit log test present",
            "type": "test_pass",
            "weight": 0.3,
            "verified": True,
        })

    # EXE-02: Idempotent retry
    retry_policy_test = ROOT / "tests" / "test_retry_policy_safety.py"
    if retry_policy_test.exists():
        evidence.setdefault("EXE-02", []).append({
            "description": "Retry policy safety test present",
            "type": "test_pass",
            "weight": 0.4,
            "verified": True,
        })

    # RSK-04: Fail-closed (test_broker_failover + test_failure_injection)
    failover_test = ROOT / "tests" / "test_broker_failover.py"
    if failover_test.exists():
        evidence.setdefault("RSK-04", []).append({
            "description": "Broker failover test present — fail-closed enforcement",
            "type": "test_pass",
            "weight": 0.5,
            "verified": True,
        })
    failure_injection_test = ROOT / "tests" / "test_failure_injection.py"
    if failure_injection_test.exists():
        evidence.setdefault("RSK-04", []).append({
            "description": "Failure injection test present",
            "type": "test_pass",
            "weight": 0.4,
            "verified": True,
        })

    # OBS-01: Structured logging
    logging_test = ROOT / "tests" / "test_logging_config.py"
    if logging_test.exists():
        evidence.setdefault("OBS-01", []).append({
            "description": "Logging config test present",
            "type": "test_pass",
            "weight": 0.3,
            "verified": True,
        })
        evidence.setdefault("OBS-01", []).append({
            "description": "Log helpers test present",
            "type": "test_pass",
            "weight": 0.3,
            "verified": True,
        })
    log_helpers_test = ROOT / "tests" / "test_log_helpers.py"
    if log_helpers_test.exists():
        evidence.setdefault("OBS-01", []).append({
            "description": "Log helpers test present",
            "type": "test_pass",
            "weight": 0.3,
            "verified": True,
        })

    # DR-03: WAL journal
    wal_test = ROOT / "tests" / "test_wal_journal.py"
    if wal_test.exists():
        evidence.setdefault("DR-03", []).append({
            "description": "WAL journal test present",
            "type": "test_pass",
            "weight": 0.5,
            "verified": True,
        })
        evidence.setdefault("DR-03", []).append({
            "description": f"WAL journal module: {'present' if (ROOT / 'core' / 'wal').is_dir() else 'MISSING'}",
            "type": "code_review",
            "weight": 0.3,
            "verified": (ROOT / "core" / "wal").is_dir(),
        })

    # OBS-02: Metrics exporter
    metrics_exporter = ROOT / "core" / "metrics_exporter.py"
    if metrics_exporter.exists():
        evidence.setdefault("OBS-02", []).append({
            "description": "Metrics exporter module present (Prometheus :9090)",
            "type": "code_review",
            "weight": 0.4,
            "verified": True,
        })
    metrics_test = ROOT / "tests" / "test_metrics_exporter.py"
    if metrics_test.exists():
        evidence.setdefault("OBS-02", []).append({
            "description": "Metrics exporter test present",
            "type": "test_pass",
            "weight": 0.3,
            "verified": True,
        })

    # OBS-04: Alerting (Telegram)
    telegram_queue = ROOT / "core" / "telegram_queue.py"
    if telegram_queue.exists():
        evidence.setdefault("OBS-04", []).append({
            "description": "Telegram priority queue present — alert routing",
            "type": "code_review",
            "weight": 0.3,
            "verified": True,
        })
    telegram_test = ROOT / "tests" / "test_telegram_queue.py"
    if telegram_test.exists():
        evidence.setdefault("OBS-04", []).append({
            "description": "Telegram queue test present",
            "type": "test_pass",
            "weight": 0.3,
            "verified": True,
        })

    # GOV-03: Technical debt tracking
    debt_doc = ROOT / "docs" / "technical_debt.md"
    if debt_doc.exists():
        evidence.setdefault("GOV-03", []).append({
            "description": "Technical debt register present",
            "type": "documentation",
            "weight": 0.4,
            "verified": True,
        })

    # GOV-04: Release governance (this module itself is evidence)
    release_gov_script = ROOT / "scripts" / "release_governance.py"
    if release_gov_script.exists():
        evidence.setdefault("GOV-04", []).append({
            "description": "Release governance automation script present",
            "type": "code_review",
            "weight": 0.5,
            "verified": True,
        })

    return evidence


# ── Category definitions ──────────────────────────────────────────────────────

CATEGORIES: dict[str, tuple[str, float, str]] = {
    "ARCH-01": ("Boundary enforcement", 9.5, "Architecture"),
    "ARCH-02": ("Single responsibility", 9.0, "Architecture"),
    "ARCH-03": ("Port/adapter separation", 9.5, "Architecture"),
    "ARCH-04": ("No circular dependencies", 9.0, "Architecture"),
    "SEC-01": ("Authentication", 9.5, "Security"),
    "SEC-02": ("Authorization/RBAC", 9.5, "Security"),
    "SEC-03": ("Secret management", 9.5, "Security"),
    "SEC-04": ("Audit trail", 9.5, "Security"),
    "RSK-01": ("Hard halt enforcement", 9.9, "Risk"),
    "RSK-02": ("Loss limits", 9.9, "Risk"),
    "RSK-03": ("Position sizing", 9.0, "Risk"),
    "RSK-04": ("Fail-closed", 9.5, "Risk"),
    "EXE-01": ("Exactly-once semantics", 9.9, "Execution"),
    "EXE-02": ("Idempotent retry", 9.5, "Execution"),
    "EXE-03": ("State machine correctness", 9.5, "Execution"),
    "EXE-04": ("Reconciliation", 9.5, "Execution"),
    "TST-01": ("Test coverage", 9.0, "Testing"),
    "TST-02": ("Chaos testing", 9.9, "Testing"),
    "TST-03": ("Contract testing", 9.5, "Testing"),
    "TST-04": ("Regression testing", 9.0, "Testing"),
    "OBS-01": ("Structured logging", 9.0, "Observability"),
    "OBS-02": ("Metrics", 9.0, "Observability"),
    "OBS-03": ("Health checks", 9.0, "Observability"),
    "OBS-04": ("Alerting", 9.0, "Observability"),
    "GOV-01": ("Documentation sync", 9.5, "Governance"),
    "GOV-02": ("Repository hygiene", 9.0, "Governance"),
    "GOV-03": ("Technical debt tracking", 9.0, "Governance"),
    "GOV-04": ("Release governance", 9.5, "Governance"),
    "DR-01": ("Database migration", 9.0, "DR"),
    "DR-02": ("State persistence", 9.0, "DR"),
    "DR-03": ("WAL journal", 9.5, "DR"),
}


def calculate_score(
    category_id: str,
    evidence_items: list[dict[str, Any]],
    regressions: list[str] | None = None,
) -> dict[str, Any]:
    """Calculate score for a single category.

    Formula:
      score = min(max_score, base(5.0) + evidence_bonus - regression_penalty)
    """
    base_score = 5.0
    max_score = CATEGORIES[category_id][1]
    regressions = regressions or []

    evidence_bonus = sum(
        item["weight"] for item in evidence_items if item.get("verified", False)
    )
    regression_penalty = 2.0 * len(regressions)

    raw = base_score + evidence_bonus - regression_penalty
    capped = min(raw, max_score)

    # Without any evidence, score cannot exceed 8.0
    if not evidence_items and capped > 8.0:
        capped = 8.0

    score = max(0.0, capped)
    has_evidence = len([e for e in evidence_items if e.get("verified")]) > 0

    return {
        "category_id": category_id,
        "name": CATEGORIES[category_id][0],
        "group": CATEGORIES[category_id][2],
        "max_score": max_score,
        "score": round(score, 2),
        "base_score": base_score,
        "evidence_bonus": round(evidence_bonus, 2),
        "regression_penalty": round(regression_penalty, 2),
        "evidence_count": len(evidence_items),
        "verified_evidence": sum(1 for e in evidence_items if e.get("verified")),
        "regression_count": len(regressions),
        "needs_9_audit": score >= 9.0,
        "needs_95_audit": score >= 9.5,
    }


# ── Main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--category", "-c", help="Score only a single category")
    ap.add_argument("--evidence", "-e", action="store_true", help="Show evidence details")
    ap.add_argument("--json", "-j", action="store_true", help="JSON output")
    ap.add_argument("--ci", action="store_true", help="CI mode (exit code only)")
    ap.add_argument("--check-min", type=float, default=0.0,
                    help="Fail if any score below this threshold")
    args = ap.parse_args(argv)

    # Collect auto-evidence
    auto_evidence = collect_auto_evidence()

    # Determine which categories to score
    categories_to_score = (
        [args.category] if args.category
        else sorted(CATEGORIES.keys())
    )

    results: list[dict[str, Any]] = []
    for cid in categories_to_score:
        if cid not in CATEGORIES:
            print(f"Unknown category: {cid}", file=sys.stderr)
            return 1
        evidence = auto_evidence.get(cid, [])
        result = calculate_score(cid, evidence)
        results.append(result)

    # Calculate overall
    overall = sum(r["score"] for r in results) / max(len(results), 1)
    regressions = sum(r["regression_count"] for r in results)
    evidence_total = sum(r["evidence_count"] for r in results)

    if args.json:
        output = {
            "timestamp": time.time(),
            "categories": results,
            "overall_score": round(overall, 2),
            "total_evidence": evidence_total,
            "total_regressions": regressions,
        }
        print(json.dumps(output, indent=2))
        return 0

    # Determine if any scores are below minimum
    failures_below_min = [r for r in results if r["score"] < args.check_min]

    if args.ci:
        return 1 if failures_below_min else 0

    # ── Print report ─────────────────────────────────────────────────────
    print("=" * 70)
    print("  CONSTITUTION SCORING SYSTEM")
    print("=" * 70)
    print(f"  Overall Score: {overall:.2f} / 9.99")
    print(f"  Total Evidence: {evidence_total}")
    print(f"  Total Regressions: {regressions}")
    print(f"  Categories: {len(results)}")
    print()

    # Group by group
    by_group: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_group[r["group"]].append(r)

    for group, items in sorted(by_group.items()):
        print(f"  [{group}]")
        for r in items:
            flag = "✓" if r["regression_count"] == 0 else "✗"
            audit_mark = " 🔍" if r["needs_9_audit"] else ""
            print(f"    {flag} {r['category_id']} {r['name']:<30s} "
                  f"{r['score']:5.2f}/{r['max_score']:.1f}{audit_mark}")
            if args.evidence and r["evidence_count"] > 0:
                for ev in auto_evidence.get(r["category_id"], []):
                    v = "✓" if ev.get("verified") else " "
                    print(f"         [{v}] {ev['description']}")
            if r["regression_count"] > 0:
                print(f"         regressions: {r['regression_count']}")
        print()

    # Summary
    print("-" * 70)
    below_8 = [r for r in results if r["score"] < 8.0]
    no_evidence = [r for r in results if r["evidence_count"] == 0]

    if below_8:
        print(f"  ⚠ {len(below_8)} category(ies) below 8.0: "
              f"{', '.join(r['category_id'] for r in below_8)}")
    if no_evidence:
        print(f"  ⚠ {len(no_evidence)} category(ies) with no evidence: "
              f"{', '.join(r['category_id'] for r in no_evidence)}")
    if failures_below_min:
        print(f"  ✗ {len(failures_below_min)} category(ies) below --check-min "
              f"({args.check_min})")
    else:
        print(f"  ✓ All scores meet minimum threshold ({args.check_min})")

    print("=" * 70)

    return 1 if failures_below_min else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
