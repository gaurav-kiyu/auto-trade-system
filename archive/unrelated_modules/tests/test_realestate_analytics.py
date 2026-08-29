"""Tests for the new real estate features: comparison, analytics, security."""

from __future__ import annotations

from realestate.analytics_dashboard import (
    AnalyticsService,
)
from realestate.application.services import LeadService, PropertyService
from realestate.comparison import (
    ComparisonSession,
    build_comparison_matrix,
    create_comparison_router,
)
from realestate.security import (
    CSP_DEFAULT,
    SECURITY_HEADERS,
    CSRFTokenService,
    RateLimitState,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Property Comparison Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestComparisonSession:
    def setup_method(self):
        self.session = ComparisonSession()

    def test_add_property(self):
        result = self.session.add("s1", "prop-1")
        assert result["success"]
        assert result["added"]
        assert result["count"] == 1

    def test_add_max_4(self):
        """Should not allow more than 4 properties."""
        for i in range(4):
            self.session.add("s2", f"prop-{i}")
        result = self.session.add("s2", "prop-5")
        assert not result["success"]  # max 4
        assert result["reason"] == "max_4"

    def test_add_duplicate(self):
        self.session.add("s3", "prop-1")
        result = self.session.add("s3", "prop-1")
        assert result["success"]
        assert not result["added"]  # already exists
        assert result["reason"] == "already_in_session"

    def test_remove_property(self):
        self.session.add("s4", "prop-1")
        self.session.add("s4", "prop-2")
        result = self.session.remove("s4", "prop-1")
        assert result["success"]
        assert "prop-2" in result["property_ids"]
        assert "prop-1" not in result["property_ids"]

    def test_get_session(self):
        self.session.add("s5", "prop-a")
        self.session.add("s5", "prop-b")
        ids = self.session.get("s5")
        assert len(ids) == 2
        assert "prop-a" in ids

    def test_clear_session(self):
        self.session.add("s6", "prop-1")
        self.session.clear("s6")
        assert self.session.get("s6") == []

    def test_isolation_between_sessions(self):
        self.session.add("s7", "prop-a")
        self.session.add("s8", "prop-b")
        assert len(self.session.get("s7")) == 1
        assert len(self.session.get("s8")) == 1


class TestComparisonMatrix:
    def setup_method(self):
        self.ps = PropertyService()
        self.p1 = self.ps.create_property(
            title="Luxury 3BHK", description="", property_type="apartment",
            price=15000000, city="Mumbai", locality="Bandra",
            owner_id="u1", bedrooms=3, bathrooms=3, carpet_area_sqft=1500,
        )
        self.p2 = self.ps.create_property(
            title="Budget 2BHK", description="", property_type="apartment",
            price=8000000, city="Mumbai", locality="Andheri",
            owner_id="u2", bedrooms=2, bathrooms=2, carpet_area_sqft=900,
        )

    def test_build_matrix_two_properties(self):
        matrix = build_comparison_matrix(self.ps, [self.p1.property_id, self.p2.property_id])
        assert matrix["count"] == 2
        assert len(matrix["properties"]) == 2
        assert "price" in matrix["matrix"]
        assert len(matrix["matrix"]["price"]) == 2

    def test_build_matrix_price_values(self):
        matrix = build_comparison_matrix(self.ps, [self.p1.property_id, self.p2.property_id])
        prices = matrix["matrix"]["price"]
        assert 15000000 in prices
        assert 8000000 in prices

    def test_build_matrix_bedrooms(self):
        matrix = build_comparison_matrix(self.ps, [self.p1.property_id, self.p2.property_id])
        bedrooms = matrix["matrix"]["bedrooms"]
        assert 3 in bedrooms
        assert 2 in bedrooms

    def test_build_matrix_includes_city(self):
        matrix = build_comparison_matrix(self.ps, [self.p1.property_id, self.p2.property_id])
        cities = matrix["matrix"]["city"]
        assert all(c == "Mumbai" for c in cities)

    def test_build_matrix_empty_ids(self):
        matrix = build_comparison_matrix(self.ps, [])
        assert matrix["count"] == 0
        assert matrix["properties"] == []

    def test_build_matrix_nonexistent_id(self):
        matrix = build_comparison_matrix(self.ps, ["nonexistent", self.p1.property_id])
        # Should skip nonexistent
        assert matrix["count"] == 1


class TestComparisonAPIRouter:
    def test_router_created(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        svc = PropertyService()
        app.include_router(create_comparison_router(property_service=svc))
        client = TestClient(app)

        # Add comparison
        resp = client.post("/api/realestate/compare/add?property_id=test-1&session_id=test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"]
        assert data["added"]

        # Check session
        resp = client.get("/api/realestate/compare/session?session_id=test")
        assert resp.status_code == 200
        assert "test-1" in resp.json()["property_ids"]

        # Clear
        resp = client.post("/api/realestate/compare/clear?session_id=test")
        assert resp.status_code == 200

    def test_comparison_matrix_api(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        svc = PropertyService()
        p = svc.create_property(
            title="Test", description="", property_type="apartment",
            price=5000000, city="Delhi", locality="", owner_id="u",
        )
        p2 = svc.create_property(
            title="Test 2", description="", property_type="apartment",
            price=7000000, city="Delhi", locality="", owner_id="u",
        )
        app.include_router(create_comparison_router(property_service=svc))
        client = TestClient(app)

        resp = client.get(f"/api/realestate/compare/matrix?property_ids={p.property_id},{p2.property_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

    def test_comparison_matrix_too_few(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        svc = PropertyService()
        p = svc.create_property(
            title="Test", description="", property_type="apartment",
            price=5000000, city="Delhi", locality="", owner_id="u",
        )
        app.include_router(create_comparison_router(property_service=svc))
        client = TestClient(app)

        resp = client.get(f"/api/realestate/compare/matrix?property_ids={p.property_id}")
        assert resp.status_code == 400  # Need at least 2


# ═══════════════════════════════════════════════════════════════════════════════
# Analytics Dashboard Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalyticsService:
    def setup_method(self):
        self.ps = PropertyService()
        self.ls = LeadService()
        self.svc = AnalyticsService(property_service=self.ps, lead_service=self.ls)

    def test_overview_empty(self):
        overview = self.svc.get_overview()
        assert overview.total_properties == 0
        assert overview.total_views == 0

    def test_overview_with_properties(self):
        self.ps.create_property(
            title="P1", description="", property_type="apartment",
            price=10000000, city="Mumbai", locality="", owner_id="u1",
        )
        self.ps.create_property(
            title="P2", description="", property_type="villa",
            price=25000000, city="Bangalore", locality="", owner_id="u2",
        )
        overview = self.svc.get_overview()
        assert overview.total_properties == 2
        assert overview.total_cities == 2
        assert overview.total_unique_owners == 2
        assert overview.avg_price > 0

    def test_lead_funnel_empty(self):
        funnel = self.svc.get_lead_funnel()
        assert funnel.total == 0
        assert funnel.conversion_rate == 0.0

    def test_lead_funnel_with_leads(self):
        lead = self.ls.create_lead("prop-1", "Rahul", "9876543210")
        self.ls.update_lead_status(lead.lead_id, "interested")
        self.ls.create_lead("prop-1", "Priya", "9876543211")

        funnel = self.svc.get_lead_funnel()
        assert funnel.total == 2
        assert funnel.interested == 1
        assert funnel.new == 1

    def test_city_breakdown(self):
        self.ps.create_property(
            title="P1", description="", property_type="apartment",
            price=10000000, city="Mumbai", locality="", owner_id="u1",
        )
        self.ps.create_property(
            title="P2", description="", property_type="apartment",
            price=8000000, city="Mumbai", locality="", owner_id="u2",
        )
        self.ps.create_property(
            title="P3", description="", property_type="villa",
            price=15000000, city="Bangalore", locality="", owner_id="u1",
        )
        cities = self.svc.get_city_breakdown()
        assert len(cities) == 2
        mumbai = [c for c in cities if c.city == "Mumbai"]
        assert len(mumbai) == 1
        assert mumbai[0].count == 2

    def test_property_type_distribution(self):
        self.ps.create_property(
            title="P1", description="", property_type="apartment",
            price=5000000, city="Delhi", locality="", owner_id="u1",
        )
        self.ps.create_property(
            title="P2", description="", property_type="apartment",
            price=6000000, city="Delhi", locality="", owner_id="u1",
        )
        self.ps.create_property(
            title="P3", description="", property_type="villa",
            price=15000000, city="Mumbai", locality="", owner_id="u1",
        )
        dist = self.svc.get_property_type_distribution()
        assert dist.get("apartment") == 2
        assert dist.get("villa") == 1

    def test_top_properties(self):
        for i in range(5):
            p = self.ps.create_property(
                title=f"P{i}", description="", property_type="apartment",
                price=5000000, city="Mumbai", locality="", owner_id="u1",
            )
            # Add some views
            for _ in range(i * 2):
                self.ps.record_view(p.property_id)

        top = self.svc.get_top_properties(3)
        assert len(top) <= 3
        # First should have most views
        assert top[0]["views"] >= top[-1]["views"]

    def test_stats_summary(self):
        self.ps.create_property(
            title="P1", description="", property_type="apartment",
            price=10000000, city="Mumbai", locality="", owner_id="u1",
        )
        summary = self.svc.get_stats_summary()
        assert "overview" in summary
        assert "lead_funnel" in summary
        assert "city_breakdown" in summary
        assert "property_types" in summary
        assert "top_properties" in summary
        assert summary["overview"]["total_properties"] == 1


class TestAnalyticsAPIRouter:
    def test_analytics_summary_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from realestate.analytics_dashboard import create_analytics_router
        from realestate.application.services import create_default_services

        app = FastAPI()
        svc = create_default_services()
        app.include_router(create_analytics_router(
            property_service=svc["property_service"],
            lead_service=svc["lead_service"],
        ))
        client = TestClient(app)

        resp = client.get("/api/realestate/analytics/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "overview" in data
        assert "lead_funnel" in data
        assert "city_breakdown" in data

    def test_analytics_overview_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from realestate.analytics_dashboard import create_analytics_router
        from realestate.application.services import create_default_services

        app = FastAPI()
        svc = create_default_services()
        app.include_router(create_analytics_router(
            property_service=svc["property_service"],
        ))
        client = TestClient(app)

        resp = client.get("/api/realestate/analytics/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert hasattr(data, "total_properties") or "total_properties" in data


# ═══════════════════════════════════════════════════════════════════════════════
# Security Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRateLimitState:
    def setup_method(self):
        self.rl = RateLimitState()

    def test_check_allows(self):
        assert self.rl.check("key1", 10, 60)

    def test_check_blocks(self):
        for _ in range(5):
            self.rl.check("key2", 5, 60)
        assert not self.rl.check("key2", 5, 60)

    def test_different_keys_independent(self):
        for _ in range(5):
            self.rl.check("key3", 5, 60)
        assert self.rl.check("key4", 5, 60)

    def test_remaining(self):
        self.rl.check("key5", 10, 60)
        rem = self.rl.remaining("key5", 10, 60)
        assert rem == 9

    def test_remaining_exceeded(self):
        for _ in range(10):
            self.rl.check("key6", 10, 60)
        rem = self.rl.remaining("key6", 10, 60)
        assert rem == 0

    def test_reset(self):
        for _ in range(5):
            self.rl.check("key7", 5, 60)
        self.rl.reset()
        assert self.rl.check("key7", 5, 60)

    def test_window_expiry(self):
        """Old entries should expire after the window."""
        import time as ttime
        # Manually add an old entry
        self.rl._buckets["key8"] = [ttime.time() - 120]  # 2 min ago
        assert self.rl.check("key8", 5, 60)  # Should allow since old entry expired


class TestCSRFTokenService:
    def setup_method(self):
        self.csrf = CSRFTokenService(secret="test-secret", expiry_seconds=3600)

    def test_generate_token(self):
        token = self.csrf.generate_token("session-1")
        assert "." in token
        parts = token.split(".")
        assert len(parts) == 2

    def test_validate_own_token(self):
        token = self.csrf.generate_token("session-2")
        assert self.csrf.validate_token(token, "session-2")

    def test_wrong_session(self):
        token = self.csrf.generate_token("session-3")
        assert not self.csrf.validate_token(token, "wrong-session")

    def test_replay_protection(self):
        token = self.csrf.generate_token("session-4")
        assert self.csrf.validate_token(token, "session-4")
        assert not self.csrf.validate_token(token, "session-4")  # Already used

    def test_tampered_token(self):
        token = self.csrf.generate_token("session-5")
        tampered = token[:-1] + "x"
        assert not self.csrf.validate_token(tampered, "session-5")

    def test_get_csrf_meta(self):
        meta = self.csrf.get_csrf_meta("session-6")
        assert "csrf_token" in meta
        assert "csrf_field" in meta
        assert 'type="hidden"' in meta["csrf_field"]


class TestSecurityHeaders:
    def test_headers_present(self):
        """Test that SECURITY_HEADERS constant has expected keys."""
        assert "X-Content-Type-Options" in SECURITY_HEADERS
        assert "X-Frame-Options" in SECURITY_HEADERS
        assert "Strict-Transport-Security" in SECURITY_HEADERS
        assert "Referrer-Policy" in SECURITY_HEADERS
        assert "Permissions-Policy" in SECURITY_HEADERS

    def test_x_frame_options_deny(self):
        assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"

    def test_hsts_enabled(self):
        assert "max-age=31536000" in SECURITY_HEADERS["Strict-Transport-Security"]
        assert "includeSubDomains" in SECURITY_HEADERS["Strict-Transport-Security"]

    def test_csp_includes_default_src(self):
        assert "default-src 'self'" in CSP_DEFAULT

    def test_csp_allows_inline_scripts(self):
        assert "unsafe-inline" in CSP_DEFAULT

    def test_csp_prevents_framing(self):
        assert "frame-ancestors 'none'" in CSP_DEFAULT

    def test_csp_restricts_form_action(self):
        assert "form-action 'self'" in CSP_DEFAULT


class TestRateLimitMiddleware:
    def test_middleware_allows_normal_requests(self):
        """Integration test verifying the middleware works with FastAPI."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from realestate.security import RateLimitMiddleware

        app = FastAPI()

        @app.get("/api/realestate/properties/search")
        async def search():
            return {"results": []}

        # Use custom exempt prefixes that don't include this endpoint
        app.add_middleware(
            RateLimitMiddleware,
            default_rate=50,
            default_window=60,
            exempt_prefixes={"/static"},
        )

        client = TestClient(app)
        resp = client.get("/api/realestate/properties/search")
        assert resp.status_code == 200
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers

    def test_rate_limit_headers_present(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from realestate.security import RateLimitMiddleware

        app = FastAPI()

        @app.get("/test")
        async def test():
            return {"ok": True}

        app.add_middleware(
            RateLimitMiddleware,
            default_rate=100,
            default_window=60,
        )

        client = TestClient(app)
        resp = client.get("/test")
        assert "X-RateLimit-Limit" in resp.headers
        assert resp.headers["X-RateLimit-Limit"] == "100"
