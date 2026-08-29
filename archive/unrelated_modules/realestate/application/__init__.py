"""Application layer — use cases, DTOs, and service interfaces.

Follows CQRS pattern: commands (write) and queries (read) separated.
"""

from __future__ import annotations

from realestate.application.dto import (
    AgreementDTO,
    EnquiryDTO,
    LeadDTO,
    ListingDTO,
    PropertyDTO,
    PropertySearchQuery,
    PropertySearchResult,
    RentAgreementDTO,
    UserDTO,
)
from realestate.application.services import (
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

__all__ = [
    "AgreementDTO", "AgreementService", "BrokerCRMService",
    "EnquiryDTO", "LeadDTO", "LeadService", "ListingDTO",
    "MultiLanguageService", "NeighborhoodService",
    "PropertyDTO", "PropertySearchQuery", "PropertySearchResult",
    "PropertySearchService", "PropertyService",
    "RecommendationEngine", "RentAgreementDTO", "RentAgreementService",
    "UserDTO",
]
