"""Tests for the Indian Real Estate Platform — domain, services, API, chatbot."""

from __future__ import annotations

from decimal import Decimal

import pytest
from realestate.ai_chatbot import RealEstateChatbot
from realestate.application.dto import PropertySearchQuery
from realestate.application.services import (
    BrokerCRMService,
    LeadService,
    MultiLanguageService,
    NeighborhoodService,
    PropertySearchService,
    PropertyService,
    RecommendationEngine,
    RentAgreementService,
    create_default_services,
)
from realestate.domain.models import (
    Address,
    Amenities,
    FurnishingStatus,
    Lead,
    LeadStatus,
    Location,
    Property,
    PropertyType,
    RentAgreement,
    UserProfile,
    UserRole,
    generate_property_id,
)
from realestate.infrastructure.repository import (
    InMemoryPropertyRepository,
    SearchEngine,
)

# ── Domain Model Tests ──────────────────────────────────────────────────────

class TestDomainModels:
    def test_generate_property_id(self):
        pid = generate_property_id()
        assert pid.startswith("RE-")
        assert len(pid) > 10

    def test_address_to_dict(self):
        addr = Address(city="Mumbai", locality="Andheri", pincode="400093")
        d = addr.to_dict()
        assert d["city"] == "Mumbai"
        assert d["locality"] == "Andheri"

    def test_amenities_defaults(self):
        am = Amenities()
        assert am.bedrooms == 0
        assert am.furnishing == FurnishingStatus.UNFURNISHED
        assert not am.gated_community

    def test_amenities_to_dict_enum_serialization(self):
        am = Amenities(bedrooms=3, bathrooms=2, furnishing=FurnishingStatus.FURNISHED)
        d = am.to_dict()
        assert d["furnishing"] == "furnished"

    def test_property_defaults(self):
        p = Property()
        assert p.property_type == PropertyType.APARTMENT
        assert p.price == Decimal("0")
        assert p.is_active

    def test_property_with_values(self):
        p = Property(
            property_id=generate_property_id(),
            title="Luxury 3BHK in Bandra",
            price=Decimal("25000000"),
            amenities=Amenities(bedrooms=3, bathrooms=3, carpet_area_sqft=1200),
            location=Location(address=Address(city="Mumbai", locality="Bandra")),
        )
        assert p.price == Decimal("25000000")
        assert p.amenities.bedrooms == 3

    def test_property_to_dict(self):
        p = Property(
            property_id="RE-001",
            title="Test Property",
            price=Decimal("10000000"),
            amenities=Amenities(bedrooms=2, bathrooms=2, carpet_area_sqft=800),
        )
        d = p.to_dict()
        assert d["property_id"] == "RE-001"
        assert d["price"] == 10000000.0
        assert d["amenities"]["bedrooms"] == 2

    def test_location_to_dict(self):
        loc = Location(
            address=Address(city="Pune"),
            walk_score=85,
            transit_score=70,
            aqi_rating="good",
        )
        d = loc.to_dict()
        assert d["walk_score"] == 85
        assert d["address"]["city"] == "Pune"

    def test_user_profile_defaults(self):
        u = UserProfile()
        assert u.role == UserRole.BUYER
        assert u.language == "en"

    def test_user_profile_to_dict(self):
        u = UserProfile(user_id="U001", role=UserRole.BROKER, name="Raj")
        d = u.to_dict()
        assert d["role"] == "broker"
        assert d["name"] == "Raj"

    def test_lead_creation(self):
        lead = Lead(
            lead_id="LD-001",
            property_id="RE-001",
            buyer_name="Amit",
            buyer_phone="9876543210",
            status=LeadStatus.NEW,
        )
        assert lead.status == LeadStatus.NEW
        assert lead.buyer_name == "Amit"

    def test_rent_agreement_defaults(self):
        ra = RentAgreement()
        assert ra.notice_period_days == 30
        assert ra.lock_in_period_months == 6


# ── Property Service Tests ──────────────────────────────────────────────────

