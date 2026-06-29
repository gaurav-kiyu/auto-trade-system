"""
Tests for core/auth/csrf.py - CSRF Protection for FastAPI.

Tests cover:
- Token generation (deterministic within time window)
- Token validation (cookie vs header match)
- Safe method exemption (GET, HEAD, OPTIONS)
- Path exemption
- Missing token handling
- Token mismatch handling
- Cookie setting on GET requests
"""

from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import MagicMock, patch

import pytest
from core.auth.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, CSRFProtection
from fastapi import HTTPException, Request, Response

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def secret() -> str:
    """Fixed secret for deterministic testing."""
    return "test_secret_key_32_chars_long!!!"


@pytest.fixture
def csrf(secret: str) -> CSRFProtection:
    """CSRFProtection instance with fixed secret."""
    return CSRFProtection(secret_key=secret)


@pytest.fixture
def mock_request() -> MagicMock:
    """Basic mock request with GET method."""
    req = MagicMock(spec=Request)
    req.method = "GET"
    req.url.path = "/api/status"
    req.cookies = {}
    req.headers = {}
    req.state = MagicMock()
    return req


@pytest.fixture
def mock_response() -> MagicMock:
    """Mock response with set_cookie tracker."""
    resp = MagicMock(spec=Response)
    return resp


# ── Token Generation ─────────────────────────────────────────────────────────


class TestCSRFTokenGeneration:
    """CSRFProtection token generation."""

    def test_generate_token_is_string(self, csrf: CSRFProtection) -> None:
        """Generated token should be a hex string."""
        token = csrf._generate_token("session_123")
        assert isinstance(token, str)
        assert len(token) == 64  # SHA256 hex digest

    def test_generate_token_deterministic_within_window(self, csrf: CSRFProtection) -> None:
        """Same session + same time window should produce same token."""
        token1 = csrf._generate_token("session_123")
        token2 = csrf._generate_token("session_123")
        assert token1 == token2

    def test_generate_token_different_sessions(self, csrf: CSRFProtection) -> None:
        """Different sessions should produce different tokens."""
        token1 = csrf._generate_token("session_123")
        token2 = csrf._generate_token("session_456")
        assert token1 != token2

    def test_generate_token_hmac_format(self, csrf: CSRFProtection) -> None:
        """Token should be a valid HMAC-SHA256."""
        session_id = "test_session"
        token = csrf._generate_token(session_id)
        window = int(time.time() / 900)
        expected_msg = f"{session_id}:{window}"
        expected = hmac.new(
            b"test_secret_key_32_chars_long!!!",
            expected_msg.encode(),
            hashlib.sha256,
        ).hexdigest()
        assert token == expected

    def test_generate_token_different_windows(self, csrf: CSRFProtection) -> None:
        """Tokens from different time windows should differ."""
        with patch("time.time", return_value=0):
            token_old = csrf._generate_token("session")
        with patch("time.time", return_value=1800):
            token_new = csrf._generate_token("session")
        assert token_old != token_new


# ── Cookie Setting (async) ───────────────────────────────────────────────────


