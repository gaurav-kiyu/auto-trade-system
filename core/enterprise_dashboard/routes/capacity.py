"""Capacity Planning route registration for the Enterprise Dashboard.

Handles: /api/capacity/* endpoints:
  - /api/capacity/report       — Full capacity analysis report
  - /api/capacity/forecast     — DB growth forecasts
  - /api/capacity/triggers     — Scaling triggers status
  - /api/capacity/throughput   — Throughput trend analysis
  - /api/capacity/changelog    — Capacity change log
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import Depends

_log = logging.getLogger(__name__)


def register_capacity_routes(app, dashboard, admin_only, operator_or_admin) -> None:  # type: ignore[no-untyped-def]
    """Register capacity planning API routes.

    Args:
        app: FastAPI application instance.
        dashboard: EnterpriseDashboard instance.
        admin_only: FastAPI Depends for admin role.
        operator_or_admin: FastAPI Depends for operator or admin role.

    """

    @app.get("/api/capacity/report", tags=["Capacity"])
    async def api_capacity_report(user: Any = Depends(operator_or_admin)):
        """Get full capacity planning analysis report."""
        try:
            from core.capacity_planning import CapacityPlanner
            planner = CapacityPlanner(dashboard._cfg)
            report = planner.analyze()
            return report.to_dict()
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Capacity report unavailable: %s", exc)
            return {"status": "unavailable", "detail": str(exc)}

    @app.get("/api/capacity/forecast", tags=["Capacity"])
    async def api_capacity_forecast(
        db_path: str = "db/trades.db",
        user: Any = Depends(operator_or_admin),
    ):
        """Get DB growth forecast for a specific database."""
        try:
            from core.capacity_planning import CapacityPlanner
            planner = CapacityPlanner(dashboard._cfg)
            forecast = planner.estimate_db_growth(db_path)
            if forecast:
                return forecast.to_dict()
            return {"status": "not_found", "detail": f"DB not found: {db_path}"}
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Capacity forecast unavailable: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/capacity/triggers", tags=["Capacity"])
    async def api_capacity_triggers(user: Any = Depends(admin_only)):
        """Get scaling trigger configuration and status."""
        try:
            from core.capacity_planning import CapacityPlanner
            planner = CapacityPlanner(dashboard._cfg)
            triggers = planner.get_triggers()
            return {
                "triggers": [t.to_dict() for t in triggers],
                "count": len(triggers),
                "timestamp": time.time(),
            }
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Capacity triggers unavailable: %s", exc)
            return {"triggers": [], "count": 0, "error": str(exc)}

    @app.get("/api/capacity/throughput", tags=["Capacity"])
    async def api_capacity_throughput(user: Any = Depends(operator_or_admin)):
        """Get trade throughput trend analysis."""
        try:
            from core.capacity_planning import CapacityPlanner
            planner = CapacityPlanner(dashboard._cfg)
            trend = planner.get_throughput_trend()
            return trend
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Throughput trend unavailable: %s", exc)
            return {"status": "unavailable", "detail": str(exc)}

    @app.get("/api/capacity/changelog", tags=["Capacity"])
    async def api_capacity_changelog(
        limit: int = 50,
        user: Any = Depends(admin_only),
    ):
        """Get capacity change log entries."""
        try:
            from core.capacity_planning import CapacityPlanner
            planner = CapacityPlanner(dashboard._cfg)
            log_entries = planner.get_change_log(limit=min(limit, 200))
            return {"log": log_entries, "count": len(log_entries), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Capacity changelog unavailable: %s", exc)
            return {"log": [], "count": 0, "error": str(exc)}