class TestPropertyService:
    def setup_method(self):
        self.svc = PropertyService()

    def test_create_property(self):
        p = self.svc.create_property(
            title="2BHK in Bangalore",
            description="Nice apartment",
            property_type="apartment",
            price=7500000,
            city="Bangalore",
            locality="Whitefield",
            owner_id="user1",
            bedrooms=2, bathrooms=2, carpet_area_sqft=900,
        )
        assert p.property_id is not None
        assert p.title == "2BHK in Bangalore"
        assert p.city == "Bangalore"
        assert p.price == 7500000.0
        assert p.bedrooms == 2

    def test_get_property(self):
        p = self.svc.create_property(title="Test", description="", property_type="apartment", price=5000000, city="Mumbai", locality="", owner_id="u1")
        found = self.svc.get_property(p.property_id)
        assert found is not None
        assert found.property_id == p.property_id

    def test_get_nonexistent_property(self):
        assert self.svc.get_property("nonexistent") is None

    def test_delete_property(self):
        p = self.svc.create_property(title="Delete me", description="", property_type="apartment", price=1000000, city="Delhi", locality="", owner_id="u1")
        assert self.svc.delete_property(p.property_id)
        assert self.svc.get_property(p.property_id) is None

    def test_add_media(self):
        p = self.svc.create_property(title="Media test", description="", property_type="apartment", price=3000000, city="Pune", locality="", owner_id="u1")
        assert self.svc.add_media(p.property_id, "https://example.com/photo.jpg", "photo")
        prop = self.svc.get_property(p.property_id)
        assert len(prop.images) == 1

    def test_record_view(self):
        p = self.svc.create_property(title="Views test", description="", property_type="apartment", price=2000000, city="Chennai", locality="", owner_id="u1")
        self.svc.record_view(p.property_id)
        prop = self.svc.get_property(p.property_id)
        assert prop.views == 1

    def test_update_property(self):
        p = self.svc.create_property(title="Update me", description="", property_type="apartment", price=4000000, city="Hyderabad", locality="", owner_id="u1")
        updated = self.svc.update_property(p.property_id, price=4500000.0)
        assert updated.price == 4500000.0


# ── Search Service Tests ────────────────────────────────────────────────────

class TestPropertySearchService:
    def setup_method(self):
        self.ps = PropertyService()
        self.ss = PropertySearchService(self.ps)

        # Seed data
        self.ps.create_property("2BHK in Andheri", "", "apartment", 8000000, "Mumbai", "Andheri", "u1", 2, 2, 800)
        self.ps.create_property("3BHK in Bandra", "", "apartment", 25000000, "Mumbai", "Bandra", "u1", 3, 3, 1500)
        self.ps.create_property("4BHK Villa in Whitefield", "", "villa", 15000000, "Bangalore", "Whitefield", "u1", 4, 4, 2500)
        self.ps.create_property("1BHK Studio in Hinjewadi", "", "studio", 3500000, "Pune", "Hinjewadi", "u1", 1, 1, 450)
        self.ps.create_property("Villa in Goa", "", "villa", 50000000, "Goa", "Panjim", "u1", 5, 5, 3500)

    def test_search_all(self):
        result = self.ss.search(PropertySearchQuery())
        assert result.total == 5

    def test_search_by_city(self):
        result = self.ss.search(PropertySearchQuery(city="Mumbai"))
        assert result.total == 2

    def test_search_by_property_type(self):
        result = self.ss.search(PropertySearchQuery(property_type="villa"))
        assert result.total == 2

    def test_search_by_bedrooms(self):
        result = self.ss.search(PropertySearchQuery(min_bedrooms=3))
        assert result.total == 3

    def test_search_by_price_range(self):
        result = self.ss.search(PropertySearchQuery(min_price=10000000, max_price=30000000))
        assert result.total >= 1

    def test_search_by_keyword(self):
        result = self.ss.search(PropertySearchQuery(query="Andheri"))
        assert result.total == 1

    def test_search_pagination(self):
        result = self.ss.search(PropertySearchQuery(page=1, page_size=2))
        assert len(result.properties) == 2
        assert result.total_pages == 3

    def test_search_facets(self):
        result = self.ss.search(PropertySearchQuery())
        assert "cities" in result.facets
        assert "Mumbai" in result.facets["cities"]

    def test_search_sort_by_price_asc(self):
        result = self.ss.search(PropertySearchQuery(sort_by="price", sort_order="asc"))
        prices = [p.price for p in result.properties]
        assert prices == sorted(prices)

    def test_search_no_match(self):
        result = self.ss.search(PropertySearchQuery(city="Unknown"))
        assert result.total == 0


# ── Lead Service Tests ──────────────────────────────────────────────────────