class TestCSRFCookieSetting:
    """CSRFProtection.ensure_cookie_set behaviour."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    async def test_sets_cookie_on_safe_methods(
        self, csrf: CSRFProtection, mock_request: MagicMock, mock_response: MagicMock, method: str
    ) -> None:
        """Cookie should be set on GET/HEAD/OPTIONS when missing."""
        mock_request.method = method
        await csrf.ensure_cookie_set(mock_request, mock_response)
        assert mock_response.set_cookie.called
        call_kwargs = mock_response.set_cookie.call_args.kwargs
        assert call_kwargs["key"] == CSRF_COOKIE_NAME
        assert len(call_kwargs["value"]) == 64  # SHA256 hex
        assert call_kwargs["max_age"] == 86400

    @pytest.mark.asyncio
    async def test_skips_cookie_if_exists(
        self, csrf: CSRFProtection, mock_request: MagicMock, mock_response: MagicMock
    ) -> None:
        """Cookie should NOT be set if already present and valid length."""
        mock_request.cookies = {CSRF_COOKIE_NAME: "a" * 64}
        await csrf.ensure_cookie_set(mock_request, mock_response)
        assert not mock_response.set_cookie.called

    @pytest.mark.asyncio
    async def test_sets_cookie_if_existing_invalid_length(
        self, csrf: CSRFProtection, mock_request: MagicMock, mock_response: MagicMock
    ) -> None:
        """Cookie should be refreshed if existing token has wrong length."""
        mock_request.cookies = {CSRF_COOKIE_NAME: "short"}
        await csrf.ensure_cookie_set(mock_request, mock_response)
        assert mock_response.set_cookie.called

    @pytest.mark.asyncio
    async def test_skips_cookie_on_post_methods(
        self, csrf: CSRFProtection, mock_request: MagicMock, mock_response: MagicMock
    ) -> None:
        """Cookie should NOT be set on POST requests."""
        mock_request.method = "POST"
        await csrf.ensure_cookie_set(mock_request, mock_response)
        assert not mock_response.set_cookie.called

    @pytest.mark.asyncio
    async def test_skips_cookie_on_exempt_path(
        self, csrf: CSRFProtection, mock_request: MagicMock, mock_response: MagicMock
    ) -> None:
        """Cookie should NOT be set on exempt paths."""
        csrf.exempt("/api/webhook")
        mock_request.url.path = "/api/webhook/receive"
        await csrf.ensure_cookie_set(mock_request, mock_response)
        assert not mock_response.set_cookie.called

    @pytest.mark.asyncio
    async def test_cookie_not_httponly(
        self, csrf: CSRFProtection, mock_request: MagicMock, mock_response: MagicMock
    ) -> None:
        """Cookie must be accessible by JavaScript (httponly=False)."""
        await csrf.ensure_cookie_set(mock_request, mock_response)
        assert mock_response.set_cookie.call_args.kwargs["httponly"] is False

    @pytest.mark.asyncio
    async def test_cookie_samesite_lax(
        self, csrf: CSRFProtection, mock_request: MagicMock, mock_response: MagicMock
    ) -> None:
        """Cookie should use SameSite=Lax."""
        await csrf.ensure_cookie_set(mock_request, mock_response)
        assert mock_response.set_cookie.call_args.kwargs["samesite"] == "lax"


# ── Validation (async) ───────────────────────────────────────────────────────


class TestCSRFValidation:
    """CSRFProtection.validate behaviour."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    async def test_skip_safe_methods(self, csrf: CSRFProtection, method: str) -> None:
        """GET/HEAD/OPTIONS should skip validation."""
        req = MagicMock(spec=Request)
        req.method = method
        req.url.path = "/api/trade"
        await csrf.validate(req)  # Should not raise

    @pytest.mark.asyncio
    async def test_skip_exempt_paths(self, csrf: CSRFProtection) -> None:
        """Exempt paths should skip validation on POST."""
        csrf.exempt("/api/webhook")
        req = MagicMock(spec=Request)
        req.method = "POST"
        req.url.path = "/api/webhook/receive"
        await csrf.validate(req)  # Should not raise

    @pytest.mark.asyncio
    async def test_validates_successfully(self, csrf: CSRFProtection) -> None:
        """Matching cookie and header tokens should pass validation."""
        session_id = "test_session"
        token = csrf._generate_token(session_id)
        req = MagicMock(spec=Request)
        req.method = "POST"
        req.url.path = "/api/trade"
        req.cookies = {CSRF_COOKIE_NAME: token}
        req.headers = {CSRF_HEADER_NAME: token}
        await csrf.validate(req)  # Should not raise

    @pytest.mark.asyncio
    async def test_raises_on_missing_cookie(self, csrf: CSRFProtection) -> None:
        """Missing cookie should raise 403."""
        req = MagicMock(spec=Request)
        req.method = "POST"
        req.url.path = "/api/trade"
        req.cookies = {}
        req.headers = {CSRF_HEADER_NAME: "some_token"}
        with pytest.raises(HTTPException) as exc:
            await csrf.validate(req)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_on_missing_header(self, csrf: CSRFProtection) -> None:
        """Missing header should raise 403."""
        req = MagicMock(spec=Request)
        req.method = "POST"
        req.url.path = "/api/trade"
        req.cookies = {CSRF_COOKIE_NAME: "some_token"}
        req.headers = {}
        with pytest.raises(HTTPException) as exc:
            await csrf.validate(req)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_on_token_mismatch(self, csrf: CSRFProtection) -> None:
        """Mismatched tokens should raise 403."""
        token1 = csrf._generate_token("session_a")
        token2 = csrf._generate_token("session_b")
        req = MagicMock(spec=Request)
        req.method = "POST"
        req.url.path = "/api/trade"
        req.cookies = {CSRF_COOKIE_NAME: token1}
        req.headers = {CSRF_HEADER_NAME: token2}
        with pytest.raises(HTTPException) as exc:
            await csrf.validate(req)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_on_empty_tokens(self, csrf: CSRFProtection) -> None:
        """Empty tokens should raise 403."""
        req = MagicMock(spec=Request)
        req.method = "POST"
        req.url.path = "/api/trade"
        req.cookies = {CSRF_COOKIE_NAME: ""}
        req.headers = {CSRF_HEADER_NAME: ""}
        with pytest.raises(HTTPException) as exc:
            await csrf.validate(req)
        assert exc.value.status_code == 403


