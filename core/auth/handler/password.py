"""Password hashing, verification, and strength validation utilities."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets

from core.auth.handler.constants import (
    MIN_PASSWORD_LENGTH,
    PBKDF2_ITERATIONS,
    SALT_BYTES,
    TOKEN_BYTES,
    HASH_ALGO,
)


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-SHA256 + random salt."""
    salt = os.urandom(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(HASH_ALGO, password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a PBKDF2 hash."""
    try:
        iterations_str, salt_hex, dk_hex = hashed.split("$")
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected_dk = bytes.fromhex(dk_hex)
        dk = hashlib.pbkdf2_hmac(HASH_ALGO, password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(dk, expected_dk)
    except (ValueError, AttributeError):
        return False


def validate_password_strength(password: str) -> tuple[bool, str]:
    """Validate password strength. Returns (valid, message)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain an uppercase letter"
    if not re.search(r"[a-z]", password):
        return False, "Password must contain a lowercase letter"
    if not re.search(r"\d", password):
        return False, "Password must contain a digit"
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-]", password):
        return False, "Password must contain a special character"
    common = ["password", "admin", "123456", "qwerty", "letmein"]
    if any(word in password.lower() for word in common):
        return False, "Password contains a common word"
    return True, ""


def generate_token() -> str:
    """Generate a cryptographically secure random token."""
    return secrets.token_hex(TOKEN_BYTES)


def generate_csrf_token() -> str:
    """Generate a CSRF token."""
    return secrets.token_hex(32)