class TestLeadService:
    def setup_method(self):
        self.svc = LeadService()

    def test_create_lead(self):
        lead = self.svc.create_lead("RE-001", "Rahul", "9876543210", "rahul@email.com", 5000000)
        assert lead.lead_id is not None
        assert lead.buyer_name == "Rahul"
        assert lead.status == "new"

    def test_update_lead_status(self):
        lead = self.svc.create_lead("RE-002", "Priya", "9876543211")
        updated = self.svc.update_lead_status(lead.lead_id, "contacted")
        assert updated.status == "contacted"

    def test_get_leads(self):
        self.svc.create_lead("RE-001", "Amit", "9876543212")
        self.svc.create_lead("RE-002", "Sneha", "9876543213")
        leads = self.svc.get_leads()
        assert len(leads) >= 2

    def test_get_leads_by_status(self):
        lead = self.svc.create_lead("RE-003", "Test", "9876543214")
        self.svc.update_lead_status(lead.lead_id, "interested")
        leads = self.svc.get_leads("interested")
        assert len(leads) >= 1
        assert all(lead.status == "interested" for lead in leads)

    def test_submit_enquiry(self):
        enq = self.svc.submit_enquiry("RE-001", "Raj", "raj@email.com", "9876543215", "Interested!")
        assert enq.enquiry_id is not None
        assert enq.name == "Raj"

    def test_get_enquiries(self):
        self.svc.submit_enquiry("RE-001", "User1", "u1@e.com", "9999999999", "Hi")
        self.svc.submit_enquiry("RE-002", "User2", "u2@e.com", "8888888888", "Hello")
        enqs = self.svc.get_enquiries()
        assert len(enqs) >= 2

    def test_get_enquiries_by_property(self):
        self.svc.submit_enquiry("RE-001", "U1", "u1@e.com", "1111", "Hi")
        enqs = self.svc.get_enquiries(property_id="RE-001")
        assert len(enqs) >= 1


# ── Rent Agreement Service Tests ────────────────────────────────────────────

class TestRentAgreementService:
    def setup_method(self):
        self.svc = RentAgreementService()

    def test_create_agreement(self):
        a = self.svc.create_agreement(
            property_id="RE-001", landlord_id="L001",
            tenant_name="Ravi", tenant_id="T001",
            rent_amount=25000, security_deposit=75000,
            lease_start="2026-08-01", lease_end="2027-07-31",
        )
        assert a.agreement_id is not None
        assert a.rent_amount == 25000.0
        assert a.status == "draft"

    def test_initiate_e_stamp(self):
        a = self.svc.create_agreement("RE-001", "L001", "Test Tenant", "T001", 20000, 60000, "2026-08-01", "2027-07-31")
        result = self.svc.initiate_e_stamp(a.agreement_id)
        assert result["success"]
        assert result["e_stamp_paper_number"] is not None
        updated = self.svc.get_agreement(a.agreement_id)
        assert updated.status == "e_stamped"

    def test_initiate_e_sign(self):
        a = self.svc.create_agreement("RE-001", "L001", "Test Tenant", "T001", 20000, 60000, "2026-08-01", "2027-07-31")
        # Sign both
        result = self.svc.initiate_e_sign(a.agreement_id, "both")
        assert result["success"]
        assert result["status"] == "completed"
        updated = self.svc.get_agreement(a.agreement_id)
        assert updated.status == "e_signed"

    def test_get_nonexistent(self):
        assert self.svc.get_agreement("nonexistent") is None

    def test_list_agreements(self):
        self.svc.create_agreement("RE-001", "L001", "T1", "T001", 15000, 45000, "2026-08-01", "2027-07-31")
        self.svc.create_agreement("RE-001", "L001", "T2", "T002", 20000, 60000, "2026-09-01", "2027-08-31")
        agreements = self.svc.list_agreements(property_id="RE-001")
        assert len(agreements) >= 2


# ── Neighborhood Service Tests ──────────────────────────────────────────────

class TestNeighborhoodService:
    def setup_method(self):
        self.svc = NeighborhoodService()

    def test_get_city_data(self):
        data = self.svc.get_city_data("Mumbai")
        assert data is not None
        assert "Andheri" in data["localities"]
        assert data["avg_price_per_sqft"] == 15000

    def test_get_city_data_unknown(self):
        assert self.svc.get_city_data("UnknownCity") is None

    def test_get_localities(self):
        locs = self.svc.get_localities("Bangalore")
        assert "Whitefield" in locs
        assert "Indiranagar" in locs

    def test_get_localities_unknown(self):
        assert self.svc.get_localities("Unknown") == []

    def test_get_insight(self):
        insight = self.svc.get_neighborhood_insight("Pune", "Hinjewadi")
        assert insight is not None
        assert insight.area_name == "Hinjewadi"
        assert insight.schools_rating > 0
        assert insight.avg_price_per_sqft == 8000

    def test_get_all_cities(self):
        cities = self.svc.get_all_cities()
        assert len(cities) == 10
        assert any(c["name"] == "Mumbai" for c in cities)


# ── Multi-Language Service Tests ────────────────────────────────────────────

