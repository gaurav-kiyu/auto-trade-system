"""
Telegram Authorization Manager.

Handles user identity verification and permission levels (USER vs ADMIN).
"""

from __future__ import annotations
from typing import Set, Any
from dataclasses import dataclass

@dataclass
class UserPermissions:
    is_authorized: bool
    is_admin: bool

class TelegramAuthManager:
    def __init__(self, authorized_ids: Set[str], admin_ids: Set[str]):
        self._authorized_ids = authorized_ids
        self._admin_ids = admin_ids

    def verify_user(self, user_id: str) -> UserPermissions:
        """Check if a user is authorized and determine their role."""
        is_auth = user_id in self._authorized_ids or not self._authorized_ids
        is_admin = user_id in self._admin_ids
        return UserPermissions(is_authorized=is_auth, is_admin=is_admin)

    def is_admin(self, user_id: str) -> bool:
        return user_id in self._admin_ids
