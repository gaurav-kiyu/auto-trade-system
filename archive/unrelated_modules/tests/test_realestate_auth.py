"""Tests for the OAuth authentication service."""

from __future__ import annotations

import time

from realestate.auth_service import (
    OAUTH_CONFIG,
    AuthService,
    GoogleOAuthVerifier,
    JWTManager,
    UserSession,
    get_auth_service,
)

# ═══════════════════════════════════════════════════════════════════════════════
# JWT Manager Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestJWTManager:
    def setup_method(self):
        self.jwt = JWTManager()

    def test_create_session(self):
        session = self.jwt.create_session(
            email="test@example.com",
            name="Test User",
            role="buyer",
        )
        assert session.email == "test@example.com"
        assert session.name == "Test User"
        assert session.role == "buyer"
        assert session.token is not None
        assert len(session.token) > 10

    def test_validate_valid_token(self):
        session = self.jwt.create_session("a@b.com", "Alice", role="broker")
        validated = self.jwt.validate_token(session.token)
        assert validated is not None
        assert validated.email == "a@b.com"
        assert validated.role == "broker"

    def test_validate_invalid_token(self):
        assert self.jwt.validate_token("invalid-token") is None

    def test_revoke_token(self):
        session = self.jwt.create_session("b@c.com", "Bob")
        assert self.jwt.revoke_token(session.token)
        assert self.jwt.validate_token(session.token) is None

    def test_expired_token(self):
        """Tokens should expire after their validity period."""
        # Create a JWTManager with short expiry
        from realestate.auth_service import OAUTH_CONFIG
        orig_expiry = OAUTH_CONFIG["jwt_expiry_hours"]
        try:
            OAUTH_CONFIG["jwt_expiry_hours"] = 0  # Expires immediately
            jwt2 = JWTManager()
            session = jwt2.create_session("c@d.com", "Carol")
            # The JWTManager uses its own expiry from OAUTH_CONFIG
            # Setting session expiry to past
            session.expires_at = time.time() - 1
            assert jwt2.validate_token(session.token) is None
        finally:
            OAUTH_CONFIG["jwt_expiry_hours"] = orig_expiry

    def test_token_structure(self):
        """JWT token should have header.payload.signature structure."""
        session = self.jwt.create_session("d@e.com", "Dave")
        parts = session.token.split(".")
        assert len(parts) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Auth Service Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthService:
    def setup_method(self):
        self.svc = AuthService()

    def test_guest_login(self):
        session = self.svc.login_as_guest("Test Guest")
        assert session.name == "Test Guest"
        assert session.role == "buyer"
        assert "guest" in session.email

    def test_guest_login_default_role(self):
        session = self.svc.login_as_guest()
        assert session.name == "Guest"

    def test_logout(self):
        session = self.svc.login_as_guest("Logout Test")
        assert self.svc.logout(session.token)
        assert self.svc.get_session(session.token) is None

    def test_get_session_valid(self):
        session = self.svc.login_as_guest("Session Test")
        result = self.svc.get_session(session.token)
        assert result is not None
        assert result.email == session.email

    def test_get_session_invalid(self):
        assert self.svc.get_session("nonexistent") is None

    def test_google_login_no_token(self):
        """Should return None for invalid tokens."""
        result = self.svc.login_with_google("invalid-token")
        assert result is None

    def test_update_role(self):
        # Use guest + manual update
        self.svc._users["test@update.com"] = {"email": "test@update.com", "name": "Test", "role": "buyer"}
        assert self.svc.update_role("test@update.com", "broker")
        assert self.svc.get_user("test@update.com")["role"] == "broker"

    def test_update_role_nonexistent(self):
        assert not self.svc.update_role("nonexistent", "admin")

    def test_list_users(self):
        self.svc._users["u1@test.com"] = {"email": "u1@test.com", "name": "User1", "role": "buyer"}
        self.svc._users["u2@test.com"] = {"email": "u2@test.com", "name": "User2", "role": "broker"}
        users = self.svc.list_users()
        assert len(users) >= 2

    def test_stats(self):
        stats = self.svc.get_stats()
        assert "total_users" in stats
        assert "active_sessions" in stats

    def test_get_user(self):
        self.svc._users["get@test.com"] = {"email": "get@test.com", "name": "Getter", "role": "buyer"}
        user = self.svc.get_user("get@test.com")
        assert user is not None
        assert user["name"] == "Getter"

    def test_get_user_nonexistent(self):
        assert self.svc.get_user("noone") is None

    def test_singleton(self):
        s1 = get_auth_service()
        s2 = get_auth_service()
        assert s1 is s2

    def test_user_session_to_dict(self):
        session = UserSession(
            user_id="uid-1",
            email="u@t.com",
            name="Test",
            role="admin",
            is_admin=True,
        )
        d = session.to_dict()
        assert d["email"] == "u@t.com"
        assert d["is_admin"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# OAuth Config Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestOAuthConfig:
    def test_config_exists(self):
        assert "google_client_id" in OAUTH_CONFIG
        assert "jwt_secret" in OAUTH_CONFIG
        assert "jwt_expiry_hours" in OAUTH_CONFIG

    def test_default_jwt_expiry(self):
        assert OAUTH_CONFIG["jwt_expiry_hours"] == 24

    def test_google_verifier_fallback(self):
        """GoogleOAuthVerifier should handle invalid tokens gracefully."""
        result = GoogleOAuthVerifier.verify_id_token("not-a-valid-token")
        assert result is None


class TestAdminPromotion:
    def test_admin_promotion_on_login(self):
        """login_with_google should set is_admin=True for configured admin emails."""
        import base64
        import json
        import os
        original = os.environ.get("ADMIN_EMAILS", "")
        try:
            os.environ["ADMIN_EMAILS"] = "admin@testplatform.in"
            import importlib

            import realestate.auth_service as auth_svc
            importlib.reload(auth_svc)
            svc = auth_svc.AuthService()

            # Create a fake JWT token with admin email in payload
            payload = json.dumps({"email": "admin@testplatform.in", "name": "Admin User"})
            payload_b64 = base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()
            fake_token = f"header.{payload_b64}.signature"

            session = svc.login_with_google(fake_token, role="admin")
            assert session is not None, "Admin login should succeed with valid JWT payload"
            assert session.is_admin is True, "Admin email should have is_admin=True"
            assert session.email == "admin@testplatform.in"

            # Non-admin email should NOT get admin status
            payload2 = json.dumps({"email": "user@testplatform.in", "name": "Regular User"})
            payload_b64_2 = base64.urlsafe_b64encode(payload2.encode()).rstrip(b"=").decode()
            fake_token2 = f"header.{payload_b64_2}.signature"

            session2 = svc.login_with_google(fake_token2)
            assert session2 is not None
            assert session2.is_admin is False, "Non-admin email should have is_admin=False"

        finally:
            os.environ["ADMIN_EMAILS"] = original

    def test_default_admin_emails(self):
        """Default admin emails should promote users correctly."""
        import base64
        import json
        import os
        orig = os.environ.pop("ADMIN_EMAILS", None)
        try:
            import importlib

            import realestate.auth_service as auth_svc
            importlib.reload(auth_svc)
            svc = auth_svc.AuthService()

            # Default admin email test
            payload = json.dumps({"email": "admin@realestate.in", "name": "Default Admin"})
            payload_b64 = base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()
            fake_token = f"header.{payload_b64}.signature"

            session = svc.login_with_google(fake_token, role="admin")
            assert session is not None
            assert session.is_admin is True, "Default admin should have is_admin=True"
            assert session.email == "admin@realestate.in"

        finally:
            if orig is not None:
                os.environ["ADMIN_EMAILS"] = orig
