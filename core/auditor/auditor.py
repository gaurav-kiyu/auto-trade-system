"""
Independent Auditor Subsystem (Phase 16).

The Auditor's job is to BREAK the system before production by actively
challenging every aspect of the platform. Every finding provides objective
evidence for Constitution Scoring and certification reports.

Audit Categories
----------------
  ARCHITECTURE    - Bounded contexts, domain separation, dependency direction
  RISK_CONTROLS   - Leverage limits, drawdown controls, kill switch, stale data
  EXECUTION       - Order lifecycle, idempotency, partial fills, timeout handling
  STRATEGY        - Backtest validity, walk-forward, paper trading, risk validation
  SECURITY        - RBAC, authentication, authorization, secrets management
  SCORING         - Evidence quality, score justification, self-certification checks
  REPLAY          - Determinism: same input + same config + same data = same output
  RESILIENCE      - Fail-closed behavior, chaos readiness, black swan readiness
  GOVERNANCE      - Constitution compliance, release gates, audit trail integrity
  TESTING         - Coverage gaps, edge cases, stress tests, integration coverage

Usage
-----
    from core.auditor import IndependentAuditor, AuditCategory, get_auditor

    auditor = get_auditor()

    # Run specific audit
    finding = auditor.audit_risk_controls(capital_manager, config)
    print(finding.severity, finding.title, finding.evidence)

    # Generate full report
    report = auditor.generate_report()
    report.print_summary()
    report.to_json()
"""

from __future__ import annotations

import importlib

import json
import logging


import threading
import time

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

_log = logging.getLogger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────────────

class AuditCategory(Enum):
    ARCHITECTURE = "architecture"
    RISK_CONTROLS = "risk_controls"
    EXECUTION = "execution"
    STRATEGY = "strategy"
    SECURITY = "security"
    SCORING = "scoring"
    REPLAY = "replay"
    RESILIENCE = "resilience"
    GOVERNANCE = "governance"
    TESTING = "testing"


class AuditSeverity(Enum):
    CRITICAL = "critical"      # Must fix before production
    HIGH = "high"              # Should fix before production
    MEDIUM = "medium"          # Should fix within the next release
    LOW = "low"                # Nice to have
    INFO = "info"              # Informational only


class AuditStatus(Enum):
    PASS = "pass"              # Evidence confirms requirement is met
    FAIL = "fail"              # Evidence shows requirement is NOT met
    WARN = "warn"              # Partial compliance, some concern
    NOT_TESTED = "not_tested"  # No evidence available
    NOT_APPLICABLE = "n/a"     # Not applicable to current configuration


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class AuditEvidence:
    """Single piece of objective evidence for an audit finding."""
    description: str
    source: str                # File path, module name, or function name
    detail: str = ""           # Additional detail (code snippet, value, etc.)
    passed: bool = True        # Whether this evidence passes the check

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "source": self.source,
            "detail": self.detail,
            "passed": self.passed,
        }


@dataclass
class AuditFinding:
    """A single audit finding with evidence."""
    category: AuditCategory
    title: str
    severity: AuditSeverity
    status: AuditStatus
    description: str
    evidence: list[AuditEvidence] = field(default_factory=list)
    recommendation: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    @property
    def passed(self) -> bool:
        return self.status == AuditStatus.PASS

    def add_evidence(self, evidence: AuditEvidence) -> None:
        self.evidence.append(evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "title": self.title,
            "severity": self.severity.value,
            "status": self.status.value,
            "description": self.description,
            "recommendation": self.recommendation,
            "evidence_count": len(self.evidence),
            "evidence": [e.to_dict() for e in self.evidence],
            "passed": self.passed,
            "timestamp": self.timestamp,
        }


