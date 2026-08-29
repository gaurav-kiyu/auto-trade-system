"""Tests for Multi-Factor Authentication engine."""

from __future__ import annotations

import os
import time
from pathlib import Path

from core.auth.mfa import (
    MFAConfig,
    MFAEngine,
    MFASessionState,
    generate_mfa_secret,
    generate_recovery_codes,
    get_mfa_provisioning_uri,
    get_mfa_session_state,
    hash_recovery_code,
    verify_mfa_token,
    verify_recovery_code,
)


class TestMFAEngine:
    """Test suite for MFAEngine."""

    def test_generate_secret(self):
        """generate_secret returns a non-empty base32 string."""
        engine = MFAEngine()
        secret = engine.generate_secret()
        assert isinstance(secret, str)
        assert len(secret) >= 16  # At least 16 chars from 20 bytes

    def test_generate_totp(self):
        """generate_totp returns a code of the correct length."""
        engine = MFAEngine()
        secret = engine.generate_secret()
        code = engine.generate_totp(secret)
        assert isinstance(code, str)
        assert len(code) == 6
        assert code.isdigit()

    def test_verify_valid_totp(self):
        """verify_totp should return True for a valid code."""
        engine = MFAEngine()
        secret = engine.generate_secret()
        code = engine.generate_totp(secret)
        assert engine.verify_totp(secret, code)

    def test_verify_invalid_totp(self):
        """verify_totp should return False for an invalid code."""
        engine = MFAEngine()
        secret = engine.generate_secret()
        assert not engine.verify_totp(secret, "000000")

    def test_verify_with_drift(self):
        """verify_totp should accept codes within drift window."""
        engine = MFAEngine()
        secret = engine.generate_secret()
        future_ts = int(time.time()) + 60  # 60 seconds in the future
        future_code = engine.generate_totp(secret, future_ts)
        # Default drift is 1 interval (30s), so 60s = 2 intervals should fail
        assert not engine.verify_totp(secret, future_code)
        # But with drift=2 it should pass
        wide_engine = MFAEngine(MFAConfig(totp_allowed_drift=2))
        assert wide_engine.verify_totp(secret, future_code)

    def test_disabled_mfa(self):
        """Disabled MFA should always return True."""
        engine = MFAEngine(MFAConfig(enabled=False))
        assert engine.verify_totp("invalid", "000000")  # Always passes

    def test_get_provisioning_uri(self):
        """get_provisioning_uri returns an otpauth URI."""
        engine = MFAEngine()
        secret = engine.generate_secret()
        uri = engine.get_provisioning_uri(secret, "testuser")
        assert uri.startswith("otpauth://totp/")
        assert "testuser" in uri
        assert "secret=" in uri

    def test_custom_issuer(self):
        """Custom issuer appears in provisioning URI."""
        engine = MFAEngine(MFAConfig(issuer="TestApp"))
        secret = engine.generate_secret()
        uri = engine.get_provisioning_uri(secret, "user", issuer="CustomIssuer")
        assert "CustomIssuer" in uri

    def test_custom_digits(self):
        """Custom digit count should work."""
        engine = MFAEngine(MFAConfig(totp_digits=8))
        secret = engine.generate_secret()
        code = engine.generate_totp(secret)
        assert len(code) == 8

    def test_custom_interval(self):
        """Custom TOTP interval should work."""
        engine = MFAEngine(MFAConfig(totp_interval=60))
        secret = engine.generate_secret()
        code = engine.generate_totp(secret)
        assert len(code) == 6

    def test_deterministic_secret(self):
        """Same secret produces same code at same time."""
        engine = MFAEngine()
        secret = engine.generate_secret()
        ts = int(time.time())
        code1 = engine.generate_totp(secret, ts)
        code2 = engine.generate_totp(secret, ts)
        assert code1 == code2

    def test_config_to_dict(self):
        """MFAConfig.to_dict returns serializable output."""
        config = MFAConfig(enabled=True, totp_digits=8)
        d = config.to_dict()
        assert d["enabled"] is True
        assert d["totp_digits"] == 8

    def test_config_property(self):
        """config property returns the MFAConfig."""
        cfg = MFAConfig(totp_interval=60)
        engine = MFAEngine(cfg)
        assert engine.config is cfg
        assert engine.config.totp_interval == 60

    def test_base32_roundtrip(self):
        """Base32 encode/decode roundtrip."""
        engine = MFAEngine()
        raw = os.urandom(20)
        encoded = engine._base32_encode(raw)
        decoded = engine._base32_decode(encoded)
        assert decoded == raw

    def test_base32_decode_padding(self):
        """_base32_decode handles missing padding."""
        engine = MFAEngine()
        # Valid base32 without padding
        result = engine._base32_decode("JBSWY3DPEHPK3PXP")
        assert isinstance(result, bytes)
        assert len(result) == 10


