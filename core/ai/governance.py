"""
AD-KIYU AI Governance — AIGovernanceBoard.

Orchestrates the full AI governance pipeline:
  ModelRegistry → CanaryManager → RollbackController

Enforces governance rules:
  - AI must NOT self-mutate live execution logic directly
  - Every model requires approved A/B test in paper mode first
  - Canary deployments: 10% → 50% → 100% over configured trading days
  - Drift detection auto-triggers rollback within 15 minutes
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from core.ai.canary_manager import CanaryManager
from core.ai.model_registry import ModelRegistry
from core.ai.rollback_controller import RollbackController

_log = logging.getLogger(__name__)


class AIGovernanceError(Exception):
    """Raised when a governance rule is violated."""


class AIGovernanceBoard:
    """Central governance board for ML model lifecycle management."""

    def __init__(
        self,
        model_registry: ModelRegistry | None = None,
        canary_manager: CanaryManager | None = None,
        rollback_controller: RollbackController | None = None,
    ):
        self._lock = threading.Lock()
        self.model_registry = model_registry or ModelRegistry()
        self.canary_manager = canary_manager or CanaryManager()
        self.rollback_controller = rollback_controller or RollbackController(
            model_registry=self.model_registry,
        )
        self._audit_log: list[dict[str, Any]] = []

    def register_model(
        self,
        model_id: str,
        version: str,
        name: str,
        source_path: str = "",
        checksum: str = "",
        metrics: dict[str, float] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register a new model as DRAFT."""
        self.model_registry.register(
            model_id=model_id,
            version=version,
            name=name,
            source_path=source_path,
            checksum=checksum,
            metrics=metrics or {},
            metadata=metadata or {},
        )
        self._audit("register", model_id, {"version": version, "name": name})

    def approve_for_canary(
        self,
        model_id: str,
        approved_by: str = "",
    ) -> None:
        """Approve a DRAFT model for canary rollout (DRAFT → CANARY)."""
        rec = self.model_registry.get(model_id)
        if rec is None:
            raise AIGovernanceError(f"Model {model_id} not found")
        if rec.status != "DRAFT":
            raise AIGovernanceError(f"Model {model_id} has status {rec.status}, expected DRAFT")
        self.model_registry.update_status(model_id, "CANARY", approved_by=approved_by, approved_ts=time.time())
        self.canary_manager.start_canary(model_id, rec.name, rec.version)
        self._audit("approve_canary", model_id, {"approved_by": approved_by})
        _log.info(f"[GOV] Model {model_id} approved for canary by {approved_by}")

    def promote_to_active(self, model_id: str, min_trades: int = 20, min_win_rate: float = 0.55) -> None:
        """Promote a CANARY model to ACTIVE if it meets performance criteria."""
        rec = self.model_registry.get(model_id)
        if rec is None:
            raise AIGovernanceError(f"Model {model_id} not found")
        if rec.status not in ("CANARY", "ACTIVE"):
            raise AIGovernanceError(f"Model {model_id} has status {rec.status}, expected CANARY")

        if not self.canary_manager.is_canary_ready_for_promotion(model_id, min_trades, min_win_rate):
            canary = self.canary_manager.get_state(model_id)
            wr = canary.trades_won / canary.trades_seen if canary and canary.trades_seen > 0 else 0
            raise AIGovernanceError(
                f"Model {model_id} not ready: {canary.trades_seen if canary else 0} trades, "
                f"{wr:.1%} win rate (need {min_trades} trades, {min_win_rate:.0%} WR)"
            )

        # Deprecate previous ACTIVE model of same name
        prev_active = self.model_registry.get_active(rec.name)
        if prev_active:
            self.model_registry.update_status(prev_active.model_id, "DEPRECATED")

        self.model_registry.update_status(model_id, "ACTIVE")
        self.canary_manager.end_canary(model_id)
        self._audit("promote_active", model_id, {})
        _log.info(f"[GOV] Model {model_id} promoted to ACTIVE")

    def rollback(self, model_id: str, reason: str = "manual") -> None:
        """Manually rollback a model to the previous ACTIVE version."""
        rec = self.model_registry.get(model_id)
        if rec is None:
            raise AIGovernanceError(f"Model {model_id} not found")

        # Find previous DEPRECATED model of same name
        all_models = self.model_registry.list_by_name(rec.name)
        rollback_target = None
        for m in all_models:
            if m.status == "DEPRECATED" and m.model_id != model_id:
                rollback_target = m
                break

        self.model_registry.update_status(model_id, "ROLLED_BACK", rollback_ts=time.time())
        if rollback_target:
            self.model_registry.update_status(rollback_target.model_id, "ACTIVE", activated_ts=time.time())
            self._audit("rollback", model_id, {"reason": reason, "rolled_back_to": rollback_target.model_id})
            _log.warning(f"[GOV] Model {model_id} rolled back to {rollback_target.model_id}: {reason}")
        else:
            self._audit("rollback", model_id, {"reason": reason, "rolled_back_to": "none"})
            _log.warning(f"[GOV] Model {model_id} rolled back (no predecessor): {reason}")

    def evaluate_and_auto_rollback(self, model_id: str, metrics: dict[str, float]) -> bool:
        """Evaluate metrics and auto-rollback on threshold breach."""
        rec = self.model_registry.get(model_id)
        if rec is None:
            return False
        triggered = self.rollback_controller.evaluate(model_id, rec.name, rec.version, metrics)
        if triggered:
            self.model_registry.update_status(model_id, "ROLLED_BACK", rollback_ts=time.time())
            self._audit("auto_rollback", model_id, {"metrics": metrics})
        return triggered

    def get_status(self, model_id: str) -> dict[str, Any]:
        """Get full governance status for a model."""
        rec = self.model_registry.get(model_id)
        if rec is None:
            return {"error": "not found"}
        canary = self.canary_manager.get_state(model_id)
        rollbacks = self.rollback_controller.recent_rollbacks()
        return {
            "model_id": rec.model_id,
            "name": rec.name,
            "version": rec.version,
            "status": rec.status,
            "created_ts": rec.created_ts,
            "approved_ts": rec.approved_ts,
            "activated_ts": rec.activated_ts,
            "metrics": rec.metrics,
            "canary": {
                "stage": canary.stage if canary else None,
                "trades_seen": canary.trades_seen if canary else 0,
                "win_rate": canary.trades_won / canary.trades_seen if canary and canary.trades_seen > 0 else 0,
            } if canary else None,
            "recent_rollbacks": len(rollbacks),
        }

    # ── Audit helpers ─────────────────────────────────────────────────────────

    def _audit(self, action: str, model_id: str, detail: dict[str, Any]) -> None:
        with self._lock:
            self._audit_log.append({
                "ts": time.time(),
                "action": action,
                "model_id": model_id,
                "detail": detail,
            })

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent governance actions."""
        with self._lock:
            return list(self._audit_log[-limit:])
