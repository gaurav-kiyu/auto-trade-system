"""Web Dashboard - enterprise-only startup module.

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

_DEFAULT_HOST = "0.0.0.0"  # bind loopback by default; override via web_dashboard_host config
_DEFAULT_PORT = 8000
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
    """Start the uvicorn server in a daemon thread (optionally with TLS).

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
            "uvicorn is required to serve the dashboard: pip install uvicorn",
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
    if host == "0.0.0.0" and not ssl_certfile:  # nosec B104
        _log.warning(
            "[DASH] Dashboard bound to 0.0.0.0 without TLS - "
            "set web_ssl_certfile and web_ssl_keyfile in config "
            "for HTTPS in production",
        )


# ── Convenience launcher (called from index_trader.py) ───────────────────────

def maybe_start_dashboard(
    cfg:           dict[str, Any],
    state_path:    str | None             = None,
    signal_log:    SignalLog | None       = None,
    db_path:       str                    = "db/trades.db",
    pause_event:   threading.Event | None = None,
    signal_queue:  Any | None            = None,
    ws_feed_manager: Any | None          = None,
    rate_limiter:  Any | None            = None,
) -> Any | None:
    """Start the EnterpriseDashboard if ``web_dashboard_enabled=true``.

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
        # Resolve the already-created Admin Control Plane server.
        # Never construct a second ControlPlaneServer for the Dashboard.
        control_plane = None
        try:
            from core.control_plane.server import get_active_control_plane_server

            control_plane = get_active_control_plane_server()
        except (ImportError, ValueError, TypeError, AttributeError):
            pass

        # Resolve MarketDataService from DI container if available
        market_data_service = None
        try:
            from core.di_container import get_container
            from core.services.market_data_service import MarketDataService
            container = get_container()
            market_data_service = container.try_resolve(MarketDataService)
        except (ImportError, ValueError, TypeError, AttributeError):
            pass

        # Also bridge market_data_service -> market_data for options chain viz
        # (webhook handler looks for "market_data" key in _bot_refs)
        dash.wire_bot_refs(
            pause_event=pause_event,
            signal_log=signal_log,
            signal_queue=signal_queue,
            ws_feed_manager=ws_feed_manager,
            rate_limiter=rate_limiter,
            control_plane=control_plane,
            market_data=market_data_service,
            market_data_service=market_data_service,
        )

        # Wire TLS/HTTPS enforcement middleware (Phase 15 Security Certification)
        try:
            from core.auth.tls_config import TLSConfig
            tls = TLSConfig.from_dict(c)
            # Also bridge top-level web_ssl_* keys into TLS config (backward compat)
            if not tls.cert_path and c.get("web_ssl_certfile"):
                tls = TLSConfig(enabled=True, cert_path=str(c["web_ssl_certfile"]), key_path=str(c.get("web_ssl_keyfile", "")))
            # Only enforce HTTPS when TLS is actually configured (cert + key).
            # Serving plain HTTP while force-redirecting every request to https://
            # breaks direct local access and tests (the redirect target has no TLS listener).
            if tls.is_tls_enabled:
                dash.app = tls.enforce_https(dash.app)  # type: ignore[assignment]
                _log.info("[DASH] HTTPS enforcement middleware enabled")
            else:
                _log.debug("[DASH] HTTPS enforcement skipped (no TLS cert/key configured)")
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] TLS middleware skipped: %s", exc)

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

if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="OPB Enterprise Web Dashboard Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    args = parser.parse_args()

    cfg_path = Path("json/config.json")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
    cfg["web_dashboard_enabled"] = True
    cfg["web_dashboard_host"] = args.host
    cfg["web_dashboard_port"] = args.port

    from core.enterprise_dashboard import EnterpriseDashboard
    dash = EnterpriseDashboard(config=cfg)
    import uvicorn
    uvicorn.run(dash.app, host=args.host, port=args.port, log_level="info")

