"""
Monitoring route registration for the Enterprise Dashboard.

Handles: /api/system/notifications/*, /api/broker/info, /api/ml/status,
/api/system/data-providers/*, /api/performance/comparison.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import StreamingResponse

from core.enterprise_dashboard.utils import _get_provider_error_info, _record_provider_request

_log = logging.getLogger(__name__)


def register_monitoring_routes(app, dashboard, admin_only, operator_or_admin):
    """Register monitoring, broker, ML, data provider, and notification routes.

    Args:
        app: FastAPI application instance.
        dashboard: EnterpriseDashboard instance.
        admin_only: FastAPI Depends for admin role.
        operator_or_admin: FastAPI Depends for operator or admin role.
    """

    # ── Real-Time Notifications: SSE Stream ────────────────────────────────

    @app.get("/api/system/notifications/stream")
    async def api_notifications_stream(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Server-Sent Events stream for real-time notifications."""
        async def _event_generator():
            recent = dashboard._notifications.recent(20)
            yield f"event: connected\ndata: {json.dumps({'status': 'ok', 'recent': recent})}\n\n"
            async for notif in dashboard._notifications.subscribe():
                yield f"event: notification\ndata: {json.dumps(notif)}\n\n"
        return StreamingResponse(_event_generator(), media_type="text/event-stream")

    # ── Notifications REST API ─────────────────────────────────────────────

    @app.get("/api/system/notifications")
    async def api_notifications_list(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Get recent notifications."""
        n = dashboard._notifications.recent(100)
        unacknowledged = [x for x in n if not x["acknowledged"]]
        return {
            "notifications": n,
            "total": len(n),
            "unacknowledged": len(unacknowledged),
            "timestamp": time.time(),
        }

    @app.post("/api/system/notifications/{notif_id}/acknowledge")
    async def api_notifications_acknowledge(notif_id: str, user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Acknowledge a single notification."""
        ok = dashboard._notifications.acknowledge(notif_id)
        return {"success": ok, "notification_id": notif_id}

    @app.post("/api/system/notifications/acknowledge-all")
    async def api_notifications_acknowledge_all(request: Request, user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Acknowledge all notifications, optionally filtered by severity."""
        body = await request.json()
        severity = body.get("severity", None)
        count = dashboard._notifications.acknowledge_all(severity=severity)
        return {"success": True, "count": count}

    @app.post("/api/system/notifications/push")
    async def api_notifications_push(request: Request, user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Push a notification programmatically."""
        body = await request.json()
        notif = dashboard._notifications.push(
            message=body.get("message", ""),
            severity=body.get("severity", "INFO"),
            category=body.get("category", "system"),
            source=body.get("source", "api"),
            details=body.get("details"),
        )
        return {"success": True, "notification": notif.to_dict()}

    # ── Broker Info API ────────────────────────────────────────────────────

    @app.get("/api/broker/info")
    async def api_broker_info(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        return {
            "status": "connected",
            "broker_name": dashboard._cfg.get("broker_name", "Zerodha"),
            "mode": dashboard._cfg.get("execution_mode", "paper"),
            "latency_ms": dashboard._bot_refs.get("broker_latency", 0),
            "adapter": dashboard._cfg.get("broker_adapter", "kite"),
            "last_connected": None,
            "requests_today": 0,
            "error_rate": None,
            "failover_active": False,
        }

    # ── ML Status API ──────────────────────────────────────────────────────

    @app.get("/api/ml/status")
    async def api_ml_status(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        return {
            "model_loaded": dashboard._bot_refs.get("ml_model_loaded", False),
            "accuracy": dashboard._bot_refs.get("ml_accuracy"),
            "brier_score": dashboard._bot_refs.get("ml_brier_score"),
            "last_training": dashboard._bot_refs.get("ml_last_training"),
            "classifier_type": "LightGBM",
            "n_features": dashboard._bot_refs.get("ml_n_features"),
            "training_samples": dashboard._bot_refs.get("ml_training_samples"),
            "drift_detected": dashboard._bot_refs.get("ml_drift_detected", False),
            "total_predictions": dashboard._bot_refs.get("ml_total_predictions", 0),
            "avg_confidence": dashboard._bot_refs.get("ml_avg_confidence"),
            "calibration_score": dashboard._bot_refs.get("ml_calibration_score"),
            "psi": dashboard._bot_refs.get("ml_psi"),
        }

    # ── Data Provider Status ───────────────────────────────────────────────

    @app.get("/api/system/data-providers")
    async def api_data_providers(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Get status of all registered market data providers."""
        mds = dashboard._bot_refs.get("market_data_service")
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
    async def api_data_providers_health(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Get aggregate health metrics for the market data provider mesh."""
        mds = dashboard._bot_refs.get("market_data_service")
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

    # ── Performance Comparison API ─────────────────────────────────────────

    @app.get("/api/performance/comparison")
    async def api_performance_comparison(request: Request, user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Get comprehensive performance comparison data."""
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

            days_str = request.query_params.get("days", "90")
            mode = request.query_params.get("mode", None)
            try:
                days = int(days_str)
            except (ValueError, TypeError):
                days = 90

            trades = load_trades(dashboard._db_path, mode=mode, days=days)

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
