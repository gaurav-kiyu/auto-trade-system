"""
Enterprise Web Dashboard - premium FastAPI + Jinja2 + Tailwind CSS UI.

Provides a world-class admin interface with full auth, RBAC, config management,
kill switch, and monitoring.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import secrets
import sqlite3
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

from collections import deque
from typing import AsyncGenerator


from core.auth.csrf import csrf_protection
from core.auth.dependencies import AuthDependencies
from core.auth.handler import AuthHandler
from core.auth.routes import create_auth_router
from core.db_utils import get_connection as _get_db_conn

_log = logging.getLogger(__name__)


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
                    return JSONResponse({"error": "Rate limit exceeded", "retry_after": 60}, status_code=429)
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
                return JSONResponse({"error": "Forbidden", "code": 403}, status_code=403)
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

        # -- HTML Routes -------------------------------------------------------

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

        # -- Helper: require admin role for HTML pages --------------------------
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

        # -- API Routes: System ------------------------------------------------

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

        # -- Config management API (admin only) --------------------------------

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

        @app.get("/api/config/drift")
        async def api_config_drift(user: Any = Depends(admin_only)):
            """Detect configuration drift between live config and defaults.

            Compares every key in the live config dict against the corresponding
            default value in index_config.defaults.json. Reports:
              - changed: keys whose live value differs from default
              - added:   keys present in live config but absent from defaults
              - removed: keys present in defaults but absent from live config

            Returns:
                Dict with drift summary: total keys in each category,
                list of change details (key, old/default, new/current),
                and a drift_pct score.
            """
            try:
                defaults = self._load_defaults()
                live = dict(self._cfg)
                changed: list[dict[str, Any]] = []
                added: list[str] = []
                removed: list[str] = []

                # Keys in both: check for differences
                for key in set(live) & set(defaults):
                    live_val = live[key]
                    default_val = defaults[key]
                    # Serialize consistently for comparison
                    live_s = json.dumps(live_val, sort_keys=True, default=str)
                    default_s = json.dumps(default_val, sort_keys=True, default=str)
                    if live_s != default_s:
                        changed.append({
                            "key": key,
                            "default": default_val,
                            "current": live_val,
                        })

                # Keys only in live config
                for key in set(live) - set(defaults):
                    if not key.startswith("_"):  # skip internal keys
                        added.append(key)

                # Keys only in defaults
                for key in set(defaults) - set(live):
                    removed.append(key)

                total_keys = len(set(live) | set(defaults))
                drift_count = len(changed) + len(added) + len(removed)
                drift_pct = round((drift_count / max(total_keys, 1)) * 100, 1)

                return {
                    "drift_pct": drift_pct,
                    "drift_count": drift_count,
                    "total_keys": total_keys,
                    "changed_count": len(changed),
                    "added_count": len(added),
                    "removed_count": len(removed),
                    "changes": changed,
                    "added_keys": added,
                    "removed_keys": removed[:50],  # limit output size
                    "timestamp": time.time(),
                }
            except (ValueError, TypeError, KeyError, OSError) as exc:
                _log.warning("[DASH] Config drift check failed: %s", exc)
                return {"status": "error", "detail": str(exc)}

        @app.post("/api/config/rollback/{version}")
        async def api_rollback_config(
            version: str,
            user: Any = Depends(admin_only),
        ):
            return self._rollback_config(version, user.username)

        # -- Kill switch API ---------------------------------------------------

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

        # -- Broker info API -----------------------------------------------------

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

        # -- ML status API -------------------------------------------------------

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

        # -- Bot control API (admin + operator) --------------------------------

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

        # -- Observability: Docker health check ---------------------------------

        @app.get("/api/system/ws-status")
        async def api_ws_status(user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Get WebSocket feed status - connection health, LTP cache, and tick count.

            Reads ``ws_feed_manager`` (``KiteTickerFeedManager`) or
            ``nse_ws_adapter`` (``NseIndexWebSocketAdapter``) from ``_bot_refs``.

            Returns:
                Dict with ``connected``, ``enabled``, ``cache_size``,
                ``tick_mode``, ``has_feed``, or ``{"status": "unavailable"}``.
            """
            # Check self-contained NSE WebSocket adapter first
            ws_adapter = self._bot_refs.get("nse_ws_adapter")
            if ws_adapter is not None:
                try:
                    st = ws_adapter.status()
                    return {
                        "status": "ok",
                        "adapter_type": "NseIndexWebSocketAdapter",
                        "connected": st.get("connected", False),
                        "enabled": st.get("enabled", False),
                        "cache_size": st.get("cache_size", 0),
                        "cache_ttl": st.get("cache_ttl", 5.0),
                        "tick_mode": st.get("tick_mode", "ltp"),
                        "has_kws": st.get("has_kws", False),
                        "tokens": st.get("tokens", {}),
                        "index_tokens": st.get("index_tokens", []),
                    }
                except (AttributeError, TypeError, ValueError) as exc:
                    _log.debug("[DASH] NSE WS adapter status error: %s", exc)

            # Fallback: legacy KiteTickerFeedManager
            ws_feed = self._ws_feed_manager
            if ws_feed is not None:
                try:
                    st = ws_feed.status()
                    return {
                        "status": "ok",
                        "adapter_type": "KiteTickerFeedManager",
                        "connected": st.get("connected", False),
                        "enabled": st.get("enabled", False),
                        "cache_size": st.get("ltp_cache_size", 0),
                        "tick_mode": st.get("tick_mode", "ltp"),
                        "has_feed": st.get("has_kws", False),
                        "reconnect_count": st.get("reconnect_count", 0),
                        "last_error": st.get("last_error", ""),
                    }
                except (AttributeError, TypeError, ValueError) as exc:
                    _log.debug("[DASH] WS feed status error: %s", exc)

            return {
                "status": "unavailable",
                "detail": "No WebSocket feed wired - set kite_ticker_enabled=true in config",
            }

        @app.get("/api/system/health/docker")
        async def docker_health_check():
            """Docker health check endpoint (no auth required)."""
            state = self._read_state()
            db_ok = False
            try:
                conn = _get_db_conn(self._db_path, timeout=2, row_factory=False)
                conn.execute("SELECT 1")
                conn.close()
                db_ok = True
            except (OSError, sqlite3.Error, ValueError) as exc:
                _log.warning("[DASH] Health check DB probe failed: %s", exc)
            auth_db_ok = False
            try:
                conn = _get_db_conn(self._auth._db_path, timeout=2, row_factory=False)
                conn.execute("SELECT 1")
                conn.close()
                auth_db_ok = True
            except (OSError, sqlite3.Error, ValueError) as exc:
                _log.warning("[DASH] Health check auth DB probe failed: %s", exc)
            uptime_secs = time.time() - self._startup_ts if hasattr(self, '_startup_ts') else 0
            return {
                "status": "healthy" if (db_ok and auth_db_ok and not state.get("hard_halt")) else "degraded",
                "version": "2.53.0",
                "uptime_seconds": uptime_secs,
                "uptime_human": f"{int(uptime_secs//3600)}h{int(uptime_secs%3600//60)}m",
                "db_connected": db_ok,
                "auth_db_connected": auth_db_ok,
                "paused": self._pause_event.is_set() if self._pause_event is not None else False,
                "hard_halt": state.get("hard_halt", False),
                "open_positions": state.get("open_positions", 0),
                "timestamp": time.time(),
            }

        # -- Change Management API -------------------------------------------------

        @app.get("/api/changes/pending")
        async def api_changes_pending(user: Any = Depends(admin_only)):
            """List all pending change proposals awaiting approval."""
            try:
                from core.change_management import get_change_manager
                mgr = get_change_manager(self._cfg)
                pending = mgr.list_pending()
                return {
                    "pending": [p.to_dict() for p in pending],
                    "count": len(pending),
                    "timestamp": time.time(),
                }
            except ImportError:
                return {"status": "unavailable", "detail": "ChangeManager not available"}
            except (ValueError, TypeError, AttributeError) as exc:
                _log.warning("[DASH] Changes pending failed: %s", exc)
                return {"status": "error", "detail": str(exc)}

        @app.post("/api/changes/propose")
        async def api_changes_propose(request: Request, user: Any = Depends(admin_only)):
            """Propose a new configuration or parameter change.

            JSON body:
                change_type: str (CONFIG|STRATEGY_PARAM|FEATURE_FLAG|INFRASTRUCTURE)
                target_key: str
                current_value: any
                proposed_value: any
                reason: str
                risk_level: str (NORMAL|HIGH|CRITICAL)
            """
            try:
                body = await request.json()
                from core.change_management import get_change_manager
                mgr = get_change_manager(self._cfg)
                prop = mgr.propose(
                    change_type=body.get("change_type", "CONFIG"),
                    target_key=body.get("target_key", ""),
                    current_value=body.get("current_value"),
                    proposed_value=body.get("proposed_value"),
                    reason=body.get("reason", "No reason provided"),
                    proposed_by=user.username,
                    risk_level=body.get("risk_level", "NORMAL"),
                )
                return {
                    "success": True,
                    "change_id": prop.id_,
                    "status": prop.status.value,
                    "proposal": prop.to_dict(),
                    "timestamp": time.time(),
                }
            except ImportError:
                return {"status": "unavailable", "detail": "ChangeManager not available"}
            except (ValueError, TypeError, AttributeError, RuntimeError) as exc:
                _log.warning("[DASH] Change propose failed: %s", exc)
                return {"status": "error", "detail": str(exc)}

        @app.post("/api/changes/approve/{change_id}")
        async def api_changes_approve(change_id: str, user: Any = Depends(admin_only)):
            """Approve a pending change proposal."""
            try:
                from core.change_management import get_change_manager
                mgr = get_change_manager(self._cfg)
                ok = mgr.approve(change_id, approved_by=user.username)
                return {
                    "success": ok,
                    "change_id": change_id,
                    "status": "approved" if ok else "failed",
                    "timestamp": time.time(),
                }
            except ImportError:
                return {"status": "unavailable", "detail": "ChangeManager not available"}
            except (ValueError, TypeError, AttributeError) as exc:
                _log.warning("[DASH] Change approve failed: %s", exc)
                return {"status": "error", "detail": str(exc)}

        @app.post("/api/changes/reject/{change_id}")
        async def api_changes_reject(change_id: str, request: Request, user: Any = Depends(admin_only)):
            """Reject a pending change proposal."""
            try:
                body = await request.json()
                from core.change_management import get_change_manager
                mgr = get_change_manager(self._cfg)
                reason = body.get("reason", "Rejected via dashboard")
                ok = mgr.reject(change_id, rejected_by=user.username, reason=reason)
                return {
                    "success": ok,
                    "change_id": change_id,
                    "status": "rejected" if ok else "failed",
                    "timestamp": time.time(),
                }
            except ImportError:
                return {"status": "unavailable", "detail": "ChangeManager not available"}
            except (ValueError, TypeError, AttributeError) as exc:
                _log.warning("[DASH] Change reject failed: %s", exc)
                return {"status": "error", "detail": str(exc)}

        @app.get("/api/changes/history")
        async def api_changes_history(user: Any = Depends(admin_only)):
            """Get recent change proposals with audit trail."""
            try:
                from core.change_management import get_change_manager
                mgr = get_change_manager(self._cfg)
                recent = mgr.list_recent(n=50)
                audit = mgr.get_audit_log(n=100)
                stats = mgr.get_stats()
                return {
                    "recent": [p.to_dict() for p in recent],
                    "audit_log": audit,
                    "stats": stats,
                    "timestamp": time.time(),
                }
            except ImportError:
                return {"status": "unavailable", "detail": "ChangeManager not available"}
            except (ValueError, TypeError, AttributeError) as exc:
                _log.warning("[DASH] Changes history failed: %s", exc)
                return {"status": "error", "detail": str(exc)}

        # -- Risk Dashboard API ---------------------------------------------------

        @app.get("/api/risk/snapshot")
        async def api_risk_snapshot(user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Get global risk snapshot - position, capital, drawdown, and execution risk."""
            try:
                from core.risk_dashboard import get_risk_dashboard
                dash = get_risk_dashboard(self._cfg)
                snap = dash.get_snapshot()
                return snap.to_dict()
            except ImportError:
                return {"status": "unavailable", "detail": "RiskDashboard not available (import error)"}
            except (ValueError, TypeError, AttributeError) as exc:
                _log.warning("[DASH] Risk snapshot failed: %s", exc)
                return {"status": "error", "detail": str(exc)}

        @app.get("/api/slo/compliance")
        async def api_slo_compliance(user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Get SLO/SLA compliance report for all registered SLOs."""
            try:
                from core.slo_governance import get_slo_governance
                slo = get_slo_governance()
                report = slo.check_all_slos()
                return report.to_dict()
            except ImportError:
                return {"status": "unavailable", "detail": "SLOGovernance not available (import error)"}
            except (ValueError, TypeError, AttributeError) as exc:
                _log.warning("[DASH] SLO compliance check failed: %s", exc)
                return {"status": "error", "detail": str(exc)}

        @app.get("/api/risk/alerts")
        async def api_risk_alerts(user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Get active risk alerts."""
            try:
                from core.risk_dashboard import get_risk_dashboard
                dash = get_risk_dashboard(self._cfg)
                alerts = dash.get_alerts(unacknowledged_only=True)
                return {
                    "alerts": [a.to_dict() for a in alerts],
                    "count": len(alerts),
                    "timestamp": time.time(),
                }
            except ImportError:
                return {"status": "unavailable", "detail": "RiskDashboard not available"}
            except (ValueError, TypeError, AttributeError) as exc:
                _log.warning("[DASH] Risk alerts failed: %s", exc)
                return {"status": "error", "detail": str(exc)}

        @app.get("/api/risk/limits")
        async def api_risk_limits(user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Get risk limit utilization across all categories."""
            try:
                from core.risk_dashboard import get_risk_dashboard
                dash = get_risk_dashboard(self._cfg)
                snap = dash.get_snapshot()
                limits = [
                    {
                        "name": m.name,
                        "utilization_pct": m.utilization_pct,
                        "limit_value": m.limit_value,
                        "current_value": m.current_value,
                        "unit": m.unit,
                        "status": m.status,
                    }
                    for m in snap.metrics
                ]
                return {
                    "limits": limits,
                    "count": len(limits),
                    "timestamp": time.time(),
                }
            except ImportError:
                return {"status": "unavailable", "detail": "RiskDashboard not available"}
            except (ValueError, TypeError, AttributeError) as exc:
                _log.warning("[DASH] Risk limits failed: %s", exc)
                return {"status": "error", "detail": str(exc)}

        # -- Observability: Uptime / diagnostics ---------------------------------

        # -- OI Snapshot Summary API --------------------------------------------

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
            except (ImportError, ValueError, TypeError, OSError) as exc:
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
            except (ImportError, ValueError, TypeError, OSError) as exc:
                _log.debug("[DASH] DB OI snapshots unavailable: %s", exc)

            return {
                "index_names": index_names,
                "live": live,
                "recent_snapshots": recent,
                "timestamp": time.time(),
            }

        # -- Invariants API ----------------------------------------------------

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
            except (ValueError, TypeError, KeyError) as e:
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

                # -- Real-Time Notifications: SSE Stream --------------------------------

        @app.get("/api/system/notifications/stream")
        async def api_notifications_stream(user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Server-Sent Events stream for real-time notifications.

            Returns a ``text/event-stream`` response. The client should
            reconnect on connection loss. A keepalive comment is sent
            every 30 seconds to prevent proxy timeouts.

            Example client:
                const evtSource = new EventSource('/api/system/notifications/stream');
                evtSource.onmessage = (e) => { const n = JSON.parse(e.data); ... };
            """
            async def _event_generator():
                # Send initial heartbeat with recent notifications
                recent = self._notifications.recent(20)
                yield f"event: connected\ndata: {json.dumps({'status': 'ok', 'recent': recent})}\n\n"
                # Subscribe to new notifications
                async for notif in self._notifications.subscribe():
                    yield f"event: notification\ndata: {json.dumps(notif)}\n\n"
                
        # -- Notifications REST API ---------------------------------------------

        @app.get("/api/system/notifications")
        async def api_notifications_list(user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Get recent notifications."""
            n = self._notifications.recent(100)
            unacknowledged = [x for x in n if not x["acknowledged"]]
            return {
                "notifications": n,
                "total": len(n),
                "unacknowledged": len(unacknowledged),
                "timestamp": time.time(),
            }

        @app.post("/api/system/notifications/{notif_id}/acknowledge")
        async def api_notifications_acknowledge(notif_id: str, user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Acknowledge a single notification."""
            ok = self._notifications.acknowledge(notif_id)
            return {"success": ok, "notification_id": notif_id}

        @app.post("/api/system/notifications/acknowledge-all")
        async def api_notifications_acknowledge_all(request: Request, user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Acknowledge all notifications, optionally filtered by severity."""
            body = await request.json()
            severity = body.get("severity", None)
            count = self._notifications.acknowledge_all(severity=severity)
            return {"success": True, "count": count}

        @app.post("/api/system/notifications/push")
        async def api_notifications_push(request: Request, user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Push a notification programmatically."""
            body = await request.json()
            notif = self._notifications.push(
                message=body.get("message", ""),
                severity=body.get("severity", "INFO"),
                category=body.get("category", "system"),
                source=body.get("source", "api"),
                details=body.get("details"),
            )
            return {"success": True, "notification": notif.to_dict()}

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
                "paused": self._pause_event.is_set() if self._pause_event is not None else False,
                "hard_halt": state.get("hard_halt", False),
                "execution_mode": state.get("execution_mode", self._cfg.get("execution_mode", "paper")),
                "uptime": time.time() - self._startup_ts,
            }

        # -- CSV Export: Trades ---------------------------------------------------

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

        # -- Risk: Position Concentration -----------------------------------------

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

        # -- v2.45 Webhook: Signal Injection --------------------------------------
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
                except (ValueError, AttributeError, TypeError, RuntimeError) as exc:
                    _log.warning("[DASH] Webhook rate limiter error: %s", exc)

            try:
                body = await request.json()
            except (json.JSONDecodeError, ValueError) as exc:
                _log.warning("[DASH] Webhook JSON decode error: %s", exc)
                return {"status": "queued", "ts": time.time()}

            # Queue the signal if a signal_queue is wired
            if self._signal_queue is not None:
                try:
                    self._signal_queue.put(body)
                except (ValueError, AttributeError, TypeError, RuntimeError) as exc:
                    _log.warning("[DASH] Webhook signal queue error: %s", exc)

            # Also append to signal_log if available
            if self._signal_log is not None:
                try:
                    self._signal_log.append(body)
                except (ValueError, AttributeError, TypeError) as exc:
                    _log.warning("[DASH] Webhook signal log error: %s", exc)

            return {"status": "queued", "ts": time.time()}

        # -- Multi-Asset Portfolio Allocation ------------------------------------

        @app.get("/api/portfolio/asset-allocation", tags=["Risk"])
        async def api_portfolio_allocation(user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Get multi-asset portfolio allocation breakdown across all 6 asset classes.

            Uses the ``MultiAssetPortfolioAggregator`` (wired via bot_refs) to compute
            per-class exposure, P&L, and allocation percentages.

            Returns:
                Dict with ``total_value``, ``cash``, ``allocation_by_asset``,
                ``positions_count``, and individual position details, or
                ``{"status": "unavailable"}`` if no aggregator is wired.
            """
            aggregator = self._bot_refs.get("portfolio_aggregator")
            if aggregator is None:
                return {"status": "unavailable", "detail": "Portfolio aggregator not wired"}

            try:
                state = self._read_state()
                cash = state.get("capital", state.get("base_capital", 0)) or 0

                # Read trader state for open positions
                equity_positions = self._bot_refs.get("equity_positions", [])
                fo_futures = self._bot_refs.get("fo_futures", [])
                fo_options = self._bot_refs.get("fo_options", [])
                commodity_positions = self._bot_refs.get("commodity_positions", [])
                currency_positions = self._bot_refs.get("currency_positions", [])
                bond_positions = self._bot_refs.get("bond_positions", [])
                equity_holdings = self._bot_refs.get("equity_holdings", [])
                sip_plans = self._bot_refs.get("sip_plans", [])
                mf_holdings = self._bot_refs.get("mf_holdings", [])

                snapshot = aggregator.aggregate(
                    equity_positions=equity_positions,
                    fo_futures=fo_futures,
                    fo_options=fo_options,
                    commodity_positions=commodity_positions,
                    currency_positions=currency_positions,
                    bond_positions=bond_positions,
                    equity_holdings=equity_holdings,
                    sip_plans=sip_plans,
                    mf_holdings=mf_holdings,
                    cash_balance=float(cash),
                )

                return {
                    "status": "ok",
                    "total_value": round(snapshot.total_value, 2),
                    "cash": round(snapshot.cash, 2),
                    "positions_count": len(snapshot.positions),
                    "allocation_by_asset": snapshot.metadata.get("exposures", {}),
                    "timestamp": time.time(),
                }

            except (ValueError, TypeError, AttributeError, RuntimeError) as exc:
                _log.warning("[DASH] Portfolio allocation error: %s", exc)
                return {"status": "error", "detail": str(exc)}

        # -- Fundamentals Analysis API --------------------------------------------

        @app.get("/api/fundamentals/weights", tags=["Fundamentals"])
        async def api_fundamentals_weights(
            user: Any = Depends(self._auth_deps.require_auth_optional),
        ):
            """Get current fundamental analysis dimension weights.

            Returns the 4 dimension weights (value, growth, quality, momentum)
            that sum to 1.0.
            """
            try:
                from core.fundamental_analyzer import get_fundamental_analyzer
                fa = get_fundamental_analyzer()
                return {
                    "weights": fa.current_weights,
                    "default_weights": {
                        "value": 0.30,
                        "growth": 0.25,
                        "quality": 0.25,
                        "momentum": 0.20,
                    },
                    "timestamp": time.time(),
                }
            except (ValueError, TypeError, ImportError, AttributeError) as exc:
                _log.warning("[DASH] Fundamentals weights fetch failed: %s", exc)
                return {"error": str(exc), "weights": {}, "timestamp": time.time()}

        @app.put("/api/fundamentals/weights", tags=["Fundamentals"])
        async def api_fundamentals_weights_update(
            request: Request,
            user: Any = Depends(self._auth_deps.require_auth_optional),
        ):
            """Update fundamental analysis dimension weights at runtime.

            Accepts a JSON body with partial or full weight overrides.
            All 4 keys (value, growth, quality, momentum) must still sum to 1.0.
            """
            try:
                body = await request.json()
                weights: dict[str, float] = body.get("weights", {})
                if not weights:
                    return {"error": "No weights provided", "success": False}

                from core.fundamental_analyzer import get_fundamental_analyzer
                fa = get_fundamental_analyzer()
                fa.set_weights(weights)

                return {
                    "success": True,
                    "weights": fa.current_weights,
                    "timestamp": time.time(),
                }
            except (ValueError, TypeError, KeyError, ImportError, AttributeError) as exc:
                _log.warning("[DASH] Fundamentals weights update failed: %s", exc)
                return {"error": str(exc), "success": False, "timestamp": time.time()}

        @app.get("/api/fundamentals/analyze/{symbol}", tags=["Fundamentals"])
        async def api_fundamentals_analyze(
            symbol: str,
            request: Request,
            user: Any = Depends(self._auth_deps.require_auth_optional),
        ):
            """Analyze a single symbol's fundamentals.

            Accepts a Yahoo Finance symbol (e.g. ``RELIANCE.NS``, ``TCS.NS``).
            Query param ``force_refresh=true`` bypasses cache.
            Query param ``weights`` as JSON-encoded dict overrides dimension weights.

            Returns a ``ScreeningResult`` with composite score, dimension
            breakdown (Value/Growth/Quality/Momentum), and verdict.

            Returns:
                Dict with ``symbol``, ``composite_score``, ``verdict``,
                ``dimension_scores``, ``details`` list, and raw metrics.
                On error, ``error`` field is set.
            """
            try:
                from core.fundamental_analyzer import get_fundamental_analyzer
                fa = get_fundamental_analyzer()

                force_refresh = request.query_params.get("force_refresh", "false").lower() == "true"
                weights_str = request.query_params.get("weights", "")

                # Apply custom weights for this request if provided
                prev_weights = None
                if weights_str:
                    try:
                        custom_w = json.loads(weights_str)
                        prev_weights = fa.current_weights
                        fa.set_weights(custom_w)
                    except (json.JSONDecodeError, ValueError, TypeError) as exc:
                        _log.warning("[DASH] Invalid weights JSON in analyze: %s", exc)

                result = fa.analyze(symbol, force_refresh=force_refresh)

                # Restore previous weights if we temporarily changed them
                if prev_weights is not None:
                    try:
                        fa.set_weights(prev_weights)
                    except ValueError:
                        pass

                return {
                    "symbol": result.symbol,
                    "name": result.name,
                    "sector": result.sector,
                    "current_price": result.current_price,
                    "market_cap": result.market_cap,
                    "pe_ratio": result.pe_ratio,
                    "pb_ratio": result.pb_ratio,
                    "dividend_yield": result.dividend_yield,
                    "eps_ttm": result.eps_ttm,
                    "roe_pct": result.roe_pct,
                    "debt_to_equity": result.debt_to_equity,
                    "earnings_growth": result.earnings_growth,
                    "composite_score": result.composite_score,
                    "verdict": result.verdict,
                    "dimension_scores": {
                        "value": result.dimension_scores.value,
                        "growth": result.dimension_scores.growth,
                        "quality": result.dimension_scores.quality,
                        "momentum": result.dimension_scores.momentum,
                    },
                    "details": [
                        {
                            "metric": d.metric,
                            "raw_value": d.raw_value,
                            "score": d.score,
                            "weight": d.weight,
                            "rationale": d.rationale,
                        }
                        for d in result.details
                    ],
                    "short_summary": result.short_summary,
                    "error": result.error,
                    "timestamp": time.time(),
                }
            except (ValueError, TypeError, KeyError, ImportError, AttributeError) as exc:
                _log.warning("[DASH] Fundamentals analyze failed: %s", exc)
                return {"error": str(exc), "symbol": symbol, "timestamp": time.time()}

        @app.post("/api/fundamentals/screen", tags=["Fundamentals"])
        async def api_fundamentals_screen(
            request: Request,
            user: Any = Depends(self._auth_deps.require_auth_optional),
        ):
            """Screen multiple symbols by fundamental scores.

            Accepts a JSON body with ``symbols`` (list of Yahoo Finance symbols)
            and optional ``min_score`` (float), ``force_refresh`` (bool),
            and ``weights`` (dict) to override dimension scoring weights.

            Returns:
                Dict with ``results`` list (sorted by composite_score desc),
                ``count``, ``min_score``, and ``error`` if any.
            """
            try:
                body = await request.json()
                symbols: list[str] = body.get("symbols", [])
                min_score: float = float(body.get("min_score", 0.0))
                force_refresh: bool = bool(body.get("force_refresh", False))
                weights: dict[str, float] | None = body.get("weights", None)

                if not symbols:
                    return {"error": "No symbols provided", "results": [], "count": 0}
                MAX_SCREEN_SYMBOLS = 50
                if len(symbols) > MAX_SCREEN_SYMBOLS:
                    symbols = symbols[:MAX_SCREEN_SYMBOLS]
                    _log.warning("[DASH] Fundamentals screen truncated to %d symbols", MAX_SCREEN_SYMBOLS)

                from core.fundamental_analyzer import get_fundamental_analyzer
                fa = get_fundamental_analyzer()

                # Apply custom weights for this screen if provided
                prev_weights = None
                if weights:
                    prev_weights = fa.current_weights
                    fa.set_weights(weights)

                results = fa.screen(symbols, min_score=min_score, force_refresh=force_refresh)

                # Restore weights
                if prev_weights is not None:
                    try:
                        fa.set_weights(prev_weights)
                    except ValueError:
                        pass

                return {
                    "results": [
                        {
                            "symbol": r.symbol,
                            "name": r.name,
                            "sector": r.sector,
                            "current_price": r.current_price,
                            "pe_ratio": r.pe_ratio,
                            "composite_score": r.composite_score,
                            "verdict": r.verdict,
                            "dimension_scores": {
                                "value": r.dimension_scores.value,
                                "growth": r.dimension_scores.growth,
                                "quality": r.dimension_scores.quality,
                                "momentum": r.dimension_scores.momentum,
                            },
                            "short_summary": r.short_summary,
                            "error": r.error,
                        }
                        for r in results
                    ],
                    "count": len(results),
                    "min_score": min_score,
                    "timestamp": time.time(),
                }
            except (ValueError, TypeError, KeyError, ImportError, AttributeError) as exc:
                _log.warning("[DASH] Fundamentals screen failed: %s", exc)
                return {"error": str(exc), "results": [], "count": 0, "timestamp": time.time()}

        # -- Performance Comparison Dashboard API ---------------------------------

        @app.get("/api/performance/comparison")
        async def api_performance_comparison(request: Request, user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Get comprehensive performance comparison data across multiple dimensions.

            Provides trade performance breakdowns by regime, score bin, direction,
            index, and exit reason. Also includes overall metrics and insights.

            Query params:
                days (int, default 90): lookback window in days.
                mode (str, optional): filter by execution mode (PAPER/LIVE).

            Returns:
                Dict with overall metrics, breakdowns by regime/score/direction/index/exit,
                insights list, and summary statistics.
            """
            try:
                from core.performance_metrics import (
                    compute_metrics,
                    generate_insights,
                    load_trades,
                    metrics_by_direction,
                    metrics_by_exit_reason,
                    metrics_by_index,
                    metrics_by_regime,
                    metrics_by_score_bin,
                )

                # Parse query params
                days_str = request.query_params.get("days", "90")
                mode = request.query_params.get("mode", None)
                try:
                    days = int(days_str)
                except (ValueError, TypeError):
                    days = 90

                trades = load_trades(self._db_path, mode=mode, days=days)

                if not trades:
                    return {
                        "status": "ok",
                        "trades_count": 0,
                        "note": "No trades found in the specified period",
                        "overall": {},
                        "by_regime": {},
                        "by_score_bin": {},
                        "by_direction": {},
                        "by_index": {},
                        "by_exit_reason": {},
                        "insights": [],
                        "period_days": days,
                        "timestamp": time.time(),
                    }

                overall = compute_metrics(trades)
                insights = generate_insights(trades)

                return {
                    "status": "ok",
                    "trades_count": len(trades),
                    "overall": overall,
                    "by_regime": metrics_by_regime(trades),
                    "by_score_bin": metrics_by_score_bin(trades),
                    "by_direction": metrics_by_direction(trades),
                    "by_index": metrics_by_index(trades),
                    "by_exit_reason": metrics_by_exit_reason(trades),
                    "insights": insights,
                    "period_days": days,
                    "period_mode": mode,
                    "timestamp": time.time(),
                }
            except ImportError as exc:
                _log.warning("[DASH] Performance comparison unavailable: %s", exc)
                return {"status": "unavailable", "detail": "performance_metrics module not available"}
            except (ValueError, TypeError, RuntimeError, OSError) as exc:
                _log.warning("[DASH] Performance comparison error: %s", exc)
                return {"status": "error", "detail": str(exc)}

        # -- Data Provider Status ------------------------------------------------

        @app.get("/api/system/data-providers")
        async def api_data_providers(user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Get status of all registered market data providers.

            Reads ``market_data_service`` (MarketDataService) from ``_bot_refs``.

            Returns:
                Dict with ``providers`` list, ``total``, ``connected``, ``health``,
                or ``{"status": "unavailable"}`` if no service is wired.
            """
            mds = self._bot_refs.get("market_data_service")
            if mds is None:
                return {"status": "unavailable", "detail": "MarketDataService not wired"}

            try:
                adapters = mds.list_adapters()
                health = mds.health_check()

                providers_list = []
                for name, info in adapters.items():
                    providers_list.append({
                        "name": name,
                        "type": info.get("adapter_type", "unknown"),
                        "asset_classes": info.get("asset_classes", []),
                        "priority": info.get("priority", 10),
                        "connected": info.get("connected", False),
                    })

                return {
                    "status": "ok",
                    "total": health.get("total_adapters", 0),
                    "connected": health.get("connected_adapters", 0),
                    "disconnected": health.get("disconnected_adapters", 0),
                    "providers": providers_list,
                    "timestamp": time.time(),
                }
            except (ValueError, TypeError, AttributeError, RuntimeError) as exc:
                _log.warning("[DASH] Data providers status error: %s", exc)
                return {"status": "error", "detail": str(exc)}

        @app.get("/api/system/data-providers/health")
        async def api_data_providers_health(user: Any = Depends(self._auth_deps.require_auth_optional)):
            """Get aggregate health metrics for the market data provider mesh.

            Returns a simplified health summary: overall status (healthy/degraded/critical),
            connected/total counts, per-provider status breakdown, and error-rate
            tracking for each adapter.

            This endpoint is designed for the auto-refresh cycle and dashboard widgets
            that only need the health summary without the full provider list.
            """
            mds = self._bot_refs.get("market_data_service")
            if mds is None:
                return {"status": "unavailable", "detail": "MarketDataService not wired"}

            try:
                health = mds.health_check()
                total = health.get("total_adapters", 0)
                connected = health.get("connected_adapters", 0)
                disconnected = health.get("disconnected_adapters", 0)
                details = health.get("adapter_details", {})

                if total == 0:
                    overall = "idle"
                elif connected == total:
                    overall = "healthy"
                elif connected > 0:
                    overall = "degraded"
                else:
                    overall = "critical"

                # Collect error-rate tracking per adapter
                _record_provider_request()
                error_info = _get_provider_error_info(details)

                return {
                    "status": overall,
                    "total": total,
                    "connected": connected,
                    "disconnected": disconnected,
                    "health_pct": round((connected / total * 100) if total > 0 else 0, 1),
                    "adapter_details": details,
                    "error_tracking": error_info,
                    "timestamp": time.time(),
                }
            except (ValueError, TypeError, AttributeError, RuntimeError) as exc:
                _log.warning("[DASH] Data providers health error: %s", exc)
                return {"status": "error", "detail": str(exc)}

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
                except (ValueError, TypeError, AttributeError, RuntimeError) as exc:
                    _log.warning("[DASH] Option chain fetch error: %s", exc)

            chain_data["symbol"] = index_name.upper()
            chain_data["spot_price"] = self._bot_refs.get(f"ltp_{index_name.upper()}", 0)
            return chain_data

        # -- Execution Safety: Startup Self-Test ----------------------------------

        @app.post("/api/system/self-test")
        async def api_self_test(user: Any = Depends(admin_only)):
            """Run startup self-test to verify critical modules are healthy."""
            results = []
            all_pass = True

            # 1. Auth DB health
            try:
                stats = self._auth.get_stats()
                results.append({"test": "auth_db", "status": "pass", "detail": f"{stats.get('total_users', 0)} users, {stats.get('active_sessions', 0)} active sessions"})
            except (ValueError, TypeError, OSError) as e:
                results.append({"test": "auth_db", "status": "fail", "detail": str(e)})
                all_pass = False

            # 2. State file readable
            try:
                state = self._read_state()
                results.append({"test": "state_file", "status": "pass", "detail": f"{len(state)} keys, mode={state.get('execution_mode', 'unknown')}"})
            except (ValueError, OSError, json.JSONDecodeError) as e:
                results.append({"test": "state_file", "status": "fail", "detail": str(e)})
                all_pass = False

            # 3. Trades DB queryable
            try:
                conn = _get_db_conn(self._db_path, timeout=2, row_factory=False)
                cursor = conn.execute("SELECT COUNT(*) FROM trades")
                trade_count = cursor.fetchone()[0]
                conn.close()
                results.append({"test": "trades_db", "status": "pass", "detail": f"{trade_count} trades"})
            except (OSError, ValueError) as e:
                results.append({"test": "trades_db", "status": "warn", "detail": f"{e} (non-fatal if no trades yet)"})

            # 4. Config available
            try:
                cfg_keys = len(self._cfg)
                defaults_path = self._resolve_defaults_path()
                defaults_ok = defaults_path.is_file()
                results.append({"test": "config", "status": "pass", "detail": f"{cfg_keys} keys loaded, defaults_file={defaults_ok}"})
                if not defaults_ok:
                    results.append({"test": "defaults_file", "status": "warn", "detail": f"Defaults file not found at {defaults_path}"})
            except (ValueError, OSError, json.JSONDecodeError) as e:
                results.append({"test": "config", "status": "fail", "detail": str(e)})
                all_pass = False

            # 5. Template rendering works
            try:
                tmpl = self._templates.get_template("login.html")
                results.append({"test": "templates", "status": "pass", "detail": f"Login template loaded ({len(tmpl.render(request=None))} bytes)"})
            except (ValueError, TypeError, AttributeError) as e:
                results.append({"test": "templates", "status": "warn", "detail": str(e)})

            return {
                "overall": "PASS" if all_pass else "FAIL",
                "timestamp": time.time(),
                "results": results,
                "summary": f"{sum(1 for r in results if r['status'] == 'pass')} passed, {sum(1 for r in results if r['status'] == 'warn')} warnings, {sum(1 for r in results if r['status'] == 'fail')} failed",
            }

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

