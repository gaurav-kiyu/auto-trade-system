"""Security Hardening Middleware for the Real Estate Platform.

Provides:
  1. RateLimitMiddleware — IP+endpoint rate limiting with sliding window
  2. SecurityHeadersMiddleware — CSP, HSTS, X-Frame-Options, etc.
  3. CSRFTokenService — simple CSRF token generation/validation for HTML forms
  4. rate_limit decorator for per-endpoint rate limiting

Usage in startup:
    from realestate.security import apply_security_middleware
    app = apply_security_middleware(app, rate_limit=True, security_headers=True)
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

_log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Rate Limit Middleware (Sliding Window)
# ═══════════════════════════════════════════════════════════════════════════════

class RateLimitState:
    """In-memory rate limit state with sliding window."""

    def __init__(self) -> None:
        # key -> [(timestamp, count), ...]
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, max_requests: int, window_seconds: int = 60) -> bool:
        """Check if the key has exceeded the rate limit.

        Returns True if allowed, False if rate limited.
        """
        now = time.time()
        window_start = now - window_seconds

        # Prune old entries
        self._buckets[key] = [t for t in self._buckets[key] if t > window_start]

        if len(self._buckets[key]) >= max_requests:
            return False

        self._buckets[key].append(now)
        return True

    def remaining(self, key: str, max_requests: int, window_seconds: int = 60) -> int:
        """Get the number of remaining requests for this key."""
        now = time.time()
        window_start = now - window_seconds
        self._buckets[key] = [t for t in self._buckets[key] if t > window_start]
        return max(0, max_requests - len(self._buckets[key]))

    def reset(self) -> None:
        """Clear all rate limit state."""
        self._buckets.clear()


# Global rate limit state
_rate_limit_state = RateLimitState()


def get_client_ip(request: Request) -> str:
    """Extract client IP from request, respecting proxies."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP", "")
    if real_ip:
        return real_ip.strip()
    client = request.client
    if client:
        return client.host
    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that rate-limits requests per IP and endpoint.

    Configuration:
      - default_rate: max requests per window (default: 100 per 60s)
      - strict_routes: set of path prefixes with stricter limits
      - exempt_routes: set of path prefixes exempt from rate limiting
    """

    def __init__(
        self,
        app: ASGIApp,
        default_rate: int = 100,
        default_window: int = 60,
        strict_routes: dict[str, tuple[int, int]] | None = None,
        exempt_prefixes: set[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._default_rate = default_rate
        self._default_window = default_window
        self._strict_routes = strict_routes or {}
        self._exempt_prefixes = exempt_prefixes or {"/static", "/api/realestate/health"}

    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        # Check exempt prefixes
        path = request.url.path
        for prefix in self._exempt_prefixes:
            if path.startswith(prefix):
                return await call_next(request)

        # Determine rate limit for this route
        rate = self._default_rate
        window = self._default_window
        for prefix, (route_rate, route_window) in self._strict_routes.items():
            if path.startswith(prefix):
                rate = route_rate
                window = route_window
                break

        # Build key from IP + path prefix
        ip = get_client_ip(request)
        # Use first 2 segments of path for grouping
        path_segments = [s for s in path.split("/") if s]
        path_key = "/".join(path_segments[:2]) if path_segments else "root"
        key = f"{ip}:{path_key}"

        # Check rate limit
        if not _rate_limit_state.check(key, rate, window):
            remaining = _rate_limit_state.remaining(key, rate, window)
            _log.warning("[RATE-LIMIT] %s exceeded limit on %s", ip, path)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please try again later.",
                    "retry_after_seconds": window,
                },
                headers={
                    "Retry-After": str(window),
                    "X-RateLimit-Limit": str(rate),
                    "X-RateLimit-Remaining": str(remaining),
                },
            )

        # Add rate limit headers to response
        response = await call_next(request)
        remaining = _rate_limit_state.remaining(key, rate, window)
        response.headers["X-RateLimit-Limit"] = str(rate)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Security Headers Middleware
# ═══════════════════════════════════════════════════════════════════════════════

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(self), payment=(self)",
}

# Default CSP — relaxed enough for real estate platform dependencies
CSP_DEFAULT = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
    "img-src 'self' data: blob: https:; "
    "font-src 'self' data: https://cdnjs.cloudflare.com; "
    "connect-src 'self' https://api.razorpay.com; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "base-uri 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that adds security headers to all responses."""

    def __init__(
        self,
        app: ASGIApp,
        include_csp: bool = True,
        custom_csp: str | None = None,
    ) -> None:
        super().__init__(app)
        self._headers = dict(SECURITY_HEADERS)
        if include_csp:
            self._headers["Content-Security-Policy"] = custom_csp or CSP_DEFAULT

    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        response = await call_next(request)
        for key, value in self._headers.items():
            response.headers[key] = value
        return response


