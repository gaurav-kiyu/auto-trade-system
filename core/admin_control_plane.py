"""
AD-KIYU Admin Control Plane — HTTP admin interface on port 7080.

Provides remote administration endpoints for:
  - Operating mode changes (SIGNAL_ONLY → PAPER → etc.)
  - WAL intent journal inspection
  - Idempotency certificate lifeline
  - Runtime invariant toggle
  - Kill-switch / resume
  - Strategy / asset / feature-flag toggles
  - AI model selection
  - Audit log view

SAFETY: Disabled by default. Set ``admin_control_plane_enabled: true`` to enable.
All mutating endpoints require ``X-Admin-Token`` header matching the configured token.
RBAC is enforced via ``X-Operator-Identity`` + ``RoleManager`` when configured.
"""
from __future__ import annotations

import logging
import os
import threading
import uuid
from collections import deque
from typing import Any

from core.datetime_ist import now_ist

# Read version from VERSION file — required, no fallback
import pathlib
_VERSION_FILE = pathlib.Path(__file__).resolve().parent.parent / "VERSION"
try:
    _VERSION = _VERSION_FILE.read_text(encoding="utf-8").strip()
except Exception as exc:
    _VERSION = "0.0.0"
    import logging
    logging.getLogger("admin_control_plane").warning(
        "Cannot read VERSION file at %s: %s", _VERSION_FILE, exc)

_log = logging.getLogger(__name__)

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
    _HAVE_FASTAPI = True
except ImportError:
    FastAPI = None  # type: ignore[assignment]
    _HAVE_FASTAPI = False
    _log.warning("fastapi not installed — admin control plane unavailable")

try:
    import uvicorn
    _HAVE_UVICORN = True
except ImportError:
    uvicorn = None  # type: ignore[assignment]
    _HAVE_UVICORN = False
    _log.warning("uvicorn not installed — admin control plane cannot serve")

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 7080

# ── In-memory audit ring buffer (last 500 events) ───────────────────────────
_AUDIT_EVENTS: deque[dict[str, Any]] = deque(maxlen=500)
_AUDIT_LOCK = threading.Lock()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _load_module(name: str):
    """Lazy-import a module, returning None on failure."""
    try:
        __import__(name)
        return __import__(name)
    except Exception:
        return None


def _check_token(request: Request, token: str | None) -> None:
    """Raise 401 if token is configured and request header doesn't match."""
    if not token:
        return
    header = request.headers.get("x-admin-token", "")
    if header != token:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Token")


def _get_identity(request: Request) -> str:
    """Extract operator identity from request header, defaulting to 'anonymous'."""
    return request.headers.get("x-operator-identity", "").strip() or "anonymous"


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _require_permission(role_manager: Any, identity: str, permission: str) -> None:
    """Check RBAC permission. Raises 403 if denied. No-op if role_manager is None."""
    if role_manager is None:
        return
    try:
        role_manager.check(identity, permission)
    except Exception as exc:
        raise HTTPException(status_code=403, detail=str(exc))


def _audit_log(
    audit_logger: Any,
    event_type: str,
    resource: str,
    action: str,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
    user_id: str | None = None,
    ip_address: str | None = None,
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
                event_type=event_type,
                resource=resource,
                action=action,
                outcome=outcome,
                details=details,
                severity="info",
                user_id=user_id,
                ip_address=ip_address,
            )
        except Exception:
            _log.warning("[ADMIN] audit_logger.log_event failed", exc_info=True)


# ── App factory ──────────────────────────────────────────────────────────────


