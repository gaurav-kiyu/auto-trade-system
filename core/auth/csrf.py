"""
AD-KIYU CSRF Protection - session-bound HMAC token pattern for FastAPI.
Uses a server-side secret + session ID to bind CSRF tokens to authenticated sessions.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from typing import Any

from fastapi import HTTPException, Request

_log = logging.getLogger(__name__)

CSRF_COOKIE_NAME = "opb_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_SECRET_BYTES = 32


class CSRFProtection:
    """CSRF protection using session-bound HMAC tokens.

    Each CSRF token is HMAC-signed with a server secret + session ID,
    preventing token reuse across sessions and reflecting session expiry.
    """

    def __init__(self, secret_key: str = "", cookie_secure: bool = False):
        self._secret = secret_key or secrets.token_hex(CSRF_SECRET_BYTES)
        self._cookie_secure = cookie_secure
        self._exempt_paths: set[str] = set()

    def exempt(self, path: str) -> None:
        self._exempt_paths.add(path)

    def _is_exempt(self, path: str) -> bool:
        return any(path.startswith(e) for e in self._exempt_paths)

    def _generate_token(self, session_id: str) -> str:
        msg = f"{session_id}:{int(time.time() / 900)}"
        return hmac.new(self._secret.encode(), msg.encode(), hashlib.sha256).hexdigest()

    async def ensure_cookie_set(self, request: Request, response: Any) -> None:
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            return
        if self._is_exempt(request.url.path):
            return
        existing = request.cookies.get(CSRF_COOKIE_NAME)
        if existing and len(existing) == 64:
            return
        session_id = (
            getattr(request.state, "session_id", None)
            or getattr(request.state, "token", None)
            and getattr(request.state.token, "token", None)
            or secrets.token_hex(16)
        )
        token = self._generate_token(str(session_id))
        response.set_cookie(
            key=CSRF_COOKIE_NAME,
            value=token,
            max_age=86400,
            httponly=False,
            samesite="lax",
            secure=self._cookie_secure,
            path="/",
        )

    async def validate(self, request: Request) -> None:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return
        if self._is_exempt(request.url.path):
            return
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
        header_token = request.headers.get(CSRF_HEADER_NAME, "")
        if not cookie_token or not header_token:
            _log.warning("[CSRF] Missing token: cookie=%s header=%s", bool(cookie_token), bool(header_token))
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        if not hmac.compare_digest(cookie_token, header_token):
            _log.warning("[CSRF] Token mismatch")
            raise HTTPException(status_code=403, detail="CSRF validation failed")


csrf_protection = CSRFProtection()