# ═══════════════════════════════════════════════════════════════════════════════
# 3. CSRF Token Service (for HTML forms)
# ═══════════════════════════════════════════════════════════════════════════════

class CSRFTokenService:
    """Simple CSRF token generator and validator for HTML forms.

    Tokens are tied to a session ID and have an expiry time.
    Uses HMAC-SHA256 for token generation.
    """

    def __init__(self, secret: str | None = None, expiry_seconds: int = 3600) -> None:
        self._secret = secret or os.urandom(32).hex()
        self._expiry = expiry_seconds
        self._used_tokens: set[str] = set()

    def generate_token(self, session_id: str = "default") -> str:
        """Generate a CSRF token for the given session."""
        import hmac

        timestamp = int(time.time())
        message = f"{session_id}:{timestamp}"
        digest = hmac.new(
            self._secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"{timestamp}.{digest}"

    def validate_token(self, token: str, session_id: str = "default") -> bool:
        """Validate a CSRF token.

        Returns True if the token is valid and not expired.
        """
        import hmac

        if token in self._used_tokens:
            return False  # Token already used (replay protection)

        try:
            timestamp_str, digest = token.split(".", 1)
            timestamp = int(timestamp_str)
        except (ValueError, IndexError):
            return False

        # Check expiry
        if time.time() - timestamp > self._expiry:
            return False

        # Verify signature
        message = f"{session_id}:{timestamp_str}"
        expected = hmac.new(
            self._secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(digest, expected):
            return False

        # Mark as used
        self._used_tokens.add(token)
        return True

    def get_csrf_meta(self, session_id: str = "default") -> dict[str, str]:
        """Get CSRF metadata for embedding in HTML forms."""
        token = self.generate_token(session_id)
        return {
            "csrf_token": token,
            "csrf_meta": f'<meta name="csrf-token" content="{token}">',
            "csrf_field": f'<input type="hidden" name="csrf_token" value="{token}">',
        }


# Global CSRF service
_csrf_service = CSRFTokenService()


def get_csrf_service() -> CSRFTokenService:
    """Get the global CSRF token service."""
    return _csrf_service


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Quick Apply Helper
# ═══════════════════════════════════════════════════════════════════════════════

def apply_security_middleware(
    app: FastAPI,
    rate_limit: bool = True,
    rate_limit_rate: int = 100,
    rate_limit_window: int = 60,
    security_headers: bool = True,
    include_csp: bool = True,
    strict_routes: dict[str, tuple[int, int]] | None = None,
) -> FastAPI:
    """Apply all security middleware to the FastAPI app.

    Order matters: rate limiter should run before security headers so
    rate-limited requests don't generate full response headers.

    Args:
        app: The FastAPI application.
        rate_limit: Enable rate limiting middleware.
        rate_limit_rate: Default max requests per window.
        rate_limit_window: Window in seconds.
        security_headers: Enable security headers middleware.
        include_csp: Include Content-Security-Policy header.
        strict_routes: Dict of path prefix -> (rate, window) for strict limits.

    Returns:
        The app with middleware applied.
    """
    if strict_routes is None:
        # Default strict routes: POST endpoints get lower limits
        strict_routes = {
            "/api/realestate/properties": (20, 60),
            "/api/realestate/leads": (30, 60),
            "/api/realestate/enquiries": (20, 60),
            "/api/realestate/chat": (30, 60),
            "/api/realestate/agreements": (15, 60),
            "/api/realestate/payments": (10, 60),
        }

    if rate_limit:
        app.add_middleware(
            RateLimitMiddleware,
            default_rate=rate_limit_rate,
            default_window=rate_limit_window,
            strict_routes=strict_routes,
        )
        _log.info("[SEC] Rate limit middleware applied (default: %d/%ds)", rate_limit_rate, rate_limit_window)

    if security_headers:
        app.add_middleware(
            SecurityHeadersMiddleware,
            include_csp=include_csp,
        )
        _log.info("[SEC] Security headers middleware applied")

    return app
