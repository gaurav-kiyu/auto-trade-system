"""
Enterprise Web Dashboard — premium FastAPI + Jinja2 + Tailwind CSS UI.

Provides a world-class admin interface with full auth, RBAC, config management,
kill switch, and monitoring.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import secrets
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.auth.csrf import csrf_protection
from core.auth.dependencies import AuthDependencies
from core.auth.handler import AuthHandler
from core.auth.routes import create_auth_router

_log = logging.getLogger(__name__)

_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_PORT = 8765


def _freeze(obj: Any) -> Any:
    """Recursively freeze a dict/list into an immutable form.

    Converts all nested dicts to MappingProxyType (read-only views)
    and all nested lists to tuples. This prevents accidental mutation
    of shared config objects at runtime.
    """
    if isinstance(obj, dict):
        return MappingProxyType({k: _freeze(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return tuple(_freeze(v) for v in obj)
    if isinstance(obj, set):
        return frozenset(_freeze(v) for v in obj)
    return obj


class EnterpriseDashboard:
    """Enterprise-grade web dashboard with auth, RBAC, and admin UI."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        auth_handler: AuthHandler | None = None,
        state_path: str | None = None,
        db_path: str = "trades.db",
    ):
        self._cfg = dict(config or {})
        # Freeze config to prevent accidental mutation at runtime
        self._cfg_frozen = _freeze(self._cfg)
        self._state_path = state_path or self._cfg.get("trader_state_path", "trader_state.json")
        self._db_path = str(db_path or self._cfg.get("trades_db", "trades.db"))
        self._auth = auth_handler or AuthHandler(
            db_path=self._cfg.get("auth_db_path", "data/auth.db"),
            token_ttl=int(self._cfg.get("auth_token_ttl_seconds", 3600)),
        )
        self._auth_deps = AuthDependencies(self._auth)
        self._cookie_secure = str(self._cfg.get("web_dashboard_host", "0.0.0.0")) != "127.0.0.1"
        self._templates_dir = self._ensure_templates()
        self._templates = Jinja2Templates(directory=str(self._templates_dir))
        self._static_dir = self._ensure_static()

        # References to bot internals (wired externally)
        self._pause_event: threading.Event = threading.Event()
        self._signal_log: Any = None
        self._signal_queue: Any = None
        self._ws_feed_manager: Any = None
        self._rate_limiter: Any = None
        self._control_plane: Any = None
        self._bot_refs: dict[str, Any] = {}
        self._config_lock: threading.Lock = threading.Lock()

        # Create the FastAPI app
        self.app = self._create_app()

        # Start background session cleanup
        self._start_session_cleanup()

    @property
    def config(self) -> MappingProxyType:
        """Read-only frozen view of the active config."""
        return self._cfg_frozen

    def _start_session_cleanup(self) -> None:
        """Background thread to purge expired sessions every 15 minutes."""
        def _cleanup_loop():
            while True:
                time.sleep(900)
                try:
                    self._auth.purge_expired_sessions()
                except Exception as exc:
                    _log.warning("[DASH] Session cleanup error: %s", exc)
        t = threading.Thread(target=_cleanup_loop, daemon=True, name="session_cleanup")
        t.start()

    def _ensure_templates(self) -> Path:
        templates_dir = Path(__file__).resolve().parent.parent / "templates" / "enterprise"
        templates_dir.mkdir(parents=True, exist_ok=True)
        return templates_dir

    def _ensure_static(self) -> Path | None:
        """Create and return the static files directory if possible."""
        static_dir = Path(__file__).resolve().parent.parent / "static"
        try:
            static_dir.mkdir(parents=True, exist_ok=True)
            return static_dir
        except Exception as e:
            _log.debug("[DASH] Cannot create static dir: %s", e)
            return None

    def wire_bot_refs(self, **refs: Any) -> None:
        """Wire external bot references."""
        self._bot_refs.update(refs)
        if "pause_event" in refs:
            self._pause_event = refs["pause_event"]
        if "signal_log" in refs:
            self._signal_log = refs["signal_log"]
        if "signal_queue" in refs:
            self._signal_queue = refs["signal_queue"]
        if "ws_feed_manager" in refs:
            self._ws_feed_manager = refs["ws_feed_manager"]
        if "rate_limiter" in refs:
            self._rate_limiter = refs["rate_limiter"]
        if "control_plane" in refs:
            self._control_plane = refs["control_plane"]

    def _create_app(self) -> FastAPI:
        self._startup_ts = time.time()

        # Register runtime invariant checks on startup
        try:
            from core.invariants.checks import register_all as _register_invariants
            _register_invariants()
            _log.info("[DASH] Runtime invariant checks registered")
        except Exception as exc:
            _log.debug("[DASH] Invariant registration skipped: %s", exc)

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            _log.info("[DASH] Enterprise dashboard started")
            yield
            _log.info("[DASH] Enterprise dashboard shutting down gracefully")

        app = FastAPI(
            title="OPB Enterprise Dashboard",
            version="2.53.0",
            docs_url="/api/docs",
            redoc_url="/api/redoc",
            openapi_tags=[
                {
                    "name": "Auth",
                    "description": "Authentication and session management — login, register, change password",
                },
                {
                    "name": "System",
                    "description": "System state, health, diagnostics, uptime, trades, signals — read-only observability",
                },
                {
                    "name": "Admin",
                    "description": "Admin-only operations — config management, kill switch, user management, self-test",
                },
                {
                    "name": "Risk",
                    "description": "Risk metrics — position concentration and exposure analysis",
                },
                {
                    "name": "Broker",
                    "description": "Broker connection status and adapter information",
                },
                {
                    "name": "ML",
                    "description": "ML model status — accuracy, drift detection, calibration",
                },
                {
                    "name": "Webhook",
                    "description": "External signal injection webhook for automated trading signals",
                },
                {
                    "name": "Charts",
                    "description": "Options chain visualization and market data charts",
                },
            ],
            lifespan=lifespan,
        )

        # Mount auth routes
        auth_router = create_auth_router(
            self._auth,
            self._auth_deps,
            cookie_secure=self._cookie_secure,
        )
        app.include_router(auth_router)

        # Mount static files if the directory exists
        if self._static_dir and self._static_dir.is_dir():
            try:
                app.mount("/static", StaticFiles(directory=str(self._static_dir)), name="static")
            except Exception as e:
                _log.warning("[DASH] Static files mount skipped: %s", e)

        # CSRF exempt paths
        csrf_protection.exempt("/api/auth/login")
        csrf_protection.exempt("/api/auth/logout")
        csrf_protection.exempt("/api/system/health/docker")
        csrf_protection.exempt("/signals/inject")
        csrf_protection.exempt("/static")
        csrf_protection.exempt("/api/system/self-test")
        csrf_protection.exempt("/api/docs")
        csrf_protection.exempt("/api/redoc")
        csrf_protection.exempt("/openapi.json")

        # ── Middleware: Security Headers ────────────────────────────────────────

        @app.middleware("http")
        async def security_headers_middleware(request: Request, call_next: Any):
            # Generate CSP nonce per-request
            nonce = secrets.token_hex(16)
            request.state.nonce = nonce
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            # HSTS: 1 year, include subdomains, preload — only on HTTPS
            # Check both direct scheme and X-Forwarded-Proto (for reverse proxy)
            forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
            is_secure = request.url.scheme == "https" or forwarded_proto == "https"
            if is_secure:
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
            # CSP: nonce-based for scripts, unsafe-inline for styles (Tailwind needs inline styles)
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                f"script-src 'self' 'nonce-{nonce}'; "
                "style-src 'self' 'unsafe-inline'; "
                "font-src 'self'; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "form-action 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'"
            )
            return response

        # ── API Rate Limiter ─────────────────────────────────────────────────

        _rate_limit_store: dict[str, list[float]] = {}
        _rate_limit_lock = threading.Lock()
        API_RATE_LIMIT = int(self._cfg.get("api_rate_limit_per_minute", 60))
        ADMIN_RATE_LIMIT = int(self._cfg.get("admin_api_rate_limit_per_minute", 20))

        def _check_rate_limit(ip: str, limit: int) -> bool:
            now = time.time()
            with _rate_limit_lock:
                attempts = _rate_limit_store.get(ip, [])
                attempts = [t for t in attempts if now - t < 60]
                if len(attempts) >= limit:
                    return False
                attempts.append(now)
                _rate_limit_store[ip] = attempts
            return True

        # ── Middleware: CORS ───────────────────────────────────────────────────

        allowed_origins = self._cfg.get("cors_allowed_origins", "")
        if allowed_origins:
            origins = [o.strip() for o in allowed_origins.split(",") if o.strip()]
            app.add_middleware(
                CORSMiddleware,
                allow_origins=origins,
                allow_credentials=True,
                allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
            )

        # ── Middleware: API Rate Limiting ──────────────────────────────────────

        @app.middleware("http")
        async def rate_limit_middleware(request: Request, call_next: Any):
            path = request.url.path
            if path.startswith("/api/") and not path.startswith("/api/system/health/docker"):
                ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "127.0.0.1").split(",")[0].strip()
                is_admin = path.startswith("/api/config") or path.startswith("/api/system/kill") or path.startswith("/api/system/resume") or path.startswith("/api/system/self-test") or path.startswith("/api/system/diagnostics")
                limit = ADMIN_RATE_LIMIT if is_admin else API_RATE_LIMIT
                if not _check_rate_limit(ip, limit):
                    return JSONResponse({"error": "Rate limit exceeded", "retry_after": 60}, status_code=429)
            response = await call_next(request)
            return response

        # ── Middleware: Request ID + Tracing ─────────────────────────────────────

        @app.middleware("http")
        async def request_id_middleware(request: Request, call_next: Any):
            request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:16])
            request.state.request_id = request_id
            request.state.request_start = time.time()
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            req_start = request.state.request_start
            elapsed_ms = int((time.time() - req_start) * 1000) if hasattr(request.state, 'request_start') else 0
            response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
            return response

        # ── Middleware: CSRF ────────────────────────────────────────────────────

        @app.middleware("http")
        async def csrf_middleware(request: Request, call_next: Any):
            await csrf_protection.validate(request)
            response = await call_next(request)
            # Ensure CSRF cookie is set on GET responses (if missing)
            try:
                await csrf_protection.ensure_cookie_set(request, response)
            except Exception as exc:
                _log.warning("[DASH] CSRF cookie set failed: %s", exc)
            return response

        # ── Error handlers ─────────────────────────────────────────────────────

        @app.exception_handler(403)
        async def forbidden_error(request: Request, exc: Any):
            nonce = getattr(request.state, 'nonce', '')
            _log.warning("[DASH] Forbidden: %s", exc)
            if "application/json" in request.headers.get("accept", ""):
                return JSONResponse({"error": "Forbidden", "code": 403}, status_code=403)
            return self._templates.TemplateResponse(
                request=request,
                name="error.html",
                context={"code": 403, "message": "Access denied — admin role required", "nonce": nonce},
                status_code=403,
            )

        @app.exception_handler(404)
        async def not_found(request: Request, exc: Any):
            nonce = getattr(request.state, 'nonce', '')
            if "application/json" in request.headers.get("accept", ""):
                return JSONResponse({"error": "Not found", "code": 404}, status_code=404)
            return self._templates.TemplateResponse(
                request=request,
                name="error.html",
                context={"code": 404, "message": "Page not found", "nonce": nonce},
                status_code=404,
            )

        @app.exception_handler(500)
        async def server_error(request: Request, exc: Any):
            nonce = getattr(request.state, 'nonce', '')
            _log.exception("[DASH] Unhandled error: %s", exc)
            if "application/json" in request.headers.get("accept", ""):
                return JSONResponse({"error": "Internal server error", "code": 500}, status_code=500)
            return self._templates.TemplateResponse(
                request=request,
                name="error.html",
                context={"code": 500, "message": "Internal server error", "nonce": nonce},
                status_code=500,
            )

        # ── HTML Routes ───────────────────────────────────────────────────────

        @app.get("/", response_class=HTMLResponse)
        async def root(request: Request):
            nonce = getattr(request.state, 'nonce', '')
            # Check if authenticated
            session_token = request.cookies.get("opb_session", "")
            user = None
            if session_token:
                token = self._auth.verify_session(session_token)
                if token:
                    user = self._auth.get_user_by_id(token.user_id)
            if user is None:
                return RedirectResponse(url="/login")
            return self._templates.TemplateResponse(
                request=request,
                name="dashboard.html",
                context={"user": user.to_dict(), "nonce": nonce},
            )

        @app.get("/login", response_class=HTMLResponse)
        async def login_page(request: Request):
            nonce = getattr(request.state, 'nonce', '')
            return self._templates.TemplateResponse(
                request=request,
                name="login.html",
                context={"nonce": nonce},
            )

        @app.get("/register", response_class=HTMLResponse)
        async def register_page(request: Request):
            nonce = getattr(request.state, 'nonce', '')
            return self._templates.TemplateResponse(
                request=request,
                name="register.html",
                context={"nonce": nonce},
            )

        # ── Helper: require admin role for HTML pages ──────────────────────────
        def _require_admin_page(request: Request):
            """Check session auth and admin role, return (user, error_response).

            Returns (user, None) if authorized, (None, error_response) otherwise.
            """
            session_token = request.cookies.get("opb_session", "")
            user = None
            if session_token:
                token = self._auth.verify_session(session_token)
                if token:
                    user = self._auth.get_user_by_id(token.user_id)
            if user is None:
                return None, RedirectResponse(url="/login")
            if user.role != "admin":
                nonce = getattr(request.state, 'nonce', '')
                return None, self._templates.TemplateResponse(
                    request=request,
                    name="error.html",
                    context={"code": 403, "message": "Admin access required", "nonce": nonce},
                    status_code=403,
                )
            return user, None

        @app.get("/admin/users", response_class=HTMLResponse)
        async def admin_users_page(request: Request):
            nonce = getattr(request.state, 'nonce', '')
            user, err = _require_admin_page(request)
            if err:
                return err
            return self._templates.TemplateResponse(
                request=request,
                name="admin_users.html",
                context={"user": user.to_dict(), "nonce": nonce},
            )

        @app.get("/admin/config", response_class=HTMLResponse)
        async def admin_config_page(request: Request):
            nonce = getattr(request.state, 'nonce', '')
            user, err = _require_admin_page(request)
            if err:
                return err
            return self._templates.TemplateResponse(
                request=request,
                name="admin_config.html",
                context={"user": user.to_dict(), "nonce": nonce},
            )

        @app.get("/admin/kill-switch", response_class=HTMLResponse)
        async def kill_switch_page(request: Request):
            nonce = getattr(request.state, 'nonce', '')
            user, err = _require_admin_page(request)
            if err:
                return err
            return self._templates.TemplateResponse(
                request=request,
                name="kill_switch.html",
                context={"user": user.to_dict(), "nonce": nonce},
            )

        # Dedicated pages redirect to SPA dashboard with anchor
        _redirect_pages = [
            ("/trading", "trading"),
            ("/signals", "signals"),
            ("/risk", "risk"),
            ("/broker", "broker"),
            ("/ml", "ml"),
            ("/health", "health"),
            ("/logs", "logs"),
            ("/system/state", "system-state"),
        ]
        for _p, _a in _redirect_pages:

            def _make_redirect(page_anchor: str):
                async def _redirect():
                    return RedirectResponse(url=f"/#page-{page_anchor}")
                return _redirect

            app.get(_p, response_class=RedirectResponse, include_in_schema=False)(_make_redirect(_a))

        @app.get("/change-password", response_class=HTMLResponse)
        async def change_password_page(request: Request):
            nonce = getattr(request.state, 'nonce', '')
            return self._templates.TemplateResponse(
                request=request,
                name="change_password.html",
                context={"nonce": nonce},
            )

        # ── API Routes: System ────────────────────────────────────────────────

        admin_only = self._auth_deps.require_role("admin")

        @app.get("/api/system/state")
        async def api_system_state(user: Any = Depends(self._auth_deps.require_auth_optional)):
            return self._read_state()

        @app.get("/api/system/trades")
        async def api_trades(user: Any = Depends(self._auth_deps.require_auth_optional)):
            return self._load_recent_trades()

        @app.get("/api/system/health")
        async def api_health(user: Any = Depends(self._auth_deps.require_auth_optional)):
            return await self._check_health()

        @app.get("/api/system/signals")
        async def api_signals(user: Any = Depends(self._auth_deps.require_auth_optional)):
            return self._get_signals()

        # ── Config management API (admin only) ────────────────────────────────

        @app.get("/api/config")
        async def api_get_config(user: Any = Depends(admin_only)):
            return {
                "config": self._cfg,
                "defaults_path": str(self._resolve_defaults_path()),
                "config_path": str(self._resolve_config_path()),
            }

        @app.get("/api/config/defaults")
        async def api_get_defaults(user: Any = Depends(admin_only)):
            return self._load_defaults()

        @app.post("/api/config/validate")
        async def api_validate_config(
            request: Request,
            user: Any = Depends(admin_only),
        ):
            body = await request.json()
            return self._validate_config_change(body)

        @app.post("/api/config/preview")
        async def api_preview_config(
            request: Request,
            user: Any = Depends(admin_only),
        ):
            body = await request.json()
            return self._preview_config_change(body)

        @app.post("/api/config/apply")
        async def api_apply_config(
            request: Request,
            user: Any = Depends(admin_only),
        ):
            body = await request.json()
            return self._apply_config_change(body, user.username)

        @app.get("/api/config/history")
        async def api_config_history(user: Any = Depends(admin_only)):
            return self._get_config_history()

        @app.post("/api/config/rollback/{version}")
        async def api_rollback_config(
            version: str,
            user: Any = Depends(admin_only),
        ):
            return self._rollback_config(version, user.username)

        # ── Kill switch API ───────────────────────────────────────────────────

        @app.post("/api/system/kill")
        async def api_kill(
            request: Request,
            user: Any = Depends(admin_only),
        ):
            body = await request.json()
            reason = str(body.get("reason", "Manual kill via dashboard"))
            return self._execute_kill(reason, user.username)

        @app.post("/api/system/resume")
        async def api_resume(
            user: Any = Depends(admin_only),
        ):
            return self._execute_resume()

        @app.get("/api/system/kill-status")
        async def api_kill_status(user: Any = Depends(self._auth_deps.require_auth_optional)):
            return {"halted": self._pause_event.is_set()}

        # ── Broker info API ─────────────────────────────────────────────────────

        @app.get("/api/broker/info")
        async def api_broker_info(user: Any = Depends(self._auth_deps.require_auth_optional)):
            return {
                "status": "connected",
                "broker_name": self._cfg.get("broker_name", "Zerodha"),
                "mode": self._cfg.get("execution_mode", "paper"),
                "latency_ms": self._bot_refs.get("broker_latency", 0),
                "adapter": self._cfg.get("broker_adapter", "kite"),
                "last_connected": None,
                "requests_today": 0,
                "error_rate": None,
                "failover_active": False,
            }

        # ── ML status API ───────────────────────────────────────────────────────

        @app.get("/api/ml/status")
        async def api_ml_status(user: Any = Depends(self._auth_deps.require_auth_optional)):
            return {
                "model_loaded": self._bot_refs.get("ml_model_loaded", False),
                "accuracy": self._bot_refs.get("ml_accuracy"),
                "brier_score": self._bot_refs.get("ml_brier_score"),
                "last_training": self._bot_refs.get("ml_last_training"),
                "classifier_type": "LightGBM",
                "n_features": self._bot_refs.get("ml_n_features"),
                "training_samples": self._bot_refs.get("ml_training_samples"),
                "drift_detected": self._bot_refs.get("ml_drift_detected", False),
                "total_predictions": self._bot_refs.get("ml_total_predictions", 0),
                "avg_confidence": self._bot_refs.get("ml_avg_confidence"),
                "calibration_score": self._bot_refs.get("ml_calibration_score"),
                "psi": self._bot_refs.get("ml_psi"),
            }

        # ── Bot control API (admin + operator) ────────────────────────────────

        operator_or_admin = self._auth_deps.require_role("admin", "operator")

        @app.post("/api/system/pause")
        async def api_pause(
            user: Any = Depends(operator_or_admin),
        ):
            self._pause_event.set()
            return {"status": "paused"}

        @app.post("/api/system/resume-entry")
        async def api_resume_entry(
            user: Any = Depends(operator_or_admin),
        ):
            self._pause_event.clear()
            return {"status": "resumed"}

        # ── Observability: Docker health check ─────────────────────────────────

        @app.get("/api/system/health/docker")
        async def docker_health_check():
            """Docker health check endpoint (no auth required)."""
            state = self._read_state()
            db_ok = False
            try:
                import sqlite3
                conn = sqlite3.connect(self._db_path, timeout=2)
                conn.execute("SELECT 1")
                conn.close()
                db_ok = True
            except Exception as exc:
                _log.warning("[DASH] Health check DB probe failed: %s", exc)
            auth_db_ok = False
            try:
                conn = sqlite3.connect(self._auth._db_path, timeout=2)
                conn.execute("SELECT 1")
                conn.close()
                auth_db_ok = True
            except Exception as exc:
                _log.warning("[DASH] Health check auth DB probe failed: %s", exc)
            uptime_secs = time.time() - self._startup_ts if hasattr(self, '_startup_ts') else 0
            return {
                "status": "healthy" if (db_ok and auth_db_ok and not state.get("hard_halt")) else "degraded",
                "version": "2.53.0",
                "uptime_seconds": uptime_secs,
                "uptime_human": f"{int(uptime_secs//3600)}h{int(uptime_secs%3600//60)}m",
                "db_connected": db_ok,
                "auth_db_connected": auth_db_ok,
                "paused": self._pause_event.is_set(),
                "hard_halt": state.get("hard_halt", False),
                "open_positions": state.get("open_positions", 0),
                "timestamp": time.time(),
            }

        # ── Observability: Uptime / diagnostics ─────────────────────────────────

        # ── OI Snapshot Summary API ────────────────────────────────────────────

        @app.get("/api/system/oi", tags=["System"])
        async def api_oi_summary(user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Get OI snapshot summary for all tracked indices.

            Returns live PCR/OI data from the NSE adapter (if available)
            plus the most recent recorded snapshot from ``oi_snapshots.db``.
            """
            index_names = self._cfg.get("INDEX_PRIORITY", ["NIFTY", "BANKNIFTY", "FINNIFTY"])

            # 1. Live data from NSE adapter (read-only, no recording side effects)
            live: dict[str, Any] = {}
            try:
                from core.nse_option_recorder import get_oi_summary
                live = get_oi_summary(index_names, self._cfg)
            except Exception as exc:
                _log.debug("[DASH] Live OI summary unavailable: %s", exc)

            # 2. Recent recorded snapshots from oi_snapshots.db
            recent: dict[str, Any] = {}
            try:
                from core.oi_snapshot_store import get_snapshot_at
                oi_db = str(
                    self._cfg.get("oi_snapshot_db_path",
                    self._cfg.get("OI_SNAPSHOT_DB_PATH", "oi_snapshots.db"))
                )
                now = time.time()
                for idx in index_names:
                    snap = get_snapshot_at(idx, now + 1, db_path=oi_db)
                    if snap:
                        # Convert to readable format, drop internal fields
                        recent[idx] = {
                            k: v for k, v in snap.items()
                            if k not in ("id", "snapshot_source")
                        }
            except Exception as exc:
                _log.debug("[DASH] DB OI snapshots unavailable: %s", exc)

            return {
                "index_names": index_names,
                "live": live,
                "recent_snapshots": recent,
                "timestamp": time.time(),
            }

        # ── Invariants API ────────────────────────────────────────────────────

        @app.get("/api/system/invariants", tags=["System"])
        async def api_invariants(user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Get runtime invariant check results and violations."""
            try:
                from core.invariants.engine import check_all, get_state, get_violations
                # Run all checks to get fresh results
                check_all()
                state = get_state()
                violations = get_violations(unresolved_only=True)
                return {
                    "checks": state["checks"],
                    "violations": state["violations"],
                    "unresolved_violations": len(violations),
                    "total_violations": state["violation_count"],
                    "disabled_checks": state["disabled_checks"],
                }
            except ImportError:
                return {"status": "unavailable", "detail": "Invariant engine not available"}
            except Exception as e:
                return {"status": "error", "detail": str(e)}

        @app.get("/api/system/uptime")
        async def api_uptime(user: Any = Depends(self._auth_deps.require_auth_optional)):
            uptime_secs = time.time() - self._startup_ts
            return {
                "started_at": self._startup_ts,
                "uptime_seconds": uptime_secs,
                "uptime_human": f"{int(uptime_secs//3600)}h{int(uptime_secs%3600//60)}m",
                "server_time": time.time(),
                "server_time_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

        @app.get("/api/system/diagnostics")
        async def api_diagnostics(user: Any = Depends(admin_only)):
            state = self._read_state()
            return {
                "python_version": sys.version,
                "platform": sys.platform,
                "state_file_exists": Path(self._state_path).is_file(),
                "config_keys": len(self._cfg),
                "auth_sessions": self._auth.get_stats().get("active_sessions", 0),
                "total_users": self._auth.get_stats().get("total_users", 0),
                "open_positions": state.get("open_positions", 0),
                "paused": self._pause_event.is_set(),
                "hard_halt": state.get("hard_halt", False),
                "execution_mode": state.get("execution_mode", self._cfg.get("execution_mode", "paper")),
                "uptime": time.time() - self._startup_ts,
            }

        # ── CSV Export: Trades ───────────────────────────────────────────────────

        @app.get("/api/system/trades/export")
        async def api_trades_export(user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Export trades as CSV download."""
            trades = self._load_recent_trades(days=90, n=5000)
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["timestamp", "symbol", "direction", "entry_price", "exit_price",
                             "quantity", "pnl", "status", "entry_time", "exit_time",
                             "strike", "expiry", "index"])
            for t in trades:
                writer.writerow([
                    t.get("created_at", t.get("entry_time", "")),
                    t.get("symbol", t.get("index", "")),
                    t.get("direction", ""),
                    t.get("entry_price", ""),
                    t.get("exit_price", ""),
                    t.get("quantity", ""),
                    t.get("pnl", ""),
                    t.get("status", ""),
                    t.get("entry_time", ""),
                    t.get("exit_time", ""),
                    t.get("strike", ""),
                    t.get("expiry", ""),
                    t.get("index", ""),
                ])
            csv_data = output.getvalue()
            output.close()
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(
                content=csv_data,
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=trades_export.csv"},
            )

        # ── Risk: Position Concentration ─────────────────────────────────────────

        @app.get("/api/risk/concentration")
        async def api_risk_concentration(user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Calculate position concentration risk metrics."""
            trades = self._load_recent_trades(days=1, n=500)
            state = self._read_state()
            capital = state.get("base_capital", state.get("capital", 1_000_000)) or 1_000_000
            open_positions = [t for t in trades if t.get("status") == "open" or t.get("exit_time") is None]
            concentration_risk = "LOW"
            single_largest_pct = 0
            total_exposure = 0
            by_index = {}
            for t in open_positions:
                val = abs(t.get("pnl", 0)) + abs(t.get("entry_price", 0) * t.get("quantity", 0))
                total_exposure += val
                idx = t.get("index", t.get("symbol", "unknown"))
                by_index[idx] = by_index.get(idx, 0) + val
            for idx, val in by_index.items():
                pct = (val / capital * 100) if capital > 0 else 0
                if pct > single_largest_pct:
                    single_largest_pct = pct
            if single_largest_pct > 30:
                concentration_risk = "CRITICAL"
            elif single_largest_pct > 15:
                concentration_risk = "HIGH"
            elif single_largest_pct > 8:
                concentration_risk = "MODERATE"
            return {
                "concentration_risk": concentration_risk,
                "single_largest_index_pct": round(single_largest_pct, 2),
                "total_exposure": round(total_exposure, 2),
                "capital": capital,
                "exposure_pct": round((total_exposure / capital * 100) if capital > 0 else 0, 2),
                "open_position_count": len(open_positions),
                "by_index": {k: {"exposure": round(v, 2), "pct": round((v / capital * 100) if capital > 0 else 0, 2)} for k, v in by_index.items()},
                "timestamp": time.time(),
            }

        # ── v2.45 Webhook: Signal Injection ──────────────────────────────────────
        # Exempt from auth so external systems can push signals

        @app.post("/signals/inject")
        async def signal_webhook(request: Request):
            """
            Receive a trading signal via webhook POST.

            Config keys:
              webhook_enabled (bool, default false)
              webhook_rate_limit_per_min (int, default 5)

            Returns:
              {"status": "disabled"} when webhook_enabled=False
              {"status": "queued", "ts": ...} when accepted
              {"status": "rate_limited", "retry_after": ...} when rate limited
            """
            if not self._cfg.get("webhook_enabled", False):
                return {"status": "disabled"}

            # Rate limiting check
            if self._rate_limiter is not None:
                try:
                    allowed = self._rate_limiter.check("webhook")
                    if not allowed:
                        retry_after = 60
                        return {"status": "rate_limited", "retry_after": retry_after}
                except Exception as exc:
                    _log.warning("[DASH] Webhook rate limiter error: %s", exc)

            try:
                body = await request.json()
            except Exception as exc:
                _log.warning("[DASH] Webhook JSON decode error: %s", exc)
                return {"status": "queued", "ts": time.time()}

            # Queue the signal if a signal_queue is wired
            if self._signal_queue is not None:
                try:
                    self._signal_queue.put(body)
                except Exception as exc:
                    _log.warning("[DASH] Webhook signal queue error: %s", exc)

            # Also append to signal_log if available
            if self._signal_log is not None:
                try:
                    self._signal_log.append(body)
                except Exception as exc:
                    _log.warning("[DASH] Webhook signal log error: %s", exc)

            return {"status": "queued", "ts": time.time()}

        # ── v2.45 Options Chain Viz ──────────────────────────────────────────────

        @app.get("/chain/{index_name}")
        async def options_chain_viz(index_name: str, user: Any = Depends(self._auth_deps.require_auth_optional)):
            """
            Get options chain data for a given index.

            Config keys:
              chain_viz_enabled (bool, default False)

            Returns:
              {"status": "disabled"} when chain_viz_enabled=False
              Otherwise, dict with chain data for the requested index.
            """
            if not self._cfg.get("chain_viz_enabled", False):
                return {"status": "disabled"}

            # Try to load chain data from market data adapter if available
            chain_data = {"index": index_name.upper()}

            market_data = self._bot_refs.get("market_data")
            if market_data is not None:
                try:
                    oc = market_data.get_option_chain(index_name.upper())
                    if oc:
                        chain_data["option_chain"] = oc
                except Exception as exc:
                    _log.warning("[DASH] Option chain fetch error: %s", exc)

            chain_data["symbol"] = index_name.upper()
            chain_data["spot_price"] = self._bot_refs.get(f"ltp_{index_name.upper()}", 0)
            return chain_data

        # ── Execution Safety: Startup Self-Test ──────────────────────────────────

        @app.post("/api/system/self-test")
        async def api_self_test(user: Any = Depends(admin_only)):
            """Run startup self-test to verify critical modules are healthy."""
            results = []
            all_pass = True

            # 1. Auth DB health
            try:
                stats = self._auth.get_stats()
                results.append({"test": "auth_db", "status": "pass", "detail": f"{stats.get('total_users', 0)} users, {stats.get('active_sessions', 0)} active sessions"})
            except Exception as e:
                results.append({"test": "auth_db", "status": "fail", "detail": str(e)})
                all_pass = False

            # 2. State file readable
            try:
                state = self._read_state()
                results.append({"test": "state_file", "status": "pass", "detail": f"{len(state)} keys, mode={state.get('execution_mode', 'unknown')}"})
            except Exception as e:
                results.append({"test": "state_file", "status": "fail", "detail": str(e)})
                all_pass = False

            # 3. Trades DB queryable
            try:
                import sqlite3
                conn = sqlite3.connect(self._db_path, timeout=2)
                cursor = conn.execute("SELECT COUNT(*) FROM trades")
                trade_count = cursor.fetchone()[0]
                conn.close()
                results.append({"test": "trades_db", "status": "pass", "detail": f"{trade_count} trades"})
            except Exception as e:
                results.append({"test": "trades_db", "status": "warn", "detail": f"{e} (non-fatal if no trades yet)"})

            # 4. Config available
            try:
                cfg_keys = len(self._cfg)
                defaults_path = self._resolve_defaults_path()
                defaults_ok = defaults_path.is_file()
                results.append({"test": "config", "status": "pass", "detail": f"{cfg_keys} keys loaded, defaults_file={defaults_ok}"})
                if not defaults_ok:
                    results.append({"test": "defaults_file", "status": "warn", "detail": f"Defaults file not found at {defaults_path}"})
            except Exception as e:
                results.append({"test": "config", "status": "fail", "detail": str(e)})
                all_pass = False

            # 5. Template rendering works
            try:
                tmpl = self._templates.get_template("login.html")
                results.append({"test": "templates", "status": "pass", "detail": f"Login template loaded ({len(tmpl.render(request=None))} bytes)"})
            except Exception as e:
                results.append({"test": "templates", "status": "warn", "detail": str(e)})

            return {
                "overall": "PASS" if all_pass else "FAIL",
                "timestamp": time.time(),
                "results": results,
                "summary": f"{sum(1 for r in results if r['status'] == 'pass')} passed, {sum(1 for r in results if r['status'] == 'warn')} warnings, {sum(1 for r in results if r['status'] == 'fail')} failed",
            }

        return app

    # ── Config management ────────────────────────────────────────────────────

    def _resolve_defaults_path(self) -> Path:
        """Resolve the path to the index_config.defaults.json file.

        Checks the config for 'index_config_defaults_path' key, falls back
        to the default filename in the project root.
        """
        return Path(self._cfg.get("index_config_defaults_path", "index_config.defaults.json"))

    def _resolve_config_path(self) -> Path:
        """Resolve the path to the active config.json file.

        Respects OPBUYING_INDEX_CONFIG env var, then 'index_config_path' config key,
        then falls back to 'config.json' in the project root.
        """
        config_file = os.environ.get("OPBUYING_INDEX_CONFIG", self._cfg.get("index_config_path", "config.json"))
        return Path(config_file)

    def _load_defaults(self) -> dict:
        """Load the defaults JSON file as a dict.

        Returns empty dict if file is missing or unreadable — never raises.
        """
        defaults_path = self._resolve_defaults_path()
        try:
            if defaults_path.is_file():
                return json.loads(defaults_path.read_text(encoding="utf-8"))
        except Exception as e:
            _log.warning("[DASH] Failed to load defaults: %s", e)
        return {}

    def _validate_config_change(self, change: dict) -> dict:
        """Validate a config change against schema rules.

        Args:
            change: Dict of key-value pairs to validate.

        Returns:
            Dict with 'valid' bool, 'errors' list, and 'warnings' list.
        """
        errors = []
        warnings = []
        for key, value in change.items():
            if key.startswith("_"):
                continue
            if key in ("BROKER_CONFIG",) and isinstance(value, dict):
                continue
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                warnings.append({"key": key, "message": "References environment variable"})
        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    def _preview_config_change(self, change: dict) -> dict:
        """Preview what a config change would look like as a diff.

        Args:
            change: Dict of key-value pairs to preview.

        Returns:
            Dict with 'changed_keys' showing old/new values, 'total_changes' count,
            and full 'preview_config' after merge.
        """
        merged = dict(self._cfg)
        changed_keys = {}
        for key, value in change.items():
            if key in merged:
                old_val = merged[key]
                if old_val != value:
                    changed_keys[key] = {"old": old_val, "new": value}
            else:
                changed_keys[key] = {"old": None, "new": value}
            merged[key] = value
        return {
            "changed_keys": changed_keys,
            "total_changes": len(changed_keys),
            "preview_config": merged,
        }

    def _apply_config_change(self, change: dict, username: str) -> dict:
        """Apply a config change to disk with automatic backup + audit log.

        Creates a timestamped .backup file before writing. On write failure,
        attempts to restore the original content. Logs all changes to
        config_audit.jsonl for traceability.

        Args:
            change: Dict of key-value pairs to apply.
            username: Username making the change (for audit trail).

        Returns:
            Dict with 'success' bool, 'applied_count', 'applied_keys', and 'backup_file'.
        """
        config_path = self._resolve_config_path()
        try:
            original = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
        except Exception as e:
            return {"success": False, "error": f"Failed to read config: {e}"}

        # Save original before any modifications (for safe rollback)
        current = dict(original)

        backup_path = config_path.with_suffix(f".json.backup.{int(time.time())}")
        try:
            Path(str(backup_path)).write_text(json.dumps(original, indent=4), encoding="utf-8")
        except Exception as e:
            return {"success": False, "error": f"Backup failed: {e}"}

        applied = {}
        for key, value in change.items():
            if key.startswith("_"):
                continue
            current[key] = value
            applied[key] = value

        try:
            config_path.write_text(json.dumps(current, indent=4), encoding="utf-8")
        except Exception as e:
            try:
                config_path.write_text(json.dumps(original, indent=4), encoding="utf-8")
                _log.info("[DASH] Config write failed — original restored")
            except Exception as restore_exc:
                _log.critical("[DASH] Config write failed AND rollback failed! %s", restore_exc)
            return {"success": False, "error": f"Write failed, rolled back: {e}"}

        with self._config_lock:
            self._cfg.clear()
            self._cfg.update(current)
            # Re-freeze the config so the config property stays current
            self._cfg_frozen = _freeze(self._cfg)

        self._log_config_audit(username, list(applied.keys()), list(applied.values()), "config_apply")
        return {
            "success": True,
            "applied_count": len(applied),
            "applied_keys": list(applied.keys()),
            "backup_file": str(backup_path),
        }

    def _get_config_history(self) -> list[dict]:
        """Get config version history from backup files.

        Scans the config directory for *.backup.* files, parses timestamps
        from filenames, and returns the 20 most recent sorted by time descending.

        Returns:
            List of dicts with 'file', 'timestamp', and 'age' (seconds).
        """
        config_path = self._resolve_config_path()
        backups = sorted(Path(config_path.parent).glob("*.backup.*"), reverse=True)
        history = []
        for bp in backups[:20]:
            try:
                ts_str = bp.suffixes[-1].lstrip(".")
                ts = float(ts_str) if ts_str.replace(".", "").isdigit() else 0
                history.append({
                    "file": bp.name,
                    "timestamp": ts,
                    "age": int(time.time() - ts) if ts else 0,
                })
            except (ValueError, IndexError):
                continue
        return history

    def _rollback_config(self, version: str, username: str) -> dict:
        """Rollback config to a previous version from a backup file.

        Args:
            version: Backup filename (e.g. 'config.json.backup.1712345678').
            username: Username performing the rollback (for audit trail).

        Returns:
            Dict with 'success' bool and details of restored keys.
        """
        config_path = self._resolve_config_path()
        # Validate backup path to prevent directory traversal
        raw_path = config_path.parent / version
        backup_path = raw_path.resolve()
        safe_prefix = str(config_path.parent.resolve())
        if not str(backup_path).startswith(safe_prefix):
            return {"success": False, "error": "Invalid backup path — directory traversal blocked"}
        if not backup_path.is_file():
            return {"success": False, "error": "Backup file not found"}
        try:
            backup_data = json.loads(backup_path.read_text(encoding="utf-8"))
            config_path.write_text(json.dumps(backup_data, indent=4), encoding="utf-8")
            with self._config_lock:
                self._cfg.clear()
                self._cfg.update(backup_data)
                # Re-freeze so config property returns current state
                self._cfg_frozen = _freeze(self._cfg)
            self._log_config_audit(username, ["rollback"], [version], "config_rollback")
            return {"success": True, "restored_from": version, "keys_restored": len(backup_data)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _log_config_audit(self, username: str, keys: list, values: list, action: str) -> None:
        try:
            audit_file = Path("config_audit.jsonl")
            with open(audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "timestamp": time.time(),
                    "action": action,
                    "username": username,
                    "keys": keys,
                    "values": values,
                    "ip": "dashboard",
                }) + "\n")
        except Exception as exc:
            _log.warning("[DASH] Config audit write failed: %s", exc)

    # ── Kill switch ──────────────────────────────────────────────────────────

    def _execute_kill(self, reason: str, username: str) -> dict:
        """Execute emergency kill: halt all trading immediately.

        Sets the pause event, logs the kill at CRITICAL level, attempts to
        propagate to control plane and halt callback if wired.

        Args:
            reason: Human-readable reason for the kill.
            username: User who triggered the kill.

        Returns:
            Dict with 'success', 'halted', 'reason', 'triggered_by', 'timestamp'.
        """
        self._pause_event.set()
        _log.critical("[DASH] EMERGENCY KILL by %s: %s", username, reason)

        if self._control_plane:
            try:
                self._control_plane.control_kill(username, reason=reason)
            except Exception as e:
                _log.warning("[DASH] Control plane kill failed: %s", e)

        if "halt_callback" in self._bot_refs:
            try:
                self._bot_refs["halt_callback"](f"KILL by {username}: {reason}")
            except Exception as e:
                _log.warning("[DASH] Halt callback failed: %s", e)

        return {
            "success": True,
            "halted": True,
            "reason": reason,
            "triggered_by": username,
            "timestamp": time.time(),
        }

    def _execute_resume(self) -> dict:
        """Resume trading after an emergency kill.

        Clears the pause event and logs the resume at WARNING level.
        """
        self._pause_event.clear()
        _log.warning("[DASH] System resumed via dashboard")
        return {"success": True, "halted": False}

    # ── Data helpers ─────────────────────────────────────────────────────────

    def _read_state(self) -> dict:
        try:
            sp = Path(self._state_path)
            if sp.is_file():
                return json.loads(sp.read_text(encoding="utf-8"))
        except Exception as exc:
            _log.warning("[DASH] Failed to read trader state: %s", exc)
        return {}

    def _load_recent_trades(self, days: int = 30, n: int = 100) -> list:
        """Load recent trades from the trades database.

        Uses core.performance_metrics.load_trades if available.
        Returns empty list on any error.

        Args:
            days: Lookback window in days. None = all time.
            n: Max number of trades to return.

        Returns:
            List of trade dicts, newest last, up to n items.
        """
        try:
            from core.performance_metrics import load_trades
            trades = load_trades(self._db_path, days=days if days > 0 else None)
            return trades[-n:]
        except Exception as e:
            _log.debug("[DASH] load_trades failed: %s", e)
            return []

    async def _check_health(self) -> dict:
        state = self._read_state()
        uptime_secs = time.time() - self._startup_ts if hasattr(self, '_startup_ts') else 0
        return {
            "status": "ok",
            "paused": self._pause_event.is_set(),
            "daily_pnl": state.get("daily_pnl", 0),
            "open_positions": state.get("open_positions", 0),
            "hard_halt": state.get("hard_halt", False),
            "uptime": uptime_secs,
            "uptime_human": f"{int(uptime_secs//3600)}h{int(uptime_secs%3600//60)}m",
            "capital": state.get("base_capital", state.get("capital", 0)),
            "execution_mode": state.get("execution_mode", self._cfg.get("execution_mode", "paper")),
            "circuit_breaker": state.get("circuit_breaker", "Closed"),
            "timestamp": time.time(),
        }

    def _get_signals(self, n: int = 50) -> list:
        if self._signal_log is None:
            return []
        sigs = self._signal_log.recent(n)
        for s in sigs:
            s.setdefault("reasoning", "No detailed reasoning available")
            s.setdefault("sentiment", "NEUTRAL")
        return sigs


def create_enterprise_dashboard(
    config: dict[str, Any] | None = None,
    **refs: Any,
) -> EnterpriseDashboard:
    """Create and wire an EnterpriseDashboard instance."""
    dashboard = EnterpriseDashboard(config=config)
    dashboard.wire_bot_refs(**refs)
    return dashboard
