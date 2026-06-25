"""
Change Management & Approval Workflow (Phase 28).

Unified module for proposing, reviewing, approving/rejecting, applying, and
rolling back configuration changes across ALL domains:
  - Config (trading parameters, risk limits)
  - Strategy parameters (SL_PCT, TARGET_PCT, entry thresholds)
  - Adaptive behavior (auto-tuner mode, signal adjustments)
  - Feature flags (spread_strategy, equity_trading)
  - Infrastructure (broker config, rate limits)

This consolidates the fragmented approval logic previously scattered across:
  - core/adaptive_behavior_governance.py (param changes only)
  - core/config_audit_log.py (audit trail only)
  - core/config_bootstrap.py (diff detection only)

Lifecycle: PROPOSED → REVIEWING → APPROVED|REJECTED → APPLIED|ROLLED_BACK

Usage
-----
    from core.change_management import get_change_manager, ChangeProposal

    mgr = get_change_manager()
    # Propose a change
    prop = mgr.propose(
        change_type="CONFIG",
        target_key="SL_PCT",
        current_value=0.30,
        proposed_value=0.25,
        reason="Reduce stop-loss to match backtest optimum",
        proposed_by="Operator",
        risk_level="HIGH",
    )
    # Approve
    mgr.approve(prop.id_, approved_by="Admin")
    # Apply
    result = mgr.apply(prop.id_, applied_by="Admin")
    # Rollback if needed
    mgr.rollback(prop.id_, rolled_back_by="Admin")

Config keys (all optional)
--------------------------
    change_management_enabled   : bool   default True
    change_require_dry_run      : bool   default True
    change_max_pending          : int    default 25
    change_auto_expire_hours    : int    default 48
    change_audit_log_path       : str    default "logs/change_audit.jsonl"
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

_log = logging.getLogger(__name__)


# ── Enums ──────────────────────────────────────────────────────────────────────

class ChangeType(Enum):
    CONFIG = "CONFIG"
    STRATEGY_PARAM = "STRATEGY_PARAM"
    ADAPTIVE_BEHAVIOR = "ADAPTIVE_BEHAVIOR"
    FEATURE_FLAG = "FEATURE_FLAG"
    INFRASTRUCTURE = "INFRASTRUCTURE"


class ChangeStatus(Enum):
    PROPOSED = "PROPOSED"
    REVIEWING = "REVIEWING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    ROLLED_BACK = "ROLLED_BACK"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class ChangeRisk(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class ChangeProposal:
    """A proposed change to the system."""
    id_: str
    change_type: ChangeType
    target_key: str
    current_value: Any
    proposed_value: Any
    reason: str
    proposed_by: str
    risk_level: ChangeRisk = ChangeRisk.NORMAL
    status: ChangeStatus = ChangeStatus.PROPOSED
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    approved_by: str | None = None
    applied_by: str | None = None
    rolled_back_by: str | None = None
    rejection_reason: str | None = None
    failure_reason: str | None = None
    expiry_at: float | None = None
    audit_id: str | None = None
    dry_run_result: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id_": self.id_,
            "change_type": self.change_type.value,
            "target_key": self.target_key,
            "current_value": str(self.current_value),
            "proposed_value": str(self.proposed_value),
            "reason": self.reason,
            "proposed_by": self.proposed_by,
            "risk_level": self.risk_level.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "approved_by": self.approved_by,
            "applied_by": self.applied_by,
            "rolled_back_by": self.rolled_back_by,
            "rejection_reason": self.rejection_reason,
            "failure_reason": self.failure_reason,
            "expiry_at": self.expiry_at,
            "dry_run_result": self.dry_run_result,
            "metadata": self.metadata,
        }


@dataclass
class ChangeAuditEntry:
    """An audit trail entry for a change lifecycle event."""
    change_id: str
    action: str          # PROPOSED | APPROVED | REJECTED | APPLIED | ROLLED_BACK | EXPIRED | FAILED
    timestamp: float
    actor: str
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "action": self.action,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "details": self.details,
        }


# ── Change Manager ─────────────────────────────────────────────────────────────

class ChangeManager:
    """Central change management workflow engine.

    Handles the full lifecycle: propose → review → approve/reject → apply → rollback.
    Thread-safe. Supports expiry of stale proposals and dry-run mode.
    """

    def __init__(self, cfg: dict[str, Any] | None = None):
        self._cfg = cfg or {}
        self._enabled = bool(self._cfg.get("change_management_enabled", True))
        self._lock = threading.RLock()
        self._proposals: dict[str, ChangeProposal] = {}
        self._audit_log: list[ChangeAuditEntry] = []
        self._max_audit = 10000
        self._max_pending = int(self._cfg.get("change_max_pending", 25))
        self._auto_expire_hours = int(self._cfg.get("change_auto_expire_hours", 48))
        self._audit_log_path = str(self._cfg.get("change_audit_log_path", "logs/change_audit.jsonl"))
        self._apply_callbacks: dict[str, Callable] = {}

        # Init audit log directory
        Path(self._audit_log_path).parent.mkdir(parents=True, exist_ok=True)

        # Start auto-expiry cleanup thread
        self._stop_expiry = threading.Event()
        self._expiry_thread = threading.Thread(
            target=_expiry_loop, args=(self,), daemon=True, name="change-mgr-expiry"
        )
        if self._enabled:
            self._expiry_thread.start()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def propose(
        self,
        change_type: str | ChangeType,
        target_key: str,
        current_value: Any,
        proposed_value: Any,
        reason: str,
        proposed_by: str,
        risk_level: str | ChangeRisk = ChangeRisk.NORMAL,
        dry_run_result: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChangeProposal:
        """Submit a new change proposal for review.

        Args:
            change_type: CONFIG, STRATEGY_PARAM, ADAPTIVE_BEHAVIOR, FEATURE_FLAG, INFRASTRUCTURE
            target_key: The key being changed (e.g. "SL_PCT")
            current_value: Current value before change
            proposed_value: Proposed new value
            reason: Human-readable justification
            proposed_by: Who/what is proposing the change
            risk_level: CRITICAL, HIGH, or NORMAL
            dry_run_result: Optional result from a dry-run/simulation
            metadata: Additional context

        Returns:
            The created ChangeProposal with generated id_
        """
        if not self._enabled:
            _log.warning("[CM] Change management disabled - change auto-approved")
            return self._create_auto_approved(
                change_type, target_key, current_value, proposed_value,
                reason, proposed_by, risk_level, dry_run_result, metadata,
            )

        if isinstance(change_type, str):
            change_type = ChangeType(change_type)
        if isinstance(risk_level, str):
            risk_level = ChangeRisk(risk_level)

        with self._lock:
            # Check pending limit
            pending = sum(1 for p in self._proposals.values()
                          if p.status in (ChangeStatus.PROPOSED, ChangeStatus.REVIEWING))
            if pending >= self._max_pending:
                raise RuntimeError(
                    f"Max pending changes ({self._max_pending}) reached. "
                    "Approve/reject existing changes first."
                )

            # Check for existing pending change to same target
            for p in self._proposals.values():
                if (p.target_key == target_key
                        and p.status in (ChangeStatus.PROPOSED, ChangeStatus.REVIEWING, ChangeStatus.APPROVED)):
                    raise RuntimeError(
                        f"Existing pending/approved change for {target_key} "
                        f"(id={p.id_}). Resolve before proposing a new one."
                    )

            import uuid
            proposal = ChangeProposal(
                id_=f"chg_{uuid.uuid4().hex[:12]}",
                change_type=change_type,
                target_key=target_key,
                current_value=current_value,
                proposed_value=proposed_value,
                reason=reason,
                proposed_by=proposed_by,
                risk_level=risk_level,
                status=ChangeStatus.PROPOSED,
                expiry_at=time.time() + (self._auto_expire_hours * 3600),
                dry_run_result=dry_run_result,
                metadata=metadata or {},
            )
            self._proposals[proposal.id_] = proposal
            self._record_audit(proposal.id_, "PROPOSED", proposed_by, reason)
            _log.info("[CM] Proposed %s change: %s=%s -> %s (id=%s, risk=%s)",
                      change_type.value, target_key, current_value, proposed_value,
                      proposal.id_, risk_level.value)
            return proposal

    def propose_with_dry_run(
        self,
        change_type: str | ChangeType,
        target_key: str,
        current_value: Any,
        proposed_value: Any,
        reason: str,
        proposed_by: str,
        risk_level: str | ChangeRisk = ChangeRisk.NORMAL,
        dry_run_fn: Callable | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChangeProposal:
        """Propose a change with an optional dry-run simulation.

        If dry_run_fn is provided and the change_require_dry_run config is true,
        the dry-run must succeed for the proposal to be created.

        Args:
            dry_run_fn: Callable that takes (current_value, proposed_value)
                        and returns a dict with 'passed' bool and optional 'details'.

        Returns:
            The ChangeProposal (may be rejected if dry-run fails).
        """
        require_dry_run = bool(self._cfg.get("change_require_dry_run", True))

        dry_run_result = None
        if dry_run_fn is not None:
            try:
                dry_run_result = dry_run_fn(current_value, proposed_value)
            except Exception as exc:
                dry_run_result = {"passed": False, "error": str(exc)}

            if require_dry_run and dry_run_result and not dry_run_result.get("passed", False):
                # Create a rejected proposal with the dry-run failure
                import uuid
                proposal = ChangeProposal(
                    id_=f"chg_{uuid.uuid4().hex[:12]}",
                    change_type=ChangeType(change_type) if isinstance(change_type, str) else change_type,
                    target_key=target_key,
                    current_value=current_value,
                    proposed_value=proposed_value,
                    reason=reason,
                    proposed_by=proposed_by,
                    risk_level=ChangeRisk(risk_level) if isinstance(risk_level, str) else risk_level,
                    status=ChangeStatus.REJECTED,
                    rejection_reason=f"Dry-run failed: {dry_run_result.get('error', 'no details')}",
                    dry_run_result=dry_run_result,
                )
                _log.warning("[CM] Proposal rejected at dry-run: %s=%s (reason: %s)",
                            target_key, proposed_value, proposal.rejection_reason)
                return proposal

        return self.propose(
            change_type=change_type,
            target_key=target_key,
            current_value=current_value,
            proposed_value=proposed_value,
            reason=reason,
            proposed_by=proposed_by,
            risk_level=risk_level,
            dry_run_result=dry_run_result,
            metadata=metadata,
        )

    def approve(self, change_id: str, approved_by: str) -> bool:
        """Approve a pending change proposal.

        Only PROPOSED and REVIEWING status changes can be approved.

        Returns:
            True if approved, False if invalid state or not found.
        """
        with self._lock:
            proposal = self._proposals.get(change_id)
            if not proposal:
                _log.warning("[CM] Approve failed: unknown change %s", change_id)
                return False
            if proposal.status not in (ChangeStatus.PROPOSED, ChangeStatus.REVIEWING):
                _log.warning("[CM] Approve failed: %s is in %s state (need PROPOSED/REVIEWING)",
                            change_id, proposal.status.value)
                return False

            proposal.status = ChangeStatus.APPROVED
            proposal.approved_by = approved_by
            proposal.updated_at = time.time()
            self._record_audit(change_id, "APPROVED", approved_by,
                              f"Approved by {approved_by}")
            _log.info("[CM] Approved %s: %s=%s (by %s)",
                     proposal.change_type.value, proposal.target_key,
                     proposal.proposed_value, approved_by)
            return True

    def reject(self, change_id: str, rejected_by: str, reason: str = "") -> bool:
        """Reject a pending change proposal.

        Returns:
            True if rejected, False if not found or already final.
        """
        with self._lock:
            proposal = self._proposals.get(change_id)
            if not proposal:
                return False
            if proposal.status not in (ChangeStatus.PROPOSED, ChangeStatus.REVIEWING):
                return False

            proposal.status = ChangeStatus.REJECTED
            proposal.rejection_reason = reason or "Rejected without reason"
            proposal.updated_at = time.time()
            self._record_audit(change_id, "REJECTED", rejected_by, reason)
            _log.info("[CM] Rejected %s: %s=%s (by %s: %s)",
                     proposal.change_type.value, proposal.target_key,
                     proposal.proposed_value, rejected_by, reason)
            return True

    def apply(self, change_id: str, applied_by: str,
              apply_fn: Callable | None = None) -> bool:
        """Apply an approved change.

        If apply_fn is provided, it's called with (proposal) and must return
        True on success. If apply_fn is None, the change is marked APPLIED
        without executing any callback (caller handles actual application).

        Returns:
            True if applied successfully.
        """
        with self._lock:
            proposal = self._proposals.get(change_id)
            if not proposal:
                _log.warning("[CM] Apply failed: unknown change %s", change_id)
                return False
            if proposal.status != ChangeStatus.APPROVED:
                _log.warning("[CM] Apply failed: %s is in %s state (need APPROVED)",
                            change_id, proposal.status.value)
                return False

            if apply_fn is not None:
                try:
                    result = apply_fn(proposal)
                    if not result:
                        proposal.status = ChangeStatus.FAILED
                        proposal.failure_reason = "Apply function returned False"
                        proposal.updated_at = time.time()
                        self._record_audit(change_id, "FAILED", applied_by,
                                          "Apply function returned False")
                        return False
                except Exception as exc:
                    proposal.status = ChangeStatus.FAILED
                    proposal.failure_reason = str(exc)
                    proposal.updated_at = time.time()
                    self._record_audit(change_id, "FAILED", applied_by, str(exc))
                    _log.error("[CM] Apply failed for %s: %s", change_id, exc)
                    return False

            proposal.status = ChangeStatus.APPLIED
            proposal.applied_by = applied_by
            proposal.updated_at = time.time()
            self._record_audit(change_id, "APPLIED", applied_by,
                              f"Applied by {applied_by}")
            _log.info("[CM] Applied %s: %s=%s -> %s (by %s)",
                     proposal.change_type.value, proposal.target_key,
                     proposal.current_value, proposal.proposed_value, applied_by)
            return True

    def rollback(self, change_id: str, rolled_back_by: str,
                 rollback_fn: Callable | None = None) -> bool:
        """Rollback an applied change to its previous value.

        Only APPLIED status changes can be rolled back.

        Returns:
            True if rolled back.
        """
        with self._lock:
            proposal = self._proposals.get(change_id)
            if not proposal:
                return False
            if proposal.status != ChangeStatus.APPLIED:
                _log.warning("[CM] Rollback failed: %s is in %s state (need APPLIED)",
                            change_id, proposal.status.value)
                return False

            if rollback_fn is not None:
                try:
                    result = rollback_fn(proposal)
                    if not result:
                        _log.warning("[CM] Rollback function failed for %s", change_id)
                        return False
                except Exception as exc:
                    _log.error("[CM] Rollback error for %s: %s", change_id, exc)
                    return False

            proposal.status = ChangeStatus.ROLLED_BACK
            proposal.rolled_back_by = rolled_back_by
            proposal.updated_at = time.time()
            self._record_audit(change_id, "ROLLED_BACK", rolled_back_by,
                              f"Rolled back by {rolled_back_by}")
            _log.warning("[CM] Rolled back %s: %s=%s (by %s)",
                        proposal.change_type.value, proposal.target_key,
                        proposal.current_value, rolled_back_by)
            return True

    def get_proposal(self, change_id: str) -> ChangeProposal | None:
        """Get a proposal by ID."""
        with self._lock:
            return self._proposals.get(change_id)

    def list_pending(self) -> list[ChangeProposal]:
        """List all pending (PROPOSED or REVIEWING) proposals."""
        with self._lock:
            return [
                p for p in self._proposals.values()
                if p.status in (ChangeStatus.PROPOSED, ChangeStatus.REVIEWING)
            ]

    def list_approved(self) -> list[ChangeProposal]:
        """List all approved but not yet applied proposals."""
        with self._lock:
            return [
                p for p in self._proposals.values()
                if p.status == ChangeStatus.APPROVED
            ]

    def list_recent(self, n: int = 20) -> list[ChangeProposal]:
        """List the n most recent proposals."""
        with self._lock:
            sorted_proposals = sorted(
                self._proposals.values(),
                key=lambda p: p.created_at,
                reverse=True,
            )
            return sorted_proposals[:n]

    def get_stats(self) -> dict[str, Any]:
        """Get change management statistics."""
        with self._lock:
            total = len(self._proposals)
            by_status = {}
            by_type = {}
            for p in self._proposals.values():
                by_status[p.status.value] = by_status.get(p.status.value, 0) + 1
                by_type[p.change_type.value] = by_type.get(p.change_type.value, 0) + 1

            return {
                "enabled": self._enabled,
                "total_proposals": total,
                "pending": by_status.get("PROPOSED", 0) + by_status.get("REVIEWING", 0),
                "by_status": by_status,
                "by_type": by_type,
                "max_pending": self._max_pending,
                "auto_expire_hours": self._auto_expire_hours,
                "audit_entries": len(self._audit_log),
            }

    def get_audit_log(self, n: int = 50) -> list[dict[str, Any]]:
        """Get the most recent audit log entries."""
        with self._lock:
            return [
                entry.to_dict() for entry in self._audit_log[-n:]
            ]

    def _create_auto_approved(
        self,
        change_type: str | ChangeType,
        target_key: str,
        current_value: Any,
        proposed_value: Any,
        reason: str,
        proposed_by: str,
        risk_level: str | ChangeRisk = ChangeRisk.NORMAL,
        dry_run_result: dict | None = None,
        metadata: dict | None = None,
    ) -> ChangeProposal:
        """Create a proposal that's auto-approved (when change management is disabled)."""
        import uuid
        if isinstance(change_type, str):
            change_type = ChangeType(change_type)
        if isinstance(risk_level, str):
            risk_level = ChangeRisk(risk_level)

        proposal = ChangeProposal(
            id_=f"chg_{uuid.uuid4().hex[:12]}",
            change_type=change_type,
            target_key=target_key,
            current_value=current_value,
            proposed_value=proposed_value,
            reason=reason,
            proposed_by=proposed_by,
            risk_level=risk_level,
            status=ChangeStatus.APPROVED,
            approved_by="auto",
            dry_run_result=dry_run_result,
            metadata=metadata or {},
        )
        with self._lock:
            self._proposals[proposal.id_] = proposal
        return proposal

    def _record_audit(self, change_id: str, action: str, actor: str, details: str = "") -> None:
        """Record an audit log entry."""
        entry = ChangeAuditEntry(
            change_id=change_id,
            action=action,
            timestamp=time.time(),
            actor=actor,
            details=details,
        )
        self._audit_log.append(entry)
        if len(self._audit_log) > self._max_audit:
            self._audit_log.pop(0)

        # Also write to persistent audit log
        try:
            line = json.dumps(entry.to_dict()) + "\n"
            with open(self._audit_log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except (OSError, ValueError) as exc:
            _log.warning("[CM] Audit log write failed: %s", exc)

    def _expire_stale(self) -> None:
        """Expire proposals that have exceeded their auto-expiry time."""
        now = time.time()
        with self._lock:
            expired_ids = []
            for cid, prop in self._proposals.items():
                if (prop.status in (ChangeStatus.PROPOSED, ChangeStatus.REVIEWING)
                        and prop.expiry_at and now >= prop.expiry_at):
                    prop.status = ChangeStatus.EXPIRED
                    prop.updated_at = now
                    self._record_audit(cid, "EXPIRED", "system",
                                      f"Auto-expired after {self._auto_expire_hours}h")
                    expired_ids.append(cid)

            if expired_ids:
                _log.info("[CM] Expired %d stale proposals: %s",
                         len(expired_ids), expired_ids)


# ── Background expiry loop ─────────────────────────────────────────────────────

def _expiry_loop(mgr: ChangeManager) -> None:
    """Background thread that checks for stale proposals every 15 minutes."""
    import time as _time
    while not mgr._stop_expiry.is_set():
        _time.sleep(900)  # 15 minutes
        try:
            mgr._expire_stale()
        except Exception as exc:
            _log.warning("[CM] Expiry check failed: %s", exc)


# ── Singleton ──────────────────────────────────────────────────────────────────

_global_cm: ChangeManager | None = None
_cm_lock = threading.RLock()


def get_change_manager(cfg: dict[str, Any] | None = None) -> ChangeManager:
    """Get the global ChangeManager singleton."""
    global _global_cm
    with _cm_lock:
        if _global_cm is None:
            _global_cm = ChangeManager(cfg)
        return _global_cm


def propose_change(
    change_type: str | ChangeType,
    target_key: str,
    current_value: Any,
    proposed_value: Any,
    reason: str,
    proposed_by: str = "auto",
    risk_level: str | ChangeRisk = ChangeRisk.NORMAL,
) -> ChangeProposal:
    """Convenience: propose a change via singleton."""
    return get_change_manager().propose(
        change_type=change_type,
        target_key=target_key,
        current_value=current_value,
        proposed_value=proposed_value,
        reason=reason,
        proposed_by=proposed_by,
        risk_level=risk_level,
    )


# ── CLI ────────────────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.change_management")
    ap.add_argument("--propose", nargs=4, metavar=("type", "key", "current", "proposed"),
                    help="Propose a change: --propose CONFIG SL_PCT 0.30 0.25")
    ap.add_argument("--reason", type=str, default="CLI proposal", help="Reason for change")
    ap.add_argument("--risk", choices=["NORMAL", "HIGH", "CRITICAL"], default="NORMAL")
    ap.add_argument("--approve", type=str, metavar="change_id", help="Approve a change")
    ap.add_argument("--reject", type=str, nargs=2, metavar=("change_id", "reason"),
                    help="Reject a change")
    ap.add_argument("--list", action="store_true", help="List pending changes")
    ap.add_argument("--stats", action="store_true", help="Show stats")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    mgr = get_change_manager()

    if args.propose:
        ctype, key, current, proposed = args.propose
        prop = mgr.propose(
            change_type=ctype,
            target_key=key,
            current_value=current,
            proposed_value=proposed,
            reason=args.reason,
            proposed_by="CLI",
            risk_level=args.risk,
        )
        print(f"Proposed: {prop.id_} ({key}: {current} -> {proposed})")
        return

    if args.approve:
        ok = mgr.approve(args.approve, approved_by="CLI")
        print(f"{'Approved' if ok else 'Failed to approve'}: {args.approve}")
        return

    if args.reject:
        cid, reason = args.reject
        ok = mgr.reject(cid, rejected_by="CLI", reason=reason)
        print(f"{'Rejected' if ok else 'Failed to reject'}: {cid}")
        return

    if args.list:
        pending = mgr.list_pending()
        if args.json:
            print(json.dumps([p.to_dict() for p in pending], indent=2))
        else:
            print(f"Pending changes ({len(pending)}):")
            for p in pending:
                print(f"  [{p.status.value}] {p.id_}: {p.change_type.value} {p.target_key} = {p.proposed_value} "
                      f"(risk={p.risk_level.value}, by={p.proposed_by})")
        return

    if args.stats:
        stats = mgr.get_stats()
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print(f"Change Management: {'ENABLED' if stats['enabled'] else 'DISABLED'}")
            print(f"  Total proposals: {stats['total_proposals']}")
            print(f"  Pending: {stats['pending']}")
            print(f"  By status: {stats['by_status']}")
            print(f"  By type: {stats['by_type']}")
        return

    # Default: show pending
    pending = mgr.list_pending()
    print(f"Pending changes ({len(pending)}):")
    for p in pending:
        print(f"  [{p.status.value}] {p.id_}: {p.change_type.value} {p.target_key} = {p.proposed_value}")


if __name__ == "__main__":
    _cli()


__all__ = [
    "ChangeAuditEntry",
    "ChangeManager",
    "ChangeProposal",
    "ChangeRisk",
    "ChangeStatus",
    "ChangeType",
    "get_change_manager",
    "propose_change",
]

