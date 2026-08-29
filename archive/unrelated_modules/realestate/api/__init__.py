"""API layer — FastAPI routes for the real estate platform.

Provides RESTful endpoints for:
  - Property CRUD and search
  - Lead management / CRM
  - Rent agreements and e-stamping
  - Neighborhood insights
  - Multi-language support
  - AI recommendations
"""

from __future__ import annotations

import logging
import time
from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Query
except ImportError:
    class APIRouter:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None: pass
        def get(self, *args: Any, **kwargs: Any) -> Any: return lambda f: f
        def post(self, *args: Any, **kwargs: Any) -> Any: return lambda f: f
        def put(self, *args: Any, **kwargs: Any) -> Any: return lambda f: f
        def delete(self, *args: Any, **kwargs: Any) -> Any: return lambda f: f
    class HTTPException(Exception):  # type: ignore
        def __init__(self, status_code: int = 500, detail: str = "") -> None:
            self.status_code = status_code
            self.detail = detail
            super().__init__(f"[{status_code}] {detail}")
    def Query(*args: Any, **kwargs: Any) -> Any: return None  # noqa: N802 # type: ignore


from realestate.application.dto import (
    EnquiryDTO,
    LeadDTO,
    PropertyDTO,
    PropertySearchQuery,
    PropertySearchResult,
    RentAgreementDTO,
)
from realestate.application.services import (
    LeadService,
    MultiLanguageService,
    NeighborhoodService,
    PropertySearchService,
    PropertyService,
    RecommendationEngine,
    RentAgreementService,
    create_default_services,
)

_log = logging.getLogger(__name__)


# ── Router Factory ───────────────────────────────────────────────────────────

