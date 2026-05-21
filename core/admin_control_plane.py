"""
AD-KIYU Admin Control Plane — HTTP admin interface on port 7080.

Provides remote administration endpoints for:
  - Operating mode changes (SIGNAL_ONLY → PAPER → etc.)
  - WAL intent journal inspection
  - Idempotency certificate lifeline
  - Runtime invariant toggle

SAFETY: Disabled by default. Set ``admin_control_plane_enabled: true`` to enable.
All mutating endpoints require ``X-Admin-Token`` header matching the configured token.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

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


# ── App factory ──────────────────────────────────────────────────────────────


def create_admin_app(
    cfg: dict[str, Any] | None = None,
    mode_manager_ref: Any = None,
    wal_ref: Any = None,
    certifier_ref: Any = None,
    invariant_engine_ref: Any = None,
) -> Any:
    """Build the FastAPI admin control plane application.

    Parameters are optional — endpoints gracefully degrade when a reference is None.
    """
    if not _HAVE_FASTAPI:
        raise RuntimeError("fastapi is not installed — cannot create admin control plane")

    app = FastAPI(title="AD-KIYU Admin Control Plane", version="2.51")
    token = (cfg or {}).get("admin_control_plane_auth_token") or os.environ.get("OPBUYING_ADMIN_TOKEN") or ""

    # ── Mode endpoints ────────────────────────────────────────────────────────

    @app.get("/mode")
    async def get_mode(request: Request):
        _check_token(request, token)
        if mode_manager_ref is None:
            return {"mode": "unavailable", "detail": "No ModeManager reference provided"}
        try:
            return {"mode": str(mode_manager_ref.current_mode)}
        except Exception as e:
            return {"mode": "error", "detail": str(e)}

    @app.post("/mode/{target}")
    async def set_mode(target: str, request: Request):
        _check_token(request, token)
        if mode_manager_ref is None:
            raise HTTPException(status_code=503, detail="ModeManager not wired")
        try:
            from core.operating_mode import OperatingMode

            new_mode = OperatingMode(target.upper())
            mode_manager_ref.force_transition(new_mode)
            _log.warning(f"[ADMIN] Mode forced to {new_mode}")
            return {"mode": str(new_mode), "status": "applied"}
        except (ValueError, Exception) as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── WAL endpoints ─────────────────────────────────────────────────────────

    @app.get("/wal")
    async def get_wal(request: Request):
        _check_token(request, token)
        if wal_ref is None:
            return {"wal": "unavailable", "detail": "No WALJournal reference provided"}
        try:
            pending = wal_ref.get_intents_by_status("PENDING") if hasattr(wal_ref, "get_intents_by_status") else []
            committed = wal_ref.get_intents_by_status("COMMITTED") if hasattr(wal_ref, "get_intents_by_status") else []
            failed = wal_ref.get_intents_by_status("FAILED") if hasattr(wal_ref, "get_intents_by_status") else []
            return {
                "total": len(pending) + len(committed) + len(failed),
                "pending": len(pending),
                "committed": len(committed),
                "failed": len(failed),
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
        if certifier_ref is None:
            return {"cert": "unavailable", "detail": "No IdempotencyCertifier reference provided"}
        try:
            if hasattr(certifier_ref, "get_all_certificates"):
                certs = certifier_ref.get_all_certificates()
                return {
                    "total": len(certs),
                    "certificates": [
                        {"id": c.execution_id, "status": c.status, "created": str(c.created_ts)}
                        for c in certs[-100:]
                    ],
                }
            return {"cert": "ok", "detail": "get_all_certificates not available"}
        except Exception as e:
            return {"cert": "error", "detail": str(e)}

    # ── Invariant endpoints ──────────────────────────────────────────────────

    @app.get("/invariants")
    async def get_invariants(request: Request):
        _check_token(request, token)
        if invariant_engine_ref is None:
            return {"invariants": "unavailable", "detail": "No InvariantEngine reference provided"}
        try:
            if hasattr(invariant_engine_ref, "get_results"):
                results = invariant_engine_ref.get_results()
                return {
                    "checks": [
                        {"name": r.name, "passed": r.passed, "severity": str(r.severity)}
                        for r in results
                    ]
                }
            return {"invariants": "ok", "detail": "get_results not available"}
        except Exception as e:
            return {"invariants": "error", "detail": str(e)}

    @app.post("/invariants/{name}/toggle")
    async def toggle_invariant(name: str, request: Request):
        _check_token(request, token)
        if invariant_engine_ref is None:
            raise HTTPException(status_code=503, detail="InvariantEngine not wired")
        try:
            if hasattr(invariant_engine_ref, "toggle_check"):
                invariant_engine_ref.toggle_check(name)
                return {"invariant": name, "status": "toggled"}
            raise HTTPException(status_code=501, detail="toggle_check not available")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── Health ────────────────────────────────────────────────────────────────

    @app.get("/")
    async def root():
        return {
            "service": "ad-kiyu-admin-control-plane",
            "status": "running",
            "version": "2.51",
            "refs": {
                "mode_manager": mode_manager_ref is not None,
                "wal": wal_ref is not None,
                "certifier": certifier_ref is not None,
                "invariant_engine": invariant_engine_ref is not None,
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
) -> threading.Thread | None:
    """Start the admin control plane in a daemon thread if enabled.

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
        args=(cfg, mode_manager, wal, certifier, invariant_engine),
        daemon=True,
        name="admin-control-plane",
    )
    t.start()
    _log.info(f"Admin control plane thread started")
    return t