class TestMFASessionState:
    """Test suite for MFASessionState."""

    def test_mark_and_check_verified(self, tmp_path: Path):
        """mark_verified followed by is_verified returns True."""
        state = MFASessionState(_file_path=tmp_path / "mfa_sessions.json")
        state.mark_verified("session_1")
        assert state.is_verified("session_1") is True

    def test_unverified_session(self, tmp_path: Path):
        """is_verified returns False for unknown session."""
        state = MFASessionState(_file_path=tmp_path / "mfa_sessions.json")
        assert state.is_verified("unknown_session") is False

    def test_revoke_session(self, tmp_path: Path):
        """revoke removes session verification."""
        state = MFASessionState(_file_path=tmp_path / "mfa_sessions.json")
        state.mark_verified("session_1")
        assert state.is_verified("session_1") is True
        state.revoke("session_1")
        assert state.is_verified("session_1") is False

    def test_expired_session(self, tmp_path: Path):
        """is_verified returns False for expired session."""
        state = MFASessionState(_file_path=tmp_path / "mfa_sessions.json")
        # Manually insert a stale timestamp
        state._verified_sessions["stale"] = time.time() - 25 * 3600  # 25 hours ago
        state._save()
        assert state.is_verified("stale", ttl_hours=24) is False

    def test_persistence(self, tmp_path: Path):
        """Session state persists to disk and reloads."""
        file_path = tmp_path / "mfa_sessions.json"
        state1 = MFASessionState(_file_path=file_path)
        state1.mark_verified("persisted_session")

        # Create a new instance that loads from file
        state2 = MFASessionState(_file_path=file_path)
        state2._load()
        assert state2.is_verified("persisted_session") is True

    def test_revoke_nonexistent(self, tmp_path: Path):
        """revoke on nonexistent session does not error."""
        state = MFASessionState(_file_path=tmp_path / "mfa_sessions.json")
        state.revoke("ghost_session")  # Should not raise

    def test_load_corrupted_file(self, tmp_path: Path):
        """_load handles corrupted JSON gracefully."""
        file_path = tmp_path / "mfa_sessions.json"
        file_path.write_text("not valid json", encoding="utf-8")
        state = MFASessionState(_file_path=file_path)
        state._load()  # Should not crash
        assert state._verified_sessions == {}

    def test_load_missing_file(self):
        """_load handles missing file gracefully."""
        state = MFASessionState(_file_path=Path("/nonexistent/mfa_sessions.json"))
        state._load()  # Should not crash
        assert state._verified_sessions == {}


class TestModuleFunctions:
    """Test suite for module-level convenience functions."""

    def test_generate_mfa_secret(self):
        """generate_mfa_secret returns a valid base32 string."""
        secret = generate_mfa_secret()
        assert isinstance(secret, str)
        assert len(secret) >= 16

    def test_verify_mfa_token(self):
        """verify_mfa_token roundtrip."""
        secret = generate_mfa_secret()
        engine = MFAEngine()
        code = engine.generate_totp(secret)
        assert verify_mfa_token(secret, code) is True
        assert verify_mfa_token(secret, "000000") is False

    def test_get_mfa_provisioning_uri(self):
        """get_mfa_provisioning_uri returns URI."""
        secret = generate_mfa_secret()
        uri = get_mfa_provisioning_uri(secret, "testuser")
        assert uri.startswith("otpauth://totp/")
        assert "testuser" in uri

    def test_generate_recovery_codes_default(self):
        """generate_recovery_codes with default count."""
        codes = generate_recovery_codes()
        assert len(codes) == 8
        for code in codes:
            assert len(code) == 12  # 6 hex bytes = 12 hex chars
            assert code.isalnum()

    def test_generate_recovery_codes_custom(self):
        """generate_recovery_codes with custom count."""
        codes = generate_recovery_codes(count=4)
        assert len(codes) == 4

    def test_hash_and_verify_recovery_code(self):
        """hash_recovery_code and verify_recovery_code roundtrip."""
        code = "ABC123DEF456"
        hashed = hash_recovery_code(code)
        assert isinstance(hashed, str)
        assert len(hashed) == 64  # SHA-256 hex digest
        assert verify_recovery_code(code, hashed) is True

    def test_verify_recovery_code_wrong(self):
        """verify_recovery_code returns False for wrong code."""
        code = "ABC123DEF456"
        hashed = hash_recovery_code(code)
        assert verify_recovery_code("WRONG1234567", hashed) is False

    def test_get_mfa_session_state_singleton(self):
        """get_mfa_session_state returns a singleton."""
        state1 = get_mfa_session_state()
        state2 = get_mfa_session_state()
        assert state1 is state2
