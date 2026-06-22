"""
AD-KIYU MFA Module — TOTP-based Multi-Factor Authentication.

Uses the pyotp library (RFC 6238) for time-based one-time passwords.
Integrates with the existing AuthHandler, AuthDependencies, and auth routes.

Usage
-----
    from core.auth.mfa import (
        generate_mfa_secret,
        get_mfa_provisioning_uri,
        verify_mfa_token,
        generate_recovery_codes,
    )

    secret = generate_mfa_secret()
    uri = get_mfa_provisioning_uri("user@example.com", secret, issuer="OPB")
    # Show QR code to user, then verify:
    ok = verify_mfa_token(secret, user_input_token)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

RECOVERY_CODE_COUNT = 8
RECOVERY_CODE_BYTES = 6  # 6 bytes → 8 hex chars
RECOVERY_CODE_HASH_ALGO = "sha256"

# ── TOTP Functions ─────────────────────────────────────────────────────────────


def generate_mfa_secret() -> str:
    """Generate a new TOTP-compatible base32 secret.

    Returns:
        A 32-character base32 secret string (160 bits).
    """
    try:
        import pyotp
        return pyotp.random_base32()
    except ImportError:
        _log.warning("[MFA] pyotp not available — using fallback secret generation")
        # Fallback: generate a base32-compatible random string
        # 32 chars = 160 bits of entropy
        b32_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
        return "".join(secrets.choice(b32_chars) for _ in range(32))


def get_mfa_provisioning_uri(
    username: str,
    secret: str,
    issuer: str = "OPB Enterprise",
) -> str:
    """Generate an otpauth:// URI for QR code provisioning.

    Args:
        username: User identifier (e.g., email or username).
        secret: Base32 TOTP secret from generate_mfa_secret().
        issuer: Display name for the authenticator app.

    Returns:
        otpauth:// URI string suitable for QR code generation.
    """
    try:
        import pyotp
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=username, issuer_name=issuer)
    except ImportError:
        _log.warning("[MFA] pyotp not available — generating URI manually")
        # Fallback: manual URI construction
        import urllib.parse
        params = urllib.parse.urlencode({
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": 6,
            "period": 30,
        })
        encoded_issuer = urllib.parse.quote(issuer)
        encoded_user = urllib.parse.quote(username)
        return f"otpauth://totp/{encoded_issuer}:{encoded_user}?{params}"


def verify_mfa_token(secret: str, token: str, valid_window: int = 1) -> bool:
    """Verify a TOTP token against the secret.

    Args:
        secret: Base32 TOTP secret.
        token: The 6-digit token provided by the user.
        valid_window: Number of 30-second windows to check before/after
                      (default 1, allowing 30s clock skew).

    Returns:
        True if token is valid, False otherwise.
    """
    if not secret or not token:
        return False
    if len(token) != 6 or not token.isdigit():
        return False

    try:
        import pyotp
        totp = pyotp.TOTP(secret)
        return totp.verify(token, valid_window=valid_window)
    except ImportError:
        _log.warning("[MFA] pyotp not available — using manual TOTP verification")
        return _verify_totp_fallback(secret, token, valid_window)


def _verify_totp_fallback(secret: str, token: str, valid_window: int = 1) -> bool:
    """Fallback TOTP verification without pyotp.

    Implements RFC 6238 TOTP using HMAC-SHA1.
    """
    try:
        import base64
        import struct

        # Decode base32 secret
        # Add padding if needed
        padded = secret + "=" * (8 - len(secret) % 8) if len(secret) % 8 else secret
        key = base64.b32decode(padded.upper())

        now = int(time.time())
        for offset in range(-valid_window, valid_window + 1):
            counter = (now + offset * 30) // 30
            counter_bytes = struct.pack(">Q", counter)
            h = hmac.new(key, counter_bytes, hashlib.sha1).digest()
            offset_val = h[-1] & 0x0F
            code_bytes = h[offset_val:offset_val + 4]
            code = struct.unpack(">I", code_bytes)[0] & 0x7FFFFFFF
            expected = code % 10 ** 6
            if expected == int(token):
                return True
        return False
    except Exception as exc:
        _log.debug("[MFA] Fallback TOTP verification failed: %s", exc)
        return False


# ── Recovery Codes ─────────────────────────────────────────────────────────────


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Generate cryptographically secure recovery codes.

    Args:
        count: Number of recovery codes to generate.

    Returns:
        List of recovery code strings (8 hex chars each).
    """
    codes: list[str] = []
    for _ in range(count):
        code_bytes = os.urandom(RECOVERY_CODE_BYTES)
        code = code_bytes.hex().upper()
        # Format as XXXX-XXXX for readability
        formatted = f"{code[:4]}-{code[4:]}"
        codes.append(formatted)
    return codes