class TestMultiLanguageService:
    def test_get_languages(self):
        langs = MultiLanguageService.get_supported_languages()
        assert "en" in langs
        assert "hi" in langs
        assert "ta" in langs
        assert len(langs) == 10

    def test_translate_default(self):
        result = MultiLanguageService.translate("search_properties", "en")
        assert result == "Search Properties"

    def test_translate_hindi(self):
        result = MultiLanguageService.translate("search_properties", "hi")
        assert result == "संपत्ति खोजें"

    def test_translate_tamil(self):
        result = MultiLanguageService.translate("buy", "ta")
        assert result == "வாங்க"

    def test_translate_unknown_key(self):
        result = MultiLanguageService.translate("nonexistent_key", "en")
        assert result == "nonexistent_key"


# ── Recommendation Engine Tests ──────────────────────────────────────────────

class TestRecommendationEngine:
    def setup_method(self):
        self.ps = PropertyService()
        self.re = RecommendationEngine(self.ps)

        # Seed
        self.p1 = self.ps.create_property("Luxury in Bandra", "", "apartment", 25000000, "Mumbai", "Bandra", "u1")
        self.p2 = self.ps.create_property("Budget in Andheri", "", "apartment", 8000000, "Mumbai", "Andheri", "u1")
        self.p3 = self.ps.create_property("Villa in Goa", "", "villa", 50000000, "Goa", "Panjim", "u1")

    def test_recommendations_no_context(self):
        recs = self.re.get_recommendations()
        assert len(recs) <= 6

    def test_recommendations_similar(self):
        recs = self.re.get_recommendations(viewed_property_id=self.p1.property_id)
        assert len(recs) >= 1
        # Should recommend things in the same city (Mumbai)
        assert any(r.city == "Mumbai" for r in recs)


# ── Chatbot Tests ───────────────────────────────────────────────────────────

class TestChatbot:
    def setup_method(self):
        self.bot = RealEstateChatbot()

    def test_greeting(self):
        resp = self.bot.respond("Hi, how are you?")
        assert "Namaste" in resp.text or "Welcome" in resp.text

    def test_hello(self):
        resp = self.bot.respond("Hello")
        assert len(resp.suggestions) > 0

    def test_faq_documents(self):
        resp = self.bot.respond("What documents do I need to buy property in India?")
        # Check response contains document-related info
        assert len(resp.text) > 50
        assert "document" in resp.text.lower() or "pan" in resp.text.lower() or "aadhaar" in resp.text.lower()

    def test_faq_rera(self):
        resp = self.bot.respond("What is RERA?")
        # RERA keyword match should trigger the FAQ
        assert len(resp.text) > 20
        assert "rera" in resp.text.lower() or "regulatory" in resp.text.lower()

    def test_faq_home_loan(self):
        resp = self.bot.respond("What are the home loan options available?")
        # Should match loan FAQ or financial intent
        assert len(resp.text) > 20
        assert "loan" in resp.text.lower() or "bank" in resp.text.lower() or "interest" in resp.text.lower()

    def test_intent_classification_buying(self):
        intent = self.bot.classify_intent("I want to buy a 2BHK apartment in Bangalore")
        assert intent.category == "buying"

    def test_intent_classification_legal(self):
        intent = self.bot.classify_intent("What are the legal documents for property registration?")
        assert intent.category == "legal"

    def test_intent_classification_renting(self):
        intent = self.bot.classify_intent("How does the rent agreement process work?")
        assert intent.category == "renting"

    def test_property_search_query(self):
        resp = self.bot.respond("Show me properties in Mumbai")
        assert len(resp.text) > 20
        # Without property_service wired, should give help response
        # With property_service wired, should mention Mumbai
        assert "property" in resp.text.lower() or "mumbai" in resp.text.lower() or "find" in resp.text.lower()

    def test_namaste(self):
        resp = self.bot.respond("Namaste")
        assert len(resp.text) > 10

    def test_help_default_response(self):
        resp = self.bot.respond("What can you help me with?")
        assert len(resp.text) > 30


# ── Infrastructure Tests ────────────────────────────────────────────────────

class TestInMemoryRepository:
    def setup_method(self):
        self.repo = InMemoryPropertyRepository()

    def test_save_and_get(self):
        p = Property(property_id="RE-001", title="Test")
        self.repo.save(p)
        assert self.repo.get("RE-001").title == "Test"

    def test_delete(self):
        self.repo.save(Property(property_id="RE-002"))
        assert self.repo.delete("RE-002")
        assert not self.repo.delete("nonexistent")

    def test_count(self):
        self.repo.save(Property(property_id="RE-001"))
        self.repo.save(Property(property_id="RE-002"))
        assert self.repo.count() == 2

    def test_list_all(self):
        self.repo.save(Property(property_id="RE-001"))
        assert len(self.repo.list_all()) == 1


