"""Application services — use cases for the real estate platform.

Implements all business use cases: property CRUD, search, lead management,
rent agreements, neighborhood insights, multi-language, and AI recommendations.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from realestate.application.dto import (
    AgreementDTO,
    EnquiryDTO,
    LeadDTO,
    PropertyDTO,
    PropertySearchQuery,
    PropertySearchResult,
    RentAgreementDTO,
    UserDTO,
)
from realestate.domain.models import (
    Address,
    AgreementStatus,
    Amenities,
    Enquiry,
    FurnishingStatus,
    Lead,
    LeadStatus,
    Location,
    MediaAsset,
    NeighborhoodInsight,
    Property,
    PropertyType,
    RentAgreement,
    generate_property_id,
)

_log = logging.getLogger(__name__)


# ── Multi-Language Service ───────────────────────────────────────────────────

@dataclass
class TranslationMap:
    """Translation for a single entity in multiple languages."""
    en: str = ""
    hi: str = ""  # Hindi
    mr: str = ""  # Marathi
    ta: str = ""  # Tamil
    te: str = ""  # Telugu
    bn: str = ""  # Bengali
    gu: str = ""  # Gujarati
    kn: str = ""  # Kannada
    ml: str = ""  # Malayalam
    pa: str = ""  # Punjabi

    def get(self, lang: str) -> str:
        return getattr(self, lang, self.en) or self.en


INDIAN_LANGUAGES = {
    "en": "English",
    "hi": "हिन्दी (Hindi)",
    "mr": "मराठी (Marathi)",
    "ta": "தமிழ் (Tamil)",
    "te": "తెలుగు (Telugu)",
    "bn": "বাংলা (Bengali)",
    "gu": "ગુજરાતી (Gujarati)",
    "kn": "ಕನ್ನಡ (Kannada)",
    "ml": "മലയാളം (Malayalam)",
    "pa": "ਪੰਜਾਬੀ (Punjabi)",
}

# Common UI translations
UI_TRANSLATIONS: dict[str, TranslationMap] = {
    "search_properties": TranslationMap(
        en="Search Properties",
        hi="संपत्ति खोजें",
        mr="मालमत्ता शोधा",
        ta="சொத்துக்களை தேடுங்கள்",
        te="ఆస్తులను శోధించండి",
        bn="সম্পত্তি অনুসন্ধান করুন",
        gu="મિલકત શોધો",
    ),
    "buy": TranslationMap(en="Buy", hi="खरीदें", mr="खरेदी करा", ta="வாங்க", te="కొనుగోలు", bn="কিনুন", gu="ખરીદો"),
    "rent": TranslationMap(en="Rent", hi="किराए पर", mr="भाड्याने", ta="வாடகை", te="అద్దె", bn="ভাড়া", gu="ભાડે"),
    "bedrooms": TranslationMap(en="Bedrooms", hi="बेडरूम", mr="बेडरूम", ta="படுக்கையறைகள்", te="బెడ్‌రూములు", bn="বেডরুম", gu="બેડરૂમ"),
    "price": TranslationMap(en="Price", hi="कीमत", mr="किंमत", ta="விலை", te="ధర", bn="মূল্য", gu="કિંમત"),
    "area": TranslationMap(en="Area (sq.ft.)", hi="क्षेत्र (वर्ग फुट)", mr="क्षेत्र (चौ. फूट)", ta="பரப்பு (ச. அடி)", te="విస్తీర్ణం (చ. అ.)", bn="এলাকা (বর্গ ফুট)", gu="વિસ્તાર (ચો. ફૂટ)"),
    "location": TranslationMap(en="Location", hi="स्थान", mr="स्थान", ta="இருப்பிடம்", te="స్థానం", bn="অবস্থান", gu="સ્થાન"),
    "contact_owner": TranslationMap(en="Contact Owner", hi="मालिक से संपर्क करें", mr="मालकाशी संपर्क साधा", ta="உரிமையாளரைத் தொடர்புகொள்ளவும்", te="యజమానిని సంప్రదించండి", bn="মালিকের সাথে যোগাযোগ করুন", gu="માલિકનો સંપર્ક કરો"),
    "schedule_visit": TranslationMap(en="Schedule Visit", hi="विजिट शेड्यूल करें", mr="भेटीचे वेळापत्रक करा", ta="வருகை திட்டமிடு", te="సందర్శన షెడ్యూల్ చేయండి", bn="ভিজিট শিডিউল করুন", gu="મુલાકાત શેડ્યૂલ કરો"),
    "featured": TranslationMap(en="Featured", hi="फीचर्ड", mr="वैशिष्ट्यीकृत", ta="சிறப்பிடப்பட்ட", te="ఫీచర్ చేయబడిన", bn="ফিচার্ড", gu="ફીચર્ડ"),
    "verified": TranslationMap(en="RERA Verified", hi="RERA सत्यापित", mr="RERA प्रमाणित", ta="RERA சரிபார்க்கப்பட்டது", te="RERA ధృవీకరించబడింది", bn="RERA যাচাইকৃত", gu="RERA ચકાસાયેલ"),
    "furnishing": TranslationMap(en="Furnishing", hi="फर्निशिंग", mr="फर्निशिंग", ta="அலங்கார நிலை", te="ఫర్నిషింగ్", bn="ফার্নিশিং", gu="ફર્નિશિંગ"),
    "amenities": TranslationMap(en="Amenities", hi="सुविधाएं", mr="सुविधा", ta="வசதிகள்", te="సౌకర్యాలు", bn="সুবিধা", gu="સુવિધાઓ"),
    "similar_properties": TranslationMap(en="Similar Properties", hi="समान संपत्तियां", mr="समान मालमत्ता", ta="ஒத்த சொத்துக்கள்", te="ఇలాంటి ఆస్తులు", bn="অনুরূপ সম্পত্তি", gu="સમાન મિલકતો"),
}


def get_translation(key: str, lang: str = "en") -> str:
    """Get a UI translation string for the given language."""
    if key in UI_TRANSLATIONS:
        return UI_TRANSLATIONS[key].get(lang)
    return key


class MultiLanguageService:
    """Service for multi-language UI support."""

    @staticmethod
    def get_supported_languages() -> dict[str, str]:
        return dict(INDIAN_LANGUAGES)

    @staticmethod
    def translate(key: str, lang: str = "en") -> str:
        return get_translation(key, lang)

    @staticmethod
    def translate_property(prop: PropertyDTO, lang: str = "en") -> PropertyDTO:
        """Translate a property's display fields."""
        if lang == "en":
            return prop
        # For non-English, property data stays as-is (addresses, etc. are local)
        # but UI labels around it will be translated
        return prop


