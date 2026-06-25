"""Tests for core/telegram/hardening.py - Telegram Command Hardening.

Covers:
- CommandSpec dataclass
- TelegramCommandValidator init and COMMAND_SPECS
- validate_command (valid args, invalid arg count, invalid format, admin-only, unknown cmd)
- check_rate_limit (under limit, at limit, different commands separate)
- request_confirmation / confirm_command (valid, expired, invalid code)
- get_danger_level
- DangerousCommandShield init
- requires_confirmation check
- process_dangerous_command (safe, admin confirmation flow, expired)
- Factory functions create_validator, create_shield
"""
from __future__ import annotations

import time


from core.telegram.hardening import (
    CommandSpec,
    DangerousCommandShield,
    TelegramCommandValidator,
    create_shield,
    create_validator,
)


# =============================================================================
# CommandSpec Tests
# =============================================================================

class TestCommandSpec:
    def test_create_simple(self):
        spec = CommandSpec(
            name="signal",
            min_args=3,
            max_args=10,
            args_pattern=[r"^[A-Z]+$", r"^(CALL|PUT)$", r"^\d+$"],
        )
        assert spec.name == "signal"
        assert spec.requires_admin is False
        assert spec.requires_confirmation is False
        assert spec.danger_level == 0

    def test_create_dangerous(self):
        spec = CommandSpec(
            name="exit_all",
            min_args=0,
            max_args=0,
            args_pattern=[],
            requires_admin=True,
            requires_confirmation=True,
            rate_limit_per_min=1,
            danger_level=3,
        )
        assert spec.requires_admin is True
        assert spec.requires_confirmation is True
        assert spec.rate_limit_per_min == 1
        assert spec.danger_level == 3


# =============================================================================
# TelegramCommandValidator Init Tests
# =============================================================================

class TestInit:
    def test_default_rate_limit(self):
        v = TelegramCommandValidator()
        assert v._default_rate_limit == 10

    def test_custom_rate_limit(self):
        v = TelegramCommandValidator(default_rate_limit=20)
        assert v._default_rate_limit == 20

    def test_has_command_specs(self):
        v = TelegramCommandValidator()
        assert "signal" in v.COMMAND_SPECS
        assert "exit" in v.COMMAND_SPECS
        assert "exit_all" in v.COMMAND_SPECS
        assert "set_config" in v.COMMAND_SPECS
        assert len(v.COMMAND_SPECS) >= 10

    def test_empty_pending_confirmations(self):
        v = TelegramCommandValidator()
        assert v._pending_confirmations == {}


# =============================================================================
# validate_command Tests
# =============================================================================

class TestValidateCommand:
    def test_valid_signal_command(self):
        v = TelegramCommandValidator()
        valid, msg = v.validate_command("signal", ["NIFTY", "CALL", "50"], is_admin=True)
        assert valid is True
        assert msg == ""

    def test_valid_signal_call(self):
        v = TelegramCommandValidator()
        valid, msg = v.validate_command("signal_call", ["NIFTY", "50"], is_admin=True)
        assert valid is True

    def test_unknown_command_allowed(self):
        """Unknown commands should pass validation (dispatcher handles them)."""
        v = TelegramCommandValidator()
        valid, msg = v.validate_command("unknown_cmd", ["arg1"], is_admin=False)
        assert valid is True
        assert msg == ""

    def test_admin_only_rejects_non_admin(self):
        v = TelegramCommandValidator()
        valid, msg = v.validate_command("approve", ["sig-123"], is_admin=False)
        assert valid is False
        assert "Admin-only" in msg

    def test_admin_only_allows_admin(self):
        v = TelegramCommandValidator()
        valid, msg = v.validate_command("approve", ["abc123-456"], is_admin=True)
        assert valid is True

    def test_too_few_args(self):
        v = TelegramCommandValidator()
        valid, msg = v.validate_command("signal", ["NIFTY"], is_admin=True)
        assert valid is False
        assert "at least 3" in msg

    def test_too_many_args(self):
        v = TelegramCommandValidator()
        valid, msg = v.validate_command("exit_all", ["extra_arg"], is_admin=True)
        assert valid is False
        assert "at most 0" in msg

    def test_invalid_arg_format(self):
        v = TelegramCommandValidator()
        valid, msg = v.validate_command("signal", ["12345", "CALL", "50"], is_admin=True)
        assert valid is False
        assert "Invalid argument" in msg

    def test_invalid_direction(self):
        v = TelegramCommandValidator()
        valid, msg = v.validate_command("signal", ["NIFTY", "SELL", "50"], is_admin=True)
        assert valid is False
        assert "Invalid argument" in msg

    def test_approve_with_optional_quantity(self):
        """Approve with 2 args: signal_id and quantity."""
        v = TelegramCommandValidator()
        valid, msg = v.validate_command("approve", ["abc-def-123", "5"], is_admin=True)
        assert valid is True

    def test_exit_with_optional_quantity(self):
        v = TelegramCommandValidator()
        valid, msg = v.validate_command("exit", ["abc-def-123", "5"], is_admin=True)
        assert valid is True


