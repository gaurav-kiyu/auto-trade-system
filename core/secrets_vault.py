"""Secrets Vault — Centralized Secrets Management (Constitution v4.0).

Provides encryption-at-rest for sensitive configuration values, API keys,
tokens, and credentials. Supports key rotation, access audit logging, and
environment-specific secret overrides.

Architecture Standard: Secrets Management
Constitution Principle: Security by Design, Privacy by Design

Usage:
    from core.secrets_vault import get_secrets_vault

    vault = get_secrets_vault(master_key_env="OPBUYING_VAULT_KEY")

    # Store a secret
    vault.set("broker.api_key", "kite12345")

    # Retrieve a secret
    api_key = vault.get("broker.api_key")

    # Rotate a secret
    vault.rotate("broker.api_key", "new_kite_key")

    # List all secret keys
    keys = vault.list_keys()
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


# ── Encryption helpers (AES-like using hashlib for key derivation) ───────────


def _derive_key(master_key: str, salt: str) -> bytes:
    """Derive an encryption key from the master key.

    Uses SHA-256 for key derivation. In production, use PBKDF2 or Argon2.
    """
    return sha256(f"{master_key}:{salt}".encode()).digest()


def _simple_encrypt(plaintext: str, key: bytes) -> str:
    """Simple XOR-based encryption with base64 encoding.

    NOTE: Not production-grade encryption. For production, use Fernet or AES-GCM.
    This provides obfuscation + basic protection against casual inspection.
    """
    data = plaintext.encode("utf-8")
    encrypted = bytearray(len(data))
    for i in range(len(data)):
        encrypted[i] = data[i] ^ key[i % len(key)]
    return base64.b64encode(bytes(encrypted)).decode("utf-8")


def _simple_decrypt(ciphertext: str, key: bytes) -> str:
    """Decrypt data encrypted with _simple_encrypt."""
    try:
        data = base64.b64decode(ciphertext.encode("utf-8"))
        decrypted = bytearray(len(data))
        for i in range(len(data)):
            decrypted[i] = data[i] ^ key[i % len(key)]
        return decrypted.decode("utf-8")
    except Exception:
        return ""


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class SecretEntry:
    """A single secret entry in the vault."""

    key: str = ""
    encrypted_value: str = ""
    salt: str = ""
    version: int = 1
    created_at: float = 0.0
    updated_at: float = 0.0
    rotated_at: float = 0.0
    tags: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "rotated_at": self.rotated_at,
            "tags": self.tags,
            "description": self.description,
            # NEVER include the encrypted value in dict output
        }


@dataclass
class AuditEntry:
    """Audit log entry for vault access."""

    action: str = ""  # get, set, delete, rotate, list
    key: str = ""
    timestamp: float = 0.0
    source: str = ""
    success: bool = True
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "key": self.key,
            "timestamp": self.timestamp,
            "source": self.source,
            "success": self.success,
            "detail": self.detail,
        }


# ── Secrets Vault ───────────────────────────────────────────────────────────


class SecretsVault:
    """Centralized secrets vault with encryption, rotation, and audit.

    Thread-safe. Persisted to encrypted JSON file.

    Args:
        master_key: Master encryption key (if not provided, reads from
                    OPBUYING_VAULT_KEY env var, or generates a file-based key).
        vault_path: Path to the vault file.
    """

    def __init__(self, master_key: str = "", vault_path: str = "") -> None:
        self._lock = threading.RLock()
        self._vault_path = Path(vault_path or "data/secrets.vault.json")
        self._audit_path = Path("data/secrets.audit.jsonl")
        self._secrets: dict[str, SecretEntry] = {}
        self._audit_log: list[AuditEntry] = []
        self._max_audit = 1000
        self._master_key = master_key
        self._initialized = False
        self._init_vault()

    def _init_vault(self) -> None:
        """Initialize the vault and load existing secrets."""
        # Resolve master key
        if not self._master_key:
            self._master_key = os.environ.get("OPBUYING_VAULT_KEY", "")
        if not self._master_key:
            # Generate a file-based key if none configured
            key_file = Path("data/.vault_key")
            if key_file.is_file():
                self._master_key = key_file.read_text().strip()
            else:
                import uuid
                self._master_key = str(uuid.uuid4()).replace("-", "")
                key_file.parent.mkdir(parents=True, exist_ok=True)
                key_file.write_text(self._master_key)
                _log.info("[VAULT] Generated new vault key at %s", key_file)

        # Load vault
        self._load_vault()
        self._initialized = True

    # ── Public API ────────────────────────────────────────────────────────

    def set(self, key: str, value: str, tags: list[str] | None = None,
            description: str = "") -> bool:
        """Store a secret.

        Args:
            key: Secret identifier (e.g., 'broker.api_key').
            value: Secret value to encrypt and store.
            tags: Optional tags for filtering.
            description: Optional description.

        Returns:
            True if stored successfully.
        """
        with self._lock:
            salt = str(time.time())
            enc_key = _derive_key(self._master_key, salt)
            encrypted = _simple_encrypt(value, enc_key)

            now = time.time()
            existing = self._secrets.get(key)
            if existing:
                existing.encrypted_value = encrypted
                existing.salt = salt
                existing.version += 1
                existing.updated_at = now
                existing.tags = [t.strip().lower() for t in (tags or []) if t.strip()]
                existing.description = description.strip()
            else:
                self._secrets[key] = SecretEntry(
                    key=key,
                    encrypted_value=encrypted,
                    salt=salt,
                    version=1,
                    created_at=now,
                    updated_at=now,
                    tags=[t.strip().lower() for t in (tags or []) if t.strip()],
                    description=description.strip(),
                )

            self._persist_vault()
            self._audit("set", key, True)
            _log.debug("[VAULT] Set secret '%s' (v%d)", key, self._secrets[key].version)
            return True

    def get(self, key: str) -> str:
        """Retrieve a decrypted secret.

        Args:
            key: Secret identifier.

        Returns:
            Decrypted secret value, or empty string if not found.

        Raises:
            KeyError: If the secret key does not exist.
        """
        with self._lock:
            entry = self._secrets.get(key)
            if entry is None:
                self._audit("get", key, False, "not_found")
                raise KeyError(f"Secret '{key}' not found")

            enc_key = _derive_key(self._master_key, entry.salt)
            value = _simple_decrypt(entry.encrypted_value, enc_key)
            if not value:
                self._audit("get", key, False, "decryption_failed")
                return ""

            self._audit("get", key, True)
            return value

    def get_or_none(self, key: str) -> str | None:
        """Retrieve a decrypted secret, returning None if not found."""
        try:
            return self.get(key)
        except KeyError:
            return None

    def delete(self, key: str) -> bool:
        """Delete a secret.

        Returns True if deleted, False if not found.
        """
        with self._lock:
            if key in self._secrets:
                del self._secrets[key]
                self._persist_vault()
                self._audit("delete", key, True)
                return True
            self._audit("delete", key, False, "not_found")
            return False

    def rotate(self, key: str, new_value: str) -> bool:
        """Rotate a secret to a new value (updates version and rotation timestamp).

        Args:
            key: Secret identifier.
            new_value: New secret value.

        Returns:
            True if rotated, False if not found.
        """
        with self._lock:
            entry = self._secrets.get(key)
            if entry is None:
                self._audit("rotate", key, False, "not_found")
                return False

            salt = str(time.time())
            enc_key = _derive_key(self._master_key, salt)
            encrypted = _simple_encrypt(new_value, enc_key)

            entry.encrypted_value = encrypted
            entry.salt = salt
            entry.version += 1
            entry.updated_at = time.time()
            entry.rotated_at = time.time()

            self._persist_vault()
            self._audit("rotate", key, True)
            _log.info("[VAULT] Rotated secret '%s' (v%d)", key, entry.version)
            return True

    def exists(self, key: str) -> bool:
        """Check if a secret exists."""
        with self._lock:
            return key in self._secrets

    def list_keys(self, tag: str = "") -> list[str]:
        """List all secret keys, optionally filtered by tag."""
        with self._lock:
            keys = list(self._secrets.keys())
        if tag:
            clean_tag = tag.lower()
            return [k for k in keys if clean_tag in (self._secrets[k].tags or [])]
        return sorted(keys)

    def get_metadata(self, key: str) -> SecretEntry | None:
        """Get secret metadata (without the decrypted value)."""
        with self._lock:
            return self._secrets.get(key)

    def get_audit_log(self, limit: int = 50, action: str = "") -> list[AuditEntry]:
        """Get the audit log, optionally filtered by action."""
        with self._lock:
            entries = list(self._audit_log)
        if action:
            entries = [e for e in entries if e.action == action]
        return entries[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """Get vault statistics."""
        with self._lock:
            now = time.time()
            total = len(self._secrets)
            by_tag: dict[str, int] = {}
            rotated_recently = 0
            for s in self._secrets.values():
                for t in (s.tags or []):
                    by_tag[t] = by_tag.get(t, 0) + 1
                if s.rotated_at and (now - s.rotated_at) < 86400 * 90:
                    rotated_recently += 1

            return {
                "total_secrets": total,
                "total_versions": sum(s.version for s in self._secrets.values()),
                "rotated_in_90_days": rotated_recently,
                "by_tag": by_tag,
                "audit_entries": len(self._audit_log),
                "vault_path": str(self._vault_path),
                "initialized": self._initialized,
                "has_master_key": bool(self._master_key),
            }

    # ── Internal ──────────────────────────────────────────────────────────

    def _audit(self, action: str, key: str, success: bool, detail: str = "") -> None:
        """Record an audit entry."""
        entry = AuditEntry(
            action=action,
            key=key,
            timestamp=time.time(),
            source="vault",
            success=success,
            detail=detail,
        )
        self._audit_log.append(entry)
        if len(self._audit_log) > self._max_audit:
            self._audit_log = self._audit_log[-self._max_audit:]
        self._persist_audit()

    def _persist_vault(self) -> None:
        """Persist secrets vault to disk (encrypted)."""
        try:
            self._vault_path.parent.mkdir(parents=True, exist_ok=True)
            data = {k: {
                "key": v.key,
                "encrypted_value": v.encrypted_value,
                "salt": v.salt,
                "version": v.version,
                "created_at": v.created_at,
                "updated_at": v.updated_at,
                "rotated_at": v.rotated_at,
                "tags": v.tags,
                "description": v.description,
            } for k, v in self._secrets.items()}
            self._vault_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.warning("[VAULT] Persist error: %s", exc)

    def _load_vault(self) -> None:
        """Load secrets vault from disk."""
        try:
            if self._vault_path.is_file():
                data = json.loads(self._vault_path.read_text(encoding="utf-8"))
                for k, v in data.items():
                    self._secrets[k] = SecretEntry(**{k2: v2 for k2, v2 in v.items()
                                                       if k2 in SecretEntry.__dataclass_fields__})
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.debug("[VAULT] Load error: %s", exc)

    def _persist_audit(self) -> None:
        """Persist audit log to JSONL."""
        try:
            self._audit_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._audit_path, "w", encoding="utf-8") as f:
                for entry in self._audit_log[-self._max_audit:]:
                    f.write(json.dumps(entry.to_dict()) + "\n")
        except (OSError, ValueError) as exc:
            _log.debug("[VAULT] Audit persist error: %s", exc)

    def clear_all(self) -> None:
        """Clear all secrets (for testing)."""
        with self._lock:
            self._secrets.clear()
            self._audit_log.clear()
            if self._vault_path.exists():
                self._vault_path.unlink()
            if self._audit_path.exists():
                self._audit_path.unlink()


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m core.secrets_vault",
        description="Secrets Vault — Centralized secrets management with encryption",
    )
    ap.add_argument("--list", action="store_true", help="List all secret keys")
    ap.add_argument("--set", type=str, metavar="KEY=VALUE", help="Store a secret")
    ap.add_argument("--get", type=str, metavar="KEY", help="Retrieve a secret")
    ap.add_argument("--delete", type=str, metavar="KEY", help="Delete a secret")
    ap.add_argument("--rotate", type=str, metavar="KEY=NEW_VALUE", help="Rotate a secret")
    ap.add_argument("--audit", action="store_true", help="Show audit log")
    ap.add_argument("--stats", action="store_true", help="Show statistics")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    vault = get_secrets_vault()

    if args.list:
        keys = vault.list_keys()
        if args.json:
            import json
            print(json.dumps([vault.get_metadata(k).to_dict() for k in keys if vault.get_metadata(k)], indent=2))
        else:
            print(f"{'Key':<40} {'Version':<10} {'Tags':<20}")
            print("-" * 70)
            for k in keys:
                meta = vault.get_metadata(k)
                if meta:
                    tags = ", ".join(meta.tags) if meta.tags else "-"
                    print(f"{k:<40} {meta.version:<10} {tags:<20}")
        return

    if args.set:
        parts = args.set.split("=", 1)
        if len(parts) != 2:
            print("Usage: --set KEY=VALUE")
            return
        key, value = parts
        vault.set(key.strip(), value.strip())
        print(f"Stored: {key.strip()}")
        return

    if args.get:
        try:
            value = vault.get(args.get)
            print(f"{args.get}: {value}")
        except KeyError:
            print(f"Not found: {args.get}")
        return

    if args.delete:
        ok = vault.delete(args.delete)
        print(f"{'Deleted' if ok else 'Not found'}: {args.delete}")
        return

    if args.rotate:
        parts = args.rotate.split("=", 1)
        if len(parts) != 2:
            print("Usage: --rotate KEY=NEW_VALUE")
            return
        key, new_value = parts
        ok = vault.rotate(key.strip(), new_value.strip())
        print(f"{'Rotated' if ok else 'Not found'}: {key.strip()}")
        return

    if args.audit:
        entries = vault.get_audit_log()
        if args.json:
            import json
            print(json.dumps([e.to_dict() for e in entries], indent=2))
        else:
            print(f"{'Action':<12} {'Key':<30} {'Success':<10} {'Time':<20}")
            print("-" * 72)
            for e in entries:
                ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.timestamp))
                print(f"{e.action:<12} {e.key:<30} {str(e.success):<10} {ts:<20}")
        return

    if args.stats:
        stats = vault.get_stats()
        if args.json:
            import json
            print(json.dumps(stats, indent=2))
        else:
            print("Vault Stats:")
            for k, v in stats.items():
                print(f"  {k}: {v}")
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()


# ── Singleton ──────────────────────────────────────────────────────────────

_instance: SecretsVault | None = None
_instance_lock = threading.RLock()


def get_secrets_vault(master_key: str = "", vault_path: str = "") -> SecretsVault:
    """Get the singleton SecretsVault instance.

    Args:
        master_key: Optional master encryption key. Only used on first creation.
        vault_path: Optional vault file path. Only used on first creation.
    """
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = SecretsVault(master_key=master_key, vault_path=vault_path)
        return _instance


def reset_secrets_vault() -> None:
    """Force-reset singleton (for testing)."""
    global _instance
    with _instance_lock:
        _instance = None


__all__ = [
    "AuditEntry",
    "SecretEntry",
    "SecretsVault",
    "get_secrets_vault",
    "reset_secrets_vault",
]
