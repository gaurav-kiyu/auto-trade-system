"""Indian Real Estate Platform — Scalable property marketplace.

Integrated into the existing enterprise system, reusing infrastructure
from the core platform (DI container, RBAC, event bus, notification service,
multi-tenancy, CQRS).

Architecture: Clean Architecture with 5 layers:
  - domain/       — Enterprise business models & rules
  - application/  — Use cases, DTOs, service interfaces
  - infrastructure/— Persistence, external API adapters
  - api/          — FastAPI routes and middleware
  - ui/           — HTML templates and static assets

Market scope: India (NCR, Mumbai, Bangalore, Hyderabad, Chennai, Pune, Kolkata)
"""

from __future__ import annotations

__version__ = "1.0.0"

from realestate.application import (
    AgreementService,
    BrokerCRMService,
    LeadService,
    MultiLanguageService,
    NeighborhoodService,
    PropertySearchService,
    PropertyService,
    RecommendationEngine,
    RentAgreementService,
)
from realestate.domain import (
    Address,
    Amenities,
    BrokerProfile,
    BuilderProject,
    DeveloperProfile,
    Enquiry,
    Lead,
    Listing,
    Location,
    MediaAsset,
    NeighborhoodInsight,
    PriceHistory,
    Property,
    PropertyType,
    RentAgreement,
    SellerProfile,
    TenantProfile,
    UserProfile,
    UserRole,
)
from realestate.infrastructure import (
    InMemoryPropertyRepository,
    PropertyRepository,
    SearchEngine,
)

__all__ = [
    # Domain
    "Address", "Amenities", "BrokerProfile", "BuilderProject",
    "DeveloperProfile", "Enquiry", "Lead", "Listing",
    "Location", "MediaAsset", "NeighborhoodInsight", "PriceHistory",
    "Property", "PropertyType", "RentAgreement", "SellerProfile",
    "TenantProfile", "UserProfile", "UserRole",
    # Application
    "AgreementService", "BrokerCRMService", "LeadService",
    "MultiLanguageService", "NeighborhoodService",
    "PropertySearchService", "PropertyService",
    "RecommendationEngine", "RentAgreementService",
    # Infrastructure
    "InMemoryPropertyRepository", "PropertyRepository", "SearchEngine",
]
