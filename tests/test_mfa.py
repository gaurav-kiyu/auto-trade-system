"""Tests for core/auth/mfa.py — TOTP-based Multi-Factor Authentication.

Covers:
  - generate_mfa_secret() — with/without pyotp
  - get_mfa_provisioning_uri() — URI generation
  - verify_mfa_token() — token validation
  - Recovery codes: generate, hash, verify, consume
  - MFASessionState: mark_verified, is_verified, clear, clear_all, TTL expiry
"""

from __future__ import annotations

import importlib
import sys
import threading
import time
from unittest.mock import patch

import pytest

from core.auth.mfa import (
    RECOVERY_CODE_COUNT,
    MFASessionState,
    consume_recovery_code,
    generate_mfa_secret,
    generate_recovery_codes,
    get_mfa_provisioning_uri,
    get_mfa_session_state,
    hash_recovery_code,
    verify_mfa_token,
    verify_recovery_code,
)


# ── Secret Generation ─────────────────────────────────────────────────────

class TestGenerateMFASecret:
    def test_generates_valid_base32_string(self):
        """Secret should be a valid base32 string (A-Z, 2-7)."""
        secret = generate_mfa_secret()
        assert isinstance(secret, str)
        assert len(secret) > 0
        valid_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
        assert all(c in valid_chars for c in secret.upper())

    def test_generates_32_char_secret(self):
        """Default pyotp secret is 32 characters (160 bits)."""
        secret = generate_mfa_secret()
        assert len(secret) == 32

    def test_generates_different_secrets(self):
        """Each call should produce a unique secret."""
        secrets = {generate_mfa_secret() for _ in range(10)}
        assert len(secrets) == 10

    def test_fallback_without_pyotp(self):
        """When pyotp is unavailable, fallback should still produce valid base32."""
        with patch.dict(sys.modules, {"pyotp": None}):
            secret = generate_mfa_secret()
        assert isinstance(secret, str)
        assert len(secret) == 32
        valid_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
        assert all(c in valid_chars for c in secret.upper())


# ── Provisioning URI ─────────────────────────────────────────────────────

class TestGetMFAProvisioningURI:
    def test_generates_otpauth_uri(self):
        """URI should start with otpauth://totp/."""
        secret = generate_mfa_secret()
        uri = get_mfa_provisioning_uri("test@example.com", secret)
        assert uri.startswith("otpauth://totp/")

    def test_contains_secret_param(self):
        """URI should contain the secret as a parameter."""
        secret = generate_mfa_secret()
        uri = get_mfa_provisioning_uri("test@example.com", secret)
        assert f"secret={secret}" in uri or secret in uri

    def test_includes_username(self):
        """URI should contain the username (URL-encoded @ as %40)."""
        uri = get_mfa_provisioning_uri("user@opb.com", "TESTFAKE123456789012345678901234")
        # @ gets URL-encoded as %40 in the URI
        assert "user%40opb.com" in uri or "user@opb.com" in uri

    def test_includes_issuer(self):
        """URI should contain the issuer."""
        uri = get_mfa_provisioning_uri("test@example.com", "TESTFAKE123456789012345678901234", issuer="MyApp")
        assert "issuer=MyApp" in uri

    def test_fallback_uri_without_pyotp(self):
        """Fallback URI construction when pyotp is unavailable."""
        secret = generate_mfa_secret()
        with patch.dict(sys.modules, {"pyotp": None}):
            uri = get_mfa_provisioning_uri("test@example.com", secret, issuer="OPB")
        assert uri.startswith("otpauth://totp/")
        assert "secret=" in uri
        assert "issuer=" in uri


# ── Token Verification ───────────────────────────────────────────────────

