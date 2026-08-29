"""Core domain models for Indian real estate platform.

Covers: Property, Listing, Location, Amenities, User profiles,
Leads/CRM, Rent agreements, Builder projects, Neighborhood insights.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

# ── Enumerations ─────────────────────────────────────────────────────────────

class PropertyType(Enum):
    APARTMENT = "apartment"
    HOUSE = "house"
    VILLA = "villa"
    PLOT = "plot"
    COMMERCIAL_OFFICE = "commercial_office"
    COMMERCIAL_SHOP = "commercial_shop"
    COMMERCIAL_WAREHOUSE = "commercial_warehouse"
    FARMHOUSE = "farmhouse"
    PENTHOUSE = "penthouse"
    STUDIO = "studio"


class ListingType(Enum):
    SELL = "sell"
    RENT = "rent"
    AUCTION = "auction"
    RESALE = "resale"


class UserRole(Enum):
    BUYER = "buyer"
    SELLER = "seller"
    BROKER = "broker"
    DEVELOPER = "developer"
    TENANT = "tenant"
    ADMIN = "admin"
    MODERATOR = "moderator"


class FurnishingStatus(Enum):
    FURNISHED = "furnished"
    SEMI_FURNISHED = "semi_furnished"
    UNFURNISHED = "unfurnished"


class TransactionType(Enum):
    SALE = "sale"
    RENT = "rent"
    LEASE = "lease"


class AgreementStatus(Enum):
    DRAFT = "draft"
    PENDING_SIGNATURE = "pending_signature"
    E_SIGNED = "e_signed"
    E_STAMPED = "e_stamped"
    REGISTERED = "registered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class LeadStatus(Enum):
    NEW = "new"
    CONTACTED = "contacted"
    INTERESTED = "interested"
    VISIT_SCHEDULED = "visit_scheduled"
    VISIT_COMPLETED = "visit_completed"
    NEGOTIATING = "negotiating"
    CLOSED = "closed"
    LOST = "lost"


# ── Value Objects ────────────────────────────────────────────────────────────

@dataclass
class Address:
    street: str = ""
    locality: str = ""
    sub_locality: str = ""
    city: str = ""
    state: str = ""
    pincode: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    full_address: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "street": self.street, "locality": self.locality,
            "sub_locality": self.sub_locality, "city": self.city,
            "state": self.state, "pincode": self.pincode,
            "latitude": self.latitude, "longitude": self.longitude,
            "full_address": self.full_address,
        }


@dataclass
class Location:
    """Location with geo-coordinates, map data, and neighborhood info."""
    address: Address = field(default_factory=Address)
    nearby_transit: list[str] = field(default_factory=list)
    nearby_schools: list[dict[str, Any]] = field(default_factory=list)
    nearby_hospitals: list[dict[str, Any]] = field(default_factory=list)
    nearby_malls: list[str] = field(default_factory=list)
    walk_score: int = 0
    transit_score: int = 0
    aqi_rating: str = ""  # good, moderate, poor, very_poor, severe
    crime_index: float = 0.0
    police_station_distance_km: float = 0.0
    fire_station_distance_km: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address.to_dict(),
            "nearby_transit": self.nearby_transit,
            "nearby_schools": self.nearby_schools[:5],
            "nearby_hospitals": self.nearby_hospitals[:5],
            "walk_score": self.walk_score,
            "transit_score": self.transit_score,
            "aqi_rating": self.aqi_rating,
            "crime_index": self.crime_index,
        }


@dataclass
class Amenities:
    """Property amenities — Indian market specific."""
    bedrooms: int = 0
    bathrooms: int = 0
    balconies: int = 0
    parking: int = 0  # number of parking spots
    furnishing: FurnishingStatus = FurnishingStatus.UNFURNISHED
    floor_number: int = 0
    total_floors: int = 0
    carpet_area_sqft: float = 0.0
    super_area_sqft: float = 0.0
    plot_area_sqft: float = 0.0
    facing_direction: str = ""  # north, south, east, west, north-east, etc.
    age_of_property_years: int = 0
    amenities_list: list[str] = field(default_factory=list)
    # Indian market specifics
    gated_community: bool = False
    power_backup: bool = False
    water_supply_24x7: bool = False
    security_personnel: bool = False
    clubhouse: bool = False
    swimming_pool: bool = False
    gym: bool = False
    park: bool = False
    lift: bool = False
    sewage_treatment: bool = False
    rain_water_harvesting: bool = False
    vaastu_compliant: bool = False
    loan_available: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {k: v.value if isinstance(v, Enum) else v
                for k, v in self.__dict__.items()}


@dataclass
class MediaAsset:
    """Photo, video, 3D tour, or drone footage."""
    asset_type: str = "photo"  # photo, video, virtual_tour, drone, floor_plan
    url: str = ""
    caption: str = ""
    is_primary: bool = False
    uploaded_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass
class PriceHistory:
    """Track price changes over time."""
    price: Decimal = Decimal("0")
    recorded_at: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": float(self.price),
            "recorded_at": self.recorded_at,
            "notes": self.notes,
        }


@dataclass
class NeighborhoodInsight:
    """AI-generated neighborhood analysis."""
    area_name: str = ""
    summary: str = ""
    avg_price_per_sqft: float = 0.0
    price_trend_6m: float = 0.0  # percentage change
    rental_yield_pct: float = 0.0
    demand_index: float = 0.0  # 0-100
    upcoming_infra: list[str] = field(default_factory=list)
    schools_rating: float = 0.0  # 0-10
    hospitals_rating: float = 0.0  # 0-10
    connectivity_rating: float = 0.0  # 0-10
    safety_rating: float = 0.0  # 0-10
    last_updated: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


# ── User Profiles ────────────────────────────────────────────────────────────

@dataclass
class UserProfile:
    """Base user profile with Indian real estate role."""
    user_id: str = ""
    role: UserRole = UserRole.BUYER
    name: str = ""
    email: str = ""
    phone: str = ""
    language: str = "en"  # Preferred language
    created_at: float = 0.0
    is_verified: bool = False
    aadhaar_verified: bool = False
    pan_verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["role"] = self.role.value
        return d


@dataclass
class SellerProfile(UserProfile):
    role: UserRole = UserRole.SELLER
    properties_for_sale: list[str] = field(default_factory=list)
    total_listings: int = 0
    response_time_minutes: int = 0
    rating: float = 0.0


@dataclass
class BrokerProfile(UserProfile):
    role: UserRole = UserRole.BROKER
    brokerage_firm: str = ""
    rera_registration: str = ""  # RERA registration number
    license_number: str = ""
    years_experience: int = 0
    total_transactions: int = 0
    rating: float = 0.0
    service_areas: list[str] = field(default_factory=list)
    commission_pct: float = 0.0


@dataclass
class DeveloperProfile(UserProfile):
    role: UserRole = UserRole.DEVELOPER
    company_name: str = ""
    rera_registration: str = ""
    projects_completed: int = 0
    projects_ongoing: int = 0
    rating: float = 0.0
    website: str = ""


@dataclass
class TenantProfile(UserProfile):
    role: UserRole = UserRole.TENANT
    current_rent: float = 0.0
    lease_end_date: str = ""
    preferred_localities: list[str] = field(default_factory=list)
    max_budget: float = 0.0
    employment_type: str = ""


# ── Property & Listing ──────────────────────────────────────────────────────

@dataclass
class Property:
    """Core property entity."""
    property_id: str = ""
    title: str = ""
    description: str = ""
    property_type: PropertyType = PropertyType.APARTMENT
    listing_type: ListingType = ListingType.SELL
    transaction_type: TransactionType = TransactionType.SALE
    price: Decimal = Decimal("0")
    price_per_sqft: Decimal = Decimal("0")
    location: Location = field(default_factory=Location)
    amenities: Amenities = field(default_factory=Amenities)
    media: list[MediaAsset] = field(default_factory=list)
    price_history: list[PriceHistory] = field(default_factory=list)
    neighborhood: NeighborhoodInsight | None = None

    # Ownership
    owner_id: str = ""
    broker_id: str = ""
    developer_id: str = ""

    # Status
    is_active: bool = True
    is_featured: bool = False
    is_verified: bool = False
    verification_date: float = 0.0
    rera_number: str = ""  # RERA registration number

    # Dates
    listed_at: float = 0.0
    updated_at: float = 0.0
    expiry_date: float = 0.0

    # SEO
    meta_title: str = ""
    meta_description: str = ""
    slug: str = ""

    # Counter metrics
    views: int = 0
    enquiries: int = 0
    favourites: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "property_id": self.property_id,
            "title": self.title,
            "description": self.description[:200] if self.description else "",
            "property_type": self.property_type.value,
            "listing_type": self.listing_type.value,
            "transaction_type": self.transaction_type.value,
            "price": float(self.price),
            "price_per_sqft": float(self.price_per_sqft),
            "location": self.location.to_dict(),
            "amenities": self.amenities.to_dict(),
            "media": [m.to_dict() for m in self.media[:5]],
            "owner_id": self.owner_id,
            "broker_id": self.broker_id,
            "is_active": self.is_active,
            "is_featured": self.is_featured,
            "is_verified": self.is_verified,
            "rera_number": self.rera_number,
            "listed_at": self.listed_at,
            "updated_at": self.updated_at,
            "views": self.views,
            "enquiries": self.enquiries,
            "favourites": self.favourites,
        }


@dataclass
class Listing:
    """A published listing (a property offered at a point in time)."""
    listing_id: str = ""
    property_id: str = ""
    listed_by_id: str = ""
    listed_by_role: UserRole = UserRole.SELLER
    listing_type: ListingType = ListingType.SELL
    price: Decimal = Decimal("0")
    description: str = ""
    # SEO & promotion
    featured_until: float = 0.0
    boost_level: int = 0  # 0-5
    # Status
    status: str = "active"  # active, sold, rented, expired, withdrawn
    # Dates
    created_at: float = 0.0
    renewed_at: float = 0.0
    expires_at: float = 0.0
    # Metrics
    total_views: int = 0
    total_enquiries: int = 0
    phone_views: int = 0

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


# ── Builder/Developer Projects ──────────────────────────────────────────────

@dataclass
class BuilderProject:
    """A builder/developer project with multiple units."""
    project_id: str = ""
    developer_id: str = ""
    name: str = ""
    description: str = ""
    rera_registration: str = ""
    location: Location = field(default_factory=Location)
    amenities: Amenities = field(default_factory=Amenities)
    total_units: int = 0
    available_units: int = 0
    price_range_min: Decimal = Decimal("0")
    price_range_max: Decimal = Decimal("0")
    possession_date: str = ""  # e.g., "Dec 2026"
    status: str = "ongoing"  # ongoing, completed, pre_launch, launched
    approval_authority: str = ""
    media: list[MediaAsset] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "developer_id": self.developer_id,
            "name": self.name,
            "description": self.description[:200],
            "rera_registration": self.rera_registration,
            "location": self.location.to_dict(),
            "total_units": self.total_units,
            "available_units": self.available_units,
            "price_range_min": float(self.price_range_min),
            "price_range_max": float(self.price_range_max),
            "possession_date": self.possession_date,
            "status": self.status,
            "created_at": self.created_at,
        }


# ── Lead Management / CRM ──────────────────────────────────────────────────

@dataclass
class Lead:
    """A sales lead from property enquiry."""
    lead_id: str = ""
    property_id: str = ""
    buyer_id: str = ""
    broker_id: str = ""
    status: LeadStatus = LeadStatus.NEW
    buyer_name: str = ""
    buyer_phone: str = ""
    buyer_email: str = ""
    budget: Decimal = Decimal("0")
    preferred_localities: list[str] = field(default_factory=list)
    notes: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    assigned_to: str = ""
    source: str = ""  # website, app, call, walk_in, referral

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["status"] = self.status.value
        d["budget"] = float(self.budget)
        return d


@dataclass
class Enquiry:
    """A property enquiry/support ticket."""
    enquiry_id: str = ""
    property_id: str = ""
    user_id: str = ""
    name: str = ""
    email: str = ""
    phone: str = ""
    message: str = ""
    enquirer_type: str = ""  # buyer, tenant, broker
    preferred_contact_time: str = ""
    created_at: float = 0.0
    is_read: bool = False

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


# ── Rent Agreement / Legal ─────────────────────────────────────────────────

@dataclass
class RentAgreement:
    """Rental/lease agreement with Indian e-stamping support."""
    agreement_id: str = ""
    property_id: str = ""
    landlord_id: str = ""
    tenant_id: str = ""
    rent_amount: Decimal = Decimal("0")
    security_deposit: Decimal = Decimal("0")
    lease_start: str = ""  # ISO date
    lease_end: str = ""  # ISO date
    notice_period_days: int = 30
    lock_in_period_months: int = 6
    rent_escalation_pct: float = 0.0  # annual increase %
    escalation_frequency_months: int = 12
    payment_day: int = 5  # day of month
    late_fee: Decimal = Decimal("0")
    maintenance_included: bool = True
    utility_bills_included: bool = False

    # Legal
    status: AgreementStatus = AgreementStatus.DRAFT
    e_stamp_paper_number: str = ""
    e_stamp_date: str = ""
    e_sign_status: str = ""  # pending, completed, failed
    aadhaar_sign_landlord: bool = False
    aadhaar_sign_tenant: bool = False
    document_url: str = ""  # URL to signed PDF
    created_at: float = 0.0
    signed_at: float = 0.0

    # Clauses
    special_clauses: list[str] = field(default_factory=list)
    utility_bills: str = "tenant"  # landlord, tenant, shared

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["status"] = self.status.value
        d["rent_amount"] = float(self.rent_amount)
        d["security_deposit"] = float(self.security_deposit)
        d["late_fee"] = float(self.late_fee)
        return d


# ── Virtual Tour ────────────────────────────────────────────────────────────

@dataclass
class virtual_tour:
    """3D virtual tour / walkthrough metadata."""
    tour_url: str = ""
    provider: str = ""  # matterport, cloudpano, kuula, custom
    thumbnail_url: str = ""
    is_360: bool = True
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


# ── Utility ─────────────────────────────────────────────────────────────────

def generate_property_id() -> str:
    """Generate a unique property ID (e.g., RE-20260726-XXXX)."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    import uuid
    suffix = uuid.uuid4().hex[:6].upper()
    return f"RE-{ts}-{suffix}"
