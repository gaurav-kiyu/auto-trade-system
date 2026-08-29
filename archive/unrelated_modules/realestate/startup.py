"""Startup wiring — integrates real estate platform into the existing system.

Handles:
  - Creating default services
  - Wiring API routes into the FastAPI app
  - Registering with the DI container
  - Initializing auction marketplace, ML predictor, builder portal
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)

REAL_ESTATE_STARTUP_KEY = "realestate_platform"


def startup_realestate_system(
    cfg: dict[str, Any] | None = None,
    app: Any = None,
    container: Any = None,
) -> dict[str, Any]:
    """Initialize the real estate platform on system boot.

    Args:
        cfg: Application config dict.
        app: Optional FastAPI app to wire routes into.
        container: Optional DI container to register services.

    Returns:
        Dict with startup status per module.
    """
    from realestate.application.services import create_default_services

    _log.info("[RE] Initializing real estate platform...")
    cfg = cfg or {}
    enabled = cfg.get("REAL_ESTATE_ENABLED", True)

    results: dict[str, Any] = {}

    if not enabled:
        _log.info("[RE] Real estate platform disabled by config")
        results[REAL_ESTATE_STARTUP_KEY] = {"status": "skipped"}
        return results

    try:
        services = create_default_services()
        results["_service_instances"] = services
        results["services"] = {"status": "ok", "count": len(services)}
        _log.info("[RE] %d services created", len(services))

        # ── Auction Marketplace ───────────────────────────────────────────
        try:
            from realestate.auction.engine import create_auction_router
            auction_router = create_auction_router()
            results["auction_marketplace"] = {"status": "ok"}
            _log.info("[RE] Auction marketplace initialized")
            if app is not None:
                app.include_router(auction_router)
                results["auction_routes"] = {"status": "ok"}
        except (ImportError, ValueError, TypeError) as exc:
            _log.debug("[RE] Auction marketplace skipped: %s", exc)
            results["auction_marketplace"] = {"status": "skipped"}

        # ── ML Price Prediction ───────────────────────────────────────────
        try:
            from realestate.ml_prediction import create_ml_router
            ml_router = create_ml_router()
            results["ml_prediction"] = {"status": "ok"}
            _log.info("[RE] ML price prediction initialized")
            if app is not None:
                app.include_router(ml_router)
                results["ml_routes"] = {"status": "ok"}
        except (ImportError, ValueError, TypeError) as exc:
            _log.debug("[RE] ML prediction skipped: %s", exc)
            results["ml_prediction"] = {"status": "skipped"}

        # ── Notification Engine ──────────────────────────────────────────
        try:
            from realestate.notifications import (
                create_notification_router,
                get_notification_engine,
            )
            eng = get_notification_engine()
            results["notification_engine"] = {"status": "ok", "stats": eng.get_stats()}
            _log.info("[RE] Notification engine initialized")
            if app is not None:
                app.include_router(create_notification_router(eng))
                results["notification_routes"] = {"status": "ok"}
            services["notification_engine"] = eng
            results["_service_instances"] = services
        except (ImportError, ValueError, TypeError, RuntimeError) as exc:
            _log.debug("[RE] Notification engine skipped: %s", exc)
            results["notification_engine"] = {"status": "skipped"}


        # ── Tenant Portal ────────────────────────────────────────────────
        try:
            from realestate.tenant_portal import (
                create_tenant_router,
                get_tenant_portal,
            )
            tp = get_tenant_portal()
            results["tenant_portal"] = {"status": "ok"}
            _log.info("[RE] Tenant portal initialized")
            if app is not None:
                app.include_router(create_tenant_router(tp))
                results["tenant_routes"] = {"status": "ok"}
            services["tenant_portal"] = tp
            results["_service_instances"] = services
        except (ImportError, ValueError, TypeError, RuntimeError) as exc:
            _log.debug("[RE] Tenant portal skipped: %s", exc)
            results["tenant_portal"] = {"status": "skipped"}

        # ── Admin Panel ───────────────────────────────────────────────────
        try:
            from realestate.admin_panel import (
                create_admin_router,
                get_admin_panel,
            )
            ap = get_admin_panel()
            results["admin_panel"] = {"status": "ok"}
            _log.info("[RE] Admin panel initialized")
            if app is not None:
                app.include_router(create_admin_router(
                    ap,
                    property_service=services.get("property_service"),
                    auction_engine=services.get("auction_engine"),
                    builder_portal=services.get("builder_portal"),
                    lead_service=services.get("lead_service"),
                    notification_engine=services.get("notification_engine"),
                ))
                results["admin_routes"] = {"status": "ok"}
        except (ImportError, ValueError, TypeError, RuntimeError) as exc:
            _log.debug("[RE] Admin panel skipped: %s", exc)
            results["admin_panel"] = {"status": "skipped"}

        # ── Saved Properties ──────────────────────────────────────────────
        try:
            from realestate.saved_properties import (
                create_saved_properties_router,
                get_saved_properties_service,
            )
            sp = get_saved_properties_service()
            services["saved_properties"] = sp
            results["saved_properties"] = {"status": "ok"}
            _log.info("[RE] Saved properties service initialized")
            if app is not None:
                app.include_router(create_saved_properties_router(sp))
                results["saved_properties_routes"] = {"status": "ok"}
        except (ImportError, ValueError, TypeError, RuntimeError) as exc:
            _log.debug("[RE] Saved properties skipped: %s", exc)
            results["saved_properties"] = {"status": "skipped"}

        # ── Payment Gateway ───────────────────────────────────────────────
        try:
            from realestate.payments import (
                create_payment_router,
                get_payment_service,
            )
            ps = get_payment_service()
            services["payment_service"] = ps
            results["payment_gateway"] = {"status": "ok"}
            _log.info("[RE] Payment gateway initialized")
            if app is not None:
                app.include_router(create_payment_router(ps))
                results["payment_routes"] = {"status": "ok"}
        except (ImportError, ValueError, TypeError, RuntimeError) as exc:
            _log.debug("[RE] Payment gateway skipped: %s", exc)
            results["payment_gateway"] = {"status": "skipped"}

        # ── Export/Import ─────────────────────────────────────────────────
        try:
            from realestate.export_import import create_export_router
            svc = services.get("property_service")
            results["export_import"] = {"status": "ok"}
            _log.info("[RE] Export/Import module initialized")
            if app is not None and svc is not None:
                app.include_router(create_export_router(property_service=svc))
                results["export_routes"] = {"status": "ok"}
        except (ImportError, ValueError, TypeError, RuntimeError) as exc:
            _log.debug("[RE] Export/Import skipped: %s", exc)
            results["export_import"] = {"status": "skipped"}

        # ── Builder Portal ────────────────────────────────────────────────
        try:
            from realestate.builder_portal import create_builder_router
            builder_router = create_builder_router()
            results["builder_portal"] = {"status": "ok"}
            _log.info("[RE] Builder portal initialized")
            if app is not None:
                app.include_router(builder_router)
                results["builder_routes"] = {"status": "ok"}
        except (ImportError, ValueError, TypeError) as exc:
            _log.debug("[RE] Builder portal skipped: %s", exc)
            results["builder_portal"] = {"status": "skipped"}

        # ── RERA Compliance Dashboard ───────────────────────────────────────
        try:
            from realestate.rera_compliance import (
                create_rera_page_router,
                create_rera_router,
            )
            if app is not None:
                app.include_router(create_rera_router())
                app.include_router(create_rera_page_router())
            results["rera_compliance"] = {"status": "ok"}
            _log.info("[RE] RERA compliance dashboard initialized")
        except (ImportError, ValueError, TypeError) as exc:
            _log.debug("[RE] RERA compliance skipped: %s", exc)
            results["rera_compliance"] = {"status": "skipped"}

        # ── API Routes (existing) ─────────────────────────────────────────
        if app is not None:
            try:
                from realestate.api import wire_realestate_api
                wire_realestate_api(app, services=services)
                results["api_routes"] = {"status": "ok"}
            except (ImportError, ValueError, TypeError) as exc:
                _log.warning("[RE] API routes failed: %s", exc)
                results["api_routes"] = {"status": "error"}

            try:
                from realestate.ui import create_realestate_pages_router
                app.include_router(create_realestate_pages_router(services=services))
                results["ui_routes"] = {"status": "ok"}
            except (ImportError, ValueError, TypeError) as exc:
                _log.warning("[RE] UI routes failed: %s", exc)

        try:
            from realestate.ai_chatbot import create_chatbot_router
            if app is not None:
                app.include_router(create_chatbot_router(services=services))
            results["chatbot"] = {"status": "ok"}
        except (ImportError, ValueError, TypeError) as exc:
            _log.warning("[RE] Chatbot failed: %s", exc)

        # ── Location Autocomplete API ───────────────────────────────────────────
        try:
            from fastapi import APIRouter, Query
            ns = services.get("neighborhood_service")
            if ns is not None:
                autocomplete_router = APIRouter(prefix="/api/realestate", tags=["Real Estate Search"])

                @autocomplete_router.get("/autocomplete")
                async def autocomplete(
                    q: str = Query("", description="Search query (city or locality prefix)"),
                ):
                    """Autocomplete endpoint for city and locality suggestions."""
                    ql = q.lower().strip()
                    if not ql or len(ql) < 1:
                        return {"suggestions": [], "query": q}

                    cities = ns.get_all_cities()
                    suggestions: list[dict[str, Any]] = []

                    # Match cities
                    for city in cities:
                        if ql in city["name"].lower():
                            suggestions.append({
                                "type": "city",
                                "text": city["name"],
                                "subtitle": f"Avg. ₹{city['avg_price']:,.0f}/sq.ft",
                                "icon": "🏙️",
                            })

                    # Match localities
                    for city in cities:
                        for loc in city["localities"]:
                            if ql in loc.lower():
                                suggestions.append({
                                    "type": "locality",
                                    "text": loc,
                                    "subtitle": f"in {city['name']}",
                                    "icon": "📍",
                                    "city": city["name"],
                                })

                    # Sort: exact matches first, then prefix matches, then substring
                    def sort_key(s: dict[str, Any]) -> int:
                        t = s["text"].lower()
                        if t == ql:
                            return 0
                        if t.startswith(ql):
                            return 1
                        return 2

                    suggestions.sort(key=sort_key)
                    suggestions = suggestions[:10]  # Max 10 suggestions

                    return {"suggestions": suggestions, "query": q}

                if app is not None:
                    app.include_router(autocomplete_router)
                results["autocomplete_api"] = {"status": "ok"}
                _log.info("[RE] Location autocomplete API initialized")
        except (ImportError, ValueError, TypeError, RuntimeError) as exc:
            _log.debug("[RE] Autocomplete API skipped: %s", exc)
            results["autocomplete_api"] = {"status": "skipped"}

        # ── Performance Caching ─────────────────────────────────────────────────
        try:
            from realestate.cache import analytics_cache, neighborhood_cache, property_cache
            results["performance_cache"] = {
                "status": "ok",
                "property_cache_max": property_cache._max_size,
                "neighborhood_cache_ttl": neighborhood_cache._default_ttl,
                "analytics_cache_ttl": analytics_cache._default_ttl,
            }
            _log.info("[RE] Performance caching initialized")
        except (ImportError, ValueError, TypeError) as exc:
            _log.debug("[RE] Performance caching skipped: %s", exc)
            results["performance_cache"] = {"status": "skipped"}

        # ── WebSocket Notifications ─────────────────────────────────────────────
        try:
            from realestate.websocket import create_websocket_router
            if app is not None:
                app.include_router(create_websocket_router())
            results["websocket_notifications"] = {"status": "ok"}
            _log.info("[RE] WebSocket notifications initialized at /ws/notifications/{user_id}")
        except (ImportError, ValueError, TypeError, RuntimeError) as exc:
            _log.debug("[RE] WebSocket notifications skipped: %s", exc)
            results["websocket_notifications"] = {"status": "skipped"}

        # ── Property Comparison Tool ────────────────────────────────────────
        try:
            from realestate.comparison import (
                create_comparison_page_router,
                create_comparison_router,
            )
            ps = services.get("property_service")
            if app is not None:
                app.include_router(create_comparison_router(property_service=ps))
                app.include_router(create_comparison_page_router())
            results["property_comparison"] = {"status": "ok"}
            _log.info("[RE] Property comparison tool initialized")
        except (ImportError, ValueError, TypeError) as exc:
            _log.debug("[RE] Property comparison skipped: %s", exc)
            results["property_comparison"] = {"status": "skipped"}

        # ── Analytics Dashboard ────────────────────────────────────────────────
        try:
            from realestate.analytics_dashboard import (
                AnalyticsService,
                create_analytics_page_router,
                create_analytics_router,
            )
            svc = AnalyticsService.get_instance()
            svc._ps = services.get("property_service")
            svc._ls = services.get("lead_service")
            if app is not None:
                app.include_router(create_analytics_router(
                    property_service=services.get("property_service"),
                    lead_service=services.get("lead_service"),
                ))
                app.include_router(create_analytics_page_router())
            results["analytics_dashboard"] = {"status": "ok"}
            _log.info("[RE] Analytics dashboard initialized")
        except (ImportError, ValueError, TypeError) as exc:
            _log.debug("[RE] Analytics dashboard skipped: %s", exc)
            results["analytics_dashboard"] = {"status": "skipped"}

        # ── Security Middleware ─────────────────────────────────────────────────
        try:
            from realestate.security import apply_security_middleware
            if app is not None:
                apply_security_middleware(app, rate_limit=True, security_headers=True)
            results["security_middleware"] = {"status": "ok"}
            _log.info("[RE] Security middleware applied")
        except (ImportError, ValueError, TypeError) as exc:
            _log.debug("[RE] Security middleware skipped: %s", exc)
            results["security_middleware"] = {"status": "skipped"}

        # ── OAuth Authentication ────────────────────────────────────────────────
        try:
            from realestate.auth_service import (
                create_auth_page_router,
                create_auth_router,
            )
            if app is not None:
                app.include_router(create_auth_router())
                app.include_router(create_auth_page_router())
            results["oauth_auth"] = {"status": "ok"}
            _log.info("[RE] OAuth authentication initialized at /api/realestate/auth")
        except (ImportError, ValueError, TypeError, RuntimeError) as exc:
            _log.debug("[RE] OAuth authentication skipped: %s", exc)
            results["oauth_auth"] = {"status": "skipped"}

        # ── SEO / Sitemap ────────────────────────────────────────────────────────
        try:
            from realestate.seo import create_seo_router
            if app is not None:
                seo_property_service = services.get("property_service")
                app.include_router(create_seo_router(property_service=seo_property_service))
            results["seo"] = {"status": "ok"}
            _log.info("[RE] SEO endpoints initialized: /sitemap.xml, /robots.txt")
        except (ImportError, ValueError, TypeError, RuntimeError) as exc:
            _log.debug("[RE] SEO skipped: %s", exc)
            results["seo"] = {"status": "skipped"}

        # ── Prometheus Monitoring ──────────────────────────────────────────────────
        try:
            from realestate.prometheus_monitoring import apply_monitoring
            if app is not None:
                apply_monitoring(app)
            results["monitoring"] = {"status": "ok"}
            _log.info("[RE] Monitoring: /metrics, /health, metrics middleware applied")
        except (ImportError, ValueError, TypeError, RuntimeError) as exc:
            _log.debug("[RE] Monitoring skipped: %s", exc)
            results["monitoring"] = {"status": "skipped"}

        # ── Fraud Detection ─────────────────────────────────────────────────────────
        try:
            from realestate.fraud_detection import create_fraud_router
            if app is not None:
                app.include_router(create_fraud_router())
            results["fraud_detection"] = {"status": "ok"}
            _log.info("[RE] Fraud detection engine initialized")
        except (ImportError, ValueError, TypeError, RuntimeError) as exc:
            _log.debug("[RE] Fraud detection skipped: %s", exc)
            results["fraud_detection"] = {"status": "skipped"}

        # ── Webhook System ─────────────────────────────────────────────────────────
        try:
            from realestate.webhooks import create_webhook_router
            if app is not None:
                app.include_router(create_webhook_router())
            results["webhooks"] = {"status": "ok"}
            _log.info("[RE] Webhook system initialized")
        except (ImportError, ValueError, TypeError, RuntimeError) as exc:
            _log.debug("[RE] Webhooks skipped: %s", exc)
            results["webhooks"] = {"status": "skipped"}

        # ── Scheduled Tasks / Scheduler ─────────────────────────────────────────────
        try:
            from realestate.scheduler import create_scheduler_router, initialize_scheduler
            scheduler = initialize_scheduler(services=services)
            services["scheduler"] = scheduler
            if app is not None:
                app.include_router(create_scheduler_router(scheduler))
            results["scheduler"] = {"status": "ok"}
            _log.info("[RE] Scheduler initialized with %d default tasks", len(scheduler.list_tasks()))
        except (ImportError, ValueError, TypeError, RuntimeError) as exc:
            _log.debug("[RE] Scheduler skipped: %s", exc)
            results["scheduler"] = {"status": "skipped"}

        results[REAL_ESTATE_STARTUP_KEY] = {"status": "ok"}
        results["_ok"] = True
        _log.info("[RE] Real estate platform initialized successfully")

    except (ImportError, ValueError, TypeError, RuntimeError) as exc:
        _log.error("[RE] Failed to initialize real estate platform: %s", exc)
        results[REAL_ESTATE_STARTUP_KEY] = {"status": "error", "detail": str(exc)}

    return results
