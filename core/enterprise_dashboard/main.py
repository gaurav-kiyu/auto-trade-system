"""
Enterprise Web Dashboard - premium FastAPI + Jinja2 + Tailwind CSS UI.

Provides a world-class admin interface with full auth, RBAC, config management,
kill switch, and monitoring.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from collections import deque
from typing import AsyncGenerator


from core.auth.csrf import csrf_protection
from core.auth.dependencies import AuthDependencies
from core.auth.handler import AuthHandler
from core.auth.routes import create_auth_router

_log = logging.getLogger(__name__)

# ── Standardized Error Response --------------------------------------------------


def _error_response(message: str, code: int, **kwargs: Any) -> dict:
    """Standardized error response body for all API endpoints.

    Usage:
        return JSONResponse(_error_response("Not found", 404), status_code=404)
        return JSONResponse(_error_response("Rate limited", 429, retry_after=60), status_code=429)
    """
    resp: dict[str, Any] = {"error": message, "code": code}
    resp.update(kwargs)
    return resp


# ── Notification Manager ──────────────────────────────────────────────────────

class Notification:
    """A single system notification with severity, message, and metadata."""

    def __init__(
        self,
        message: str,
        severity: str = "INFO",
        category: str = "system",
        source: str = "dashboard",
        details: dict | None = None,
    ):
        self.id = uuid.uuid4().hex[:12]
        self.message = message
        self.severity = severity.upper()  # INFO, WARNING, ERROR, CRITICAL
        self.category = category
        self.source = source
        self.timestamp = time.time()
        self.details = details or {}
        self.acknowledged = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "message": self.message,
            "severity": self.severity,
            "category": self.category,
            "source": self.source,
            "timestamp": self.timestamp,
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.timestamp)),
            "timestamp_human": time.strftime("%H:%M:%S", time.localtime(self.timestamp)),
            "acknowledged": self.acknowledged,
        }


class NotificationManager:
    """Thread-safe notification manager with SSE subscriber support.

    Holds up to ``maxlen`` notifications in memory. Subscribers receive
    new notifications via an async generator for SSE streaming.
    """

    def __init__(self, maxlen: int = 200):
        self._notifications: deque[Notification] = deque(maxlen=maxlen)
        self._lock = threading.RLock()
        self._subscribers: list[asyncio.Queue] = []
        self._sub_lock = threading.RLock()

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._notifications)

    def push(self, message: str, severity: str = "INFO", category: str = "system", source: str = "dashboard", details: dict | None = None) -> Notification:
        """Create and broadcast a new notification."""
        notif = Notification(
            message=message,
            severity=severity,
            category=category,
            source=source,
            details=details,
        )
        with self._lock:
            self._notifications.append(notif)
        with self._sub_lock:
            dead: list[asyncio.Queue] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(notif.to_dict())
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)
        _log.debug("[NOTIFY] %s: %s", severity, message)
        return notif

    def recent(self, n: int = 50) -> list[dict]:
        """Return the ``n`` most recent notifications as dicts."""
        with self._lock:
            return [n.to_dict() for n in list(self._notifications)[-n:]]

    def acknowledge(self, notif_id: str) -> bool:
        """Mark a notification as acknowledged by ID."""
        with self._lock:
            for n in self._notifications:
                if n.id == notif_id:
                    n.acknowledged = True
                    return True
        return False

    def acknowledge_all(self, severity: str | None = None) -> int:
        """Acknowledge all notifications, optionally filtered by severity."""
        count = 0
        with self._lock:
            for n in self._notifications:
                if severity is None or n.severity == severity.upper():
                    n.acknowledged = True
                    count += 1
        return count

    def clear(self) -> int:
        """Clear all notifications. Returns the count cleared."""
        with self._lock:
            count = len(self._notifications)
            self._notifications.clear()
            return count

    async def subscribe(self) -> AsyncGenerator[dict, None]:
        """Async generator for SSE streaming. Yields notification dicts as they arrive.

        Usage:
            async for notif in manager.subscribe():
                yield f"data: {json.dumps(notif)}\n\n"
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        with self._sub_lock:
            self._subscribers.append(q)
        try:
            while True:
                notif = await q.get()
                yield notif
        except asyncio.CancelledError:
            pass
        finally:
            with self._sub_lock:
                if q in self._subscribers:
                    self._subscribers.remove(q)


