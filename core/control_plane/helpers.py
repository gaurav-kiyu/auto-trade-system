"""
Legacy helper functions for the Admin Control Plane — extracted from server.py.

Provides token checking, identity resolution, permission checking,
and legacy audit logging for the FastAPI control plane routes.
"""

from __future__ import annotations

import uuid
from typing import Any

from core.auth.permissions import PermissionDenied
from core.control_plane.audit_store import _AUDIT_EVENTS, _AUDIT_LOCK
from core.datetime_ist import now_ist

_log = __import__("logging").getLogger(__name__)


def check_token(request: Any, token: str | None) -> None:
    """Raise 401 if token is configured and request header doesn't match."""
    if not token:
        return
    header = request.headers.get("x-admin-token", "")
    if header != token:
        raise _get_http_exception(401, "Invalid or missing X-Admin-Token")


def get_identity(request: Any) -> str:
    """Extract operator identity from request header."""
    return request.headers.get("x-operator-identity", "").strip() or "anonymous"


def get_client_ip(request: Any) -> str:
    """Extract client IP from request, respecting X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def require_permission(role_manager: Any, identity: str, permission: str) -> None:
    """Check RBAC permission. Raises 403 if denied."""
    if role_manager is None:
        return
    try:
        role_manager.check(identity, permission)
    except (KeyError, ValueError, TypeError) as exc:
        raise _get_http_exception(403, str(exc))
    except PermissionDenied as exc:
        raise _get_http_exception(403, str(exc))


def legacy_audit_log(
    audit_logger: Any, event_type: str, resource: str, action: str,
    outcome: str = "success", details: dict | None = None,
    user_id: str | None = None, ip_address: str | None = None,
) -> None:
    """Write event to persistent audit logger and in-memory ring buffer."""
    ev = {
        "event_id": uuid.uuid4().hex[:16],
        "timestamp": str(now_ist()),
        "event_type": event_type,
        "resource": resource,
        "action": action,
        "outcome": outcome,
        "details": details or {},
        "user_id": user_id,
        "ip_address": ip_address,
    }
    with _AUDIT_LOCK:
        _AUDIT_EVENTS.append(ev)
    if audit_logger is not None:
        try:
            audit_logger.log_event(
                event_type=event_type, resource=resource, action=action,
                outcome=outcome, details=details, severity="info",
                user_id=user_id, ip_address=ip_address,
            )
        except (ValueError, TypeError, AttributeError):
            _log.warning("[ADMIN] audit_logger.log_event failed", exc_info=True)


def _get_http_exception(status_code: int, detail: str) -> Exception:
    """Try to create a FastAPI HTTPException, fallback to RuntimeError."""
    try:
        from fastapi import HTTPException
        return HTTPException(status_code=status_code, detail=detail)
    except ImportError:
        return RuntimeError(f"HTTP {status_code}: {detail}")


__all__ = [
    "check_token",
    "get_client_ip",
    "get_identity",
    "legacy_audit_log",
    "require_permission",
]
