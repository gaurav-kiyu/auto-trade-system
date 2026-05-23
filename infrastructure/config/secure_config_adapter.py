"""
Secure Config Adapter

Adapter that implements the ConfigPort interface using the existing SecureConfig class.
This allows the trading logic to depend on the abstraction (ConfigPort) rather than the concrete implementation.
"""

from __future__ import annotations

from typing import Any, Optional, Union
from pathlib import Path

# Import the port interface
from core.ports.config import ConfigPort

# Import our secure configuration implementation
from infrastructure.config.secure_config import SecureConfig


class SecureConfigAdapter(ConfigPort):
    """
    Adapter that implements ConfigPort using the existing SecureConfig class.

    This follows the Dependency Inversion Principle - high-level modules (trading logic)
    depend on abstractions (ConfigPort), not concretions (SecureConfig).
    """

    def __init__(self,
                 defaults_path: Optional[Union[str, Path]] = None,
                 config_dir: Optional[Union[str, Path]] = None,
                 env_prefix: str = "OPBUYING_",
                 enable_secret_redaction: bool = True):
        """
        Initialize the secure configuration adapter.

        Args:
            defaults_path: Path to JSON file containing default configuration values
            config_dir: Directory containing config.json, config.local.json, etc.
            env_prefix: Prefix for environment variables that contain secrets
            enable_secret_redaction: Whether to automatically redact secrets in logs
        """
        self._secure_config = SecureConfig(
            defaults_path=defaults_path,
            config_dir=config_dir,
            env_prefix=env_prefix,
            enable_secret_redaction=enable_secret_redaction
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by key."""
        return self._secure_config.get(key, default)

    def get_secret(self, key: str, default: Any = None) -> Any:
        """Get a secret value by key with security auditing."""
        return self._secure_config.get_secret(key, default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get a boolean configuration value."""
        return self._secure_config.get_bool(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        """Get an integer configuration value."""
        return self._secure_config.get_int(key, default)

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Get a float configuration value."""
        return self._secure_config.get_float(key, default)

    def get_safe_config(self) -> dict[str, Any]:
        """Get a safe copy of the configuration with all secrets redacted."""
        return self._secure_config.get_safe_config()

    def get_all(self) -> dict[str, Any]:
        """Get all configuration as a dictionary."""
        return self._secure_config.get_all()

    def keys(self) -> list[str]:
        """Return all config keys for dict() conversion."""
        return list(self._secure_config.get_all().keys())

    def values(self) -> list[Any]:
        """Return all config values."""
        return list(self._secure_config.get_all().values())

    def items(self) -> list[tuple[str, Any]]:
        """Return all config (key, value) pairs."""
        return list(self._secure_config.get_all().items())

    def __contains__(self, key: str) -> bool:
        """Check if a key exists in config."""
        return key in self._secure_config.get_all()

    def __iter__(self):
        """Iterate over config keys."""
        return iter(self._secure_config.get_all())

    def __getitem__(self, key: str) -> Any:
        """Allow dict-like access."""
        return self._secure_config.get(key)

    def __len__(self) -> int:
        """Return the number of config keys."""
        return len(self._secure_config.get_all())

    def __dict__(self) -> dict:
        """Return config as dict for dict() conversion."""
        return self._secure_config.get_all()