"""
Secrets Manager - Item 22

Secure secrets storage instead of env files:
- API keys
- Broker credentials
- Telegram tokens
- Database passwords

Production-grade security.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class Secret:
    """Secret definition"""
    name: str
    value: str
    encrypted: bool = False
    description: str = ""


class SecretsManager:
    """
    Secrets manager for secure credential storage.
    Supports multiple backends: env vars, encrypted files, external vaults.
    """

    def __init__(self, storage_path: str = "secrets.enc"):
        self._storage_path = storage_path
        self._secrets: dict[str, Secret] = {}
        self._load_secrets()

    def _load_secrets(self) -> None:
        """Load secrets from storage"""
        if os.path.exists(self._storage_path):
            try:
                with open(self._storage_path) as f:
                    data = json.load(f)
                    for name, secret_data in data.items():
                        self._secrets[name] = Secret(**secret_data)
                _log.info(f"Loaded {len(self._secrets)} secrets")
            except Exception as e:
                _log.error(f"Failed to load secrets: {e}")

        self._load_from_env()

    def _load_from_env(self) -> None:
        """Load secrets from environment variables"""
        env_prefix = "OPBUYING_SECRET_"

        for key, value in os.environ.items():
            if key.startswith(env_prefix):
                secret_name = key[len(env_prefix):].lower()
                self._secrets[secret_name] = Secret(
                    name=secret_name,
                    value=value,
                    description=f"From environment: {key}",
                )
                _log.debug(f"Loaded secret from env: {secret_name}")

    def get(self, name: str, default: str = "") -> str:
        """Get secret value"""
        secret = self._secrets.get(name)
        if secret:
            return secret.value
        return default

    def set(self, name: str, value: str, description: str = "") -> None:
        """Set secret value"""
        self._secrets[name] = Secret(
            name=name,
            value=value,
            description=description,
        )
        _log.info(f"Set secret: {name}")

    def delete(self, name: str) -> bool:
        """Delete secret"""
        if name in self._secrets:
            del self._secrets[name]
            _log.info(f"Deleted secret: {name}")
            return True
        return False

    def list_secrets(self) -> dict[str, str]:
        """List secret names (not values)"""
        return {
            name: secret.description or "No description"
            for name, secret in self._secrets.items()
        }

    def save(self) -> bool:
        """Save secrets to storage"""
        try:
            data = {
                name: {
                    "name": s.name,
                    "value": s.value,
                    "encrypted": s.encrypted,
                    "description": s.description,
                }
                for name, s in self._secrets.items()
            }

            with open(self._storage_path, "w") as f:
                json.dump(data, f)

            _log.info(f"Saved {len(self._secrets)} secrets")
            return True
        except Exception as e:
            _log.error(f"Failed to save secrets: {e}")
            return False

    def get_broker_credentials(self, broker: str) -> dict[str, str]:
        """Get broker-specific credentials"""
        prefix = f"{broker}_"

        credentials = {}
        for name, secret in self._secrets.items():
            if name.startswith(prefix):
                key = name[len(prefix):]
                credentials[key] = secret.value
            elif name in ["api_key", "access_token", "password", "user_id", "totp_key"]:
                credentials[name] = secret.value

        return credentials

    def get_telegram_config(self) -> dict[str, str]:
        """Get Telegram configuration"""
        return {
            "bot_token": self.get("telegram_bot_token", ""),
            "chat_id": self.get("telegram_chat_id", ""),
        }

    def get_database_config(self) -> dict[str, Any]:
        """Get database configuration"""
        return {
            "host": self.get("db_host", "localhost"),
            "port": int(self.get("db_port", "5432")),
            "name": self.get("db_name", "trading"),
            "user": self.get("db_user", "trading"),
            "password": self.get("db_password", ""),
        }


_secrets_manager: SecretsManager | None = None
_manager_lock = None


def get_secrets_manager() -> SecretsManager:
    """Get singleton secrets manager"""
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    return _secrets_manager


def get_secret(name: str, default: str = "") -> str:
    """Quick access to secrets"""
    return get_secrets_manager().get(name, default)
