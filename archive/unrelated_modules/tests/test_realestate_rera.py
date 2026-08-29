"""Tests for the RERA Compliance Checker module."""

from __future__ import annotations

import pytest
from realestate.rera_compliance import (
    RERA_PATTERN,
    RERA_STATE_CODES,
    RERAComplianceEngine,
    create_rera_router,
    get_rera_engine,
)

# ═══════════════════════════════════════════════════════════════════════════════
# RERA Format Validation Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRERAFormatValidation:
    def test_valid_rera_mh(self):
        result = RERAComplianceEngine.validate_format("RERA-MH-2024-00123")
        assert result is not None
        assert result["state"] == "MH"
        assert result["state_name"] == "Maharashtra"
        assert result["year"] == 2024
        assert result["sequence"] == 123

    def test_valid_rera_ka(self):
        result = RERAComplianceEngine.validate_format("RERA-KA-2023-00789")
        assert result is not None
        assert result["state"] == "KA"

    def test_valid_rera_with_slash(self):
        result = RERAComplianceEngine.validate_format("RERA/MH/2024/00123")
        assert result is not None
        assert result["rera_number"] == "RERA-MH-2024-00123"

    def test_invalid_rera_no_state(self):
        assert RERAComplianceEngine.validate_format("RERA-2024-00123") is None

    def test_invalid_rera_wrong_state(self):
        assert RERAComplianceEngine.validate_format("RERA-XX-2024-00123") is None

    def test_invalid_rera_garbage(self):
        assert RERAComplianceEngine.validate_format("not-a-rera-number") is None

    def test_valid_rera_case_insensitive(self):
        result = RERAComplianceEngine.validate_format("rera-mh-2024-00123")
        assert result is not None

    def test_valid_rera_long_sequence(self):
        result = RERAComplianceEngine.validate_format("RERA-TN-2024-123456")
        assert result is not None
        assert result["sequence"] == 123456

    def test_all_state_codes_present(self):
        """All major Indian states should have RERA codes."""
        assert "MH" in RERA_STATE_CODES
        assert "KA" in RERA_STATE_CODES
        assert "DL" in RERA_STATE_CODES
        assert "HR" in RERA_STATE_CODES
        assert "UP" in RERA_STATE_CODES
        assert "TN" in RERA_STATE_CODES
        assert "GJ" in RERA_STATE_CODES
        assert len(RERA_STATE_CODES) >= 21

    def test_regex_matches_valid(self):
        assert RERA_PATTERN.match("RERA-MH-2024-00123") is not None
        assert RERA_PATTERN.match("RERA/KA/2023/00789") is not None


