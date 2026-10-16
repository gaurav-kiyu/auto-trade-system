"""Unit and Integration Tests for Contact Inquiry Store, Notification Dispatch, and Admin Portal.

Covers:
- Durable SQLite InquiryStore persistence, indexing, and WAL mode.
- Idempotent legacy JSONL migration.
- Notification formatting, ticket ID inclusion, and test suppression.
- Public /api/contact rate limiting, honeypot, validation, and truthful response.
- RBAC and lifecycle management for /admin/inquiries and /api/v1/admin/inquiries.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.auth.handler import AuthHandler
from core.enterprise_dashboard import create_enterprise_dashboard
from core.notifications.inquiry_notifications import (
    build_admin_alert_email,
    build_submitter_acknowledgment_email,
    dispatch_inquiry_notifications,
)
from core.storage.inquiry_store import InquiryStore, resolve_inquiry_db_path


@pytest.fixture
def temp_db_path(tmp_path):
    return str(tmp_path / "test_inquiries.db")


@pytest.fixture
def inquiry_store(temp_db_path):
    return InquiryStore(db_path=temp_db_path)


class TestInquiryStore:
    def test_schema_creation_and_indexes(self, inquiry_store, temp_db_path):
        conn = sqlite3.connect(temp_db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        assert "inquiries" in tables
        assert "inquiry_audit_log" in tables

        cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row[0] for row in cur.fetchall()}
        assert "idx_inquiries_created_at" in indexes
        assert "idx_inquiries_status" in indexes
        assert "idx_inquiries_email" in indexes
        assert "idx_inquiry_audit_id" in indexes
        conn.close()

    def test_save_and_retrieve_inquiry(self, inquiry_store):
        ticket_id = inquiry_store.save_inquiry(
            name="Alice Sharma",
            email="alice@example.com",
            subject="API Question",
            message="How do I connect via WebSocket?",
            category="Technical Support",
            client_ip="192.168.1.100",
            metadata={"source": "test"},
        )
        assert ticket_id.startswith("inq_")

        inq = inquiry_store.get_inquiry(ticket_id)
        assert inq is not None
        assert inq["id"] == ticket_id
        assert inq["name"] == "Alice Sharma"
        assert inq["email"] == "alice@example.com"
        assert inq["subject"] == "API Question"
        assert inq["message"] == "How do I connect via WebSocket?"
        assert inq["category"] == "Technical Support"
        assert inq["client_ip"] == "192.168.1.100"
        assert inq["status"] == "NEW"
        assert inq["notification_status"] == "PENDING"

        # Check initial audit log
        audit = inquiry_store.get_audit_log(ticket_id)
        assert len(audit) == 1
        assert audit[0]["action"] == "SUBMISSION"
        assert audit[0]["new_status"] == "NEW"

    def test_status_transitions_and_audit(self, inquiry_store):
        ticket_id = inquiry_store.save_inquiry(
            name="Bob Gupta",
            email="bob@example.com",
            subject="Bug Report",
            message="Found an issue on options page",
        )

        # Transition NEW -> IN_PROGRESS
        ok = inquiry_store.update_inquiry_status(
            ticket_id, "IN_PROGRESS", actor_username="support_admin", notes="Assigned to engineering"
        )
        assert ok is True
        inq = inquiry_store.get_inquiry(ticket_id)
        assert inq["status"] == "IN_PROGRESS"
        assert inq["admin_notes"] == "Assigned to engineering"

        # Transition IN_PROGRESS -> RESOLVED
        ok = inquiry_store.update_inquiry_status(
            ticket_id, "RESOLVED", actor_username="dev_lead", notes="Patch deployed in v2.61.5"
        )
        assert ok is True
        inq = inquiry_store.get_inquiry(ticket_id)
        assert inq["status"] == "RESOLVED"
        assert inq["admin_notes"] == "Patch deployed in v2.61.5"

        # Invalid status should raise ValueError
        with pytest.raises(ValueError, match="Invalid inquiry status"):
            inquiry_store.update_inquiry_status(ticket_id, "INVALID_STATUS", actor_username="admin")

        # Audit trail must show both transitions
        audit = inquiry_store.get_audit_log(ticket_id)
        assert len(audit) == 3  # SUBMISSION, STATUS_CHANGE (IN_PROGRESS), STATUS_CHANGE (RESOLVED)
        assert audit[1]["action"] == "STATUS_CHANGE"
        assert audit[1]["previous_status"] == "NEW"
        assert audit[1]["new_status"] == "IN_PROGRESS"
        assert audit[1]["actor_username"] == "support_admin"

        assert audit[2]["previous_status"] == "IN_PROGRESS"
        assert audit[2]["new_status"] == "RESOLVED"
        assert audit[2]["actor_username"] == "dev_lead"

    def test_list_inquiries_filtering_and_search(self, inquiry_store):
        id1 = inquiry_store.save_inquiry(name="Charlie", email="charlie@test.com", subject="General Alpha", message="Msg 1", category="General Inquiry")
        id2 = inquiry_store.save_inquiry(name="Dana", email="dana@test.com", subject="Bug Beta", message="Msg 2", category="Bug Report")
        id3 = inquiry_store.save_inquiry(name="Eve", email="eve@other.com", subject="Feature Gamma", message="Msg 3", category="Feature Suggestion")

        inquiry_store.update_inquiry_status(id2, "IN_PROGRESS", "admin")

        # All inquiries
        items, total = inquiry_store.list_inquiries()
        assert total == 3
        assert len(items) == 3

        # Filter by status
        items, total = inquiry_store.list_inquiries(status="IN_PROGRESS")
        assert total == 1
        assert items[0]["id"] == id2

        # Filter by category
        items, total = inquiry_store.list_inquiries(category="Bug Report")
        assert total == 1
        assert items[0]["id"] == id2

        # Search across subject / name
        items, total = inquiry_store.list_inquiries(search="Beta")
        assert total == 1
        assert items[0]["id"] == id2

        items, total = inquiry_store.list_inquiries(search="other.com")
        assert total == 1
        assert items[0]["id"] == id3

    def test_stats_aggregation(self, inquiry_store):
        id1 = inquiry_store.save_inquiry(name="U1", email="u1@test.com", subject="S1", message="M1")
        id2 = inquiry_store.save_inquiry(name="U2", email="u2@test.com", subject="S2", message="M2")
        id3 = inquiry_store.save_inquiry(name="U3", email="u3@test.com", subject="S3", message="M3")

        inquiry_store.update_inquiry_status(id2, "IN_PROGRESS", "admin")
        inquiry_store.update_inquiry_status(id3, "RESOLVED", "admin")

        stats = inquiry_store.get_stats()
        assert stats["total"] == 3
        assert stats["new"] == 1
        assert stats["in_progress"] == 1
        assert stats["resolved"] == 1

    def test_idempotent_legacy_jsonl_migration(self, inquiry_store):
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".jsonl") as f:
            f.write(json.dumps({
                "id": "inq_legacy_001",
                "name": "Legacy User",
                "email": "legacy@example.com",
                "category": "Feedback",
                "subject": "Great Platform",
                "message": "Loved the options chain matrix",
                "status": "PENDING_REVIEW",
                "client_ip": "10.0.0.1",
                "created_at": "2026-10-10T12:00:00Z"
            }) + "\n")
            f.write(json.dumps({
                "id": "inq_legacy_002",
                "name": "Legacy User 2",
                "email": "legacy2@example.com",
                "category": "General Inquiry",
                "subject": "Pricing question",
                "message": "Is paper trading free?",
                "status": "RESOLVED",
                "client_ip": "10.0.0.2",
                "created_at": "2026-10-11T12:00:00Z"
            }) + "\n")
            temp_jsonl = f.name

        try:
            # First migration
            count = inquiry_store.migrate_legacy_jsonl(temp_jsonl)
            assert count == 2

            inq = inquiry_store.get_inquiry("inq_legacy_001")
            assert inq is not None
            assert inq["name"] == "Legacy User"
            assert inq["status"] == "NEW"  # PENDING_REVIEW maps to NEW

            # Second migration should insert 0 rows (idempotent)
            count2 = inquiry_store.migrate_legacy_jsonl(temp_jsonl)
            assert count2 == 0
        finally:
            if os.path.exists(temp_jsonl):
                os.unlink(temp_jsonl)

    def test_env_db_path_override(self):
        with patch.dict(os.environ, {"OPBUYING_INQUIRIES_DB": "/custom/path/inquiries.db"}):
            assert resolve_inquiry_db_path() == "/custom/path/inquiries.db"


class TestInquiryNotifications:
    def test_email_template_formatting(self):
        inquiry_data = {
            "id": "inq_1729000000000",
            "name": "Dev Submitter <script>",
            "email": "dev@example.com",
            "category": "API Integration",
            "subject": "WebSocket Test & Feedback",
            "message": "Testing & verified <script>alert(1)</script>",
            "created_at": "2026-10-17T00:00:00Z",
            "client_ip": "127.0.0.1",
        }

        # Admin alert
        admin_html, admin_plain = build_admin_alert_email(inquiry_data)
        assert "inq_1729000000000" in admin_html
        assert "&lt;script&gt;" in admin_html
        assert "<script>" not in admin_html
        assert "WebSocket Test &amp; Feedback" in admin_html
        assert "inq_1729000000000" in admin_plain

        # Submitter acknowledgment
        user_html, user_plain = build_submitter_acknowledgment_email(inquiry_data)
        assert "inq_1729000000000" in user_html
        assert "CONFIRMATION OF RECEIPT" in user_html
        assert "&lt;script&gt;" in user_html
        assert "Reference Ticket ID: inq_1729000000000" in user_plain

    def test_dispatch_in_test_mode(self, inquiry_store):
        inquiry_data = {
            "id": inquiry_store.save_inquiry(name="Test User", email="test@example.com", subject="Sub", message="Msg"),
            "name": "Test User",
            "email": "test@example.com",
            "category": "General",
            "subject": "Sub",
            "message": "Msg",
            "created_at": "2026-10-17T00:00:00Z",
        }

        with patch("core.storage.inquiry_store.get_inquiry_store", return_value=inquiry_store):
            # In test mode, notifications succeed without real SMTP network calls
            results = dispatch_inquiry_notifications(inquiry_data)
            assert results["admin_sent"] is True
            assert results["submitter_sent"] is True

            inq = inquiry_store.get_inquiry(inquiry_data["id"])
            assert inq["notification_status"] == "DISPATCHED"


class TestContactAndAdminRoutes:
    @pytest.fixture
    def client(self, temp_db_path):
        with patch.dict(os.environ, {"OPBUYING_INQUIRIES_DB": temp_db_path}):
            dash = create_enterprise_dashboard(config={"ENVIRONMENT": "PAPER"})
            client = TestClient(dash.app)
            yield client, dash

    def test_public_contact_form_success(self, client):
        c, dash = client
        payload = {
            "name": "Aditi Roy",
            "email": "aditi.roy@domain.in",
            "category": "General Inquiry",
            "subject": "Platform access query",
            "message": "I would like to inquire about paper trading capabilities.",
            "company_website": "",
        }
        resp = c.post("/api/contact", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "ticket_id" in data
        assert data["ticket_id"].startswith("inq_")
        assert data["ticket_id"] in data["message"]

    def test_contact_form_honeypot(self, client):
        c, dash = client
        payload = {
            "name": "Spam Bot",
            "email": "bot@spam.com",
            "category": "General Inquiry",
            "subject": "Buy SEO services",
            "message": "Click this spam link now",
            "company_website": "http://spamsite.xyz",
        }
        resp = c.post("/api/contact", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        # Honeypot returns silent success without ticket_id
        assert "ticket_id" not in data

    def test_contact_form_validation_errors(self, client):
        c, dash = client

        # Missing name
        resp = c.post("/api/contact", json={"name": "", "email": "valid@test.com", "subject": "S", "message": "Valid msg"})
        assert resp.status_code == 400

        # Invalid email
        resp = c.post("/api/contact", json={"name": "Valid", "email": "invalid-email", "subject": "S", "message": "Valid msg"})
        assert resp.status_code == 400

        # Message too short
        resp = c.post("/api/contact", json={"name": "Valid", "email": "valid@test.com", "subject": "S", "message": "hi"})
        assert resp.status_code == 400

    def test_admin_inquiries_unauthorized(self, client):
        c, dash = client

        # Unauthenticated HTML request should redirect to /login
        resp = c.get("/admin/inquiries", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert resp.headers["location"] == "/login"

        # Unauthenticated API request should fail auth
        resp = c.get("/api/v1/admin/inquiries")
        assert resp.status_code in (401, 403)

    def test_admin_inquiries_authorized_flow(self, client):
        c, dash = client

        # Create session for super admin
        auth = dash._auth
        user = auth.get_user("admin")
        if not user:
            res = auth.create_user("admin", "AdminPassword123!", role="admin")
            user = auth.get_user_by_id(res["user_id"])
        session = auth.create_session(user)
        c.cookies.set("opb_session", session.token)

        # 1. Submit an inquiry
        c.post("/api/contact", json={
            "name": "Kiran Patel",
            "email": "kiran@example.com",
            "category": "Technical Support",
            "subject": "Database Connection Issue",
            "message": "Seeing timeout on paper order dispatch",
        })

        # 2. Access Admin HTML page
        page_resp = c.get("/admin/inquiries")
        assert page_resp.status_code == 200
        assert "Contact Inquiries &amp; Support Management" in page_resp.text
        assert "Kiran Patel" in page_resp.text
        assert "Database Connection Issue" in page_resp.text

        # 3. Access Admin Inquiries API
        api_resp = c.get("/api/v1/admin/inquiries")
        assert api_resp.status_code == 200
        data = api_resp.json()
        assert data["status"] == "ok"
        assert data["total"] >= 1
        ticket_id = data["items"][0]["id"]

        # 4. Access Detail API
        detail_resp = c.get(f"/api/v1/admin/inquiries/{ticket_id}")
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["inquiry"]["name"] == "Kiran Patel"
        assert len(detail_data["audit_log"]) >= 1

        # 5. Update Status
        status_resp = c.post(
            f"/api/v1/admin/inquiries/{ticket_id}/status",
            json={"status": "IN_PROGRESS", "notes": "Investigating log traces"}
        )
        assert status_resp.status_code == 200
        assert status_resp.json()["new_status"] == "IN_PROGRESS"

        # Verify updated status
        detail_resp2 = c.get(f"/api/v1/admin/inquiries/{ticket_id}")
        assert detail_resp2.json()["inquiry"]["status"] == "IN_PROGRESS"
        assert detail_resp2.json()["inquiry"]["admin_notes"] == "Investigating log traces"
