"""Real Estate Analytics Dashboard — KPIs, charts, and trend analysis.

Provides:
  - AnalyticsService: computes metrics from property/lead/enquiry data
  - REST API: GET /api/realestate/analytics/{dashboard}
  - HTML page: /realestate/analytics
  - Metrics: total properties, total views, leads funnel, conversion rates,
    popular cities, price trends, broker performance
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from realestate.application.services import MultiLanguageService, PropertyService

_log = logging.getLogger(__name__)

_TEMPLATES_DIR = None


def _get_templates() -> Jinja2Templates:
    global _TEMPLATES_DIR
    if _TEMPLATES_DIR is None:
        from pathlib import Path
        _TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "realestate"
        _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    return Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class DashboardMetrics:
    """Aggregate metrics for the dashboard overview."""
    total_properties: int = 0
    total_views: int = 0
    total_enquiries: int = 0
    total_leads: int = 0
    active_listings: int = 0
    featured_count: int = 0
    verified_count: int = 0
    avg_price: float = 0.0
    avg_price_per_sqft: float = 0.0
    total_cities: int = 0
    total_unique_owners: int = 0
    generated_at: float = 0.0


@dataclass
class LeadFunnel:
    """Lead conversion funnel data."""
    new: int = 0
    contacted: int = 0
    interested: int = 0
    visit_scheduled: int = 0
    visit_completed: int = 0
    negotiating: int = 0
    closed: int = 0
    lost: int = 0
    conversion_rate: float = 0.0  # closed / total
    total: int = 0


@dataclass
class CityBreakdown:
    """Per-city property metrics."""
    city: str = ""
    count: int = 0
    avg_price: float = 0.0
    avg_price_per_sqft: float = 0.0
    total_views: int = 0
    avg_bedrooms: float = 0.0
    featured_count: int = 0


# ── Analytics Service ────────────────────────────────────────────────────────

class AnalyticsService:
    """Computes analytics metrics from the platform's data stores."""

    def __init__(
        self,
        property_service: PropertyService | None = None,
        lead_service: Any = None,
        notification_engine: Any = None,
    ):
        self._ps = property_service
        self._ls = lead_service
        self._ne = notification_engine

    _instance: AnalyticsService | None = None

    @classmethod
    def get_instance(cls) -> AnalyticsService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_overview(self) -> DashboardMetrics:
        """Compute aggregate dashboard metrics."""
        if not self._ps:
            return DashboardMetrics(generated_at=time.time())

        props = self._ps.list_all()
        total_views = sum(p.views for p in props)
        active = [p for p in props]  # all listed are considered active
        prices = [p.price for p in props if p.price > 0]
        areas = [p.carpet_area_sqft for p in props if p.carpet_area_sqft > 0]
        cities = set(p.city for p in props if p.city)
        owners = set(p.owner_id for p in props if p.owner_id)

        avg_price = sum(prices) / len(prices) if prices else 0.0

        # Lead data
        lead_count = 0
        if self._ls:
            try:
                lead_count = len(self._ls.get_leads())
            except Exception:
                pass

        return DashboardMetrics(
            total_properties=len(props),
            total_views=total_views,
            total_enquiries=sum(getattr(p, 'enquiries', 0) for p in props),
            total_leads=lead_count,
            active_listings=len(active),
            featured_count=sum(1 for p in props if p.is_featured),
            verified_count=sum(1 for p in props if p.is_verified),
            avg_price=round(avg_price, 2),
            avg_price_per_sqft=round(avg_price / (sum(areas) / len(areas)), 2) if areas else 0.0,
            total_cities=len(cities),
            total_unique_owners=len(owners),
            generated_at=time.time(),
        )

    def get_lead_funnel(self) -> LeadFunnel:
        """Compute lead conversion funnel."""
        if not self._ls:
            return LeadFunnel()

        try:
            leads = self._ls.get_leads()
        except Exception:
            return LeadFunnel()

        funnel = LeadFunnel(total=len(leads))
        for lead in leads:
            status = lead.status if hasattr(lead, "status") else getattr(lead, "status", "")
            if status == "new":
                funnel.new += 1
            elif status == "contacted":
                funnel.contacted += 1
            elif status == "interested":
                funnel.interested += 1
            elif status == "visit_scheduled":
                funnel.visit_scheduled += 1
            elif status == "visit_completed":
                funnel.visit_completed += 1
            elif status == "negotiating":
                funnel.negotiating += 1
            elif status == "closed":
                funnel.closed += 1
            elif status == "lost":
                funnel.lost += 1

        if funnel.total > 0:
            funnel.conversion_rate = round(funnel.closed / funnel.total * 100, 1)
        return funnel

    def get_city_breakdown(self) -> list[CityBreakdown]:
        """Compute per-city property metrics."""
        if not self._ps:
            return []

        props = self._ps.list_all()
        city_map: dict[str, list[Any]] = {}
        for p in props:
            c = p.city or "Unknown"
            city_map.setdefault(c, []).append(p)

        result = []
        for city, city_props in sorted(city_map.items()):
            prices = [p.price for p in city_props if p.price > 0]
            result.append(CityBreakdown(
                city=city,
                count=len(city_props),
                avg_price=round(sum(prices) / len(prices), 2) if prices else 0.0,
                avg_price_per_sqft=round(
                    sum(prices) / sum(p.carpet_area_sqft for p in city_props if p.carpet_area_sqft > 0), 2
                ) if any(p.carpet_area_sqft > 0 for p in city_props) else 0.0,
                total_views=sum(p.views for p in city_props),
                avg_bedrooms=round(
                    sum(p.bedrooms for p in city_props) / len(city_props), 1
                ) if city_props else 0.0,
                featured_count=sum(1 for p in city_props if p.is_featured),
            ))

        return result

    def get_property_type_distribution(self) -> dict[str, int]:
        """Get property type counts."""
        if not self._ps:
            return {}
        props = self._ps.list_all()
        dist: dict[str, int] = {}
        for p in props:
            pt = p.property_type or "unknown"
            dist[pt] = dist.get(pt, 0) + 1
        return dict(sorted(dist.items(), key=lambda x: -x[1]))

    def get_top_properties(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get top properties by views."""
        if not self._ps:
            return []
        props = self._ps.list_all()
        sorted_props = sorted(props, key=lambda p: p.views, reverse=True)[:limit]
        return [
            {
                "property_id": p.property_id,
                "title": p.title,
                "price": p.price,
                "city": p.city,
                "locality": p.locality,
                "views": p.views,
                "enquiries": getattr(p, 'enquiries', 0),
                "favourites": getattr(p, 'favourites', 0),
            }
            for p in sorted_props
        ]

    def get_stats_summary(self) -> dict[str, Any]:
        """Get a quick stats summary (for dashboard sidebar)."""
        overview = self.get_overview()
        funnel = self.get_lead_funnel()
        cities = self.get_city_breakdown()
        types = self.get_property_type_distribution()
        top = self.get_top_properties(5)

        return {
            "overview": {
                "total_properties": overview.total_properties,
                "total_views": overview.total_views,
                "total_enquiries": overview.total_enquiries,
                "total_leads": overview.total_leads,
                "active_listings": overview.active_listings,
                "avg_price": overview.avg_price,
                "avg_price_per_sqft": overview.avg_price_per_sqft,
                "featured_count": overview.featured_count,
                "verified_count": overview.verified_count,
                "total_cities": overview.total_cities,
                "total_unique_owners": overview.total_unique_owners,
            },
            "lead_funnel": {
                "new": funnel.new,
                "contacted": funnel.contacted,
                "interested": funnel.interested,
                "visit_scheduled": funnel.visit_scheduled,
                "negotiating": funnel.negotiating,
                "closed": funnel.closed,
                "lost": funnel.lost,
                "conversion_rate": funnel.conversion_rate,
                "total": funnel.total,
            },
            "city_breakdown": [
                {"city": c.city, "count": c.count, "avg_price": c.avg_price,
                 "avg_price_per_sqft": c.avg_price_per_sqft, "total_views": c.total_views}
                for c in cities
            ],
            "property_types": types,
            "top_properties": top,
            "generated_at": time.time(),
        }


# ── API Router ───────────────────────────────────────────────────────────────

def create_analytics_router(
    property_service: PropertyService | None = None,
    lead_service: Any = None,
    notification_engine: Any = None,
) -> APIRouter:
    """Create the analytics API router."""
    router = APIRouter(prefix="/api/realestate/analytics", tags=["Real Estate Analytics"])

    @router.get("/overview")
    async def analytics_overview():
        """Get aggregate dashboard overview metrics."""
        svc = AnalyticsService.get_instance()
        if property_service:
            svc._ps = property_service
        if lead_service:
            svc._ls = lead_service
        return svc.get_overview()

    @router.get("/leads-funnel")
    async def analytics_leads_funnel():
        """Get lead conversion funnel data."""
        svc = AnalyticsService.get_instance()
        if lead_service:
            svc._ls = lead_service
        return svc.get_lead_funnel()

    @router.get("/city-breakdown")
    async def analytics_city_breakdown():
        """Get per-city property metrics."""
        svc = AnalyticsService.get_instance()
        if property_service:
            svc._ps = property_service
        return svc.get_city_breakdown()

    @router.get("/property-types")
    async def analytics_property_types():
        """Get property type distribution."""
        svc = AnalyticsService.get_instance()
        if property_service:
            svc._ps = property_service
        return svc.get_property_type_distribution()

    @router.get("/top-properties")
    async def analytics_top_properties(limit: int = Query(10, ge=1, le=50)):
        """Get top properties by views."""
        svc = AnalyticsService.get_instance()
        if property_service:
            svc._ps = property_service
        return {"properties": svc.get_top_properties(limit)}

    @router.get("/summary")
    async def analytics_summary():
        """Get complete analytics summary."""
        svc = AnalyticsService.get_instance()
        if property_service:
            svc._ps = property_service
        if lead_service:
            svc._ls = lead_service
        return svc.get_stats_summary()

    return router


# ── HTML Page ────────────────────────────────────────────────────────────────

def create_analytics_page_router() -> APIRouter:
    """Create router for the analytics HTML dashboard page."""
    router = APIRouter(tags=["Real Estate Pages"])
    templates = _get_templates()
    mls = MultiLanguageService()

    @router.get("/realestate/analytics", response_class=HTMLResponse)
    async def analytics_dashboard_page(request: Request):
        """Full analytics dashboard with charts and KPIs."""
        return templates.TemplateResponse(
            request=request,
            name="analytics.html",
            context={
                "languages": mls.get_supported_languages(),
                "current_lang": "en",
            },
        )

    return router
