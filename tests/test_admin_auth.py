"""Tests for AdminAuth — JWT-like admin authentication for the control plane."""

from __future__ import annotations

import time

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def admin_auth():
    """Create an AdminAuth instance with a known auth token."""
    from core.control_plane.admin_auth import AdminAuth
    return AdminAuth(auth_token="test-auth-token-for-testing", token_ttl_seconds=3600)


@pytest.fixture
def admin_auth_ephemeral():
    """Create an AdminAuth with no auth token (ephemeral key mode)."""
    from core.control_plane.admin_auth import AdminAuth
    return AdminAuth(auth_token="", token_ttl_seconds=3600)


# ──────────────────────────────────────────────────────────────────────────────
# Token Creation & Verification
# ──────────────────────────────────────────────────────────────────────────────


class TestTokenCreation:
    def test_create_token(self, admin_auth):
        token_str = admin_auth.create_token("alice", "admin")
        assert isinstance(token_str, str)
        assert "." in token_str  # payload.signature format

    def test_create_token_with_metadata(self, admin_auth):
        token_str = admin_auth.create_token("bob", "operator", source="cli", ip="10.0.0.1")
        assert isinstance(token_str, str)
        assert "." in token_str

    def test_create_token_default_role(self, admin_auth):
        token_str = admin_auth.create_token("charlie", "observer")
        token = admin_auth.verify_token(token_str)
        assert token is not None
        assert token.role.value == "observer"

    def test_create_token_invalid_role_falls_back(self, admin_auth):
        """Invalid role string should raise ValueError."""

        from core.auth.permissions import Role
        token_str = admin_auth.create_token("dave", Role.ADMIN)
        token = admin_auth.verify_token(token_str)
        assert token is not None
        assert token.identity == "dave"


class TestTokenVerification:
    def test_verify_valid_token(self, admin_auth):
        token_str = admin_auth.create_token("alice", "admin")
        token = admin_auth.verify_token(token_str)
        assert token is not None
        assert token.identity == "alice"
        assert token.role.value == "admin"
        assert not token.is_expired
        assert token.is_valid

    def test_verify_token_with_metadata_preserved(self, admin_auth):
        token_str = admin_auth.create_token("bob", "operator", dept="trading")
        token = admin_auth.verify_token(token_str)
        assert token is not None
        assert token.identity == "bob"

    def test_verify_expired_token(self, admin_auth):
        """Token with zero TTL should be expired."""
        auth = admin_auth
        auth._token_ttl = 0  # instant expiry
        token_str = auth.create_token("eve", "observer")
        time.sleep(0.01)
        token = auth.verify_token(token_str)
        assert token is None

    def test_verify_tampered_token(self, admin_auth):
        token_str = admin_auth.create_token("alice", "admin")
        tampered = token_str[:-5] + "XXXXX"
        token = admin_auth.verify_token(tampered)
        assert token is None

    def test_verify_invalid_format(self, admin_auth):
        token = admin_auth.verify_token("not-a-token")
        assert token is None

    def test_verify_empty_token(self, admin_auth):
        token = admin_auth.verify_token("")
        assert token is None

    def test_verify_token_without_dot(self, admin_auth):
        token = admin_auth.verify_token("justapayload")
        assert token is None

    def test_verify_token_wrong_key(self, admin_auth):
        """Token signed with one key should not verify with another."""
        from core.control_plane.admin_auth import AdminAuth
        auth1 = AdminAuth(auth_token="key1")
        auth2 = AdminAuth(auth_token="key2")
        token = auth1.create_token("mallory", "admin")
        verified = auth2.verify_token(token)
        assert verified is None


# ──────────────────────────────────────────────────────────────────────────────
# Authentication via HTTP headers
# ──────────────────────────────────────────────────────────────────────────────


class TestAuthenticateRequest:
    def test_no_auth_header(self, admin_auth):
        token = admin_auth.authenticate_request(None)
        assert token is None

    def test_empty_auth_header(self, admin_auth):
        token = admin_auth.authenticate_request("")
        assert token is None

    def test_bearer_token_valid(self, admin_auth):
        token_str = admin_auth.create_token("alice", "admin")
        token = admin_auth.authenticate_request(f"Bearer {token_str}")
        assert token is not None
        assert token.identity == "alice"

    def test_bearer_token_invalid(self, admin_auth):
        token = admin_auth.authenticate_request("Bearer invalid-token")
        assert token is None

    def test_direct_token_match(self, admin_auth):
        """When auth_token is configured, direct token match works."""
        token = admin_auth.authenticate_request("test-auth-token-for-testing")
        assert token is not None
        assert token.identity == "admin"
        assert token.role.value == "admin"

    def test_direct_token_with_spaces(self, admin_auth):
        token = admin_auth.authenticate_request("  test-auth-token-for-testing  ")
        assert token is not None

    def test_ephemeral_mode_accepts_signed(self, admin_auth_ephemeral):
        """With no auth_token, ephemeral mode should accept properly signed tokens."""
        token_str = admin_auth_ephemeral.create_token("alice", "admin")
        token = admin_auth_ephemeral.authenticate_request(token_str)
        assert token is not None
        assert token.identity == "alice"

    def test_ephemeral_mode_rejects_unsigned(self, admin_auth_ephemeral):
        token = admin_auth_ephemeral.authenticate_request("random-token")
        assert token is None


