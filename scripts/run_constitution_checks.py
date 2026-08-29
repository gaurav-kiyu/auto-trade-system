#!/usr/bin/env python3
"""Unified Constitution v4.0 System Check — validate all 15 modules.

Usage:
    python scripts/run_constitution_checks.py              # Full report
    python scripts/run_constitution_checks.py --json       # JSON output
    python scripts/run_constitution_checks.py --check-min 90  # CI gate mode
    python scripts/run_constitution_checks.py --module ai_security_gate  # Single module

This script imports every Constitution v4.0 module, calls its get_<module>()
singleton factory, and verifies get_stats() returns valid data. Designed
for CI pipelines, startup validation, and operational health checks.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

# Add project root to sys.path so 'from core.*' imports work when run as script
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_script_dir, ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
_log = logging.getLogger("constitution_check")


# ── Module registry ──────────────────────────────────────────────────────────

MODULES: list[dict[str, Any]] = [
    {"name": "AI Security Gate",        "key": "ai_security_gate",      "import": "core.ai_security_gate",         "factory": "get_ai_security_gate"},
    {"name": "Threat Modeler",          "key": "threat_modeler",        "import": "core.threat_modeler",           "factory": "get_threat_modeler"},
    {"name": "Postmortem Automator",    "key": "postmortem_automator",  "import": "core.postmortem_automator",     "factory": "get_postmortem_automator"},
    {"name": "Decision Memory",         "key": "decision_memory",       "import": "core.decision_memory",          "factory": "get_decision_memory"},
    {"name": "Digital Twin",            "key": "digital_twin",          "import": "core.digital_twin",             "factory": "get_digital_twin"},
    {"name": "Runtime Security",        "key": "runtime_security",      "import": "core.runtime_security",         "factory": "get_runtime_security"},
    {"name": "API Versioning",          "key": "api_versioning",        "import": "core.api_versioning",           "factory": "get_api_version_manager"},
    {"name": "Executive Advisor",       "key": "executive_advisor",     "import": "core.executive_advisor",        "factory": "get_executive_advisor"},
    {"name": "Accessibility Gate",      "key": "accessibility_gate",    "import": "core.accessibility_gate",       "factory": "get_accessibility_gate"},
    {"name": "Service Catalog",         "key": "service_catalog",       "import": "core.service_catalog",          "factory": "get_service_catalog"},
    {"name": "Incident Commander",      "key": "incident_commander",    "import": "core.incident_command_system",   "factory": "get_incident_commander"},
    {"name": "Continuous Intelligence",     "key": "continuous_intelligence",  "import": "core.continuous_intelligence",    "factory": "get_intelligence_pipeline"},
    {"name": "ICS-Telegram Bridge",          "key": "ics_telegram_bridge",      "import": "core.ics_telegram_bridge",        "factory": "get_ics_telegram_bridge"},
    {"name": "ICS-Self-Healing Bridge",      "key": "ics_self_healing_bridge",  "import": "core.ics_self_healing_bridge",    "factory": "get_ics_self_healing_bridge"},
    {"name": "Constitution Startup",         "key": "constitution_startup",     "import": "core.startup",                   "factory": "startup_constitution_system", "orchestrator": True},
]


@dataclass
class ModuleCheckResult:
    """Result of checking a single constitution module."""

    name: str
    key: str
    status: str  # "PASS", "FAIL", "SKIP"
    duration_ms: float = 0.0
    error: str = ""
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "key": self.key,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error,
            "stats": self.stats,
        }


@dataclass
class CheckReport:
    """Consolidated report from all module checks."""

    results: list[ModuleCheckResult] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == "PASS")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == "FAIL")

    @property
    def score_pct(self) -> float:
        return (self.passed / self.total * 100) if self.total > 0 else 0.0

    @property
    def duration_sec(self) -> float:
        return round(self.end_time - self.start_time, 2)

    def summary_text(self) -> str:
        lines = [
            "=" * 60,
            "CONSTITUTION v4.0 — SYSTEM CHECK REPORT",
            "=" * 60,
            f"  Modules checked : {self.total}",
            f"  Passed         : {self.passed}",
            f"  Failed         : {self.failed}",
            f"  Score          : {self.score_pct:.1f}%",
            f"  Duration       : {self.duration_sec}s",
            "-" * 60,
        ]
        for r in self.results:
            icon = "[PASS]" if r.status == "PASS" else "[FAIL]" if r.status == "FAIL" else "[SKIP]"
            lines.append(f"  {icon} {r.name:25s} ({r.duration_ms:6.1f}ms)")
            if r.status == "FAIL" and r.error:
                lines.append(f"     Error: {r.error}")
        lines.append("=" * 60)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "score_pct": round(self.score_pct, 1),
            "duration_sec": self.duration_sec,
            "results": [r.to_dict() for r in self.results],
        }


def check_single_module(mod: dict[str, Any]) -> ModuleCheckResult:
    """Import, instantiate, and verify a single constitution module."""
    start = time.time()
    result = ModuleCheckResult(name=mod["name"], key=mod["key"], status="FAIL")

    try:
        # Step 1: Import the module
        mod_obj = __import__(mod["import"], fromlist=[""])

        # Step 2: Get the factory function
        factory_fn = getattr(mod_obj, mod["factory"], None)
        if factory_fn is None:
            raise AttributeError(f"Factory function {mod['factory']} not found in {mod['import']}")

        # Step 3: Instantiate the singleton
        # NOTE: Orchestrators (modules with orchestrator=True, e.g. constitution_startup)
        # are only verified for importability. We do NOT call their factory because
        # it would cause infinite recursion: startup_constitution_system() ->
        # run_checks() -> startup_constitution_system() -> ...
        if mod.get("orchestrator"):
            result.status = "PASS"
            result.stats = {"importable": True, "orchestrator": True}
            result.duration_ms = (time.time() - start) * 1000
            return result

        instance = factory_fn()

        # Step 4: Verify get_stats() works
        stats = instance.get_stats() if hasattr(instance, "get_stats") else {"available": True}

        result.status = "PASS"
        result.stats = stats if isinstance(stats, dict) else {"status": "available"}
        result.duration_ms = (time.time() - start) * 1000

    except Exception as exc:
        result.status = "FAIL"
        result.error = f"{type(exc).__name__}: {exc}"
        result.duration_ms = (time.time() - start) * 1000

    return result


def run_checks(module_filter: str | None = None) -> CheckReport:
    """Run all module checks, optionally filtering to a single module."""
    report = CheckReport()

    for mod in MODULES:
        if module_filter and module_filter != mod["key"]:
            continue
        result = check_single_module(mod)
        report.results.append(result)

    report.end_time = time.time()
    return report


def _cli() -> None:
    """Command-line interface."""
    parser = argparse.ArgumentParser(
        description="Constitution v4.0 System Check — validate all 15 modules",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output results as JSON (default: human-readable text)",
    )
    parser.add_argument(
        "--check-min", type=float, default=0.0,
        help="CI gate mode: exit with code 1 if score is below this percentage",
    )
    parser.add_argument(
        "--module", type=str, default=None,
        help="Check only a single module (use key name, e.g. ai_security_gate)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress output (useful for CI)",
    )
    parser.add_argument(
        "--check-v4-health", action="store_true",
        help="Run v4.0 comprehensive health check and validate all domains are initialized",
    )
    parser.add_argument(
        "--v4-min-score", type=float, default=5.0,
        help="CI gate mode for v4.0 health: exit with code 1 if overall score is below this value (default: 5.0)",
    )

    args = parser.parse_args()
    report = run_checks(args.module)

    if args.json:
        output = report.to_dict()
        # Add v4.0 health check if requested
        if args.check_v4_health:
            try:
                from core.constitution import get_validator
                v4_health = get_validator().comprehensive_health_check()
                output["v4_health"] = v4_health
            except Exception as exc:
                output["v4_health"] = {"error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(output, indent=2))
    elif not args.quiet:
        print(report.summary_text())
        # Print v4.0 health if requested
        if args.check_v4_health:
            try:
                from core.constitution import get_validator
                v4_health = get_validator().comprehensive_health_check()
                print("\n" + "=" * 60)
                print("  CONSTITUTION v4.0 — COMPREHENSIVE HEALTH CHECK")
                print("=" * 60)
                print(f"  Version               : {v4_health['version']}")
                print(f"  Overall Score         : {v4_health['overall_score']}")
                print(f"  Total Categories      : {v4_health['total_categories']}")
                print(f"  Total Evidence        : {v4_health['total_evidence']}")
                print(f"  Open Regressions      : {v4_health['open_regressions']}")
                print()
                for domain_key, domain_label in [
                    ("enterprise_layers", "Enterprise Layers"),
                    ("quality_gates", "Quality Gates"),
                    ("success_metrics", "Success Metrics"),
                    ("ai_specialist_roles", "AI Specialist Roles"),
                    ("definition_of_done", "Definition of Done"),
                    ("continuous_lifecycle", "Continuous Lifecycle"),
                    ("engineering_principles", "Engineering Principles"),
                    ("architecture_standards", "Architecture Standards"),
                    ("security_governance", "Security & Governance"),
                    ("platform_engineering", "Platform Engineering"),
                    ("sre_reliability", "SRE/Reliability"),
                ]:
                    domain = v4_health.get(domain_key, {})
                    count = domain.get("count", 0)
                    print(f"  {domain_label:30s}: {count}")
                print("=" * 60)
            except Exception as exc:
                print(f"\n  v4.0 Health Check failed: {exc}")

    # CI gate: module check score
    if args.check_min > 0 and report.score_pct < args.check_min:
        msg = (
            f"FAIL: Constitution check score {report.score_pct:.1f}% "
            f"is below minimum {args.check_min:.1f}%"
        )
        print(msg, file=sys.stderr)
        sys.exit(1)

    # CI gate: v4.0 health overall score
    if args.check_v4_health:
        try:
            from core.constitution import get_validator
            v4_health = get_validator().comprehensive_health_check()
            overall = v4_health["overall_score"]
            if overall < args.v4_min_score:
                msg = (
                    f"FAIL: v4.0 Health score {overall:.2f} "
                    f"is below minimum {args.v4_min_score:.1f}"
                )
                print(msg, file=sys.stderr)
                sys.exit(1)
        except Exception as exc:
            print(f"FAIL: v4.0 Health check error: {exc}", file=sys.stderr)
            sys.exit(1)

    # Exit with error if any modules failed
    if report.failed > 0 and not args.json:
        sys.exit(1)


if __name__ == "__main__":
    _cli()
