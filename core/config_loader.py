"""Canonical Config Loader (v2.46)

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

    def __init__(self, config_dir: Path = CONFIG_DIR) -> None:
        self.config_dir = config_dir
        self._cache: dict[str, dict] = {}

    def load(self, environment: str = "base") -> dict[str, Any]:
        """Load configuration for specified environment.

        Args:
            environment: 'base', 'dev', 'paper', 'live'

        Returns:
            Merged configuration dictionary

        Note:
            ``OPBUYING_*`` env vars override keys already present in the merged
            config (case-insensitive, coerced to the existing value's type);
            unknown keys are ignored. ``BROKER_CONFIG.<field>_env`` fields are
            resolved from the named env vars (explicit values win). Env
            overrides are applied at first load and the result is cached, so
            later env changes require a fresh loader instance.

        """
        if environment in self._cache:
            return self._cache[environment]

        config : dict[str, Any] = {}

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

        # Apply environment variable overrides + broker credential bridge
        config = self._apply_env_overrides(config)
        self._resolve_broker_config_env(config)

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
        """Apply ``OPBUYING_*`` environment overrides to existing config keys.

        Mirrors ``index_app.domains.config.loader._apply_opbuying_env_overrides``:
        keys are matched case-insensitively and coerced to the type of the
        existing value. Only keys already present in *config* are overridden
        — ``OPBUYING_*`` variables for unknown keys are ignored (never add new
        keys). Returns a shallow copy with the overrides applied.
        """
        prefix = "OPBUYING_"
        result = dict(config)
        lower_keys = {k.lower(): k for k in result}
        for env_key, env_value in os.environ.items():
            if not env_key.lower().startswith(prefix.lower()):
                continue
            raw_key = env_key[len(prefix):]
            if not raw_key:
                continue
            target_key = lower_keys.get(raw_key.lower())
            if target_key is None:
                continue
            current = result.get(target_key)
            new_value: Any = env_value
            if isinstance(current, bool):
                new_value = env_value.strip().lower() in ("true", "1", "yes", "on")
            elif isinstance(current, int) and not isinstance(current, bool):
                try:
                    new_value = int(env_value)
                except ValueError:
                    logger.debug(
                        "Failed to coerce env %s=%s to int", env_key, env_value,
                    )
            elif isinstance(current, float):
                try:
                    new_value = float(env_value)
                except ValueError:
                    logger.debug(
                        "Failed to coerce env %s=%s to float", env_key, env_value,
                    )
            result[target_key] = new_value
            logger.debug("Env override: %s = %s", target_key, new_value)
        return result

    def _resolve_broker_config_env(self, config: dict) -> int:
        """Resolve ``BROKER_CONFIG.<field>_env`` -> ``BROKER_CONFIG.<field>``.

        Mirrors ``index_app.domains.config.loader._resolve_broker_config_env``:
        config declares e.g. ``api_key_env: "OPBUYING_BROKER_API_KEY"`` — the
        named environment variable supplies the secret. The plain field is
        only filled while empty, so explicit values always win.

        Returns the number of credentials resolved from the environment.
        """
        bc = config.get("BROKER_CONFIG")
        if not isinstance(bc, dict):
            return 0
        resolved = 0
        for env_key in list(bc.keys()):
            if not str(env_key).endswith("_env"):
                continue
            env_name = str(bc.get(env_key) or "")
            plain = str(env_key)[:-4]
            if not env_name or not plain:
                continue
            if bc.get(plain):
                continue  # explicit value wins over env
            value = os.environ.get(env_name, "")
            if value:
                bc[plain] = value
                resolved += 1
        if resolved:
            logger.info(
                "Resolved %d broker credential(s) from environment", resolved,
            )
        return resolved

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
    with _lock:
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
    "SCHEMA_PATH",
    "ConfigLoader",
    "get_effective_config",
    "get_loader",
    "load_config",
    "logger",
]


import threading

_lock = threading.RLock()
