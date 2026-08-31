"""Enterprise Web Dashboard - premium FastAPI + Jinja2 + Tailwind CSS UI.

Provides a world-class admin interface with full auth, RBAC, config management,
kill switch, and monitoring.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Any

from core.notifications.url_resolver import is_production_environment

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

    class FastAPI:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.routes: list[Any] = []
        def include_router(self, *args: Any, **kwargs: Any) -> None: pass

        def mount(self, *args: Any, **kwargs: Any) -> None: pass
        def add_middleware(self, *args: Any, **kwargs: Any) -> None: pass
        def middleware(self, *args: Any, **kwargs: Any) -> Any: return lambda f: f
        def exception_handler(self, *args: Any, **kwargs: Any) -> Any: return lambda f: f
        def on_event(self, *args: Any, **kwargs: Any) -> Any: return lambda f: f
        def get(self, *args: Any, **kwargs: Any) -> Any: return lambda f: f
        def post(self, *args: Any, **kwargs: Any) -> Any: return lambda f: f
        def put(self, *args: Any, **kwargs: Any) -> Any: return lambda f: f
        def delete(self, *args: Any, **kwargs: Any) -> Any: return lambda f: f




    class Request:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None: pass
    class HTTPException(Exception):  # type: ignore
        def __init__(self, status_code: int = 500, detail: str = "") -> None:
            self.status_code = status_code
            self.detail = detail
            super().__init__(f"[{status_code}] {detail}")
    class CORSMiddleware:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None: pass
    class FileResponse:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None: pass
    class JSONResponse:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None: pass
    class RedirectResponse:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None: pass
    class StaticFiles:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None: pass
    class Jinja2Templates:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None: pass
        def TemplateResponse(self, *args: Any, **kwargs: Any) -> Any: return None




from core.auth.csrf import csrf_protection
from core.auth.dependencies import AuthDependencies
from core.auth.handler import AuthHandler
from core.auth.routes import create_auth_router
from core.enterprise_dashboard.models import DashboardNotifier, Notification, NotificationManager
from core.enterprise_dashboard.utils import (
    _error_response,
    _freeze,
)

_log = logging.getLogger(__name__)


class EnterpriseDashboard:
    """Enterprise-grade web dashboard with auth, RBAC, and admin UI."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        auth_handler: AuthHandler | None = None,
        state_path: str | None = None,
        db_path: str = "db/trades.db",
    ):
        self._cfg = dict(config or {})
        # Freeze config to prevent accidental mutation at runtime
        self._cfg_frozen = _freeze(self._cfg)
        self._state_path = state_path or self._cfg.get("trader_state_path", "json/trader_state.json")
        # Was a bare hardcoded relative path before - meant every test
        # exercising _apply_config_change()/_rollback_config() (which call
        # _log_config_audit()) wrote real entries into the live project's
        # json/config_audit.jsonl, polluting the audit trail an admin now
        # sees in the UI with test-run noise.
        self._config_audit_log_path = Path(self._cfg.get("config_audit_log_path", "json/config_audit.jsonl"))
        self._db_path = str(db_path or self._cfg.get("trades_db", "db/trades.db"))
        self._auth = auth_handler or AuthHandler(
            db_path=self._cfg.get("auth_db_path", "db/auth.db"),
            token_ttl=int(self._cfg.get("auth_token_ttl_seconds", 3600)),
        )
        self._auth_deps = AuthDependencies(self._auth)
        self._cookie_secure = str(self._cfg.get("web_dashboard_host", "127.0.0.1")) != "127.0.0.1"  # nosec B104
        self._templates_dir = self._ensure_templates()
        self._templates = Jinja2Templates(directory=str(self._templates_dir))

        # Centralized permission resolver for navigation and page chrome.
        # UI visibility is derived from the same effective per-user RBAC
        # calculation used by the API dependency layer (role baseline +
        # explicit per-user allow/deny overrides; Super Admin is unrestricted).
        def _template_user_can(user: Any, permission: str) -> bool:
            try:
                username = user.get("username") if isinstance(user, dict) else getattr(user, "username", "")
                role = user.get("role") if isinstance(user, dict) else getattr(user, "role", "")
                if str(role).lower() == "super_admin":
                    return True
                if not username:
                    return False
                from core.auth.permissions import role_has_permission
                from core.auth.user_signal_permissions import UserPermissionManager
                mgr = UserPermissionManager.get_instance()
                # Role is the baseline when no per-user record exists.
                record = mgr.get_user_permissions(str(username))
                return mgr.user_has_permission(str(username), str(permission)) if record is not None else role_has_permission(str(role), str(permission))
            except Exception:
                return False

        self._templates.env.globals["user_can"] = _template_user_can
        self._static_dir = self._ensure_static()

        # References to bot internals (wired externally)
        self._pause_event: threading.Event = threading.Event()
        self._signal_log: Any = None
        self._signal_queue: Any = None
        self._ws_feed_manager: Any = None
        self._rate_limiter: Any = None
        self._control_plane: Any = None
        self._bot_refs: dict[str, Any] = {}
        self._config_lock: threading.RLock = threading.RLock()

        # Create the FastAPI app
        self.app = self._create_app()

        # Start background session cleanup
        self._start_session_cleanup()

        # Notification manager for real-time alerts
        self._notifications = NotificationManager(maxlen=200)

        # Lazily built in routes/monitoring.py's paper-trade endpoint (shares
        # db/manual_signals.db with the live trading loop's ManualSignalQueue).
        self._manual_signal_queue: Any = None

    @property
    def config(self) -> MappingProxyType:
        """Read-only frozen view of the active config."""
        return self._cfg_frozen  # type: ignore[no-any-return]

    def _start_session_cleanup(self) -> None:
        """Background thread to purge expired sessions every 15 minutes."""
        self._session_stop = threading.Event()

        def _cleanup_loop() -> None:
            while not self._session_stop.is_set():
                if self._session_stop.wait(900):
                    break
                try:
                    self._auth.purge_expired_sessions()
                except (ValueError, AttributeError, OSError, sqlite3.Error) as exc:
                    _log.warning("[DASH] Session cleanup error: %s", exc)
        t = threading.Thread(target=_cleanup_loop, daemon=True, name="session_cleanup")
        t.start()

    def _ensure_templates(self) -> Path:
        root_dir = Path(__file__).resolve().parent.parent.parent
        root_templates = root_dir / "templates" / "enterprise"
        if root_templates.exists() and root_templates.is_dir():
            return root_templates
        templates_dir = Path(__file__).resolve().parent.parent / "templates" / "enterprise"
        templates_dir.mkdir(parents=True, exist_ok=True)
        return templates_dir

    def _ensure_static(self) -> Path | None:
        """Create and return the static files directory if possible."""
        root_dir = Path(__file__).resolve().parent.parent.parent
        root_static = root_dir / "static"
        if root_static.exists() and root_static.is_dir():
            return root_static

        core_static = Path(__file__).resolve().parent.parent / "static"
        try:
            core_static.mkdir(parents=True, exist_ok=True)
            return core_static
        except (OSError, PermissionError) as e:
            _log.debug("[DASH] Cannot create static dir: %s", e)
            return None

    def _bridge_trader_positions(self) -> None:
        """Auto-bridge commodity/currency/futures trader positions into domain models.

        Called after wire_bot_refs to ensure portfolio aggregation routes
        (in risk.py) have access to converted positions from all trading engines.
        """
        try:
            from core.positions.bridge import wire_trader_positions_to_aggregator
            bridge_result = wire_trader_positions_to_aggregator(self._bot_refs)
            for key, positions in bridge_result.items():
                if positions:
                    self._bot_refs[key] = positions
                    _log.info("[DASH] Bridged %d %s from trader positions", len(positions), key)
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Position bridge unavailable: %s", exc)

    def wire_bot_refs(self, **refs: Any) -> None:
        """Wire external bot references.

        Only overwrites internal references if the supplied value is not None,
        preserving constructor defaults. This prevents callers that pass
        ``pause_event=None`` from accidentally overwriting the default
        ``threading.Event()``.

        After wiring, automatically bridges trader positions (CommodityTrader,
        CurrencyTrader, FuturesTrader) into domain model lists for the
        portfolio aggregation route.
        """
        # Filter out None values to preserve constructor defaults in
        # both the refs dict and the dedicated attributes
        self._bot_refs.update({k: v for k, v in refs.items() if v is not None})
        if "pause_event" in refs and refs["pause_event"] is not None:
            self._pause_event = refs["pause_event"]
        if "signal_log" in refs and refs["signal_log"] is not None:
            self._signal_log = refs["signal_log"]
        if "signal_queue" in refs and refs["signal_queue"] is not None:
            self._signal_queue = refs["signal_queue"]
        if "ws_feed_manager" in refs and refs["ws_feed_manager"] is not None:
            self._ws_feed_manager = refs["ws_feed_manager"]
        if "rate_limiter" in refs and refs["rate_limiter"] is not None:
            self._rate_limiter = refs["rate_limiter"]
        if "control_plane" in refs and refs["control_plane"] is not None:
            self._control_plane = refs["control_plane"]
        # Auto-bridge trader positions for portfolio aggregation
        self._bridge_trader_positions()

    def _create_app(self) -> FastAPI:
        self._startup_ts = time.time()

        # Register runtime invariant checks on startup
        try:
            from core.invariants.checks import register_all as _register_invariants
            _register_invariants()
            _log.info("[DASH] Runtime invariant checks registered")
        except (ImportError, ValueError, AttributeError) as exc:
            _log.debug("[DASH] Invariant registration skipped -> None: %s", exc)

        @asynccontextmanager
        async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
            _log.info("[DASH] Enterprise dashboard started")
            # Start periodic Prometheus gauge updater for market data providers
            _metrics_stop = threading.Event()

            def _update_provider_metrics_loop() -> None:
                while not _metrics_stop.is_set():
                    if _metrics_stop.wait(30):
                        break
                    try:
                        from core.metrics_exporter import update_metrics
                        mds = self._bot_refs.get("market_data_service")
                        if mds is not None:
                            health = mds.health_check()
                            total = health.get("total_adapters", 0)
                            connected = health.get("connected_adapters", 0)
                            disconnected_pct = round(((total - connected) / max(total, 1)) * 100, 1) if total > 0 else 0.0
                            worst_state = 0  # healthy
                            if connected < total:
                                worst_state = 1  # degraded
                            if connected == 0 and total > 0:
                                worst_state = 2  # critical

                            update_metrics({
                                "data_providers_total": total,
                                "data_providers_connected": connected,
                                "data_providers_disconnected_pct": disconnected_pct,
                                "data_providers_worst_state": worst_state,
                            })
                            _log.debug(
                                "[DASH] Updated Prometheus gauges: %d/%d providers connected",
                                connected, total,
                            )
                    except (ValueError, TypeError, AttributeError, ImportError, RuntimeError) as exc:
                        _log.debug("[DASH] Prometheus metrics update skipped: %s", exc)
            t = threading.Thread(target=_update_provider_metrics_loop, daemon=True, name="provider_metrics_updater")
            t.start()

            # Start health metrics → SLO governance poller (every 5 minutes)
            _slo_stop = threading.Event()

            def _slo_health_poller_loop() -> None:
                while not _slo_stop.is_set():
                    try:
                        from core.health_checker import run_full_health_check
                        from core.slo_governance import get_slo_governance, ingest_health_report
                        report = run_full_health_check(self._cfg)
                        ingest_health_report(report)
                        # Also run SLO compliance check so data is fresh when UI queries /api/slo/compliance
                        slo = get_slo_governance()
                        slo.check_all_slos()
                        _log.debug("[DASH] SLO health metrics ingested: %s", report.summary)
                    except (ValueError, TypeError, AttributeError, OSError, ImportError) as exc:
                        _log.debug("[DASH] SLO health poller skipped: %s", exc)
                    # Wait 5 minutes (interruptible on shutdown), then loop again
                    # Outer while ensures recovery from transient exceptions
                    if _slo_stop.wait(300):
                        break
                _log.info("[DASH] SLO health poller stopped")
            t2 = threading.Thread(target=_slo_health_poller_loop, daemon=True, name="slo-health-poller")
            t2.start()
            _log.info("[DASH] SLO health metrics poller started (5min interval)")
            yield
            _metrics_stop.set()
            _slo_stop.set()
            _log.info("[DASH] Enterprise dashboard shutting down gracefully")

        app = FastAPI(
            title="OPB Enterprise Dashboard",
            version="2.54.0",
            docs_url="/api/docs",
            redoc_url="/api/redoc",
            openapi_tags=[
                {
                    "name": "Auth",
                    "description": "Authentication and session management - login, register, change password",
                },
                {
                    "name": "System",
                    "description": "System state, health, diagnostics, uptime, trades, signals - read-only observability",
                },
                {
                    "name": "Admin",
                    "description": "Admin-only operations - config management, kill switch, user management, self-test",
                },
                {
                    "name": "Risk",
                    "description": "Risk metrics - position concentration and exposure analysis",
                },
                {
                    "name": "Broker",
                    "description": "Broker connection status and adapter information",
                },
                {
                    "name": "ML",
                    "description": "ML model status - accuracy, drift detection, calibration",
                },
                {
                    "name": "Webhook",
                    "description": "External signal injection webhook for automated trading signals",
                },
                {
                    "name": "Charts",
                    "description": "Options chain visualization and market data charts",
                },
                {
                    "name": "Governance",
                    "description": "Strategy governance, approval workflow, and data quality scoring",
                },
                {
                    "name": "Capacity",
                    "description": "Capacity planning, resource forecasting, throughput trends, and scaling triggers",
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
            except (ValueError, OSError) as e:
                _log.warning("[DASH] Static files mount skipped: %s", e)

        # CSRF exempt paths
        csrf_protection.exempt("/api/auth/login")
        csrf_protection.exempt("/api/auth/register")
        csrf_protection.exempt("/api/auth/forgot-password")
        csrf_protection.exempt("/api/auth/verify-reset-token")
        csrf_protection.exempt("/api/auth/reset-password")
        csrf_protection.exempt("/api/auth/emergency-reset-password")
        csrf_protection.exempt("/api/auth/forgot-password")
        csrf_protection.exempt("/api/auth/verify-reset-token")
        csrf_protection.exempt("/api/auth/reset-password")
        csrf_protection.exempt("/api/auth/emergency-reset-password")
        csrf_protection.exempt("/api/auth/logout")
        csrf_protection.exempt("/api/system/health/docker")
        csrf_protection.exempt("/signals/inject")
        csrf_protection.exempt("/static")
        csrf_protection.exempt("/api/system/self-test")
        csrf_protection.exempt("/api/v1/admin/test-dispatch-signal")
        csrf_protection.exempt("/api/v1/admin/test-email")
        # SSE notification stream (long-lived connection, not a browser form)
        csrf_protection.exempt("/api/system/notifications/stream")
        # Fundamentals API endpoints (programmatic access, not browser forms)
        csrf_protection.exempt("/api/fundamentals")
        csrf_protection.exempt("/api/docs")
        csrf_protection.exempt("/api/redoc")
        csrf_protection.exempt("/openapi.json")
        # Real Estate API endpoints (programmatic access with token auth)
        # PWA service worker (CSRF exempt, long-lived connection)
        csrf_protection.exempt("/dashboard-sw.js")

        # -- PWA Service Worker Route (served with Service-Worker-Allowed header for root scope) --
        @app.get("/favicon.ico")
        async def favicon() -> FileResponse:
            """Serve the application favicon from the existing OPB icon asset."""
            favicon_path = Path(self._static_dir / "opb-icon-192.svg") if self._static_dir else None
            if favicon_path and favicon_path.is_file():
                return FileResponse(
                    str(favicon_path),
                    media_type="image/svg+xml",
                )
            return FileResponse(
                str(Path(__file__).resolve().parent.parent / "static" / "opb-icon-192.svg"),
                media_type="image/svg+xml",
            )

        @app.get("/dashboard-sw.js")
        async def serve_service_worker():  # type: ignore[no-untyped-def]
            sw_path = Path(self._static_dir / "dashboard-sw.js") if self._static_dir else None
            if sw_path and sw_path.is_file():
                return FileResponse(
                    str(sw_path),
                    media_type="application/javascript",
                    headers={"Service-Worker-Allowed": "/"},
                )
            return JSONResponse({"error": "Service worker not found"}, status_code=404)

        # -- Dashboard alias route (/dashboard -> /) --
        @app.get("/dashboard")
        async def dashboard_alias_redirect():  # type: ignore[no-untyped-def]
            return RedirectResponse(url="/", status_code=307)

        # -- Testing suite alias route (/testing-suite -> /ab-tester) --
        @app.get("/testing-suite")
        async def testing_suite_redirect():  # type: ignore[no-untyped-def]
            return RedirectResponse(url="/ab-tester", status_code=307)



        # -- Admin Root Redirect Route (/admin and /admin/ -> /admin/config) --
        @app.get("/admin")
        @app.get("/admin/")
        async def admin_root_redirect():  # type: ignore[no-untyped-def]
            return RedirectResponse(url="/admin/config", status_code=307)

        # -- Logout Redirect Route (/logout -> /api/auth/logout) --
        @app.get("/logout")
        @app.post("/logout")
        async def logout_redirect(request: Request):  # type: ignore[no-untyped-def]
            return RedirectResponse(url="/api/auth/logout", status_code=307)

        # -- Middleware: Security Headers ----------------------------------------

        @app.middleware("http")
        async def security_headers_middleware(request: Request, call_next: Any):  # type: ignore[no-untyped-def]
            # Generate CSP nonce per-request
            nonce = secrets.token_hex(16)
            request.state.nonce = nonce
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            # HSTS: 1 year, include subdomains, preload - only on HTTPS
            # Check both direct scheme and X-Forwarded-Proto (for reverse proxy)
            forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
            is_secure = request.url.scheme == "https" or forwarded_proto == "https"
            if is_secure:
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
            # CSP: nonce-based scripts, self-hosted assets only (Zero external CDN)
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                f"script-src 'self' 'nonce-{nonce}'; "
                "style-src 'self' 'unsafe-inline'; "
                "font-src 'self' data:; "
                "img-src 'self' data: https:; "
                "connect-src 'self' ws: wss:; "
                "form-action 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'"
            )
            return response

        # -- API Rate Limiter -------------------------------------------------

        _rate_limit_store: dict[str, list[float]] = {}
        _rate_limit_lock = threading.RLock()
        API_RATE_LIMIT = int(self._cfg.get("api_rate_limit_per_minute", 300))
        ADMIN_RATE_LIMIT = int(self._cfg.get("admin_api_rate_limit_per_minute", 300))

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

        # -- Middleware: CORS ---------------------------------------------------

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

        # -- Middleware: API Rate Limiting --------------------------------------

        @app.middleware("http")
        async def rate_limit_middleware(request: Request, call_next: Any):  # type: ignore[no-untyped-def]
            path = request.url.path
            # Exempt monitoring and health diagnostics polling from rate limiting
            exempt_prefixes = (
                "/api/system/health",
                "/api/system/diagnostics",
                "/api/system/status",
                "/api/system/events",
                "/api/v1/admin/system-status",
            )
            if path.startswith("/api/") and not any(path.startswith(p) for p in exempt_prefixes):
                ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "127.0.0.1").split(",")[0].strip()
                is_admin = path.startswith("/api/config") or path.startswith("/api/system/kill") or path.startswith("/api/system/resume")
                limit = ADMIN_RATE_LIMIT if is_admin else API_RATE_LIMIT
                if not _check_rate_limit(ip, limit):
                    return JSONResponse(_error_response("Rate limit exceeded", 429, retry_after=60), status_code=429)
            response = await call_next(request)
            return response

        # -- Middleware: Request ID + Tracing -------------------------------------

        @app.middleware("http")
        async def request_id_middleware(request: Request, call_next: Any):  # type: ignore[no-untyped-def]
            request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:16])
            request.state.request_id = request_id
            request.state.request_start = time.time()
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            req_start = request.state.request_start
            elapsed_ms = int((time.time() - req_start) * 1000) if hasattr(request.state, "request_start") else 0
            response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
            return response

        # -- Middleware: CSRF ----------------------------------------------------

        @app.middleware("http")
        async def csrf_middleware(request: Request, call_next: Any):  # type: ignore[no-untyped-def]
            # HTTPException raised here (BaseHTTPMiddleware.dispatch, via the
            # @app.middleware("http") decorator) does NOT reliably reach
            # FastAPI's @app.exception_handler(403) registration in Starlette -
            # it can instead surface as an unhandled ExceptionGroup at the ASGI
            # boundary. Build the response directly rather than relying on that.
            try:
                await csrf_protection.validate(request)
            except HTTPException as exc:
                return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
            response = await call_next(request)
            # Ensure CSRF cookie is set on GET responses (if missing)
            try:
                await csrf_protection.ensure_cookie_set(request, response)
            except (ValueError, AttributeError, TypeError) as exc:
                _log.warning("[DASH] CSRF cookie set failed: %s", exc)
            return response

        # -- Error handlers -----------------------------------------------------

        @app.exception_handler(403)
        async def forbidden_error(request: Request, exc: Any):  # type: ignore[no-untyped-def]
            nonce = getattr(request.state, "nonce", "")
            _log.warning("[DASH] Forbidden: %s", exc)
            if "application/json" in request.headers.get("accept", ""):
                return JSONResponse(_error_response("Forbidden", 403), status_code=403)
            return self._templates.TemplateResponse(
                request=request,
                name="error.html",
                context={"code": 403, "message": "Access denied - admin role required", "nonce": nonce},
                status_code=403,
            )

        @app.exception_handler(404)
        async def not_found(request: Request, exc: Any):  # type: ignore[no-untyped-def]
            nonce = getattr(request.state, "nonce", "")
            if "application/json" in request.headers.get("accept", ""):
                return JSONResponse(_error_response("Not found", 404), status_code=404)
            return self._templates.TemplateResponse(
                request=request,
                name="error.html",
                context={"code": 404, "message": "Page not found", "nonce": nonce},
                status_code=404,
            )

        @app.exception_handler(500)
        async def server_error(request: Request, exc: Any):  # type: ignore[no-untyped-def]
            nonce = getattr(request.state, "nonce", "")
            _log.exception("[DASH] Unhandled error: %s", exc)
            if "application/json" in request.headers.get("accept", ""):
                return JSONResponse(_error_response("Internal server error", 500), status_code=500)
            return self._templates.TemplateResponse(
                request=request,
                name="error.html",
                context={"code": 500, "message": "Internal server error", "nonce": nonce},
                status_code=500,
            )

        # -- Route Registrations ---------------------------------------------------
        # Routes are organized into domain-specific modules under routes/ package
        admin_only = self._auth_deps.require_role("admin")
        operator_or_admin = self._auth_deps.require_role("admin", "operator")

        def _require_admin_page(request: Request) -> tuple[Any, Any]:
            """Check session auth and admin role, return (user, error_response)."""
            session_token = request.cookies.get("opb_session", "")
            user = None
            if session_token:
                token = self._auth.verify_session(session_token)
                if token:
                    user = self._auth.get_user_by_id(token.user_id)
            if user is None:
                return None, RedirectResponse(url="/login")
            if user.role.lower() not in ("admin", "super_admin"):
                nonce = getattr(request.state, "nonce", "")
                return None, self._templates.TemplateResponse(
                    request=request,
                    name="error.html",
                    context={"code": 403, "message": "Admin access required", "nonce": nonce},
                    status_code=403,
                )
            return user, None

        def _require_operator_or_admin_page(request: Request) -> tuple[Any, Any]:
            """Check session auth and operator/admin role, return (user, error_response)."""
            session_token = request.cookies.get("opb_session", "")
            user = None
            if session_token:
                token = self._auth.verify_session(session_token)
                if token:
                    user = self._auth.get_user_by_id(token.user_id)
            if user is None:
                return None, RedirectResponse(url="/login")
            if user.role.lower() not in ("admin", "super_admin", "operator"):
                nonce = getattr(request.state, "nonce", "")
                return None, self._templates.TemplateResponse(
                    request=request,
                    name="error.html",
                    context={"code": 403, "message": "Access restricted to Administrator and Operator accounts.", "nonce": nonce},
                    status_code=403,
                )
            return user, None

        if not _HAS_FASTAPI:
            return app

        from core.enterprise_dashboard.routes.admin import register_admin_routes
        from core.enterprise_dashboard.routes.fundamentals import register_fundamentals_routes
        from core.enterprise_dashboard.routes.monitoring import register_monitoring_routes
        from core.enterprise_dashboard.routes.pages import register_page_routes
        from core.enterprise_dashboard.routes.reporting import register_reporting_routes
        from core.enterprise_dashboard.routes.risk import register_risk_routes
        from core.enterprise_dashboard.routes.system import register_system_routes
        from core.enterprise_dashboard.routes.webhooks import register_webhook_routes

        register_page_routes(app, self, _require_admin_page, _require_operator_or_admin_page)
        register_system_routes(app, self, admin_only, operator_or_admin)
        register_admin_routes(app, self, admin_only, operator_or_admin)
        register_risk_routes(app, self, admin_only, operator_or_admin)
        register_monitoring_routes(app, self, admin_only, operator_or_admin)
        register_fundamentals_routes(app, self, admin_only, operator_or_admin)
        register_webhook_routes(app, self, admin_only, operator_or_admin)
        register_reporting_routes(app, self, admin_only, operator_or_admin)
        _log.info("[DASH] Report Center routes registered (PDF/Excel + signal intelligence)")

        # Governance routes (strategy lifecycle + data quality)
        try:
            from core.enterprise_dashboard.routes.governance import register_governance_routes
            register_governance_routes(app, self, admin_only, operator_or_admin)
            _log.info("[DASH] Governance routes registered")
        except (ImportError, ValueError, TypeError) as exc:
            _log.debug("[DASH] Governance routes unavailable: %s", exc)

        # Capacity planning routes
        try:
            from core.enterprise_dashboard.routes.capacity import register_capacity_routes
            register_capacity_routes(app, self, admin_only, operator_or_admin)
            _log.info("[DASH] Capacity planning routes registered")
        except (ImportError, ValueError, TypeError) as exc:
            _log.debug("[DASH] Capacity routes unavailable: %s", exc)

        # Intelligence routes (Pillars 2, 4, 5, 8, 9, 10)
        try:
            from core.enterprise_dashboard.routes.intelligence import register_intelligence_routes
            register_intelligence_routes(app, self, admin_only, operator_or_admin)
            _log.info("[DASH] Intelligence routes registered (impact, root-cause, knowledge, risk, tests, docs)")
        except (ImportError, ValueError, TypeError) as exc:
            _log.debug("[DASH] Intelligence routes unavailable: %s", exc)

        # Self-Service Infrastructure Provisioning routes (Constitution v4.0 PLS-06)
        try:
            from core.enterprise_dashboard.routes.provisioning import register_provisioning_routes
            register_provisioning_routes(app, self, admin_only, operator_or_admin)
            _log.info("[DASH] Self-service provisioning routes registered (PLS-06)")
        except (ImportError, ValueError, TypeError) as exc:
            _log.debug("[DASH] Provisioning routes unavailable: %s", exc)

        # Success Metrics Trend routes (Constitution v4.0 MET-07/MET-08)
        try:
            from core.enterprise_dashboard.routes.metrics_trend import register_metrics_trend_routes
            register_metrics_trend_routes(app, self, admin_only, operator_or_admin)
            _log.info("[DASH] Success metrics trend routes registered (MET-07/MET-08)")
        except (ImportError, ValueError, TypeError) as exc:
            _log.debug("[DASH] Metrics trend routes unavailable: %s", exc)

        # Option strategy payoff-curve calculator (read-only decision support)
        try:
            from core.enterprise_dashboard.routes.payoff_calculator import register_payoff_calculator_routes
            register_payoff_calculator_routes(app, self, admin_only, operator_or_admin)
            _log.info("[DASH] Payoff calculator routes registered")
        except (ImportError, ValueError, TypeError) as exc:
            _log.debug("[DASH] Payoff calculator routes unavailable: %s", exc)

        # Real Estate Platform routes (Archived & Disabled - Trading Focus)
        pass

        return app

    # -- Config management ----------------------------------------------------

    def _resolve_defaults_path(self) -> Path:
        """Resolve the path to the index_config.defaults.json file.

        Checks the config for 'index_config_defaults_path' key, falls back
        to the default filename in the json/ folder.
        """
        return Path(self._cfg.get("index_config_defaults_path", "json/index_config.defaults.json"))

    def _resolve_config_path(self) -> Path:
        """Resolve the path to the active config.json file.

        Respects OPBUYING_INDEX_CONFIG env var, then 'index_config_path' config key,
        then falls back to 'json/config.json'.
        """
        config_file = os.environ.get("OPBUYING_INDEX_CONFIG", self._cfg.get("index_config_path", "json/config.json"))
        return Path(config_file)

    def _load_defaults(self) -> dict:
        """Load the defaults JSON file as a dict.

        Returns empty dict if file is missing or unreadable - never raises.
        """
        defaults_path = self._resolve_defaults_path()
        try:
            if defaults_path.is_file():
                return json.loads(defaults_path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        except (OSError, json.JSONDecodeError, ValueError) as e:
            _log.warning("[DASH] Failed to load defaults: %s", e)
        return {}

    def _validate_config_change(self, change: dict) -> dict:
        """Validate an Admin config delta against the canonical config contract.

        The Admin UI may submit a sparse delta, while the canonical validator
        expects an effective configuration. Therefore validation is performed
        in two layers:

        1. Validate the submitted Admin delta for Admin-specific constraints.
        2. Merge canonical defaults + persisted configuration + submitted delta
           and run the authoritative runtime/startup validator.

        No configuration is written by this method.
        """
        errors: list[Any] = []
        warnings: list[Any] = []

        # Only public configuration keys participate in Admin validation.
        public_change = {
            key: value
            for key, value in change.items()
            if not key.startswith("_")
        }

        # ------------------------------------------------------------
        # 1. Admin-delta validation
        # ------------------------------------------------------------
        for key, value in public_change.items():
            if key in ("BROKER_CONFIG",) and isinstance(value, dict):
                continue

            if key in {"PUBLIC_BASE_URL", "PUBLIC_BASE_URL_ADMIN_OVERRIDE"}:
                import urllib.parse

                from core.notifications.url_resolver import _is_loopback_url

                if not isinstance(value, str) or not value.strip():
                    errors.append({
                        "key": key,
                        "message": "PUBLIC_BASE_URL must be a non-empty URL",
                    })
                    continue

                candidate = value.strip()
                if not candidate.startswith(("http://", "https://")):
                    candidate = f"https://{candidate}"

                parsed = urllib.parse.urlparse(candidate)

                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    errors.append({
                        "key": key,
                        "message": "PUBLIC_BASE_URL must include a valid http(s) host",
                    })
                elif is_production_environment(self._cfg) and _is_loopback_url(candidate):
                    errors.append({
                        "key": key,
                        "message": (
                            "PUBLIC_BASE_URL cannot point to "
                            "localhost/loopback in production"
                        ),
                    })
                elif parsed.username or parsed.password:
                    errors.append({
                        "key": key,
                        "message": (
                            "PUBLIC_BASE_URL must not contain embedded credentials"
                        ),
                    })
                elif parsed.path not in ("", "/") or parsed.query or parsed.fragment:
                    warnings.append({
                        "key": key,
                        "message": (
                            "PUBLIC_BASE_URL should normally be an origin "
                            "without a path/query/fragment"
                        ),
                    })
                continue

            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                warnings.append({
                    "key": key,
                    "message": "References environment variable",
                })

        if errors:
            return {
                "valid": False,
                "errors": errors,
                "warnings": warnings,
            }

        # ------------------------------------------------------------
        # 2. Canonical effective-config validation
        # ------------------------------------------------------------
        config_path = self._resolve_config_path()

        try:
            if config_path.is_file():
                original = json.loads(
                    config_path.read_text(encoding="utf-8")
                )
            else:
                from core.defaults_loader import load_defaults_file

                project_root = Path(__file__).resolve().parents[2]
                original = load_defaults_file(
                    project_root,
                    "json/index_config.defaults.json",
                )

            if not isinstance(original, dict):
                return {
                    "valid": False,
                    "errors": [{
                        "key": "config",
                        "message": "Persisted configuration must be a JSON object",
                    }],
                    "warnings": warnings,
                }

            from core.config_validator import validate_config
            from core.defaults_loader import load_defaults_file

            project_root = Path(__file__).resolve().parents[2]
            defaults = load_defaults_file(
                project_root,
                "json/index_config.defaults.json",
            )

            # Defaults are only the validation baseline. They are NOT written
            # into the persisted config by the validate endpoint.
            validation_base = dict(defaults)
            validation_base.update(original)

            prospective = dict(validation_base)
            prospective.update(public_change)

            canonical_errors, canonical_warnings = validate_config(prospective)

        except Exception as exc:
            return {
                "valid": False,
                "errors": [{
                    "key": "config",
                    "message": (
                        "Canonical configuration validation failed: "
                        f"{exc}"
                    ),
                }],
                "warnings": warnings,
            }

        errors.extend(
            {"key": "config", "message": message}
            for message in canonical_errors
        )
        warnings.extend(
            {"key": "config", "message": message}
            for message in canonical_warnings
        )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


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
        # Load the persisted configuration before canonical validation.
        # _validate_config_change() validates the submitted Admin delta only;
        # the complete prospective configuration is validated below.
        config_path = self._resolve_config_path()
        try:
            if config_path.is_file():
                original = json.loads(config_path.read_text(encoding="utf-8"))
            else:
                # A brand-new Admin-managed config must start from the
                # repository's canonical defaults rather than an empty dict.
                # Do not duplicate defaults here: defaults_loader is the
                # single source of truth for bundled configuration defaults.
                from core.defaults_loader import load_defaults_file

                project_root = Path(__file__).resolve().parents[2]
                original = load_defaults_file(
                    project_root,
                    "json/index_config.defaults.json",
                )

            if not isinstance(original, dict):
                return {
                    "success": False,
                    "error": "Configuration validation failed",
                    "validation": {
                        "valid": False,
                        "errors": [{
                            "key": "config",
                            "message": "Persisted configuration must be a JSON object",
                        }],
                        "warnings": [],
                    },
                }

            # Only public keys participate in the persisted prospective config.
            public_change = {
                key: value
                for key, value in change.items()
                if not key.startswith("_")
            }

            # First preserve the existing Admin-delta validation behavior.
            delta_validation = self._validate_config_change(public_change)
            if not delta_validation["valid"]:
                return {
                    "success": False,
                    "error": "Configuration validation failed",
                    "validation": delta_validation,
                }

            # Canonical validator is the authoritative startup/runtime
            # configuration validator. Validate the COMPLETE EFFECTIVE
            # prospective configuration before any backup or disk mutation.
            #
            # Admin-managed config files may intentionally be sparse. Therefore
            # canonical defaults are used as the validation baseline only.
            # The persisted file itself is still based on `original`, so this
            # does not silently materialize 1,000+ default keys into the file.
            try:
                from core.config_validator import validate_config
                from core.defaults_loader import load_defaults_file

                project_root = Path(__file__).resolve().parents[2]
                defaults = load_defaults_file(
                    project_root,
                    "json/index_config.defaults.json",
                )

                validation_base = dict(defaults)
                validation_base.update(original)

                prospective = dict(validation_base)
                prospective.update(public_change)

                canonical_errors, canonical_warnings = validate_config(prospective)
            except Exception as exc:
                return {
                    "success": False,
                    "error": "Configuration validation failed",
                    "validation": {
                        "valid": False,
                        "errors": [{
                            "key": "config",
                            "message": (
                                "Canonical configuration validation failed: "
                                f"{exc}"
                            ),
                        }],
                        "warnings": delta_validation["warnings"],
                    },
                }

            if canonical_errors:
                return {
                    "success": False,
                    "error": "Configuration validation failed",
                    "validation": {
                        "valid": False,
                        "errors": [
                            {"key": "config", "message": message}
                            for message in canonical_errors
                        ],
                        "warnings": (
                            delta_validation["warnings"]
                            + [
                                {"key": "config", "message": message}
                                for message in canonical_warnings
                            ]
                        ),
                    },
                }

        except (OSError, json.JSONDecodeError, ValueError) as e:
            return {"success": False, "error": f"Failed to read config: {e}"}

        # Save original before any modifications (for safe rollback)
        current = dict(original)

        backup_path = config_path.with_suffix(f".json.backup.{int(time.time())}")
        try:
            Path(str(backup_path)).write_text(json.dumps(original, indent=4), encoding="utf-8")
        except (OSError, ValueError) as e:
            return {"success": False, "error": f"Backup failed: {e}"}

        applied = {}
        for key, value in change.items():
            if key.startswith("_"):
                continue
            current[key] = value
            applied[key] = value

        try:
            config_path.write_text(json.dumps(current, indent=4), encoding="utf-8")
        except (OSError, ValueError, TypeError) as e:
            try:
                config_path.write_text(json.dumps(original, indent=4), encoding="utf-8")
                _log.info("[DASH] Config write failed - original restored")
            except (OSError, ValueError, TypeError) as restore_exc:
                _log.critical("[DASH] Config write failed AND rollback failed! %s", restore_exc)
            return {"success": False, "error": f"Write failed, rolled back: {e}"}

        with self._config_lock:
            self._cfg.clear()
            self._cfg.update(current)
            # Re-freeze the config so the config property stays current
            self._cfg_frozen = _freeze(self._cfg)

        if any(k in applied for k in ("PUBLIC_BASE_URL", "PUBLIC_BASE_URL_ADMIN_OVERRIDE")):
            try:
                from core.notifications.url_resolver import invalidate_public_url_cache
                invalidate_public_url_cache()
            except Exception as cache_ex:
                _log.warning("[DASH] PUBLIC_BASE_URL cache invalidation failed: %s", cache_ex)

        # Synchronize EMAIL_TO and CHAT_ID to admin user permissions.
        # get_user_permission()/upsert_user_permission() never existed on
        # UserPermissionManager (only the plural get_user_permissions() and
        # update_user_permissions(username, data, admin_username) do) - this
        # always raised AttributeError, silently swallowed below, so this
        # sync has never actually run.
        if "EMAIL_TO" in applied or "CHAT_ID" in applied:
            try:
                from core.auth.user_signal_permissions import UserPermissionManager
                perm_mgr = UserPermissionManager.get_instance()
                if perm_mgr.get_user_permissions("admin") is not None:
                    _perm_updates: dict[str, Any] = {}
                    if "EMAIL_TO" in applied:
                        _perm_updates["email"] = str(applied["EMAIL_TO"])
                    if "CHAT_ID" in applied:
                        _perm_updates["telegram_chat_id"] = str(applied["CHAT_ID"])
                    perm_mgr.update_user_permissions("admin", _perm_updates, admin_username=username)
            except Exception as perm_sync_ex:
                # warning, not debug: a real failure here means EMAIL_TO/
                # CHAT_ID changes silently never reach the per-user
                # permission store an admin thinks they just updated.
                _log.warning("[DASH] User permission sync FAILED for keys %s: %s", list(applied.keys()), perm_sync_ex)

        # Synchronize to .env and os.environ
        try:
            from core.env_sync import sync_env_file
            sync_env_file(applied)
        except Exception as env_sync_ex:
            _log.warning("[DASH] .env sync FAILED for keys %s: %s", list(applied.keys()), env_sync_ex)

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
            return {"success": False, "error": "Invalid backup path - directory traversal blocked"}
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
            try:
                from core.notifications.url_resolver import invalidate_public_url_cache
                invalidate_public_url_cache()
            except Exception as cache_ex:
                _log.warning("[DASH] PUBLIC_BASE_URL cache invalidation failed during rollback: %s", cache_ex)
            self._log_config_audit(username, ["rollback"], [version], "config_rollback")
            return {"success": True, "restored_from": version, "keys_restored": len(backup_data)}
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as e:
            _log.warning("[DASH] Config rollback failed: %s", e)
            return {"success": False, "error": f"Rollback failed: {e}"}

    def _log_config_audit(self, username: str, keys: list, values: list, action: str) -> None:
        """Log a config change to the audit trail (config_audit.jsonl)."""
        try:
            audit_file = self._config_audit_log_path
            audit_file.parent.mkdir(parents=True, exist_ok=True)
            with open(audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "timestamp": time.time(),
                    "action": action,
                    "username": username,
                    "keys": keys,
                    "values": values,
                    "ip": "dashboard",
                }) + "\n")
        except (OSError, ValueError, TypeError) as exc:
            _log.warning("[DASH] Config audit write failed: %s", exc)

    def _get_config_audit_log(self, limit: int = 50) -> list[dict]:
        """Read the real config-change audit trail (who/what/when).

        _get_config_history() above only lists *.backup.* filenames with no
        username/keys - an admin previously had no way to see WHO changed
        WHAT in the config editor without grepping json/config_audit.jsonl
        by hand. Most recent entries first.
        """
        audit_file = self._config_audit_log_path
        if not audit_file.is_file():
            return []
        entries: list[dict] = []
        try:
            with open(audit_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except (ValueError, TypeError):
                        continue
        except OSError as exc:
            _log.warning("[DASH] Config audit read failed: %s", exc)
            return []
        entries.sort(key=lambda e: e.get("timestamp", 0), reverse=True)
        return entries[:limit]

    # -- Kill switch ----------------------------------------------------------

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
            except (ValueError, AttributeError, TypeError, RuntimeError) as e:
                _log.warning("[DASH] Control plane kill failed: %s", e)

        if "halt_callback" in self._bot_refs:
            try:
                self._bot_refs["halt_callback"](f"KILL by {username}: {reason}")
            except (ValueError, AttributeError, TypeError, RuntimeError) as e:
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

    # -- Notification helpers -------------------------------------------------

    def push_notification(self, message: str, severity: str = "INFO", category: str = "system", details: dict | None = None) -> Notification:
        """Push a notification from any part of the system.

        Can be called from bot refs or external code to broadcast
        real-time alerts to the dashboard.

        Example:
            dashboard.push_notification(
                "Daily loss limit reached",
                severity="CRITICAL",
                category="risk",
                details={"loss_pct": 95.0, "limit": 600},
            )

        """
        return self._notifications.push(
            message=message,
            severity=severity,
            category=category,
            source="system",
            details=details,
        )

    # -- Data helpers ---------------------------------------------------------

    def _read_state(self) -> dict:
        st: dict[str, Any] = {}
        try:
            sp = Path(self._state_path)
            if sp.is_file():
                raw = json.loads(sp.read_text(encoding="utf-8"))
                if raw and isinstance(raw, dict):
                    st = raw
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.warning("[DASH] Failed to read trader state: %s", exc)

        capital = st.get("capital") or st.get("base_capital") or st.get("current_capital") or 10000.0
        day_pnl = st.get("day_pnl") if st.get("day_pnl") is not None else (st.get("daily_pnl") if st.get("daily_pnl") is not None else (st.get("net_daily_pnl") if st.get("net_daily_pnl") is not None else 0.0))
        open_trades = st.get("open_trades") if st.get("open_trades") is not None else (st.get("open_positions") if st.get("open_positions") is not None else 0)
        # Previously fell back to plausible-looking fabricated numbers
        # (78.5% win rate, 4.2% drawdown, 14 trades/day, 2.45 Sharpe) with no
        # indication they weren't real - indistinguishable from genuine
        # performance data on the main dashboard landing page. Fall back to
        # neutral zeros instead, and flag is_demo_data so the UI can show a
        # real "no track record yet" state.
        has_real_stats = any(
            st.get(k) is not None
            for k in ("win_rate", "max_drawdown", "trades_today", "trade_count", "sharpe_ratio")
        )
        win_rate = st.get("win_rate") if st.get("win_rate") is not None else 0.0
        max_drawdown = st.get("max_drawdown") if st.get("max_drawdown") is not None else 0.0
        trades_today = st.get("trades_today") if st.get("trades_today") is not None else (st.get("trade_count") if st.get("trade_count") is not None else 0)
        sharpe_ratio = st.get("sharpe_ratio") if st.get("sharpe_ratio") is not None else 0.0

        return {
            "capital": capital,
            "base_capital": capital,
            "current_capital": capital,
            "day_pnl": day_pnl,
            "daily_pnl": day_pnl,
            "net_daily_pnl": day_pnl,
            "open_trades": open_trades,
            "open_positions": open_trades,
            "win_rate": win_rate,
            "max_drawdown": max_drawdown,
            "trades_today": trades_today,
            "trade_count": trades_today,
            "sharpe_ratio": sharpe_ratio,
            "is_demo_data": not has_real_stats,
            "risk_halted": st.get("risk_halted", False),
            "circuit_breaker": st.get("circuit_breaker", "Closed"),
            "execution_mode": st.get("execution_mode", "LIVE_PAPER"),
            "status": st.get("status", "RUNNING"),
            "hard_halt": st.get("hard_halt", False),
        }

    def _load_recent_trades(self, days: int = 30, n: int = 100) -> list:
        """Load recent trades from the trades database.

        Uses core.performance_metrics.load_trades if available.
        Returns fallback demo trades list if empty - every trade dict from
        either path now carries is_demo_data so a fresh/low-activity account
        can't be mistaken for one with real history (this fallback feeds
        /api/system/performance, /api/system/trades, and /api/trade-journal
        - none of them previously marked it).

        Args:
            days: Lookback window in days. None = all time.
            n: Max number of trades to return.

        Returns:
            List of trade dicts, newest last, up to n items.

        """
        try:
            from core.performance_metrics import load_trades
            trades = load_trades(self._db_path, days=days if days > 0 else None)
            if trades:
                for t in trades:
                    t.setdefault("is_demo_data", False)
                return trades[-n:]
        except (ImportError, ValueError, RuntimeError, OSError) as e:
            _log.debug("[DASH] load_trades failed: %s", e)

        # Sample trade records shown only when the real trades DB has no
        # history yet (fresh install / no trades executed) - never real data.
        demo_trades = [
            {"entry_time": "2026-08-14 11:15:00", "exit_time": "2026-08-14 11:42:30", "symbol": "NIFTY26AUG24500CE", "direction": "BUY", "quantity": 50, "entry_price": 145.20, "expected_price": 145.10, "filled_price": 145.20, "exit_price": 178.60, "net_pnl": 1670.00, "exit_reason": "TARGET_HIT", "slippage": 0.10, "latency_ms": 11.2},
            {"entry_time": "2026-08-14 14:10:00", "exit_time": "2026-08-14 14:38:15", "symbol": "BANKNIFTY26AUG51200PE", "direction": "BUY", "quantity": 25, "entry_price": 230.50, "expected_price": 230.30, "filled_price": 230.50, "exit_price": 285.00, "net_pnl": 1362.50, "exit_reason": "TRAILING_SL", "slippage": 0.20, "latency_ms": 13.5},
            {"entry_time": "2026-08-17 10:25:00", "exit_time": "2026-08-17 11:20:00", "symbol": "RELIANCE", "direction": "BUY", "quantity": 100, "entry_price": 2850.00, "expected_price": 2849.80, "filled_price": 2850.00, "exit_price": 2920.00, "net_pnl": 7000.00, "exit_reason": "PROFIT_TARGET", "slippage": 0.20, "latency_ms": 12.0},
            {"entry_time": "2026-08-17 13:40:00", "exit_time": "2026-08-17 14:05:00", "symbol": "INFY", "direction": "SELL", "quantity": 150, "entry_price": 1820.00, "expected_price": 1820.15, "filled_price": 1820.00, "exit_price": 1804.00, "net_pnl": 2400.00, "exit_reason": "TARGET_HIT", "slippage": 0.15, "latency_ms": 10.8},
            {"entry_time": "2026-08-18 14:50:00", "exit_time": "2026-08-18 15:10:00", "symbol": "TCS", "direction": "BUY", "quantity": 40, "entry_price": 4180.00, "expected_price": 4179.75, "filled_price": 4180.00, "exit_price": 4175.00, "net_pnl": -200.00, "exit_reason": "STOP_LOSS", "slippage": 0.25, "latency_ms": 14.1},
        ]
        for t in demo_trades:
            t["is_demo_data"] = True
        return demo_trades[-n:]

    _HEALTH_STATUS_MAP = {"OK": "healthy", "WARN": "degraded", "FAIL": "down"}

    async def _check_health(self) -> dict:
        """Real system health, via core.health_checker.run_full_health_check().

        Previously every field here (checks, mttr, incidents) was a hardcoded
        literal that always reported 6/6 healthy regardless of actual DB
        integrity, ML model state, or broker connectivity - it could never
        show a degraded or down component even during a real outage. This is
        the "System Health" screen for a real-money trading bot, so that gap
        mattered more than most.
        """
        state = self._read_state()
        uptime_secs = time.time() - self._startup_ts if hasattr(self, "_startup_ts") else 7200

        checks: list[dict[str, Any]] = []
        incidents: list[dict[str, Any]] = []
        incident_stats: dict[str, Any] = {}
        try:
            from core.health_checker import run_full_health_check
            report = run_full_health_check(cfg=dict(self._cfg), db_path=self._db_path)
            now_str = time.strftime("%Y-%m-%d %H:%M:%S")
            checks = [
                {
                    "component": f"{r.category}: {r.name}",
                    "status": self._HEALTH_STATUS_MAP.get(r.status, "down"),
                    "detail": r.message or (f"value={r.value}" if r.value is not None else r.status),
                    "last_check": now_str,
                }
                for r in report.results
            ]
        except (ImportError, ValueError, TypeError, OSError, AttributeError) as exc:
            _log.warning("[DASH] run_full_health_check failed: %s", exc)

        try:
            import datetime as _dt

            from core.incident_command_system import get_incident_commander
            commander = get_incident_commander(dict(self._cfg))
            incident_stats = commander.get_stats()

            def _to_row(inc: dict[str, Any]) -> dict[str, Any]:
                resolved = inc.get("status") in ("RESOLVED", "CLOSED")
                duration_seconds = None
                end_ts = inc.get("resolved_at") or inc.get("closed_at")
                if end_ts:
                    try:
                        created = _dt.datetime.fromisoformat(inc["created_at"])
                        ended = _dt.datetime.fromisoformat(end_ts)
                        duration_seconds = round((ended - created).total_seconds())
                    except (ValueError, TypeError, KeyError):
                        duration_seconds = None
                return {
                    "time": inc.get("created_at", ""),
                    "category": inc.get("source", ""),
                    "severity": inc.get("severity", ""),
                    "description": inc.get("title") or inc.get("description", ""),
                    "resolved": resolved,
                    "duration_seconds": duration_seconds,
                }

            incidents = [_to_row(i) for i in commander.get_open_incidents()]
        except (ImportError, ValueError, TypeError, OSError, AttributeError) as exc:
            _log.debug("[DASH] incident commander unavailable: %s", exc)

        return {
            "status": "ok",
            "paused": self._pause_event.is_set() if self._pause_event is not None else False,
            "daily_pnl": state.get("daily_pnl", 0.0),
            "open_positions": state.get("open_positions", 0),
            "hard_halt": state.get("hard_halt", False),
            "uptime": uptime_secs,
            "uptime_human": f"{int(uptime_secs//3600)}h{int(uptime_secs%3600//60)}m",
            "capital": state.get("base_capital", state.get("capital", 10000.0)),
            "execution_mode": state.get("execution_mode", self._cfg.get("execution_mode", "paper")),
            "circuit_breaker": state.get("circuit_breaker", "Closed"),
            "timestamp": time.time(),
            # No real MTTR/MTBF time-series computation exists yet (would need
            # resolved-incident create->resolve deltas) - these are real
            # incident *counts*, not a fabricated per-category breakdown.
            "incident_stats": incident_stats,
            "incidents": incidents,
            "checks": checks,
        }

    def _get_signals(self, n: int = 50) -> list:
        if self._signal_log is not None:
            sigs = self._signal_log.recent(n)
            if sigs:
                for s in sigs:
                    s.setdefault("reasoning", "Autonomous signal validation passed")
                    s.setdefault("sentiment", "BULLISH")
                return sigs  # type: ignore[no-any-return]

        import datetime
        now = datetime.datetime.now()
        # Clamp post-market close (15:30 IST) to last active market hour
        if now.hour > 15 or (now.hour == 15 and now.minute > 30):
            base_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
        else:
            base_time = now

        return [
            {"index": "NIFTY 50", "symbol": "NIFTY26AUG24050CE", "score": 8.8, "direction": "BUY", "strength": "STRONG", "timestamp": base_time.strftime("%Y-%m-%d %H:%M:%S")},
            {"index": "BANK NIFTY", "symbol": "BANKNIFTY26AUG57100PE", "score": 7.5, "direction": "BUY", "strength": "MODERATE", "timestamp": (base_time - datetime.timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")},
            {"index": "FIN NIFTY", "symbol": "FINNIFTY26AUG26000CE", "score": 9.2, "direction": "BUY", "strength": "VERY STRONG", "timestamp": (base_time - datetime.timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")},
            {"index": "SENSEX", "symbol": "SENSEX26AUG79200CE", "score": 6.8, "direction": "BUY", "strength": "MODERATE", "timestamp": (base_time - datetime.timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M:%S")},
        ]


def create_enterprise_dashboard(
    config: dict[str, Any] | None = None,
    **refs: Any,
) -> EnterpriseDashboard:
    """Create and wire an EnterpriseDashboard instance."""
    dashboard = EnterpriseDashboard(config=config)
    dashboard.wire_bot_refs(**refs)
    return dashboard


__all__ = [
    "DashboardNotifier",
    "EnterpriseDashboard",
    "Notification",
    "NotificationManager",
    "create_enterprise_dashboard",
]

# ── CLI Entry Point ──────────────────────────────────────────────────────────────

def main() -> None:
    """Start the enterprise dashboard server.

    Reads config from ``config.json`` (or ``OPBUYING_INDEX_CONFIG`` env),
    creates the dashboard instance, and serves it via uvicorn on the
    configured host/port (default 0.0.0.0:8765).
    """
    import io
    import json
    import sys
    from pathlib import Path

    # Ensure stdout/stderr have valid streams with isatty() for frozen/windowed executables
    class SafeStream(io.StringIO):
        def isatty(self) -> bool:
            return False
        def write(self, s: str) -> int:
            return len(s)
        def flush(self) -> None:
            pass

    if sys.stdout is None:
        sys.stdout = SafeStream()
    if sys.stderr is None:
        sys.stderr = SafeStream()
    if sys.stdin is None:
        sys.stdin = io.StringIO()

    import uvicorn

    config_path = os.environ.get("OPBUYING_INDEX_CONFIG", "json/config.json")
    cfg = {}
    try:
        p = Path(config_path)
        if p.is_file():
            cfg = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _log.warning("[DASH] Config load skipped: %s", exc)

    dashboard = EnterpriseDashboard(config=cfg)
    host = str(cfg.get("web_dashboard_host", "127.0.0.1"))
    port = int(cfg.get("web_dashboard_port", 8000))
    _log.info("[DASH] Starting on %s:%s", host, port)

    # Disable terminal color formatting to prevent isatty issues in frozen apps
    log_cfg = uvicorn.config.LOGGING_CONFIG.copy()
    if "formatters" in log_cfg:
        for fmt in log_cfg["formatters"].values():
            if isinstance(fmt, dict):
                fmt["use_colors"] = False

    uvicorn.run(dashboard.app, host=host, port=port, log_config=log_cfg, log_level="info")


if __name__ == "__main__":
    main()

