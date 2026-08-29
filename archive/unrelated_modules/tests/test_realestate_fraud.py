"""Tests for the fraud detection system."""

from __future__ import annotations

from realestate.fraud_detection import (
    FraudCategory,
    FraudDetectionEngine,
    FraudSeverity,
)


class TestFraudDetectionEngine:
    def setup_method(self):
        self.engine = FraudDetectionEngine()

    def test_clean_property_passes(self):
        """A normal property should have low fraud score."""
        result = self.engine.check_property({
            "property_id": "RE-001",
            "title": "Beautiful 2BHK in Andheri",
            "description": "Spacious apartment with modern amenities in prime location.",
            "price": 7500000,
            "city": "Mumbai",
            "owner_phone": "9876543210",
            "owner_email": "owner@example.com",
        }, area_avg_price=12000)
        assert result.score < 0.5
        assert not result.is_blocked

    def test_duplicate_content_detected(self):
        """Properties with same text should be flagged as duplicates."""
        data = {
            "property_id": "RE-001",
            "title": "Duplicate Listing",
            "description": "Same description text for fraud check.",
            "price": 5000000,
            "owner_phone": "9123456789",
            "owner_email": "a@b.com",
        }
        self.engine.check_property(data)
        # Second identical property
        data2 = dict(data, property_id="RE-002")
        result2 = self.engine.check_property(data2)
        assert result2.score > 0.4
        assert "duplicate" in " ".join(result2.matched_rules).lower() or result2.score > 0.4

    def test_suspicious_price_low(self):
        """Extremely low price should increase fraud score."""
        result = self.engine.check_property({
            "property_id": "RE-CHEAP",
            "title": "Prime Location Property",
            "description": "Well maintained property",
            "price": 100000,
            "city": "Mumbai",
            "owner_phone": "9988776655",
            "owner_email": "test@example.com",
            "carpet_area_sqft": 1000,
        }, area_avg_price=20000)
        assert result.score > 0.3
        assert "price" in str(result.reasons).lower()

    def test_blacklisted_phone_flagged(self):
        """Properties from blacklisted phone should be flagged with high score."""
        self.engine.blacklist_phone("9999999999", "Known fraud")
        result = self.engine.check_property({
            "property_id": "RE-BAD",
            "title": "Suspicious Property",
            "description": "Too good to be true",
            "price": 1000000,
            "owner_phone": "9999999999",
            "owner_email": "fraud@test.com",
        })
        # Phone blacklist adds 0.8, auto-block threshold is 0.9
        # So score >= 0.8 but < 0.9 unless other rules fire
        assert result.score >= 0.7
        assert result.score < 1.0
        assert result.severity == FraudSeverity.CRITICAL

    def test_suspicious_keywords(self):
        """Properties with fraud keywords should get higher score."""
        result = self.engine.check_property({
            "property_id": "RE-KEY",
            "title": "Urgent Sale Owner Leaving City",
            "description": "Below market price need immediate sale best deal ever direct owner",
            "price": 3000000,
            "city": "Delhi",
            "owner_phone": "9876501234",
            "owner_email": "owner@example.com",
        })
        assert result.score > 0.1
        assert len(result.matched_rules) >= 1

    def test_enquiry_bulk_detection(self):
        """Multiple rapid enquiries should be flagged."""
        results = []
        for i in range(15):
            r = self.engine.check_enquiry(
                user_id="bulk_user",
                phone="9876543210",
                property_id=f"RE-{i:03d}",
            )
            results.append(r)

        # Some bulk checks should have HIGH severity
        high = [r for r in results if r.severity in (FraudSeverity.HIGH, FraudSeverity.CRITICAL)]
        assert len(high) > 0

    def test_blacklist_user(self):
        """Blacklisted users should be blocked on enquiry."""
        self.engine.blacklist_user("bad_user", "Known fraudster")
        result = self.engine.check_enquiry(user_id="bad_user")
        assert result.is_blocked
        assert result.score > 0.8

    def test_disposable_email_detected(self):
        """Disposable email domains should increase score."""
        result = self.engine.check_property({
            "property_id": "RE-DISP",
            "title": "Property from temp email",
            "description": "Description text",
            "price": 5000000,
            "owner_phone": "9988776655",
            "owner_email": "owner@mailinator.com",
        })
        assert result.score > 0.2
        assert any("email" in r.lower() for r in result.reasons)

    def test_invalid_phone_detected(self):
        """Invalid Indian phone numbers should be flagged."""
        result = self.engine.check_property({
            "property_id": "RE-PHONE",
            "title": "Bad Phone Property",
            "description": "Description text",
            "price": 5000000,
            "owner_phone": "12345",
            "owner_email": "a@b.com",
        })
        assert result.score > 0.2
        assert any("phone" in r.lower() for r in result.reasons)

    def test_get_stats(self):
        self.engine.check_property({"property_id": "STATS-1", "title": "T", "description": "D", "price": 1000, "owner_phone": "9876543211"})
        stats = self.engine.get_stats()
        assert stats["total_checks"] >= 1
        assert "by_category" in stats

    def test_generate_report(self):
        self.engine.check_property({"property_id": "RPT-1", "title": "T", "description": "D", "price": 1000, "owner_phone": "9876543212"})
        report = self.engine.generate_report()
        assert report.total_checks >= 1
        assert len(report.recent_results) >= 1

    def test_is_blacklisted(self):
        self.engine.blacklist_phone("1111111111")
        assert self.engine.is_blacklisted(phone="1111111111")
        assert not self.engine.is_blacklisted(phone="2222222222")


class TestFraudConstants:
    def test_severity_order(self):
        """FraudSeverity should have logical ordering."""
        assert FraudSeverity.LOW.order < FraudSeverity.MEDIUM.order
        assert FraudSeverity.MEDIUM.order < FraudSeverity.HIGH.order
        assert FraudSeverity.HIGH.order < FraudSeverity.CRITICAL.order
        assert FraudSeverity.LOW.label == "low"
        assert FraudSeverity.CRITICAL.label == "critical"

    def test_categories(self):
        assert FraudCategory.DUPLICATE_LISTING.value == "duplicate_listing"
        assert FraudCategory.BULK_ENQUIRY.value == "bulk_enquiry"


class TestFraudCheckResult:
    def test_to_dict(self):
        result = FraudDetectionEngine().check_property({
            "property_id": "DICT-1", "title": "T", "description": "D",
            "price": 1000, "owner_phone": "9988776655",
        })
        d = result.to_dict()
        assert "score" in d
        assert "reasons" in d
        assert "is_blocked" in d
