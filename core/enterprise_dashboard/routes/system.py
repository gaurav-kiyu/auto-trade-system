"""
System API route registration for the Enterprise Dashboard.

Handles read-only system endpoints: /api/system/state, /api/system/trades,
/api/system/health, /api/system/signals, /api/system/ws-status,
/api/system/health/docker, /api/system/uptime, /api/system/diagnostics,
/api/system/oi, /api/system/invariants.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import Depends

from core.db_utils import get_connection as _get_db_conn

_log = logging.getLogger(__name__)


def register_system_routes(app, dashboard, admin_only, operator_or_admin):
    """Register read-only system API routes.

    Args:
        app: FastAPI application instance.
        dashboard: EnterpriseDashboard instance.
        admin_only: FastAPI Depends for admin role.
        operator_or_admin: FastAPI Depends for operator or admin role.
    """

    @app.get("/api/system/state")
    async def api_system_state(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        return dashboard._read_state()

    @app.get("/api/system/trades")
    async def api_trades(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        return dashboard._load_recent_trades()

    @app.get("/api/system/health")
    async def api_health(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        return await dashboard._check_health()

    @app.get("/api/system/signals")
    async def api_signals(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        return dashboard._get_signals()

    @app.get("/api/system/ws-status")
    async def api_ws_status(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Get WebSocket feed status."""
        ws_adapter = dashboard._bot_refs.get("nse_ws_adapter")
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

        ws_feed = dashboard._ws_feed_manager
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
        state = dashboard._read_state()
        db_ok = False
        try:
            conn = _get_db_conn(dashboard._db_path, timeout=2, row_factory=False)
            conn.execute("SELECT 1")
            conn.close()
            db_ok = True
        except (OSError, sqlite3.Error, ValueError) as exc:
            _log.warning("[DASH] Health check DB probe failed: %s", exc)
        auth_db_ok = False
        try:
            conn = _get_db_conn(dashboard._auth._db_path, timeout=2, row_factory=False)
            conn.execute("SELECT 1")
            conn.close()
            auth_db_ok = True
        except (OSError, sqlite3.Error, ValueError) as exc:
            _log.warning("[DASH] Health check auth DB probe failed: %s", exc)
        uptime_secs = time.time() - dashboard._startup_ts if hasattr(dashboard, '_startup_ts') else 0
        return {
            "status": "healthy" if (db_ok and auth_db_ok and not state.get("hard_halt")) else "degraded",
            "version": "2.53.0",
            "uptime_seconds": uptime_secs,
            "uptime_human": f"{int(uptime_secs//3600)}h{int(uptime_secs%3600//60)}m",
            "db_connected": db_ok,
            "auth_db_connected": auth_db_ok,
            "paused": dashboard._pause_event.is_set() if dashboard._pause_event is not None else False,
            "hard_halt": state.get("hard_halt", False),
            "open_positions": state.get("open_positions", 0),
            "timestamp": time.time(),
        }

    @app.get("/api/system/uptime")
    async def api_uptime(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        uptime_secs = time.time() - dashboard._startup_ts
        return {
            "started_at": dashboard._startup_ts,
            "uptime_seconds": uptime_secs,
            "uptime_human": f"{int(uptime_secs//3600)}h{int(uptime_secs%3600//60)}m",
            "server_time": time.time(),
            "server_time_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    @app.get("/api/system/diagnostics")
    async def api_diagnostics(user: Any = Depends(admin_only)):
        state = dashboard._read_state()
        return {
            "python_version": sys.version,
            "platform": sys.platform,
            "state_file_exists": Path(dashboard._state_path).is_file(),
            "config_keys": len(dashboard._cfg),
            "auth_sessions": dashboard._auth.get_stats().get("active_sessions", 0),
            "total_users": dashboard._auth.get_stats().get("total_users", 0),
            "open_positions": state.get("open_positions", 0),
            "paused": dashboard._pause_event.is_set() if dashboard._pause_event is not None else False,
            "hard_halt": state.get("hard_halt", False),
            "execution_mode": state.get("execution_mode", dashboard._cfg.get("execution_mode", "paper")),
            "uptime": time.time() - dashboard._startup_ts,
        }

    @app.get("/api/system/oi", tags=["System"])
    async def api_oi_summary(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Get OI snapshot summary for all tracked indices."""
        index_names = dashboard._cfg.get("INDEX_PRIORITY", ["NIFTY", "BANKNIFTY", "FINNIFTY"])

        live: dict[str, Any] = {}
        try:
            from core.nse_option_recorder import get_oi_summary
            live = get_oi_summary(index_names, dashboard._cfg)
        except (ImportError, ValueError, TypeError, OSError) as exc:
            _log.debug("[DASH] Live OI summary unavailable: %s", exc)

        recent: dict[str, Any] = {}
        try:
            from core.oi_snapshot_store import get_snapshot_at
            oi_db = str(
                dashboard._cfg.get("oi_snapshot_db_path",
                dashboard._cfg.get("OI_SNAPSHOT_DB_PATH", "oi_snapshots.db"))
            )
            now = time.time()
            for idx in index_names:
                snap = get_snapshot_at(idx, now + 1, db_path=oi_db)
                if snap:
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

    @app.get("/api/system/invariants", tags=["System"])
    async def api_invariants(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Get runtime invariant check results and violations."""
        try:
            from core.invariants.engine import check_all, get_state, get_violations
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

    @app.get("/api/system/kill-status")
    async def api_kill_status(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        return {"halted": dashboard._pause_event.is_set()}