# =============================================================================
# check_rate_limit Tests
# =============================================================================

class TestCheckRateLimit:
    def test_under_limit_allowed(self):
        v = TelegramCommandValidator(default_rate_limit=10)
        allowed, remaining = v.check_rate_limit("signal", "user1")
        assert allowed is True
        assert remaining >= 0

    def test_default_rate_limit_applied(self):
        """Commands without specific rate_limit_per_min use default."""
        v = TelegramCommandValidator(default_rate_limit=5)
        allowed, remaining = v.check_rate_limit("signal", "user1")
        assert allowed is True

    def test_command_specific_rate_limit(self):
        v = TelegramCommandValidator()
        allowed, remaining = v.check_rate_limit("exit_all", "user1")
        assert allowed is True

    def test_same_command_different_users_separate(self):
        v = TelegramCommandValidator(default_rate_limit=1)
        assert v.check_rate_limit("exit", "user1")[0] is True
        assert v.check_rate_limit("exit", "user2")[0] is True

    def test_different_commands_separate_limits(self):
        v = TelegramCommandValidator(default_rate_limit=1)
        assert v.check_rate_limit("signal", "user1")[0] is True
        assert v.check_rate_limit("signal_call", "user1")[0] is True

    def test_old_entries_expired(self):
        """Entries older than 60 seconds should be cleaned up."""
        v = TelegramCommandValidator(default_rate_limit=1)
        key = "user1:signal"
        v._command_history[key] = [time.time() - 120]  # 2 minutes old
        allowed, _ = v.check_rate_limit("signal", "user1")
        assert allowed is True  # Old entry expired


# =============================================================================
# Confirmation Flow Tests
# =============================================================================

class TestConfirmation:
    def test_request_confirmation_returns_code(self):
        v = TelegramCommandValidator()
        code = v.request_confirmation("exit_all", "user1")
        assert code.startswith("EXI-") or code.startswith("EXI")

    def test_confirm_matches(self):
        v = TelegramCommandValidator()
        code = v.request_confirmation("exit_all", "user1")
        assert v.confirm_command("exit_all", "user1", code) is True

    def test_confirm_wrong_code(self):
        v = TelegramCommandValidator()
        v.request_confirmation("exit_all", "user1")
        assert v.confirm_command("exit_all", "user1", "WRONG-CODE") is False

    def test_confirm_no_pending(self):
        v = TelegramCommandValidator()
        assert v.confirm_command("exit_all", "user1", "some-code") is False

    def test_confirm_after_expiry(self):
        """Test that confirmation codes expire after 60 seconds.
        Manually set timestamp in past to test expiry without patching time.
        """
        v = TelegramCommandValidator()
        code = v.request_confirmation("exit_all", "user1")
        # Manually set timestamp to 2 minutes in the past
        key = "user1:exit_all"
        old_ts = time.time() - 120
        v._pending_confirmations[key] = (code, old_ts)
        assert v.confirm_command("exit_all", "user1", code) is False

    def test_confirm_different_command(self):
        """Confirming wrong command should fail."""
        v = TelegramCommandValidator()
        code = v.request_confirmation("exit_all", "user1")
        assert v.confirm_command("set_config", "user1", code) is False  # Different user:cmd key

    def test_confirm_removes_pending(self):
        v = TelegramCommandValidator()
        code = v.request_confirmation("exit_all", "user1")
        assert v.confirm_command("exit_all", "user1", code) is True
        # Second attempt should fail (already consumed)
        assert v.confirm_command("exit_all", "user1", code) is False