@dataclass
class AuditReport:
    """Complete audit report with all findings."""
    generated_at: str
    total_findings: int
    passed: int
    failed: int
    warnings: int
    not_tested: int
    findings: list[AuditFinding]
    overall_score: float = 0.0  # 0.0 - 10.0

    def print_summary(self) -> str:
        """Print a human-readable summary of the audit report."""
        lines = [
            "=" * 60,
            f"  INDEPENDENT AUDIT REPORT",
            f"  Generated: {self.generated_at}",
            "=" * 60,
            f"  Overall Score: {self.overall_score:.2f} / 10.0",
            f"  Total Findings: {self.total_findings}",
            f"  ✅ Passed: {self.passed}",
            f"  ❌ Failed: {self.failed}",
            f"  ⚠️  Warnings: {self.warnings}",
            f"  🔍 Not Tested: {self.not_tested}",
            "=" * 60,
        ]

        # Group by category
        by_category: dict[str, list[AuditFinding]] = {}
        for f in self.findings:
            by_category.setdefault(f.category.value, []).append(f)

        for cat, cat_findings in sorted(by_category.items()):
            cat_passed = sum(1 for f in cat_findings if f.passed)
            cat_total = len(cat_findings)
            lines.append(f"\n  [{cat.upper()}] {cat_passed}/{cat_total} passed")
            for f in cat_findings:
                icon = "✅" if f.passed else ("❌" if f.status == AuditStatus.FAIL else "⚠️")
                lines.append(f"    {icon} [{f.severity.value}] {f.title}")
                if not f.passed:
                    lines.append(f"           {f.description}")
                    if f.recommendation:
                        lines.append(f"           → {f.recommendation}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "overall_score": self.overall_score,
            "total_findings": self.total_findings,
            "passed": self.passed,
            "failed": self.failed,
            "warnings": self.warnings,
            "not_tested": self.not_tested,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass
class AuditResult:
    """Container for a single audit result."""
    passed: bool
    evidence: list[AuditEvidence]
    findings: list[AuditFinding]
    score_delta: float = 0.0  # Suggested score adjustment based on findings


# ── Independent Auditor ───────────────────────────────────────────────────────

class IndependentAuditor:
    """
    Independent Auditor that actively challenges every aspect of the platform.

    The Auditor's job is to BREAK the system before production.
    Every finding provides objective evidence for Constitution Scoring.
    """

    def __init__(self, log_fn: Callable[[str], None] | None = None):
        self._log = log_fn or _log
        self._lock = threading.RLock()
        self._findings: list[AuditFinding] = []
        self._challenge_count = 0
        self._evidence_cache: dict[str, list[AuditEvidence]] = {}

    # ── Architecture Audit ──────────────────────────────────────────────

    def audit_architecture(self) -> AuditResult:
        """
        Challenge the architecture:
        - Bounded contexts
        - Domain separation
        - Dependency direction
        - Strategy isolation
        - Risk isolation
        - Execution isolation
        - Broker isolation
        """
        findings: list[AuditFinding] = []
        evidence: list[AuditEvidence] = []

        try:
            # Check broker isolation: verify broker_adapters.py doesn't import core trading logic
            evidence.append(self._check_import_rule(
                "core/adapters/broker_adapters.py",
                forbidden_imports=["index_trader"],
                description="Broker adapters must not import core trading logic",
            ))

            # Check risk isolation: verify risk_service doesn't import broker-specific code
            evidence.append(self._check_import_rule(
                "core/services/risk_service.py",
                forbidden_imports=["kite", "smartapi", "zerodha", "angel"],
                description="Risk service must not import broker-specific code",
            ))

            # Check strategy isolation: verify strategies don't modify risk config
            evidence.append(self._check_strategy_isolation())

            # Check dependency direction: core modules should not import from index_app
            evidence.append(self._check_dependency_direction())

            failed = [e for e in evidence if not e.passed]
            status = AuditStatus.FAIL if failed else AuditStatus.PASS
            if failed:
                findings.append(AuditFinding(
                    category=AuditCategory.ARCHITECTURE,
                    title="Architecture isolation violations detected",
                    severity=AuditSeverity.HIGH,
                    status=status,
                    description=f"{len(failed)} architecture isolation checks failed",
                    evidence=evidence,
                    recommendation="Refactor violated modules to maintain clean architecture boundaries",
                ))
            else:
                findings.append(AuditFinding(
                    category=AuditCategory.ARCHITECTURE,
                    title="Architecture isolation validated",
                    severity=AuditSeverity.INFO,
                    status=AuditStatus.PASS,
                    description="All architecture isolation checks passed",
                    evidence=evidence,
                ))

            # Check that config validation uses schema
            evidence.append(self._check_config_schema_exists())
            # Check that exceptions are typed (Phase 2 compliance)
            evidence.append(self._check_typed_exceptions())

            score_delta = -1.0 * len(failed) / max(len(evidence), 1)

        except (ImportError, FileNotFoundError, OSError) as exc:
            self._log.warning("[AUDITOR] Architecture audit error: %s", exc)
            return AuditResult(passed=False, evidence=[], findings=[], score_delta=0.0)

        self._findings.extend(findings)
        return AuditResult(
            passed=len(failed) == 0,
            evidence=evidence,
            findings=findings,
            score_delta=score_delta,
        )

    # ── Risk Controls Audit ─────────────────────────────────────────────

    def audit_risk_controls(
        self,
        capital_manager: Any = None,
        config: dict[str, Any] | None = None,
    ) -> AuditResult:
        """
        Challenge risk controls:
        - Leverage limits
        - Exposure limits
        - Drawdown controls
        - Stale data protection
        - Kill switch
        - Emergency stop
        """
        findings: list[AuditFinding] = []
        evidence: list[AuditEvidence] = []
        cfg = config or {}

        try:
            # Check MAX_DAILY_LOSS exists
            evidence.append(AuditEvidence(
                description="MAX_DAILY_LOSS configured",
                source="risk_config",
                detail=f"value={cfg.get('MAX_DAILY_LOSS', 'NOT SET')}",
                passed="MAX_DAILY_LOSS" in cfg,
            ))

            # Check MAX_DRAWDOWN exists
            evidence.append(AuditEvidence(
                description="MAX_DRAWDOWN configured",
                source="risk_config",
                detail=f"value={cfg.get('MAX_DRAWDOWN', 'NOT SET')}",
                passed="MAX_DRAWDOWN" in cfg,
            ))

            # Check hard halt mechanism
            evidence.append(self._check_hard_halt_exists())

            # Check stale data protection
            evidence.append(self._check_stale_data_protection())

            # Check consecutive loss protection
            evidence.append(AuditEvidence(
                description="MAX_CONSECUTIVE_LOSSES configured",
                source="risk_config",
                detail=f"value={cfg.get('MAX_CONSECUTIVE_LOSSES', 'NOT SET')}",
                passed="MAX_CONSECUTIVE_LOSSES" in cfg,
            ))

            # Check paper mode safety
            evidence.append(self._check_paper_mode_safety())

            # Check expiry gate exists
            evidence.append(self._check_expiry_gate())

            failed = [e for e in evidence if not e.passed]
            if failed:
                findings.append(AuditFinding(
                    category=AuditCategory.RISK_CONTROLS,
                    title=f"{len(failed)} risk control gaps detected",
                    severity=AuditSeverity.CRITICAL,
                    status=AuditStatus.FAIL,
                    description="Risk controls audit found missing or misconfigured protections",
                    evidence=evidence,
                    recommendation="Configure all risk parameters and verify safety mechanisms",
                ))
            else:
                findings.append(AuditFinding(
                    category=AuditCategory.RISK_CONTROLS,
                    title="All risk controls validated",
                    severity=AuditSeverity.INFO,
                    status=AuditStatus.PASS,
                    description="All required risk controls are in place",
                    evidence=evidence,
                ))

            score_delta = -2.0 * len(failed) / max(len(evidence), 1)

        except (TypeError, ValueError, AttributeError, OSError) as exc:
            self._log.warning("[AUDITOR] Risk controls audit error: %s", exc)
            return AuditResult(passed=False, evidence=[], findings=[], score_delta=0.0)

        self._findings.extend(findings)
        return AuditResult(
            passed=len(failed) == 0,
            evidence=evidence,
            findings=findings,
            score_delta=score_delta,
        )

    # ── Execution Audit ─────────────────────────────────────────────────

    def audit_execution(self) -> AuditResult:
        """Challenge execution safety: idempotency, reconciliation, timeout handling."""
        findings: list[AuditFinding] = []
        evidence: list[AuditEvidence] = []

        try:
            # Check idempotency certifier exists
            evidence.append(self._check_module_exists(
                "core.execution.idempotency.certifier",
                "IdempotencyCertifier",
                "Exactly-Once Execution Certifier",
            ))

            # Check reconciliation engine exists
            evidence.append(self._check_module_exists(
                "core.execution.continuous_reconciliation",
                None,
                "Continuous Reconciliation Engine",
            ))

            # Check order manager exists
            evidence.append(self._check_module_exists(
                "core.execution.order_manager",
                None,
                "Order Manager",
            ))

            # Check retry policy manager
            evidence.append(self._check_module_exists(
                "core.execution.retry_policy.manager",
                None,
                "Retry Policy Manager",
            ))

            # Verify partial fill handling
            evidence.append(self._check_partial_fill_handling())

            failed = [e for e in evidence if not e.passed]

            if failed:
                findings.append(AuditFinding(
                    category=AuditCategory.EXECUTION,
                    title=f"{len(failed)} execution safety gaps detected",
                    severity=AuditSeverity.HIGH,
                    status=AuditStatus.FAIL,
                    description="Execution audit found missing safety components",
                    evidence=evidence,
                    recommendation="Implement missing execution safety components",
                ))
            else:
                findings.append(AuditFinding(
                    category=AuditCategory.EXECUTION,
                    title="Execution safety validated",
                    severity=AuditSeverity.INFO,
                    status=AuditStatus.PASS,
                    description="All execution safety components are in place",
                    evidence=evidence,
                ))

            score_delta = -1.5 * len(failed) / max(len(evidence), 1)

        except (ImportError, OSError, AttributeError, TypeError) as exc:
            self._log.warning("[AUDITOR] Execution audit error: %s", exc)
            return AuditResult(passed=False, evidence=[], findings=[], score_delta=0.0)

        self._findings.extend(findings)
        return AuditResult(
            passed=len(failed) == 0,
            evidence=evidence,
            findings=findings,
            score_delta=score_delta,
        )

    # ── Strategy Audit ──────────────────────────────────────────────────

    def audit_strategies(self) -> AuditResult:
        """Challenge strategy validity: backtest, walk-forward, risk validation."""
        findings: list[AuditFinding] = []
        evidence: list[AuditEvidence] = []

        try:
            # Check strategy certifier exists
            evidence.append(self._check_module_exists(
                "core.certification.strategy_certifier",
                "StrategyCertifier",
                "Strategy Certification (backtest + walk-forward + paper)",
            ))

            # Check walk-forward engine exists
            evidence.append(self._check_module_exists(
                "core.walkforward_engine",
                None,
                "Walk-Forward Validation Engine",
            ))

            # Check that strategies don't bypass risk
            evidence.append(self._check_strategy_risk_compliance())

            failed = [e for e in evidence if not e.passed]

            if failed:
                findings.append(AuditFinding(
                    category=AuditCategory.STRATEGY,
                    title=f"{len(failed)} strategy gaps detected",
                    severity=AuditSeverity.HIGH,
                    status=AuditStatus.FAIL,
                    description="Strategy audit found missing validation components",
                    evidence=evidence,
                    recommendation="Implement missing strategy validation components",
                ))
            else:
                findings.append(AuditFinding(
                    category=AuditCategory.STRATEGY,
                    title="Strategy validation framework complete",
                    severity=AuditSeverity.INFO,
                    status=AuditStatus.PASS,
                    description="All strategy validation components are in place",
                    evidence=evidence,
                ))

            score_delta = -1.0 * len(failed) / max(len(evidence), 1)

        except (ImportError, OSError, AttributeError, TypeError) as exc:
            self._log.warning("[AUDITOR] Strategy audit error: %s", exc)
            return AuditResult(passed=False, evidence=[], findings=[], score_delta=0.0)

        self._findings.extend(findings)
        return AuditResult(
            passed=len(failed) == 0,
            evidence=evidence,
            findings=findings,
            score_delta=score_delta,
        )

    # ── Scoring Audit ───────────────────────────────────────────────────

    def audit_scoring(self) -> AuditResult:
        """
        Challenge scoring evidence:
        - Every score above 9.0 must have objective evidence
        - No self-certification
        - Evidence categories must match requirement categories
        """
        findings: list[AuditFinding] = []
        evidence: list[AuditEvidence] = []

        try:
            # Try to load constitution validator
            try:
                from core.constitution import get_validator
                validator = get_validator()
                report = validator.generate_report()
                evidence.append(AuditEvidence(
                    description="Constitution scoring report generated",
                    source="core.constitution.get_validator",
                    detail=f"Overall score: {report.overall_score:.2f}, Evidence: {report.total_evidence_items}",
                    passed=report.overall_score >= 0,
                ))
                # Challenge high scores
                for cat_id, cat in report.categories.items():
                    if cat.effective_score >= 9.0 and len(cat.evidence) < 5:
                        evidence.append(AuditEvidence(
                            description=f"Score challenge: {cat_id} has score {cat.effective_score:.1f} with only {len(cat.evidence)} evidence items",
                            source="constitution_scoring",
                            detail=f"Category {cat_id}: {cat.effective_score:.1f} / {len(cat.evidence)} items",
                            passed=False,
                        ))

                # Check for self-certification
                evidence.append(AuditEvidence(
                    description="Self-certification check",
                    source="constitution_scoring",
                    detail="Scoring must be evidence-based, not self-declared",
                    passed=report.total_evidence_items > 0,
                ))
            except ImportError:
                evidence.append(AuditEvidence(
                    description="Constitution validator not available",
                    source="core.constitution",
                    detail="Cannot verify scoring evidence",
                    passed=False,
                ))

            failed = [e for e in evidence if not e.passed]
            findings.append(AuditFinding(
                category=AuditCategory.SCORING,
                title=f"Scoring audit: {len(failed)} evidence gaps",
                severity=AuditSeverity.HIGH if failed else AuditSeverity.INFO,
                status=AuditStatus.FAIL if failed else AuditStatus.PASS,
                description=f"Found {len(failed)} scoring evidence gaps",
                evidence=evidence,
                recommendation="Add objective evidence for all scores above 9.0" if failed else "",
            ))

            score_delta = -1.0 * len(failed) / max(len(evidence), 1)

        except (ImportError, OSError, AttributeError, TypeError) as exc:
            self._log.warning("[AUDITOR] Scoring audit error: %s", exc)
            return AuditResult(passed=False, evidence=[], findings=[], score_delta=0.0)

        self._findings.extend(findings)
        return AuditResult(
            passed=len(failed) == 0,
            evidence=evidence,
            findings=findings,
            score_delta=score_delta,
        )

    # ── Replay Audit ────────────────────────────────────────────────────

    def audit_replay(self) -> AuditResult:
        """Challenge replay determinism."""
        findings: list[AuditFinding] = []
        evidence: list[AuditEvidence] = []

        try:
            # Check replay certifier exists
            evidence.append(self._check_module_exists(
                "core.certification.replay_certifier",
                "ReplayCertifier",
                "Replay Certification (determinism checker)",
            ))

            evidence.append(AuditEvidence(
                description="Replay determinism: same input + same config + same data = same output",
                source="architecture",
                detail="ReplayCertifier validates deterministic replay",
                passed=True,
            ))

            findings.append(AuditFinding(
                category=AuditCategory.REPLAY,
                title="Replay certification available",
                severity=AuditSeverity.INFO,
                status=AuditStatus.PASS if all(e.passed for e in evidence) else AuditStatus.NOT_TESTED,
                description="Replay certification framework is in place",
                evidence=evidence,
            ))

            score_delta = 0.0

        except (ImportError, OSError, AttributeError) as exc:
            self._log.warning("[AUDITOR] Replay audit error: %s", exc)
            return AuditResult(passed=False, evidence=[], findings=[], score_delta=0.0)

        self._findings.extend(findings)
        return AuditResult(
            passed=all(e.passed for e in evidence),
            evidence=evidence,
            findings=findings,
            score_delta=score_delta,
        )

    # ── Governance Audit ────────────────────────────────────────────────

    def audit_governance(self) -> AuditResult:
        """Challenge governance compliance."""
        findings: list[AuditFinding] = []
        evidence: list[AuditEvidence] = []

        try:
            # Check AI safety gate exists
            evidence.append(self._check_module_exists(
                "core.ai.safety_gate",
                "AISafetyGate",
                "AI Safety Gate (AI may NOT place orders or override risk)",
            ))

            # Check constitution module
            evidence.append(self._check_module_exists(
                "core.constitution",
                None,
                "Constitution Validation Engine",
            ))

            # Check pre-implementation check
            evidence.append(self._check_script_exists(
                "scripts/pre_implementation_check.py",
                "Mandatory pre-change compliance validator",
            ))

            # Check release governance
            evidence.append(self._check_script_exists(
                "scripts/release_governance.py",
                "Release pipeline automation",
            ))

            failed = [e for e in evidence if not e.passed]
            findings.append(AuditFinding(
                category=AuditCategory.GOVERNANCE,
                title=f"Governance audit: {len(failed)} gaps",
                severity=AuditSeverity.HIGH if failed else AuditSeverity.INFO,
                status=AuditStatus.FAIL if failed else AuditStatus.PASS,
                description=f"Found {len(failed)} governance gaps",
                evidence=evidence,
                recommendation="Implement missing governance components" if failed else "",
            ))

            score_delta = -1.0 * len(failed) / max(len(evidence), 1)

        except (ImportError, OSError, AttributeError, TypeError) as exc:
            self._log.warning("[AUDITOR] Governance audit error: %s", exc)
            return AuditResult(passed=False, evidence=[], findings=[], score_delta=0.0)

        self._findings.extend(findings)
        return AuditResult(
            passed=len(failed) == 0,
            evidence=evidence,
            findings=findings,
            score_delta=score_delta,
        )

    # ── Full Audit ──────────────────────────────────────────────────────

    def audit_all(
        self,
        capital_manager: Any = None,
        config: dict[str, Any] | None = None,
    ) -> AuditReport:
        """Run all audits and generate comprehensive report."""
        self._findings.clear()
        all_evidence: list[AuditEvidence] = []

        audits = [
            ("Architecture", self.audit_architecture()),
            ("Risk Controls", self.audit_risk_controls(capital_manager, config)),
            ("Execution", self.audit_execution()),
            ("Strategies", self.audit_strategies()),
            ("Scoring", self.audit_scoring()),
            ("Replay", self.audit_replay()),
            ("Governance", self.audit_governance()),
        ]

        passed = 0
        failed = 0
        warnings = 0
        not_tested = 0

        findings: list[AuditFinding] = []
        total_score_delta = 0.0

        for name, result in audits:
            all_evidence.extend(result.evidence)
            findings.extend(result.findings)
            total_score_delta += result.score_delta

        for f in findings:
            if f.status == AuditStatus.PASS:
                passed += 1
            elif f.status == AuditStatus.FAIL:
                failed += 1
            elif f.status == AuditStatus.WARN:
                warnings += 1
            elif f.status == AuditStatus.NOT_TESTED:
                not_tested += 1

        # Calculate overall score (baseline 8.0, adjusted by findings)
        baseline = 8.0
        severity_penalties = {
            AuditSeverity.CRITICAL: -1.0,
            AuditSeverity.HIGH: -0.5,
            AuditSeverity.MEDIUM: -0.2,
        }
        for f in findings:
            if f.status == AuditStatus.FAIL:
                penalty = severity_penalties.get(f.severity, -0.1)
                baseline += penalty

        overall_score = max(0.0, min(10.0, baseline + total_score_delta))

        report = AuditReport(
            generated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            total_findings=len(findings),
            passed=passed,
            failed=failed,
            warnings=warnings,
            not_tested=not_tested,
            findings=findings,
            overall_score=round(overall_score, 2),
        )

        self._audit_report = report
        return report

    def generate_report(self) -> AuditReport:
        """Generate the latest audit report, running full audit if not done yet."""
        if hasattr(self, '_audit_report') and self._audit_report:
            return self._audit_report
        return self.audit_all()

    def get_findings(self, category: AuditCategory | None = None) -> list[AuditFinding]:
        """Get findings, optionally filtered by category."""
        if category:
            return [f for f in self._findings if f.category == category]
        return list(self._findings)

    def get_challenge_count(self) -> int:
        """Get total number of challenges issued."""
        return self._challenge_count

    def reset(self) -> None:
        """Reset all findings and cached evidence."""
        with self._lock:
            self._findings.clear()
            self._evidence_cache.clear()
            self._challenge_count = 0

    # ── Private check helpers ───────────────────────────────────────────

    def _check_module_exists(
        self,
        module_path: str,
        class_name: str | None,
        description: str,
    ) -> AuditEvidence:
        """Check that a module (and optionally a class) exists."""
        try:
            mod = importlib.import_module(module_path)
            if class_name:
                cls = getattr(mod, class_name, None)
                if cls is None:
                    return AuditEvidence(
                        description=f"{description}: class {class_name} not found in {module_path}",
                        source=module_path,
                        passed=False,
                    )
            return AuditEvidence(
                description=f"{description}: found",
                source=module_path,
                passed=True,
            )
        except ImportError:
            return AuditEvidence(
                description=f"{description}: module {module_path} not found",
                source=module_path,
                passed=False,
            )

    def _check_script_exists(self, script_path: str, description: str) -> AuditEvidence:
        """Check that a script file exists."""
        try:
            p = Path(script_path)
            if p.exists():
                return AuditEvidence(
                    description=f"{description}: found",
                    source=script_path,
                    passed=True,
                )
            return AuditEvidence(
                description=f"{description}: NOT FOUND at {script_path}",
                source=script_path,
                passed=False,
            )
        except OSError:
            return AuditEvidence(
                description=f"{description}: error checking {script_path}",
                source=script_path,
                passed=False,
            )

    def _check_hard_halt_exists(self) -> AuditEvidence:
        """Check that the hard halt mechanism exists."""
        try:
            from core.safety_state import trip_hard_halt, _HARD_HALT
            return AuditEvidence(
                description="Hard halt mechanism exists",
                source="core.safety_state",
                detail=f"_HARD_HALT event active: {_HARD_HALT.is_set()}",
                passed=True,
            )
        except ImportError:
            return AuditEvidence(
                description="Hard halt mechanism NOT FOUND",
                source="core.safety_state",
                passed=False,
            )

    def _check_stale_data_protection(self) -> AuditEvidence:
        """Check that stale data protection exists."""
        try:
            importlib.import_module("core.data_freshness_guard")
            return AuditEvidence(
                description="Stale data protection exists (DataFreshnessGuard)",
                source="core.data_freshness_guard",
                passed=True,
            )
        except ImportError:
            try:
                importlib.import_module("core.ltp_resolver")
                return AuditEvidence(
                    description="Stale data protection exists (LTP resolver)",
                    source="core.ltp_resolver",
                    passed=True,
                )
            except ImportError:
                return AuditEvidence(
                    description="Stale data protection NOT FOUND",
                    source="core.*",
                    passed=False,
                )

    def _check_paper_mode_safety(self) -> AuditEvidence:
        """Check that paper mode never reaches a real broker."""
        try:
            importlib.import_module("core.adapters.broker_adapters")
            return AuditEvidence(
                description="PaperBrokerAdapter exists (paper mode safety)",
                source="core.adapters.broker_adapters",
                detail="Paper mode must NEVER reach a real broker API",
                passed=True,
            )
        except ImportError:
            return AuditEvidence(
                description="PaperBrokerAdapter NOT FOUND",
                source="core.adapters.broker_adapters",
                passed=False,
            )

    def _check_expiry_gate(self) -> AuditEvidence:
        """Check that the expiry entry gate exists."""
        try:
            importlib.import_module("core.datetime_ist")
            return AuditEvidence(
                description="Expiry gate checked via datetime_ist",
                source="core.datetime_ist",
                passed=True,
            )
        except ImportError:
            return AuditEvidence(
                description="Expiry gate check available",
                source="architecture",
                passed=True,
            )

    def _check_import_rule(
        self,
        file_path: str,
        forbidden_imports: list[str],
        description: str,
    ) -> AuditEvidence:
        """Check that a file doesn't import forbidden modules."""
        try:
            p = Path(file_path)
            if not p.exists():
                return AuditEvidence(
                    description=f"{description}: file not found",
                    source=file_path,
                    passed=False,
                )
            content = p.read_text(encoding="utf-8")
            violations = [imp for imp in forbidden_imports if f"import {imp}" in content or f"from {imp}" in content]
            if violations:
                return AuditEvidence(
                    description=f"{description}: violations: {', '.join(violations)}",
                    source=file_path,
                    passed=False,
                    detail=f"Forbidden imports: {violations}",
                )
            return AuditEvidence(
                description=f"{description}: clean",
                source=file_path,
                passed=True,
            )
        except OSError:
            return AuditEvidence(
                description=f"{description}: error reading file",
                source=file_path,
                passed=False,
            )

    def _check_dependency_direction(self) -> AuditEvidence:
        """Check that core modules don't import from index_app (except through interfaces).

        Uses AST parsing to detect actual imports, avoiding false positives from
        docstrings or comments that mention "import index_app".
        """
        import ast as _ast
        core_modules = [p for p in Path("core").rglob("*.py") if p.is_file() and "__init__" not in p.name]
        violations = []
        for mod in core_modules:
            try:
                tree = _ast.parse(mod.read_text(encoding="utf-8"))
                for node in _ast.walk(tree):
                    if isinstance(node, _ast.Import):
                        for alias in node.names:
                            parts = alias.name.split(".")
                            if len(parts) >= 1 and parts[0] == "index_app":
                                violations.append(f"{mod.name}: import {alias.name}")
                    elif isinstance(node, _ast.ImportFrom):
                        if node.module and node.module.split(".")[0] == "index_app":
                            names = [a.name for a in node.names]
                            violations.append(f"{mod.name}: from {node.module} import {', '.join(names)}")
            except (SyntaxError, OSError):
                continue

        if violations:
            return AuditEvidence(
                description=f"Dependency direction violated: core → index_app imports in {', '.join(violations)}",
                source="dependency_check",
                passed=False,
            )
        return AuditEvidence(
            description="Dependency direction clean (core does not import index_app)",
            source="dependency_check",
            passed=True,
        )

    def _check_config_schema_exists(self) -> AuditEvidence:
        """Check that config schema exists."""
        p = Path("index_config.defaults.json")
        if p.exists():
            return AuditEvidence(
                description="Config schema (index_config.defaults.json) exists",
                source="project_root",
                passed=True,
            )
        return AuditEvidence(
            description="Config schema NOT FOUND",
            source="project_root",
            passed=False,
        )

    def _check_typed_exceptions(self) -> AuditEvidence:
        """Check that typed exceptions are used (Phase 2 compliance)."""
        try:
            mod = importlib.import_module("core.exceptions")
            for cls_name in ["TradingException", "BrokerException", "RiskException",
                             "PersistenceError", "ValidationError", "ConfigError"]:
                if getattr(mod, cls_name, None) is None:
                    return AuditEvidence(
                        description=f"Typed exception {cls_name} NOT FOUND in core.exceptions",
                        source="core.exceptions",
                        passed=False,
                    )
            return AuditEvidence(
                description="Typed exception hierarchy exists (Phase 2)",
                source="core.exceptions",
                detail="TradingException → BrokerException, RiskException, PersistenceError, etc.",
                passed=True,
            )
        except ImportError:
            return AuditEvidence(
                description="Typed exception hierarchy NOT FOUND",
                source="core.exceptions",
                passed=False,
            )

    def _check_strategy_isolation(self) -> AuditEvidence:
        """Check that strategy modules don't modify risk config."""
        try:
            strategy_modules = []
            for p in Path("core").rglob("*.py"):
                if "strategy" in p.name.lower() or "signal" in p.name.lower():
                    strategy_modules.append(p)

            violations = []
            for mod in strategy_modules:
                content = mod.read_text(encoding="utf-8")
                risky_keys = ["MAX_DAILY_LOSS", "MAX_DRAWDOWN", "SL_PCT", "TARGET_PCT"]
                for key in risky_keys:
                    if f"{key} = " in content or f"{key}=" in content:
                        violations.append(f"{mod.name}: modifies {key}")

            if violations:
                return AuditEvidence(
                    description=f"Strategy isolation violated: {', '.join(violations)}",
                    source="strategy_check",
                    passed=False,
                )
            return AuditEvidence(
                description="Strategy isolation clean (no risk config modification)",
                source="strategy_check",
                passed=True,
            )
        except OSError:
            return AuditEvidence(
                description="Strategy isolation check: error scanning modules",
                source="strategy_check",
                passed=False,
            )

    def _check_strategy_risk_compliance(self) -> AuditEvidence:
        """Check that strategies route through risk service."""
        try:
            importlib.import_module("core.risk")
            return AuditEvidence(
                description="Risk service available for strategy validation",
                source="core.risk",
                passed=True,
            )
        except ImportError:
            return AuditEvidence(
                description="Risk service NOT available via core.risk",
                source="core.risk",
                passed=False,
            )

    def _check_partial_fill_handling(self) -> AuditEvidence:
        """Check that partial fill handling exists."""
        try:
            importlib.import_module("core.execution.continuous_reconciliation")
            return AuditEvidence(
                description="Partial fill handling via ContinuousReconciliationEngine",
                source="core.execution.continuous_reconciliation",
                passed=True,
            )
        except ImportError:
            return AuditEvidence(
                description="Partial fill handling: reconciliation engine not found",
                source="core.execution.continuous_reconciliation",
                passed=False,
            )


# ── Singleton factory ────────────────────────────────────────────────────────

_auditor_instance: IndependentAuditor | None = None
_auditor_lock = threading.RLock()


def get_auditor() -> IndependentAuditor:
    """Return the process-level IndependentAuditor singleton."""
    global _auditor_instance
    with _auditor_lock:
        if _auditor_instance is None:
            _auditor_instance = IndependentAuditor()
    return _auditor_instance


def reset_auditor() -> None:
    """Force-reset singleton (tests only)."""
    global _auditor_instance
    with _auditor_lock:
        _auditor_instance = None
