"""Strategy Approval Workflow — Formal governance for strategy lifecycle transitions.

Implements Master Prompt Phase 13 (Strategy Governance) requirements:
- Formal approval workflow for state transitions
- DONT_RUN → PAPER_ONLY → LIVE_APPROVED → DEPRECATED lifecycle
- Multi-signer approval for LIVE promotion
- Evidence-based certification before promotion
- Full audit trail for all state changes

Usage:
    from core.strategy.approval_workflow import StrategyApprovalWorkflow

    workflow = StrategyApprovalWorkflow()
    workflow.request_transition("ma_crossover", "LIVE_APPROVED",
                                requested_by="quant_team",
                                evidence={"backtest_sharpe": 1.8, "paper_trades": 150})
    workflow.approve_transition("ma_crossover", "LIVE_APPROVED",
                                approved_by="risk_committee")

    report = workflow.get_governance_report()
    for s in report["pending_approvals"]:
        print(f"  {s['strategy']}: {s['from_state']} -> {s['to_state']}")
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)


class TransitionType(str, Enum):
    """Types of strategy state transitions with governance requirements.

    Higher levels require progressively more evidence and approvals.
    """

    INITIALIZE = "INITIALIZE"               # Strategy created
    PAPER_START = "PAPER_START"             # Start paper trading
    PROMOTE_TO_LIVE = "PROMOTE_TO_LIVE"     # Paper -> Live (requires approval)
    DEMOTE_TO_PAPER = "DEMOTE_TO_PAPER"     # Live -> Paper
    DEPRECATE = "DEPRECATE"                 # Mark as deprecated
    REACTIVATE = "REACTIVATE"               # Deprecated -> Paper
    BLOCK = "BLOCK"                         # DONT_RUN


class ApprovalStatus(str, Enum):
    """Status of an approval request."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass
class TransitionRequest:
    """A request to transition a strategy's governance state.

    Attributes:
        strategy_name: Name of the strategy.
        from_state: Current governance state.
        to_state: Desired governance state.
        requested_by: Person/team requesting the transition.
        evidence: Dict of evidence supporting the transition.
        status: Current approval status.
        requested_at: Timestamp of request.
        approved_by: Person/team who approved (if approved).
        approved_at: Timestamp of approval (if approved).
        rejection_reason: Reason for rejection (if rejected).
        approval_count: Number of partial approvals received (for multi-signer).
    """

    strategy_name: str
    from_state: str
    to_state: str
    requested_by: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: str = ""
    approved_by: str = ""
    approved_at: str = ""
    rejection_reason: str = ""
    approval_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "requested_by": self.requested_by,
            "evidence": self.evidence,
            "status": self.status.value,
            "requested_at": self.requested_at,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "rejection_reason": self.rejection_reason,
            "approval_count": self.approval_count,
        }


@dataclass
class ApprovalRule:
    """Rule defining approval requirements for a transition type.

    Attributes:
        transition_type: Type of transition.
        min_evidence: Minimum number of evidence items required.
        required_evidence_keys: Evidence keys that must be present.
        requires_approver: Whether a named approver is required.
        required_approval_count: Number of approvals needed.
        description: Human-readable description of the rule.
    """

    transition_type: str
    min_evidence: int = 0
    required_evidence_keys: list[str] = field(default_factory=list)
    requires_approver: bool = True
    required_approval_count: int = 1
    description: str = ""


# ── Default approval rules ──────────────────────────────────────────────────

DEFAULT_APPROVAL_RULES: dict[str, ApprovalRule] = {
    TransitionType.INITIALIZE.value: ApprovalRule(
        transition_type=TransitionType.INITIALIZE.value,
        min_evidence=0,
        requires_approver=False,
        description="Strategy initialization requires no approval",
    ),
    TransitionType.PAPER_START.value: ApprovalRule(
        transition_type=TransitionType.PAPER_START.value,
        min_evidence=1,
        required_evidence_keys=["config_validated"],
        description="Paper start requires config validation",
    ),
    TransitionType.PROMOTE_TO_LIVE.value: ApprovalRule(
        transition_type=TransitionType.PROMOTE_TO_LIVE.value,
        min_evidence=3,
        required_evidence_keys=[
            "backtest_sharpe", "paper_trades", "paper_win_rate",
        ],
        required_approval_count=2,  # Two-person rule
        description="LIVE promotion requires 3+ evidence items and 2 approvals",
    ),
    TransitionType.DEMOTE_TO_PAPER.value: ApprovalRule(
        transition_type=TransitionType.DEMOTE_TO_PAPER.value,
        min_evidence=1,
        required_evidence_keys=["reason_for_demotion"],
        description="Demotion requires documented reason",
    ),
    TransitionType.DEPRECATE.value: ApprovalRule(
        transition_type=TransitionType.DEPRECATE.value,
        min_evidence=1,
        required_evidence_keys=["deprecation_reason"],
        description="Deprecation requires documented reason",
    ),
    TransitionType.REACTIVATE.value: ApprovalRule(
        transition_type=TransitionType.REACTIVATE.value,
        min_evidence=2,
        required_evidence_keys=["updated_config", "retest_results"],
        description="Reactivation requires updated config and retest results",
    ),
    TransitionType.BLOCK.value: ApprovalRule(
        transition_type=TransitionType.BLOCK.value,
        min_evidence=1,
        required_evidence_keys=["block_reason"],
        description="Block requires documented reason",
    ),
}


