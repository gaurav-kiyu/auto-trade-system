"""
Adaptive Behavior Governance (v2.46).

Ensures adaptive/auto-tuning systems cannot mutate live trading behavior
without explicit approval. This is a critical safety layer.

Governance rules:
1. AUTO_TUNE_ENABLED must be False for LIVE mode (default)
2. Auto_tuner runs in DRY_RUN mode by default (never writes)
3. Adaptive_signal score adjustments stay in-memory only (no persistence)
4. Any behavioral change requires human approval in LIVE mode
5. All auto-tuning actions are logged with full audit trail
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist

log = logging.getLogger("adaptive_governance")


class AdaptiveMode(str):
    """Possible adaptive behavior modes."""
    DISABLED = "DISABLED"      # No adaptive behavior allowed
    DRY_RUN = "DRY_RUN"        # Suggest but never apply
    SUGGEST = "SUGGEST"        # Create suggestions for human review
    ENABLED = "ENABLED"        # Full adaptive behavior (LIVE only with explicit approval)


@dataclass
class GovernanceConfig:
    """Configuration for adaptive behavior governance."""
    adaptive_mode: AdaptiveMode = AdaptiveMode.DISABLED
    require_approval_for_live: bool = True
    max_daily_suggestions: int = 10
    audit_log_path: str = "logs/adaptive_governance.log"
    allowed_param_changes: set[str] = field(default_factory=set)
    blocked_param_changes: set[str] = field(default_factory=lambda: {
        "MAX_DAILY_LOSS", "MAX_DRAWDOWN", "SL_PCT", "TARGET_PCT",
        "EXECUTION_MODE", "PAPER_MODE", "BROKER_CONFIG",
    })


@dataclass
class AdaptiveAction:
    """Record of an adaptive behavior action."""
    timestamp: str
    source: str  # auto_tuner, adaptive_signal, etc.
    action_type: str  # score_adjustment, param_suggestion, etc.
    details: dict[str, Any]
    was_approved: bool
    was_applied: bool
    mode: AdaptiveMode


class AdaptiveBehaviorGovernor:
    """
    Governance layer for adaptive behavior systems.

    Ensures no automatic behavior changes in live trading without explicit approval.
    """

    def __init__(
        self,
        config: dict[str, Any],
        governance_config: GovernanceConfig | None = None,
    ):
        self._config = config
        self._governance = governance_config or self._create_from_config(config)
        self._actions: list[AdaptiveAction] = []
        self._pending_approvals: dict[str, dict[str, Any]] = {}
        self._init_audit_log()

    def _create_from_config(self, config: dict[str, Any]) -> GovernanceConfig:
        """Create governance config from main config."""
        mode_str = config.get("AUTO_TUNE_MODE", "DISABLED").upper()
        try:
            mode = AdaptiveMode(mode_str)
        except ValueError:
            mode = AdaptiveMode.DISABLED

        return GovernanceConfig(
            adaptive_mode=mode,
            require_approval_for_live=config.get("AUTO_TUNE_REQUIRE_APPROVAL", True),
            max_daily_suggestions=config.get("AUTO_TUNE_MAX_SUGGESTIONS", 10),
            allowed_param_changes=set(config.get("AUTO_TUNE_ALLOWED_PARAMS", [])),
        )

    def _init_audit_log(self):
        """Initialize audit logging."""
        log_path = Path(self._governance.audit_log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

    def get_mode(self) -> AdaptiveMode:
        """Get current adaptive behavior mode."""
        return self._governance.adaptive_mode

    def is_allowed(self) -> bool:
        """Check if adaptive behavior is allowed in current mode."""
        return self._governance.adaptive_mode != AdaptiveMode.DISABLED

    def can_auto_apply(self) -> bool:
        """Check if auto-tuning can automatically apply changes."""
        return self._governance.adaptive_mode == AdaptiveMode.ENABLED

    def request_param_change(
        self,
        source: str,
        param: str,
        current_value: Any,
        suggested_value: Any,
        reason: str,
    ) -> tuple[bool, str]:
        """
        Request a parameter change with governance approval.

        Returns:
            (is_approved, message)
        """
        if param in self._governance.blocked_param_changes:
            self._record_action(
                source=source,
                action_type="param_change_request",
                details={
                    "param": param,
                    "current": current_value,
                    "suggested": suggested_value,
                    "reason": reason,
                },
                was_approved=False,
                was_applied=False,
            )
            return False, f"⛔ Parameter {param} is blocked from auto-tuning"

        if self._governance.adaptive_mode == AdaptiveMode.DISABLED:
            self._record_action(
                source=source,
                action_type="param_change_request",
                details={"param": param, "suggested": suggested_value},
                was_approved=False,
                was_applied=False,
            )
            return False, "⛔ Adaptive behavior is DISABLED"

        if self._governance.adaptive_mode == AdaptiveMode.DRY_RUN:
            self._record_action(
                source=source,
                action_type="param_change_request",
                details={"param": param, "suggested": suggested_value, "mode": "DRY_RUN"},
                was_approved=False,
                was_applied=False,
            )
            return False, f"ℹ️ DRY_RUN: Would suggest {param}={suggested_value} (not applied)"

        if self._governance.adaptive_mode == AdaptiveMode.SUGGEST:
            approval_id = f"{param}:{now_ist().isoformat()}"
            self._pending_approvals[approval_id] = {
                "param": param,
                "current": current_value,
                "suggested": suggested_value,
                "reason": reason,
                "source": source,
                "timestamp": now_ist().isoformat(),
            }
            self._record_action(
                source=source,
                action_type="param_change_suggestion",
                details={"param": param, "suggested": suggested_value, "approval_id": approval_id},
                was_approved=False,
                was_applied=False,
            )
            return False, f"📋 Suggestion recorded: {param}={suggested_value}. Use approve_param('{approval_id}') to apply."

        if self._governance.adaptive_mode == AdaptiveMode.ENABLED:
            if self._governance.require_approval_for_live:
                approval_id = f"{param}:{now_ist().isoformat()}"
                self._pending_approvals[approval_id] = {
                    "param": param,
                    "current": current_value,
                    "suggested": suggested_value,
                    "reason": reason,
                    "source": source,
                    "timestamp": now_ist().isoformat(),
                }
                return False, f"⚠️ LIVE mode: Approval required. Use approve_param('{approval_id}') to apply."

            return True, "APPROVED"

        return False, "Unknown mode"

    def approve_param(self, approval_id: str) -> tuple[bool, str]:
        """Approve a pending parameter change."""
        if approval_id not in self._pending_approvals:
            return False, "Unknown approval ID"

        approval = self._pending_approvals.pop(approval_id)
        self._record_action(
            source=approval["source"],
            action_type="param_change_approved",
            details=approval,
            was_approved=True,
            was_applied=True,
        )
        return True, f"✅ Approved: {approval['param']}={approval['suggested']}"

    def reject_param(self, approval_id: str) -> tuple[bool, str]:
        """Reject a pending parameter change."""
        if approval_id not in self._pending_approvals:
            return False, "Unknown approval ID"

        approval = self._pending_approvals.pop(approval_id)
        self._record_action(
            source=approval["source"],
            action_type="param_change_rejected",
            details=approval,
            was_approved=False,
            was_applied=False,
        )
        return True, f"❌ Rejected: {approval['param']}={approval['suggested']}"

    def record_score_adjustment(
        self,
        source: str,
        signal_id: str,
        raw_score: int,
        adjusted_score: int,
        reason: str,
    ):
        """Record adaptive signal score adjustments (in-memory only)."""
        self._record_action(
            source=source,
            action_type="score_adjustment",
            details={
                "signal_id": signal_id,
                "raw_score": raw_score,
                "adjusted_score": adjusted_score,
                "reason": reason,
            },
            was_approved=True,
            was_applied=True,
        )

    def get_pending_approvals(self) -> list[dict[str, Any]]:
        """Get list of pending parameter change approvals."""
        return list(self._pending_approvals.values())

    def get_governance_report(self) -> dict[str, Any]:
        """Get governance status report."""
        return {
            "mode": self._governance.adaptive_mode.value,
            "can_auto_apply": self.can_auto_apply(),
            "is_allowed": self.is_allowed(),
            "pending_approvals": len(self._pending_approvals),
            "actions_today": len([a for a in self._actions if a.timestamp.startswith(now_ist().strftime("%Y-%m-%d"))]),
        }

    def _record_action(
        self,
        source: str,
        action_type: str,
        details: dict[str, Any],
        was_approved: bool,
        was_applied: bool,
    ):
        """Record an action to the audit log."""
        action = AdaptiveAction(
            timestamp=now_ist().isoformat(),
            source=source,
            action_type=action_type,
            details=details,
            was_approved=was_approved,
            was_applied=was_applied,
            mode=self._governance.adaptive_mode,
        )
        self._actions.append(action)

        log_msg = f"[GOV] {source}/{action_type}: approved={was_approved}, applied={was_applied}"
        if details:
            log_msg += f" {details}"
        log.info(log_msg)


def create_governor(config: dict[str, Any]) -> AdaptiveBehaviorGovernor:
    """Create adaptive behavior governor from config."""
    return AdaptiveBehaviorGovernor(config)
