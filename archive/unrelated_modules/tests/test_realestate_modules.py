"""Tests for Tenant Portal, Admin Panel, and Saved Properties modules."""

from __future__ import annotations

from realestate.admin_panel import (
    AdminPanel,
    ModerationStatus,
    PlatformMetrics,
)
from realestate.saved_properties import SavedPropertiesService
from realestate.tenant_portal import (
    MaintenanceStatus,
    PaymentStatus,
    TenantPortal,
)

# ── Tenant Portal Tests ─────────────────────────────────────────────────────

class TestTenantPortal:
    def setup_method(self):
        self.portal = TenantPortal()

    def test_record_payment(self):
        payment = self.portal.record_payment(
            tenant_id="t1", property_id="p1", agreement_id="a1",
            amount=25000, due_date="2026-08-05", month_period="Aug 2026",
            payment_mode="UPI",
        )
        assert payment.payment_id is not None
        assert payment.amount == 25000
        assert payment.status == PaymentStatus.PAID
        assert payment.month_period == "Aug 2026"

    def test_get_tenant_payments(self):
        self.portal.record_payment("t1", "p1", "a1", 25000, "2026-08-05", "Aug 2026")
        self.portal.record_payment("t1", "p1", "a1", 25000, "2026-09-05", "Sep 2026")
        payments = self.portal.get_tenant_payments("t1")
        assert len(payments) == 2

    def test_payment_history_dict(self):
        self.portal.record_payment("t1", "p1", "a1", 25000, "2026-08-05", "Aug 2026")
        history = self.portal.get_payment_history("t1")
        assert len(history) == 1
        assert history[0]["amount"] == 25000.0
        assert history[0]["status"] == "paid"

    def test_submit_maintenance(self):
        req = self.portal.submit_maintenance_request(
            tenant_id="t1", property_id="p1",
            category="plumbing", description="Leaking pipe",
            priority="high",
        )
        assert req.request_id is not None
        assert req.category == "plumbing"
        assert req.priority.value == "high"
        assert req.status == MaintenanceStatus.SUBMITTED

    def test_submit_maintenance_emergency(self):
        req = self.portal.submit_maintenance_request(
            tenant_id="t1", property_id="p1",
            category="electrical", description="Power outage",
            priority="emergency",
        )
        assert req.priority.value == "emergency"

    def test_update_maintenance_status(self):
        req = self.portal.submit_maintenance_request("t1", "p1", "plumbing", "Leak")
        assert self.portal.update_maintenance_status(req.request_id, "in_progress")
        assert self.portal.update_maintenance_status(req.request_id, "resolved", "Fixed leak", 1500)
        updated = self.portal.get_tenant_requests("t1")[0]
        assert updated.status == MaintenanceStatus.RESOLVED
        assert updated.resolution_notes == "Fixed leak"
        assert updated.actual_cost == 1500

    def test_get_tenant_requests(self):
        self.portal.submit_maintenance_request("t1", "p1", "plumbing", "Issue 1")
        self.portal.submit_maintenance_request("t1", "p1", "electrical", "Issue 2")
        reqs = self.portal.get_tenant_requests("t1")
        assert len(reqs) == 2

    def test_maintenance_stats(self):
        r1 = self.portal.submit_maintenance_request("t1", "p1", "plumbing", "Leak")
        self.portal.submit_maintenance_request("t1", "p1", "electrical", "Power", priority="emergency")
        self.portal.update_maintenance_status(r1.request_id, "resolved")
        stats = self.portal.get_maintenance_stats("t1")
        assert stats["total"] == 2
        assert stats["resolved"] == 1
        assert stats["emergency"] == 1

    def test_get_stats(self):
        self.portal.record_payment("t1", "p1", "a1", 25000, "2026-08-05", "Aug 2026")
        self.portal.submit_maintenance_request("t1", "p1", "other", "Issue")
        stats = self.portal.get_stats()
        assert stats["total_payments"] == 1
        assert stats["total_maintenance_requests"] == 1
        assert stats["total_tenants"] == 1

    def test_singleton(self):
        from realestate.tenant_portal import get_tenant_portal
        tp1 = get_tenant_portal()
        tp2 = get_tenant_portal()
        assert tp1 is tp2

    def test_invalid_priority(self):
        req = self.portal.submit_maintenance_request("t1", "p1", "other", "Test", priority="invalid")
        assert req.priority.value == "medium"  # Falls back


# ── Admin Panel Tests ───────────────────────────────────────────────────────