# ── Exempt Paths ─────────────────────────────────────────────────────────────


class TestCSRFExemptPaths:
    """CSRFProtection path exemption."""

    def test_exempt_adds_path(self, csrf: CSRFProtection) -> None:
        """exempt() should add a path to exempt set."""
        csrf.exempt("/api/webhook")
        assert "/api/webhook" in csrf._exempt_paths

    def test_is_exempt_exact_match(self, csrf: CSRFProtection) -> None:
        """Exact path should be exempt."""
        csrf.exempt("/api/health")
        assert csrf._is_exempt("/api/health") is True

    def test_is_exempt_prefix_match(self, csrf: CSRFProtection) -> None:
        """Prefix match should be exempt."""
        csrf.exempt("/api/public")
        assert csrf._is_exempt("/api/public/endpoint") is True

    def test_is_exempt_no_match(self, csrf: CSRFProtection) -> None:
        """Non-exempt path should not be exempt."""
        csrf.exempt("/api/exempt")
        assert csrf._is_exempt("/api/other") is False

    def test_is_exempt_empty_exemptions(self, csrf: CSRFProtection) -> None:
        """Empty exemption set should not match anything."""
        assert csrf._is_exempt("/any/path") is False


# ── Construction ─────────────────────────────────────────────────────────────


class TestCSRFConstruction:
    """CSRFProtection construction."""

    def test_default_secret_generated(self) -> None:
        """Default construction should generate a random secret."""
        csrf = CSRFProtection()
        assert len(csrf._secret) == 64  # 32 bytes hex = 64 chars
        assert csrf._cookie_secure is False

    def test_custom_secret(self) -> None:
        """Custom secret should be used."""
        csrf = CSRFProtection(secret_key="custom_secret_123")
        assert csrf._secret == "custom_secret_123"

    def test_secure_cookie(self) -> None:
        """Secure cookie flag should be respected."""
        csrf = CSRFProtection(cookie_secure=True)
        assert csrf._cookie_secure is True


# ── Edge Cases (async) ───────────────────────────────────────────────────────


class TestCSRFEdgeCases:
    """Edge cases for CSRF protection."""

    @pytest.mark.asyncio
    async def test_session_from_request_state(
        self, csrf: CSRFProtection, mock_request: MagicMock, mock_response: MagicMock
    ) -> None:
        """Should use session_id from request.state if available."""
        mock_request.state.session_id = "explicit_session"
        await csrf.ensure_cookie_set(mock_request, mock_response)
        assert mock_response.set_cookie.called

    @pytest.mark.asyncio
    async def test_session_from_token(
        self, csrf: CSRFProtection, mock_request: MagicMock, mock_response: MagicMock
    ) -> None:
        """Should use token from request.state.token if available."""
        mock_request.state.token.token = "token_based_session"
        await csrf.ensure_cookie_set(mock_request, mock_response)
        assert mock_response.set_cookie.called
