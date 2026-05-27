"""
AD-KIYU Authentication & Authorisation package.

Provides:
  - AuthHandler — password hashing, JWT tokens, brute-force protection, account lockout
  - RoleManager — role assignment and permission checking
  - SessionStore — operator session tracking with TTL
  - Permission matrix (defined in permissions.py)
  - CSRFProtection — double-submit cookie CSRF protection
  - AuthDependencies — FastAPI dependency injection for auth + RBAC
  - Auth Router — FastAPI router with login, logout, user management
"""

from __future__ import annotations

from core.auth.handler import AuthHandler, AuthToken, AuthUser, hash_password, verify_password
from core.auth.permissions import Permission, PermissionDenied, Role, role_has_permission
from core.auth.role_manager import RoleManager
from core.auth.session_store import SessionStore
from core.auth.csrf import CSRFProtection, csrf_protection
from core.auth.dependencies import AuthDependencies
from core.auth.routes import create_auth_router

__all__ = [
    "AuthHandler",
    "AuthToken",
    "AuthUser",
    "hash_password",
    "verify_password",
    "Permission",
    "PermissionDenied",
    "Role",
    "role_has_permission",
    "RoleManager",
    "SessionStore",
    "CSRFProtection",
    "csrf_protection",
    "AuthDependencies",
    "create_auth_router",
]