# =============================================================================
# get_danger_level Tests
# =============================================================================

class TestGetDangerLevel:
    def test_safe_command(self):
        v = TelegramCommandValidator()
        assert v.get_danger_level("signal") == 1  # signal is level 1

    def test_dangerous_command(self):
        v = TelegramCommandValidator()
        assert v.get_danger_level("exit_all") == 3

    def test_unknown_command(self):
        v = TelegramCommandValidator()
        assert v.get_danger_level("unknown") == 0


# =============================================================================
# DangerousCommandShield Tests
# =============================================================================

class TestDangerousCommandShield:
    def test_requires_confirmation_true(self):
        v = TelegramCommandValidator()
        shield = DangerousCommandShield(v)
        assert shield.requires_confirmation("exit_all") is True
        assert shield.requires_confirmation("exit") is True
        assert shield.requires_confirmation("set_config") is True

    def test_requires_confirmation_false(self):
        v = TelegramCommandValidator()
        shield = DangerousCommandShield(v)
        assert shield.requires_confirmation("signal") is False
        assert shield.requires_confirmation("approve") is False

    def test_unknown_command_no_confirmation(self):
        v = TelegramCommandValidator()
        shield = DangerousCommandShield(v)
        assert shield.requires_confirmation("unknown") is False

    def test_safe_command_proceeds(self):
        v = TelegramCommandValidator()
        shield = DangerousCommandShield(v)
        proceed, confirmation, msg = shield.process_dangerous_command(
            "signal", ["NIFTY", "CALL", "50"], "user1", is_admin=True
        )
        assert proceed is True
        assert confirmation is None
        assert msg == ""

    def test_dangerous_without_admin(self):
        v = TelegramCommandValidator()
        shield = DangerousCommandShield(v)
        proceed, _, msg = shield.process_dangerous_command(
            "exit_all", [], "user1", is_admin=False
        )
        assert proceed is False
        assert "admin confirmation" in msg.lower()

    def test_dangerous_requests_confirmation(self):
        v = TelegramCommandValidator()
        shield = DangerousCommandShield(v)
        proceed, confirmation, msg = shield.process_dangerous_command(
            "exit_all", [], "user1", is_admin=True
        )
        assert proceed is False
        assert confirmation is not None
        assert "CONFIRM:" in msg

    def test_dangerous_with_valid_confirmation(self):
        v = TelegramCommandValidator()
        shield = DangerousCommandShield(v)
        # First get the confirmation code
        _, confirmation, _ = shield.process_dangerous_command(
            "exit_all", [], "user1", is_admin=True
        )
        # Now send with confirmation
        proceed, _, msg = shield.process_dangerous_command(
            "exit_all", [f"CONFIRM:{confirmation}"], "user1", is_admin=True
        )
        assert proceed is True
        assert "confirmed" in msg.lower()

    def test_dangerous_with_invalid_confirmation(self):
        v = TelegramCommandValidator()
        shield = DangerousCommandShield(v)
        proceed, _, msg = shield.process_dangerous_command(
            "exit_all", ["CONFIRM:WRONG"], "user1", is_admin=True
        )
        assert proceed is False
        assert "Invalid" in msg

    def test_dangerous_with_expired_confirmation(self):
        v = TelegramCommandValidator()
        shield = DangerousCommandShield(v)
        _, confirmation, _ = shield.process_dangerous_command(
            "exit_all", [], "user1", is_admin=True
        )
        # Manually set timestamp in the past
        key = "user1:exit_all"
        old_ts = time.time() - 120
        v._pending_confirmations[key] = (confirmation, old_ts)
        proceed, _, msg = shield.process_dangerous_command(
            "exit_all", [f"CONFIRM:{confirmation}"], "user1", is_admin=True
        )
        assert proceed is False


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestFactoryFunctions:
    def test_create_validator(self):
        config = {"telegram_cmd_rate_limit_per_min": 15}
        v = create_validator(config)
        assert isinstance(v, TelegramCommandValidator)
        assert v._default_rate_limit == 15

    def test_create_validator_default_config(self):
        v = create_validator({})
        assert v._default_rate_limit == 10

    def test_create_shield(self):
        v = TelegramCommandValidator()
        shield = create_shield(v)
        assert isinstance(shield, DangerousCommandShield)
        assert shield._validator is v