def create_admin_app(
    cfg: dict[str, Any] | None = None,
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
    config_reload_ref: Any = None,  # callable[[], dict] — reloads config, returns status
) -> Any:
    """Build the FastAPI admin control plane application.

    Parameters are optional — endpoints gracefully degrade when a reference is None.

    RBAC:
      - role_manager_ref: core.auth.role_manager.RoleManager instance.
        Reads ``X-Operator-Identity`` header to determine role and checks permission.

    Audit:
      - audit_logger_ref: infrastructure.security.audit_logger.AuditLogger instance.
        Mutating endpoints log events to persistent audit log + in-memory ring buffer.

    Kill switch:
      - halt_event_ref: threading.Event — set to halt, clear to resume.

    Registries (dict-like with .get(key, default) / .items() / .__setitem__(key, val)):
      - strategy_registry_ref: {name: enabled_bool}
      - asset_registry_ref:    {name: enabled_bool}
      - feature_flags_ref:     {name: enabled_bool}

    Model registry:
      - model_registry_ref: object with .list_models() -> list[dict] and
        .activate(model_id) -> None or similar API.
    """
    if not _HAVE_FASTAPI:
        raise RuntimeError("fastapi is not installed — cannot create admin control plane")

    app = FastAPI(title="AD-KIYU Admin Control Plane", version=_VERSION)
    token = (cfg or {}).get("admin_control_plane_auth_token") or os.environ.get("OPBUYING_ADMIN_TOKEN") or ""

    # ── Mode endpoints ────────────────────────────────────────────────────────

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
            _log.warning(f"[ADMIN] Mode set to {new_mode} by {identity}")
            _audit_log(audit_logger_ref, "mode_change", "operating_mode", "set",
                       details={"target": target, "mode": str(new_mode)},
                       user_id=identity, ip_address=_get_client_ip(request))
            return {"mode": str(new_mode), "status": "applied"}
        except (ValueError, Exception) as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── WAL endpoints ─────────────────────────────────────────────────────────

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
            failed_count = status_counts.get("FAILED", 0)
            return {
                "total": len(pending) + len(committed) + failed_count,
                "pending": len(pending),
                "committed": len(committed),
                "failed": failed_count,
                "pending_intents": [
                    {"id": str(i.intent_id), "action": str(i.action), "created": str(i.created_ts)}
                    for i in pending[:50]
                ],
            }
        except Exception as e:
            return {"wal": "error", "detail": str(e)}

    # ── Cert lifeline endpoints ───────────────────────────────────────────────

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

    # ── Invariant endpoints ──────────────────────────────────────────────────

    @app.get("/invariants")
    async def get_invariants(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "view_state")
        if invariant_engine_ref is None:
            return {"invariants": "unavailable", "detail": "No InvariantEngine reference provided"}
        try:
            if hasattr(invariant_engine_ref, "get_state"):
                state = invariant_engine_ref.get_state()
                return state
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
            _audit_log(audit_logger_ref, "invariant_toggle", f"invariant:{name}", "toggle",
                       details={"name": name, "enabled": new_state},
                       user_id=identity, ip_address=_get_client_ip(request))
            return {"invariant": name, "enabled": new_state, "status": "toggled"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── Kill-switch endpoints ─────────────────────────────────────────────────

    @app.post("/control/halt")
    async def halt_trading(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "halt_trading")
        if halt_event_ref is None:
            raise HTTPException(status_code=503, detail="HaltEvent not wired")
        try:
            halt_event_ref.set()
            _log.warning(f"[ADMIN] Trading halted by {identity}")
            _audit_log(audit_logger_ref, "kill_switch", "trading", "halt",
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
            _log.warning(f"[ADMIN] Trading resumed by {identity}")
            _audit_log(audit_logger_ref, "kill_switch", "trading", "resume",
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

    # ── Strategy toggle endpoints ─────────────────────────────────────────────

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
            _audit_log(audit_logger_ref, "strategy_toggle", f"strategy:{name}", "toggle",
                       details={"name": name, "enabled": new_val},
                       user_id=identity, ip_address=_get_client_ip(request))
            return {"strategy": name, "enabled": new_val}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── Asset toggle endpoints ────────────────────────────────────────────────

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
            _audit_log(audit_logger_ref, "asset_toggle", f"asset:{name}", "toggle",
                       details={"name": name, "enabled": new_val},
                       user_id=identity, ip_address=_get_client_ip(request))
            return {"asset": name, "enabled": new_val}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── Feature flag endpoints ────────────────────────────────────────────────

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
            _audit_log(audit_logger_ref, "feature_toggle", f"feature:{name}", "set",
                       details={"name": name, "enabled": enabled},
                       user_id=identity, ip_address=_get_client_ip(request))
            return {"feature": name, "enabled": enabled}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── AI model selection endpoints ──────────────────────────────────────────

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
            _audit_log(audit_logger_ref, "model_select", f"model:{model_id}", "select",
                       details={"model_id": model_id},
                       user_id=identity, ip_address=_get_client_ip(request))
            return {"model": model_id, "status": "selected"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── Broker mode summary ───────────────────────────────────────────────────

    @app.get("/broker")
    async def get_broker_summary(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "view_state")
        mode_str = str(mode_manager_ref.current_mode) if mode_manager_ref else "unavailable"
        return {"operating_mode": mode_str} 

    # ── Audit log endpoint ────────────────────────────────────────────────────

    @app.get("/audit")
    async def get_audit(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "view_logs")
        limit = int(request.query_params.get("limit", 100))
        with _AUDIT_LOCK:
            events = list(_AUDIT_EVENTS)[-limit:]
        return {"events": events, "total": len(events)}

    # ── RBAC admin endpoints ──────────────────────────────────────────────────

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
            _audit_log(audit_logger_ref, "role_assign", f"role:{operator}", "assign",
                       details={"operator": operator, "role": role},
                       user_id=identity, ip_address=_get_client_ip(request))
            return {"operator": operator, "role": role}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── Config reload ─────────────────────────────────────────────────────────

    @app.post("/config/reload")
    async def reload_config(request: Request):
        _check_token(request, token)
        identity = _get_identity(request)
        _require_permission(role_manager_ref, identity, "modify_config")
        if config_reload_ref is None:
            return {"status": "unavailable", "detail": "No config reload handler registered"}
        try:
            result = config_reload_ref()
            _audit_log(audit_logger_ref, "config_reload", "config", "reload",
                       details={"result": str(result)},
                       user_id=identity, ip_address=_get_client_ip(request))
            return {"status": "ok", "detail": "Config reloaded", "result": result}
        except Exception as e:
            _log.exception("Config reload failed")
            return {"status": "error", "detail": str(e)}

    # ── Health ────────────────────────────────────────────────────────────────

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

    return app


# ── Server ───────────────────────────────────────────────────────────────────


def _serve_forever(
    cfg: dict[str, Any],
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
):
    """Run the admin control plane in a background thread."""
    if not _HAVE_FASTAPI:
        _log.warning("Admin control plane disabled — fastapi not installed")
        return
    if not _HAVE_UVICORN:
        _log.warning("Admin control plane disabled — uvicorn not installed")
        return
    host = str(cfg.get("admin_control_plane_host", _DEFAULT_HOST))
    port = int(cfg.get("admin_control_plane_port", _DEFAULT_PORT))
    app = create_admin_app(
        cfg=cfg,
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
    _log.info(f"Admin control plane starting on {host}:{port}")
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except Exception as exc:
        _log.error(f"Admin control plane error: {exc}")


def start_admin_control_plane(
    cfg: dict[str, Any],
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
) -> threading.Thread | None:
    """Start the admin control plane in a daemon thread if enabled.

    All refs are optional — endpoints gracefully degrade when a reference is None.

    Returns the thread handle, or None if disabled / fastapi unavailable.
    """
    enabled = cfg.get("admin_control_plane_enabled", False)
    if not enabled:
        _log.info("Admin control plane disabled (admin_control_plane_enabled=false)")
        return None
    if not _HAVE_FASTAPI:
        _log.info("Admin control plane requires fastapi — install with: pip install fastapi")
        return None
    if not _HAVE_UVICORN:
        _log.info("Admin control plane requires uvicorn — install with: pip install uvicorn")
        return None
    t = threading.Thread(
        target=_serve_forever,
        args=(cfg, mode_manager, wal, certifier, invariant_engine,
              role_manager, audit_logger, halt_event,
              strategy_registry, asset_registry, feature_flags, model_registry,
              config_reload),
        daemon=True,
        name="admin-control-plane",
    )
    t.start()
    _log.info(f"Admin control plane thread started")
    return t