def create_realestate_router(
    services: dict[str, Any] | None = None,
    auth_deps: Any = None,
) -> APIRouter:
    """Create the real estate API router with all endpoints.

    Args:
        services: dict of service instances, or None to create defaults.
        auth_deps: Optional auth dependency injection (from enterprise dashboard).

    Returns:
        Configured APIRouter instance.
    """
    svc = services or create_default_services()
    router = APIRouter(prefix="/api/realestate", tags=["Real Estate"])

    ps: PropertyService = svc["property_service"]
    ss: PropertySearchService = svc["search_service"]
    ls: LeadService = svc["lead_service"]
    ns: NeighborhoodService = svc["neighborhood_service"]
    ras: RentAgreementService = svc["rent_agreement_service"]
    re: RecommendationEngine = svc["recommendation_engine"]
    mls: MultiLanguageService = svc["multi_language_service"]

    # ── Health & Languages ───────────────────────────────────────────────

    @router.get("/health")
    async def health():
        return {"status": "ok", "service": "realestate", "timestamp": time.time()}

    @router.get("/languages")
    async def get_languages():
        return {"languages": mls.get_supported_languages()}

    # ── Properties ────────────────────────────────────────────────────────

    @router.post("/properties", response_model=PropertyDTO)
    async def create_property(
        title: str = Query(..., description="Property title"),
        description: str = Query("", description="Property description"),
        property_type: str = Query("apartment", description="Property type"),
        price: float = Query(..., description="Price in INR"),
        city: str = Query(..., description="City"),
        locality: str = Query("", description="Locality"),
        bedrooms: int = Query(0, description="Number of bedrooms"),
        bathrooms: int = Query(0, description="Number of bathrooms"),
        carpet_area_sqft: float = Query(0.0, description="Carpet area in sq.ft."),
        owner_id: str = Query("", description="Owner user ID"),
    ):
        """Create a new property listing."""
        prop = ps.create_property(
            title=title, description=description, property_type=property_type,
            price=price, city=city, locality=locality,
            bedrooms=bedrooms, bathrooms=bathrooms,
            carpet_area_sqft=carpet_area_sqft, owner_id=owner_id,
        )
        return prop

    @router.get("/properties", response_model=PropertySearchResult)
    async def search_properties(
        query: str = Query("", description="Full-text search"),
        city: str = Query("", description="City filter"),
        locality: str = Query("", description="Locality filter"),
        property_type: str = Query("", description="Property type filter"),
        listing_type: str = Query("", description="Listing type: sell/rent"),
        min_price: float = Query(0.0, description="Min price"),
        max_price: float = Query(1_000_000_000, description="Max price"),
        min_bedrooms: int = Query(0, description="Min bedrooms"),
        max_bedrooms: int = Query(10, description="Max bedrooms"),
        furnishing: str = Query("", description="Furnishing status"),
        page: int = Query(1, ge=1, description="Page number"),
        page_size: int = Query(20, ge=1, le=100, description="Items per page"),
        sort_by: str = Query("listed_at", description="Sort field"),
        sort_order: str = Query("desc", description="Sort direction"),
        lang: str = Query("en", description="Response language"),
    ):
        """Search properties with multi-criteria filtering."""
        sq = PropertySearchQuery(
            query=query, city=city, locality=locality,
            property_type=property_type, listing_type=listing_type,
            min_price=min_price, max_price=max_price,
            min_bedrooms=min_bedrooms, max_bedrooms=max_bedrooms,
            furnishing=furnishing, page=page, page_size=page_size,
            sort_by=sort_by, sort_order=sort_order,
        )
        result = ss.search(sq)
        # Apply language translation to labels if needed
        if lang != "en" and result.properties:
            result.properties = [
                mls.translate_property(p, lang) for p in result.properties
            ]
        return result

    @router.get("/properties/{property_id}", response_model=PropertyDTO)
    async def get_property(
        property_id: str,
        lang: str = Query("en", description="Response language"),
    ):
        """Get a single property by ID."""
        prop = ps.get_property(property_id)
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
        ps.record_view(property_id)
        return mls.translate_property(prop, lang) if lang != "en" else prop

    @router.put("/properties/{property_id}/media")
    async def add_property_media(
        property_id: str,
        url: str = Query(..., description="Media URL"),
        asset_type: str = Query("photo", description="Type: photo/video/virtual_tour/drone/floor_plan"),
        is_primary: bool = Query(False, description="Set as primary image"),
    ):
        """Add media to a property."""
        success = ps.add_media(property_id, url, asset_type, is_primary)
        if not success:
            raise HTTPException(status_code=404, detail="Property not found")
        return {"success": True}

    @router.delete("/properties/{property_id}")
    async def delete_property(property_id: str):
        """Delete a property listing."""
        success = ps.delete_property(property_id)
        if not success:
            raise HTTPException(status_code=404, detail="Property not found")
        return {"success": True}

    # ── Recommendations ──────────────────────────────────────────────────

    @router.get("/recommendations")
    async def get_recommendations(
        property_id: str = Query("", description="Base property for similar"),
        limit: int = Query(6, ge=1, le=20),
    ):
        """Get property recommendations."""
        recs = re.get_recommendations(
            viewed_property_id=property_id or None,
            limit=limit,
        )
        return {"recommendations": [r.to_dict() for r in recs]}

    # ── Neighborhood ──────────────────────────────────────────────────────

    @router.get("/neighborhood/cities")
    async def get_cities():
        """Get all supported cities with locality data."""
        return {"cities": ns.get_all_cities()}

    @router.get("/neighborhood/{city}/localities")
    async def get_localities(city: str):
        """Get localities for a city."""
        return {"city": city, "localities": ns.get_localities(city)}

    @router.get("/neighborhood/{city}/insight")
    async def get_neighborhood_insight(
        city: str,
        locality: str = Query(..., description="Locality name"),
    ):
        """Get neighborhood insight for a locality."""
        insight = ns.get_neighborhood_insight(city, locality)
        if not insight:
            raise HTTPException(status_code=404, detail="City not found")
        return {"insight": insight.to_dict()}

    # ── Leads & Enquiries ─────────────────────────────────────────────────

    @router.post("/leads", response_model=LeadDTO)
    async def create_lead(
        property_id: str = Query(..., description="Property ID"),
        buyer_name: str = Query(..., description="Buyer name"),
        buyer_phone: str = Query(..., description="Buyer phone"),
        buyer_email: str = Query("", description="Buyer email"),
        budget: float = Query(0.0, description="Budget"),
        source: str = Query("website", description="Lead source"),
    ):
        """Create a new sales lead."""
        return ls.create_lead(
            property_id=property_id, buyer_name=buyer_name,
            buyer_phone=buyer_phone, buyer_email=buyer_email,
            budget=budget, source=source,
        )

    @router.get("/leads", response_model=list[LeadDTO])
    async def get_leads(status: str = Query("", description="Filter by status")):
        """Get all leads, optionally filtered by status."""
        return ls.get_leads(status or None)

    @router.put("/leads/{lead_id}/status")
    async def update_lead_status(lead_id: str, status: str = Query(..., description="New status")):
        """Update lead status."""
        result = ls.update_lead_status(lead_id, status)
        if not result:
            raise HTTPException(status_code=404, detail="Lead not found")
        return result

    @router.post("/enquiries", response_model=EnquiryDTO)
    async def submit_enquiry(
        property_id: str = Query(..., description="Property ID"),
        name: str = Query(..., description="Contact name"),
        email: str = Query(..., description="Contact email"),
        phone: str = Query(..., description="Contact phone"),
        message: str = Query("", description="Enquiry message"),
        enquirer_type: str = Query("buyer", description="Type: buyer/tenant/broker"),
    ):
        """Submit a property enquiry."""
        return ls.submit_enquiry(
            property_id=property_id, name=name, email=email,
            phone=phone, message=message, enquirer_type=enquirer_type,
        )

    @router.get("/enquiries", response_model=list[EnquiryDTO])
    async def get_enquiries(property_id: str = Query("", description="Filter by property")):
        """Get enquiries, optionally filtered by property."""
        return ls.get_enquiries(property_id or None)

    # ── Rent Agreements ───────────────────────────────────────────────────

    @router.post("/agreements/rent", response_model=RentAgreementDTO)
    async def create_rent_agreement(
        property_id: str = Query(..., description="Property ID"),
        landlord_id: str = Query(..., description="Landlord user ID"),
        tenant_name: str = Query("", description="Tenant name"),
        tenant_id: str = Query("", description="Tenant user ID"),
        rent_amount: float = Query(..., description="Monthly rent"),
        security_deposit: float = Query(0.0, description="Security deposit"),
        lease_start: str = Query(..., description="Lease start date (YYYY-MM-DD)"),
        lease_end: str = Query(..., description="Lease end date (YYYY-MM-DD)"),
        notice_period_days: int = Query(30, description="Notice period in days"),
        lock_in_months: int = Query(6, description="Lock-in period in months"),
    ):
        """Create a new rent agreement."""
        return ras.create_agreement(
            property_id=property_id, landlord_id=landlord_id,
            tenant_name=tenant_name, tenant_id=tenant_id,
            rent_amount=rent_amount, security_deposit=security_deposit,
            lease_start=lease_start, lease_end=lease_end,
            notice_period_days=notice_period_days,
            lock_in_months=lock_in_months,
        )

    @router.get("/agreements/rent/{agreement_id}", response_model=RentAgreementDTO)
    async def get_rent_agreement(agreement_id: str):
        """Get a rent agreement by ID."""
        agreement = ras.get_agreement(agreement_id)
        if not agreement:
            raise HTTPException(status_code=404, detail="Agreement not found")
        return agreement

    @router.post("/agreements/rent/{agreement_id}/e-stamp")
    async def initiate_e_stamp(agreement_id: str):
        """Initiate e-stamping for a rent agreement."""
        result = ras.initiate_e_stamp(agreement_id)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error", "Failed"))
        return result

    @router.post("/agreements/rent/{agreement_id}/e-sign")
    async def initiate_e_sign(
        agreement_id: str,
        party: str = Query("both", description="Party to sign: landlord/tenant/both"),
    ):
        """Initiate Aadhaar e-signing for a rent agreement."""
        result = ras.initiate_e_sign(agreement_id, party)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error", "Failed"))
        return result

    # ── Translation ───────────────────────────────────────────────────────

    @router.get("/translate")
    async def translate(
        key: str = Query(..., description="UI translation key"),
        lang: str = Query("en", description="Target language code"),
    ):
        """Get a UI string translation."""
        return {"key": key, "lang": lang, "translation": mls.translate(key, lang)}

    # ── Map Data ───────────────────────────────────────────────────────────

    @router.get("/map-data")
    async def get_map_data(city: str = Query("", description="City filter")):
        """Get property coordinates and prices for map visualization.

        Returns properties with lat/lng coordinates for rendering on
        Leaflet/Mapbox maps. Filters out properties without coordinates.
        """
        all_props = ps.list_all()
        map_props = [
            {
                "property_id": p.property_id,
                "title": p.title,
                "price": p.price,
                "city": p.city,
                "locality": p.locality,
                "lat": p.latitude,
                "lng": p.longitude,
                "bedrooms": p.bedrooms,
            }
            for p in all_props
            if p.latitude and p.longitude
        ]
        if city:
            map_props = [p for p in map_props if p["city"].lower() == city.lower()]
        return {"properties": map_props, "total": len(map_props)}

    return router


# ── Wire helper ──────────────────────────────────────────────────────────────

def wire_realestate_api(
    app: Any,
    services: dict[str, Any] | None = None,
    auth_deps: Any = None,
) -> None:
    """Wire real estate API into a FastAPI app."""
    router = create_realestate_router(services=services, auth_deps=auth_deps)
    app.include_router(router)
    _log.info("[RE] Real estate API mounted at /api/realestate")
