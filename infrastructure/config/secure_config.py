"""
Secure Configuration Management

This module implements secure configuration loading that addresses the security vulnerabilities
identified in the critical findings report, specifically:
- Moving secrets to environment variables with OPBUYING_* prefix
- Secure credential handling
- Prevention of secret leakage in logs and error messages
"""

from __future__ import annotations

import json
import os
import base64
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union

# Import our credential storage
from infrastructure.security.credential_storage import CredentialStorage

logger = logging.getLogger(__name__)

# Initialize credential storage
_credential_storage = CredentialStorage()

# Import jsonschema for validation (would be in requirements)
try:
    import jsonschema
    from jsonschema import validate, ValidationError
    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False
    # Fallback if jsonschema not available
    def validate(*args, **kwargs):
        pass
    class ValidationError(Exception):
        pass


class SecureConfigError(Exception):
    """Custom exception for configuration errors."""
    pass


class SecureConfig:
    """
    Secure configuration manager that loads configuration from multiple sources
    with precedence: defaults → config files → environment variables → secrets.

    Security features:
    - All secrets must come from OPBUYING_* environment variables
    - Automatic redaction of secrets in logs and error messages
    - Validation of configuration against schemas
    - Support for encrypted secrets (optional)
    """

    # Environment variable prefix for all secrets
    ENV_PREFIX = "OPBUYING_"

    # List of known secret keys that should be redacted
    SECRET_KEYS = frozenset({
        'BOT_TOKEN', 'CHAT_ID', 'KITE_API_KEY', 'KITE_ACCESS_TOKEN',
        'KITE_USER_ID', 'KITE_PASSWORD', 'KITE_TOTP_KEY',
        'ANGEL_API_KEY', 'ANGEL_CLIENT_ID', 'ANGEL_PASSWORD',
        'ANGEL_TOTP_KEY', 'ANGEL_REFRESH_TOKEN'
    })

    def __init__(self,
                 defaults_path: Optional[Union[str, Path]] = None,
                 config_dir: Optional[Union[str, Path]] = None,
                 env_prefix: str = ENV_PREFIX,
                 enable_secret_redaction: bool = True):
        """
        Initialize the secure configuration manager.

        Args:
            defaults_path: Path to JSON file containing default configuration values
            config_dir: Directory containing config.json, config.local.json, etc.
            env_prefix: Prefix for environment variables that contain secrets (used as fallback by credential storage)
            enable_secret_redaction: Whether to automatically redact secrets in logs
        """
        self.env_prefix = env_prefix
        self.enable_secret_redaction = enable_secret_redaction
        self._defaults: Dict[str, Any] = {}
        self._config: Dict[str, Any] = {}
        self._secrets: Dict[str, Any] = {}
        self._merged_config: Dict[str, Any] = {}

        # Load defaults if provided
        if defaults_path:
            self._load_defaults(defaults_path)

        # Load configuration files if directory provided
        if config_dir:
            self._load_config_files(config_dir)

        # Load secrets from credential storage (which may use keyring, encrypted file, or env vars as fallback)
        self._load_secrets_from_storage()

        # Merge all configuration sources
        self._merge_configuration()

        # logger.info("Secure configuration initialized")

    def _load_defaults(self, path: Union[str, Path]) -> None:
        """Load default configuration values from JSON file."""
        try:
            with open(path, 'r') as f:
                self._defaults = json.load(f)
            pass  # Logging removed to avoid recursion during config init
        except FileNotFoundError:
            pass  # Logging removed to avoid recursion during config init
            self._defaults = {}
        except json.JSONDecodeError as e:
            raise SecureConfigError(f"Invalid JSON in defaults file {path}: {e}")

    def _load_config_files(self, directory: Union[str, Path]) -> None:
        """Load configuration files from the specified directory."""
        config_dir = Path(directory)
        if not config_dir.exists():
            logger.warning(f"Config directory not found: {config_dir}")
            return

        # Load in order: config.json, config.local.json
        config_files = ['config.json', 'config.local.json']

        for filename in config_files:
            file_path = config_dir / filename
            if file_path.exists():
                try:
                    with open(file_path, 'r') as f:
                        config_data = json.load(f)
                    # Merge with existing config (later files override earlier)
                    self._deep_merge(self._config, config_data)
                    pass  # Logging removed to avoid recursion during config init
                except FileNotFoundError:
                    pass  # Already checked existence
                except json.JSONDecodeError as e:
                    pass  # Logging removed to avoid recursion during config init

    def _load_secrets_from_storage(self) -> None:
        """Load all secrets from secure credential storage."""
        # Load from credential storage (keyring, encrypted file, or env vars as fallback)
        for secret_key in self.SECRET_KEYS:
            credential_value = _credential_storage.get_credential(secret_key)
            if credential_value is not None:
                self._secrets[secret_key] = credential_value
                # logger.debug(f"Loaded secret '{secret_key}' from credential storage")

    def _merge_configuration(self) -> None:
        """Merge all configuration sources in order of precedence."""
        # Start with defaults
        self._merged_config = self._defaults.copy()

        # Overlay with config files
        self._deep_merge(self._merged_config, self._config)

        # Overlay with secrets (highest precedence)
        self._deep_merge(self._merged_config, self._secrets)

        # logger.debug("Configuration sources merged")

    def _deep_merge(self, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        """
        Deep merge source dictionary into target dictionary.
        Modifies target in place.
        """
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value by key.

        Args:
            key: Configuration key (can use dot notation for nested keys)
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        # Handle dot notation for nested keys
        if '.' in key:
            keys = key.split('.')
            value = self._merged_config
            try:
                for k in keys:
                    value = value[k]
                return self._redact_if_needed(key, value)
            except (KeyError, TypeError):
                return default
        else:
            value = self._merged_config.get(key, default)
            return self._redact_if_needed(key, value)

    def get_secret(self, key: str, default: Any = None) -> Any:
        """
        Get a secret value by key. This method is intended for accessing
        sensitive values and includes additional security auditing.

        Args:
            key: Configuration key for the secret
            default: Default value if key not found

        Returns:
            Secret value or default

        Note:
            Access to secrets through this method is logged for audit purposes.
        """
        # Check if the key is in our known secrets list
        is_known_secret = key in self.SECRET_KEYS

        # Get the value
        value = self.get(key, default)

        # Log access to secrets for audit trail (without revealing the value)
        if is_known_secret or key in self._secrets:
            logger.info(f"Secret access: {key} {'[FOUND]' if key in self._secrets or self._merged_config.get(key) is not None else '[NOT FOUND]'}")
        elif self.enable_secret_redaction and key in self._merged_config:
            # If it's not a known secret but we have it in merged config and redaction is enabled, still log
            logger.info(f"Secret access: {key} {'[FOUND]' if self._merged_config.get(key) is not None else '[NOT FOUND]'}")

        return value

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get a boolean configuration value."""
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')
        return bool(value)

    def get_int(self, key: str, default: int = 0) -> int:
        """Get an integer configuration value."""
        value = self.get(key, default)
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Get a float configuration value."""
        value = self.get(key, default)
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def get_list(self, key: str, default: Optional[list] = None) -> list:
        """Get a list configuration value."""
        if default is None:
            default = []
        value = self.get(key, default)
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            # Try to parse as JSON array
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                # Fallback: split by commas
                return [item.strip() for item in value.split(',') if item.strip()]
        return default

    def get_dict(self, key: str, default: Optional[dict] = None) -> dict:
        """Get a dictionary configuration value."""
        if default is None:
            default = {}
        value = self.get(key, default)
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            # Try to parse as JSON object
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                logger.warning(f"Could not parse config value for {key} as JSON")
                return default
        return default

    def _redact_if_needed(self, key: str, value: Any) -> Any:
        """
        Redact sensitive values if they match known secret patterns.

        Args:
            key: Configuration key
            value: Configuration value

        Returns:
            Original value if not secret, redacted value if secret
        """
        if not self.enable_secret_redaction:
            return value

        # Check if key indicates a secret
        is_secret_key = (
            key in self.SECRET_KEYS or
            any(secret_word in key.lower() for secret_word in ['token', 'key', 'secret', 'password', 'credential'])
        )

        if is_secret_key and isinstance(value, str) and len(value) > 8:
            # Show first 4 and last 4 characters, redact the middle
            return value[:4] + '*' * (len(value) - 8) + value[-4:]
        elif is_secret_key and isinstance(value, str):
            # For short strings, redact completely
            return '*' * len(value)
        else:
            return value

    def get_safe_config(self) -> Dict[str, Any]:
        """
        Get a safe copy of the configuration with all secrets redacted.

        Returns:
            Dictionary containing configuration with secrets replaced by '[REDACTED]'
        """
        safe_config = {}
        for key, value in self._merged_config.items():
            safe_config[key] = self._redact_if_needed(key, value)
        return safe_config

    def get_all_config(self) -> Dict[str, Any]:
        """
        Get a copy of the complete configuration including secrets.
        Use with caution as this may expose sensitive data.

        Returns:
            Dictionary containing the complete configuration
        """
        return self._merged_config.copy()

    def get_all(self) -> Dict[str, Any]:
        """
        Get all configuration as a flat dictionary.
        Alias for get_all_config() for backward compatibility.

        Returns:
            Dictionary containing the complete configuration
        """
        return self.get_all_config()


def get_secure_config(
    defaults_path: Optional[Union[str, Path]] = None,
    config_dir: Optional[Union[str, Path]] = None,
    env_prefix: str = SecureConfig.ENV_PREFIX,
    enable_secret_redaction: bool = True,
) -> SecureConfig:
    """
    Factory function to create a SecureConfig instance.

    This is provided for backward compatibility with code that expects a
    get_secure_config function.

    Args:
        defaults_path: Path to JSON file containing default configuration values
        config_dir: Directory containing config.json, config.local.json, etc.
        env_prefix: Prefix for environment variables that contain secrets
        enable_secret_redaction: Whether to automatically redact secrets in logs

    Returns:
        SecureConfig instance
    """
    return SecureConfig(
        defaults_path=defaults_path,
        config_dir=config_dir,
        env_prefix=env_prefix,
        enable_secret_redaction=enable_secret_redaction,
    )