# ═══════════════════════════════════════════════════════════════════════════════
# RERA Verification Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRERAVerification:
    def setup_method(self):
        self.engine = RERAComplianceEngine()

    def test_verify_known_builder(self):
        """Known RERA numbers should return verified registration."""
        result = self.engine.verify("RERA-MH-2024-00123")
        assert result.is_verified
        assert result.builder_name == "ABC Builders Pvt Ltd"
        assert result.status == "active"

    def test_verify_unknown_builder(self):
        """Unknown but format-valid RERA should return unverified."""
        result = self.engine.verify("RERA-KL-2025-99999")
        assert not result.is_verified
        assert result.state == "KL"

    def test_verify_invalid_format(self):
        with pytest.raises(ValueError):
            self.engine.verify("invalid")

    def test_verify_suspended_builder(self):
        result = self.engine.verify("RERA-UP-2023-00111")
        assert result.is_verified
        assert result.status == "suspended"

    def test_register_new_builder(self):
        result = self.engine.register_builder(
            "RERA-MH-2025-55555",
            "New Builder Ltd",
            "New Project",
            "Mumbai",
        )
        assert result.is_verified
        assert result.builder_name == "New Builder Ltd"
        assert result.status == "active"

    def test_register_duplicate_raises(self):
        """Registering with an existing RERA number should update."""
        self.engine.register_builder("RERA-MH-2024-88888", "B1", "P1")
        # Should update existing
        result = self.engine.register_builder("RERA-MH-2024-88888", "B2", "P2")
        assert result.builder_name == "B2"

    def test_get_registrations_all(self):
        regs = self.engine.get_registrations()
        assert len(regs) >= 7  # Mock seed data

    def test_get_registrations_by_state(self):
        regs = self.engine.get_registrations("MH")
        assert len(regs) >= 1
        assert all(r["state"] == "MH" for r in regs)

    def test_compliance_stats(self):
        stats = self.engine.get_compliance_stats()
        assert stats["total_registrations"] >= 7
        assert stats["states_covered"] >= 1
        assert stats["compliance_rate"] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Property Compliance Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPropertyCompliance:
    def setup_method(self):
        self.engine = RERAComplianceEngine()

    def test_check_compliant_property(self):
        """A property with a valid, active RERA should score highly."""
        from realestate.application.dto import PropertyDTO
        prop = PropertyDTO(
            property_id="RE-001",
            title="Compliant Property",
            rera_number="RERA-MH-2024-00123",
        )
        result = self.engine.check_property_compliance(prop)
        assert result["status"] in ("compliant", "warning")
        assert result["score"] >= 50

    def test_check_no_rera_property(self):
        from realestate.application.dto import PropertyDTO
        prop = PropertyDTO(property_id="RE-002", title="No RERA")
        result = self.engine.check_property_compliance(prop)
        assert result["status"] == "no_rera"
        assert result["score"] == 0

    def test_check_invalid_rera_property(self):
        from realestate.application.dto import PropertyDTO
        prop = PropertyDTO(
            property_id="RE-003",
            title="Bad RERA",
            rera_number="invalid-rera",
        )
        result = self.engine.check_property_compliance(prop)
        assert result["status"] == "invalid_format"
        assert result["score"] == 0

    def test_check_suspended_property(self):
        from realestate.application.dto import PropertyDTO
        prop = PropertyDTO(
            property_id="RE-004",
            title="Suspended",
            rera_number="RERA-UP-2023-00111",
        )
        result = self.engine.check_property_compliance(prop)
        assert result["status"] == "warning"
        assert "SUSPENDED" in str(result["recommendations"])

    def test_check_with_recommendations(self):
        from realestate.application.dto import PropertyDTO
        prop = PropertyDTO(
            property_id="RE-005",
            title="Unknown RERA",
            rera_number="RERA-KL-2025-99999",
        )
        result = self.engine.check_property_compliance(prop)
        assert len(result["recommendations"]) > 0

    def test_checks_structure(self):
        from realestate.application.dto import PropertyDTO
        prop = PropertyDTO(
            property_id="RE-001",
            rera_number="RERA-MH-2024-00123",
        )
        result = self.engine.check_property_compliance(prop)
        assert "checks" in result
        assert "rera_format" in result["checks"]
        assert "rera_registered" in result["checks"]
        assert "registration" in result
        assert "last_checked" in result


# ═══════════════════════════════════════════════════════════════════════════════
# API Router Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRERAAPIRouter:
    def test_verify_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(create_rera_router())
        client = TestClient(app)

        resp = client.get("/api/realestate/rera/verify?rera_number=RERA-MH-2024-00123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"]
        assert data["registration"]["is_verified"]

    def test_verify_invalid_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(create_rera_router())
        client = TestClient(app)

        resp = client.get("/api/realestate/rera/verify?rera_number=invalid")
        assert resp.status_code == 400

    def test_validate_format_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(create_rera_router())
        client = TestClient(app)

        resp = client.get("/api/realestate/rera/validate-format?rera_number=RERA-MH-2024-00123")
        assert resp.status_code == 200
        assert resp.json()["valid"]

    def test_validate_format_invalid(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(create_rera_router())
        client = TestClient(app)

        resp = client.get("/api/realestate/rera/validate-format?rera_number=invalid")
        assert resp.status_code == 400

    def test_register_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(create_rera_router())
        client = TestClient(app)

        resp = client.post(
            "/api/realestate/rera/register",
            params={
                "rera_number": "RERA-GJ-2024-55555",
                "builder_name": "Test Builder",
                "project_name": "Test Project",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"]

    def test_register_invalid_format(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(create_rera_router())
        client = TestClient(app)

        resp = client.post(
            "/api/realestate/rera/register",
            params={"rera_number": "invalid", "builder_name": "B", "project_name": "P"},
        )
        assert resp.status_code == 400

    def test_stats_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(create_rera_router())
        client = TestClient(app)

        resp = client.get("/api/realestate/rera/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "stats" in data
        assert data["stats"]["total_registrations"] >= 7

    def test_registrations_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(create_rera_router())
        client = TestClient(app)

        resp = client.get("/api/realestate/rera/registrations")
        assert resp.status_code == 200
        assert len(resp.json()["registrations"]) >= 7

    def test_registrations_filtered_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(create_rera_router())
        client = TestClient(app)

        resp = client.get("/api/realestate/rera/registrations?state=MH")
        assert resp.status_code == 200
        regs = resp.json()["registrations"]
        assert len(regs) >= 1
        assert all(r["state"] == "MH" for r in regs)

    def test_check_endpoint_no_property(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(create_rera_router())
        client = TestClient(app)

        resp = client.get("/api/realestate/rera/check")
        assert resp.status_code == 200

    def test_singleton(self):
        m1 = get_rera_engine()
        m2 = get_rera_engine()
        assert m1 is m2
