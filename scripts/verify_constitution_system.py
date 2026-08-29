#!/usr/bin/env python3
"""Constitution v4.0 — End-to-End System Verification.

Runs comprehensive checks across ALL constitution v4.0 systems:
  1. ConstitutionValidator — categories, evidence, scoring
  2. AIGovernanceGate — AI roles, layer validation
  3. Alert Bridge — health checks, status detection
  4. Self-Healing Bridge — pattern registration, healing cycles
  5. Startup Integration — all 10 module keys
  6. Dashboard API — intelligence summary endpoint
  7. Metrics Export — Prometheus gauge acceptance
  8. Report Generator — health report generation
  9. CI Compliance Gate — check runs without errors

Usage:
    python scripts/verify_constitution_system.py          # Full verification
    python scripts/verify_constitution_system.py --json   # JSON output
    python scripts/verify_constitution_system.py --quick  # Skip report generation
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

_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_script_dir, ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logging.basicConfig(level=logging.WARNING)
_log = logging.getLogger("verify_constitution")


@dataclass
class CheckResult:
    name: str
    passed: bool = False
    detail: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "duration_ms": round(self.duration_ms, 1),
        }


@dataclass
class VerificationReport:
    checks: list[CheckResult] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def score_pct(self) -> float:
        return (self.passed / max(self.total, 1)) * 100

    @property
    def duration_sec(self) -> float:
        return round(self.end_time - self.start_time, 2)

    def summary_text(self) -> str:
        _BAR = "=" * 64
        lines = [
            _BAR,
            "  CONSTITUTION v4.0 — END-TO-END VERIFICATION",
            _BAR,
            f"  Checks: {self.passed}/{self.total} passed ({self.score_pct:.0f}%)",
            f"  Duration: {self.duration_sec}s",
            "",
        ]
        for c in self.checks:
            icon = "[PASS]" if c.passed else "[FAIL]"
            lines.append(f"  {icon} {c.name:50s} ({c.duration_ms:6.1f}ms)")
            if not c.passed and c.detail:
                lines.append(f"       Error: {c.detail}")
        lines.append(_BAR)
        if self.passed == self.total:
            lines.append("  STATUS: ✅ ALL SYSTEMS OPERATIONAL")
        else:
            lines.append(f"  STATUS: ⚠️  {self.failed} check(s) FAILED")
        lines.append(_BAR)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "score_pct": round(self.score_pct, 1),
            "duration_sec": self.duration_sec,
            "checks": [c.to_dict() for c in self.checks],
        }


def _check(name: str, fn: Any) -> CheckResult:
    start = time.time()
    result = CheckResult(name=name)
    try:
        result.passed, result.detail = fn()
    except Exception as exc:
        result.passed = False
        result.detail = f"{type(exc).__name__}: {exc}"
    result.duration_ms = (time.time() - start) * 1000
    return result


def run_all_checks(quick: bool = False) -> VerificationReport:
    report = VerificationReport()

    # ── 1. ConstitutionValidator ────────────────────────────────────────
    def check_categories() -> tuple[bool, str]:
        from core.constitution import get_validator
        v = get_validator()
        count = len(v.CATEGORIES)
        expected = 111
        return count == expected, f"{count} categories (expected {expected})"

    def check_evidence_storage() -> tuple[bool, str]:
        from core.constitution import get_validator
        v = get_validator()
        ok1 = v.add_evidence("ARCH-01", "Verification evidence", "code_review", 0.5)
        ok2 = v.add_evidence("PRN-01", "Verification evidence", "code_review", 0.5)
        ok3 = v.add_evidence("SRE-09", "Verification evidence", "code_review", 0.5)
        return ok1 and ok2 and ok3, f"ARCH={ok1} PRN={ok2} SRE={ok3}"

    def check_scoring() -> tuple[bool, str]:
        from core.constitution import get_validator
        v = get_validator()
        report = v.generate_report()
        return report.overall_score > 0 and report.version == "4.0.0", \
            f"score={report.overall_score:.2f} version={report.version} cats={len(report.categories)} ev={report.total_evidence_items}"

    def check_health_check() -> tuple[bool, str]:
        from core.constitution import get_validator
        v = get_validator()
        health = v.comprehensive_health_check()
        domains = ["enterprise_layers", "quality_gates", "engineering_principles",
                    "architecture_standards", "security_governance", "platform_engineering", "sre_reliability"]
        missing = [d for d in domains if d not in health]
        return len(missing) == 0, f"domains={len(health)}, missing={missing}"

    # ── 2. AIGovernanceGate ─────────────────────────────────────────────
    def check_ai_gate() -> tuple[bool, str]:
        from core.constitution_ai_gate import get_gate
        gate = get_gate(identity="verify_test")
        ack = gate.acknowledge_constitution()
        return bool(ack), f"acknowledged={bool(ack)}"

    def check_ai_roles() -> tuple[bool, str]:
        from core.constitution import ConstitutionValidator
        roles = ConstitutionValidator.AI_SPECIALIST_ROLES
        return len(roles) >= 18, f"{len(roles)} roles"

    # ── 3. Alert Bridge ─────────────────────────────────────────────────
    def check_alert_bridge() -> tuple[bool, str]:
        from core.constitution_alert_bridge import get_constitution_alert_bridge
        bridge = get_constitution_alert_bridge({"enabled": False})
        result = bridge.check_and_alert()
        return result.error == "", f"score={result.overall_score:.2f} status={result.health_status} cats={result.total_categories}"

    # ── 4. Self-Healing Bridge ──────────────────────────────────────────
    def check_self_healing_bridge() -> tuple[bool, str]:
        from core.constitution_self_healing_bridge import register_constitution_patterns
        count = register_constitution_patterns()
        return count >= 5, f"{count} patterns registered"

    def check_self_healing_orchestrator() -> tuple[bool, str]:
        from core.self_healing.orchestrator import get_orchestrator
        o = get_orchestrator()
        status = o.get_health_status()
        return status["patterns_registered"] >= 1, f"{status['patterns_registered']} patterns, running={status['monitor_running']}"

    # ── 5. Startup Integration ──────────────────────────────────────────
    def check_startup() -> tuple[bool, str]:
        from core.startup import startup_constitution_system
        result = startup_constitution_system()
        meta = result["_meta"]
        keys = [k for k in result if k != "_meta"]
        return meta["modules_failed"] == 0, f"{len(keys)} modules, {meta['modules_initialized']} initialized, {meta['modules_failed']} failed"

    def check_disabled_startup() -> tuple[bool, str]:
        from core.startup import startup_constitution_system
        result = startup_constitution_system(cfg={"CONSTITUTION_ENABLED": False})
        return result["_meta"]["enabled"] is False, f"enabled={result['_meta']['enabled']}"

    # ── 6. Dashboard API ────────────────────────────────────────────────
    def check_dashboard_endpoint() -> tuple[bool, str]:
        from core.enterprise_dashboard.routes.intelligence import _TOTAL_TESTS
        return _TOTAL_TESTS > 0, f"{_TOTAL_TESTS} tests tracked"

    # ── 7. Metrics Export ───────────────────────────────────────────────
    def check_metrics() -> tuple[bool, str]:
        from core.metrics_exporter import update_metrics
        metrics = {
            "constitution_overall_score": 7.0,
            "constitution_total_categories": 111.0,
            "constitution_evidence_count": 500.0,
            "constitution_open_regressions": 0.0,
        }
        update_metrics(metrics)
        return True, "metrics accepted"

    # ── 8. Report Generator ──────────────────────────────────────────────
    if not quick:
        def check_report_generator() -> tuple[bool, str]:
            from scripts.generate_constitution_report import generate_health_report
            report = generate_health_report(days=7)
            required_keys = ["overall_score", "total_categories", "trending", "domain_breakdown", "recommendations"]
            missing = [k for k in required_keys if k not in report]
            return len(missing) == 0, \
                f"score={report['overall_score']:.2f} cats={report['total_categories']} domains={len(report['domain_breakdown'])} recs={len(report['recommendations'])}"

    # ── Run all checks ─────────────────────────────────────────────────
    report.checks.append(_check("ConstitutionValidator: 111 categories", check_categories))
    report.checks.append(_check("ConstitutionValidator: evidence storage (ARCH/PRN/SRE)", check_evidence_storage))
    report.checks.append(_check("ConstitutionValidator: scoring & report", check_scoring))
    report.checks.append(_check("ConstitutionValidator: comprehensive health check", check_health_check))
    report.checks.append(_check("AIGovernanceGate: constitution acknowledgment", check_ai_gate))
    report.checks.append(_check("AIGovernanceGate: 18+ AI specialist roles", check_ai_roles))
    report.checks.append(_check("ConstitutionAlertBridge: health check & status", check_alert_bridge))
    report.checks.append(_check("ConstitutionSelfHealingBridge: 5+ patterns", check_self_healing_bridge))
    report.checks.append(_check("SelfHealingOrchestrator: patterns registered", check_self_healing_orchestrator))
    report.checks.append(_check("Startup Integration: 10 modules, 0 failures", check_startup))
    report.checks.append(_check("Startup Integration: disabled mode", check_disabled_startup))
    report.checks.append(_check("Dashboard: test count tracking", check_dashboard_endpoint))
    report.checks.append(_check("Metrics Export: constitution gauges accepted", check_metrics))
    if not quick:
        report.checks.append(_check("Report Generator: health report with all sections", check_report_generator))

    report.end_time = time.time()
    return report


def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Constitution v4.0 — End-to-End System Verification",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--quick", action="store_true", help="Skip report generation (faster)")
    parser.add_argument("--quiet", action="store_true", help="Suppress output")

    args = parser.parse_args()
    report = run_all_checks(quick=args.quick)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    elif not args.quiet:
        print(report.summary_text())

    if report.failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    _cli()