# ── API Wire Tests ──────────────────────────────────────────────────────────

class TestAPIWiring:
    def test_create_default_services(self):
        svc = create_default_services()
        assert "property_service" in svc
        assert "search_service" in svc
        assert "lead_service" in svc
        assert "neighborhood_service" in svc
        assert "rent_agreement_service" in svc
        assert "recommendation_engine" in svc
        assert "multi_language_service" in svc
        assert "broker_crm" in svc
        assert len(svc) == 9

    def test_broker_crm_register(self):
        crm = BrokerCRMService()
        from realestate.application.dto import UserDTO
        broker = crm.register_broker(UserDTO(user_id="B001", name="Ramesh", role="broker"))
        assert broker.name == "Ramesh"


# ── Validation Tests ────────────────────────────────────────────────────────

class TestValidation:
    def test_validate_phone_valid(self):
        from realestate.api.validation import validate_phone
        assert validate_phone("9876543210") == "9876543210"

    def test_validate_phone_invalid(self):
        from realestate.api.validation import HTTPException, validate_phone
        with pytest.raises(HTTPException):
            validate_phone("12345")

    def test_validate_email_valid(self):
        from realestate.api.validation import validate_email
        assert validate_email("test@example.com") == "test@example.com"

    def test_validate_email_invalid(self):
        from realestate.api.validation import HTTPException, validate_email
        with pytest.raises(HTTPException):
            validate_email("not-an-email")

    def test_validate_price_valid(self):
        from realestate.api.validation import validate_price
        assert validate_price(5000000) == 5000000

    def test_validate_price_too_low(self):
        from realestate.api.validation import HTTPException, validate_price
        with pytest.raises(HTTPException):
            validate_price(100)

    def test_property_create_validator_valid(self):
        from realestate.api.validation import PropertyCreateValidator
        result = PropertyCreateValidator.validate(
            title="Test Property", price=5000000, city="Mumbai",
        )
        assert result["title"] == "Test Property"

    def test_property_create_validator_invalid(self):
        from realestate.api.validation import HTTPException, PropertyCreateValidator
        with pytest.raises(HTTPException):
            PropertyCreateValidator.validate(
                title="", price=100, city="",
            )

    def test_lead_create_validator_valid(self):
        from realestate.api.validation import LeadCreateValidator
        result = LeadCreateValidator.validate(
            buyer_name="Raj Kumar", buyer_phone="9876543210", budget=5000000,
        )
        assert result["buyer_name"] == "Raj Kumar"

    def test_lead_create_validator_invalid_phone(self):
        from realestate.api.validation import HTTPException, LeadCreateValidator
        with pytest.raises(HTTPException):
            LeadCreateValidator.validate(buyer_name="Raj", buyer_phone="123")

    def test_enquiry_create_validator(self):
        from realestate.api.validation import EnquiryCreateValidator
        result = EnquiryCreateValidator.validate(
            name="Rahul", email="rahul@test.com", phone="9876543211",
        )
        assert result["name"] == "Rahul"

    def test_agreement_create_validator(self):
        from realestate.api.validation import AgreementCreateValidator
        result = AgreementCreateValidator.validate(
            rent_amount=25000, security_deposit=75000,
            lease_start="2026-08-01", lease_end="2027-07-31",
        )
        assert result["rent_amount"] == 25000

    def test_agreement_create_deposit_too_high(self):
        from realestate.api.validation import AgreementCreateValidator, HTTPException
        with pytest.raises(HTTPException):
            AgreementCreateValidator.validate(
                rent_amount=10000, security_deposit=200000,
                lease_start="2026-01-01", lease_end="2026-12-31",
            )


# ── PropertyService with Repository Tests ────────────────────────────────────

class TestPropertyServiceWithRepository:
    def test_service_uses_repository_when_injected(self):
        from realestate.infrastructure.repository import InMemoryPropertyRepository
        repo = InMemoryPropertyRepository()
        svc = PropertyService(repository=repo)
        p = svc.create_property(
            title="Repo Test", description="", property_type="apartment",
            price=5000000, city="Delhi", locality="Dwarka", owner_id="u1",
        )
        # Should be in both service and repository
        assert svc.get_property(p.property_id) is not None
        domain_obj = repo.get(p.property_id)
        assert domain_obj is not None
        assert domain_obj.title == "Repo Test"

    def test_service_repository_delete_sync(self):
        from realestate.infrastructure.repository import InMemoryPropertyRepository
        repo = InMemoryPropertyRepository()
        svc = PropertyService(repository=repo)
        p = svc.create_property(
            title="Delete Sync", description="", property_type="apartment",
            price=3000000, city="Pune", locality="", owner_id="u1",
        )
        svc.delete_property(p.property_id)
        assert svc.get_property(p.property_id) is None
        assert repo.get(p.property_id) is None

    def test_service_repository_property(self):
        svc = PropertyService()
        assert svc.repository is None
        from realestate.infrastructure.repository import InMemoryPropertyRepository
        repo = InMemoryPropertyRepository()
        svc2 = PropertyService(repository=repo)
        assert svc2.repository is not None


