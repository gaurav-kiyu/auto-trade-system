"""AD-KIYU Admin Authentication - JWT-based auth for the control plane.

Uses a config-based auth token to issue short-lived JWTs for admin sessions.
Integrates with core.auth.session_store for session tracking.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from core.auth.permissions import Role
from core.auth.session_store import Session, SessionStore

_log = logging.getLogger(__name__)


@dataclass
class AdminToken:
    """Decoded admin token payload."""

    identity: str
    role: Role
    issued_ts: float
    expiry_ts: float
    session_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expiry_ts

    @property
    def is_valid(self) -> bool:
        return not self.is_expired


class AdminAuth:
    """JWT-like admin authentication for the control plane.

    Uses HMAC-SHA256 signing with a config-derived secret key.
    Tokens are short-lived (default 1 hour) and tied to sessions.
    """

    def __init__(
        self,
        auth_token: str = "",
        token_ttl_seconds: int = 3600,
        session_store: SessionStore | None = None,
    ):
        self._auth_token = auth_token
        self._token_ttl = token_ttl_seconds
        self._session_store = session_store or SessionStore(ttl_seconds=token_ttl_seconds)
        self._lock = threading.RLock()
        if not auth_token:
            _log.warning("[AUTH] No auth_token configured - using ephemeral random key. Set AUTH_TOKEN config for secure operation.")
            self._secret_key = secrets.token_hex(32).encode("utf-8")
        else:
            self._secret_key = self._derive_key(auth_token)

    def _derive_key(self, token: str) -> bytes:
        """Derive a deterministic signing key from the auth token."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest().encode("utf-8")

    def _sign(self, message: str) -> str:
        """Create an HMAC-SHA256 signature for the message."""
        return hmac.new(self._secret_key, message.encode("utf-8"), hashlib.sha256).hexdigest()

    def _verify(self, message: str, signature: str) -> bool:
        """Verify the HMAC-SHA256 signature."""
        expected = self._sign(message)
        return hmac.compare_digest(expected, signature)

    def create_token(
        self,
        identity: str,
        role: Role | str,
        **metadata: Any,
    ) -> str:
        """Create a signed admin token.

        Args:
            identity: Operator identity (e.g. "alice")
            role: Role for this session
            **metadata: Additional metadata to embed

        Returns:
            Signed token string (payload.signature)

        """
        if isinstance(role, str):
            role = Role(role.lower())

        session = self._session_store.create(identity, role, **metadata)

        now = time.time()
        payload = {
            "identity": identity,
            "role": role.value,
            "issued_ts": now,
            "expiry_ts": now + self._token_ttl,
            "session_id": session.session_id,
        }
        encoded = json.dumps(payload, separators=(",", ":"))
        # Base64-encode to avoid dots from JSON float representation
        b64_payload = base64.urlsafe_b64encode(encoded.encode("utf-8")).decode("ascii")
        signature = self._sign(encoded)
        return f"{b64_payload}.{signature}"

    def verify_token(self, token_str: str) -> AdminToken | None:
        """Verify and decode a signed token.

        Args:
            token_str: Signed token string (b64payload.signature)

        Returns:
            AdminToken if valid, None otherwise

        """
        try:
            parts = token_str.split(".")
            if len(parts) != 2:
                return None
            b64_payload, signature = parts
            # Add padding for urlsafe_b64decode
            padding = 4 - len(b64_payload) % 4
            if padding != 4:
                b64_payload += "=" * padding
            decoded_bytes = base64.urlsafe_b64decode(b64_payload)
            encoded_payload = decoded_bytes.decode("utf-8")
            payload = json.loads(encoded_payload)

            if not self._verify(encoded_payload, signature):
                _log.warning("[AUTH] Token signature verification failed")
                return None

            token = AdminToken(
                identity=payload["identity"],
                role=Role(payload["role"].lower()),
                issued_ts=payload["issued_ts"],
                expiry_ts=payload["expiry_ts"],
                session_id=payload["session_id"],
            )

            if token.is_expired:
                _log.debug("[AUTH] Token expired for %s", token.identity)
                return None

            # Validate session is still active
            session = self._session_store.get(token.session_id)
            if session is None:
                _log.debug("[AUTH] Session expired/not found for %s", token.identity)
                return None

            return token
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            _log.warning("[AUTH] Token verification failed: %s", e)
            return None

    def authenticate_request(self, authorization: str | None) -> AdminToken | None:
        """Authenticate an HTTP request from the Authorization header.

        Args:
            authorization: The Authorization header value (e.g. "Bearer <token>")

        Returns:
            AdminToken if valid, None otherwise

        """
        if not authorization:
            return None

        # Support both "Bearer <token>" and "<token>" formats
        token_str = authorization
        if authorization.startswith("Bearer "):
            token_str = authorization[7:]

        token_str = token_str.strip()
        if not token_str:
            return None

        # If no auth token configured, allow only if explicit token matches
        if not self._auth_token:
            # No auth configured - accept any properly signed token
            return self.verify_token(token_str)

        # Auth token configured - validate against config
        # Direct token match (simplified auth for config-based tokens)
        if token_str == self._auth_token:
            return AdminToken(
                identity="admin",
                role=Role.ADMIN,
                issued_ts=time.time(),
                expiry_ts=time.time() + self._token_ttl,
                session_id="direct",
            )

        # Try JWT-style verification
        return self.verify_token(token_str)

    def revoke_session(self, session_id: str) -> bool:
        """Revoke a session by ID."""
        return self._session_store.delete(session_id)

    def get_active_sessions(self) -> list[Session]:
        """Get all active sessions."""
        return self._session_store.list_active()

    @property
    def has_auth_enabled(self) -> bool:
        """Returns True if authentication is configured."""
        return bool(self._auth_token)


__all__ = [
    "AdminAuth",
    "AdminToken",
]

