"""
Web Dashboard - enterprise-only startup module.

Provides the startup entry point for the EnterpriseDashboard (auth + RBAC +
premium UI).  Legacy ``create_app()`` has been removed in favor of the
``core.enterprise_dashboard.EnterpriseDashboard`` class.

Exports
-------
    SignalLog      - Thread-safe ring buffer for live signals (used by tests).
    serve()        - Start uvicorn in a daemon thread.
    maybe_start_dashboard() - Conditionally start the EnterpriseDashboard.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_PORT = 8765
_DEFAULT_SSL_CERT = ""
_DEFAULT_SSL_KEY = ""


# ── In-process signal ring buffer ─────────────────────────────────────────────

class SignalLog:
    """Thread-safe ring buffer for the last N live signals."""

    def __init__(self, maxlen: int = 200) -> None:
        self._buf: list[dict] = []
        self._maxlen = maxlen
        self._lock = threading.RLock()

    def append(self, signal: dict) -> None:
        with self._lock:
            self._buf.append({**signal, "_ts": time.time()})
            if len(self._buf) > self._maxlen:
                self._buf.pop(0)

    def recent(self, n: int = 50) -> list[dict]:
        with self._lock:
            return list(self._buf[-n:])

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


# ── Server ────────────────────────────────────────────────────────────────────

def serve(
    app: Any,
    *,
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
    log_level: str = "warning",
    ssl_certfile: str = "",
    ssl_keyfile: str = "",
) -> None:
    """
    Start the uvicorn server in a daemon thread (optionally with TLS).

    Returns immediately - the server runs in the background.
    Call this only when ``web_dashboard_enabled=true``.

    Args:
        app: FastAPI application instance.
        host: Bind address.
        port: Bind port.
        log_level: Uvicorn log level.
        ssl_certfile: Path to TLS certificate file (PEM format).
                      If provided, enables HTTPS.
        ssl_keyfile: Path to TLS private key file (PEM format).
                     Required if ssl_certfile is set.
    """
    try:
        import uvicorn
    except ImportError as exc:
        raise ImportError(
            "uvicorn is required to serve the dashboard: pip install uvicorn"
        ) from exc

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level,
        ssl_certfile=ssl_certfile or None,
        ssl_keyfile=ssl_keyfile or None,
    )
    server = uvicorn.Server(config)

    t = threading.Thread(target=server.run, daemon=True, name="web_dashboard")
    t.start()
    proto = "https" if ssl_certfile else "http"
    _log.info("[DASH] Dashboard started at %s://%s:%d", proto, host, port)

    # Warn if dashboard bound to 0.0.0.0 without TLS
    if host == "0.0.0.0" and not ssl_certfile:
        _log.warning(
            "[DASH] Dashboard bound to 0.0.0.0 without TLS - "
            "set web_ssl_certfile and web_ssl_keyfile in config "
            "for HTTPS in production"
        )


# ── Convenience launcher (called from index_trader.py) ───────────────────────

def maybe_start_dashboard(
    cfg:           dict[str, Any],
    state_path:    str | None             = None,
    signal_log:    SignalLog | None       = None,
    db_path:       str                    = "trades.db",
    pause_event:   threading.Event | None = None,
    signal_queue:  Any | None            = None,
    ws_feed_manager: Any | None          = None,
    rate_limiter:  Any | None            = None,
) -> Any | None:
    """
    Start the EnterpriseDashboard if ``web_dashboard_enabled=true``.

    Returns the FastAPI app (for testing) or None if disabled / import failure.
    All exceptions are caught - never blocks the main thread.
    """
    c = cfg or {}
    if not c.get("web_dashboard_enabled", False):
        return None
    try:
        host = str(c.get("web_dashboard_host", _DEFAULT_HOST))
        port = int(c.get("web_dashboard_port", _DEFAULT_PORT))
        ssl_certfile = str(c.get("web_ssl_certfile", _DEFAULT_SSL_CERT))
        ssl_keyfile = str(c.get("web_ssl_keyfile", _DEFAULT_SSL_KEY))

        from core.enterprise_dashboard import EnterpriseDashboard

        dash = EnterpriseDashboard(
            config=c,
            state_path=state_path,
            db_path=db_path,
        )
        # Resolve MarketDataService from DI container if available
        market_data_service = None
        try:
            from core.di_container import get_container
            from core.services.market_data_service import MarketDataService
            container = get_container()
            market_data_service = container.try_resolve(MarketDataService)
        except (ImportError, ValueError, TypeError, AttributeError):
            pass

        dash.wire_bot_refs(
            pause_event=pause_event,
            signal_log=signal_log,
            signal_queue=signal_queue,
            ws_feed_manager=ws_feed_manager,
            rate_limiter=rate_limiter,
            market_data_service=market_data_service,
        )

        serve(dash.app, host=host, port=port, ssl_certfile=ssl_certfile, ssl_keyfile=ssl_keyfile)
        return dash.app
    except Exception as exc:
        _log.warning("[DASH] Dashboard startup failed (non-fatal): %s", exc)
        return None


__all__ = [
    "SignalLog",
    "maybe_start_dashboard",
    "serve",
]

