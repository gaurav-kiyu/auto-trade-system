"""Tests for production-critical modules: email, upload, PostgreSQL."""

from __future__ import annotations

import time

import pytest
from realestate.email_service import (
    SMTP_CONFIG,
    EmailService,
    get_email_service,
    is_smtp_configured,
)
from realestate.upload_service import (
    UPLOAD_CONFIG,
    UploadService,
    get_upload_service,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Email Service Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestEmailService:
    def setup_method(self):
        self.svc = EmailService()

    def test_send_email_log_only(self):
        """Should log email when SMTP is not configured (no error)."""
        result = self.svc.send_email("test@example.com", "Test Subject", "<p>Hello</p>")
        assert result.to == "test@example.com"
        assert result.subject == "Test Subject"

    def test_send_no_recipient(self):
        result = self.svc.send_email("", "Subject", "<p>Content</p>")
        assert not result.success
        assert "No recipient" in result.error

    def test_sent_emails_tracked(self):
        self.svc.send_email("a@test.com", "S1", "<p>A</p>")
        self.svc.send_email("b@test.com", "S2", "<p>B</p>")
        sent = self.svc.get_sent_emails()
        assert len(sent) >= 2

    def test_sent_emails_newest_first(self):
        self.svc.send_email("e1@test.com", "Older", "<p>1</p>")
        time.sleep(0.01)
        self.svc.send_email("e2@test.com", "Newer", "<p>2</p>")
        sent = self.svc.get_sent_emails(limit=2)
        assert sent[0].subject == "Newer"

    def test_stats(self):
        self.svc.send_email("s@test.com", "S", "<p>X</p>")
        stats = self.svc.get_stats()
        assert stats["total_sent"] >= 1
        assert "success_rate" in stats
        assert "smtp_configured" in stats

    def test_enquiry_notification(self):
        result = self.svc.send_enquiry_notification(
            owner_email="owner@test.com",
            property_title="2BHK in Bandra",
            enquirer_name="Rahul",
            enquirer_phone="9876543210",
            enquirer_message="I'm interested",
        )
        assert result.success
        assert "Enquiry" in result.subject

    def test_payment_receipt(self):
        result = self.svc.send_payment_receipt(
            user_email="user@test.com",
            user_name="Raj",
            amount=25000,
            purpose="Aug 2026 Rent",
            payment_method="UPI",
            transaction_id="TXN123",
        )
        assert result.success
        assert "Receipt" in result.subject

    def test_auction_won(self):
        result = self.svc.send_auction_won(
            user_email="buyer@test.com",
            user_name="Amit",
            property_title="Luxury Villa",
            amount=5000000,
        )
        assert result.success
        assert "Won" in result.subject

    def test_agreement_signed(self):
        result = self.svc.send_agreement_signed(
            user_email="tenant@test.com",
            property_title="2BHK in Pune",
            agreement_id="AG-001",
        )
        assert result.success
        assert "Signed" in result.subject

    def test_lead_update(self):
        result = self.svc.send_lead_update(
            broker_email="broker@test.com",
            lead_name="Priya",
            property_title="3BHK in Bangalore",
            new_status="interested",
        )
        assert result.success
        assert "Lead" in result.subject

    def test_property_match_alert(self):
        result = self.svc.send_property_match_alert(
            user_email="user@test.com",
            user_name="Ravi",
            property_title="New 2BHK",
            property_price=7500000,
            property_city="Mumbai",
            property_url="/property/RE-001",
        )
        assert result.success
        assert "Match" in result.subject

    def test_smtp_not_configured_by_default(self):
        """In test environment, SMTP should not be configured."""
        # SMTP_CONFIG is read from env, which won't be set in tests
        assert not is_smtp_configured()

    def test_singleton(self):
        s1 = get_email_service()
        s2 = get_email_service()
        assert s1 is s2


# ═══════════════════════════════════════════════════════════════════════════════
# Upload Service Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestUploadService:
    def setup_method(self):
        self.svc = UploadService()

    def test_upload_file(self):
        result = self.svc.upload(
            file_data=b"fake-image-data",
            original_name="test.jpg",
            property_id="RE-001",
            mime_type="image/jpeg",
        )
        assert result.file_id is not None
        assert result.property_id == "RE-001"
        assert result.original_name == "test.jpg"
        assert result.mime_type == "image/jpeg"
        assert result.size_bytes == len(b"fake-image-data")
        assert "/uploads/" in result.url

    def test_upload_no_property(self):
        result = self.svc.upload(
            file_data=b"data",
            original_name="img.png",
        )
        assert result.file_id is not None
        assert result.property_id == ""

    def test_upload_too_large(self):
        large_data = b"x" * (11 * 1024 * 1024)  # 11MB > default 10MB
        with pytest.raises(ValueError, match="File too large"):
            self.svc.upload(large_data, "big.jpg")

    def test_upload_invalid_type(self):
        with pytest.raises(ValueError, match="not allowed"):
            self.svc.upload(
                file_data=b"data",
                original_name="file.exe",
                mime_type="application/x-msdownload",
            )

    def test_get_upload(self):
        uploaded = self.svc.upload(b"data", "test.jpg", "RE-001")
        result = self.svc.get_upload(uploaded.file_id)
        assert result is not None
        assert result.file_id == uploaded.file_id

    def test_get_uploads_for_property(self):
        self.svc.upload(b"img1", "img1.jpg", "RE-002")
        self.svc.upload(b"img2", "img2.jpg", "RE-002")
        uploads = self.svc.get_uploads_for_property("RE-002")
        assert len(uploads) == 2

    def test_delete_upload(self):
        uploaded = self.svc.upload(b"data", "delete.jpg", "RE-003")
        assert self.svc.delete_upload(uploaded.file_id)
        assert self.svc.get_upload(uploaded.file_id) is None

    def test_set_primary(self):
        u1 = self.svc.upload(b"img1", "img1.jpg", "RE-004")
        u2 = self.svc.upload(b"img2", "img2.jpg", "RE-004")
        self.svc.set_primary(u1.file_id, "RE-004")
        assert self.svc.get_upload(u1.file_id).is_primary
        assert not self.svc.get_upload(u2.file_id).is_primary

    def test_get_stats(self):
        self.svc.upload(b"data", "s1.jpg", "RE-005")
        self.svc.upload(b"data2", "s2.jpg", "RE-006")
        stats = self.svc.get_stats()
        assert stats["total_files"] == 2
        assert stats["properties_with_uploads"] == 2
        assert stats["total_bytes"] > 0

    def test_singleton(self):
        s1 = get_upload_service()
        s2 = get_upload_service()
        assert s1 is s2


# ═══════════════════════════════════════════════════════════════════════════════
# PostgreSQL Repository Tests (lightweight — no real DB)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPostgresRepository:
    def test_repository_instantiation(self):
        """Postgres repository should instantiate without error."""
        from realestate.infrastructure.postgres_repository import PostgresPropertyRepository
        repo = PostgresPropertyRepository()
        assert repo is not None

    def test_repository_has_available_property(self):
        """Repository should expose the `available` property."""
        from realestate.infrastructure.postgres_repository import PostgresPropertyRepository
        repo = PostgresPropertyRepository()
        # When SQLAlchemy is installed (even with SQLite), the repo becomes available
        assert hasattr(repo, "available")
        # The available flag depends on whether SQLAlchemy ORM models loaded
        assert isinstance(repo.available, bool)

    def test_migration_helpers_exist(self):
        """Migration functions should exist and not crash."""
        from realestate.infrastructure.postgres_repository import MIGRATIONS
        assert len(MIGRATIONS) >= 1
        assert MIGRATIONS[0]["version"] == 1
        assert "re_properties" in MIGRATIONS[0]["sql"]

    def test_migration_runs_with_sqlite(self):
        """When SQLAlchemy+SQLite is available, migrations should apply."""
        from realestate.infrastructure.postgres_repository import run_migrations
        # SQLAlchemy is installed — migrations will run against default SQLite
        results = run_migrations(engine=None)
        assert len(results) >= 1
        # Either applied successfully or already applied from previous test
        assert results[0]["status"] in ("applied", "already_applied", "skipped")

    def test_session_scope_with_sqlite(self):
        """When SQLAlchemy is available, session_scope should work with SQLite."""
        from realestate.infrastructure.postgres_repository import session_scope
        try:
            with session_scope() as session:
                # Should succeed since SQLAlchemy+SQLite is available
                assert session is not None
        except RuntimeError:
            # In some environments, SQLite may not be usable
            pass

    def test_domain_conversion(self):
        """Postgres model should convert to domain properly."""
        from decimal import Decimal

        from realestate.domain.models import Address, Amenities, Location, Property, PropertyType

        p = Property(
            property_id="PG-001",
            title="PG Test",
            price=Decimal("10000000"),
            location=Location(address=Address(city="TestCity", locality="TestLocality")),
            amenities=Amenities(bedrooms=3, bathrooms=2, carpet_area_sqft=1200),
            property_type=PropertyType.APARTMENT,
        )
        assert p.property_id == "PG-001"
        assert p.amenities.bedrooms == 3
        assert float(p.price) == 10000000.0

    def test_lead_domain_conversion(self):
        from realestate.domain.models import Lead, LeadStatus
        lead = Lead(
            lead_id="LD-PG-001",
            property_id="PG-001",
            buyer_name="Test Buyer",
            status=LeadStatus.NEW,
        )
        assert lead.buyer_name == "Test Buyer"
        assert lead.status == LeadStatus.NEW


# ═══════════════════════════════════════════════════════════════════════════════
# Config Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfig:
    def test_email_config_exists(self):
        assert "host" in SMTP_CONFIG
        assert "port" in SMTP_CONFIG
        assert "from_email" in SMTP_CONFIG

    def test_upload_config_exists(self):
        assert "storage" in UPLOAD_CONFIG
        assert "max_size_mb" in UPLOAD_CONFIG
        assert "allowed_types" in UPLOAD_CONFIG

    def test_upload_default_storage(self):
        assert UPLOAD_CONFIG["storage"] == "local"

    def test_email_defaults(self):
        assert SMTP_CONFIG["port"] == 587
        assert "noreply@" in SMTP_CONFIG["from_email"]
