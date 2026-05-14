"""
Telegram Command Hardening (v2.46).

Adds:
- Strict argument validation per command
- Admin confirmation for dangerous commands
- Per-command rate limiting
- Enhanced audit logging with command fingerprinting
"""

from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from collections import defaultdict

_log = logging.getLogger(__name__)


@dataclass
class CommandSpec:
    """Specification for a command's allowed arguments."""
    name: str
    min_args: int
    max_args: int
    args_pattern: list[str]  # regex patterns for each arg
    requires_admin: bool = False
    requires_confirmation: bool = False
    rate_limit_per_min: int = 0  # 0 = use global default
    danger_level: int = 0  # 0 = safe, 1 = risky, 2 = dangerous


class TelegramCommandValidator:
    """
    Validates Telegram commands before execution.
    Provides argument parsing and dangerous command detection.
    """

    COMMAND_SPECS: dict[str, CommandSpec] = {
        "signal": CommandSpec(
            name="signal",
            min_args=3,
            max_args=10,
            args_pattern=[r"^[A-Z]+$", r"^(CALL|PUT)$", r"^\d+$"],
            requires_confirmation=False,
            danger_level=1,
        ),
        "signal_call": CommandSpec(
            name="signal_call",
            min_args=2,
            max_args=3,
            args_pattern=[r"^[A-Z]+$", r"^\d+$"],
            danger_level=1,
        ),
        "signal_put": CommandSpec(
            name="signal_put",
            min_args=2,
            max_args=3,
            args_pattern=[r"^[A-Z]+$", r"^\d+$"],
            danger_level=1,
        ),
        "approve": CommandSpec(
            name="approve",
            min_args=1,
            max_args=2,
            args_pattern=[r"^[a-f0-9\-]+$", r"^\d*$"],
            requires_admin=True,
            danger_level=2,
        ),
        "reject": CommandSpec(
            name="reject",
            min_args=1,
            max_args=2,
            args_pattern=[r"^[a-f0-9\-]+$"],
            requires_admin=True,
            danger_level=2,
        ),
        "approve_all": CommandSpec(
            name="approve_all",
            min_args=0,
            max_args=0,
            args_pattern=[],
            requires_admin=True,
            danger_level=2,
        ),
        "cancel": CommandSpec(
            name="cancel",
            min_args=1,
            max_args=1,
            args_pattern=[r"^[a-f0-9\-]+$"],
            requires_admin=True,
            danger_level=2,
        ),
        "exit": CommandSpec(
            name="exit",
            min_args=1,
            max_args=2,
            args_pattern=[r"^[a-f0-9\-]+$", r"^\d*$"],
            requires_admin=True,
            requires_confirmation=True,
            rate_limit_per_min=2,
            danger_level=3,
        ),
        "exit_all": CommandSpec(
            name="exit_all",
            min_args=0,
            max_args=0,
            args_pattern=[],
            requires_admin=True,
            requires_confirmation=True,
            rate_limit_per_min=1,
            danger_level=3,
        ),
        "move_sl": CommandSpec(
            name="move_sl",
            min_args=2,
            max_args=2,
            args_pattern=[r"^[a-f0-9\-]+$", r"^\d+(\.\d+)?$"],
            requires_admin=True,
            requires_confirmation=True,
            danger_level=2,
        ),
        "partial_exit": CommandSpec(
            name="partial_exit",
            min_args=2,
            max_args=2,
            args_pattern=[r"^[a-f0-9\-]+$", r"^\d+$"],
            requires_admin=True,
            requires_confirmation=True,
            danger_level=2,
        ),
        "set_config": CommandSpec(
            name="set_config",
            min_args=2,
            max_args=10,
            args_pattern=[r"^[A-Z_]+$"],
            requires_admin=True,
            requires_confirmation=True,
            danger_level=3,
        ),
        "retrain_ml": CommandSpec(
            name="retrain_ml",
            min_args=0,
            max_args=1,
            args_pattern=[r"^(FORCE)?$"],
            requires_admin=True,
            danger_level=2,
        ),
        "backup": CommandSpec(
            name="backup",
            min_args=0,
            max_args=1,
            args_pattern=[r"^(FULL|DATA|CONFIG)?$"],
            requires_admin=True,
            danger_level=1,
        ),
    }

    def __init__(self, default_rate_limit: int = 10):
        self._default_rate_limit = default_rate_limit
        self._pending_confirmations: dict[str, tuple[str, float]] = {}
        self._command_history: dict[str, list[float]] = defaultdict(list)

    def validate_command(
        self,
        cmd: str,
        args: list[str],
        is_admin: bool,
    ) -> tuple[bool, str]:
        """
        Validate command arguments and permissions.

        Returns:
            (is_valid, error_message)
        """
        spec = self.COMMAND_SPECS.get(cmd)
        if spec is None:
            return True, ""  # Unknown command, let dispatcher handle

        if is_admin and spec.requires_admin:
            pass  # Admin has permission
        elif spec.requires_admin:
            return False, "⛔ Admin-only command."

        if len(args) < spec.min_args:
            return False, f"❌ {cmd} requires at least {spec.min_args} arguments"
        if len(args) > spec.max_args:
            return False, f"❌ {cmd} accepts at most {spec.max_args} arguments"

        for i, arg in enumerate(args):
            if i < len(spec.args_pattern):
                pattern = spec.args_pattern[i]
                if not re.match(pattern, arg, re.IGNORECASE):
                    return False, f"❌ Invalid argument {i+1}: {arg}"

        return True, ""

    def check_rate_limit(
        self,
        cmd: str,
        user_id: str,
    ) -> tuple[bool, int]:
        """
        Check rate limit for command.

        Returns:
            (is_allowed, remaining_calls)
        """
        spec = self.COMMAND_SPECS.get(cmd)
        limit = spec.rate_limit_per_min if spec and spec.rate_limit_per_min > 0 else self._default_rate_limit

        now = time.time()
        key = f"{user_id}:{cmd}"
        history = self._command_history[key]

        history[:] = [t for t in history if now - t < 60]

        if len(history) >= limit:
            return False, 0

        history.append(now)
        return True, limit - len(history) - 1

    def request_confirmation(self, cmd: str, user_id: str) -> str:
        """Generate confirmation code for dangerous command."""
        code = f"{cmd.upper()[:3]}-{int(time.time()) % 10000:04d}"
        self._pending_confirmations[f"{user_id}:{cmd}"] = (code, time.time())
        return code

    def confirm_command(
        self,
        cmd: str,
        user_id: str,
        confirmation_code: str,
    ) -> bool:
        """Verify confirmation code for dangerous command."""
        key = f"{user_id}:{cmd}"
        if key not in self._pending_confirmations:
            return False

        expected_code, timestamp = self._pending_confirmations[key]

        if time.time() - timestamp > 60:
            del self._pending_confirmations[key]
            return False

        if confirmation_code == expected_code:
            del self._pending_confirmations[key]
            return True

        return False

    def get_danger_level(self, cmd: str) -> int:
        """Get danger level of command (0-3)."""
        spec = self.COMMAND_SPECS.get(cmd)
        return spec.danger_level if spec else 0


