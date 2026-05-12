"""
Configuration Port Interface

This interface defines the contract for configuration management.
It decouples the trading logic from specific configuration implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ConfigPort(ABC):
    """
    Abstract base class defining the configuration interface.

    All configuration managers (secure config, file config, env config, etc.)
    must implement this interface. This enables the trading logic to remain
    configuration provider-agnostic.
    """

    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value by key.

        Args:
            key: Configuration key (can use dot notation for nested keys)
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def get_bool(self, key: str, default: bool = False) -> bool:
        """
        Get a boolean configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Boolean configuration value
        """
        pass

    @abstractmethod
    def get_int(self, key: str, default: int = 0) -> int:
        """
        Get an integer configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Integer configuration value
        """
        pass

    @abstractmethod
    def get_float(self, key: str, default: float = 0.0) -> float:
        """
        Get a float configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Float configuration value
        """
        pass

    @abstractmethod
    def get_safe_config(self) -> dict[str, Any]:
        """
        Get a safe copy of the configuration with all secrets redacted.

        Returns:
            Dictionary containing configuration with secrets replaced by '[REDACTED]'
        """
        pass
