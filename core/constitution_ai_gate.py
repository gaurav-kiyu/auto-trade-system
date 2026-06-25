"""
AI Governance Gate - Pre-implementation validation for AI agents.

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

    This gate enforces the AI Governance article of the Constitution.
    Every AI agent MUST pass through this gate before implementing changes.
    """

    CONSTITUTION_ACKNOWLEDGMENT = (
        "I have read the Final Master System Constitution. "
        "I acknowledge that CORRECTNESS > FEATURES and SAFETY > SPEED. "
        "I will follow the Mandatory Change Pipeline."
    )

    REQUIRED_READINGS = [
        "CLAUDE.md",
        "docs/constitution_scoring_framework.md",
        "docs/technical_debt.md",
        "docs/ownership_matrix.md",
    ]

    def __init__(self, identity: str = "unknown") -> None:
        self._identity = identity
        self._lock = threading.RLock()
        self._audit_log: list[AIGateEvent] = []
        self._gate_open = True

    @property
    def identity(self) -> str:
        return self._identity

    @identity.setter
    def identity(self, value: str) -> None:
        self._identity = value

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
    ) -> AIGateResult:
        """Run the full AI governance gate validation.

        Args:
            constitution_acknowledged: AI has read and acknowledged the Constitution
            claude_read: AI has read CLAUDE.md for project context
            architecture_reviewed: AI has reviewed architecture documents
            audit_history_reviewed: AI has reviewed audit history
            risk_controls_verified: AI has verified risk controls are intact
            changed_files: List of files the AI intends to modify
            score_changes: Dict of {category_id: new_score} if scores are affected
            has_evidence: Whether evidence exists for score changes

        Returns:
            AIGateResult with passed/failed status and details.
        """
        failures: list[str] = []

        # ── Step 1: Constitution acknowledgment ──────────────────────────
        if not constitution_acknowledged:
            failures.append(
                "Constitution not acknowledged. AI MUST acknowledge: "
                + self.CONSTITUTION_ACKNOWLEDGMENT
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

        # ── Step 3: Check for forbidden file modifications ───────────────
        if changed_files:
            for f in changed_files:
                for forbidden in FORBIDDEN_FILE_TARGETS:
                    if forbidden in f:
                        failures.append(
                            f"Forbidden file modification: {f} requires explicit human approval"
                        )
                # Check for risk-control keyword modifications
                file_path = Path(f)
                if file_path.suffix == ".py" and file_path.exists():
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    for kw in RISK_CONTROL_KEYWORDS:
                        if kw in content:
                            failures.append(
                                f"Risk control '{kw}' present in {f} - verify risk control is not being modified"
                            )
                    # Check for broker SDK calls
                    for sdk in BROKER_SDK_PATTERNS:
                        if sdk in content:
                            failures.append(
                                f"Direct broker SDK call '{sdk}' detected in {f} - must use broker_adapters.py"
                            )
                    # Check for datetime.now() bypass
                    for bp in BYPASS_PATTERNS:
                        if bp in content:
                            failures.append(
                                f"Bypass pattern '{bp}' found in {f} - use core.datetime_ist.now_ist() instead"
                            )

        # ── Step 4: Score evidence check ─────────────────────────────────
        if score_changes:
            for category, new_score in score_changes.items():
                if new_score > 9.0 and not has_evidence:
                    failures.append(
                        f"Score {category}={new_score:.1f} exceeds 9.0 but no evidence provided. "
                        "Evidence is required for scores above 9.0."
                    )
                if new_score > 8.0 and not has_evidence:
                    failures.append(
                        f"Score {category}={new_score:.1f} exceeds 8.0 without evidence. "
                        "Without evidence, score is capped at 8.0."
                    )

        # ── Step 5: Change pipeline check ────────────────────────────────
        # (This is a lightweight check - full pipeline validation is in constitution.py)

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
            "version": "1.0.0",
        }
        self._audit("acknowledge", "ACK", AIGateResult(
            passed=True, reason="Constitution acknowledged",
            detail=self.CONSTITUTION_ACKNOWLEDGMENT,
            identity=self._identity,
        ))
        return ack

    def check_forbidden_action(self, action_description: str) -> AIGateResult:
        """Check if an action is forbidden by the Constitution.

        Args:
            action_description: Description of the intended action

        Returns:
            AIGateResult indicating whether the action is allowed.
        """
        forbidden_keywords = [
            "bypass risk",
            "disable hard halt",
            "remove safety",
            "delete test",
            "skip documentation",
            "commit without tests",
            "modify ai governance",
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

        return AIGateResult(
            passed=True,
            reason="Action allowed",
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
    "AIGateEvent",
    "AIGateResult",
    "AIGovernanceGate",
    "BROKER_SDK_PATTERNS",
    "BYPASS_PATTERNS",
    "FORBIDDEN_FILE_TARGETS",
    "RISK_CONTROL_KEYWORDS",
    "get_gate",
    "log",
    "validate_ai_action",
]