class StrategyApprovalWorkflow:
    """Formal approval workflow for strategy lifecycle transitions.

    Governs all strategy state transitions with configurable approval rules,
    evidence requirements, and multi-signer approval for high-risk transitions.

    Thread-safe for concurrent access from multiple strategy orchestrators.
    """

    def __init__(
        self,
        rules: dict[str, ApprovalRule] | None = None,
    ) -> None:
        """Initialize the approval workflow.

        Args:
            rules: Custom approval rules (uses defaults if None).
        """
        self._rules = rules or DEFAULT_APPROVAL_RULES
        self._lock = threading.RLock()
        self._requests: list[TransitionRequest] = []
        self._max_requests = 1000
        self._approval_log: list[dict[str, Any]] = []

    # ── Request lifecycle ───────────────────────────────────────────────

    def request_transition(
        self,
        strategy_name: str,
        to_state: str,
        requested_by: str = "",
        evidence: dict[str, Any] | None = None,
    ) -> tuple[bool, str, str]:
        """Request a strategy state transition.

        Validates the request against approval rules and creates a pending
        approval request if validation passes.

        Args:
            strategy_name: Name of the strategy.
            to_state: Desired governance state.
            requested_by: Person/team requesting.
            evidence: Dict of evidence supporting the transition.

        Returns:
            (is_valid, message, request_id) tuple.
            request_id is empty string if validation fails.

        """
        ts = datetime.utcnow().isoformat()
        evidence = evidence or {}

        # Determine from_state based on existing requests
        from_state = self._get_current_state(strategy_name)

        # Validate transition is allowed
        valid, msg = self._validate_transition(from_state, to_state)
        if not valid:
            _log.warning("Transition rejected: %s -> %s for %s: %s",
                         from_state, to_state, strategy_name, msg)
            return False, msg, ""

        # Validate against approval rules
        transition_type = self._get_transition_type(from_state, to_state)
        rule = self._rules.get(transition_type, ApprovalRule(
            transition_type=transition_type,
            min_evidence=0,
            description="Default rule",
        ))

        valid, msg = self._validate_evidence(evidence, rule)
        if not valid:
            _log.warning("Evidence validation failed for %s: %s", strategy_name, msg)
            return False, msg, ""

        # Create request
        request_id = f"{strategy_name}:{to_state}:{ts}"
        with self._lock:
            request = TransitionRequest(
                strategy_name=strategy_name,
                from_state=from_state,
                to_state=to_state,
                requested_by=requested_by,
                evidence=evidence,
                status=ApprovalStatus.PENDING,
                requested_at=ts,
            )
            self._requests.append(request)
            if len(self._requests) > self._max_requests:
                self._requests.pop(0)

            self._log_approval_event("requested", request)
            _log.info("Transition requested: %s %s -> %s (requested_by=%s)",
                      strategy_name, from_state, to_state, requested_by)
            return True, f"Request created: {strategy_name} -> {to_state}", request_id

    def approve_transition(
        self,
        strategy_name: str,
        to_state: str,
        approved_by: str = "",
    ) -> tuple[bool, str]:
        """Approve a pending transition request.

        Args:
            strategy_name: Name of the strategy.
            to_state: Target state of the request.
            approved_by: Person/team approving.

        Returns:
            (is_approved, message) tuple.
        """
        with self._lock:
            # Find the most recent pending request
            for request in reversed(self._requests):
                if (request.strategy_name == strategy_name
                        and request.to_state == to_state
                        and request.status == ApprovalStatus.PENDING):
                    rule = self._rules.get(
                        self._get_transition_type(request.from_state, request.to_state),
                        ApprovalRule(transition_type="UNKNOWN"),
                    )

                    # Check if we have enough approvals (multi-signer)
                    if rule.required_approval_count > 1:
                        # Increment the approval count on this request
                        request.approval_count += 1
                        if request.approval_count < rule.required_approval_count:
                            # Need more approvals
                            remaining = rule.required_approval_count - request.approval_count
                            self._log_approval_event("partial_approval", request,
                                                     approver=approved_by,
                                                     remaining=remaining)
                            _log.info("Partial approval for %s -> %s (%d more needed)",
                                      strategy_name, to_state, remaining)
                            return True, f"Partial approval recorded (need {remaining} more)"

                    # Full approval
                    request.status = ApprovalStatus.APPROVED
                    request.approved_by = approved_by
                    request.approved_at = datetime.utcnow().isoformat()

                    self._log_approval_event("approved", request, approver=approved_by)
                    _log.info("Transition APPROVED: %s %s -> %s (approved_by=%s)",
                              strategy_name, request.from_state, to_state, approved_by)

                    return True, f"Approved: {strategy_name} -> {to_state}"

            return False, f"No pending request found for {strategy_name} -> {to_state}"

    def reject_transition(
        self,
        strategy_name: str,
        to_state: str,
        rejected_by: str = "",
        reason: str = "",
    ) -> tuple[bool, str]:
        """Reject a pending transition request.

        Args:
            strategy_name: Name of the strategy.
            to_state: Target state of the request.
            rejected_by: Person/team rejecting.
            reason: Reason for rejection.

        Returns:
            (is_rejected, message) tuple.
        """
        with self._lock:
            for request in reversed(self._requests):
                if (request.strategy_name == strategy_name
                        and request.to_state == to_state
                        and request.status == ApprovalStatus.PENDING):
                    request.status = ApprovalStatus.REJECTED
                    request.rejection_reason = reason

                    self._log_approval_event("rejected", request,
                                             approver=rejected_by, reason=reason)
                    _log.info("Transition REJECTED: %s -> %s (by=%s, reason=%s)",
                              strategy_name, to_state, rejected_by, reason)
                    return True, f"Rejected: {strategy_name} -> {to_state}"

            return False, f"No pending request found for {strategy_name} -> {to_state}"

    def expire_old_requests(self, max_age_hours: int = 24) -> int:
        """Expire pending requests older than max_age_hours.

        Args:
            max_age_hours: Maximum age for pending requests.

        Returns:
            Number of requests expired.
        """
        with self._lock:
            now = datetime.utcnow()
            expired = 0
            for request in self._requests:
                if request.status != ApprovalStatus.PENDING:
                    continue
                try:
                    req_time = datetime.fromisoformat(request.requested_at)
                    if (now - req_time).total_seconds() > max_age_hours * 3600:
                        request.status = ApprovalStatus.EXPIRED
                        expired += 1
                except (ValueError, TypeError):
                    continue
            if expired:
                _log.info("Expired %d old approval requests", expired)
            return expired

    # ── Queries ─────────────────────────────────────────────────────────

    def get_pending_approvals(self) -> list[dict[str, Any]]:
        """Get all pending approval requests.

        Returns:
            List of pending request dicts.
        """
        with self._lock:
            return [
                r.to_dict() for r in self._requests
                if r.status == ApprovalStatus.PENDING
            ]

    def get_request_history(self, strategy_name: str | None = None) -> list[dict[str, Any]]:
        """Get request history, optionally filtered by strategy.

        Args:
            strategy_name: Optional filter by strategy name.

        Returns:
            List of request dicts sorted by request time (newest first).
        """
        with self._lock:
            results = [
                r.to_dict() for r in reversed(self._requests)
                if strategy_name is None or r.strategy_name == strategy_name
            ]
            return results

    def get_approval_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get the approval audit log.

        Args:
            limit: Max log entries to return.

        Returns:
            List of log entry dicts.
        """
        with self._lock:
            return list(reversed(self._approval_log))[:limit]

    def get_governance_report(self) -> dict[str, Any]:
        """Get comprehensive governance report.

        Returns:
            Dict with governance status.
        """
        with self._lock:
            pending = [r for r in self._requests if r.status == ApprovalStatus.PENDING]
            approved = [r for r in self._requests if r.status == ApprovalStatus.APPROVED]
            rejected = [r for r in self._requests if r.status == ApprovalStatus.REJECTED]

            return {
                "total_requests": len(self._requests),
                "pending_count": len(pending),
                "approved_count": len(approved),
                "rejected_count": len(rejected),
                "pending_approvals": [r.to_dict() for r in pending],
                "strategies_approved_for_live": list(
                    dict.fromkeys(r.strategy_name for r in approved if r.to_state == "LIVE_APPROVED")
                ),
                "rules": {
                    k: {
                        "min_evidence": v.min_evidence,
                        "required_evidence_keys": v.required_evidence_keys,
                        "required_approval_count": v.required_approval_count,
                        "description": v.description,
                    }
                    for k, v in self._rules.items()
                },
            }

    # ── Configuration ──────────────────────────────────────────────────

    def get_approval_rules(self) -> dict[str, dict[str, Any]]:
        """Get current approval rules configuration.

        Returns:
            Dict of rule name -> rule details.
        """
        return {
            k: {
                "transition_type": v.transition_type,
                "min_evidence": v.min_evidence,
                "required_evidence_keys": v.required_evidence_keys,
                "requires_approver": v.requires_approver,
                "required_approval_count": v.required_approval_count,
                "description": v.description,
            }
            for k, v in self._rules.items()
        }

    # ── Internal helpers ───────────────────────────────────────────────

    def _get_current_state(self, strategy_name: str) -> str:
        """Get the current governance state of a strategy based on history.

        Iterates requests newest-first, returning the most recent APPROVED
        transition's target state. If no APPROVED transition exists, returns
        the from_state of the most recent request as the best guess.
        Returns "INITIALIZED" if no requests exist for this strategy.
        """
        with self._lock:
            last_from_state = "INITIALIZED"
            for request in reversed(self._requests):
                if request.strategy_name == strategy_name:
                    if request.status == ApprovalStatus.APPROVED:
                        return request.to_state
                    last_from_state = request.from_state
            return last_from_state

    def _get_transition_type(self, from_state: str, to_state: str) -> str:
        """Determine the transition type based on from/to states."""
        if to_state in ("DONT_RUN", "DEPRECATED"):
            return to_state
        if from_state == "INITIALIZED" and to_state == "PAPER_ONLY":
            return TransitionType.PAPER_START.value
        if to_state == "LIVE_APPROVED":
            return TransitionType.PROMOTE_TO_LIVE.value
        if from_state == "LIVE_APPROVED" and to_state == "PAPER_ONLY":
            return TransitionType.DEMOTE_TO_PAPER.value
        return TransitionType.INITIALIZE.value

    def _validate_transition(self, from_state: str, to_state: str) -> tuple[bool, str]:
        """Validate that a transition is logically allowed."""
        valid_transitions = {
            "INITIALIZED": ["PAPER_ONLY", "DONT_RUN", "DEPRECATED"],
            "PAPER_ONLY": ["LIVE_APPROVED", "DONT_RUN", "DEPRECATED"],
            "LIVE_APPROVED": ["PAPER_ONLY", "DONT_RUN", "DEPRECATED"],
            "DONT_RUN": ["PAPER_ONLY", "DEPRECATED"],
            "DEPRECATED": ["PAPER_ONLY"],
        }

        allowed = valid_transitions.get(from_state, [])
        if to_state not in allowed:
            return False, (
                f"Transition {from_state} -> {to_state} not allowed. "
                f"Allowed from {from_state}: {', '.join(allowed)}"
            )
        return True, ""

    def _validate_evidence(
        self,
        evidence: dict[str, Any],
        rule: ApprovalRule,
    ) -> tuple[bool, str]:
        """Validate evidence meets rule requirements."""
        if len(evidence) < rule.min_evidence:
            return False, (
                f"Need at least {rule.min_evidence} evidence items, "
                f"got {len(evidence)}"
            )

        for key in rule.required_evidence_keys:
            if key not in evidence:
                return False, f"Missing required evidence: {key}"

        return True, ""

    def _log_approval_event(
        self,
        event: str,
        request: TransitionRequest,
        approver: str = "",
        reason: str = "",
        **extra: Any,
    ) -> None:
        """Log an approval event to the audit log."""
        entry = {
            "event": event,
            "timestamp": datetime.utcnow().isoformat(),
            "strategy_name": request.strategy_name,
            "from_state": request.from_state,
            "to_state": request.to_state,
            "requested_by": request.requested_by,
            "approver": approver,
            "reason": reason,
            **extra,
        }
        self._approval_log.append(entry)


# ── Singleton ─────────────────────────────────────────────────────────────────

_workflow: StrategyApprovalWorkflow | None = None
_workflow_lock = threading.RLock()


def get_approval_workflow(rules: dict[str, ApprovalRule] | None = None) -> StrategyApprovalWorkflow:
    """Get singleton StrategyApprovalWorkflow instance.

    Args:
        rules: Custom approval rules (uses defaults if None for first init).

    Returns:
        Shared StrategyApprovalWorkflow instance.
    """
    global _workflow
    with _workflow_lock:
        if _workflow is None:
            _workflow = StrategyApprovalWorkflow(rules=rules)
        return _workflow


__all__ = [
    "ApprovalRule",
    "ApprovalStatus",
    "DEFAULT_APPROVAL_RULES",
    "StrategyApprovalWorkflow",
    "TransitionRequest",
    "TransitionType",
    "get_approval_workflow",
]