# ── SQLite Repository Tests ────────────────────────────────────────────────

class TestSQLiteRepository:
    def test_save_and_get(self):
        import os
        import tempfile

        from realestate.infrastructure.sqlite_repository import SQLitePropertyRepository
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            repo = SQLitePropertyRepository(db_path)
            p = Property(property_id="SQL-001", title="SQLite Test",
                         price=Decimal("10000000"),
                         property_type=PropertyType.APARTMENT,
                         location=Location(address=Address(city="TestCity")),
                         amenities=Amenities(bedrooms=2, bathrooms=2, carpet_area_sqft=1000))
            repo.save(p)
            fetched = repo.get("SQL-001")
            assert fetched is not None
            assert fetched.title == "SQLite Test"
            assert fetched.price == Decimal("10000000")
            assert fetched.amenities.bedrooms == 2
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass


    def test_delete(self):
        import os
        import tempfile

        from realestate.infrastructure.sqlite_repository import SQLitePropertyRepository
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            repo = SQLitePropertyRepository(db_path)
            p = Property(property_id="SQL-002")
            repo.save(p)
            assert repo.delete("SQL-002") is True
            assert repo.get("SQL-002") is None
            assert repo.delete("nonexistent") is False
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass


    def test_count(self):
        import os
        import tempfile

        from realestate.infrastructure.sqlite_repository import SQLitePropertyRepository
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            repo = SQLitePropertyRepository(db_path)
            assert repo.count() == 0
            repo.save(Property(property_id="SQL-003"))
            repo.save(Property(property_id="SQL-004"))
            assert repo.count() == 2
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass


    def test_list_all(self):
        import os
        import tempfile

        from realestate.infrastructure.sqlite_repository import SQLitePropertyRepository
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            repo = SQLitePropertyRepository(db_path)
            repo.save(Property(property_id="SQL-005", title="A"))
            repo.save(Property(property_id="SQL-006", title="B"))
            props = repo.list_all()
            assert len(props) == 2
            titles = {p.title for p in props}
            assert "A" in titles and "B" in titles
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass


    def test_search_by_city(self):
        import os
        import tempfile

        from realestate.infrastructure.sqlite_repository import SQLitePropertyRepository
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            repo = SQLitePropertyRepository(db_path)
            repo.save(Property(property_id="SQL-007",
                               location=Location(address=Address(city="Mumbai"))))
            repo.save(Property(property_id="SQL-008",
                               location=Location(address=Address(city="Pune"))))
            results = repo.search(city="Mumbai")
            assert len(results) == 1
            assert results[0].property_id == "SQL-007"
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass


    def test_save_updates_existing(self):
        import os
        import tempfile

        from realestate.infrastructure.sqlite_repository import SQLitePropertyRepository
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            repo = SQLitePropertyRepository(db_path)
            p = Property(property_id="SQL-009", title="Original")
            repo.save(p)
            p.title = "Updated"
            repo.save(p)
            fetched = repo.get("SQL-009")
            assert fetched.title == "Updated"
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass



# ── Map Data API Tests ──────────────────────────────────────────────────────

class TestMapDataAPI:
    def test_map_data_empty_no_coords(self):
        from realestate.application.services import PropertyService
        ps = PropertyService()
        ps.create_property(
            title="No Coords", description="", property_type="apartment",
            price=5000000, city="Delhi", locality="", owner_id="u1",
        )
        # Latitude/longitude are 0, so no map data
        all_props = ps.list_all()
        map_props = [p for p in all_props if p.latitude and p.longitude]
        assert len(map_props) == 0

    def test_map_data_with_coords(self):
        from decimal import Decimal

        from realestate.application.services import PropertyService
        from realestate.domain.models import Address, Location
        from realestate.domain.models import Property as DomainProperty
        ps = PropertyService()
        # Create a property via domain model and inject directly
        prop = DomainProperty(
            property_id="MAP-001", title="Has Coords",
            price=Decimal("7500000"),
            location=Location(
                address=Address(city="Mumbai", latitude=19.076, longitude=72.8777)
            ),
        )
        ps._properties["MAP-001"] = prop
        all_props = ps.list_all()
        map_props = [p for p in all_props if p.latitude and p.longitude]
        assert len(map_props) == 1
        assert map_props[0].latitude == 19.076


