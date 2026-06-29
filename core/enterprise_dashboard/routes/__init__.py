"""
Route registration package for Enterprise Dashboard.

Each module defines a ``register_*_routes(app, dashboard, ...)`` function
that registers route handlers on the FastAPI ``app`` instance using the
supplied ``dashboard`` (EnterpriseDashboard) for shared dependencies.

Route groups:
  - pages.py:     HTML page routes (/, /login, /admin/*, /change-password, redirects)
  - system.py:    Read-only system API (/api/system/*)
  - admin.py:     Admin control (/api/config/*, /api/changes/*, kill/resume/pause, self-test)
  - risk.py:      Risk & SLO endpoints (/api/risk/*, /api/slo/*, /api/portfolio/*)
  - monitoring.py: Notifications, broker, ML, data providers, performance, trades export
  - fundamentals.py: Fundamental analysis API (/api/fundamentals/*)
  - webhooks.py:  External signal injection, options chain (/signals/inject, /chain/*)

Usage inside EnterpriseDashboard._create_app():
    from core.enterprise_dashboard.routes.pages import register_page_routes
    from core.enterprise_dashboard.routes.system import register_system_routes
    ...
    register_page_routes(app, self, _require_admin_page)
    register_system_routes(app, self, admin_only, operator_or_admin)
    ...
"""

from __future__ import annotations

from core.enterprise_dashboard.routes.admin import register_admin_routes
from core.enterprise_dashboard.routes.fundamentals import register_fundamentals_routes
from core.enterprise_dashboard.routes.monitoring import register_monitoring_routes
from core.enterprise_dashboard.routes.pages import register_page_routes
from core.enterprise_dashboard.routes.risk import register_risk_routes
from core.enterprise_dashboard.routes.system import register_system_routes
from core.enterprise_dashboard.routes.webhooks import register_webhook_routes

__all__ = [
    "register_page_routes",
    "register_system_routes",
    "register_admin_routes",
    "register_risk_routes",
    "register_monitoring_routes",
    "register_fundamentals_routes",
    "register_webhook_routes",
]
