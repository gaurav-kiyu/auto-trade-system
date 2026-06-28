"""
Admin control route registration for the Enterprise Dashboard.

Handles: /api/config/* (CRUD), /api/changes/* (change management),
/api/system/kill, /api/system/resume, /api/system/pause, /api/system/resume-entry,
/api/system/self-test.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import Depends, Request


_log = logging.getLogger(__name__)


def register_admin_routes(app, dashboard, admin_only, operator_or_admin):
    """Register admin control and config management routes.

    Args:
        app: FastAPI application instance.
        dashboard: EnterpriseDashboard instance.
        admin_only: FastAPI Depends for admin role.
        operator_or_admin: FastAPI Depends for operator or admin role.
    """

    # ── Config Management API ──────────────────────────────────────────────

    @app.get("/api/config")
    async def api_get_config(user: Any = Depends(admin_only)):
        return {
            "config": dashboard._cfg,
            "defaults_path": str(dashboard._resolve_defaults_path()),
            "config_path": str(dashboard._resolve_config_path()),
        }

    @app.get("/api/config/defaults")
    async def api_get_defaults(user: Any = Depends(admin_only)):
        return dashboard._load_defaults()

    @app.post("/api/config/validate")
    async def api_validate_config(
        request: Request,
        user: Any = Depends(admin_only),
    ):
        body = await request.json()
        return dashboard._validate_config_change(body)

    @app.post("/api/config/preview")
    async def api_preview_config(
        request: Request,
        user: Any = Depends(admin_only),
    ):
        body = await request.json()
        return dashboard._preview_config_change(body)

    @app.post("/api/config/apply")
    async def api_apply_config(
        request: Request,
        user: Any = Depends(admin_only),
    ):
        body = await request.json()
        return dashboard._apply_config_change(body, user.username)

    @app.get("/api/config/history")
    async def api_config_history(user: Any = Depends(admin_only)):
        return dashboard._get_config_history()

    @app.get("/api/config/drift")
    async def api_config_drift(user: Any = Depends(admin_only)):
        """Detect configuration drift between live config and defaults."""
        try:
            defaults = dashboard._load_defaults()
            live = dict(dashboard._cfg)
            changed: list[dict[str, Any]] = []
            added: list[str] = []
            removed: list[str] = []

            for key in set(live) & set(defaults):
                live_val = live[key]
                default_val = defaults[key]
                live_s = json.dumps(live_val, sort_keys=True, default=str)
                default_s = json.dumps(default_val, sort_keys=True, default=str)
                if live_s != default_s:
                    changed.append({
                        "key": key,
                        "default": default_val,
                        "current": live_val,
                    })

            for key in set(live) - set(defaults):
                if not key.startswith("_"):
                    added.append(key)

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
                "removed_keys": removed[:50],
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
        return dashboard._rollback_config(version, user.username)

    # ── Kill Switch API ────────────────────────────────────────────────────

    @app.post("/api/system/kill")
    async def api_kill(
        request: Request,
        user: Any = Depends(admin_only),
    ):
        body = await request.json()
        reason = str(body.get("reason", "Manual kill via dashboard"))
        return dashboard._execute_kill(reason, user.username)

    @app.post("/api/system/resume")
    async def api_resume(
        user: Any = Depends(admin_only),
    ):
        return dashboard._execute_resume()

    @app.post("/api/system/pause")
    async def api_pause(
        user: Any = Depends(operator_or_admin),
    ):
        dashboard._pause_event.set()
        return {"status": "paused"}

    @app.post("/api/system/resume-entry")
    async def api_resume_entry(
        user: Any = Depends(operator_or_admin),
    ):
        dashboard._pause_event.clear()
        return {"status": "resumed"}

    # ── Change Management API ──────────────────────────────────────────────

    @app.get("/api/changes/pending")
    async def api_changes_pending(user: Any = Depends(admin_only)):
        """List all pending change proposals awaiting approval."""
        try:
            from core.change_management import get_change_manager
            mgr = get_change_manager(dashboard._cfg)
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
        """Propose a new configuration or parameter change."""
        try:
            body = await request.json()
            from core.change_management import get_change_manager
            mgr = get_change_manager(dashboard._cfg)
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
            mgr = get_change_manager(dashboard._cfg)
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
            mgr = get_change_manager(dashboard._cfg)
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
            mgr = get_change_manager(dashboard._cfg)
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

    # ── Self-Test API ──────────────────────────────────────────────────────

    @app.post("/api/system/self-test")
    async def api_self_test(user: Any = Depends(admin_only)):
        """Run startup self-test to verify critical modules are healthy."""
        from core.db_utils import get_connection as _get_db_conn
        import json

        results = []
        all_pass = True

        # 1. Auth DB health
        try:
            stats = dashboard._auth.get_stats()
            results.append({"test": "auth_db", "status": "pass",
                "detail": f"{stats.get('total_users', 0)} users, {stats.get('active_sessions', 0)} active sessions"})
        except (ValueError, TypeError, OSError) as e:
            results.append({"test": "auth_db", "status": "fail", "detail": str(e)})
            all_pass = False

        # 2. State file readable
        try:
            state = dashboard._read_state()
            results.append({"test": "state_file", "status": "pass",
                "detail": f"{len(state)} keys, mode={state.get('execution_mode', 'unknown')}"})
        except (ValueError, OSError, json.JSONDecodeError) as e:
            results.append({"test": "state_file", "status": "fail", "detail": str(e)})
            all_pass = False

        # 3. Trades DB queryable
        try:
            conn = _get_db_conn(dashboard._db_path, timeout=2, row_factory=False)
            cursor = conn.execute("SELECT COUNT(*) FROM trades")
            trade_count = cursor.fetchone()[0]
            conn.close()
            results.append({"test": "trades_db", "status": "pass",
                "detail": f"{trade_count} trades"})
        except (OSError, ValueError) as e:
            results.append({"test": "trades_db", "status": "warn",
                "detail": f"{e} (non-fatal if no trades yet)"})

        # 4. Config available
        try:
            cfg_keys = len(dashboard._cfg)
            defaults_path = dashboard._resolve_defaults_path()
            defaults_ok = defaults_path.is_file()
            results.append({"test": "config", "status": "pass",
                "detail": f"{cfg_keys} keys loaded, defaults_file={defaults_ok}"})
            if not defaults_ok:
                results.append({"test": "defaults_file", "status": "warn",
                    "detail": f"Defaults file not found at {defaults_path}"})
        except (ValueError, OSError, json.JSONDecodeError) as e:
            results.append({"test": "config", "status": "fail", "detail": str(e)})
            all_pass = False

        # 5. Template rendering works
        try:
            tmpl = dashboard._templates.get_template("login.html")
            results.append({"test": "templates", "status": "pass",
                "detail": f"Login template loaded"})
        except (ValueError, TypeError, AttributeError) as e:
            results.append({"test": "templates", "status": "warn", "detail": str(e)})

        return {
            "overall": "PASS" if all_pass else "FAIL",
            "timestamp": time.time(),
            "results": results,
            "summary": f"{sum(1 for r in results if r['status'] == 'pass')} passed, "
                       f"{sum(1 for r in results if r['status'] == 'warn')} warnings, "
                       f"{sum(1 for r in results if r['status'] == 'fail')} failed",
        }
