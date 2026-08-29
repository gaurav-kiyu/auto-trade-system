"""Strategy Governance route registration for the Enterprise Dashboard.

Handles: /api/governance/* endpoints for strategy lifecycle management:
  - /api/governance/status         — Governance system health
  - /api/governance/pending        — Pending approval requests
  - /api/governance/history        — Request history (all or per-strategy)
  - /api/governance/rules          — Approval rules configuration
  - /api/governance/log            — Approval audit log
  - /api/governance/report         — Comprehensive governance report
  - /api/governance/request        — Request a transition
  - /api/governance/approve        — Approve a transition
  - /api/governance/reject         — Reject a transition
  - /api/governance/quality        — Data quality scoring report
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import Depends, Request

_log = logging.getLogger(__name__)


def register_governance_routes(app, dashboard, admin_only, operator_or_admin) -> None:  # type: ignore[no-untyped-def]
    """Register strategy governance and data quality API routes.

    Args:
        app: FastAPI application instance.
        dashboard: EnterpriseDashboard instance.
        admin_only: FastAPI Depends for admin role.
        operator_or_admin: FastAPI Depends for operator or admin role.

    """

    @app.get("/api/governance/status", tags=["Governance"])
    async def api_governance_status(user: Any = Depends(operator_or_admin)):
        """Get governance system availability status."""
        statuses = {
            "approval_workflow": False,
            "quality_scorer": False,
            "invariants_engine": False,
        }
        # Check approval workflow
        try:
            from core.strategy.approval_workflow import get_approval_workflow
            wf = get_approval_workflow()
            report = wf.get_governance_report()
            statuses["approval_workflow"] = True
            statuses["pending_approvals"] = report.get("pending_count", 0)
            statuses["approved_live"] = len(report.get("strategies_approved_for_live", []))
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Approval workflow unavailable: %s", exc)
            statuses["approval_workflow_error"] = str(exc)

        # Check quality scorer
        try:
            from core.data_quality_scorer import get_quality_scorer
            scorer = get_quality_scorer()
            health = scorer.get_system_health()
            statuses["quality_scorer"] = True
            statuses["data_quality_score"] = health.overall_score
            statuses["data_quality_health"] = health.health
            statuses["data_quality_trend"] = health.trend
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Quality scorer unavailable: %s", exc)
            statuses["quality_scorer_error"] = str(exc)

        # Check invariants engine
        try:
            from core.invariants.engine import get_state
            state = get_state()
            chk = state.get("checks", 0)
            statuses["invariants_engine"] = True
            statuses["invariant_checks"] = len(chk) if isinstance(chk, list) else chk
            statuses["invariant_violations"] = state.get("violation_count", 0)
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Invariants engine unavailable: %s", exc)
            statuses["invariants_engine_error"] = str(exc)

        return statuses

    @app.get("/api/governance/report", tags=["Governance"])
    async def api_governance_report(user: Any = Depends(operator_or_admin)):
        """Get comprehensive strategy governance report."""
        try:
            from core.strategy.approval_workflow import get_approval_workflow
            wf = get_approval_workflow()
            report = wf.get_governance_report()
            report["timestamp"] = time.time()
            return report
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Governance report unavailable: %s", exc)
            return {"status": "unavailable", "detail": str(exc)}

    @app.get("/api/governance/pending", tags=["Governance"])
    async def api_governance_pending(user: Any = Depends(operator_or_admin)):
        """Get all pending approval requests."""
        try:
            from core.strategy.approval_workflow import get_approval_workflow
            wf = get_approval_workflow()
            pending = wf.get_pending_approvals()
            return {"pending": pending, "count": len(pending), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Pending approvals unavailable: %s", exc)
            return {"pending": [], "count": 0, "error": str(exc)}

    @app.get("/api/governance/history", tags=["Governance"])
    async def api_governance_history(
        strategy_name: str = "",
        user: Any = Depends(operator_or_admin),
    ):
        """Get approval request history, optionally filtered by strategy."""
        try:
            from core.strategy.approval_workflow import get_approval_workflow
            wf = get_approval_workflow()
            history = wf.get_request_history(strategy_name=strategy_name or None)
            return {
                "history": history,
                "count": len(history),
                "strategy_filter": strategy_name or None,
                "timestamp": time.time(),
            }
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Governance history unavailable: %s", exc)
            return {"history": [], "count": 0, "error": str(exc)}

    @app.get("/api/governance/log", tags=["Governance"])
    async def api_governance_log(
        limit: int = 50,
        user: Any = Depends(admin_only),
    ):
        """Get approval audit log entries."""
        try:
            from core.strategy.approval_workflow import get_approval_workflow
            wf = get_approval_workflow()
            log_entries = wf.get_approval_log(limit=min(limit, 200))
            return {"log": log_entries, "count": len(log_entries), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Governance log unavailable: %s", exc)
            return {"log": [], "count": 0, "error": str(exc)}

    @app.get("/api/governance/rules", tags=["Governance"])
    async def api_governance_rules(user: Any = Depends(operator_or_admin)):
        """Get current approval rules configuration."""
        try:
            from core.strategy.approval_workflow import get_approval_workflow
            wf = get_approval_workflow()
            rules = wf.get_approval_rules()
            return {"rules": rules, "count": len(rules), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Governance rules unavailable: %s", exc)
            return {"rules": {}, "count": 0, "error": str(exc)}

    @app.post("/api/governance/request", tags=["Governance"])
    async def api_governance_request(
        request: Request,
        user: Any = Depends(operator_or_admin),
    ):
        """Request a strategy governance transition.

        Body (JSON):
            strategy_name (str, required): Name of the strategy.
            to_state (str, required): Desired governance state.
            evidence (dict, optional): Evidence supporting the transition.
        """
        try:
            body = await request.json()
            from core.strategy.approval_workflow import get_approval_workflow
            wf = get_approval_workflow()
            ok, msg, request_id = wf.request_transition(
                strategy_name=str(body.get("strategy_name", "")),
                to_state=str(body.get("to_state", "")),
                requested_by=user.username,
                evidence=body.get("evidence", {}),
            )
            return {
                "success": ok,
                "message": msg,
                "request_id": request_id,
                "timestamp": time.time(),
            }
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Governance request failed: %s", exc)
            return {"success": False, "error": str(exc)}

    @app.post("/api/governance/approve", tags=["Governance"])
    async def api_governance_approve(
        request: Request,
        user: Any = Depends(admin_only),
    ):
        """Approve a pending strategy governance transition.

        Body (JSON):
            strategy_name (str, required): Name of the strategy.
            to_state (str, required): Target state to approve.
        """
        try:
            body = await request.json()
            from core.strategy.approval_workflow import get_approval_workflow
            wf = get_approval_workflow()
            ok, msg = wf.approve_transition(
                strategy_name=str(body.get("strategy_name", "")),
                to_state=str(body.get("to_state", "")),
                approved_by=user.username,
            )
            return {
                "success": ok,
                "message": msg,
                "timestamp": time.time(),
            }
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Governance approve failed: %s", exc)
            return {"success": False, "error": str(exc)}

    @app.post("/api/governance/reject", tags=["Governance"])
    async def api_governance_reject(
        request: Request,
        user: Any = Depends(admin_only),
    ):
        """Reject a pending strategy governance transition.

        Body (JSON):
            strategy_name (str, required): Name of the strategy.
            to_state (str, required): Target state to reject.
            reason (str, optional): Reason for rejection.
        """
        try:
            body = await request.json()
            from core.strategy.approval_workflow import get_approval_workflow
            wf = get_approval_workflow()
            ok, msg = wf.reject_transition(
                strategy_name=str(body.get("strategy_name", "")),
                to_state=str(body.get("to_state", "")),
                rejected_by=user.username,
                reason=str(body.get("reason", "Rejected via dashboard")),
            )
            return {
                "success": ok,
                "message": msg,
                "timestamp": time.time(),
            }
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Governance reject failed: %s", exc)
            return {"success": False, "error": str(exc)}

    @app.get("/api/governance/quality", tags=["Governance"])
    async def api_data_quality(user: Any = Depends(operator_or_admin)):
        """Get data quality scoring report for all data sources."""
        try:
            from core.data_quality_scorer import get_quality_scorer
            scorer = get_quality_scorer()
            report = scorer.get_source_health_report()
            return report
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Data quality unavailable: %s", exc)
            return {"status": "unavailable", "detail": str(exc)}
