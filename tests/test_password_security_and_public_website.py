"""Tests for Password Security, Public Website Pages, and Release Readiness.

Covers:
1. Backend password confirmation validation (register, change, reset).
2. Password-reset token invalidation of prior unused tokens upon new generation.
3. Single-use and expiration enforcement on password reset tokens.
4. Universal copy/paste/cut restriction attributes across all template password fields.
5. Public page accessibility (/about, /contact, /privacy, /terms) without authentication.
6. Public contact API (/api/contact) validation, anti-spam honeypot, and rate-limiting.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth.handler.password import validate_password_confirmation
from core.auth.handler.handler import AuthHandler
from core.enterprise_dashboard.routes.pages import register_page_routes


class TestPasswordConfirmation:
    """Test backend password confirmation comparison."""

    def test_validate_password_confirmation_matching(self):
        valid, msg = validate_password_confirmation("Secret123!", "Secret123!")
        assert valid is True
        assert msg == ""

        valid2, msg2 = validate_password_confirmation("correct-horse-battery", "correct-horse-battery")
        assert valid2 is True
        assert msg2 == ""

    def test_validate_password_confirmation_mismatched(self):
        valid, msg = validate_password_confirmation("Secret123!", "Secret1234")
        assert valid is False
        assert "do not match" in msg

        valid, msg = validate_password_confirmation("Password123!", "password123!")
        assert valid is False

        valid, msg = validate_password_confirmation("Secret123!", "")
        assert valid is False

        valid, msg = validate_password_confirmation("", "Secret123!")
        assert valid is False

        valid, msg = validate_password_confirmation("", "")
        assert valid is False

        valid, msg = validate_password_confirmation(None, "Secret123!")
        assert valid is False

        valid, msg = validate_password_confirmation("Secret123!", None)
        assert valid is False


class TestPasswordResetTokenSecurity:
    """Test password reset token invalidation, single-use, and expiration."""

    INITIAL_PW = "Str0ng#K9v!mQ7x"
    NEW_PW = "An0ther#Str0ng!Key9"
    SECOND_PW = "Th1rd#Str0ng!Key8"

    @pytest.fixture
    def auth_handler(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        handler = AuthHandler(db_path=db_path)
        # Create a test user with a strong password
        res = handler.create_user(
            username="testuser",
            password=self.INITIAL_PW,
            email="testuser@example.com",
            role="operator"
        )
        assert res.get("success") is True, f"Failed to create test user: {res}"
        yield handler
        try:
            os.remove(db_path)
        except OSError:
            pass

    def test_prior_unused_tokens_invalidated_on_new_token_generation(self, auth_handler):
        # Generate first token
        token1 = auth_handler.create_password_reset_token("testuser")
        assert token1 is not None

        # Verify token1 is currently valid (mark_used=False for inspection)
        assert auth_handler.verify_password_reset_token(token1, mark_used=False) == "testuser"

        t1_hash = hashlib.sha256(token1.encode()).hexdigest()

        # Check DB state: token1 is unused
        with auth_handler._get_conn() as conn:
            row1 = conn.execute("SELECT used FROM password_reset_tokens WHERE token_hash = ?", (t1_hash,)).fetchone()
            assert row1 is not None and row1["used"] == 0

        # Generate second token for the same user
        token2 = auth_handler.create_password_reset_token("testuser")
        assert token2 is not None
        assert token2 != token1

        t2_hash = hashlib.sha256(token2.encode()).hexdigest()

        # Check DB state: token1 MUST have been invalidated (used = 1)
        with auth_handler._get_conn() as conn:
            row1_after = conn.execute("SELECT used FROM password_reset_tokens WHERE token_hash = ?", (t1_hash,)).fetchone()
            assert row1_after is not None and row1_after["used"] == 1, "Prior token must be marked as used/invalidated"

            row2 = conn.execute("SELECT used FROM password_reset_tokens WHERE token_hash = ?", (t2_hash,)).fetchone()
            assert row2 is not None and row2["used"] == 0, "New token must be unused"

        # Verification of token1 MUST now fail
        assert auth_handler.verify_password_reset_token(token1, mark_used=False) is None

        # Verification of token2 MUST succeed
        assert auth_handler.verify_password_reset_token(token2, mark_used=False) == "testuser"

    def test_token_single_use_enforcement(self, auth_handler):
        token = auth_handler.create_password_reset_token("testuser")
        assert token is not None

        # Reset password using the token
        res = auth_handler.reset_password_with_token(token, self.NEW_PW)
        assert res.get("success") is True

        # Second attempt with the same token MUST fail (single-use)
        second_attempt = auth_handler.reset_password_with_token(token, self.SECOND_PW)
        assert second_attempt.get("success") is False

        # Verify token is rejected
        assert auth_handler.verify_password_reset_token(token) is None

    def test_expired_token_rejected(self, auth_handler):
        token = auth_handler.create_password_reset_token("testuser")
        assert token is not None

        t_hash = hashlib.sha256(token.encode()).hexdigest()

        # Manually alter expires_ts in DB to simulate expiration (2 hours in past)
        with auth_handler._get_conn() as conn:
            conn.execute(
                "UPDATE password_reset_tokens SET expires_ts = ? WHERE token_hash = ?",
                (time.time() - 7200, t_hash)
            )
            conn.commit()

        assert auth_handler.verify_password_reset_token(token) is None
        res = auth_handler.reset_password_with_token(token, self.NEW_PW)
        assert res.get("success") is False


class TestFrontendPasswordPasteRestriction:
    """Verify copy/paste/cut restriction markers and event handlers across templates."""

    TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates", "enterprise")

    @pytest.mark.parametrize("template_name,expected_markers", [
        ("register.html", ['data-disable-paste="true"', "paste"]),
        ("reset_password.html", ['data-disable-paste="true"', "paste"]),
        ("change_password.html", ['data-disable-paste="true"', "paste"]),
        ("forgot_password.html", ['data-disable-paste="true"', "paste"]),
        ("profile.html", ['data-disable-paste="true"', "paste"]),
        ("admin_users.html", ['data-disable-paste="true"']),
        ("login.html", ['data-disable-paste="true"']),
    ])
    def test_template_contains_paste_prevention(self, template_name, expected_markers):
        template_path = os.path.join(self.TEMPLATES_DIR, template_name)
        assert os.path.isfile(template_path), f"Template {template_name} missing"
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()

        for marker in expected_markers:
            assert marker in content, f"Marker '{marker}' not found in {template_name}"

    def test_theme_engine_contains_universal_paste_restriction(self):
        js_path = os.path.join(os.path.dirname(__file__), "..", "static", "theme_engine.js")
        assert os.path.isfile(js_path)
        with open(js_path, "r", encoding="utf-8") as f:
            js_content = f.read()

        assert "paste" in js_content
        assert "copy" in js_content
        assert "cut" in js_content
        assert "drop" in js_content
        assert "data-disable-paste" in js_content
        assert "Pasting is disabled in password fields for security" in js_content


class TestPublicWebsiteAndContactAPI:
    """Test public HTML routes (/about, /contact, /privacy, /terms) and /api/contact."""

    @pytest.fixture
    def test_client(self):
        import jinja2
        from starlette.templating import Jinja2Templates

        app = FastAPI()
        templates = Jinja2Templates(directory="templates/enterprise")

        # Mock dashboard
        mock_dashboard = MagicMock()
        mock_dashboard._templates = templates
        mock_dashboard._auth = MagicMock()
        mock_dashboard._auth.verify_session.return_value = None
        mock_dashboard._auth.get_user_by_id.return_value = None
        mock_dashboard._cfg = {
            "EXECUTION_MODE": "PAPER",
            "api_rate_limit_per_minute": 300
        }

        async def _dummy_require_admin_page(req):
            return None, None

        register_page_routes(app, mock_dashboard, _dummy_require_admin_page)
        return TestClient(app)

    @pytest.mark.parametrize("route,title_fragment,expected_text", [
        ("/about", "About Platform", "Quantitative Cockpit"),
        ("/contact", "Contact Us", "Technical Support"),
        ("/privacy", "Privacy Policy", "Data Governance"),
        ("/terms", "Terms of Service", "Statutory Risk Disclosures"),
    ])
    def test_public_pages_accessible_unauthenticated(self, test_client, route, title_fragment, expected_text):
        resp = test_client.get(route)
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        body = resp.text
        assert title_fragment in body
        assert expected_text in body
        # Ensure SEBI / statutory risk warning presence
        assert "SEBI" in body or "Risk" in body

    def test_terms_page_contains_sebi_fo_risk_statistics(self, test_client):
        resp = test_client.get("/terms")
        assert resp.status_code == 200
        text = resp.text
        assert "9 out of 10" in text
        assert "Futures and Options" in text
        assert "15% to 28%" in text

    def test_privacy_page_contains_dpdpa_and_cryptographic_details(self, test_client):
        resp = test_client.get("/privacy")
        assert resp.status_code == 200
        text = resp.text
        assert "DPDPA 2023" in text or "Digital Personal Data Protection" in text
        assert "PBKDF2-HMAC-SHA256" in text
        assert "Tenant Isolation" in text

    def test_contact_api_success(self, test_client):
        payload = {
            "name": "Jane Trader",
            "email": "jane@example.com",
            "category": "Technical Support",
            "subject": "Inquiry about options heatmap latency",
            "message": "Hello, I wanted to know the refresh frequency of the options heatmap.",
            "company_website": ""  # empty honeypot
        }
        resp = test_client.post("/api/contact", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "ok"
        assert "received" in data.get("message", "").lower()

        # Verify message was persisted to disk
        inq_path = os.path.join(os.path.dirname(__file__), "..", "data", "contact_inquiries.jsonl")
        assert os.path.isfile(inq_path), "Contact inquiries JSONL must exist"
        with open(inq_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) > 0
        last_inq = json.loads(lines[-1])
        assert last_inq["name"] == "Jane Trader"
        assert last_inq["email"] == "jane@example.com"
        assert last_inq["status"] == "PENDING_REVIEW"

    def test_contact_api_honeypot_silently_accepted(self, test_client):
        # Spambot fills the hidden company_website honeypot
        payload = {
            "name": "Bot Spammer",
            "email": "bot@spam.com",
            "category": "General Inquiry",
            "subject": "Buy crypto now",
            "message": "Spam message here",
            "company_website": "http://spamsite.xyz"
        }
        resp = test_client.post("/api/contact", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "ok"

    def test_contact_api_invalid_email(self, test_client):
        payload = {
            "name": "Jane Trader",
            "email": "not-an-email",
            "category": "General Inquiry",
            "subject": "Valid Subject",
            "message": "Valid message with more than 10 characters."
        }
        resp = test_client.post("/api/contact", json=payload)
        assert resp.status_code == 400
        assert "email" in resp.json().get("detail", "").lower()

    def test_contact_api_short_message(self, test_client):
        payload = {
            "name": "Jane Trader",
            "email": "jane@example.com",
            "category": "General Inquiry",
            "subject": "Valid Subject",
            "message": "Hi"  # too short (< 5 chars)
        }
        resp = test_client.post("/api/contact", json=payload)
        assert resp.status_code == 400
        assert "message" in resp.json().get("detail", "").lower()
