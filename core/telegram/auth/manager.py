"""
Telegram Authorization Manager.

Handles user identity verification and permission levels (USER vs ADMIN).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UserPermissions:
    is_authorized: bool
    is_admin: bool

class TelegramAuthManager:
    def __init__(self, authorized_ids: set[str], admin_ids: set[str],
                 authorized_chat_ids: set[str] | None = None):
        self._authorized_ids = authorized_ids
        self._admin_ids = admin_ids
        self._authorized_chat_ids = authorized_chat_ids or set()

    def verify_user(self, user_id: str) -> UserPermissions:
        """Check if a user is authorized and determine their role.

        An empty authorized_ids set means NO ONE is authorized by default.
        Operators must explicitly configure telegram_authorized_user_ids.
        """
        is_auth = user_id in self._authorized_ids
        is_admin = user_id in self._admin_ids
        return UserPermissions(is_authorized=is_auth, is_admin=is_admin)

    def verify_chat(self, chat_id: str) -> bool:
        """Verify the sender's chat_id is in the allowlist.

        An empty authorized_chat_ids set means all chats are allowed (backward compat).
        """
        return not self._authorized_chat_ids or chat_id in self._authorized_chat_ids

    def is_admin(self, user_id: str) -> bool:
        return user_id in self._admin_ids


__all__ = [
    "TelegramAuthManager",
    "UserPermissions",
]

