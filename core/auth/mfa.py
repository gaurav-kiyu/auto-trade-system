"""Multi-Factor Authentication (MFA) Support (Phase 15 — Security Certification).

Provides TOTP-based MFA for enhanced login security with:
- TOTP code generation and verification (RFC 6238)
- Recovery codes for account recovery
- Session-level MFA verification tracking
- Provisioning URI generation for authenticator apps

Usage:
    from core.auth.mfa import MFAEngine

    engine = MFAEngine()
    secret = engine.generate_secret()
    code = engine.generate_totp(secret)
    is_valid = engine.verify_totp(secret, code)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

__all__ = [
    "MFASessionState",
    "MFAConfig",
    "MFAEngine",
    "generate_mfa_secret",
    "generate_recovery_codes",
    "get_mfa_provisioning_uri",
    "get_mfa_session_state",
    "hash_recovery_code",
    "verify_mfa_token",
    "verify_recovery_code",
]


class MFAConfig:
    """MFA configuration.

    Attributes:
        enabled: Whether MFA is enabled globally.
        totp_interval: TOTP time step in seconds (default 30).
        totp_digits: Number of digits in TOTP code (default 6).
        totp_allowed_drift: Allowed TOTP drift in intervals (default 1).
        issuer: Issuer name for authenticator apps.
    """

    def __init__(
        self,
        enabled: bool = True,
        totp_interval: int = 30,
        totp_digits: int = 6,
        totp_allowed_drift: int = 1,
        issuer: str = "OPB Trading System",
    ) -> None:
        self.enabled = enabled
        self.totp_interval = totp_interval
        self.totp_digits = totp_digits
        self.totp_allowed_drift = totp_allowed_drift
        self.issuer = issuer

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "totp_interval": self.totp_interval,
            "totp_digits": self.totp_digits,
            "totp_allowed_drift": self.totp_allowed_drift,
            "issuer": self.issuer,
        }


class MFAEngine:
    """MFA engine providing TOTP generation and verification.

    Uses HMAC-SHA1 per RFC 6238 for TOTP generation, compatible with
    Google Authenticator, Authy, and other TOTP apps.
    """

    def __init__(self, config: MFAConfig | None = None) -> None:
        self._config = config or MFAConfig()

    @property
    def config(self) -> MFAConfig:
        return self._config

    def generate_secret(self) -> str:
        """Generate a new base32-encoded TOTP secret.

        Uses 20 random bytes (160 bits) per RFC 4226 recommendation,
        producing a 32-character base32 secret compatible with Google
        Authenticator and other TOTP apps.

        Returns:
            A 32-character base32 secret string.
        """
        raw = os.urandom(20)
        return self._base32_encode(raw)

    def generate_totp(self, secret: str, timestamp: int | None = None) -> str:
        """Generate a TOTP code for the given secret and timestamp.

        Args:
            secret: Base32-encoded secret string.
            timestamp: Unix timestamp (default: current time).

        Returns:
            TOTP code as a zero-padded string of totp_digits length.
        """
        if timestamp is None:
            timestamp = int(time.time())
        key = self._base32_decode(secret)
        counter = struct.pack(">Q", timestamp // self._config.totp_interval)
        h = hmac.new(key, counter, hashlib.sha1).digest()
        offset = h[-1] & 0x0F
        truncated = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
        code = truncated % (10 ** self._config.totp_digits)
        return str(code).zfill(self._config.totp_digits)

    def verify_totp(self, secret: str, code: str, timestamp: int | None = None) -> bool:
        """Verify a TOTP code against the secret.

        Allows a configurable time drift (totp_allowed_drift intervals)
        to account for clock skew between server and authenticator app.

        Args:
            secret: Base32-encoded secret string.
            code: The TOTP code to verify.
            timestamp: Unix timestamp (default: current time).

        Returns:
            True if the code is valid, False otherwise.
        """
        if not self._config.enabled:
            return True

        if timestamp is None:
            timestamp = int(time.time())

        for drift in range(
            -self._config.totp_allowed_drift,
            self._config.totp_allowed_drift + 1,
        ):
            expected = self.generate_totp(secret, timestamp + drift * self._config.totp_interval)
            if hmac.compare_digest(expected, code.strip()):
                return True
        return False

    def get_provisioning_uri(
        self,
        secret: str,
        username: str,
        issuer: str | None = None,
    ) -> str:
        """Generate an otpauth:// URI for provisioning in authenticator apps.

        Args:
            secret: Base32-encoded secret string.
            username: User identifier (e.g., email).
            issuer: Issuer name (default: from config).

        Returns:
            otpauth:// URI string.
        """
        iss = (issuer or self._config.issuer).replace(":", "")
        return (
            f"otpauth://totp/{iss}:{username}?secret={secret}"
            f"&issuer={iss}&algorithm=SHA1"
            f"&digits={self._config.totp_digits}"
            f"&period={self._config.totp_interval}"
        )

    @staticmethod
    def _base32_encode(data: bytes) -> str:
        return base64.b32encode(data).decode("utf-8").rstrip("=")

    @staticmethod
    def _base32_decode(secret: str) -> bytes:
        padding = 8 - (len(secret) % 8)
        if padding != 8:
            secret += "=" * padding
        return base64.b32decode(secret.upper())


# ── Session State ────────────────────────────────────────────────────────────


@dataclass
class MFASessionState:
    """Tracks MFA verification status per session.

    Persists to a JSON file so MFA-verified sessions survive bot restarts.
    Thread-safe via internal RLock.
    """

    _verified_sessions: dict[str, float] = field(default_factory=dict)
    _file_path: Path = field(default_factory=lambda: Path("json/mfa_sessions.json"))
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def mark_verified(self, session_id: str) -> None:
        """Mark a session as MFA-verified with current timestamp."""
        with self._lock:
            self._verified_sessions[session_id] = time.time()
            self._save()

    def is_verified(self, session_id: str, ttl_hours: int = 24) -> bool:
        """Check if a session is MFA-verified within TTL.

        Args:
            session_id: The session token to check.
            ttl_hours: Verification TTL in hours (default 24).

        Returns:
            True if the session has been verified within the TTL.
        """
        with self._lock:
            ts = self._verified_sessions.get(session_id)
            if ts is None:
                return False
            if time.time() - ts > ttl_hours * 3600:
                self._verified_sessions.pop(session_id, None)
                self._save()
                return False
            return True

    def revoke(self, session_id: str) -> None:
        """Revoke MFA verification for a session."""
        with self._lock:
            self._verified_sessions.pop(session_id, None)
            self._save()

    def _load(self) -> None:
        """Load verified sessions from JSON file."""
        try:
            if self._file_path.exists():
                data = json.loads(self._file_path.read_text(encoding="utf-8"))
                self._verified_sessions = {k: float(v) for k, v in data.get("verified", {}).items()}
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            pass

    def _save(self) -> None:
        """Save verified sessions to JSON file."""
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_path.write_text(
                json.dumps({"verified": self._verified_sessions}, indent=2),
                encoding="utf-8",
            )
        except (OSError, ValueError, TypeError):
            pass


# ── Singleton ────────────────────────────────────────────────────────────────

_session_state: MFASessionState | None = None
_session_lock = threading.RLock()


def get_mfa_session_state() -> MFASessionState:
    """Get the singleton MFA session state tracker.

    Returns:
        The global MFASessionState instance.
    """
    global _session_state
    with _session_lock:
        if _session_state is None:
            _session_state = MFASessionState()
            _session_state._load()
        return _session_state


# ── Module-level convenience functions ───────────────────────────────────────

_engine: MFAEngine | None = None
_engine_lock = threading.RLock()


def _get_engine() -> MFAEngine:
    """Get the global MFA engine singleton."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = MFAEngine()
        return _engine


