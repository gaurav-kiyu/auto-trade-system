"""Integration 4: Secrets Vault -> Config System.

Wires the Secrets Vault into the configuration system so that config
values can reference vault secrets using a `vault://` prefix. When the
config resolver encounters `vault://my_key`, it automatically retrieves
the decrypted value from the Secrets Vault.

Usage:
    from core.integrations import SecretsConfigBridge, wire_secrets_to_config

    bridge = SecretsConfigBridge()
    value = bridge.resolve("vault://broker.api_key")  # Returns decrypted value
    value = bridge.resolve("plain_config_value")       # Returns as-is
"""

from __future__ import annotations

import logging
import re
from typing import Any

_log = logging.getLogger(__name__)

_VAULT_PREFIX_RE = re.compile(r"^vault://([A-Za-z0-9._-]+)$")


class SecretsConfigBridge:
    """Bridge between Secrets Vault and Config system.

    Resolves `vault://key` prefixed config values by fetching
    the decrypted value from the Secrets Vault.
    """

    def __init__(self) -> None:
        self._vault = None

    def _get_vault(self):
        """Lazy-load vault singleton."""
        if self._vault is None:
            try:
                from core.secrets_vault import get_secrets_vault
                self._vault = get_secrets_vault()
            except ImportError:
                return None
        return self._vault

    def resolve(self, value: Any) -> Any:
        """Resolve a config value, handling vault:// prefixed strings.

        Args:
            value: Config value (string, dict, list, or primitive).

        Returns:
            Resolved value with vault secrets decrypted.
        """
        if isinstance(value, str):
            match = _VAULT_PREFIX_RE.match(value)
            if match:
                vault_key = match.group(1)
                vault = self._get_vault()
                if vault:
                    try:
                        return vault.get(vault_key)
                    except KeyError:
                        _log.warning("[SECRETS_BRIDGE] Vault key '%s' not found", vault_key)
                        return f"{{MISSING_VAULT:{vault_key}}}"
                else:
                    _log.warning("[SECRETS_BRIDGE] Vault not available, cannot resolve '%s'", vault_key)
                    return f"{{VAULT_UNAVAILABLE:{vault_key}}}"
            return value

        if isinstance(value, dict):
            return {k: self.resolve(v) for k, v in value.items()}

        if isinstance(value, list):
            return [self.resolve(item) for item in value]

        return value

    def resolve_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Recursively resolve all vault:// references in a config dict.

        Args:
            config: Raw config dictionary.

        Returns:
            Config with all vault references resolved.
        """
        return {k: self.resolve(v) for k, v in config.items()}


def wire_secrets_to_config() -> bool:
    """Wire Secrets Vault into the Config system.

    Creates a SecretsConfigBridge instance and makes it available
    for config resolution.

    Returns:
        True if wired successfully.
    """
    try:
        from core.secrets_vault import get_secrets_vault
        # Ensure vault is initialized
        get_secrets_vault()
        _log.info("[INTEGRATION] Secrets Vault -> Config: WIRED")
        return True
    except ImportError as exc:
        _log.warning("[INTEGRATION] Secrets Vault -> Config: FAILED (%s)", exc)
        return False
    except Exception as exc:
        _log.warning("[INTEGRATION] Secrets Vault -> Config: ERROR (%s)", exc)
        return False


__all__ = ["SecretsConfigBridge", "wire_secrets_to_config"]
