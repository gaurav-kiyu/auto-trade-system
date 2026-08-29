"""Self-Service Infrastructure Provisioning API routes for the Enterprise Dashboard.

Handles /api/platform/provisioning/* endpoints (Constitution v4.0 PLS-06):
  - GET  /api/platform/provisioning/blueprints          — list available blueprints
  - GET  /api/platform/provisioning/blueprints/{name}   — blueprint detail + artifact status
  - POST /api/platform/provisioning/request             — create a provisioning request
  - GET  /api/platform/provisioning/requests            — list provisioning requests
  - POST /api/platform/provisioning/requests/{id}/approve     — approve (admin)
  - POST /api/platform/provisioning/requests/{id}/provisioned — mark provisioned (admin)
  - POST /api/platform/provisioning/requests/{id}/reject      — reject (admin)
  - GET  /api/platform/provisioning/stats               — provisioning statistics
  - GET  /api/platform/provisioning/report              — full provisioning report

This is the self-service layer: it manages the provisioning workflow/state without
executing system commands (IaC apply is left to the operator's pipeline).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, Request

_log = logging.getLogger(__name__)


def register_provisioning_routes(app, dashboard, admin_only, operator_or_admin) -> None:  # type: ignore[no-untyped-def]
    """Register self-service provisioning API routes.

    Args:
        app: FastAPI application instance.
        dashboard: EnterpriseDashboard instance.
        admin_only: FastAPI Depends for admin role.
        operator_or_admin: FastAPI Depends for operator or admin role.

    """

    def _provisioner():
        from core.self_service_provisioning import get_provisioner
        return get_provisioner()

    @app.get("/api/platform/provisioning/blueprints", tags=["Provisioning"])
    async def api_provisioning_blueprints(
        environment: str = "",
        user: Any = Depends(operator_or_admin),
    ):
        """List available self-service provisioning blueprints."""
        try:
            prov = _provisioner()
            blueprints = prov.list_blueprints(environment=environment)
            return {
                "blueprints": [b.to_dict() for b in blueprints],
                "count": len(blueprints),
                "timestamp": __import__("time").time(),
            }
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Provisioning blueprints unavailable: %s", exc)
            return {"blueprints": [], "count": 0, "error": str(exc)}

    @app.get("/api/platform/provisioning/blueprints/{name}", tags=["Provisioning"])
    async def api_provisioning_blueprint_detail(
        name: str,
        user: Any = Depends(operator_or_admin),
    ):
        """Get a single blueprint with artifact existence status."""
        try:
            prov = _provisioner()
            bp = prov.get_blueprint(name)
            if not bp:
                return {"status": "not_found", "detail": f"Blueprint not found: {name}"}
            return {
                "blueprint": bp.to_dict(),
                "artifacts": prov.blueprint_artifacts_exist(name),
            }
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Blueprint detail unavailable: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.post("/api/platform/provisioning/request", tags=["Provisioning"])
    async def api_provisioning_request(
        request: Request,
        user: Any = Depends(operator_or_admin),
    ):
        """Create a self-service provisioning request (no ops ticket)."""
        try:
            body = await request.json()
            blueprint = str(body.get("blueprint", ""))
            actor = str(body.get("actor", getattr(user, "username", "self-service")))
            environment = str(body.get("environment", ""))
            prov = _provisioner()
            req = prov.request_provisioning(blueprint, actor=actor, environment=environment)
            if req is None:
                return {"status": "error", "detail": f"Unknown blueprint: {blueprint}"}
            return {"status": "created", "request": req.to_dict()}
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Provisioning request failed: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/platform/provisioning/requests", tags=["Provisioning"])
    async def api_provisioning_requests(
        status: str = "",
        environment: str = "",
        user: Any = Depends(operator_or_admin),
    ):
        """List provisioning requests with optional filters."""
        try:
            prov = _provisioner()
            requests = prov.list_requests(status=status, environment=environment)
            return {
                "requests": [r.to_dict() for r in requests],
                "count": len(requests),
                "timestamp": __import__("time").time(),
            }
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Provisioning requests unavailable: %s", exc)
            return {"requests": [], "count": 0, "error": str(exc)}

    @app.post("/api/platform/provisioning/requests/{request_id}/approve", tags=["Provisioning"])
    async def api_provisioning_approve(
        request_id: str,
        request: Request,
        user: Any = Depends(admin_only),
    ):
        """Approve a pending provisioning request (admin only)."""
        try:
            body = await request.json()
            note = str(body.get("note", ""))
            approver = str(body.get("approver", getattr(user, "username", "admin")))
            prov = _provisioner()
            req = prov.approve_provisioning(request_id, approver=approver, note=note)
            if not req:
                return {"status": "not_found", "detail": f"Request not found: {request_id}"}
            return {"status": "ok", "request": req.to_dict()}
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Provisioning approve failed: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.post("/api/platform/provisioning/requests/{request_id}/provisioned", tags=["Provisioning"])
    async def api_provisioning_mark_provisioned(
        request_id: str,
        request: Request,
        user: Any = Depends(admin_only),
    ):
        """Mark an approved provisioning request as provisioned (admin only)."""
        try:
            body = await request.json()
            note = str(body.get("note", ""))
            prov = _provisioner()
            req = prov.mark_provisioned(request_id, note=note)
            if not req:
                return {"status": "not_found", "detail": f"Request not found: {request_id}"}
            return {"status": "ok", "request": req.to_dict()}
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Provisioning mark-provisioned failed: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.post("/api/platform/provisioning/requests/{request_id}/reject", tags=["Provisioning"])
    async def api_provisioning_reject(
        request_id: str,
        request: Request,
        user: Any = Depends(admin_only),
    ):
        """Reject a pending provisioning request (admin only)."""
        try:
            body = await request.json()
            reason = str(body.get("reason", "rejected by approver"))
            prov = _provisioner()
            req = prov.reject_provisioning(request_id, reason=reason)
            if not req:
                return {"status": "not_found", "detail": f"Request not found: {request_id}"}
            return {"status": "ok", "request": req.to_dict()}
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Provisioning reject failed: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/platform/provisioning/stats", tags=["Provisioning"])
    async def api_provisioning_stats(user: Any = Depends(operator_or_admin)):
        """Get provisioning statistics."""
        try:
            prov = _provisioner()
            return {"stats": prov.get_stats(), "timestamp": __import__("time").time()}
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Provisioning stats unavailable: %s", exc)
            return {"stats": {}, "error": str(exc)}

    @app.get("/api/platform/provisioning/report", tags=["Provisioning"])
    async def api_provisioning_report(user: Any = Depends(admin_only)):
        """Get the full self-service provisioning report (admin only)."""
        try:
            prov = _provisioner()
            return prov.get_report()
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Provisioning report unavailable: %s", exc)
            return {"status": "unavailable", "detail": str(exc)}
