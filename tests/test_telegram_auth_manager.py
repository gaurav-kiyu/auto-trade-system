"""Tests for core/telegram/auth/manager.py - Telegram Authorization Manager.

Covers:
- UserPermissions dataclass
- TelegramAuthManager init
- verify_user (authorized/unauthorized/admin)
- verify_chat (allowlisted/all allowed)
- is_admin checks
"""
from __future__ import annotations


from core.telegram.auth.manager import TelegramAuthManager, UserPermissions


# =============================================================================
# UserPermissions Tests
# =============================================================================

class TestUserPermissions:
    def test_authorized_user(self):
        perm = UserPermissions(is_authorized=True, is_admin=False)
        assert perm.is_authorized is True
        assert perm.is_admin is False

    def test_admin_user(self):
        perm = UserPermissions(is_authorized=True, is_admin=True)
        assert perm.is_authorized is True
        assert perm.is_admin is True

    def test_unauthorized_user(self):
        perm = UserPermissions(is_authorized=False, is_admin=False)
        assert perm.is_authorized is False
        assert perm.is_admin is False


# =============================================================================
# TelegramAuthManager Tests
# =============================================================================

class TestInit:
    def test_stores_ids(self):
        auth = TelegramAuthManager(
            authorized_ids={"user1", "user2"},
            admin_ids={"admin1"},
        )
        assert auth._authorized_ids == {"user1", "user2"}
        assert auth._admin_ids == {"admin1"}
        assert auth._authorized_chat_ids == set()

    def test_stores_chat_ids(self):
        auth = TelegramAuthManager(
            authorized_ids={"user1"},
            admin_ids={"admin1"},
            authorized_chat_ids={"chat1", "chat2"},
        )
        assert auth._authorized_chat_ids == {"chat1", "chat2"}

    def test_empty_authorized_ids(self):
        """Empty authorized_ids means NO ONE is authorized."""
        auth = TelegramAuthManager(authorized_ids=set(), admin_ids=set())
        perm = auth.verify_user("unknown_user")
        assert perm.is_authorized is False


class TestVerifyUser:
    def test_authorized_user(self):
        auth = TelegramAuthManager(
            authorized_ids={"user123"},
            admin_ids={},
        )
        perm = auth.verify_user("user123")
        assert perm.is_authorized is True
        assert perm.is_admin is False

    def test_admin_user(self):
        auth = TelegramAuthManager(
            authorized_ids={"admin1"},
            admin_ids={"admin1"},
        )
        perm = auth.verify_user("admin1")
        assert perm.is_authorized is True
        assert perm.is_admin is True

    def test_unauthorized_user(self):
        auth = TelegramAuthManager(
            authorized_ids={"user123"},
            admin_ids={"admin1"},
        )
        perm = auth.verify_user("unknown_user")
        assert perm.is_authorized is False
        assert perm.is_admin is False

    def test_admin_not_in_authorized(self):
        """Admin that's not in authorized_ids should still be admin."""
        auth = TelegramAuthManager(
            authorized_ids={"user1"},
            admin_ids={"admin1"},
        )
        perm = auth.verify_user("admin1")
        # Not in authorized_ids, but checking is_admin
        assert perm.is_authorized is False
        assert perm.is_admin is True

    def test_multiple_authorized_users(self):
        auth = TelegramAuthManager(
            authorized_ids={"user1", "user2", "user3"},
            admin_ids={"user1"},
        )
        assert auth.verify_user("user1").is_authorized is True
        assert auth.verify_user("user2").is_authorized is True
        assert auth.verify_user("user3").is_authorized is True
        assert auth.verify_user("user4").is_authorized is False


class TestVerifyChat:
    def test_empty_chat_ids_allows_all(self):
        """Empty authorized_chat_ids means all chats allowed."""
        auth = TelegramAuthManager(
            authorized_ids={"user1"},
            admin_ids={},
        )
        assert auth.verify_chat("any_chat") is True
        assert auth.verify_chat("") is True

    def test_allowed_chat(self):
        auth = TelegramAuthManager(
            authorized_ids={"user1"},
            admin_ids={},
            authorized_chat_ids={"chat1", "chat2"},
        )
        assert auth.verify_chat("chat1") is True
        assert auth.verify_chat("chat2") is True

    def test_blocked_chat(self):
        auth = TelegramAuthManager(
            authorized_ids={"user1"},
            admin_ids={},
            authorized_chat_ids={"chat1", "chat2"},
        )
        assert auth.verify_chat("chat3") is False

    def test_single_chat_id(self):
        auth = TelegramAuthManager(
            authorized_ids={"user1"},
            admin_ids={},
            authorized_chat_ids={"only_chat"},
        )
        assert auth.verify_chat("only_chat") is True
        assert auth.verify_chat("other_chat") is False


class TestIsAdmin:
    def test_is_admin(self):
        auth = TelegramAuthManager(
            authorized_ids={"admin1"},
            admin_ids={"admin1", "admin2"},
        )
        assert auth.is_admin("admin1") is True
        assert auth.is_admin("admin2") is True

    def test_not_admin(self):
        auth = TelegramAuthManager(
            authorized_ids={"user1"},
            admin_ids={"admin1"},
        )
        assert auth.is_admin("user1") is False

    def test_unknown_user_not_admin(self):
        auth = TelegramAuthManager(
            authorized_ids={},
            admin_ids={"admin1"},
        )
        assert auth.is_admin("unknown") is False