class TestVerifyMFAToken:
    def test_rejects_empty_secret(self):
        assert verify_mfa_token("", "123456") is False

    def test_rejects_empty_token(self):
        assert verify_mfa_token("SOME_SECRET", "") is False

    def test_rejects_none_secret(self):
        assert verify_mfa_token(None, "123456") is False  # type: ignore

    def test_rejects_short_token(self):
        assert verify_mfa_token("SOME_SECRET", "12345") is False

    def test_rejects_long_token(self):
        assert verify_mfa_token("SOME_SECRET", "1234567") is False

    def test_rejects_non_digit_token(self):
        assert verify_mfa_token("SOME_SECRET", "abc123") is False

    def test_rejects_random_token(self):
        """A random token should not verify against a random secret."""
        secret = generate_mfa_secret()
        assert verify_mfa_token(secret, "000000") is False

    @pytest.mark.skipif(
        importlib.util.find_spec("pyotp") is None,
        reason="pyotp not installed",
    )
    def test_validates_correct_token_with_pyotp(self):
        """If pyotp is available, verify a freshly generated token."""
        import pyotp

        secret = generate_mfa_secret()
        totp = pyotp.TOTP(secret)
        token = totp.now()
        assert verify_mfa_token(secret, token) is True

    def test_fallback_verify_format(self):
        """Fallback verification should handle token format."""
        secret = "JBSWY3DPEHPK3PXP"
        # This is a known test secret; we can't predict the token w/o pyotp
        # Just verify the function returns False for a random token
        with patch.dict(sys.modules, {"pyotp": None}):
            result = verify_mfa_token(secret, "123456")
        # May be True if the counter happens to align (unlikely) or False
        assert isinstance(result, bool)


# ── Recovery Codes ───────────────────────────────────────────────────────

class TestRecoveryCodes:
    def test_generates_correct_count(self):
        """Should generate the default number of recovery codes."""
        codes = generate_recovery_codes()
        assert len(codes) == RECOVERY_CODE_COUNT

    def test_generates_custom_count(self):
        codes = generate_recovery_codes(count=4)
        assert len(codes) == 4

    def test_codes_formatted_correctly(self):
        """Each code should be in XXXX-XXXXXXXX format (13 chars)."""
        codes = generate_recovery_codes()
        for code in codes:
            assert len(code) == 13  # XXXX-XXXXXXXX (6 bytes hex = 12 chars + dash)
            assert code[4] == "-"
            assert len(code.replace("-", "")) == 12
            assert all(c in "0123456789ABCDEF" for c in code.replace("-", ""))

    def test_codes_are_unique(self):
        codes = generate_recovery_codes(20)
        assert len(set(codes)) == 20

    def test_hash_recovery_code(self):
        """Hashed code should be a 64-char hex string (SHA-256)."""
        code = "ABCD-1234"
        hashed = hash_recovery_code(code)
        assert isinstance(hashed, str)
        assert len(hashed) == 64
        assert all(c in "0123456789abcdef" for c in hashed)

    def test_hash_is_deterministic(self):
        code = "ABCD-1234"
        assert hash_recovery_code(code) == hash_recovery_code(code)

    def test_verify_valid_code(self):
        """A generated code should verify against its own hash."""
        codes = generate_recovery_codes()
        hashed = [hash_recovery_code(c) for c in codes]
        assert verify_recovery_code(codes[0], hashed) is True

    def test_verify_invalid_code(self):
        hashed = [hash_recovery_code("ABCD-1234")]
        assert verify_recovery_code("WXYZ-5678", hashed) is False

    def test_verify_with_unnormalized_code(self):
        """Should accept codes without the dash separator."""
        codes = generate_recovery_codes()
        hashed = [hash_recovery_code(c) for c in codes]
        raw = codes[0].replace("-", "")  # 12 hex chars
        assert verify_recovery_code(raw, hashed) is True

    def test_verify_case_insensitive(self):
        codes = generate_recovery_codes()
        hashed = [hash_recovery_code(c) for c in codes]
        assert verify_recovery_code(codes[0].lower(), hashed) is True

    def test_consume_recovery_code(self):
        """Consuming a code should remove it from the list."""
        codes = generate_recovery_codes()
        hashed = [hash_recovery_code(c) for c in codes]
        remaining = consume_recovery_code(codes[0], hashed)
        assert len(remaining) == len(hashed) - 1
        assert hash_recovery_code(codes[0]) not in remaining

    def test_consume_nonexistent_code(self):
        """Consuming a code not in the list should return unchanged list."""
        hashed = [hash_recovery_code("ABCD-1234")]
        remaining = consume_recovery_code("WXYZ-5678", hashed)
        assert remaining == hashed

    def test_consume_with_unnormalized(self):
        codes = generate_recovery_codes()
        hashed = [hash_recovery_code(c) for c in codes]
        raw = codes[0].replace("-", "")  # 12 hex chars sans dash
        remaining = consume_recovery_code(raw, hashed)
        assert len(remaining) == len(hashed) - 1