# ──────────────────────────────────────────────────────────────────────────────
# Session Management
# ──────────────────────────────────────────────────────────────────────────────


class TestSessionManagement:
    def test_revoke_session(self, admin_auth):
        token_str = admin_auth.create_token("alice", "admin")
        token = admin_auth.verify_token(token_str)
        assert token is not None
        assert admin_auth.revoke_session(token.session_id)

    def test_revoke_nonexistent_session(self, admin_auth):
        assert not admin_auth.revoke_session("nonexistent-session")

    def test_revoked_session_rejected(self, admin_auth):
        token_str = admin_auth.create_token("alice", "admin")
        token = admin_auth.verify_token(token_str)
        assert token is not None
        admin_auth.revoke_session(token.session_id)
        token2 = admin_auth.verify_token(token_str)
        assert token2 is None  # Session revoked

    def test_get_active_sessions(self, admin_auth):
        admin_auth.create_token("alice", "admin")
        admin_auth.create_token("bob", "operator")
        sessions = admin_auth.get_active_sessions()
        assert len(sessions) >= 2

    def test_has_auth_enabled(self, admin_auth):
        assert admin_auth.has_auth_enabled

    def test_has_auth_disabled(self, admin_auth_ephemeral):
        assert not admin_auth_ephemeral.has_auth_enabled


# ──────────────────────────────────────────────────────────────────────────────
# Security & Edge Cases
# ──────────────────────────────────────────────────────────────────────────────


class TestSecurity:
    def test_different_tokens_for_different_identities(self, admin_auth):
        t1 = admin_auth.create_token("alice", "admin")
        t2 = admin_auth.create_token("bob", "admin")
        assert t1 != t2

    def test_token_contains_no_raw_secrets(self, admin_auth):
        import base64
        token_str = admin_auth.create_token("alice", "admin")
        assert "test-auth-token-for-testing" not in token_str
        # Decode the base64 payload to verify identity is embedded
        b64_payload = token_str.split(".")[0]
        padding = 4 - len(b64_payload) % 4
        if padding != 4:
            b64_payload += "=" * padding
        decoded = base64.urlsafe_b64decode(b64_payload).decode("utf-8")
        assert "alice" in decoded  # identity is in payload

    def test_admin_token_properties(self, admin_auth):
        token_str = admin_auth.create_token("alice", "admin")
        token = admin_auth.verify_token(token_str)
        assert token is not None
        assert token.issued_ts > 0
        assert token.expiry_ts > token.issued_ts
        assert token.session_id != ""
        assert isinstance(token.metadata, dict)

    def test_expired_token_property(self):
        from core.auth.permissions import Role
        from core.control_plane.admin_auth import AdminToken
        token = AdminToken(
            identity="test",
            role=Role.ADMIN,
            issued_ts=0,
            expiry_ts=0,
            session_id="s1",
        )
        assert token.is_expired
        assert not token.is_valid

    def test_signing_key_deterministic(self):
        """Same auth token produces same signing key."""
        from core.auth.session_store import SessionStore
        from core.control_plane.admin_auth import AdminAuth
        shared_store = SessionStore()
        a1 = AdminAuth(auth_token="shared-key", session_store=shared_store)
        a2 = AdminAuth(auth_token="shared-key", session_store=shared_store)
        token = a1.create_token("alice", "admin")
        verified = a2.verify_token(token)
        assert verified is not None
        assert verified.identity == "alice"

    def test_signature_not_reversible(self, admin_auth):
        """Signature should not reveal the secret key."""
        token_str = admin_auth.create_token("alice", "admin")
        parts = token_str.split(".")
        assert len(parts) == 2, f"Expected 2 parts, got {len(parts)}"
        signature = parts[1]
        assert "test" not in signature
        assert len(signature) == 64  # SHA-256 hex digest


# ──────────────────────────────────────────────────────────────────────────────
# Session Store Integration
# ──────────────────────────────────────────────────────────────────────────────


class TestSessionStoreIntegration:
    def test_custom_session_store(self, admin_auth):
        """Verify sessions are stored and retrievable."""
        from core.auth.session_store import SessionStore
        store = admin_auth._session_store
        assert isinstance(store, SessionStore)

    def test_session_ttl_propagated(self):
        """Session store TTL should match auth token TTL."""
        from core.control_plane.admin_auth import AdminAuth
        auth = AdminAuth(auth_token="test", token_ttl_seconds=7200)
        assert auth._session_store._ttl == 7200
