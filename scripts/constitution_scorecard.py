#!/usr/bin/env python3
"""Constitution v4.0 Compliance Scorecard — Automated Coverage Verification.

Evaluates every requirement from the Master Engineering Constitution v4.0
against the existing codebase modules, producing a scored compliance report.

Usage:
    python scripts/constitution_scorecard.py          # Full report
    python scripts/constitution_scorecard.py --json   # JSON output
    python scripts/constitution_scorecard.py --check-min 80  # CI mode (fail if <80%)
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)

ROOT = pathlib.Path(".")


# ── Scorecard Data ───────────────────────────────────────────────────────────

CATEGORY_WEIGHTS = {
    "enterprise_layers": 0.20,
    "architecture_standards": 0.15,
    "engineering_principles": 0.10,
    "security_governance": 0.15,
    "quality_gates": 0.15,
    "platform_engineering": 0.10,
    "reliability_sre": 0.08,
    "knowledge_learning": 0.07,
}


@dataclass
class Requirement:
    """A single Constitution requirement."""

    id: str
    name: str
    category: str
    module_path: str  # Pattern to check existence of
    weight: float = 1.0
    description: str = ""

    def check(self) -> bool:
        """Check if the required module exists in the codebase."""
        # Support glob patterns
        if "*" in self.module_path:
            matches = list(ROOT.glob(self.module_path))
            return len(matches) > 0
        return ROOT.joinpath(self.module_path).exists()


# ── Full Requirement Set ─────────────────────────────────────────────────────

REQUIREMENTS: list[Requirement] = [
    # ── 12 Enterprise Layers ──────────────────────────────────────────────
    Requirement("LAY-01", "Business Layer", "enterprise_layers",
                "index_app/index_trader.py", weight=2.0),
    Requirement("LAY-02", "Platform Engineering Layer", "enterprise_layers",
                "Dockerfile", weight=1.0),
    Requirement("LAY-02b", "CI/CD Pipeline", "enterprise_layers",
                ".github/workflows/ci.yml", weight=1.0),
    Requirement("LAY-03", "Enterprise Architecture Layer", "enterprise_layers",
                "core/architecture_analyzer.py", weight=1.5),
    Requirement("LAY-04", "AI Intelligence Layer", "enterprise_layers",
                "core/recommendation_engine.py", weight=1.5),
    Requirement("LAY-05", "Knowledge Graph & Digital Twin", "enterprise_layers",
                "core/digital_twin.py", weight=1.5),
    Requirement("LAY-05b", "Codebase Knowledge Graph", "enterprise_layers",
                "core/codebase_knowledge_graph.py", weight=1.0),
    Requirement("LAY-06", "Autonomous Engineering Layer", "enterprise_layers",
                "core/self_healing/orchestrator.py", weight=1.5),
    Requirement("LAY-07", "Security, Governance & Compliance", "enterprise_layers",
                "core/security_auditor.py", weight=1.5),
    Requirement("LAY-07b", "Constitution Engine", "enterprise_layers",
                "core/constitution/__init__.py", weight=1.0),
    Requirement("LAY-08", "Reliability, Observability & SRE", "enterprise_layers",
                "core/synthetic_monitor.py", weight=1.5),
    Requirement("LAY-09", "Documentation & Knowledge Management", "enterprise_layers",
                "core/living_documentation.py", weight=1.5),
    Requirement("LAY-10", "Executive Intelligence Layer", "enterprise_layers",
                "core/executive_advisor.py", weight=1.5),
    Requirement("LAY-11", "Continuous Learning Layer", "enterprise_layers",
                "core/auto_learner.py", weight=1.5),
    Requirement("LAY-12", "Enterprise Evolution Layer", "enterprise_layers",
                "core/change_management.py", weight=1.5),

    # ── Architecture Standards (14) ───────────────────────────────────────
    Requirement("ARC-01", "Domain-Driven Design (DDD)", "architecture_standards",
                "core/strategy/orchestrator.py", weight=1.0),
    Requirement("ARC-02", "Clean Architecture", "architecture_standards",
                "core/ports/*.py", weight=1.0),
    Requirement("ARC-03", "Vertical Slice", "architecture_standards",
                "core/services/use_cases/*.py", weight=1.0),
    Requirement("ARC-04", "CQRS", "architecture_standards",
                "core/patterns/mediator.py", weight=1.0),
    Requirement("ARC-05", "Event Sourcing", "architecture_standards",
                "core/execution/event_system.py", weight=1.0),
    Requirement("ARC-06", "Mediator Pattern", "architecture_standards",
                "core/patterns/mediator.py", weight=1.0),
    Requirement("ARC-07", "Modular Monolith", "architecture_standards",
                "core/di_container", weight=1.0),
    Requirement("ARC-08", "Feature Flags", "architecture_standards",
                "core/config/feature_flags.py", weight=1.0),
    Requirement("ARC-09", "Plugin Architecture", "architecture_standards",
                "core/strategy/plugin_framework.py", weight=1.0),
    Requirement("ARC-10", "Multi-tenancy", "architecture_standards",
                "core/multi_tenant.py", weight=1.0),
    Requirement("ARC-11", "Versioned APIs", "architecture_standards",
                "core/api_versioning.py", weight=1.0),
    Requirement("ARC-12", "Semantic Versioning", "architecture_standards",
                "VERSION", weight=1.0),
    Requirement("ARC-13", "Strongly Typed Configuration", "architecture_standards",
                "json/index_config.defaults.json", weight=1.0),
    Requirement("ARC-14", "API First", "architecture_standards",
                "core/enterprise_dashboard/routes/*.py", weight=1.0),

    # ── Engineering Principles (13) ───────────────────────────────────────
    Requirement("PRN-01", "Security by Design", "engineering_principles",
                "core/security_auditor.py", weight=1.0),
    Requirement("PRN-02", "Privacy by Design", "engineering_principles",
                "core/runtime_security.py", weight=1.0),
    Requirement("PRN-03", "AI by Design", "engineering_principles",
                "core/ai_security_gate.py", weight=1.0),
    Requirement("PRN-04", "API First", "engineering_principles",
                "core/enterprise_dashboard/routes/__init__.py", weight=1.0),
    Requirement("PRN-05", "Cloud Native", "engineering_principles",
                "docker-compose.yml", weight=1.0),
    Requirement("PRN-06", "Everything as Code", "engineering_principles",
                "pyproject.toml", weight=1.0),
    Requirement("PRN-07", "Documentation as Code", "engineering_principles",
                "CLAUDE.md", weight=1.0),
    Requirement("PRN-08", "Test Everything", "engineering_principles",
                "pytest.ini", weight=1.0),
    Requirement("PRN-09", "Observe Everything", "engineering_principles",
                "core/observability/opentelemetry.py", weight=1.0),
    Requirement("PRN-10", "Automate Everything", "engineering_principles",
                "Makefile", weight=1.0),
    Requirement("PRN-11", "Measure Everything", "engineering_principles",
                "core/metrics_exporter.py", weight=1.0),
    Requirement("PRN-12", "Continuous Improvement", "engineering_principles",
                "core/auto_learner.py", weight=1.0),
    Requirement("PRN-13", "Backward Compatibility", "engineering_principles",
                "core/version_compatibility.py", weight=1.0),

    # ── Security & Governance (10) ────────────────────────────────────────
    Requirement("SEC-01", "Zero Trust", "security_governance",
                "core/auth/permissions.py", weight=1.0),
    Requirement("SEC-02", "RBAC/PBAC", "security_governance",
                "core/auth/role_manager.py", weight=1.0),
    Requirement("SEC-03", "Threat Modeling", "security_governance",
                "core/threat_modeler.py", weight=1.5),
    Requirement("SEC-04", "Secrets Management", "security_governance",
                "infrastructure/config/secure_config.py", weight=1.0),
    Requirement("SEC-05", "SBOM", "security_governance",
                "core/sbom_generator.py", weight=1.0),
    Requirement("SEC-06", "Compliance Reporting", "security_governance",
                "core/regulatory_reporting.py", weight=1.0),
    Requirement("SEC-07", "Runtime Security", "security_governance",
                "core/runtime_security.py", weight=1.0),
    Requirement("SEC-08", "AI Security", "security_governance",
                "core/ai_security_gate.py", weight=1.5),
    Requirement("SEC-09", "Prompt Injection Detection", "security_governance",
                "core/ai_security_gate.py", weight=1.0),
    Requirement("SEC-10", "Hallucination Detection", "security_governance",
                "core/ai_security_gate.py", weight=1.0),
    Requirement("SEC-11", "Audit Trails", "security_governance",
                "core/audit_mode.py", weight=1.0),

    # ── Quality Gates (12) ────────────────────────────────────────────────
    Requirement("QAT-01", "Architecture Quality Gate", "quality_gates",
                "scripts/check_architecture_compliance.py", weight=1.0),
    Requirement("QAT-02", "Security Quality Gate", "quality_gates",
                "core/security_auditor.py", weight=1.0),
    Requirement("QAT-03", "Performance Quality Gate", "quality_gates",
                "core/performance_optimizer.py", weight=1.0),
    Requirement("QAT-04", "Maintainability Gate", "quality_gates",
                "core/bi_dashboard.py", weight=1.0),
    Requirement("QAT-05", "Reliability Gate", "quality_gates",
                "core/synthetic_monitor.py", weight=1.0),
    Requirement("QAT-06", "Scalability Gate", "quality_gates",
                "core/capacity_planning.py", weight=1.0),
    Requirement("QAT-07", "Documentation Quality Gate", "quality_gates",
                "core/living_documentation.py", weight=1.0),
    Requirement("QAT-08", "Accessibility Gate", "quality_gates",
                "core/accessibility_gate.py", weight=1.0),
    Requirement("QAT-09", "Testing Quality Gate", "quality_gates",
                "pytest.ini", weight=1.0),
    Requirement("QAT-10", "Technical Debt Gate", "quality_gates",
                "docs/technical_debt.md", weight=1.0),
    Requirement("QAT-11", "Deployment Readiness Gate", "quality_gates",
                "scripts/pre_implementation_check.py", weight=1.0),
    Requirement("QAT-12", "Engineering Score Gate", "quality_gates",
                "scripts/score_system.py", weight=1.0),

    # ── Platform Engineering ──────────────────────────────────────────────
    Requirement("PLT-01", "Internal Developer Platform", "platform_engineering",
                "core/service_catalog.py", weight=1.5),
    Requirement("PLT-02", "Golden Paths", "platform_engineering",
                "core/service_catalog.py", weight=1.0),
    Requirement("PLT-03", "Service Catalog", "platform_engineering",
                "core/service_catalog.py", weight=1.0),
    Requirement("PLT-04", "Environment Provisioning", "platform_engineering",
                "deploy/docker-compose.postgres.yml", weight=1.0),
    Requirement("PLT-05", "Infrastructure as Code", "platform_engineering",
                "docker-compose.yml", weight=1.0),
    Requirement("PLT-06", "Self-Service Infrastructure", "platform_engineering",
                "Makefile", weight=0.5),

    # ── Reliability & SRE ─────────────────────────────────────────────────
    Requirement("SRE-01", "Structured Logging", "reliability_sre",
                "core/logging.py", weight=1.0),
    Requirement("SRE-02", "Distributed Tracing", "reliability_sre",
                "core/observability/opentelemetry.py", weight=1.0),
    Requirement("SRE-03", "Metrics & Dashboards", "reliability_sre",
                "core/metrics_exporter.py", weight=1.0),
    Requirement("SRE-04", "Health Checks", "reliability_sre",
                "core/health_checker.py", weight=1.0),
    Requirement("SRE-05", "Synthetic Monitoring", "reliability_sre",
                "core/synthetic_monitor.py", weight=1.5),
    Requirement("SRE-06", "Chaos Engineering", "reliability_sre",
                "core/chaos_engine.py", weight=1.5),
    Requirement("SRE-07", "Self-Healing", "reliability_sre",
                "core/self_healing/orchestrator.py", weight=1.5),
    Requirement("SRE-08", "Rollback Automation", "reliability_sre",
                "core/ai/rollback_controller.py", weight=1.0),
    Requirement("SRE-09", "Error Budgets", "reliability_sre",
                "core/error_budget.py", weight=1.0),

    # ── Knowledge & Learning ──────────────────────────────────────────────
    Requirement("KNW-01", "Enterprise Decision Memory", "knowledge_learning",
                "core/decision_memory.py", weight=1.5),
    Requirement("KNW-02", "ADR Documentation", "knowledge_learning",
                "docs/adr/0010-architecture-governance.md", weight=1.0),
    Requirement("KNW-03", "Organizational Memory", "knowledge_learning",
                "core/decision_memory.py", weight=1.0),
    Requirement("KNW-04", "Incident Learning", "knowledge_learning",
                "core/postmortem_automator.py", weight=1.5),
    Requirement("KNW-05", "Postmortems", "knowledge_learning",
                "core/postmortem_automator.py", weight=1.0),
    Requirement("KNW-06", "Knowledge Base", "knowledge_learning",
                "docs/runbooks/", weight=1.0),
    Requirement("KNW-07", "Living Documentation", "knowledge_learning",
                "core/living_documentation.py", weight=1.0),
]

SCORE_THRESHOLD_GOOD = 90.0


# ── Scorecard Engine ─────────────────────────────────────────────────────────


@dataclass
class CategoryScore:
    """Score for a single category."""

    name: str
    weight: float
    passed: int = 0
    total: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def pct(self) -> float:
        return round(self.passed / max(1, self.total) * 100, 1)

    @property
    def weighted_score(self) -> float:
        return round(self.pct * self.weight / 100, 2)


@dataclass
class ScorecardReport:
    """Complete compliance scorecard report."""

    categories: dict[str, CategoryScore] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    total_passed: int = 0
    total_requirements: int = 0
    overall_pct: float = 0.0
    overall_weighted_score: float = 0.0

    @property
    def status(self) -> str:
        if self.overall_pct >= SCORE_THRESHOLD_GOOD:
            return "PASS"
        return "REVIEW"

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_passed": self.total_passed,
            "total_requirements": self.total_requirements,
            "overall_pct": self.overall_pct,
            "overall_weighted_score": self.overall_weighted_score,
            "status": self.status,
            "categories": {
                name: {
                    "passed": cat.passed,
                    "total": cat.total,
                    "pct": cat.pct,
                    "weight": cat.weight,
                    "weighted_score": cat.weighted_score,
                    "results": cat.results,
                }
                for name, cat in sorted(self.categories.items())
            },
        }

    def summary_text(self) -> str:
        _BAR = "=" * 64
        lines = [
            _BAR,
            "  CONSTITUTION v4.0 COMPLIANCE SCORECARD",
            _BAR,
            f"  Overall: {self.overall_pct:.1f}% ({self.total_passed}/{self.total_requirements})"
            f" -> Weighted: {self.overall_weighted_score:.1f}/100"
            f" -> Status: {self.status}",
            "",
        ]
        for cat_name, cat in sorted(self.categories.items()):
            label = cat_name.replace("_", " ").title()
            filled = int(cat.pct / 5)
            bar = "#" * filled + "." * (20 - filled)
            lines.append(
                f"  {label:30s} {cat.pct:5.1f}% ({cat.passed:2d}/{cat.total:2d}) "
                f"w={cat.weight:.2f} s={cat.weighted_score:.2f}"
            )
            lines.append(f"  {'':30s}  {bar}")
        lines.append(_BAR)
        return "\n".join(lines)


def run_scorecard() -> ScorecardReport:
    """Run the full compliance scorecard check."""
    report = ScorecardReport()

    for req in REQUIREMENTS:
        if req.category not in report.categories:
            report.categories[req.category] = CategoryScore(
                name=req.category,
                weight=CATEGORY_WEIGHTS.get(req.category, 0.05),
            )

        cat = report.categories[req.category]
        cat.total += 1
        report.total_requirements += 1

        passed = req.check()
        cat.passed += 1 if passed else 0
        report.total_passed += 1 if passed else 0

        cat.results.append({
            "id": req.id,
            "name": req.name,
            "module": req.module_path,
            "passed": passed,
            "weight": req.weight,
        })

    # Compute scores
    for cat in report.categories.values():
        cat.pct  # property triggers computation

    total_weight = sum(CATEGORY_WEIGHTS.values())
    report.overall_weighted_score = round(
        sum(c.weighted_score for c in report.categories.values())
        / max(0.01, total_weight) * 100,
        1,
    )
    report.overall_pct = round(
        report.total_passed / max(1, report.total_requirements) * 100, 1
    )

    return report


# ── CLI ──────────────────────────────────────────────────────────────────────


def _cli() -> None:
    ap = argparse.ArgumentParser(prog="constitution_scorecard")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    ap.add_argument("--check-min", type=float, default=0.0,
                    help="CI mode: exit code 1 if overall %% below this threshold")
    args = ap.parse_args()

    report = run_scorecard()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.summary_text())

    # Optional CI gate
    if args.check_min > 0 and report.overall_pct < args.check_min:
        print(f"\nFAILED: Overall {report.overall_pct:.1f}% < minimum {args.check_min:.1f}%")
        sys.exit(1)

    if sys.stdout.encoding and sys.stdout.encoding.upper() in ("UTF-8", "UTF8"):
        check = "\u2713"
    else:
        check = "OK"
    print(f"\n{check} Scorecard complete: {report.overall_pct:.1f}% compliance, "
          f"Status: {report.status}")


if __name__ == "__main__":
    _cli()