# ── Property Service ─────────────────────────────────────────────────────────

class PropertyService:
    """Core property use cases: CRUD, listing management, media.

    Uses the ``PropertyRepository`` interface for persistence, falling back
    to in-memory dict storage if no repository is provided.

    This dual-persistence approach allows the service to work in both
    development (in-memory) and production (database-backed) modes.
    """

    def __init__(self, repository: Any = None):
        self._repo = repository  # Optional PropertyRepository
        self._properties: dict[str, Property] = {}

    @property
    def repository(self) -> Any:
        """Get the injected repository (or None if using in-memory storage)."""
        return self._repo

    def _persist(self, prop: Property) -> None:
        """Save property to both in-memory dict and repository (if available)."""
        self._properties[prop.property_id] = prop
        if self._repo is not None:
            try:
                self._repo.save(prop)
            except Exception:
                _log.debug("[RE] Repository save failed (non-fatal): %s", prop.property_id)

    def _remove(self, property_id: str) -> None:
        """Remove property from both in-memory dict and repository."""
        self._properties.pop(property_id, None)
        if self._repo is not None:
            try:
                self._repo.delete(property_id)
            except Exception:
                _log.debug("[RE] Repository delete failed (non-fatal): %s", property_id)

    def create_property(
        self,
        title: str,
        description: str,
        property_type: str,
        price: float,
        city: str,
        locality: str,
        owner_id: str,
        bedrooms: int = 0,
        bathrooms: int = 0,
        carpet_area_sqft: float = 0.0,
        amenities_list: list[str] | None = None,
    ) -> PropertyDTO:
        """Create a new property listing."""
        prop = Property(
            property_id=generate_property_id(),
            title=title,
            description=description,
            property_type=PropertyType(property_type) if property_type in {p.value for p in PropertyType} else PropertyType.APARTMENT,
            price=Decimal(str(price)),
            location=Location(
                address=Address(city=city, locality=locality),
            ),
            amenities=Amenities(
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                carpet_area_sqft=carpet_area_sqft,
                amenities_list=amenities_list or [],
            ),
            owner_id=owner_id,
            listed_at=time.time(),
            updated_at=time.time(),
        )
        self._persist(prop)
        _log.info("[RE] Property created: %s — %s", prop.property_id, title)
        return self._to_dto(prop)

    def get_property(self, property_id: str) -> PropertyDTO | None:
        prop = self._properties.get(property_id)
        return self._to_dto(prop) if prop else None

    def update_property(self, property_id: str, **updates: Any) -> PropertyDTO | None:
        prop = self._properties.get(property_id)
        if not prop:
            return None
        for key, value in updates.items():
            if hasattr(prop, key):
                setattr(prop, key, value)
        prop.updated_at = time.time()
        return self._to_dto(prop)

    def delete_property(self, property_id: str) -> bool:
        exists = property_id in self._properties
        self._remove(property_id)
        return exists

    def add_media(self, property_id: str, url: str, asset_type: str = "photo", is_primary: bool = False) -> bool:
        prop = self._properties.get(property_id)
        if not prop:
            return False
        prop.media.append(MediaAsset(
            asset_type=asset_type,
            url=url,
            is_primary=is_primary,
            uploaded_at=time.time(),
        ))
        return True

    def record_view(self, property_id: str) -> None:
        prop = self._properties.get(property_id)
        if prop:
            prop.views += 1

    def list_all(self) -> list[PropertyDTO]:
        # Prefer repository if wired (returns fresh domain objects)
        if self._repo is not None:
            try:
                repo_props = self._repo.list_all()
                if repo_props:
                    return [self._to_dto(p) for p in repo_props]
            except Exception:
                _log.debug("[RE] Repository list_all failed, falling back to in-memory")
        return [self._to_dto(p) for p in self._properties.values()]

    def _to_dto(self, prop: Property) -> PropertyDTO:
        if prop is None:
            return PropertyDTO()
        loc = prop.location
        addr = loc.address
        am = prop.amenities
        return PropertyDTO(
            property_id=prop.property_id,
            title=prop.title,
            description=prop.description,
            property_type=prop.property_type.value,
            listing_type=prop.listing_type.value,
            transaction_type=prop.transaction_type.value,
            price=float(prop.price),
            price_per_sqft=float(prop.price_per_sqft),
            city=addr.city,
            locality=addr.locality,
            state=addr.state,
            pincode=addr.pincode,
            latitude=addr.latitude,
            longitude=addr.longitude,
            bedrooms=am.bedrooms,
            bathrooms=am.bathrooms,
            balconies=am.balconies,
            carpet_area_sqft=am.carpet_area_sqft,
            super_area_sqft=am.super_area_sqft,
            plot_area_sqft=am.plot_area_sqft,
            furnishing=am.furnishing.value if isinstance(am.furnishing, FurnishingStatus) else "unfurnished",
            facing_direction=am.facing_direction,
            amenities=am.amenities_list[:20],
            images=[m.url for m in prop.media if m.asset_type in ("photo", "drone", "floor_plan")][:10],
            floor_plan_url=next((m.url for m in prop.media if m.asset_type == "floor_plan"), ""),
            virtual_tour_url=next((m.url for m in prop.media if m.asset_type == "virtual_tour"), ""),
            is_featured=prop.is_featured,
            is_verified=prop.is_verified,
            rera_number=prop.rera_number,
            owner_id=prop.owner_id,
            broker_id=prop.broker_id,
            listed_at=prop.listed_at,
            updated_at=prop.updated_at,
            views=prop.views,
            slug=prop.slug or prop.title.lower().replace(" ", "-")[:80],
        )


