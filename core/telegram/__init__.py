"""Telegram integration — secure bot communication, authentication, and audit."""

from core.telegram.hardening import (
    CommandSpec,
    DangerousCommandShield,
    TelegramCommandValidator,
    create_shield,
    create_validator,
)

__all__ = [
    "CommandSpec",
    "DangerousCommandShield",
    "TelegramCommandValidator",
    "create_shield",
    "create_validator",
]
