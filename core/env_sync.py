"""
Environment and Config Synchronization Utility

Ensures that changes made via Admin UI (or config.json) are automatically
synchronized to .env, os.environ, and all active runtime service adapters.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Key mapping from config.json keys to corresponding .env variable names
CONFIG_TO_ENV_MAP: dict[str, list[str]] = {
    "BOT_TOKEN": ["OPBUYING_BOT_TOKEN", "OPBUYING_TELEGRAM_BOT_TOKEN"],
    "CHAT_ID": ["OPBUYING_CHAT_ID", "OPBUYING_TELEGRAM_CHAT_ID"],
    "EMAIL_USER": ["OPBUYING_EMAIL_USER", "SMTP_USERNAME"],
    "EMAIL_PASS": ["OPBUYING_EMAIL_PASS", "SMTP_PASSWORD"],
    "EMAIL_SMTP": ["OPBUYING_EMAIL_SMTP", "SMTP_SERVER"],
    "EMAIL_PORT": ["OPBUYING_EMAIL_PORT", "SMTP_PORT"],
    "EMAIL_TO": ["OPBUYING_EMAIL_TO"],
    "EMAIL_ENABLED": ["OPBUYING_EMAIL_ENABLED"],
    "INDEX_MIN_SCORE": ["INDEX_MIN_SCORE", "OPBUYING_INDEX_MIN_SCORE"],
    "MIN_SCORE_THRESHOLD": ["MIN_SCORE_THRESHOLD", "OPBUYING_MIN_SCORE_THRESHOLD"],
    "TG_TRADE_ONLY": ["TG_TRADE_ONLY", "OPBUYING_TG_TRADE_ONLY"],
    "TG_QUIET_MODE": ["TG_QUIET_MODE", "OPBUYING_TG_QUIET_MODE"],
}


def sync_env_file(
    changes: dict[str, Any],
    env_path: Path | str | None = None,
) -> bool:
    """Update .env file on disk with the provided key-value changes.

    Preserves comments and existing formatting. Updates existing keys or
    appends new ones.
    """
    if env_path is None:
        root = Path(__file__).resolve().parent.parent
        target_path = root / ".env"
    else:
        target_path = Path(env_path)

    # Flatten changes to .env key-value pairs
    env_updates: dict[str, str] = {}
    for cfg_key, val in changes.items():
        val_str = str(val) if val is not None else ""
        # Direct OPBUYING_ prefix
        env_updates[f"OPBUYING_{cfg_key}"] = val_str
        # Mapped specific variables
        if cfg_key in CONFIG_TO_ENV_MAP:
            for env_var in CONFIG_TO_ENV_MAP[cfg_key]:
                env_updates[env_var] = val_str

    # Update os.environ immediately for current running process
    for env_var, val_str in env_updates.items():
        os.environ[env_var] = val_str

    if not target_path.exists():
        try:
            lines = [f"{k}={v}\n" for k, v in env_updates.items()]
            target_path.write_text("".join(lines), encoding="utf-8")
            return True
        except OSError as e:
            logger.warning("Failed to create .env file: %s", e)
            return False

    try:
        content = target_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        updated_keys = set()
        new_lines = []

        for line in lines:
            trimmed = line.strip()
            if not trimmed or trimmed.startswith("#") or "=" not in trimmed:
                new_lines.append(line)
                continue

            k, _, _ = trimmed.partition("=")
            k = k.strip()
            if k in env_updates:
                new_lines.append(f"{k}={env_updates[k]}\n")
                updated_keys.add(k)
            else:
                new_lines.append(line)

        # Append any keys that weren't already in the file
        for k, v in env_updates.items():
            if k not in updated_keys and k in (
                "OPBUYING_BOT_TOKEN", "OPBUYING_CHAT_ID", "OPBUYING_TELEGRAM_BOT_TOKEN",
                "OPBUYING_TELEGRAM_CHAT_ID", "SMTP_USERNAME", "SMTP_PASSWORD",
                "SMTP_SERVER", "SMTP_PORT", "OPBUYING_EMAIL_USER", "OPBUYING_EMAIL_PASS",
            ):
                new_lines.append(f"{k}={v}\n")

        target_path.write_text("".join(new_lines), encoding="utf-8")
        logger.info("[ENV_SYNC] Synchronized %d variables to %s", len(env_updates), target_path)
        return True
    except OSError as e:
        logger.warning("[ENV_SYNC] Failed to write to .env file: %s", e)
        return False