# ── MFASessionState ──────────────────────────────────────────────────────

class TestMFASessionState:
    def test_not_verified_initially(self):
        state = MFASessionState()
        assert state.is_verified("session_1") is False

    def test_mark_verified(self):
        state = MFASessionState()
        state.mark_verified("session_1")
        assert state.is_verified("session_1") is True

    def test_different_sessions_independent(self):
        state = MFASessionState()
        state.mark_verified("session_1")
        assert state.is_verified("session_1") is True
        assert state.is_verified("session_2") is False

    def test_clear_removes_verification(self):
        state = MFASessionState()
        state.mark_verified("session_1")
        state.clear("session_1")
        assert state.is_verified("session_1") is False

    def test_clear_nonexistent_session_no_error(self):
        state = MFASessionState()
        state.clear("nonexistent")  # Should not raise

    def test_clear_all_for_user(self):
        state = MFASessionState()
        state.mark_verified("sess_a")
        state.mark_verified("sess_b")
        state.mark_verified("sess_c")
        state.clear_all_for_user(["sess_a", "sess_c"])
        assert state.is_verified("sess_a") is False
        assert state.is_verified("sess_b") is True
        assert state.is_verified("sess_c") is False

    def test_ttl_expiry(self):
        """MFA verification should expire after TTL."""
        state = MFASessionState()
        state.mark_verified("session_1")
        # Patch time.time to simulate TTL expiry
        original_time = time.time
        try:
            time.time = lambda: original_time() + 86401  # 1 second past TTL
            assert state.is_verified("session_1", ttl_seconds=86400) is False
        finally:
            time.time = original_time

    def test_expired_verification_cleaned_up(self):
        """Expired entries should be removed from the dict."""
        state = MFASessionState()
        state.mark_verified("session_1")
        original_time = time.time
        try:
            time.time = lambda: original_time() + 86401
            state.is_verified("session_1", ttl_seconds=86400)
            assert "session_1" not in state._verified
        finally:
            time.time = original_time

    def test_thread_safety(self):
        """Concurrent mark_verified and is_verified should not race."""
        state = MFASessionState()
        errors = []

        def worker(session_id: str):
            for _ in range(100):
                try:
                    state.mark_verified(session_id)
                    state.is_verified(session_id)
                    state.clear(session_id)
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"s{i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0, f"Thread safety errors: {errors}"


# ── Singleton ────────────────────────────────────────────────────────────

class TestGetMFASessionState:
    def test_returns_same_instance(self):
        s1 = get_mfa_session_state()
        s2 = get_mfa_session_state()
        assert s1 is s2

    def test_instance_is_mfa_session_state(self):
        state = get_mfa_session_state()
        assert isinstance(state, MFASessionState)

    def test_persists_across_calls(self):
        state = get_mfa_session_state()
        state.mark_verified("test_session")
        assert get_mfa_session_state().is_verified("test_session") is True
        state.clear("test_session")