# ── Auction Tests ────────────────────────────────────────────────────────────

class TestAuctionEngine:
    def setup_method(self):
        from realestate.auction.engine import AuctionEngine
        self.engine = AuctionEngine()

    def test_create_auction(self):
        a = self.engine.create_auction(
            property_id="RE-001", property_title="Test Property",
            city="Mumbai", locality="Andheri", bedrooms=2,
            starting_bid=1000000, reserve_price=1200000, duration_hours=48,
        )
        assert a.auction_id is not None
        assert a.starting_bid == 1000000
        assert a.status.value == "scheduled"

    def test_start_auction(self):
        a = self.engine.create_auction("RE-001", "Test", "Mumbai", "", 2, 500000, 600000)
        assert self.engine.start_auction(a.auction_id)
        assert self.engine.get_auction(a.auction_id).status.value == "active"

    def test_place_bid(self):
        a = self.engine.create_auction("RE-001", "Test", "Mumbai", "", 2, 1000000)
        self.engine.start_auction(a.auction_id)
        result = self.engine.place_bid(a.auction_id, "B1", "Buyer1", 1100000)
        assert result.success
        assert result.is_new_high_bid

    def test_place_bid_too_low(self):
        a = self.engine.create_auction("RE-001", "Test", "Mumbai", "", 2, 1000000)
        self.engine.start_auction(a.auction_id)
        result = self.engine.place_bid(a.auction_id, "B1", "Buyer1", 1005000)
        assert not result.success  # Below min increment

    def test_buy_it_now(self):
        a = self.engine.create_auction(
            "RE-001", "Test", "Mumbai", "", 2, 1000000, buy_it_now_price=2000000,
        )
        self.engine.start_auction(a.auction_id)
        result = self.engine.place_bid(a.auction_id, "B1", "Buyer1", 2000000)
        assert result.success
        assert result.is_buy_it_now
        assert self.engine.get_auction(a.auction_id).status.value == "sold"

    def test_auction_bids(self):
        a = self.engine.create_auction("RE-001", "Test", "Mumbai", "", 2, 500000)
        self.engine.start_auction(a.auction_id)
        self.engine.place_bid(a.auction_id, "B1", "A", 600000)
        self.engine.place_bid(a.auction_id, "B2", "B", 700000)
        bids = self.engine.get_bids_for_auction(a.auction_id)
        assert len(bids) == 2
        assert bids[0].amount == 700000  # newest first

    def test_cancel_auction(self):
        a = self.engine.create_auction("RE-001", "Test", "Mumbai", "", 2, 500000)
        assert self.engine.cancel_auction(a.auction_id)
        assert self.engine.get_auction(a.auction_id).status.value == "cancelled"

    def test_stats(self):
        a = self.engine.create_auction("RE-001", "T1", "M", "", 2, 500000)
        self.engine.start_auction(a.auction_id)
        self.engine.place_bid(a.auction_id, "B1", "X", 600000)
        stats = self.engine.get_stats()
        assert stats["total_auctions"] == 1
        assert stats["total_bids_placed"] == 1


# ── ML Prediction Tests ─────────────────────────────────────────────────────

class TestMLPrediction:
    def test_heuristic_price(self):
        from realestate.ml_prediction import _heuristic_price
        price = _heuristic_price({"city": "mumbai", "carpet_area_sqft": 1000, "total_area_sqft": 1200})
        assert price > 0
        assert price > 500000  # Minimum

    def test_price_prediction_input(self):
        from realestate.ml_prediction import PricePredictionInput
        inp = PricePredictionInput(city="Mumbai", bedrooms=3, carpet_area_sqft=1200)
        fd = inp.to_feature_dict()
        assert fd["city"] == "mumbai"
        assert fd["bedrooms"] == 3

    def test_predictor_heuristic_fallback(self):
        from realestate.ml_prediction import PricePredictionInput, PricePredictor
        predictor = PricePredictor()
        inp = PricePredictionInput(city="Bangalore", bedrooms=2, carpet_area_sqft=1000)
        prediction = predictor.predict(inp)
        assert prediction.predicted_price > 0
        assert prediction.min_price < prediction.predicted_price < prediction.max_price
        assert "features" in str(type(prediction)).lower() or hasattr(prediction, 'features_used')

    def test_predictor_train(self):
        from realestate.ml_prediction import PricePredictor
        predictor = PricePredictor()
        result = predictor.train()
        assert result["success"]
        assert result["training_samples"] >= 300

    def test_furnishing_multipliers(self):
        from realestate.ml_prediction import FURNISHING_MULTIPLIERS
        assert FURNISHING_MULTIPLIERS["furnished"] > FURNISHING_MULTIPLIERS["unfurnished"]

    def test_city_base_prices(self):
        from realestate.ml_prediction import CITY_BASE_PRICES
        assert "mumbai" in CITY_BASE_PRICES
        assert CITY_BASE_PRICES["mumbai"] > CITY_BASE_PRICES["kolkata"]


