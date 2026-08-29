"""UI layer — HTML templates and static assets for the real estate platform.

Templates are served via FastAPI Jinja2Templates, integrated into the
existing enterprise dashboard template system.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from realestate.application.services import MultiLanguageService

_log = logging.getLogger(__name__)

# Templates are expected at: templates/realestate/
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates" / "realestate"


def get_templates() -> Jinja2Templates:
    """Get the Jinja2 templates instance for real estate pages."""
    _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    return Jinja2Templates(directory=str(_TEMPLATES_DIR))


def create_realestate_pages_router(services: dict[str, Any] | None = None) -> APIRouter:
    """Create a router for HTML page routes."""
    router = APIRouter(tags=["Real Estate Pages"])
    templates = get_templates()
    mls = MultiLanguageService()

    @router.get("/realestate", response_class=HTMLResponse)
    async def realestate_home(request: Request, lang: str = "en"):
        """Real estate platform home page."""
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={
                "languages": mls.get_supported_languages(),
                "current_lang": lang,
                "t": lambda key: mls.translate(key, lang),
            },
        )

    @router.get("/realestate/search", response_class=HTMLResponse)
    async def realestate_search(request: Request, lang: str = "en"):
        """Property search page."""
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context={
                "languages": mls.get_supported_languages(),
                "current_lang": lang,
                "t": lambda key: mls.translate(key, lang),
            },
        )

    @router.get("/realestate/property/{property_id}", response_class=HTMLResponse)
    async def realestate_property_detail(request: Request, property_id: str, lang: str = "en"):
        """Property detail page."""
        return templates.TemplateResponse(
            request=request,
            name="property_detail.html",
            context={
                "property_id": property_id,
                "languages": mls.get_supported_languages(),
                "current_lang": lang,
                "t": lambda key: mls.translate(key, lang),
            },
        )

    @router.get("/realestate/leads", response_class=HTMLResponse)
    async def realestate_leads_dashboard(request: Request, lang: str = "en"):
        """Lead management / CRM dashboard for brokers."""
        return templates.TemplateResponse(
            request=request,
            name="leads_dashboard.html",
            context={
                "languages": mls.get_supported_languages(),
                "current_lang": lang,
                "t": lambda key: mls.translate(key, lang),
            },
        )

    @router.get("/realestate/tenant", response_class=HTMLResponse)
    async def realestate_tenant_portal(request: Request, lang: str = "en"):
        """Tenant portal dashboard."""
        return templates.TemplateResponse(
            request=request,
            name="tenant_dashboard.html",
            context={
                "languages": mls.get_supported_languages(),
                "current_lang": lang,
                "t": lambda key: mls.translate(key, lang),
            },
        )

    @router.get("/realestate/admin", response_class=HTMLResponse)
    async def realestate_admin_panel(request: Request, lang: str = "en"):
        """Admin panel for platform management."""
        return templates.TemplateResponse(
            request=request,
            name="admin_panel.html",
            context={
                "languages": mls.get_supported_languages(),
                "current_lang": lang,
                "t": lambda key: mls.translate(key, lang),
            },
        )

    @router.get("/realestate/api-docs", response_class=HTMLResponse)
    async def realestate_api_docs(request: Request, lang: str = "en"):
        """API documentation page."""
        return templates.TemplateResponse(
            request=request,
            name="api_docs.html",
            context={
                "languages": mls.get_supported_languages(),
                "current_lang": lang,
            },
        )

    @router.get("/realestate/compare", response_class=HTMLResponse)
    async def realestate_compare(request: Request, ids: str = "", lang: str = "en"):
        """Property comparison page."""
        return templates.TemplateResponse(
            request=request,
            name="compare.html",
            context={
                "property_ids": ids,
                "languages": mls.get_supported_languages(),
                "current_lang": lang,
            },
        )

    @router.get("/realestate/analytics", response_class=HTMLResponse)
    async def realestate_analytics(request: Request, lang: str = "en"):
        """Analytics dashboard page."""
        return templates.TemplateResponse(
            request=request,
            name="analytics.html",
            context={
                "languages": mls.get_supported_languages(),
                "current_lang": lang,
            },
        )

    return router


__all__ = [
    "create_realestate_pages_router",
    "get_templates",
]
