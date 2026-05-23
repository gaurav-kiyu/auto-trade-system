"""
AD-KIYU Safe Admin Control Plane — FastAPI server on port 7080.

Provides validated, audited, and reversible control over the trading system.
All mutations follow: validate() → audit_log() → version() → reversible().

Supports both legacy API (via _ref parameters) and new clean API (via ControlPlaneServer).

Endpoints (legacy):
    GET/POST /mode                    — Operating mode
    GET      /wal                     — WAL journal inspection
    GET      /cert                    — Idempotency certificates
    GET/POST /invariants/[/toggle]    — Runtime invariant checks
    POST     /control/halt|resume     — Kill-switch
    GET      /control/status          — Halt status
    GET/POST /strategies[/toggle]     — Strategy toggles
    GET/POST /assets[/toggle]         — Asset toggles
    GET/POST /features[/set]          — Feature flags
    GET/POST /models[/select]         — AI model selection
    GET      /audit                   — Audit log
    GET/POST /roles[/assign]          — RBAC roles
    POST     /config/reload           — Config hot-reload
    GET      /broker                  — Broker summary

Endpoints (v2, new style):
    POST /control/auth/login          — JWT login
    GET  /control/state               — Full state
    GET  /control/audit               — Audit history
    POST /control/kill                — Emergency kill
    POST /control/strategy/{name}/{action}
    POST /control/asset_class/{class}/{action}
    POST /control/capital/{amount}
    POST /control/risk_limit/{name}/{value}
    POST /control/ai_model/{name}/{action}
    POST /control/feature_flag/{name}/{value}

SAFETY: Disabled by default. Set admin_control_plane_enabled: true to enable.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)

# Read version from VERSION file
_VERSION_FILE = Path(__file__).resolve().parent.parent.parent / "VERSION"
try:
    _VERSION = _VERSION_FILE.read_text(encoding="utf-8").strip()
except Exception:
    _VERSION = "0.0.0"

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 7080

# ── In-memory audit ring buffer (last 500 events) — legacy compat ──────────
_AUDIT_EVENTS: deque[dict[str, Any]] = deque(maxlen=500)
_AUDIT_LOCK = threading.Lock()

# ── FastAPI availability ─────────────────────────────────────────────────────

try:
    from fastapi import FastAPI, Header, HTTPException, Request
    _HAVE_FASTAPI = True
except ImportError:
    FastAPI = None  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    HTTPException = None  # type: ignore[assignment]
    Request = None  # type: ignore[assignment]
    _HAVE_FASTAPI = False
    _log.warning("fastapi not installed — admin control plane unavailable")

try:
    import uvicorn
    _HAVE_UVICORN = True
except ImportError:
    uvicorn = None  # type: ignore[assignment]
    _HAVE_UVICORN = False
    _log.warning("uvicorn not installed — admin control plane cannot serve")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ControlAction:
    """Record of a single control action with full audit trail."""
    action_id: str
    action: str
    target: str
    value: str
    identity: str
    timestamp: datetime
    success: bool
    previous_state: dict[str, Any] | None = None
    new_state: dict[str, Any] | None = None
    reason: str = ""
    reversible: bool = True


# ── AuditStore ────────────────────────────────────────────────────────────────

class AuditStore:
    """Thread-safe in-memory + JSONL audit store for control actions."""

    def __init__(self, max_entries: int = 1000, persist_path: str = ""):
        self._lock = threading.Lock()
        self._entries: list[ControlAction] = []
        self._max_entries = max_entries
        self._persist_path = persist_path

    def append(self, action: ControlAction) -> None:
        with self._lock:
            self._entries.append(action)
            if len(self._entries) > self._max_entries:
                self._entries.pop(0)
        if self._persist_path:
            try:
                Path(self._persist_path).parent.mkdir(parents=True, exist_ok=True)
                with open(self._persist_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "action_id": action.action_id,
                        "action": action.action,
                        "target": action.target,
                        "value": action.value,
                        "identity": action.identity,
                        "timestamp": str(action.timestamp),
                        "success": action.success,
                        "reason": action.reason,
                    }, default=str) + "\n")
            except Exception as e:
                _log.warning("[CTRL] Failed to persist audit entry: %s", e)

        # Also write to legacy _AUDIT_EVENTS ring buffer
        legacy_ev = {
            "event_id": action.action_id,
            "timestamp": str(action.timestamp),
            "event_type": action.action,
            "resource": action.target,
            "action": action.action,
            "outcome": "success" if action.success else "failure",
            "details": {"value": action.value, "reason": action.reason},
            "user_id": action.identity,
            "ip_address": "local",
        }
        with _AUDIT_LOCK:
            _AUDIT_EVENTS.append(legacy_ev)

    def get_recent(self, limit: int = 100) -> list[ControlAction]:
        with self._lock:
            return list(self._entries[-limit:])

    def count(self) -> int:
        with self._lock:
            return len(self._entries)


# ── ControlPlaneServer ────────────────────────────────────────────────────────

class ControlPlaneServer:
    """
    Safe Admin Control Plane Server.

    Validated, audited, reversible control over the trading system.
    All mutations go through: validate() → audit() → version().
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
    ):
        self._cfg = config or {}
        self._audit_store = AuditStore(
            persist_path=self._cfg.get("admin_audit_log_path", "logs/control_plane_audit.jsonl"),
        )
        self._version = 0
        self._lock = threading.RLock()
        self._kill_triggered = False
        self._halt_callback: Callable[[str], None] | None = None
        self._state_callback: Callable[[str, Any], None] | None = None

        self._strategies: dict[str, bool] = {}
        self._asset_classes: dict[str, bool] = {}
        self._feature_flags: dict[str, bool] = {}
        self._capital: float = float(self._cfg.get("BASE_CAPITAL", 5000))
        self._risk_limits: dict[str, float] = {}

    @property
    def audit_store(self) -> AuditStore:
        return self._audit_store

    def register_halt_callback(self, cb: Callable[[str], None]) -> None:
        self._halt_callback = cb

    def register_state_callback(self, cb: Callable[[str, Any], None]) -> None:
        self._state_callback = cb

    def _audit(
        self, action: str, target: str, value: str, identity: str,
        success: bool, reason: str = "",
        previous_state: dict | None = None, new_state: dict | None = None,
    ) -> ControlAction:
        record = ControlAction(
            action_id=uuid.uuid4().hex[:12],
            action=action, target=target, value=value,
            identity=identity, timestamp=now_ist(),
            success=success, reason=reason,
            previous_state=previous_state, new_state=new_state,
        )
        self._audit_store.append(record)
        with self._lock:
            self._version += 1
        return record

    def control_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "version": self._version,
                "capital": self._capital,
                "kill_triggered": self._kill_triggered,
                "strategies": dict(self._strategies),
                "asset_classes": dict(self._asset_classes),
                "feature_flags": dict(self._feature_flags),
                "risk_limits": dict(self._risk_limits),
                "audit_count": self._audit_store.count(),
                "mode": self._cfg.get("EXECUTION_MODE", "SIGNAL_ONLY"),
                "timestamp": str(now_ist()),
            }

    def control_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        return [
            {
                "action_id": a.action_id, "action": a.action,
                "target": a.target, "value": a.value,
                "identity": a.identity, "timestamp": str(a.timestamp),
                "success": a.success, "reason": a.reason,
                "reversible": a.reversible,
            }
            for a in self._audit_store.get_recent(limit)
        ]

    def control_strategy(self, name: str, action: str, identity: str) -> dict[str, Any]:
        if action not in ("enable", "disable"):
            rec = self._audit("strategy", name, action, identity, False, f"Unknown action: {action}")
            return {"success": False, "reason": f"Unknown action: {action}", "action_id": rec.action_id}
        with self._lock:
            previous = self._strategies.get(name)
            self._strategies[name] = (action == "enable")
            new_state = self._strategies[name]
            rec = self._audit("strategy", name, action, identity, True,
                              previous_state={"enabled": previous}, new_state={"enabled": new_state})
            _log.warning("[CTRL] Strategy %s %s by %s", name, action, identity)
            if self._state_callback:
                self._state_callback(f"strategy/{name}", {"enabled": new_state})
            return {"success": True, "action_id": rec.action_id, "strategy": name, "enabled": new_state}

    def control_asset_class(self, asset_class: str, action: str, identity: str) -> dict[str, Any]:
        if action not in ("enable", "disable"):
            rec = self._audit("asset_class", asset_class, action, identity, False, f"Unknown action: {action}")
            return {"success": False, "reason": f"Unknown action: {action}", "action_id": rec.action_id}
        with self._lock:
            previous = self._asset_classes.get(asset_class)
            self._asset_classes[asset_class] = (action == "enable")
            new_state = self._asset_classes[asset_class]
            rec = self._audit("asset_class", asset_class, action, identity, True,
                              previous_state={"enabled": previous}, new_state={"enabled": new_state})
            _log.warning("[CTRL] Asset class %s %s by %s", asset_class, action, identity)
            if self._state_callback:
                self._state_callback(f"asset_class/{asset_class}", {"enabled": new_state})
            return {"success": True, "action_id": rec.action_id, "asset_class": asset_class, "enabled": new_state}

    def control_kill(self, identity: str, reason: str = "Manual kill via control plane") -> dict[str, Any]:
        with self._lock:
            self._kill_triggered = True
            rec = self._audit("kill", "system", "HALT", identity, True, reason=reason)
            _log.critical("[CTRL] EMERGENCY KILL triggered by %s: %s", identity, reason)
            if self._halt_callback:
                self._halt_callback(f"EMERGENCY_KILL by {identity}: {reason}")
            return {"success": True, "action_id": rec.action_id, "kill_triggered": True, "reason": reason}

    def control_capital(self, amount: str, identity: str) -> dict[str, Any]:
        try:
            new_amount = float(amount)
        except ValueError:
            rec = self._audit("capital", "system", amount, identity, False, f"Invalid amount: {amount}")
            return {"success": False, "reason": f"Invalid amount: {amount}", "action_id": rec.action_id}
        with self._lock:
            previous = self._capital
            self._capital = new_amount
            rec = self._audit("capital", "system", amount, identity, True,
                              previous_state={"capital": previous}, new_state={"capital": new_amount})
            _log.warning("[CTRL] Capital set to %.2f by %s", new_amount, identity)
            if self._state_callback:
                self._state_callback("capital", {"capital": new_amount})
            return {"success": True, "action_id": rec.action_id, "capital": new_amount, "previous": previous}

    def control_risk_limit(self, name: str, value: str, identity: str) -> dict[str, Any]:
        try:
            new_value = float(value)
        except ValueError:
            rec = self._audit("risk_limit", name, value, identity, False, f"Invalid value: {value}")
            return {"success": False, "reason": f"Invalid value: {value}", "action_id": rec.action_id}
        with self._lock:
            previous = self._risk_limits.get(name)
            self._risk_limits[name] = new_value
            rec = self._audit("risk_limit", name, value, identity, True,
                              previous_state={"value": previous}, new_state={"value": new_value})
            _log.warning("[CTRL] Risk limit %s set to %.2f by %s", name, new_value, identity)
            if self._state_callback:
                self._state_callback(f"risk_limit/{name}", {"value": new_value})
            return {"success": True, "action_id": rec.action_id, "limit_name": name, "value": new_value, "previous": previous}

    def control_ai_model(self, name: str, action: str, identity: str) -> dict[str, Any]:
        rec = self._audit("ai_model", name, action, identity, True,
                          reason=f"Model {action}: {name}")
        _log.warning("[CTRL] AI model %s %s by %s", name, action, identity)
        if self._state_callback:
            self._state_callback(f"ai_model/{name}", {"action": action})
        return {"success": True, "action_id": rec.action_id, "model": name, "action": action}

    def control_feature_flag(self, name: str, value: str, identity: str) -> dict[str, Any]:
        bool_value = value.lower() in ("true", "1")
        with self._lock:
            previous = self._feature_flags.get(name)
            self._feature_flags[name] = bool_value
            rec = self._audit("feature_flag", name, value, identity, True,
                              previous_state={"enabled": previous}, new_state={"enabled": bool_value})
            _log.warning("[CTRL] Feature flag %s=%s by %s", name, bool_value, identity)
            if self._state_callback:
                self._state_callback(f"feature_flag/{name}", {"enabled": bool_value})
            return {"success": True, "action_id": rec.action_id, "flag": name, "enabled": bool_value, "previous": previous}