# ── Builder Portal Tests ────────────────────────────────────────────────────

class TestBuilderPortal:
    def setup_method(self):
        from realestate.builder_portal import BuilderPortal
        self.portal = BuilderPortal()

    def test_create_project(self):
        p = self.portal.create_project(
            developer_id="DEV-001", developer_name="ABC Builders",
            name="Green Acres", description="Luxury apartments",
            city="Bangalore", locality="Whitefield",
            total_units=100, possession_date="Dec 2027",
            rera_registration="RERA-BLR-2024-00123",
        )
        assert p.project_id is not None
        assert p.name == "Green Acres"
        assert p.status.value == "pre_launch"

    def test_add_units(self):
        p = self.portal.create_project("DEV-001", "ABC", "Proj", "", "Pune", "Hinjewadi", 50, "Dec 2027")
        units = self.portal.add_units(p.project_id, [
            {"unit_number": "101", "floor_number": 1, "unit_type": "2BHK", "carpet_area_sqft": 850, "price": 7500000},
            {"unit_number": "102", "floor_number": 1, "unit_type": "3BHK", "carpet_area_sqft": 1200, "price": 10000000},
        ])
        assert len(units) == 2
        assert len(self.portal.get_units(p.project_id)) == 2

    def test_book_unit(self):
        p = self.portal.create_project("DEV-001", "ABC", "Proj", "", "Mumbai", "", 10, "Dec 2027")
        self.portal.add_units(p.project_id, [{"unit_number": "201", "unit_type": "2BHK", "carpet_area_sqft": 900, "price": 8000000}])
        success = self.portal.book_unit(
            unit_id=f"U-{p.project_id}-201",
            buyer_id="BUY-001", buyer_name="Rajesh",
            project_id=p.project_id,
        )
        assert success
        project = self.portal.get_project(p.project_id)
        assert project.sold_units == 1

    def test_rera_compliance(self):
        self.portal.create_project("DEV-001", "ABC", "P1", "", "Delhi", "", 50, "Dec 2027", rera_registration="RERA-001")
        self.portal.create_project("DEV-001", "ABC", "P2", "", "Delhi", "", 30, "Jun 2028")
        report = self.portal.check_rera_compliance("DEV-001")
        assert report["total_projects"] == 2
        assert report["rera_registered"] == 1
        assert report["rera_compliance_pct"] == 50.0

    def test_portal_stats(self):
        self.portal.create_project("DEV-001", "ABC", "P1", "", "Mumbai", "", 10, "Dec 2027")
        stats = self.portal.get_stats()
        assert stats["total_projects"] == 1

    def test_update_project_status(self):
        p = self.portal.create_project("DEV-001", "ABC", "P1", "", "Chennai", "", 20, "Dec 2027")
        assert self.portal.update_project_status(p.project_id, "launched")
        assert self.portal.get_project(p.project_id).status.value == "launched"


# ── Search Engine Tests ─────────────────────────────────────────────────────

class TestSearchEngine:
    def setup_method(self):
        self.repo = InMemoryPropertyRepository()
        self.engine = SearchEngine(self.repo)

        p1 = Property(property_id="RE-001", title="2BHK Andheri", price=Decimal("8000000"),
                       property_type=PropertyType.APARTMENT,
                       location=Location(address=Address(city="Mumbai", locality="Andheri")),
                       amenities=Amenities(bedrooms=2, carpet_area_sqft=800))
        p2 = Property(property_id="RE-002", title="3BHK Bandra", price=Decimal("25000000"),
                       property_type=PropertyType.APARTMENT,
                       location=Location(address=Address(city="Mumbai", locality="Bandra")),
                       amenities=Amenities(bedrooms=3, carpet_area_sqft=1500))
        self.repo.save(p1)
        self.repo.save(p2)

    def test_engine_search_all(self):
        result = self.engine.search()
        assert result.total == 2

    def test_engine_search_city(self):
        result = self.engine.search(city="Mumbai")
        assert result.total == 2

    def test_engine_search_bedroom(self):
        result = self.engine.search(min_bedrooms=3)
        assert result.total == 1

    def test_engine_search_price(self):
        result = self.engine.search(max_price=10000000)
        assert result.total == 1
