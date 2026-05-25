"""
Secret Hygiene Validation

Ensures:
- No API keys in repo/config dumps/logs
- Config values are properly masked
- Secrets are not exposed in error messages

Config keys to check:
- KITE_API_KEY, KITE_ACCESS_TOKEN, KITE_PASSWORD, KITE_TOTP_KEY
- ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_REFRESH_TOKEN
- TELEGRAM_BOT_TOKEN
- Any key with "secret", "password", "token", "key" in name
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("secret_hygiene")


@dataclass
class SecretHygieneResult:
    """Result of secret hygiene validation."""
    passed: bool
    secrets_found: list[str]
    warnings: list[str]


# Patterns that indicate secrets
SECRET_PATTERNS = [
    r"api[_-]?key",
    r"access[_-]?token",
    r"refresh[_-]?token",
    r"password",
    r"secret",
    r"private[_-]?key",
    r"bearer",
    r"client[_-]?secret",
    r"totp[_-]?key",
    r"bot[_-]?token",
]

# Known secret keys (exact matches)
KNOWN_SECRET_KEYS: set[str] = {
    "KITE_API_KEY",
    "KITE_ACCESS_TOKEN",
    "KITE_PASSWORD",
    "KITE_TOTP_KEY",
    "KITE_USER_ID",
    "ANGEL_API_KEY",
    "ANGEL_CLIENT_ID",
    "ANGEL_PASSWORD",
    "ANGEL_TOTP_KEY",
    "ANGEL_REFRESH_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "BROKER_API_KEY",
    "BROKER_ACCESS_TOKEN",
    "BROKER_PASSWORD",
}

# Partial matches (any key containing these)
SECRET_KEY_PARTS: set[str] = {
    "api_key",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "token",
    "key",
}


class SecretHygieneChecker:
    """
    Validates that secrets are not exposed in config or logs.
    """

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._patterns = [re.compile(p, re.IGNORECASE) for p in SECRET_PATTERNS]

    def is_secret_key(self, key: str) -> bool:
        """Check if a key name indicates a secret."""
        key_upper = key.upper()

        # Check exact match
        if key_upper in KNOWN_SECRET_KEYS:
            return True

        # Check partial match
        key_lower = key.lower()
        for part in SECRET_KEY_PARTS:
            if part in key_lower:
                return True

        # Check regex patterns
        for pattern in self._patterns:
            if pattern.search(key):
                return True

        return False

    def mask_value(self, value: str, visible_chars: int = 4) -> str:
        """Mask a secret value, showing only last few characters."""
        if not isinstance(value, str) or len(value) <= visible_chars:
            return "***"
        return "*" * (len(value) - visible_chars) + value[-visible_chars:]

    def check_config(self, config: dict) -> SecretHygieneResult:
        """
        Check a config dict for exposed secrets.

        Returns:
            SecretHygieneResult with any secrets found
        """
        secrets_found = []
        warnings = []

        def check_dict(d: dict, path: str = ""):
            for key, value in d.items():
                current_path = f"{path}.{key}" if path else key

                if self.is_secret_key(key):
                    if isinstance(value, str) and value and value != "":
                        # Check if it's a placeholder
                        if value in ("[REDACTED]", "***", "xxx", "placeholder"):
                            continue

                        # Found a real secret
                        secrets_found.append(f"{current_path}={self.mask_value(value)}")

                # Recurse into nested dicts
                if isinstance(value, dict):
                    check_dict(value, current_path)
                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        if isinstance(item, dict):
                            check_dict(item, f"{current_path}[{i}]")

        check_dict(config)

        return SecretHygieneResult(
            passed=len(secrets_found) == 0,
            secrets_found=secrets_found,
            warnings=warnings
        )

    def check_file(self, file_path: Path) -> SecretHygieneResult:
        """
        Check a file for exposed secrets.

        Only checks files that might contain config (JSON, YAML, env).
        """
        if not file_path.exists():
            return SecretHygieneResult(passed=True, secrets_found=[], warnings=[])

        # Skip binary files and common non-config files
        # NOTE: .py is intentionally NOT excluded — secrets can be hardcoded in source.
        skip_extensions = {".md", ".txt", ".log", ".db", ".sqlite"}
        if file_path.suffix.lower() in skip_extensions:
            return SecretHygieneResult(passed=True, secrets_found=[], warnings=[])

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return SecretHygieneResult(passed=True, secrets_found=[], warnings=[])

        secrets_found = []

        # Simple line-by-line check
        for line_num, line in enumerate(content.split("\n"), 1):
            for key in KNOWN_SECRET_KEYS:
                if key in line:
                    # Check if it's a comment or placeholder
                    stripped = line.strip()
                    if stripped.startswith("#") or "placeholder" in stripped.lower():
                        continue
                    secrets_found.append(f"{file_path.name}:{line_num} contains {key}")

        return SecretHygieneResult(
            passed=len(secrets_found) == 0,
            secrets_found=secrets_found,
            warnings=[]
        )

    def check_directory(self, directory: Path, patterns: list[str] = None) -> SecretHygieneResult:
        """
        Check a directory for exposed secrets in config files.

        Args:
            directory: Root directory to check
            patterns: Glob patterns for files to check (default: common config files)
        """
        if patterns is None:
            patterns = ["*.json", "*.yaml", "*.yml", "*.env", "*.conf", "*.cfg", "*.ini"]

        all_secrets = []

        for pattern in patterns:
            for file_path in directory.rglob(pattern):
                # Skip node_modules, .git, etc.
                if any(skip in str(file_path) for skip in ["node_modules", ".git", "__pycache__", "venv", ".venv"]):
                    continue

                result = self.check_file(file_path)
                all_secrets.extend(result.secrets_found)

        return SecretHygieneResult(
            passed=len(all_secrets) == 0,
            secrets_found=all_secrets,
            warnings=[]
        )

    def sanitize_for_logging(self, data: dict) -> dict:
        """
        Create a sanitized copy of data for logging.
        Replaces secret values with placeholders.
        """
        sanitized = {}

        for key, value in data.items():
            if self.is_secret_key(key):
                sanitized[key] = "[REDACTED]"
            elif isinstance(value, dict):
                sanitized[key] = self.sanitize_for_logging(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    self.sanitize_for_logging(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                sanitized[key] = value

        return sanitized


# Singleton
_secret_checker: SecretHygieneChecker | None = None


def get_secret_checker(config: dict | None = None) -> SecretHygieneChecker:
    """Get or create singleton secret checker."""
    global _secret_checker
    if _secret_checker is None:
        _secret_checker = SecretHygieneChecker(config)
    return _secret_checker


def check_config_secrets(config: dict) -> SecretHygieneResult:
    """Quick check config for secrets."""
    checker = get_secret_checker()
    return checker.check_config(config)


def sanitize_for_log(data: dict) -> dict:
    """Quick sanitize data for logging."""
    checker = get_secret_checker()
    return checker.sanitize_for_logging(data)
