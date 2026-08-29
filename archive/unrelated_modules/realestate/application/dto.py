"""Data Transfer Objects for the real estate platform.

DTOs are used for API request/response serialization
and for communication between layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Property DTOs ────────────────────────────────────────────────────────────

@dataclass
class PropertyDTO:
    """Property data for API responses."""
    property_id: str = ""
    title: str = ""
    description: str = ""
    property_type: str = "apartment"
    listing_type: str = "sell"
    transaction_type: str = "sale"
    price: float = 0.0
    price_per_sqft: float = 0.0
    city: str = ""
    locality: str = ""
    state: str = ""
    pincode: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    bedrooms: int = 0
    bathrooms: int = 0
    balconies: int = 0
    carpet_area_sqft: float = 0.0
    super_area_sqft: float = 0.0
    plot_area_sqft: float = 0.0
    furnishing: str = "unfurnished"
    facing_direction: str = ""
    amenities: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    floor_plan_url: str = ""
    virtual_tour_url: str = ""
    is_featured: bool = False
    is_verified: bool = False
    rera_number: str = ""
    owner_id: str = ""
    broker_id: str = ""
    broker_name: str = ""
    listed_at: float = 0.0
    updated_at: float = 0.0
    views: int = 0
    slug: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class ListingDTO:
    """Published listing DTO."""
    listing_id: str = ""
    property_id: str = ""
    price: float = 0.0
    listing_type: str = "sell"
    status: str = "active"
    created_at: float = 0.0
    total_views: int = 0
    total_enquiries: int = 0


@dataclass
class PropertySearchQuery:
    """Search/filter criteria for properties."""
    query: str = ""
    city: str = ""
    locality: str = ""
    property_type: str = ""
    listing_type: str = ""
    min_price: float = 0.0
    max_price: float = 1_000_000_000.0
    min_bedrooms: int = 0
    max_bedrooms: int = 10
    furnishing: str = ""
    min_area_sqft: float = 0.0
    max_area_sqft: float = 100_000.0
    amenities: list[str] = field(default_factory=list)
    page: int = 1
    page_size: int = 20
    sort_by: str = "listed_at"  # price, area, listed_at, views
    sort_order: str = "desc"    # asc, desc
    featured_first: bool = True
    verified_only: bool = False
    with_virtual_tour: bool = False

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass
class PropertySearchResult:
    """Search result with pagination."""
    properties: list[PropertyDTO] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 1
    facets: dict[str, Any] = field(default_factory=dict)
    query_time_ms: float = 0.0


# ── User DTOs ────────────────────────────────────────────────────────────────

@dataclass
class UserDTO:
    """User profile DTO."""
    user_id: str = ""
    role: str = "buyer"
    name: str = ""
    email: str = ""
    phone: str = ""
    language: str = "en"
    is_verified: bool = False
    rera_registration: str = ""
    company_name: str = ""
    rating: float = 0.0
    total_transactions: int = 0
    created_at: float = 0.0


# ── Lead & Enquiry DTOs ──────────────────────────────────────────────────────

@dataclass
class LeadDTO:
    """Lead/sales opportunity DTO."""
    lead_id: str = ""
    property_id: str = ""
    buyer_name: str = ""
    buyer_phone: str = ""
    buyer_email: str = ""
    budget: float = 0.0
    preferred_localities: list[str] = field(default_factory=list)
    status: str = "new"
    notes: str = ""
    created_at: float = 0.0
    assigned_to: str = ""
    source: str = ""


@dataclass
class EnquiryDTO:
    """Property enquiry DTO."""
    enquiry_id: str = ""
    property_id: str = ""
    name: str = ""
    email: str = ""
    phone: str = ""
    message: str = ""
    enquirer_type: str = "buyer"
    created_at: float = 0.0
    is_read: bool = False


# ── Agreement DTOs ───────────────────────────────────────────────────────────

@dataclass
class RentAgreementDTO:
    """Rental agreement DTO for API."""
    agreement_id: str = ""
    property_id: str = ""
    property_title: str = ""
    landlord_name: str = ""
    tenant_name: str = ""
    rent_amount: float = 0.0
    security_deposit: float = 0.0
    lease_start: str = ""
    lease_end: str = ""
    notice_period_days: int = 30
    lock_in_period_months: int = 6
    status: str = "draft"
    e_stamp_paper_number: str = ""
    e_sign_status: str = ""
    document_url: str = ""
    created_at: float = 0.0


@dataclass
class AgreementDTO:
    """Generic agreement DTO (sale/rent/lease)."""
    agreement_id: str = ""
    type: str = "rent"
    status: str = "draft"
    parties: list[str] = field(default_factory=list)
    property_id: str = ""
    amount: float = 0.0
    created_at: float = 0.0
    signed_at: float = 0.0
