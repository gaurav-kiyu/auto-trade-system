"""AI Governance Gate - Pre-implementation validation for AI agents.

Every AI agent MUST pass through this gate before making changes to the codebase.
The gate enforces:
  1. Constitution acknowledgment
  2. Context gathering
  3. Evidence attachment for score changes
  4. Change pipeline validation

Usage:
    from core.constitution_ai_gate import AIGovernanceGate, AIGateResult

    gate = AIGovernanceGate()
    result = gate.validate(
        constitution_acknowledged=True,
        claude_read=True,
        architecture_reviewed=True,
        audit_history_reviewed=True,
        risk_controls_verified=True,
        changed_files=["core/foo.py"],
    )
    if not result.passed:
        print(f"Gate blocked: {result.reason}")
        # AI must stop and report the failure
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class AIGateResult:
    """Result of an AI governance gate validation."""

    passed: bool
    reason: str = ""
    detail: str = ""
    failures: list[str] = field(default_factory=list)
    timestamp: float = 0.0
    identity: str = ""

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class AIGateEvent:
    """Audit event for AI governance gate actions."""

    ts: float
    action: str
    identity: str
    result: str
    detail: str


# ── Forbidden actions registry ───────────────────────────────────────────────

# Risk-control keywords checked in context of modified files
RISK_CONTROL_KEYWORDS: list[str] = [
    "_trip_hard_halt",
    "MAX_DAILY_LOSS",
    "MAX_DRAWDOWN",
    "SL_PCT",
    "TARGET_PCT",
    "TRAIL_PCT",
    "PORTFOLIO_MAX_SL_RISK_PCT",
    "expiry_entry_allowed",
    "PaperBrokerAdapter",
]

# Direct broker SDK call patterns (checked in context)
BROKER_SDK_PATTERNS: list[str] = [
    "from kiteconnect",
    "from angelbroking",
]

# Bypass patterns that trigger warnings
BYPASS_PATTERNS: list[str] = [
    "datetime.now()",
]

FORBIDDEN_FILE_TARGETS: list[str] = [
    # Do not modify these files without explicit human approval
    "test_smoke.py",
    "test_broker_contract_certification.py",
    "test_exactly_once_certification.py",
]


# ── AI Governance Gate ────────────────────────────────────────────────────────


class AIGovernanceGate:
    """Gate that validates AI agents before they make changes.

    This gate enforces the AI Governance article of the Master Engineering Constitution v4.0.
    Every AI agent MUST pass through this gate before implementing changes.

    v4.0 Features:
      - 18 AI Specialist Roles with role-specific checks
      - 12 Enterprise Layer awareness
      - Role-specific forbidden actions registry
      - Layer-aware validation context
    """

    # ── v4.0: Constitution Acknowledgment ─────────────────────────────────
    CONSTITUTION_ACKNOWLEDGMENT = (
        "I have read the Master Engineering Constitution v4.0. "
        "I acknowledge that CORRECTNESS > FEATURES and SAFETY > SPEED. "
        "I will follow the Mandatory Change Pipeline and Definition of Done. "
        "I accept my assigned AI Specialist Role and its responsibilities."
    )

    # ── v4.0: 18 AI Specialist Roles with forbidden keywords per role ─────
    AI_SPECIALIST_ROLES: dict[str, dict[str, Any]] = {
        "PLANNER": {
            "name": "Planner",
            "responsibilities": "Break down work, create implementation plans, estimate effort",
            "forbidden_actions": ["skip impact analysis", "bypass architecture review", "ignore dependencies"],
            "required_readings": ["docs/architecture.md", "docs/technical_debt.md"],
        },
        "PRINCIPAL_ARCHITECT": {
            "name": "Principal Architect",
            "responsibilities": "Design system architecture, validate patterns, enforce standards",
            "forbidden_actions": ["violate clean architecture", "introduce circular dependency", "bypass adr process"],
            "required_readings": ["docs/adr/", "docs/architecture.md"],
        },
        "DEVELOPER": {
            "name": "Developer",
            "responsibilities": "Write code, implement features, fix bugs",
            "forbidden_actions": ["modify risk controls without review", "skip testing", "introduce security vulnerability"],
            "required_readings": ["CLAUDE.md", "docs/constitution_scoring_framework.md"],
        },
        "REVIEWER": {
            "name": "Reviewer",
            "responsibilities": "Code review, architecture review, security review",
            "forbidden_actions": ["approve without review", "skip security check", "ignore code quality"],
            "required_readings": ["docs/ownership_matrix.md", "docs/technical_debt.md"],
        },
        "SECURITY": {
            "name": "Security",
            "responsibilities": "Security audit, vulnerability scanning, threat modeling",
            "forbidden_actions": ["disable security control", "introduce cve", "bypass authentication"],
            "required_readings": ["SECURITY.md", "docs/threat_model.md"],
        },
        "PERFORMANCE": {
            "name": "Performance",
            "responsibilities": "Performance profiling, optimization, benchmarking",
            "forbidden_actions": ["introduce n+1 query", "bypass benchmark", "degrade latency"],
            "required_readings": ["docs/api_reference.md", "docs/benchmarks/"],
        },
        "DATABASE": {
            "name": "Database",
            "responsibilities": "Schema design, query optimization, migration planning",
            "forbidden_actions": ["add migration without rollback", "drop column without backup", "bypass migration review"],
            "required_readings": ["docs/db_migration.md", "docs/deployment/disaster_recovery_plan.md"],
        },
        "DEVOPS": {
            "name": "DevOps",
            "responsibilities": "CI/CD, containerization, infrastructure as code",
            "forbidden_actions": ["skip ci pipeline", "break build", "modify deployment without rollback"],
            "required_readings": ["Dockerfile", "docker-compose.yml", "bitbucket-pipelines.yml"],
        },
        "SRE": {
            "name": "SRE",
            "responsibilities": "Monitoring, alerting, incident response, chaos engineering",
            "forbidden_actions": ["remove health check", "silence alert without review", "disable monitoring"],
            "required_readings": ["docs/runbooks/", "docs/deployment/disaster_recovery_plan.md"],
        },
        "QA": {
            "name": "QA",
            "responsibilities": "Test strategy, test generation, quality gates",
            "forbidden_actions": ["delete test", "skip regression test", "bypass quality gate"],
            "required_readings": ["pytest.ini", "tests/", "docs/constitution_scoring_framework.md"],
        },
        "TECHNICAL_WRITER": {
            "name": "Technical Writer",
            "responsibilities": "Documentation, runbooks, ADRs, knowledge base",
            "forbidden_actions": ["remove documentation", "leave stale docs", "skip adr for architecture change"],
            "required_readings": ["docs/", "docs/adr/", "docs/runbooks/"],
        },
        "BUSINESS_ANALYST": {
            "name": "Business Analyst",
            "responsibilities": "Requirements gathering, stakeholder communication",
            "forbidden_actions": ["change requirements without approval", "ignore business value", "misrepresent data"],
            "required_readings": ["README.md", "USER_GUIDE.md"],
        },
        "PRODUCT_OWNER": {
            "name": "Product Owner",
            "responsibilities": "Prioritization, roadmap, backlog management",
            "forbidden_actions": ["change roadmap without stakeholder approval", "deprioritize security"],
            "required_readings": ["CHANGELOG.md", "RELEASE_NOTES.md", "ROADMAP.md"],
        },
        "CLOUD": {
            "name": "Cloud",
            "responsibilities": "Cloud architecture, cost optimization, migration",
            "forbidden_actions": ["expose credentials", "provision without cost estimate", "skip security group review"],
            "required_readings": ["Dockerfile", "docker-compose.yml"],
        },
        "PLATFORM": {
            "name": "Platform",
            "responsibilities": "IDP, Golden Paths, service catalog, self-service",
            "forbidden_actions": ["skip golden path", "bypass service registration", "ignore platform standards"],
            "required_readings": ["core/service_catalog.py", "docs/architecture.md"],
        },
        "FINOPS": {
            "name": "FinOps",
            "responsibilities": "Cost tracking, budgeting, optimization recommendations",
            "forbidden_actions": ["exceed budget without approval", "skip cost impact analysis"],
            "required_readings": ["core/ai_token_cost_tracker.py"],
        },
        "GOVERNANCE": {
            "name": "Governance",
            "responsibilities": "Constitution compliance, policy enforcement, audit",
            "forbidden_actions": ["modify constitution without review", "skip audit", "bypass governance gate"],
            "required_readings": ["core/constitution/", "core/constitution_ai_gate.py", "docs/constitution_scoring_framework.md"],
        },
        "EXECUTIVE_ADVISOR": {
            "name": "Executive Advisor",
            "responsibilities": "Strategic recommendations, business value analysis",
            "forbidden_actions": ["make false claims", "misrepresent metrics", "give advice without data"],
            "required_readings": ["core/presentation_generator.py", "docs/api_reference.md"],
        },
    }

    # ── v4.0: 12 Enterprise Layers ───────────────────────────────────────
    ENTERPRISE_LAYERS: dict[str, str] = {
        "LAYER_BUSINESS": "Business Layer — business logic, domain models, workflows",
        "LAYER_PLATFORM": "Platform Engineering Layer — IDP, Golden Paths, self-service",
        "LAYER_ARCHITECTURE": "Enterprise Architecture Layer — patterns, decisions, standards",
        "LAYER_AI": "AI Intelligence Layer — ML models, signal processing, decisions",
        "LAYER_KNOWLEDGE_GRAPH": "Knowledge Graph & Digital Twin Layer — repo intelligence, KG",
        "LAYER_AUTONOMOUS": "Autonomous Engineering Layer — self-healing, auto-optimization",
        "LAYER_SECURITY": "Security, Governance & Compliance Layer — Zero Trust, RBAC",
        "LAYER_SRE": "Reliability, Observability & SRE Layer — logging, tracing, metrics",
        "LAYER_DOCUMENTATION": "Documentation & Knowledge Management Layer — living docs, ADRs",
        "LAYER_EXECUTIVE": "Executive Intelligence Layer — presentations, reports, KPIs",
        "LAYER_LEARNING": "Continuous Learning Layer — incident learning, postmortems",
        "LAYER_EVOLUTION": "Enterprise Evolution Layer — capability maturity, roadmap",
    }

    REQUIRED_READINGS = [
        "CLAUDE.md",
        "docs/constitution_scoring_framework.md",
        "docs/technical_debt.md",
        "docs/ownership_matrix.md",
        "docs/MASTER_ENGINEERING_CONSTITUTION_v4.0.md",
    ]

    def __init__(self, identity: str = "unknown") -> None:
        self._identity = identity
        self._lock = threading.RLock()
        self._audit_log: list[AIGateEvent] = []
        self._gate_open = True
        self._active_role: str | None = None

    @property
    def identity(self) -> str:
        return self._identity

    @identity.setter
    def identity(self, value: str) -> None:
        self._identity = value

    # ── v4.0: Role Management ──────────────────────────────────────────────

    def set_role(self, role_key: str) -> bool:
        """Set the current AI specialist role.

        Args:
            role_key: Role key (e.g., "DEVELOPER", "SRE", "SECURITY").

        Returns:
            True if role was set, False if unknown.
        """
        if role_key.upper() in self.AI_SPECIALIST_ROLES:
            self._active_role = role_key.upper()
            self._audit("role_set", "INFO", AIGateResult(
                passed=True,
                reason=f"Role set to {self.AI_SPECIALIST_ROLES[role_key.upper()]['name']}",
                identity=self._identity,
            ))
            return True
        return False

    def get_role_info(self, role_key: str | None = None) -> dict[str, Any] | None:
        """Get information about an AI specialist role.

        Args:
            role_key: Role key (defaults to current active role).

        Returns:
            Dict with role info or None if not found.
        """
        key = (role_key or self._active_role or "").upper()
        role = self.AI_SPECIALIST_ROLES.get(key)
        if role:
            return {
                "key": key,
                "name": role["name"],
                "responsibilities": role["responsibilities"],
                "forbidden_actions": role["forbidden_actions"],
                "required_readings": role["required_readings"],
            }
        return None

    def validate(
        self,
        constitution_acknowledged: bool = False,
        claude_read: bool = False,
        architecture_reviewed: bool = False,
        audit_history_reviewed: bool = False,
        risk_controls_verified: bool = False,
        changed_files: list[str] | None = None,
        score_changes: dict[str, float] | None = None,
        has_evidence: bool = False,
        affected_layers: list[str] | None = None,
        role_specific_readings_completed: list[str] | None = None,
    ) -> AIGateResult:
        """Run the full AI governance gate validation (v4.0).

        Args:
            constitution_acknowledged: AI has read and acknowledged the Constitution
            claude_read: AI has read CLAUDE.md for project context
            architecture_reviewed: AI has reviewed architecture documents
            audit_history_reviewed: AI has reviewed audit history
            risk_controls_verified: AI has verified risk controls are intact
            changed_files: List of files the AI intends to modify
            score_changes: Dict of {category_id: new_score} if scores are affected
            has_evidence: Whether evidence exists for score changes
            affected_layers: List of affected enterprise layer keys (LAYER_*)
            role_specific_readings_completed: List of role-specific readings completed

        Returns:
            AIGateResult with passed/failed status and details.

        """
        failures: list[str] = []

        # ── Step 1: Constitution acknowledgment ──────────────────────────
        if not constitution_acknowledged:
            failures.append(
                "Constitution not acknowledged. AI MUST acknowledge: "
                + self.CONSTITUTION_ACKNOWLEDGMENT,
            )

        # ── Step 2: Context gathering ────────────────────────────────────
        context_checks = [
            ("CLAUDE.md", claude_read, "Project context (CLAUDE.md) not read"),
            ("architecture", architecture_reviewed, "Architecture documents not reviewed"),
            ("audit_history", audit_history_reviewed, "Audit history not reviewed"),
            ("risk_controls", risk_controls_verified, "Risk controls not verified"),
        ]
        for name, passed, msg in context_checks:
            if not passed:
                failures.append(f"Context missing: {msg}")

        # ── Step 3: Role-specific checks ─────────────────────────────────
        if self._active_role:
            role_info = self.AI_SPECIALIST_ROLES.get(self._active_role)
            if role_info:
                # Check role-specific readings
                if role_specific_readings_completed:
                    for required in role_info["required_readings"]:
                        completed = any(
                            required.lower() in r.lower()
                            for r in role_specific_readings_completed
                        )
                        if not completed:
                            failures.append(
                                f"Role '{role_info['name']}': missing required reading '{required}'",
                            )

        # ── Step 4: Enterprise layer awareness ───────────────────────────
        if affected_layers:
            for layer_key in affected_layers:
                if layer_key not in self.ENTERPRISE_LAYERS:
                    failures.append(
                        f"Unknown enterprise layer: {layer_key}. Valid layers: {', '.join(self.ENTERPRISE_LAYERS.keys())}",
                    )

        # ── Step 5: Check for forbidden file modifications ───────────────
        if changed_files:
            for f in changed_files:
                for forbidden in FORBIDDEN_FILE_TARGETS:
                    if forbidden in f:
                        failures.append(
                            f"Forbidden file modification: {f} requires explicit human approval",
                        )
                # Check for risk-control keyword modifications
                file_path = Path(f)
                if file_path.suffix == ".py" and file_path.exists():
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    for kw in RISK_CONTROL_KEYWORDS:
                        if kw in content:
                            failures.append(
                                f"Risk control '{kw}' present in {f} - verify risk control is not being modified",
                            )
                    # Check for broker SDK calls
                    for sdk in BROKER_SDK_PATTERNS:
                        if sdk in content:
                            failures.append(
                                f"Direct broker SDK call '{sdk}' detected in {f} - must use broker_adapters.py",
                            )
                    # Check for datetime.now() bypass
                    for bp in BYPASS_PATTERNS:
                        if bp in content:
                            failures.append(
                                f"Bypass pattern '{bp}' found in {f} - use core.datetime_ist.now_ist() instead",
                            )

        # ── Step 6: Score evidence check ─────────────────────────────────
        if score_changes:
            for category, new_score in score_changes.items():
                if new_score > 9.0 and not has_evidence:
                    failures.append(
                        f"Score {category}={new_score:.1f} exceeds 9.0 but no evidence provided. "
                        "Evidence is required for scores above 9.0.",
                    )
                if new_score > 8.0 and not has_evidence:
                    failures.append(
                        f"Score {category}={new_score:.1f} exceeds 8.0 without evidence. "
                        "Without evidence, score is capped at 8.0.",
                    )

        # ── Final result ─────────────────────────────────────────────────
        if failures:
            result = AIGateResult(
                passed=False,
                reason="AI Governance Gate: BLOCKED",
                detail=f"{len(failures)} validation failure(s) found",
                failures=failures,
                identity=self._identity,
            )
        else:
            result = AIGateResult(
                passed=True,
                reason="AI Governance Gate: PASSED",
                detail="All AI governance checks passed",
                identity=self._identity,
            )

        self._audit("validate", "PASS" if result.passed else "BLOCK", result)
        return result

    def acknowledge_constitution(self) -> dict[str, Any]:
        """Record that the AI has acknowledged the Constitution.

        Returns acknowledgment record.
        """
        ack = {
            "identity": self._identity,
            "acknowledgment": self.CONSTITUTION_ACKNOWLEDGMENT,
            "timestamp": time.time(),
            "version": "4.1.0",
            "active_role": self._active_role,
        }
        self._audit("acknowledge", "ACK", AIGateResult(
            passed=True, reason="Constitution acknowledged",
            detail=self.CONSTITUTION_ACKNOWLEDGMENT,
            identity=self._identity,
        ))
        return ack

    def check_forbidden_action(self, action_description: str) -> AIGateResult:
        """Check if an action is forbidden by the Constitution, including role-specific checks.

        Args:
            action_description: Description of the intended action

        Returns:
            AIGateResult indicating whether the action is allowed.

        """
        # Global forbidden keywords
        forbidden_keywords = [
            "bypass risk",
            "disable hard halt",
            "remove safety",
            "delete test",
            "skip documentation",
            "commit without tests",
            "modify ai governance",
            "violate constitution",
            "skip compliance",
            "ignore security",
        ]

        lower = action_description.lower()
        for kw in forbidden_keywords:
            if kw in lower:
                return AIGateResult(
                    passed=False,
                    reason=f"Forbidden action detected: '{kw}'",
                    detail="This action violates AI Governance rules",
                    failures=[f"Forbidden keyword: {kw}"],
                    identity=self._identity,
                )

        # Role-specific forbidden actions
        if self._active_role:
            role_info = self.AI_SPECIALIST_ROLES.get(self._active_role)
            if role_info:
                for forbidden in role_info["forbidden_actions"]:
                    if forbidden.lower() in lower:
                        return AIGateResult(
                            passed=False,
                            reason=f"Role '{role_info['name']}' forbidden action: '{forbidden}'",
                            detail="This action violates role-specific governance rules",
                            failures=[f"Role-specific forbidden: {forbidden}"],
                            identity=self._identity,
                        )

        return AIGateResult(
            passed=True,
            reason="Action allowed",
            identity=self._identity,
        )

    def validate_layer_compliance(
        self,
        affected_layers: list[str],
    ) -> AIGateResult:
        """Validate that actions are compliant with the affected enterprise layers.

        Args:
            affected_layers: List of affected layer keys.

        Returns:
            AIGateResult indicating layer compliance.
        """
        invalid_layers = [
            layer for layer in affected_layers if layer not in self.ENTERPRISE_LAYERS
        ]
        if invalid_layers:
            return AIGateResult(
                passed=False,
                reason="Layer compliance: BLOCKED",
                detail=f"Invalid enterprise layers: {', '.join(invalid_layers)}",
                failures=[f"Unknown layer: {layer}" for layer in invalid_layers],
                identity=self._identity,
            )

        return AIGateResult(
            passed=True,
            reason="Layer compliance: PASSED",
            detail=f"All {len(affected_layers)} affected layers are valid",
            identity=self._identity,
        )

    # ── Audit ────────────────────────────────────────────────────────────

    def _audit(self, action: str, result: str, detail: AIGateResult) -> None:
        with self._lock:
            self._audit_log.append(AIGateEvent(
                ts=time.time(),
                action=action,
                identity=self._identity,
                result=result,
                detail=f"{detail.reason}: {detail.detail}",
            ))

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "ts": e.ts,
                    "action": e.action,
                    "identity": e.identity,
                    "result": e.result,
                    "detail": e.detail,
                }
                for e in self._audit_log[-limit:]
            ]


# ── Module-level singleton ────────────────────────────────────────────────────

_GATE: AIGovernanceGate | None = None
_GATE_LOCK = threading.RLock()


def get_gate(identity: str = "ai_agent") -> AIGovernanceGate:
    """Get or create the singleton AI governance gate."""
    global _GATE
    if _GATE is None:
        with _GATE_LOCK:
            if _GATE is None:
                _GATE = AIGovernanceGate(identity=identity)
    return _GATE


def validate_ai_action(
    constitution_acknowledged: bool = False,
    claude_read: bool = False,
    changed_files: list[str] | None = None,
) -> AIGateResult:
    """Quick validation helper for AI agents."""
    gate = get_gate()
    return gate.validate(
        constitution_acknowledged=constitution_acknowledged,
        claude_read=claude_read,
        architecture_reviewed=True,
        audit_history_reviewed=True,
        risk_controls_verified=True,
        changed_files=changed_files,
    )


__all__ = [
    "BROKER_SDK_PATTERNS",
    "BYPASS_PATTERNS",
    "FORBIDDEN_FILE_TARGETS",
    "RISK_CONTROL_KEYWORDS",
    "AIGateEvent",
    "AIGateResult",
    "AIGovernanceGate",
    "get_gate",
    "log",
    "validate_ai_action",
]