class DashboardNotifier:
    """Lightweight HTTP client for pushing notifications to the dashboard API.

    Posts to POST /api/system/notifications/push. Thread-safe, silently fails
    when dashboard is unreachable. Auto-disables after 10 consecutive failures.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8765", timeout: float = 2.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._lock = threading.RLock()
        self._enabled = True
        self._consecutive_failures = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def disable(self) -> None:
        with self._lock:
            self._enabled = False

    def send(self, message: str, severity: str = "INFO", category: str = "system", source: str = "bot", details: dict | None = None) -> bool:
        if not self._enabled:
            return False
        try:
            import requests as _req
            resp = _req.post(
                f"{self._base_url}/api/system/notifications/push",
                json={"message": message, "severity": severity, "category": category, "source": source, "details": details or {}},
                timeout=self._timeout,
            )
            if resp.status_code in (200, 201):
                with self._lock:
                    self._consecutive_failures = 0
                return True
            self._track_failure()
            return False
        except Exception:
            self._track_failure()
            return False

    def _track_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 10:
                self._enabled = False

    def push_bot_start(self, mode: str = "paper") -> None:
        self.send("Bot started — mode=" + mode, severity="INFO", category="system")

    def push_trade_entry(self, symbol: str, direction: str, score: int, price: float) -> None:
        self.send("Trade entered: {symbol} {direction} @ {price:.2f} (score={score})", severity="INFO", category="trade", details={"symbol": symbol, "direction": direction, "score": score, "price": price})

    def push_trade_exit(self, symbol: str, reason: str, pnl: float) -> None:
        sev = "WARNING" if pnl < 0 else "INFO"
        self.send("Trade exited: {symbol} {reason} P&L={pnl:+.2f}", severity=sev, category="trade", details={"symbol": symbol, "reason": reason, "pnl": pnl})

    def push_risk_breach(self, metric: str, value: float, limit: float) -> None:
        self.send("Risk breach: {metric}={value:.2f} (limit={limit:.2f})", severity="CRITICAL", category="risk", details={"metric": metric, "value": value, "limit": limit})

    def push_shutdown(self, reason: str = "User initiated") -> None:
        self.send("Bot shutting down: " + reason, severity="INFO", category="system")



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



# -- Error-rate tracking for market data providers ------------------------------

_PROVIDER_REQUESTS: list[float] = []
_LOCK = threading.RLock()


def _record_provider_request() -> None:
    """Record a request timestamp for rate/error tracking."""
    global _PROVIDER_REQUESTS
    now = time.time()
    with _LOCK:
        _PROVIDER_REQUESTS.append(now)
        # Keep only last 5 minutes of requests
        _PROVIDER_REQUESTS = [t for t in _PROVIDER_REQUESTS if now - t < 300]


def _get_provider_error_info(details: dict) -> dict:
    """Get error-rate info for each adapter from health details."""
    error_info: dict[str, Any] = {}
    now = time.time()
    for name, detail in details.items():
        if not isinstance(detail, dict):
            continue
        error_rate = detail.get("error_rate", 0.0)
        last_error = detail.get("last_error", None)
        last_error_ts = detail.get("last_error_ts", None)
        error_info[name] = {
            "error_rate": error_rate,
            "last_error": last_error,
            "last_error_ts": last_error_ts,
            "error_age": round(now - last_error_ts, 2) if last_error_ts else None,
        }
    return error_info


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
        self._config_lock: threading.Lock = threading.RLock()

        # Create the FastAPI app
        self.app = self._create_app()

        # Start background session cleanup
        self._start_session_cleanup()

        # Notification manager for real-time alerts
        self._notifications = NotificationManager(maxlen=200)

    @property
    def config(self) -> MappingProxyType:
        """Read-only frozen view of the active config."""
        return self._cfg_frozen

    def _start_session_cleanup(self) -> None:
        """Background thread to purge expired sessions every 15 minutes."""
        self._session_stop = threading.Event()

        def _cleanup_loop():
            while not self._session_stop.is_set():
                if self._session_stop.wait(900):
                    break
                try:
                    self._auth.purge_expired_sessions()
                except (ValueError, AttributeError, OSError) as exc:
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
        except (OSError, PermissionError) as e:
            _log.debug("[DASH] Cannot create static dir: %s", e)
            return None

    def wire_bot_refs(self, **refs: Any) -> None:
        """Wire external bot references.

        Only overwrites internal references if the supplied value is not None,
        preserving constructor defaults. This prevents callers that pass
        ``pause_event=None`` from accidentally overwriting the default
        ``threading.Event()``.
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

    def _create_app(self) -> FastAPI:
        self._startup_ts = time.time()

        # Register runtime invariant checks on startup
        try:
            from core.invariants.checks import register_all as _register_invariants
            _register_invariants()
            _log.info("[DASH] Runtime invariant checks registered")
        except (ImportError, ValueError, AttributeError) as exc:
            _log.debug("[DASH] Invariant registration skipped: %s", exc)

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            _log.info("[DASH] Enterprise dashboard started")
            # Start periodic Prometheus gauge updater for market data providers
            _metrics_stop = threading.Event()

            def _update_provider_metrics_loop():
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

            def _slo_health_poller_loop():
                while not _slo_stop.is_set():
                    try:
                        from core.slo_governance import ingest_health_report, get_slo_governance
                        from core.health_checker import run_full_health_check
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
            version="2.53.0",
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
        csrf_protection.exempt("/api/auth/logout")
        csrf_protection.exempt("/api/system/health/docker")
        csrf_protection.exempt("/signals/inject")
        csrf_protection.exempt("/static")
        csrf_protection.exempt("/api/system/self-test")
        # SSE notification stream (long-lived connection, not a browser form)
        csrf_protection.exempt("/api/system/notifications/stream")
        # Fundamentals API endpoints (programmatic access, not browser forms)
        csrf_protection.exempt("/api/fundamentals")
        csrf_protection.exempt("/api/docs")
        csrf_protection.exempt("/api/redoc")
        csrf_protection.exempt("/openapi.json")

        # -- Middleware: Security Headers ----------------------------------------

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
            # HSTS: 1 year, include subdomains, preload - only on HTTPS
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

        # -- API Rate Limiter -------------------------------------------------

        _rate_limit_store: dict[str, list[float]] = {}
        _rate_limit_lock = threading.RLock()
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
        async def rate_limit_middleware(request: Request, call_next: Any):
            path = request.url.path
            if path.startswith("/api/") and not path.startswith("/api/system/health/docker"):
                ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "127.0.0.1").split(",")[0].strip()
                is_admin = path.startswith("/api/config") or path.startswith("/api/system/kill") or path.startswith("/api/system/resume") or path.startswith("/api/system/self-test") or path.startswith("/api/system/diagnostics")
                limit = ADMIN_RATE_LIMIT if is_admin else API_RATE_LIMIT
                if not _check_rate_limit(ip, limit):
                    return JSONResponse(_error_response("Rate limit exceeded", 429, retry_after=60), status_code=429)
            response = await call_next(request)
            return response

        # -- Middleware: Request ID + Tracing -------------------------------------

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

        # -- Middleware: CSRF ----------------------------------------------------

        @app.middleware("http")
        async def csrf_middleware(request: Request, call_next: Any):
            await csrf_protection.validate(request)
            response = await call_next(request)
            # Ensure CSRF cookie is set on GET responses (if missing)
            try:
                await csrf_protection.ensure_cookie_set(request, response)
            except (ValueError, AttributeError, TypeError) as exc:
                _log.warning("[DASH] CSRF cookie set failed: %s", exc)
            return response

        # -- Error handlers -----------------------------------------------------

        @app.exception_handler(403)
        async def forbidden_error(request: Request, exc: Any):
            nonce = getattr(request.state, 'nonce', '')
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
        async def not_found(request: Request, exc: Any):
            nonce = getattr(request.state, 'nonce', '')
            if "application/json" in request.headers.get("accept", ""):
                return JSONResponse(_error_response("Not found", 404), status_code=404)
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

        def _require_admin_page(request: Request):
            """Check session auth and admin role, return (user, error_response)."""
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

        from core.enterprise_dashboard.routes.pages import register_page_routes
        from core.enterprise_dashboard.routes.system import register_system_routes
        from core.enterprise_dashboard.routes.admin import register_admin_routes
        from core.enterprise_dashboard.routes.risk import register_risk_routes
        from core.enterprise_dashboard.routes.monitoring import register_monitoring_routes
        from core.enterprise_dashboard.routes.fundamentals import register_fundamentals_routes
        from core.enterprise_dashboard.routes.webhooks import register_webhook_routes

        register_page_routes(app, self, _require_admin_page)
        register_system_routes(app, self, admin_only, operator_or_admin)
        register_admin_routes(app, self, admin_only, operator_or_admin)
        register_risk_routes(app, self, admin_only, operator_or_admin)
        register_monitoring_routes(app, self, admin_only, operator_or_admin)
        register_fundamentals_routes(app, self, admin_only, operator_or_admin)
        register_webhook_routes(app, self, admin_only, operator_or_admin)

        return app

    # -- Config management ----------------------------------------------------

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

        Returns empty dict if file is missing or unreadable - never raises.
        """
        defaults_path = self._resolve_defaults_path()
        try:
            if defaults_path.is_file():
                return json.loads(defaults_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError) as e:
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
            self._log_config_audit(username, ["rollback"], [version], "config_rollback")
            return {"success": True, "restored_from": version, "keys_restored": len(backup_data)}
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as e:
            _log.warning("[DASH] Config rollback failed: %s", e)
            return {"success": False, "error": f"Rollback failed: {e}"}

    def _log_config_audit(self, username: str, keys: list, values: list, action: str) -> None:
        """Log a config change to the audit trail (config_audit.jsonl)."""
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
        except (OSError, ValueError, TypeError) as exc:
            _log.warning("[DASH] Config audit write failed: %s", exc)

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
        try:
            sp = Path(self._state_path)
            if sp.is_file():
                return json.loads(sp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
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
        except (ImportError, ValueError, RuntimeError, OSError) as e:
            _log.debug("[DASH] load_trades failed: %s", e)
            return []

    async def _check_health(self) -> dict:
        state = self._read_state()
        uptime_secs = time.time() - self._startup_ts if hasattr(self, '_startup_ts') else 0
        return {
            "status": "ok",
            "paused": self._pause_event.is_set() if self._pause_event is not None else False,
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


__all__ = [
    "DashboardNotifier",
    "EnterpriseDashboard",
    "Notification",
    "NotificationManager",
    "create_enterprise_dashboard",
]

