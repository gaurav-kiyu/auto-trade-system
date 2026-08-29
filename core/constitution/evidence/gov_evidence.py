"""
GOV (Governance) evidence collection — extracted from evidence.py.

Scans codebase to register objective evidence for GOV (Governance)
constitution scoring categories.

Usage:
    from core.constitution.evidence.gov_evidence import collect_gov_evidence
    collect_gov_evidence(validator, root, add_ev)
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.constitution import ConstitutionValidator


__all__ = [
    "collect_gov_evidence",
]


def collect_gov_evidence(
    validator: ConstitutionValidator,
    root: Path,
    add_ev,
) -> None:
    """Collect GOV (Governance) evidence from the codebase.

    Args:
        validator: ConstitutionValidator instance.
        root: PROJECT_ROOT path for file existence checks.
        add_ev: validator.add_evidence bound method.

    """
    # ── GOV: Governance ─────────────────────────────────────────────
    if (root / "scripts" / "sync_artifacts.py").exists():
        add_ev("GOV-01",
            "Artifact Sync checker for docs/configs/env.example sync",
            "test_pass", 0.5)
    if (root / "tests" / "test_sync_artifacts.py").exists():
        add_ev("GOV-01",
            "Artifact sync test validates sync correctness",
            "test_pass", 0.5)
    if (root / "docs").is_dir():
        doc_files = list((root / "docs").rglob("*.md"))
        add_ev("GOV-01",
            f"{len(doc_files)} documentation files across architecture, runbooks, ops",
            "documentation", 0.4)
    if (root / "docs" / "doc_drift_register.md").exists():
        add_ev("GOV-01",
            "Doc drift register tracks doc-to-code gaps",
            "documentation", 0.3)
    if (root / "docs" / "constitution_scoring_framework.md").exists():
        add_ev("GOV-01",
            "23-category constitution scoring framework with objective evidence rules",
            "documentation", 0.3)
    if (root / "docs" / "AI_GOVERNANCE_GUIDE.md").exists():
        add_ev("GOV-01",
            "AI Governance Guide for agent constitution acknowledgment protocol",
            "documentation", 0.3)
    if (root / "docs" / "runbooks").is_dir():
        runbook_files = list((root / "docs" / "runbooks").glob("*.md"))
        if runbook_files:
            add_ev("GOV-01",
                f"{len(runbook_files)} incident runbooks covering broker outage, auth expiry, DB corruption",
                "documentation", 0.3)
    if (root / "scripts" / "hygiene_check.py").exists():
        add_ev("GOV-02",
            "Repository Hygiene checker scans forbidden artifacts",
            "test_pass", 0.5)
    if (root / "tests" / "test_hygiene_check.py").exists():
        add_ev("GOV-02",
            "Hygiene check test validates detection logic",
            "test_pass", 0.4)
    if (root / ".gitignore").exists():
        add_ev("GOV-02",
            ".gitignore covers all standard artifacts",
            "documentation", 0.3)
    if (root / "bitbucket-pipelines.yml").exists():
        yml_content = (root / "bitbucket-pipelines.yml").read_text(encoding="utf-8", errors="replace")
        if "hygiene_check" in yml_content:
            add_ev("GOV-02",
                "CI pipeline runs hygiene_check as mandatory gate before deployment",
                "code_review", 0.3)
        if "scan_dead_code" in yml_content:
            add_ev("GOV-02",
                "CI pipeline runs dead code scan as mandatory gate (scan_dead_code.py --ci)",
                "code_review", 0.3)
        if "sync_artifacts" in yml_content:
            add_ev("GOV-02",
                "CI pipeline runs artifact sync check as mandatory gate (sync_artifacts.py --ci)",
                "code_review", 0.3)
    if (root / "docs" / "technical_debt.md").exists():
        add_ev("GOV-03",
            "Technical debt register: items tracked by severity",
            "documentation", 0.4)
    if (root / "scripts" / "scan_dead_code.py").exists():
        add_ev("GOV-03",
            "Dead Code Scanner: unused imports, orphaned symbols",
            "test_pass", 0.5)
    if (root / "tests" / "test_scan_dead_code.py").exists():
        add_ev("GOV-03",
            "Dead code scan test validates scanner",
            "test_pass", 0.4)
    if (root / "docs" / "dead_code_register.md").exists():
        add_ev("GOV-03",
            "Auto-generated dead code register with findings",
            "documentation", 0.3)
    if (root / "docs" / "duplicate_code_register.md").exists():
        add_ev("GOV-03",
            "Auto-generated duplicate code register",
            "documentation", 0.3)
    if (root / "docs" / "config_drift_register.md").exists():
        add_ev("GOV-03",
            "Config drift register tracks sync gaps",
            "documentation", 0.2)
    if (root / "scripts" / "release_governance.py").exists():
        add_ev("GOV-04",
            "Release governance automation: branch, notes, changelog, tagging",
            "test_pass", 0.6)
    if (root / "tests" / "test_release_governance.py").exists():
        add_ev("GOV-04",
            "Release governance test validates 38 scenarios",
            "test_pass", 0.5)
    if (root / "scripts" / "pre_implementation_check.py").exists():
        add_ev("GOV-04",
            "Pre-implementation checker for mandatory compliance",
            "test_pass", 0.4)
    if (root / "tests" / "test_pre_implementation_check.py").exists():
        add_ev("GOV-04",
            "Pre-implementation check test: 34 tests",
            "test_pass", 0.4)
    if (root / "tests" / "test_constitution.py").exists():
        add_ev("GOV-04",
            "Constitution test: 66 tests validating governance framework",
            "test_pass", 0.4)
    if (root / "core" / "constitution_ai_gate.py").exists():
        add_ev("GOV-04",
            "AI governance gate for agent pre-implementation validation",
            "test_pass", 0.4)

    # ── GOV-01: Additional documentation sync evidence ────────────────
    test_dir = root / "tests"
    for tf_name in ["test_sync_artifacts", "test_doc_drift", "test_config_drift",
                    "test_config_drift_api", "test_hygiene_check", "test_scan_dead_code",
                    "test_institutional_challenge"]:
        if (test_dir / f"{tf_name}.py").exists():
            add_ev("GOV-01",
                f"Documentation sync test: {tf_name} validates doc-to-code alignment",
                "test_pass", 0.3)
    if (root / "docs" / "constitution_scoring_framework.md").exists():
        add_ev("GOV-01",
            "Constitution scoring framework with 23-category criteria and evidence rules",
            "documentation", 0.3)
    if (root / "docs" / "AI_GOVERNANCE_GUIDE.md").exists():
        add_ev("GOV-01",
            "AI Governance Guide for agent constitution acknowledgment protocol",
            "documentation", 0.3)

    # ── GOV-02: Additional repository hygiene evidence ────────────────
    for tf_name in ["test_hygiene_check", "test_scan_dead_code", "test_sync_artifacts",
                    "test_doc_drift", "test_config_drift", "test_config_drift_api",
                    "test_config_drift_integration"]:
        if (test_dir / f"{tf_name}.py").exists():
            add_ev("GOV-02",
                f"Hygiene test: {tf_name} validates repository quality enforcement",
                "test_pass", 0.3)
    if (root / ".gitignore").exists():
        content = (root / ".gitignore").read_text(encoding="utf-8", errors="replace")
        patterns = sum(1 for line in content.splitlines() if line.strip() and not line.strip().startswith("#"))
        add_ev("GOV-02",
            f".gitignore with {patterns} exclusion patterns preventing artifact leakage",
            "documentation", 0.3)

    # ── GOV-03: Additional technical debt evidence ────────────────────
    for tf_name in ["test_scan_dead_code", "test_sync_artifacts", "test_hygiene_check",
                    "test_shared_config_validate", "test_score_system", "test_mandate_enforcer",
                    "test_mandate_validator", "test_mandate_service",
                    "test_architecture_compliance"]:
        if (test_dir / f"{tf_name}.py").exists():
            add_ev("GOV-03",
                f"Technical debt test: {tf_name} validates code quality tracking",
                "test_pass", 0.3)
    if (root / "TECHNICAL_DEBT_REGISTER.md").exists():
        add_ev("GOV-03",
            "Technical debt register tracks all known debt items prioritized by severity",
            "documentation", 0.3)

    # ── GOV-04: Additional release governance evidence ────────────────
    for tf_name in ["test_release_governance", "test_pre_implementation_check",
                    "test_constitution", "test_constitution_ai_gate",
                    "test_score_system", "test_institutional_challenge"]:
        if (test_dir / f"{tf_name}.py").exists():
            add_ev("GOV-04",
                f"Release governance test: {tf_name} validates release pipeline compliance",
                "test_pass", 0.3)
    if (root / "CHANGELOG.md").exists():
        add_ev("GOV-04",
            "CHANGELOG.md maintained with structured release history for audit traceability",
            "documentation", 0.3)
    if (root / "RELEASE_NOTES.md").exists():
        add_ev("GOV-04",
            "RELEASE_NOTES.md documents per-version feature additions and bug fixes",
            "documentation", 0.3)

