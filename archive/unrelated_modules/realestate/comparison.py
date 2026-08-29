"""Property Comparison Tool — side-by-side comparison of up to 4 properties.

Provides:
  - ComparisonService: manages comparison sessions (add/remove/compare)
  - REST API: POST /compare/add, POST /compare/remove, GET /compare/session
  - HTML page: /realestate/compare?ids=id1,id2,id3
  - Feature matrix: price, area, bedrooms, amenities, location, ratings
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from realestate.application.services import MultiLanguageService, PropertyService

_log = logging.getLogger(__name__)

_TEMPLATES_DIR = None  # resolved lazily


def _get_templates() -> Jinja2Templates:
    global _TEMPLATES_DIR
    if _TEMPLATES_DIR is None:
        from pathlib import Path
        _TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "realestate"
        _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    return Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ── Comparison Session Store ─────────────────────────────────────────────────

class ComparisonSession:
    """Tracks comparison selections for a user/session."""

    def __init__(self) -> None:
        # session_id -> list of property_ids (max 4)
        self._sessions: dict[str, list[str]] = {}

    def add(self, session_id: str, property_id: str) -> dict[str, Any]:
        """Add a property to the comparison session. Returns state."""
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        current = self._sessions[session_id]
        if property_id in current:
            return {"success": True, "property_ids": current, "added": False, "reason": "already_in_session"}
        if len(current) >= 4:
            return {"success": False, "property_ids": current, "added": False, "reason": "max_4"}
        current.append(property_id)
        self._sessions[session_id] = current
        return {"success": True, "property_ids": list(current), "added": True, "count": len(current)}

    def remove(self, session_id: str, property_id: str) -> dict[str, Any]:
        """Remove a property from the comparison session."""
        current = self._sessions.get(session_id, [])
        if property_id in current:
            current.remove(property_id)
            self._sessions[session_id] = current
        return {"success": True, "property_ids": list(current), "removed": property_id not in current}

    def get(self, session_id: str) -> list[str]:
        """Get property IDs in the session."""
        return list(self._sessions.get(session_id, []))

    def clear(self, session_id: str) -> None:
        """Clear the session."""
        self._sessions.pop(session_id, None)


# Global session store
_session_store = ComparisonSession()


def get_comparison_session() -> ComparisonSession:
    """Get the global comparison session store."""
    return _session_store


# ── Comparison Logic ─────────────────────────────────────────────────────────

def build_comparison_matrix(
    property_service: PropertyService,
    property_ids: list[str],
) -> dict[str, Any]:
    """Build a comparison matrix for the given property IDs."""
    props = []
    for pid in property_ids:
        p = property_service.get_property(pid)
        if p:
            props.append(p)

    return {
        "properties": [p.to_dict() if hasattr(p, "to_dict") else _dto_to_dict(p) for p in props],
        "count": len(props),
        "generated_at": time.time(),
        "matrix": _build_feature_matrix(props) if props else {},
    }


def _dto_to_dict(dto: Any) -> dict[str, Any]:
    """Convert a PropertyDTO or similar to a plain dict."""
    if hasattr(dto, "to_dict"):
        return dto.to_dict()
    return {k: v for k, v in dto.__dict__.items()}


def _build_feature_matrix(props: list[Any]) -> dict[str, list[Any]]:
    """Build a feature-by-feature comparison matrix."""
    if not props:
        return {}

    rows: dict[str, list[Any]] = {
        "price": [],
        "price_per_sqft": [],
        "bedrooms": [],
        "bathrooms": [],
        "balconies": [],
        "carpet_area_sqft": [],
        "super_area_sqft": [],
        "furnishing": [],
        "city": [],
        "locality": [],
        "property_type": [],
        "listing_type": [],
        "facing_direction": [],
        "is_featured": [],
        "is_verified": [],
        "rera_number": [],
        "views": [],
        "amenities": [],
        "images": [],
    }

    for p in props:
        p_dict = _dto_to_dict(p)
        for key in rows:
            if key == "amenities":
                rows[key].append(p_dict.get("amenities", []))
            elif key == "images":
                rows[key].append(p_dict.get("images", [])[:3])
            else:
                rows[key].append(p_dict.get(key, "-"))

    return rows


# ── API Router ───────────────────────────────────────────────────────────────

def create_comparison_router(
    property_service: PropertyService | None = None,
) -> APIRouter:
    """Create the comparison API router."""
    if property_service is None:
        raise ValueError("property_service is required for comparison router")
    router = APIRouter(prefix="/api/realestate/compare", tags=["Real Estate Compare"])
    store = get_comparison_session()

    @router.post("/add")
    async def add_to_compare(
        property_id: str = Query(..., description="Property ID to compare"),
        session_id: str = Query("default", description="Session identifier"),
    ):
        """Add a property to the comparison session."""
        result = store.add(session_id, property_id)
        return result

    @router.post("/remove")
    async def remove_from_compare(
        property_id: str = Query(..., description="Property ID to remove"),
        session_id: str = Query("default", description="Session identifier"),
    ):
        """Remove a property from the comparison session."""
        result = store.remove(session_id, property_id)
        return result

    @router.get("/session")
    async def get_comparison_session_api(
        session_id: str = Query("default", description="Session identifier"),
    ):
        """Get the current comparison session."""
        ids = store.get(session_id)
        return {"property_ids": ids, "count": len(ids)}

    @router.post("/clear")
    async def clear_comparison_session(
        session_id: str = Query("default", description="Session identifier"),
    ):
        """Clear the comparison session."""
        store.clear(session_id)
        return {"success": True}

    @router.get("/matrix")
    async def get_comparison_matrix(
        property_ids: str = Query(..., description="Comma-separated property IDs"),
    ):
        """Build a comparison matrix for up to 4 properties."""
        ids = [pid.strip() for pid in property_ids.split(",") if pid.strip()]
        max_allowed = 4
        if len(ids) > max_allowed:
            raise HTTPException(status_code=400, detail=f"Max {max_allowed} properties can be compared at once")
        if len(ids) < 2:
            raise HTTPException(status_code=400, detail="At least 2 properties required for comparison")

        matrix = build_comparison_matrix(property_service, ids)
        return matrix

    return router


# ── HTML Page ────────────────────────────────────────────────────────────────

def create_comparison_page_router() -> APIRouter:
    """Create router for the comparison HTML page."""
    router = APIRouter(tags=["Real Estate Pages"])
    templates = _get_templates()
    mls = MultiLanguageService()

    @router.get("/realestate/compare", response_class=HTMLResponse)
    async def compare_properties_page(
        request: Request,
        ids: str = Query("", description="Comma-separated property IDs to compare"),
    ):
        """Property comparison page with side-by-side matrix."""
        return templates.TemplateResponse(
            request=request,
            name="compare.html",
            context={
                "property_ids": ids,
                "languages": mls.get_supported_languages(),
                "current_lang": "en",
            },
        )

    return router