def hash_recovery_code(code: str) -> str:
    """Hash a recovery code for secure storage.

    Uses SHA-256 with a static pepper (the recovery code itself is
    high-entropy enough that no salt is needed).
    """
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def verify_recovery_code(code: str, hashed_codes: list[str]) -> bool:
    """Verify a recovery code against a list of hashed codes.

    Args:
        code: The raw recovery code to verify.
        hashed_codes: List of SHA-256 hashed recovery codes.

    Returns:
        True if the code matches one of the hashed codes, False otherwise.
    """
    code = code.strip().upper()
    # Normalize: allow XXXX-XXXX or XXXXXXXX
    if "-" not in code and len(code) == 8:
        code = f"{code[:4]}-{code[4:]}"
    hashed = hash_recovery_code(code)
    return hashed in hashed_codes


def consume_recovery_code(code: str, hashed_codes: list[str]) -> list[str]:
    """Remove a used recovery code from the list.

    Args:
        code: The raw recovery code that was used.
        hashed_codes: List of SHA-256 hashed recovery codes.

    Returns:
        Updated list of hashed codes (with the used one removed).
    """
    code = code.strip().upper()
    if "-" not in code and len(code) == 8:
        code = f"{code[:4]}-{code[4:]}"
    hashed = hash_recovery_code(code)
    result = [h for h in hashed_codes if h != hashed]
    return result


# ── MFA State Manager (in-memory, per-session) ──────────────────────────────


class MFASessionState:
    """Tracks which sessions have completed MFA verification.

    Thread-safe. Stores session_id -> verified_timestamp mappings in memory.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._verified: dict[str, float] = {}  # session_id -> verified_at

    def mark_verified(self, session_id: str) -> None:
        """Mark a session as MFA-verified."""
        with self._lock:
            self._verified[session_id] = time.time()

    def is_verified(self, session_id: str, ttl_seconds: int = 86400) -> bool:
        """Check if a session has completed MFA verification recently.

        Args:
            session_id: The session ID to check.
            ttl_seconds: Max age of a verification (default 24h).

        Returns:
            True if MFA was verified for this session within the TTL.
        """
        with self._lock:
            ts = self._verified.get(session_id)
            if ts is None:
                return False
            if time.time() - ts > ttl_seconds:
                # Expired
                del self._verified[session_id]
                return False
            return True

    def clear(self, session_id: str) -> None:
        """Clear MFA verification for a session (e.g., on logout)."""
        with self._lock:
            self._verified.pop(session_id, None)

    def clear_all_for_user(self, user_sessions: list[str]) -> None:
        """Clear MFA verification for all sessions belonging to a user."""
        with self._lock:
            for sid in user_sessions:
                self._verified.pop(sid, None)


# ── Singleton ────────────────────────────────────────────────────────────────

_mfa_session_state: MFASessionState | None = None
_mfa_session_lock = threading.RLock()


def get_mfa_session_state() -> MFASessionState:
    """Get the global MFA session state singleton."""
    global _mfa_session_state
    if _mfa_session_state is None:
        with _mfa_session_lock:
            if _mfa_session_state is None:
                _mfa_session_state = MFASessionState()
    return _mfa_session_state
