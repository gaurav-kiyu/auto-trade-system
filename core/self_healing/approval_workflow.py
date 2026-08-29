"""Self-Healing Approval Workflow (Pillar 6 enhancement).

Adds an approval gate to the SelfHealingOrchestrator:
- Low-risk actions execute automatically (restart stale feed, clear cache)
- Medium-risk actions auto-execute with notification
- High-risk actions require operator approval before execution

Tracks pending approvals, provides approval/rejection API,
and escalates if approval is not received within a timeout.

Usage:
    from core.self_healing.approval_workflow import (
        HealingApprovalWorkflow,
        get_approval_workflow,
        ActionRiskLevel,
    )

    workflow = get_approval_workflow()

    # Request approval for a high-risk action
    ticket = workflow.request_approval(
        action_type="RECONNECT_BROKER",
        component="kite_adapter",
        reason="Broker connection lost in production",
        risk_level=ActionRiskLevel.HIGH,
    )

    # Operator approves
    workflow.approve(ticket.id, "operator@example.com")

    # Execute the approved action
    if ticket.is_approved:
        # ... execute healing action
        pass
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


class ActionRiskLevel(Enum):
    """Risk level for self-healing actions."""
    LOW = "LOW"          # Auto-execute, no notification
    MEDIUM = "MEDIUM"    # Auto-execute, notify operator
    HIGH = "HIGH"        # Require operator approval
    CRITICAL = "CRITICAL"  # Require operator approval + escalation


# Risk level mapping for self-healing recovery actions
ACTION_RISK_MAP: dict[str, ActionRiskLevel] = {
    "restart_stale_feed": ActionRiskLevel.LOW,
    "clear_hard_halt": ActionRiskLevel.LOW,
    "recycle_session": ActionRiskLevel.LOW,
    "disk_cleanup": ActionRiskLevel.LOW,
    "force_wal_checkpoint": ActionRiskLevel.LOW,
    "clear_stale_locks": ActionRiskLevel.LOW,
    "reload_config": ActionRiskLevel.MEDIUM,
    "reconnect_database": ActionRiskLevel.MEDIUM,
    "notify_operator": ActionRiskLevel.MEDIUM,
    "restart_watchdog": ActionRiskLevel.MEDIUM,
    "reset_circuit_breaker": ActionRiskLevel.HIGH,
    "reconnect_broker": ActionRiskLevel.HIGH,
    "run_runbook": ActionRiskLevel.HIGH,
}


@dataclass
class ApprovalTicket:
    """A pending approval request for a self-healing action."""

    id: str
    action_type: str
    component: str
    reason: str
    risk_level: str
    status: str = "PENDING"  # PENDING, APPROVED, REJECTED, EXPIRED, ESCALATED
    requested_at: float = field(default_factory=time.time)
    decided_at: float = 0.0
    approved_by: str = ""
    rejection_reason: str = ""
    notify_fn: Callable | None = None
    timeout_seconds: float = 300.0  # 5 min default

    @property
    def is_approved(self) -> bool:
        return self.status == "APPROVED"

    @property
    def is_expired(self) -> bool:
        return time.time() - self.requested_at > self.timeout_seconds

    @property
    def age_seconds(self) -> float:
        return time.time() - self.requested_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "component": self.component,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "status": self.status,
            "requested_at": self.requested_at,
            "requested_at_iso": datetime.fromtimestamp(self.requested_at).isoformat(),
            "age_seconds": round(self.age_seconds, 1),
            "decided_at": self.decided_at,
            "approved_by": self.approved_by,
            "rejection_reason": self.rejection_reason,
            "timeout_seconds": self.timeout_seconds,
            "is_expired": self.is_expired,
        }


@dataclass
class ApprovalWorkflowConfig:
    """Configuration for the approval workflow."""
    auto_approve_low_risk: bool = True
    auto_approve_medium_risk: bool = True
    require_approval_high_risk: bool = True
    approval_timeout_seconds: float = 300.0
    escalation_timeout_seconds: float = 600.0  # 10 min
    max_pending_tickets: int = 20
    persistence_path: str = "json/approval_tickets.json"


class HealingApprovalWorkflow:
    """Manages the approval workflow for self-healing actions.

    Thread-safe. Persists pending tickets to disk for operator review.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._cfg = config or {}
        self._lock = threading.RLock()
        self._pending: dict[str, ApprovalTicket] = {}
        self._history: list[dict[str, Any]] = []
        self._ticket_config: dict[str, Any] = {
            "auto_approve_low_risk": bool(self._cfg.get("auto_approve_low_risk", True)),
            "auto_approve_medium_risk": bool(self._cfg.get("auto_approve_medium_risk", True)),
            "require_approval_high_risk": bool(self._cfg.get("require_approval_high_risk", True)),
            "approval_timeout_seconds": float(self._cfg.get("approval_timeout_seconds", 300.0)),
            "escalation_timeout_seconds": float(self._cfg.get("escalation_timeout_seconds", 600.0)),
            "max_pending_tickets": int(self._cfg.get("max_pending_tickets", 20)),
            "persistence_path": str(self._cfg.get("persistence_path", "json/approval_tickets.json")),
        }
        self._escalation_callbacks: list[Callable] = []
        self._notify_fn: Callable | None = None
        self._approved_actions: set[str] = set()  # action_type:component that were approved

        # Load persisted tickets
        self._load_tickets()

        # Start background expiry checker
        self._stop_expiry = threading.Event()
        self._expiry_thread = threading.Thread(
            target=self._expiry_check_loop,
            daemon=True,
            name="approval-expiry-checker",
        )
        self._expiry_thread.start()

    def set_notify_fn(self, notify_fn: Callable | None) -> None:
        """Set a notification function (e.g., Telegram send)."""
        self._notify_fn = notify_fn

    def register_escalation_callback(self, callback: Callable) -> None:
        """Register a callback for escalated tickets (e.g., SMS/call)."""
        self._escalation_callbacks.append(callback)

    # ── Core API ─────────────────────────────────────────────────────────

    def request_approval(
        self,
        action_type: str,
        component: str,
        reason: str,
        risk_level: str | ActionRiskLevel | None = None,
        timeout_seconds: float | None = None,
    ) -> ApprovalTicket:
        """Request approval for a healing action.

        Args:
            action_type: The recovery action (e.g., 'reconnect_broker').
            component: The component being acted on.
            reason: Human-readable reason for the action.
            risk_level: Override risk level. Auto-detected if not provided.
            timeout_seconds: Override approval timeout.

        Returns:
            ApprovalTicket with current status.
                - If auto-approved: status = APPROVED
                - If pending: status = PENDING
        """
        if isinstance(risk_level, str):
            try:
                risk_level = ActionRiskLevel(risk_level)
            except ValueError:
                risk_level = None

        # Auto-detect risk level if not provided
        if risk_level is None:
            risk_level = ACTION_RISK_MAP.get(
                action_type, ActionRiskLevel.MEDIUM
            )

        with self._lock:
            # Check max pending
            pending_count = sum(1 for t in self._pending.values() if t.status == "PENDING")
            if pending_count >= self._ticket_config.get("max_pending_tickets", 20):
                _log.warning("[APPROVAL] Max pending tickets reached (%d)", pending_count)
                # Create auto-rejected ticket
                ticket = ApprovalTicket(
                    id=f"app_{uuid.uuid4().hex[:12]}",
                    action_type=action_type,
                    component=component,
                    reason=reason,
                    risk_level=risk_level.value if isinstance(risk_level, ActionRiskLevel) else risk_level,
                    status="REJECTED",
                    rejection_reason="Max pending tickets reached",
                )
                self._history.append(ticket.to_dict())
                return ticket

            # Determine if auto-approval applies
            auto_approve = False
            if risk_level == ActionRiskLevel.LOW and self._ticket_config.get("auto_approve_low_risk", True):
                auto_approve = True
            elif risk_level == ActionRiskLevel.MEDIUM and self._ticket_config.get("auto_approve_medium_risk", True):
                auto_approve = True
            elif risk_level == ActionRiskLevel.CRITICAL:
                auto_approve = False  # Critical always requires approval

            ticket_id = f"app_{uuid.uuid4().hex[:12]}"

            if auto_approve:
                ticket = ApprovalTicket(
                    id=ticket_id,
                    action_type=action_type,
                    component=component,
                    reason=reason,
                    risk_level=risk_level.value if isinstance(risk_level, ActionRiskLevel) else risk_level,
                    status="APPROVED",
                    approved_by="auto",
                    decided_at=time.time(),
                    timeout_seconds=timeout_seconds or self._ticket_config.get("approval_timeout_seconds", 300.0),
                )
                self._history.append(ticket.to_dict())
                _log.info("[APPROVAL] Auto-approved %s on %s: %s",
                         action_type, component, reason)
            else:
                ticket = ApprovalTicket(
                    id=ticket_id,
                    action_type=action_type,
                    component=component,
                    reason=reason,
                    risk_level=risk_level.value if isinstance(risk_level, ActionRiskLevel) else risk_level,
                    timeout_seconds=timeout_seconds or self._ticket_config.get("approval_timeout_seconds", 300.0),
                )
                self._pending[ticket_id] = ticket
                self._save_tickets()
                _log.warning("[APPROVAL] Approval needed: %s on %s (risk=%s): %s",
                            action_type, component, risk_level, reason)

                # Notify operator
                if self._notify_fn:
                    try:
                        self._notify_fn(
                            f"🔴 Approval Required: {action_type} on {component}\n"
                            f"Risk: {risk_level.value}\n"
                            f"Reason: {reason}\n"
                            f"ID: {ticket_id}"
                        )
                    except Exception as exc:
                        _log.warning("[APPROVAL] Notify failed: %s", exc)

            return ticket

    def approve(self, ticket_id: str, approved_by: str) -> bool:
        """Approve a pending approval ticket.

        Args:
            ticket_id: The ticket ID to approve.
            approved_by: Who approved it (username/email).

        Returns:
            True if approved, False if not found or already decided.
        """
        with self._lock:
            ticket = self._pending.get(ticket_id)
            if not ticket:
                _log.warning("[APPROVAL] Ticket not found: %s", ticket_id)
                return False
            if ticket.status != "PENDING":
                _log.warning("[APPROVAL] Ticket %s already %s", ticket_id, ticket.status)
                return False
            if ticket.is_expired:
                ticket.status = "EXPIRED"
                _log.warning("[APPROVAL] Ticket %s expired", ticket_id)
                return False

            ticket.status = "APPROVED"
            ticket.approved_by = approved_by
            ticket.decided_at = time.time()
            # Track approved actions for faster lookup
            action_key = f"{ticket.action_type}:{ticket.component}"
            self._approved_actions.add(action_key)
            self._history.append(ticket.to_dict())
            self._remove_ticket(ticket_id)
            _log.info("[APPROVAL] Approved by %s: %s on %s",
                     approved_by, ticket.action_type, ticket.component)

            if self._notify_fn:
                try:
                    self._notify_fn(
                        f"✅ Approval granted by {approved_by}: {ticket.action_type} on {ticket.component}"
                    )
                except Exception:
                    pass

            return True

    def reject(self, ticket_id: str, rejected_by: str, reason: str = "") -> bool:
        """Reject a pending approval ticket.

        Args:
            ticket_id: The ticket ID to reject.
            rejected_by: Who rejected it.
            reason: Reason for rejection.

        Returns:
            True if rejected, False if not found or already decided.
        """
        with self._lock:
            ticket = self._pending.get(ticket_id)
            if not ticket:
                return False
            if ticket.status != "PENDING":
                return False

            ticket.status = "REJECTED"
            ticket.rejection_reason = reason or "Rejected without reason"
            ticket.decided_at = time.time()
            ticket.approved_by = rejected_by
            self._history.append(ticket.to_dict())
            self._remove_ticket(ticket_id)
            _log.warning("[APPROVAL] Rejected by %s: %s on %s (reason: %s)",
                        rejected_by, ticket.action_type, ticket.component, reason)

            if self._notify_fn:
                try:
                    self._notify_fn(
                        f"❌ Rejected by {rejected_by}: {ticket.action_type} on {ticket.component}\nReason: {reason}"
                    )
                except Exception:
                    pass

            return True

    # ── Query API ────────────────────────────────────────────────────────

    def get_pending(self) -> list[dict[str, Any]]:
        """Get all pending approval tickets."""
        with self._lock:
            return [
                t.to_dict() for t in self._pending.values()
                if t.status == "PENDING"
            ]

    def get_ticket(self, ticket_id: str) -> dict[str, Any] | None:
        """Get a specific ticket by ID."""
        with self._lock:
            ticket = self._pending.get(ticket_id)
            if ticket:
                return ticket.to_dict()
            # Also check history
            for h in self._history:
                if h.get("id") == ticket_id:
                    return h
        return None

    def get_stats(self) -> dict[str, Any]:
        """Get approval workflow statistics."""
        with self._lock:
            n_pending = sum(1 for t in self._pending.values() if t.status == "PENDING")
            n_approved = sum(1 for h in self._history if h.get("status") == "APPROVED")
            n_rejected = sum(1 for h in self._history if h.get("status") == "REJECTED")
            n_expired = sum(1 for h in self._history if h.get("status") == "EXPIRED")
            n_auto = sum(1 for h in self._history if h.get("approved_by") == "auto")

            return {
                "pending": n_pending,
                "approved": n_approved,
                "auto_approved": n_auto,
                "rejected": n_rejected,
                "expired": n_expired,
                "total_history": len(self._history),
                "total_pending": len(self._pending),
            }

    def get_history(self, n: int = 50) -> list[dict[str, Any]]:
        """Get recent approval history."""
        with self._lock:
            return list(reversed(self._history))[:n]

    def clear_history(self) -> None:
        """Clear all history."""
        with self._lock:
            self._history.clear()

    # ── Integration with SelfHealingOrchestrator ────────────────────────

    def should_execute(self, action_type: str, component: str) -> tuple[bool, str]:
        """Check if an action should be executed based on approval status.

        Called by SelfHealingOrchestrator before executing an action.

        Args:
            action_type: The recovery action name.
            component: The component name.

        Returns:
            (should_execute: bool, message: str)
        """
        risk = ACTION_RISK_MAP.get(action_type, ActionRiskLevel.MEDIUM)

        # Low risk: always execute
        if risk == ActionRiskLevel.LOW:
            return True, "Auto-approved (low risk)"

        # Medium risk: execute, but log
        if risk == ActionRiskLevel.MEDIUM:
            return True, "Auto-approved (medium risk)"

        # High risk: check for approval ticket
        with self._lock:
            for ticket_id, ticket in self._pending.items():
                if ticket.action_type == action_type and ticket.component == component:
                    if ticket.is_approved:
                        return True, f"Approved by {ticket.approved_by}"
                    elif ticket.status == "REJECTED":
                        return False, f"Rejected: {ticket.rejection_reason}"
                    elif ticket.is_expired:
                        return False, "Approval ticket expired"
                    else:
                        return False, f"Awaiting approval (ticket: {ticket_id})"

        # Check if action was previously approved
        action_key = f"{action_type}:{component}"
        with self._lock:
            if action_key in self._approved_actions:
                return True, "Previously approved (cached)"

        # No ticket found — auto-create one
        ticket = self.request_approval(action_type, component,
                                       "Auto-requested during healing cycle",
                                       risk)
        if ticket.is_approved:
            return True, f"Auto-approved (risk level: {risk.value})"
        return False, f"Awaiting approval (ticket: {ticket.id})"

    # ── Internal ─────────────────────────────────────────────────────────

    def _remove_ticket(self, ticket_id: str) -> None:
        """Remove a ticket from pending storage."""
        self._pending.pop(ticket_id, None)
        self._save_tickets()

    def _expiry_check_loop(self) -> None:
        """Background thread that expires stale tickets."""
        while not self._stop_expiry.is_set():
            time.sleep(30)  # Check every 30 seconds
            try:
                self._check_expired()
            except Exception as exc:
                _log.debug("[APPROVAL] Expiry check error: %s", exc)

    def _check_expired(self) -> None:
        """Expire tickets that have timed out."""
        with self._lock:
            time.time()
            expired_ids = []
            for ticket_id, ticket in self._pending.items():
                if ticket.status == "PENDING" and ticket.is_expired:
                    ticket.status = "EXPIRED"
                    self._history.append(ticket.to_dict())
                    expired_ids.append(ticket_id)
                    _log.warning("[APPROVAL] Ticket %s expired (action=%s, component=%s)",
                                ticket_id, ticket.action_type, ticket.component)

                    # Escalate critical expired tickets
                    if ticket.risk_level == "CRITICAL":
                        self._escalate(ticket)

            for tid in expired_ids:
                self._pending.pop(tid, None)

            if expired_ids:
                self._save_tickets()

    def _escalate(self, ticket: ApprovalTicket) -> None:
        """Escalate a critical expired ticket."""
        escalation_msg = (
            f"🚨 ESCALATION: Critical approval ticket expired!\n"
            f"Action: {ticket.action_type} on {ticket.component}\n"
            f"Reason: {ticket.reason}\n"
            f"Ticket: {ticket.id}\n"
            f"Age: {ticket.age_seconds:.0f}s"
        )
        _log.critical("[APPROVAL] %s", escalation_msg)

        for cb in self._escalation_callbacks:
            try:
                cb(escalation_msg)
            except Exception as exc:
                _log.warning("[APPROVAL] Escalation callback failed: %s", exc)

        if self._notify_fn:
            try:
                self._notify_fn(escalation_msg)
            except Exception:
                pass

    def _load_tickets(self) -> None:
        """Load pending tickets from disk."""
        path = Path(self._ticket_config.get("persistence_path", "json/approval_tickets.json"))
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                for item in data:
                    ticket = ApprovalTicket(
                        id=item.get("id", ""),
                        action_type=item.get("action_type", ""),
                        component=item.get("component", ""),
                        reason=item.get("reason", ""),
                        risk_level=item.get("risk_level", "MEDIUM"),
                        status=item.get("status", "PENDING"),
                        requested_at=item.get("requested_at", 0.0),
                    )
                    self._pending[ticket.id] = ticket
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.debug("[APPROVAL] Load tickets failed: %s", exc)

    def _save_tickets(self) -> None:
        """Save pending tickets to disk."""
        path = Path(self._ticket_config.get("persistence_path", "json/approval_tickets.json"))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = [t.to_dict() for t in self._pending.values() if t.status == "PENDING"]
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError, TypeError) as exc:
            _log.debug("[APPROVAL] Save tickets failed: %s", exc)


# ── Singleton ────────────────────────────────────────────────────────────────


_workflow: HealingApprovalWorkflow | None = None
_workflow_lock = threading.RLock()


def get_approval_workflow() -> HealingApprovalWorkflow:
    """Get the singleton HealingApprovalWorkflow instance."""
    global _workflow
    with _workflow_lock:
        if _workflow is None:
            _workflow = HealingApprovalWorkflow()
        return _workflow


def reset_approval_workflow() -> None:
    """Force-reset singleton (for testing)."""
    global _workflow
    with _workflow_lock:
        _workflow = None


__all__ = [
    "ACTION_RISK_MAP",
    "ActionRiskLevel",
    "ApprovalTicket",
    "HealingApprovalWorkflow",
    "get_approval_workflow",
    "reset_approval_workflow",
]