# ── Legacy helpers ────────────────────────────────────────────────────────────

def _check_token(request: Any, token: str | None) -> None:
    """Raise 401 if token is configured and request header doesn't match."""
    if not token:
        return
    header = request.headers.get("x-admin-token", "")
    if header != token:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Token")


def _get_identity(request: Any) -> str:
    """Extract operator identity from request header."""
    return request.headers.get("x-operator-identity", "").strip() or "anonymous"


def _get_client_ip(request: Any) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _require_permission(role_manager: Any, identity: str, permission: str) -> None:
    """Check RBAC permission. Raises 403 if denied."""
    if role_manager is None:
        return
    try:
        role_manager.check(identity, permission)
    except Exception as exc:
        raise HTTPException(status_code=403, detail=str(exc))


def _legacy_audit_log(
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
        except Exception:
            _log.warning("[ADMIN] audit_logger.log_event failed", exc_info=True)


# ── FastAPI App Factory (legacy API) ──────────────────────────────────────────

def create_control_plane_app(
    cfg: dict[str, Any] | None = None,
    server: ControlPlaneServer | None = None,
    rbac: Any | None = None,
    auth: Any | None = None,
    # Legacy ref parameters (backward compat)
    mode_manager_ref: Any = None,
    wal_ref: Any = None,
    certifier_ref: Any = None,
    invariant_engine_ref: Any = None,
    role_manager_ref: Any = None,
    audit_logger_ref: Any = None,
    halt_event_ref: Any = None,
    strategy_registry_ref: Any = None,
    asset_registry_ref: Any = None,
    feature_flags_ref: Any = None,
    model_registry_ref: Any = None,
    config_reload_ref: Any = None,
) -> Any:
    """Create a FastAPI app for the admin control plane.

    Supports both legacy API (with _ref parameters for backward compat)
    and new API (with server/rbac/auth params).

    Legacy endpoints use the _ref parameters directly as closure captures.
    New-style endpoints use the ControlPlaneServer class.
    """
    if not _HAVE_FASTAPI:
        raise RuntimeError("fastapi is not installed — cannot create admin control plane")

    c = cfg or {}
    token = str(c.get("admin_control_plane_auth_token", "")) or os.environ.get("OPBUYING_ADMIN_TOKEN", "")

    # Use new-style server or create one
    _server = server or ControlPlaneServer(config=c)

    # Wire RBAC
    if rbac is not None:
        _rbac = rbac
    else:
        from core.control_plane.rbac import ControlRBAC
        _rbac = ControlRBAC()
        _rbac.load_from_config(c)

    # Wire auth
    if auth is not None:
        _auth = auth
    else:
        from core.control_plane.admin_auth import AdminAuth
        _auth = AdminAuth(
            auth_token=token,
            token_ttl_seconds=int(c.get("admin_token_ttl_seconds", 3600)),
        )

    app = FastAPI(
        title="AD-KIYU Admin Control Plane",
        version=_VERSION,
        docs_url="/control/docs",
        redoc_url=None,
    )

    # ── Auth dependency for new endpoints ────────────────────────────────────

    def _resolve_identity(authorization: str | None) -> str:
        if not _auth.has_auth_enabled:
            return "local"
        token_obj = _auth.authenticate_request(authorization)
        if token_obj is None:
            raise HTTPException(status_code=401, detail="Unauthorized: invalid or expired token")
        return token_obj.identity

    def _check_permission(identity: str, endpoint: str) -> None:
        allowed, reason = _rbac.check_endpoint(identity, endpoint)
        if not allowed:
            _log.warning("[CTRL] %s denied for %s on %s", endpoint, identity, reason)
            raise HTTPException(status_code=403, detail=reason)

    # =========================================================================
    # LEGACY ENDPOINTS — backward compat with old admin_control_plane.py API
    # =========================================================================

    # ── Mode ─────────────────────────────────────────────────────────────────

    @app.get("/mode")
    async def get_mode(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "view_state")
        if mode_manager_ref is None:
            return {"mode": "unavailable", "detail": "No ModeManager reference provided"}
        try:
            return {"mode": str(mode_manager_ref.current_mode)}
        except Exception as e:
            return {"mode": "error", "detail": str(e)}

    @app.post("/mode/{target}")
    async def set_mode(target: str, request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "modify_config")
        if mode_manager_ref is None:
            raise HTTPException(status_code=503, detail="ModeManager not wired")
        try:
            from core.operating_mode import OperatingMode
            new_mode = OperatingMode(target.upper())
            mode_manager_ref.set_mode(new_mode, reason="admin override", authorized_by=identity)
            _log.warning("[ADMIN] Mode set to %s by %s", new_mode, identity)
            _legacy_audit_log(audit_logger_ref, "mode_change", "operating_mode", "set",
                              details={"target": target, "mode": str(new_mode)},
                              user_id=identity, ip_address=_get_client_ip(request))
            return {"mode": str(new_mode), "status": "applied"}
        except (ValueError, Exception) as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── WAL ──────────────────────────────────────────────────────────────────

    @app.get("/wal")
    async def get_wal(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "view_state")
        if wal_ref is None:
            return {"wal": "unavailable", "detail": "No WALJournal reference provided"}
        try:
            pending = wal_ref.get_pending() if hasattr(wal_ref, "get_pending") else []
            committed = wal_ref.get_unsettled() if hasattr(wal_ref, "get_unsettled") else []
            status_counts = wal_ref.count_by_status() if hasattr(wal_ref, "count_by_status") else {}
            return {
                "total": len(pending) + len(committed) + status_counts.get("FAILED", 0),
                "pending": len(pending), "committed": len(committed),
                "failed": status_counts.get("FAILED", 0),
                "pending_intents": [
                    {"id": str(i.intent_id), "action": str(i.action), "created": str(i.created_ts)}
                    for i in pending[:50]
                ],
            }
        except Exception as e:
            return {"wal": "error", "detail": str(e)}

    # ── Cert ─────────────────────────────────────────────────────────────────

    @app.get("/cert")
    async def get_certs(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "view_state")
        if certifier_ref is None:
            return {"cert": "unavailable", "detail": "No IdempotencyCertifier reference provided"}
        try:
            status_counts = certifier_ref.count_by_status() if hasattr(certifier_ref, "count_by_status") else {}
            pending = certifier_ref.get_pending() if hasattr(certifier_ref, "get_pending") else []
            return {
                "total": sum(status_counts.values()),
                "by_status": {s: c for s, c in status_counts.items()},
                "pending": len(pending),
                "pending_certs": [
                    {"id": c.execution_id, "status": c.status, "created": str(c.created_at)}
                    for c in pending[:50]
                ],
            }
        except Exception as e:
            return {"cert": "error", "detail": str(e)}

    # ── Invariants ───────────────────────────────────────────────────────────

    @app.get("/invariants")
    async def get_invariants(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "view_state")
        if invariant_engine_ref is None:
            return {"invariants": "unavailable", "detail": "No InvariantEngine reference provided"}
        try:
            if hasattr(invariant_engine_ref, "get_state"):
                return invariant_engine_ref.get_state()
            from core.invariants.engine import get_state as _get_engine_state
            return _get_engine_state()
        except Exception as e:
            return {"invariants": "error", "detail": str(e)}

    @app.post("/invariants/{name}/toggle")
    async def toggle_invariant(name: str, request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "modify_config")
        if invariant_engine_ref is None:
            raise HTTPException(status_code=503, detail="InvariantEngine not wired")
        try:
            if hasattr(invariant_engine_ref, "toggle_check"):
                new_state = invariant_engine_ref.toggle_check(name)
            else:
                from core.invariants.engine import toggle_check as _toggle_invariant
                new_state = _toggle_invariant(name)
            _legacy_audit_log(audit_logger_ref, "invariant_toggle", f"invariant:{name}", "toggle",
                              details={"name": name, "enabled": new_state},
                              user_id=identity, ip_address=_get_client_ip(request))
            return {"invariant": name, "enabled": new_state, "status": "toggled"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── Kill-switch (legacy) ─────────────────────────────────────────────────

    @app.post("/control/halt")
    async def halt_trading(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "halt_trading")
        if halt_event_ref is None:
            raise HTTPException(status_code=503, detail="HaltEvent not wired")
        try:
            halt_event_ref.set()
            _log.warning("[ADMIN] Trading halted by %s", identity)
            _legacy_audit_log(audit_logger_ref, "kill_switch", "trading", "halt",
                              user_id=identity, ip_address=_get_client_ip(request))
            return {"status": "halted"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/control/resume")
    async def resume_trading(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "halt_trading")
        if halt_event_ref is None:
            raise HTTPException(status_code=503, detail="HaltEvent not wired")
        try:
            halt_event_ref.clear()
            _log.warning("[ADMIN] Trading resumed by %s", identity)
            _legacy_audit_log(audit_logger_ref, "kill_switch", "trading", "resume",
                              user_id=identity, ip_address=_get_client_ip(request))
            return {"status": "resumed"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/control/status")
    async def control_status(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "view_state")
        halted = halt_event_ref.is_set() if halt_event_ref is not None else None
        return {"halted": halted}

    # ── Strategy toggles (legacy) ────────────────────────────────────────────

    @app.get("/strategies")
    async def list_strategies(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "view_state")
        if strategy_registry_ref is None:
            return {"strategies": "unavailable", "detail": "No strategy registry wired"}
        try:
            items = dict(strategy_registry_ref.items()) if hasattr(strategy_registry_ref, "items") else {}
            return {"strategies": items}
        except Exception as e:
            return {"strategies": "error", "detail": str(e)}

    @app.post("/strategies/{name}/toggle")
    async def toggle_strategy(name: str, request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "toggle_strategies")
        if strategy_registry_ref is None:
            raise HTTPException(status_code=503, detail="No strategy registry wired")
        try:
            current = bool(strategy_registry_ref.get(name, False))
            new_val = not current
            strategy_registry_ref[name] = new_val
            _legacy_audit_log(audit_logger_ref, "strategy_toggle", f"strategy:{name}", "toggle",
                              details={"name": name, "enabled": new_val},
                              user_id=identity, ip_address=_get_client_ip(request))
            return {"strategy": name, "enabled": new_val}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── Asset toggles (legacy) ───────────────────────────────────────────────

    @app.get("/assets")
    async def list_assets(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "view_state")
        if asset_registry_ref is None:
            return {"assets": "unavailable", "detail": "No asset registry wired"}
        try:
            items = dict(asset_registry_ref.items()) if hasattr(asset_registry_ref, "items") else {}
            return {"assets": items}
        except Exception as e:
            return {"assets": "error", "detail": str(e)}

    @app.post("/assets/{name}/toggle")
    async def toggle_asset(name: str, request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "toggle_strategies")
        if asset_registry_ref is None:
            raise HTTPException(status_code=503, detail="No asset registry wired")
        try:
            current = bool(asset_registry_ref.get(name, False))
            new_val = not current
            asset_registry_ref[name] = new_val
            _legacy_audit_log(audit_logger_ref, "asset_toggle", f"asset:{name}", "toggle",
                              details={"name": name, "enabled": new_val},
                              user_id=identity, ip_address=_get_client_ip(request))
            return {"asset": name, "enabled": new_val}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── Feature flags (legacy) ───────────────────────────────────────────────

    @app.get("/features")
    async def list_features(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "view_state")
        if feature_flags_ref is None:
            return {"features": "unavailable", "detail": "No feature flags wired"}
        try:
            items = dict(feature_flags_ref.items()) if hasattr(feature_flags_ref, "items") else {}
            return {"features": items}
        except Exception as e:
            return {"features": "error", "detail": str(e)}

    @app.post("/features/{name}")
    async def set_feature(name: str, request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "modify_config")
        if feature_flags_ref is None:
            raise HTTPException(status_code=503, detail="No feature flags wired")
        try:
            body = await request.json()
            enabled = bool(body.get("enabled", True))
            feature_flags_ref[name] = enabled
            _legacy_audit_log(audit_logger_ref, "feature_toggle", f"feature:{name}", "set",
                              details={"name": name, "enabled": enabled},
                              user_id=identity, ip_address=_get_client_ip(request))
            return {"feature": name, "enabled": enabled}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── AI model selection (legacy) ──────────────────────────────────────────

    @app.get("/models")
    async def list_models(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "view_state")
        if model_registry_ref is None:
            return {"models": "unavailable", "detail": "No model registry wired"}
        try:
            if hasattr(model_registry_ref, "list_all"):
                records = model_registry_ref.list_all()
                return {"models": [
                    {"model_id": r.model_id, "name": r.name, "version": r.version,
                     "status": r.status, "created_ts": r.created_ts}
                    for r in records
                ]}
            return {"models": "ok", "detail": "list_all not available"}
        except Exception as e:
            return {"models": "error", "detail": str(e)}

    @app.post("/models/{model_id}/select")
    async def select_model(model_id: str, request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "deploy_models")
        if model_registry_ref is None:
            raise HTTPException(status_code=503, detail="No model registry wired")
        try:
            if hasattr(model_registry_ref, "update_status"):
                model_registry_ref.update_status(model_id, "ACTIVE")
            else:
                raise HTTPException(status_code=501, detail="Model selection not supported by registry")
            _legacy_audit_log(audit_logger_ref, "model_select", f"model:{model_id}", "select",
                              details={"model_id": model_id},
                              user_id=identity, ip_address=_get_client_ip(request))
            return {"model": model_id, "status": "selected"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── Broker summary (legacy) ──────────────────────────────────────────────

    @app.get("/broker")
    async def get_broker_summary(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "view_state")
        mode_str = str(mode_manager_ref.current_mode) if mode_manager_ref else "unavailable"
        return {"operating_mode": mode_str}

    # ── Audit log (legacy) ───────────────────────────────────────────────────

    @app.get("/audit")
    async def get_audit_log(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "view_logs")
        limit = int(request.query_params.get("limit", 100))
        with _AUDIT_LOCK:
            events = list(_AUDIT_EVENTS)[-limit:]
        return {"events": events, "total": len(events)}

    # ── RBAC admin (legacy) ──────────────────────────────────────────────────

    @app.get("/roles")
    async def list_roles(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "view_state")
        if role_manager_ref is None:
            return {"roles": "unavailable", "detail": "No RoleManager wired"}
        try:
            assignments = role_manager_ref.list_assignments() if hasattr(role_manager_ref, "list_assignments") else {}
            return {"roles": assignments}
        except Exception as e:
            return {"roles": "error", "detail": str(e)}

    @app.post("/roles/{operator}")
    async def assign_role(operator: str, request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "modify_config")
        if role_manager_ref is None:
            raise HTTPException(status_code=503, detail="No RoleManager wired")
        try:
            body = await request.json()
            role = str(body.get("role", "observer"))
            role_manager_ref.assign(operator, role)
            _legacy_audit_log(audit_logger_ref, "role_assign", f"role:{operator}", "assign",
                              details={"operator": operator, "role": role},
                              user_id=identity, ip_address=_get_client_ip(request))
            return {"operator": operator, "role": role}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── Config reload (legacy) ───────────────────────────────────────────────

    @app.post("/config/reload")
    async def reload_config(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "modify_config")
        if config_reload_ref is None:
            return {"status": "unavailable", "detail": "No config reload handler registered"}
        try:
            result = config_reload_ref()
            _legacy_audit_log(audit_logger_ref, "config_reload", "config", "reload",
                              details={"result": str(result)},
                              user_id=identity, ip_address=_get_client_ip(request))
            return {"status": "ok", "detail": "Config reloaded", "result": result}
        except Exception as e:
            _log.exception("Config reload failed")
            return {"status": "error", "detail": str(e)}

    # ── Root health (legacy) ─────────────────────────────────────────────────

    @app.get("/")
    async def root():
        return {
            "service": "ad-kiyu-admin-control-plane",
            "status": "running",
            "version": _VERSION,
            "refs": {
                "mode_manager": mode_manager_ref is not None,
                "wal": wal_ref is not None,
                "certifier": certifier_ref is not None,
                "invariant_engine": invariant_engine_ref is not None,
                "role_manager": role_manager_ref is not None,
                "audit_logger": audit_logger_ref is not None,
                "halt_event": halt_event_ref is not None,
                "strategy_registry": strategy_registry_ref is not None,
                "asset_registry": asset_registry_ref is not None,
                "feature_flags": feature_flags_ref is not None,
                "model_registry": model_registry_ref is not None,
                "config_reload": config_reload_ref is not None,
            },
        }

    # =========================================================================
    # NEW ENDPOINTS — v2 style with ControlPlaneServer + JWT auth
    # =========================================================================

    @app.post("/control/auth/login")
    def login(
        identity: str = "",
        role: str = "observer",
        authorization: str | None = Header(default=None),
    ) -> dict:
        if not identity and not _auth.has_auth_enabled:
            identity = "local"
        elif not identity:
            token_obj = _auth.authenticate_request(authorization)
            if token_obj is not None:
                identity = token_obj.identity
                role = token_obj.role.value
            else:
                raise HTTPException(status_code=401, detail="Authentication required")
        try:
            jwt = _auth.create_token(identity, role)
            return {"token": jwt, "identity": identity, "role": role}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/control/state")
    def get_state(authorization: str | None = Header(default=None)) -> dict:
        identity = _resolve_identity(authorization)
        _check_permission(identity, "control_state")
        return _server.control_state()

    @app.get("/control/audit")
    def get_audit(
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ) -> list:
        identity = _resolve_identity(authorization)
        _check_permission(identity, "control_audit")
        return _server.control_audit(limit=limit)

    @app.post("/control/kill")
    def kill(
        reason: str = "Manual kill via control plane",
        authorization: str | None = Header(default=None),
    ) -> dict:
        identity = _resolve_identity(authorization)
        _check_permission(identity, "control_kill")
        return _server.control_kill(identity, reason=reason)

    @app.post("/control/strategy/{name}/{action}")
    def strategy_control(
        name: str, action: str,
        authorization: str | None = Header(default=None),
    ) -> dict:
        identity = _resolve_identity(authorization)
        _check_permission(identity, f"control_strategy_{action}")
        return _server.control_strategy(name, action, identity)

    @app.post("/control/asset_class/{asset_class}/{action}")
    def asset_control(
        asset_class: str, action: str,
        authorization: str | None = Header(default=None),
    ) -> dict:
        identity = _resolve_identity(authorization)
        _check_permission(identity, f"control_asset_{action}")
        return _server.control_asset_class(asset_class, action, identity)

    @app.post("/control/capital/{amount}")
    def set_capital(
        amount: str,
        authorization: str | None = Header(default=None),
    ) -> dict:
        identity = _resolve_identity(authorization)
        _check_permission(identity, "control_capital")
        return _server.control_capital(amount, identity)

    @app.post("/control/risk_limit/{name}/{value}")
    def set_risk_limit(
        name: str, value: str,
        authorization: str | None = Header(default=None),
    ) -> dict:
        identity = _resolve_identity(authorization)
        _check_permission(identity, "control_risk_limit")
        return _server.control_risk_limit(name, value, identity)

    @app.post("/control/ai_model/{name}/{action}")
    def ai_model_control(
        name: str, action: str,
        authorization: str | None = Header(default=None),
    ) -> dict:
        identity = _resolve_identity(authorization)
        _check_permission(identity, "control_ai_model")
        return _server.control_ai_model(name, action, identity)

    @app.post("/control/feature_flag/{name}/{value}")
    def set_feature_flag(
        name: str, value: str,
        authorization: str | None = Header(default=None),
    ) -> dict:
        identity = _resolve_identity(authorization)
        _check_permission(identity, "control_feature_flag")
        return _server.control_feature_flag(name, value, identity)

    return app


# ── Server launcher ───────────────────────────────────────────────────────────

def maybe_start_control_plane(
    cfg: dict[str, Any],
    # Legacy ref parameters
    mode_manager: Any = None,
    wal: Any = None,
    certifier: Any = None,
    invariant_engine: Any = None,
    role_manager: Any = None,
    audit_logger: Any = None,
    halt_event: Any = None,
    strategy_registry: Any = None,
    asset_registry: Any = None,
    feature_flags: Any = None,
    model_registry: Any = None,
    config_reload: Any = None,
    # New-style callbacks
    halt_callback: Callable[[str], None] | None = None,
    state_callback: Callable[[str, Any], None] | None = None,
) -> threading.Thread | None:
    """Start the admin control plane in a daemon thread if enabled.

    All refs are optional — endpoints gracefully degrade when a reference is None.
    Supports both legacy ref parameters and new-style callbacks.

    Returns the thread handle, or None if disabled / fastapi unavailable.
    """
    c = cfg or {}
    if not c.get("admin_control_plane_enabled", False):
        _log.info("Admin control plane disabled (admin_control_plane_enabled=false)")
        return None
    if not _HAVE_FASTAPI:
        _log.info("Admin control plane requires fastapi — install with: pip install fastapi uvicorn")
        return None
    if not _HAVE_UVICORN:
        _log.info("Admin control plane requires uvicorn — install with: pip install fastapi uvicorn")
        return None

    host = str(c.get("admin_control_plane_host", _DEFAULT_HOST))
    port = int(c.get("admin_control_plane_port", _DEFAULT_PORT))

    # Create new-style ControlPlaneServer with halt callback
    _server = ControlPlaneServer(config=c)
    if halt_callback:
        _server.register_halt_callback(halt_callback)
    if state_callback:
        _server.register_state_callback(state_callback)

    # Wire auth and rbac
    from core.control_plane.admin_auth import AdminAuth
    from core.control_plane.rbac import ControlRBAC

    auth_token = str(c.get("admin_control_plane_auth_token", ""))
    _auth = AdminAuth(auth_token=auth_token)
    _rbac = ControlRBAC()
    _rbac.load_from_config(c)

    app = create_control_plane_app(
        cfg=c, server=_server, rbac=_rbac, auth=_auth,
        # Pass legacy refs through
        mode_manager_ref=mode_manager,
        wal_ref=wal,
        certifier_ref=certifier,
        invariant_engine_ref=invariant_engine,
        role_manager_ref=role_manager,
        audit_logger_ref=audit_logger,
        halt_event_ref=halt_event,
        strategy_registry_ref=strategy_registry,
        asset_registry_ref=asset_registry,
        feature_flags_ref=feature_flags,
        model_registry_ref=model_registry,
        config_reload_ref=config_reload,
    )

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    srv = uvicorn.Server(config)
    t = threading.Thread(target=srv.run, daemon=True, name="control_plane")
    t.start()
    _log.info("[CTRL] Admin control plane started at http://%s:%d", host, port)
    return t
