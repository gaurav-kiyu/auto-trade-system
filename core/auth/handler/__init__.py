"""AD-KIYU Enterprise Auth Handler package.

Provides password hashing, JWT tokens, session management,
brute-force protection, account lockout, and MFA management.
"""

from __future__ import annotations

from core.auth.handler.constants import (
    BRUTE_FORCE_MAX_ATTEMPTS,
    BRUTE_FORCE_WINDOW_SECONDS,
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    DEFAULT_ADMIN_USERNAME,
    HASH_ALGO,
    LOCKOUT_DURATION_SECONDS,
    MAX_CONCURRENT_SESSIONS,
    MAX_LOGIN_ATTEMPTS,
    MIN_PASSWORD_LENGTH,
    PBKDF2_ITERATIONS,
    REFRESH_TTL_SECONDS,
    SALT_BYTES,
    SESSION_COOKIE_NAME,
    TOKEN_BYTES,
    TOKEN_TTL_SECONDS,
)
from core.auth.handler.handler import AuthHandler
from core.auth.handler.mfa_handler import MfaHandlerMixin
from core.auth.handler.session_manager import SessionManagerMixin
from core.auth.handler.models import AuthToken, AuthUser, PasswordResetToken
from core.auth.handler.password import (
    generate_csrf_token,
    generate_token,
    hash_password,
    validate_password_strength,
    verify_password,
)

__all__ = [
    # Constants
    "TOKEN_TTL_SECONDS",
    "SESSION_COOKIE_NAME",
    "CSRF_COOKIE_NAME",
    "CSRF_HEADER_NAME",
    "MIN_PASSWORD_LENGTH",
    "PBKDF2_ITERATIONS",
    "HASH_ALGO",
    "SALT_BYTES",
    "TOKEN_BYTES",
    "REFRESH_TTL_SECONDS",
    "MAX_LOGIN_ATTEMPTS",
    "LOCKOUT_DURATION_SECONDS",
    "BRUTE_FORCE_WINDOW_SECONDS",
    "BRUTE_FORCE_MAX_ATTEMPTS",
    "MAX_CONCURRENT_SESSIONS",
    "DEFAULT_ADMIN_USERNAME",
    # Models
    "AuthUser",
    "AuthToken",
    "PasswordResetToken",
    # Password utilities
    "hash_password",
    "verify_password",
    "validate_password_strength",
    "generate_token",
    "generate_csrf_token",
    # Mixins
    "MfaHandlerMixin",
    "SessionManagerMixin",
    # Main class
    "AuthHandler",
]
