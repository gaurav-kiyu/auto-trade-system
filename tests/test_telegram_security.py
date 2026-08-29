"""
Tests for Telegram Security and Hardening (v2.46).
"""


import pytest
from core.telegram.auth.manager import TelegramAuthManager
from core.telegram.hardening import (
    create_shield,
    create_validator,
)


class TestTelegramAuth:
    def test_authorized_user(self):
        auth = TelegramAuthManager(authorized_ids={"123", "456"}, admin_ids={"456"})
        result = auth.verify_user("123")
        assert result.is_authorized is True
        assert result.is_admin is False

    def test_admin_user(self):
        auth = TelegramAuthManager(authorized_ids={"123", "456"}, admin_ids={"456"})
        result = auth.verify_user("456")
        assert result.is_authorized is True
        assert result.is_admin is True

    def test_unauthorized_user(self):
        auth = TelegramAuthManager(authorized_ids={"123", "456"}, admin_ids={"456"})
        result = auth.verify_user("999")
        assert result.is_authorized is False


class TestCommandValidation:
    @pytest.fixture
    def validator(self):
        return create_validator({"telegram_cmd_rate_limit_per_min": 10})

    def test_valid_signal_command(self, validator):
        is_valid, msg = validator.validate_command("signal", ["NIFTY", "CALL", "75"], is_admin=False)
        assert is_valid is True

    def test_invalid_signal_direction(self, validator):
        is_valid, msg = validator.validate_command("signal", ["NIFTY", "INVALID", "75"], is_admin=False)
        assert is_valid is False


class TestRateLimiting:
    @pytest.fixture
    def validator(self):
        return create_validator({"telegram_cmd_rate_limit_per_min": 3})

    def test_rate_limit_allows_within_limit(self, validator):
        for i in range(3):
            is_allowed, _ = validator.check_rate_limit("signal", "user_1")
            assert is_allowed is True

    def test_rate_limit_blocks_over_limit(self, validator):
        for i in range(3):
            validator.check_rate_limit("signal", "user_1")
        is_allowed, _ = validator.check_rate_limit("signal", "user_1")
        assert is_allowed is False


class TestDangerousCommandShield:
    @pytest.fixture
    def shield(self):
        validator = create_validator({})
        return create_shield(validator)

    def test_exit_requires_confirmation(self, shield):
        assert shield.requires_confirmation("exit") is True

    def test_confirmation_flow(self, shield):
        proceed, code, msg = shield.process_dangerous_command("exit_all", [], "123", is_admin=True)
        assert proceed is False
        assert code is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