def generate_mfa_secret() -> str:
    """Generate a new MFA secret (base32-encoded).

    Returns:
        A 32-character base32 secret string for provisioning
        in authenticator apps.
    """
    return _get_engine().generate_secret()


def verify_mfa_token(secret: str, token: str) -> bool:
    """Verify a TOTP token against a secret.

    Args:
        secret: Base32-encoded secret string.
        token: The TOTP code to verify (6+ digits).

    Returns:
        True if the token is valid.
    """
    return _get_engine().verify_totp(secret, token)


def get_mfa_provisioning_uri(secret: str, username: str) -> str:
    """Generate an otpauth:// provisioning URI for QR code generation.

    Args:
        secret: Base32-encoded secret string.
        username: User identifier (e.g., email or username).

    Returns:
        otpauth:// URI suitable for QR code generation.
    """
    return _get_engine().get_provisioning_uri(secret, username)


def generate_recovery_codes(count: int = 8) -> list[str]:
    """Generate recovery codes for MFA fallback.

    Each code is a cryptographically random 12-character hex string.
    Recovery codes should be hashed before storage using hash_recovery_code().

    Args:
        count: Number of recovery codes to generate (default 8).

    Returns:
        List of recovery code strings.
    """
    codes: list[str] = []
    for _ in range(count):
        code = secrets.token_hex(6).upper()
        codes.append(code)
    return codes


def hash_recovery_code(code: str) -> str:
    """Hash a recovery code for secure storage.

    Uses SHA-256 with a deterministic salt prefix derived from the
    code itself. This ensures the same code always produces the same
    hash, while still being one-way.

    Args:
        code: The recovery code to hash.

    Returns:
        SHA-256 hex digest of the salted code.
    """
    salt = hashlib.sha256(code.encode()).hexdigest()[:16]
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


def verify_recovery_code(code: str, hashed_code: str) -> bool:
    """Verify a recovery code against its stored hash.

    Args:
        code: The recovery code to verify.
        hashed_code: The stored hash (from hash_recovery_code).

    Returns:
        True if the code matches the hash.
    """
    return hmac.compare_digest(hash_recovery_code(code), hashed_code)