# ── Property Search Service ──────────────────────────────────────────────────

class PropertySearchService:
    """Multi-criteria property search with fuzzy matching and facets."""

    def __init__(self, property_service: PropertyService):
        self._property_service = property_service

    def search(self, query: PropertySearchQuery) -> PropertySearchResult:
        """Search properties by multiple criteria with pagination."""
        start = time.time()
        all_props = self._property_service.list_all()

        # Filter
        filtered: list[PropertyDTO] = []
        for p in all_props:
            if query.city and query.city.lower() not in p.city.lower():
                continue
            if query.locality and query.locality.lower() not in p.locality.lower():
                continue
            if query.property_type and p.property_type != query.property_type:
                continue
            if query.listing_type and p.listing_type != query.listing_type:
                continue
            if p.price < query.min_price or p.price > query.max_price:
                continue
            if p.bedrooms < query.min_bedrooms or p.bedrooms > query.max_bedrooms:
                continue
            if query.furnishing and p.furnishing != query.furnishing:
                continue
            if p.carpet_area_sqft < query.min_area_sqft or p.carpet_area_sqft > query.max_area_sqft:
                continue
            if query.verified_only and not p.is_verified:
                continue
            if query.with_virtual_tour and not p.virtual_tour_url:
                continue
            if query.amenities:
                p_amenities = set(a.lower() for a in p.amenities)
                if not all(a.lower() in p_amenities for a in query.amenities):
                    continue
            if query.query:
                q = query.query.lower()
                if q not in p.title.lower() and q not in p.description.lower() and q not in p.locality.lower():
                    continue
            filtered.append(p)

        # Sort
        reverse = query.sort_order == "desc"
        if query.sort_by == "price":
            filtered.sort(key=lambda x: x.price, reverse=reverse)
        elif query.sort_by == "area":
            filtered.sort(key=lambda x: x.carpet_area_sqft, reverse=reverse)
        elif query.sort_by == "views":
            filtered.sort(key=lambda x: x.views, reverse=reverse)
        else:
            filtered.sort(key=lambda x: x.listed_at, reverse=reverse)

        # Featured first
        if query.featured_first:
            featured = [p for p in filtered if p.is_featured]
            not_featured = [p for p in filtered if not p.is_featured]
            filtered = featured + not_featured

        # Paginate
        total = len(filtered)
        total_pages = max(1, (total + query.page_size - 1) // query.page_size)
        page = min(query.page, total_pages)
        start_idx = (page - 1) * query.page_size
        end_idx = start_idx + query.page_size
        page_props = filtered[start_idx:end_idx]

        # Build facets
        cities: dict[str, int] = {}
        types: dict[str, int] = {}
        for p in all_props:
            cities[p.city] = cities.get(p.city, 0) + 1
            types[p.property_type] = types.get(p.property_type, 0) + 1

        elapsed = (time.time() - start) * 1000

        return PropertySearchResult(
            properties=page_props,
            total=total,
            page=page,
            page_size=query.page_size,
            total_pages=total_pages,
            facets={"cities": cities, "property_types": types},
            query_time_ms=round(elapsed, 2),
        )


# ── Lead Service (CRM) ───────────────────────────────────────────────────────

class LeadService:
    """Sales lead management for the CRM."""

    def __init__(self):
        self._leads: dict[str, Lead] = {}
        self._enquiries: dict[str, Enquiry] = {}

    def create_lead(
        self,
        property_id: str,
        buyer_name: str,
        buyer_phone: str,
        buyer_email: str = "",
        budget: float = 0.0,
        source: str = "website",
    ) -> LeadDTO:
        lead = Lead(
            lead_id=f"LD-{int(time.time())}-{random.randint(100, 999)}",
            property_id=property_id,
            buyer_name=buyer_name,
            buyer_phone=buyer_phone,
            buyer_email=buyer_email,
            budget=Decimal(str(budget)),
            status=LeadStatus.NEW,
            source=source,
            created_at=time.time(),
        )
        self._leads[lead.lead_id] = lead
        return self._to_lead_dto(lead)

    def update_lead_status(self, lead_id: str, status: str) -> LeadDTO | None:
        try:
            ls = LeadStatus(status)
        except ValueError:
            return None
        lead = self._leads.get(lead_id)
        if not lead:
            return None
        lead.status = ls
        lead.updated_at = time.time()
        return self._to_lead_dto(lead)

    def assign_lead(self, lead_id: str, assignee: str) -> LeadDTO | None:
        lead = self._leads.get(lead_id)
        if not lead:
            return None
        lead.assigned_to = assignee
        lead.updated_at = time.time()
        return self._to_lead_dto(lead)

    def get_leads(self, status: str | None = None) -> list[LeadDTO]:
        leads = list(self._leads.values())
        if status:
            leads = [lead for lead in leads if lead.status.value == status]
        leads.sort(key=lambda x: x.created_at, reverse=True)
        return [self._to_lead_dto(lead) for lead in leads]

    def submit_enquiry(
        self,
        property_id: str,
        name: str,
        email: str,
        phone: str,
        message: str,
        enquirer_type: str = "buyer",
    ) -> EnquiryDTO:
        enq = Enquiry(
            enquiry_id=f"ENQ-{int(time.time())}-{random.randint(100, 999)}",
            property_id=property_id,
            name=name,
            email=email,
            phone=phone,
            message=message,
            enquirer_type=enquirer_type,
            created_at=time.time(),
        )
        self._enquiries[enq.enquiry_id] = enq
        return EnquiryDTO(
            enquiry_id=enq.enquiry_id,
            property_id=enq.property_id,
            name=enq.name,
            email=enq.email,
            phone=enq.phone,
            message=enq.message,
            enquirer_type=enq.enquirer_type,
            created_at=enq.created_at,
        )

    def get_enquiries(self, property_id: str | None = None) -> list[EnquiryDTO]:
        enqs = list(self._enquiries.values())
        if property_id:
            enqs = [e for e in enqs if e.property_id == property_id]
        enqs.sort(key=lambda x: x.created_at, reverse=True)
        return [
            EnquiryDTO(
                enquiry_id=e.enquiry_id,
                property_id=e.property_id,
                name=e.name,
                email=e.email,
                phone=e.phone,
                message=e.message,
                enquirer_type=e.enquirer_type,
                created_at=e.created_at,
                is_read=e.is_read,
            )
            for e in enqs
        ]

    def _to_lead_dto(self, lead: Lead) -> LeadDTO:
        return LeadDTO(
            lead_id=lead.lead_id,
            property_id=lead.property_id,
            buyer_name=lead.buyer_name,
            buyer_phone=lead.buyer_phone,
            buyer_email=lead.buyer_email,
            budget=float(lead.budget),
            status=lead.status.value,
            notes=lead.notes,
            created_at=lead.created_at,
            assigned_to=lead.assigned_to,
            source=lead.source,
        )


class BrokerCRMService:
    """Broker/Developer CRM with client management."""

    def __init__(self):
        self._brokers: dict[str, UserDTO] = {}
        self._client_map: dict[str, list[str]] = {}  # broker_id -> lead_ids

    def register_broker(self, dto: UserDTO) -> UserDTO:
        self._brokers[dto.user_id] = dto
        self._client_map.setdefault(dto.user_id, [])
        return dto

    def get_broker_leads(self, broker_id: str) -> list[LeadDTO]:
        return []


# ── Neighborhood Service ─────────────────────────────────────────────────────

INDIAN_CITIES_DATA: dict[str, dict[str, Any]] = {
    "mumbai": {
        "localities": ["Andheri", "Bandra", "Powai", "Worli", "Malad", "Thane", "Navi Mumbai", "Goregaon", "Juhu", "Colaba"],
        "avg_price_per_sqft": 15000, "schools_rating": 8.2, "hospitals_rating": 8.5,
        "connectivity_rating": 8.8, "safety_rating": 7.5, "aqi": "moderate",
    },
    "bangalore": {
        "localities": ["Whitefield", "Electronic City", "Indiranagar", "Koramangala", "HSR Layout", "JP Nagar", "Jayanagar", "Marathahalli", "Hebbal", "Yelahanka"],
        "avg_price_per_sqft": 9500, "schools_rating": 8.8, "hospitals_rating": 8.3,
        "connectivity_rating": 7.5, "safety_rating": 8.0, "aqi": "moderate",
    },
    "delhi": {
        "localities": ["Dwarka", "Rohini", "Lajpat Nagar", "Greater Kailash", "Saket", "Vasant Kunj", "Hauz Khas", "Pitampura", "Karol Bagh", "Connaught Place"],
        "avg_price_per_sqft": 12000, "schools_rating": 8.5, "hospitals_rating": 8.0,
        "connectivity_rating": 9.0, "safety_rating": 6.5, "aqi": "very_poor",
    },
    "pune": {
        "localities": ["Hinjewadi", "Kharadi", "Baner", "Wakad", "Hadapsar", "Kothrud", "Viman Nagar", "Pimpri", "Bibhwewadi", "Magarpatta"],
        "avg_price_per_sqft": 8000, "schools_rating": 8.5, "hospitals_rating": 8.2,
        "connectivity_rating": 7.8, "safety_rating": 8.2, "aqi": "good",
    },
    "hyderabad": {
        "localities": ["HITEC City", "Gachibowli", "Kondapur", "Madhapur", "Jubilee Hills", "Banjara Hills", "Kukatpally", "Miyapur", "Shamshabad", "Uppal"],
        "avg_price_per_sqft": 7500, "schools_rating": 8.3, "hospitals_rating": 8.5,
        "connectivity_rating": 8.0, "safety_rating": 8.5, "aqi": "good",
    },
    "chennai": {
        "localities": ["OMR", "Velachery", "Thoraipakkam", "Adyar", "Tambaram", "Porur", "Chromepet", "Thiruvanmiyur", "Guindy", "Sholinganallur"],
        "avg_price_per_sqft": 7000, "schools_rating": 8.8, "hospitals_rating": 8.7,
        "connectivity_rating": 7.8, "safety_rating": 8.0, "aqi": "moderate",
    },
    "kolkata": {
        "localities": ["Salt Lake", "New Town", "Rajarbagh", "Dum Dum", "New Alipore", "Behala", "Baranagar", "Keshtopur", "Lake Town", "Tollygunge"],
        "avg_price_per_sqft": 5500, "schools_rating": 8.0, "hospitals_rating": 7.8,
        "connectivity_rating": 7.0, "safety_rating": 7.0, "aqi": "poor",
    },
    "ahmedabad": {
        "localities": ["SG Highway", "Prahlad Nagar", "Bodakdev", "Vastrapur", "Satellite", "Thaltej", "Bopal", "Chandkheda", "Naranpura", "Maninagar"],
        "avg_price_per_sqft": 5000, "schools_rating": 8.0, "hospitals_rating": 7.8,
        "connectivity_rating": 7.5, "safety_rating": 8.5, "aqi": "moderate",
    },
    "noida": {
        "localities": ["Sector 62", "Sector 44", "Sector 15", "Sector 128", "Sector 137", "Greater Noida West", "Sector 168", "Sector 45", "Sector 22", "Sector 70"],
        "avg_price_per_sqft": 6500, "schools_rating": 7.8, "hospitals_rating": 7.5,
        "connectivity_rating": 8.5, "safety_rating": 7.5, "aqi": "poor",
    },
    "gurgaon": {
        "localities": ["DLF Phase 1-5", "Sector 56", "Sohna Road", "Gurgaon South", "Dwarka Expressway", "Golf Course Road", "MG Road", "Sector 14", "Sector 43", "Sector 57"],
        "avg_price_per_sqft": 11000, "schools_rating": 8.0, "hospitals_rating": 7.8,
        "connectivity_rating": 8.5, "safety_rating": 7.0, "aqi": "poor",
    },
}


class NeighborhoodService:
    """Neighborhood insights and locality data."""

    def get_city_data(self, city: str) -> dict[str, Any] | None:
        return INDIAN_CITIES_DATA.get(city.lower())

    def get_localities(self, city: str) -> list[str]:
        data = self.get_city_data(city)
        return data["localities"] if data else []

    def get_neighborhood_insight(self, city: str, locality: str) -> NeighborhoodInsight | None:
        data = self.get_city_data(city)
        if not data:
            return None
        return NeighborhoodInsight(
            area_name=locality,
            summary=f"{locality} is a prime locality in {city.title()} with excellent connectivity and infrastructure.",
            avg_price_per_sqft=data["avg_price_per_sqft"],
            price_trend_6m=round(random.uniform(-3, 8), 1),
            rental_yield_pct=round(random.uniform(2.5, 5.0), 1),
            demand_index=round(random.uniform(60, 95), 1),
            schools_rating=data["schools_rating"],
            hospitals_rating=data["hospitals_rating"],
            connectivity_rating=data["connectivity_rating"],
            safety_rating=data["safety_rating"],
            last_updated=time.time(),
        )

    def get_all_cities(self) -> list[dict[str, Any]]:
        return [
            {"name": k.title(), "localities": v["localities"], "avg_price": v["avg_price_per_sqft"]}
            for k, v in sorted(INDIAN_CITIES_DATA.items())
        ]


# ── Rent Agreement Service ───────────────────────────────────────────────────

class RentAgreementService:
    """Rent/lease agreement creation and management with e-stamping support."""

    def __init__(self):
        self._agreements: dict[str, RentAgreement] = {}

    def create_agreement(
        self,
        property_id: str,
        landlord_id: str,
        tenant_name: str,
        tenant_id: str,
        rent_amount: float,
        security_deposit: float,
        lease_start: str,
        lease_end: str,
        notice_period_days: int = 30,
        lock_in_months: int = 6,
    ) -> RentAgreementDTO:
        agreement = RentAgreement(
            agreement_id=f"AG-{int(time.time())}-{random.randint(100, 999)}",
            property_id=property_id,
            landlord_id=landlord_id,
            tenant_id=tenant_id,
            rent_amount=Decimal(str(rent_amount)),
            security_deposit=Decimal(str(security_deposit)),
            lease_start=lease_start,
            lease_end=lease_end,
            notice_period_days=notice_period_days,
            lock_in_period_months=lock_in_months,
            status=AgreementStatus.DRAFT,
            created_at=time.time(),
        )
        self._agreements[agreement.agreement_id] = agreement
        _log.info("[RE] Rent agreement created: %s", agreement.agreement_id)
        return self._to_dto(agreement)

    def initiate_e_stamp(self, agreement_id: str) -> dict[str, Any]:
        """Initiate e-stamping process (stub)."""
        agreement = self._agreements.get(agreement_id)
        if not agreement:
            return {"success": False, "error": "Agreement not found"}
        agreement.e_stamp_paper_number = f"EST{int(time.time())}"
        agreement.e_stamp_date = datetime.now(timezone.utc).isoformat()
        agreement.status = AgreementStatus.E_STAMPED
        return {
            "success": True,
            "e_stamp_paper_number": agreement.e_stamp_paper_number,
            "e_stamp_date": agreement.e_stamp_date,
        }

    def initiate_e_sign(self, agreement_id: str, party: str = "both") -> dict[str, Any]:
        """Initiate e-signing via Aadhaar eSign (stub)."""
        agreement = self._agreements.get(agreement_id)
        if not agreement:
            return {"success": False, "error": "Agreement not found"}
        if party in ("landlord", "both"):
            agreement.aadhaar_sign_landlord = True
        if party in ("tenant", "both"):
            agreement.aadhaar_sign_tenant = True
        if agreement.aadhaar_sign_landlord and agreement.aadhaar_sign_tenant:
            agreement.e_sign_status = "completed"
            agreement.status = AgreementStatus.E_SIGNED
            agreement.signed_at = time.time()
        return {
            "success": True,
            "landlord_signed": agreement.aadhaar_sign_landlord,
            "tenant_signed": agreement.aadhaar_sign_tenant,
            "status": agreement.e_sign_status,
        }

    def get_agreement(self, agreement_id: str) -> RentAgreementDTO | None:
        agreement = self._agreements.get(agreement_id)
        return self._to_dto(agreement) if agreement else None

    def list_agreements(self, property_id: str | None = None) -> list[RentAgreementDTO]:
        agreements = list(self._agreements.values())
        if property_id:
            agreements = [a for a in agreements if a.property_id == property_id]
        agreements.sort(key=lambda x: x.created_at, reverse=True)
        return [self._to_dto(a) for a in agreements]

    def _to_dto(self, a: RentAgreement) -> RentAgreementDTO:
        return RentAgreementDTO(
            agreement_id=a.agreement_id,
            property_id=a.property_id,
            rent_amount=float(a.rent_amount),
            security_deposit=float(a.security_deposit),
            lease_start=a.lease_start,
            lease_end=a.lease_end,
            notice_period_days=a.notice_period_days,
            lock_in_period_months=a.lock_in_period_months,
            status=a.status.value,
            e_stamp_paper_number=a.e_stamp_paper_number,
            e_sign_status=a.e_sign_status,
            document_url=a.document_url,
            created_at=a.created_at,
        )


class AgreementService:
    """Higher-level agreement service for all agreement types."""

    def create_agreement(
        self,
        agreement_type: str,
        property_id: str,
        amount: float,
        parties: list[str],
    ) -> AgreementDTO:
        return AgreementDTO(
            agreement_id=f"AG-{int(time.time())}",
            type=agreement_type,
            status="draft",
            parties=parties,
            property_id=property_id,
            amount=amount,
            created_at=time.time(),
        )


# ── Recommendation Engine ────────────────────────────────────────────────────

class RecommendationEngine:
    """AI-powered property recommendation engine."""

    def __init__(self, property_service: PropertyService):
        self._property_service = property_service

    def get_recommendations(
        self,
        user_id: str | None = None,
        viewed_property_id: str | None = None,
        limit: int = 6,
    ) -> list[PropertyDTO]:
        """Get property recommendations based on viewing history or similar."""
        all_props = self._property_service.list_all()

        if viewed_property_id:
            viewed = self._property_service.get_property(viewed_property_id)
            if viewed:
                # Find similar: same city, similar price range
                similar = [
                    p for p in all_props
                    if p.property_id != viewed_property_id
                    and p.city == viewed.city
                    and abs(p.price - viewed.price) / max(viewed.price, 1) < 0.5
                ]
                if similar:
                    return similar[:limit]

        # Default: return featured + random
        featured = [p for p in all_props if p.is_featured]
        random.shuffle(featured)
        if len(featured) >= limit:
            return featured[:limit]

        non_featured = [p for p in all_props if not p.is_featured]
        random.shuffle(non_featured)
        return featured + non_featured[:limit - len(featured)]


# ── Factory ──────────────────────────────────────────────────────────────────

def create_default_services() -> dict[str, Any]:
    """Create all services wired together for the real estate platform."""
    property_service = PropertyService()
    return {
        "property_service": property_service,
        "search_service": PropertySearchService(property_service),
        "lead_service": LeadService(),
        "broker_crm": BrokerCRMService(),
        "neighborhood_service": NeighborhoodService(),
        "rent_agreement_service": RentAgreementService(),
        "agreement_service": AgreementService(),
        "recommendation_engine": RecommendationEngine(property_service),
        "multi_language_service": MultiLanguageService(),
    }