class TestAdminPanel:
    def setup_method(self):
        self.panel = AdminPanel()

    def test_add_to_moderation(self):
        self.panel.add_to_moderation("prop-1")
        queue = self.panel.get_moderation_queue()
        assert len(queue) == 1
        assert queue[0]["status"] == "pending"

    def test_approve_listing(self):
        self.panel.add_to_moderation("prop-1")
        assert self.panel.approve_listing("prop-1")
        queue = self.panel.get_moderation_queue()
        assert queue[0]["status"] == "approved"

    def test_reject_listing(self):
        self.panel.add_to_moderation("prop-1")
        assert self.panel.reject_listing("prop-1")
        assert self.panel.get_moderation_count("rejected") == 1

    def test_moderation_count(self):
        self.panel.add_to_moderation("p1")
        self.panel.add_to_moderation("p2")
        self.panel.approve_listing("p1")
        assert self.panel.get_moderation_count() == 2
        assert self.panel.get_moderation_count("approved") == 1
        assert self.panel.get_moderation_count("pending") == 1

    def test_report_listing(self):
        report = self.panel.report_listing("prop-1", "user-1", "spam", "Fake listing")
        assert report.report_id is not None
        assert report.reason.value == "spam"
        assert report.status == ModerationStatus.PENDING

    def test_resolve_report_remove(self):
        report = self.panel.report_listing("prop-1", "user-1", "fraud", "Scam")
        assert self.panel.resolve_report(report.report_id, "removed")
        assert report.status == ModerationStatus.BANNED
        queue_status = self.panel.get_moderation_queue()[0]["status"]
        assert queue_status == "rejected"  # Auto-rejected after removal

    def test_resolve_report_dismiss(self):
        report = self.panel.report_listing("prop-1", "user-1", "other", "Test")
        assert self.panel.resolve_report(report.report_id, "nothing")
        assert report.status == ModerationStatus.APPROVED

    def test_get_reported_listings(self):
        self.panel.report_listing("p1", "u1", "spam", "Bad")
        self.panel.report_listing("p2", "u2", "fraud", "Scam")
        reports = self.panel.get_reported_listings()
        assert len(reports) == 2

    def test_kyc_submit(self):
        assert self.panel.submit_kyc("broker-1")
        assert self.panel.get_kyc_status("broker-1") == "pending"

    def test_kyc_verify(self):
        self.panel.submit_kyc("broker-1")
        assert self.panel.verify_kyc("broker-1")
        assert self.panel.get_kyc_status("broker-1") == "verified"

    def test_kyc_reject(self):
        self.panel.submit_kyc("broker-1")
        assert self.panel.reject_kyc("broker-1")
        assert self.panel.get_kyc_status("broker-1") == "rejected"

    def test_kyc_double_verify(self):
        self.panel.submit_kyc("broker-1")
        self.panel.verify_kyc("broker-1")
        assert not self.panel.submit_kyc("broker-1")  # Already verified

    def test_kyc_queue(self):
        self.panel.submit_kyc("b1")
        self.panel.submit_kyc("b2")
        self.panel.verify_kyc("b1")
        queue = self.panel.get_kyc_queue()
        assert len(queue) == 1
        assert queue[0]["user_id"] == "b2"

    def test_platform_metrics_generation(self):
        metrics = self.panel.generate_metrics()
        assert isinstance(metrics, PlatformMetrics)
        assert metrics.total_listings == 0

    def test_get_stats(self):
        self.panel.add_to_moderation("p1")
        self.panel.report_listing("p2", "u1", "spam", "Bad")
        self.panel.submit_kyc("b1")
        stats = self.panel.get_stats()
        assert stats["moderation_queue"] == 2
        assert stats["pending_reports"] == 1
        assert stats["kyc_pending"] == 1

    def test_singleton(self):
        from realestate.admin_panel import get_admin_panel
        ap1 = get_admin_panel()
        ap2 = get_admin_panel()
        assert ap1 is ap2

    def test_daily_metrics_snapshot(self):
        metrics = PlatformMetrics(total_listings=100, active_users=50)
        self.panel.save_daily_snapshot(metrics)
        daily = self.panel.get_daily_metrics(days=1)
        assert len(daily) >= 1
        assert daily[0]["total_listings"] == 100


# ── Saved Properties Tests ──────────────────────────────────────────────────

class TestSavedProperties:
    def setup_method(self):
        self.svc = SavedPropertiesService()

    def test_save_property(self):
        assert self.svc.save_property("user-1", "prop-1")
        assert self.svc.get_saved_count("user-1") == 1

    def test_save_duplicate(self):
        assert self.svc.save_property("user-1", "prop-1")
        assert not self.svc.save_property("user-1", "prop-1")  # Already saved

    def test_unsave_property(self):
        self.svc.save_property("user-1", "prop-1")
        assert self.svc.unsave_property("user-1", "prop-1")
        assert self.svc.get_saved_count("user-1") == 0

    def test_unsave_nonexistent(self):
        assert not self.svc.unsave_property("user-1", "nonexistent")

    def test_is_saved(self):
        self.svc.save_property("user-1", "prop-1")
        assert self.svc.is_saved("user-1", "prop-1")
        assert not self.svc.is_saved("user-1", "prop-2")
        assert not self.svc.is_saved("user-2", "prop-1")

    def test_get_saved_properties(self):
        self.svc.save_property("user-1", "prop-1")
        self.svc.save_property("user-1", "prop-2")
        saved = self.svc.get_saved_properties("user-1")
        assert len(saved) == 2
        assert saved[0]["property_id"] in ("prop-1", "prop-2")

    def test_get_saved_properties_empty(self):
        assert self.svc.get_saved_properties("user-none") == []

    def test_get_saved_count(self):
        self.svc.save_property("u1", "p1")
        self.svc.save_property("u1", "p2")
        self.svc.save_property("u1", "p3")
        assert self.svc.get_saved_count("u1") == 3
        assert self.svc.get_saved_count("u2") == 0

    def test_get_stats(self):
        self.svc.save_property("u1", "p1")
        self.svc.save_property("u1", "p2")
        self.svc.save_property("u2", "p3")
        stats = self.svc.get_stats()
        assert stats["total_users_with_saved"] == 2
        assert stats["total_saved_properties"] == 3

    def test_get_property_details_no_service(self):
        self.svc.save_property("u1", "p1")
        details = self.svc.get_property_details("u1", None)
        assert len(details) == 1
        assert details[0]["property_id"] == "p1"

    def test_singleton(self):
        from realestate.saved_properties import get_saved_properties_service
        s1 = get_saved_properties_service()
        s2 = get_saved_properties_service()
        assert s1 is s2
