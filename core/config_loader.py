"""
Canonical Config Loader (v2.46)

Unified configuration system supporting YAML config files.
Replaces fragmented JSON config approach.

Structure:
  config/
    base.yaml      - defaults for all environments
    dev.yaml      - development overrides
    paper.yaml    - paper trading overrides
    live.yaml     - live trading overrides

Usage:
    from core.config_loader import load_config
    cfg = load_config('dev')  # Loads base.yaml + dev.yaml
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("config_loader")

CONFIG_DIR = Path("config")
SCHEMA_PATH = Path("schemas")


class ConfigLoader:
    """Unified configuration loader with YAML support."""

    def __init__(self, config_dir: Path = CONFIG_DIR):
        self.config_dir = config_dir
        self._cache: dict[str, dict] = {}

    def load(self, environment: str = "base") -> dict[str, Any]:
        """
        Load configuration for specified environment.

        Args:
            environment: 'base', 'dev', 'paper', 'live'

        Returns:
            Merged configuration dictionary
        """
        if environment in self._cache:
            return self._cache[environment]

        config = {}

        # Load base config first
        base_path = self.config_dir / "base.yaml"
        if base_path.exists():
            with open(base_path) as f:
                base_cfg = yaml.safe_load(f) or {}
                config = self._deep_merge(config, base_cfg)
                logger.info(f"Loaded base config from {base_path}")

        # Load environment-specific config
        if environment != "base":
            env_path = self.config_dir / f"{environment}.yaml"
            if env_path.exists():
                with open(env_path) as f:
                    env_cfg = yaml.safe_load(f) or {}
                    config = self._deep_merge(config, env_cfg)
                    logger.info(f"Loaded {environment} config from {env_path}")
            else:
                logger.warning(f"Config file not found: {env_path}")

        # Apply environment variable overrides
        config = self._apply_env_overrides(config)

        # Store in cache
        self._cache[environment] = config

        return config

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """Deep merge two dictionaries."""
        result = dict(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _apply_env_overrides(self, config: dict) -> dict:
        """Apply OPBUYING_* environment variable overrides."""
        result = dict(config)
        for key, value in os.environ.items():
            if key.startswith("OPBUYING_"):
                config_key = key[9:]  # Remove OPBUYING_ prefix
                # Try to parse as appropriate type
                parsed = self._parse_env_value(value)
                result[config_key] = parsed
                logger.debug(f"Env override: {config_key} = {parsed}")
        return result

    def _parse_env_value(self, value: str) -> Any:
        """Parse environment variable value to appropriate type."""
        # Try bool
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False

        # Try int
        try:
            return int(value)
        except ValueError as e:
            logger.debug("[CONFIG_LOADER] non-critical error: %s", e)

        # Try float
        try:
            return float(value)
        except ValueError as e:
            logger.debug("[CONFIG_LOADER] non-critical error: %s", e)

        # Return as string
        return value

    def validate_schema(self, config: dict, schema_name: str = "index_config") -> bool:
        """Validate configuration against schema."""
        schema_path = SCHEMA_PATH / f"{schema_name}.schema.json"
        if not schema_path.exists():
            logger.warning(f"Schema not found: {schema_path}")
            return True

        # Schema validation would go here
        # For now, just return True
        return True

    def get_effective_config(self, environment: str = "base") -> dict[str, Any]:
        """Get effective configuration with validation."""
        config = self.load(environment)
        self.validate_schema(config)
        return config


# Singleton instance
_loader: ConfigLoader | None = None


def get_loader() -> ConfigLoader:
    """Get singleton config loader."""
    global _loader
    if _loader is None:
        _loader = ConfigLoader()
    return _loader


def load_config(environment: str = "base") -> dict[str, Any]:
    """Convenience function to load configuration."""
    return get_loader().load(environment)


def get_effective_config(environment: str = "base") -> dict[str, Any]:
    """Convenience function to get validated effective configuration."""
    return get_loader().get_effective_config(environment)


__all__ = [
    "CONFIG_DIR",
    "ConfigLoader",
    "SCHEMA_PATH",
    "get_effective_config",
    "get_loader",
    "load_config",
    "logger",
]