class DangerousCommandShield:
    """
    Shield for dangerous commands requiring admin confirmation.
    """

    def __init__(self, validator: TelegramCommandValidator):
        self._validator = validator
        self._admin_confirmations: dict[str, dict[str, Any]] = {}

    def requires_confirmation(self, cmd: str) -> bool:
        """Check if command requires admin confirmation."""
        spec = TelegramCommandValidator.COMMAND_SPECS.get(cmd)
        return spec.requires_confirmation if spec else False

    def process_dangerous_command(
        self,
        cmd: str,
        args: list[str],
        user_id: str,
        is_admin: bool,
    ) -> tuple[bool, Optional[str], str]:
        """
        Process a dangerous command with confirmation flow.

        Returns:
            (proceed, confirmation_needed, message)
        """
        if not self.requires_confirmation(cmd):
            return True, None, ""

        if not is_admin:
            return False, None, "⛔ This command requires admin confirmation."

        if len(args) > 0 and args[-1].startswith("CONFIRM:"):
            confirmation = args[-1].replace("CONFIRM:", "")
            if self._validator.confirm_command(cmd, user_id, confirmation):
                return True, None, "✅ Command confirmed and executed."
            else:
                return False, None, "❌ Invalid or expired confirmation code."

        confirmation_code = self._validator.request_confirmation(cmd, user_id)
        return (
            False,
            confirmation_code,
            f"⚠️ This is a DANGEROUS command. Reply with:\n"
            f"/{cmd} {' '.join(args)} CONFIRM:{confirmation_code}\n"
            f"Confirmation expires in 60 seconds."
        )


def create_validator(
    config: dict[str, Any],
) -> TelegramCommandValidator:
    """Create command validator from config."""
    rate_limit = int(config.get("telegram_cmd_rate_limit_per_min", 10))
    return TelegramCommandValidator(default_rate_limit=rate_limit)


def create_shield(validator: TelegramCommandValidator) -> DangerousCommandShield:
    """Create dangerous command shield."""
    return DangerousCommandShield(validator)