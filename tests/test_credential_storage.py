"""Tests for infrastructure.security.credential_storage — CredentialStorage class."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from infrastructure.security.credential_storage import (
    CredentialStorage,
    CredentialStorageError,
)

# cryptography is optional; tests that need actual crypto are skipped
_HAS_CRYPTO = False
try:

    _HAS_CRYPTO = True
except ImportError:
    pass


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def encrypted_file(tmp_path: Path) -> Path:
    return tmp_path / ".config" / "opb" / "secrets.json.enc"


@pytest.fixture()
def storage_no_keyring(encrypted_file: Path) -> CredentialStorage:
    """CredentialStorage with keyring mocked as unavailable."""
    with patch("infrastructure.security.credential_storage.KEYRING_AVAILABLE", False):
        yield CredentialStorage(encrypted_file_path=encrypted_file)


@pytest.fixture()
def storage_no_keyring_no_crypto(encrypted_file: Path) -> CredentialStorage:
    """CredentialStorage with both keyring and cryptography mocked as unavailable."""
    with (
        patch("infrastructure.security.credential_storage.KEYRING_AVAILABLE", False),
        patch("infrastructure.security.credential_storage.CRYPTOGRAPHY_AVAILABLE", False),
    ):
        yield CredentialStorage(encrypted_file_path=encrypted_file)


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestCredentialStorageInit:
    def test_default_encrypted_file_path(self):
        """Default encrypted file path uses ~/.config/opb/secrets.json.enc."""
        with patch("infrastructure.security.credential_storage.KEYRING_AVAILABLE", False):
            s = CredentialStorage()
            assert s.encrypted_file_path.name == "secrets.json.enc"
            assert s.encrypted_file_path.parent.name == "opb"

    def test_custom_encrypted_file_path(self, tmp_path: Path):
        with patch("infrastructure.security.credential_storage.KEYRING_AVAILABLE", False):
            p = tmp_path / "custom" / "file.enc"
            s = CredentialStorage(encrypted_file_path=p)
            assert s.encrypted_file_path == p

    def test_custom_env_var_for_key(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "test")
        with patch("infrastructure.security.credential_storage.KEYRING_AVAILABLE", False):
            with patch("infrastructure.security.credential_storage.CRYPTOGRAPHY_AVAILABLE", True):
                s = CredentialStorage(env_var_for_encryption_key="MY_KEY")
                assert s._encryption_key == "test"

    def test_encryption_key_none_when_cryptography_unavailable(self, tmp_path: Path):
        with (
            patch("infrastructure.security.credential_storage.KEYRING_AVAILABLE", False),
            patch("infrastructure.security.credential_storage.CRYPTOGRAPHY_AVAILABLE", False),
        ):
            s = CredentialStorage(encrypted_file_path=tmp_path / "secrets.enc")
            assert s._encryption_key is None


class TestCredentialStorageGetCredential:
    def test_backend_order_keyring_first(self, storage_no_keyring, monkeypatch):
        monkeypatch.setenv("OPBUYING_BOT_TOKEN", "fallback")
        keyring_mock = MagicMock()
        keyring_mock.get_password.return_value = "from_keyring"
        with patch("infrastructure.security.credential_storage.keyring", keyring_mock):
            with patch("infrastructure.security.credential_storage.KEYRING_AVAILABLE", True):
                val = storage_no_keyring.get_credential("BOT_TOKEN")
        assert val == "from_keyring"

    def test_keyring_returns_none_tries_env(self, storage_no_keyring_no_crypto):
        """When keyring is available but returns None, fall through to env var."""
        keyring_mock = MagicMock()
        keyring_mock.get_password.return_value = None
        with patch("infrastructure.security.credential_storage.keyring", keyring_mock):
            with patch("infrastructure.security.credential_storage.KEYRING_AVAILABLE", True):
                storage_no_keyring_no_crypto._environment["OPBUYING_MY_KEY"] = "env_value"
                val = storage_no_keyring_no_crypto.get_credential("MY_KEY")
        assert val == "env_value"

    def test_keyring_exception_falls_through(self, storage_no_keyring_no_crypto):
        """Keyring raising exception should fall through to next backend."""
        keyring_mock = MagicMock()
        keyring_mock.get_password.side_effect = RuntimeError("keyring unavailable")
        with patch("infrastructure.security.credential_storage.keyring", keyring_mock):
            with patch("infrastructure.security.credential_storage.KEYRING_AVAILABLE", True):
                storage_no_keyring_no_crypto._environment["OPBUYING_FALLBACK"] = "works"
                val = storage_no_keyring_no_crypto.get_credential("FALLBACK")
        assert val == "works"

    def test_env_var_with_prefix(self, storage_no_keyring_no_crypto):
        """get_credential('BOT_TOKEN') looks for OPBUYING_BOT_TOKEN in env."""
        storage_no_keyring_no_crypto._environment["OPBUYING_BOT_TOKEN"] = "env_val"
        val = storage_no_keyring_no_crypto.get_credential("BOT_TOKEN")
        assert val == "env_val"

    def test_env_var_none_returned_when_not_found(self, storage_no_keyring_no_crypto):
        """When no backend has the credential, return None."""
        val = storage_no_keyring_no_crypto.get_credential("NONEXISTENT")
        assert val is None

    @pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography not installed")
    def test_encrypted_file_is_tried_before_env(self, storage_no_keyring, tmp_path: Path, monkeypatch):
        """When cryptography is available, encrypted file is tried before env."""
        import base64

        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

        monkeypatch.setenv("OPBUYING_SECURE_CONFIG_KEY", "test-key-12345")

        # Re-init with crypto available and env key set
        with patch("infrastructure.security.credential_storage.CRYPTOGRAPHY_AVAILABLE", True):
            s = CredentialStorage(encrypted_file_path=storage_no_keyring.encrypted_file_path)
            s._environment = {**s._environment, "OPBUYING_BOT_TOKEN": "env_fallback"}

            # Manually create an encrypted file
            salt_file = os.urandom(16)
            env_key = s._encryption_key or "test-key-12345"
            kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt_file, iterations=100000)
            key = base64.urlsafe_b64encode(kdf.derive(env_key.encode()))
            fernet = Fernet(key)
            encrypted = fernet.encrypt(json.dumps({"BOT_TOKEN": "from_encrypted_file"}).encode("utf-8"))
            s.encrypted_file_path.write_bytes(salt_file + encrypted)

            val = s.get_credential("BOT_TOKEN")
            assert val == "from_encrypted_file"

    def test_encrypted_file_exception_falls_through(self, storage_no_keyring, monkeypatch):
        """Encrypted file exception falls through to env."""
        monkeypatch.setenv("OPBUYING_SECURE_CONFIG_KEY", "some-key")
        with patch("infrastructure.security.credential_storage.CRYPTOGRAPHY_AVAILABLE", True):
            s = CredentialStorage(encrypted_file_path=storage_no_keyring.encrypted_file_path)
            s._environment = {**s._environment, "OPBUYING_BOT_TOKEN": "env_val"}
            # Write corrupted data
            s.encrypted_file_path.write_bytes(b"\x00" * 10)
            val = s.get_credential("BOT_TOKEN")
            assert val == "env_val"

    def test_encrypted_file_corrupted_decrypt_returns_none(self, storage_no_keyring, monkeypatch):
        """Corrupted data >=16 bytes failing fernet decrypt returns None."""
        monkeypatch.setenv("OPBUYING_SECURE_CONFIG_KEY", "some-key-must-be-32-bytes")
        with patch("infrastructure.security.credential_storage.CRYPTOGRAPHY_AVAILABLE", True):
            s = CredentialStorage(encrypted_file_path=storage_no_keyring.encrypted_file_path)
            s.encrypted_file_path.write_bytes(b"\x00" * 64)
            val = s._get_from_encrypted_file("BOT_TOKEN")
        assert val is None

    def test_encrypted_file_raise_falls_to_env(self, storage_no_keyring, monkeypatch):
        """When _get_from_encrypted_file raises, falls through to env."""
        monkeypatch.setenv("OPBUYING_SECURE_CONFIG_KEY", "some-key")
        with patch("infrastructure.security.credential_storage.CRYPTOGRAPHY_AVAILABLE", True):
            s = CredentialStorage(encrypted_file_path=storage_no_keyring.encrypted_file_path)
            s._environment = {**s._environment, "OPBUYING_BOT_TOKEN": "env_val"}
            with patch.object(s, "_get_from_encrypted_file", side_effect=RuntimeError("crypto fail")):
                val = s.get_credential("BOT_TOKEN")
        assert val == "env_val"


class TestCredentialStorageSetCredential:
    def test_set_credential_keyring_success(self, storage_no_keyring):
        """set_credential should use keyring when available."""
        keyring_mock = MagicMock()
        with patch("infrastructure.security.credential_storage.keyring", keyring_mock):
            with patch("infrastructure.security.credential_storage.KEYRING_AVAILABLE", True):
                storage_no_keyring.set_credential("BOT_TOKEN", "new_value")
        keyring_mock.set_password.assert_called_once_with(
            CredentialStorage.SERVICE_NAME, "BOT_TOKEN", "new_value"
        )

    @pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography not installed")
    def test_set_credential_keyring_exception_falls_to_encrypted_file(self, storage_no_keyring, monkeypatch):
        """When keyring raises, try encrypted file."""
        monkeypatch.setenv("OPBUYING_SECURE_CONFIG_KEY", "my-encryption-key")
        keyring_mock = MagicMock()
        keyring_mock.set_password.side_effect = RuntimeError("fail")
        with patch("infrastructure.security.credential_storage.keyring", keyring_mock):
            with patch("infrastructure.security.credential_storage.KEYRING_AVAILABLE", True):
                storage_no_keyring.set_credential("BOT_TOKEN", "new_value")
        assert storage_no_keyring.encrypted_file_path.exists()

    def test_set_credential_encrypted_file_fail_raises(self, storage_no_keyring, monkeypatch):
        """set_credential raises when encrypted file set fails."""
        monkeypatch.setenv("OPBUYING_SECURE_CONFIG_KEY", "some-key-must-be-32-bytes")
        with patch("infrastructure.security.credential_storage.CRYPTOGRAPHY_AVAILABLE", True):
            with patch.object(storage_no_keyring, "_set_in_encrypted_file", side_effect=OSError("write fail")):
                with pytest.raises(CredentialStorageError, match="Failed to store"):
                    storage_no_keyring.set_credential("BOT_TOKEN", "val")

    def test_set_in_encrypted_file_malformed_creates_new(self, storage_no_keyring, monkeypatch):
        """_set_in_encrypted_file with malformed existing file creates new."""
        monkeypatch.setenv("OPBUYING_SECURE_CONFIG_KEY", "some-key-must-be-32-bytes")
        with patch("infrastructure.security.credential_storage.CRYPTOGRAPHY_AVAILABLE", True):
            s = CredentialStorage(encrypted_file_path=storage_no_keyring.encrypted_file_path)
            # Write a valid Fernet token with garbage data
            import base64
            import os

            from cryptography.fernet import Fernet
            key = base64.urlsafe_b64encode(os.urandom(32))
            fake_token = Fernet(key).encrypt(b'{"garbage')
            s.encrypted_file_path.write_bytes(fake_token)
            # Now set - should fail to decrypt old file, create new
            s.set_credential("BOT_TOKEN", "new_val")
        assert s.get_credential("BOT_TOKEN") == "new_val"

    def test_set_in_encrypted_file_no_key_raises(self, storage_no_keyring):
        """_set_in_encrypted_file raises when env var not set."""
        with patch("infrastructure.security.credential_storage.CRYPTOGRAPHY_AVAILABLE", True):
            with pytest.raises(CredentialStorageError, match="not set"):
                storage_no_keyring._set_in_encrypted_file("BOT_TOKEN", "val")

    def test_set_credential_no_backend_raises(self, storage_no_keyring_no_crypto):
        """When no backend is available, raise CredentialStorageError."""
        with pytest.raises(CredentialStorageError, match="Unable to store"):
            storage_no_keyring_no_crypto.set_credential("BOT_TOKEN", "val")

    def test_set_credential_encrypted_file_no_key_raises(self, storage_no_keyring):
        """If keyring unavailable and encryption key not set, raise."""
        with patch("infrastructure.security.credential_storage.KEYRING_AVAILABLE", False):
            with pytest.raises(CredentialStorageError):
                storage_no_keyring.set_credential("BOT_TOKEN", "val")

    @pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography not installed")
    def test_set_then_get_roundtrip_via_encrypted_file(self, storage_no_keyring, monkeypatch):
        """Set via encrypted file, then get back the same value."""
        monkeypatch.setenv("OPBUYING_SECURE_CONFIG_KEY", "my-secure-key-42")
        with patch("infrastructure.security.credential_storage.CRYPTOGRAPHY_AVAILABLE", True):
            with patch("infrastructure.security.credential_storage.KEYRING_AVAILABLE", False):
                s = CredentialStorage(encrypted_file_path=storage_no_keyring.encrypted_file_path)
                s.set_credential("BOT_TOKEN", "super-secret-123")
                val = s.get_credential("BOT_TOKEN")
        assert val == "super-secret-123"


class TestCredentialStorageGetFromEncryptedFile:
    def test_file_not_found_returns_none(self, storage_no_keyring):
        val = storage_no_keyring._get_from_encrypted_file("BOT_TOKEN")
        assert val is None

    def test_malformed_file_returns_none(self, storage_no_keyring):
        storage_no_keyring.encrypted_file_path.write_bytes(b"\x00" * 5)
        val = storage_no_keyring._get_from_encrypted_file("BOT_TOKEN")
        assert val is None

    def test_short_file_returns_none(self, storage_no_keyring):
        storage_no_keyring.encrypted_file_path.write_bytes(b"\x00" * 5)
        val = storage_no_keyring._get_from_encrypted_file("BOT_TOKEN")
        assert val is None

    def test_decryption_failure_returns_none(self, storage_no_keyring):
        salt = os.urandom(16)
        storage_no_keyring.encrypted_file_path.write_bytes(salt + b"garbage_encrypted_data_here")
        val = storage_no_keyring._get_from_encrypted_file("BOT_TOKEN")
        assert val is None


class TestCredentialStorageSetInEncryptedFile:
    @pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography not installed")
    def test_creates_file_on_set(self, storage_no_keyring, monkeypatch):
        monkeypatch.setenv("OPBUYING_SECURE_CONFIG_KEY", "encryption-key-123")
        with patch("infrastructure.security.credential_storage.CRYPTOGRAPHY_AVAILABLE", True):
            with patch("infrastructure.security.credential_storage.KEYRING_AVAILABLE", False):
                s = CredentialStorage(encrypted_file_path=storage_no_keyring.encrypted_file_path)
                s._set_in_encrypted_file("BOT_TOKEN", "val")
        assert storage_no_keyring.encrypted_file_path.exists()

    @pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography not installed")
    def test_roundtrip_multiple_credentials(self, storage_no_keyring, monkeypatch):
        monkeypatch.setenv("OPBUYING_SECURE_CONFIG_KEY", "key-for-multiple-credentials")
        with patch("infrastructure.security.credential_storage.CRYPTOGRAPHY_AVAILABLE", True):
            with patch("infrastructure.security.credential_storage.KEYRING_AVAILABLE", False):
                s = CredentialStorage(encrypted_file_path=storage_no_keyring.encrypted_file_path)
                s._set_in_encrypted_file("BOT_TOKEN", "val1")
                s._set_in_encrypted_file("KITE_API_KEY", "val2")

                val1 = s._get_from_encrypted_file("BOT_TOKEN")
                val2 = s._get_from_encrypted_file("KITE_API_KEY")
        assert val1 == "val1"
        assert val2 == "val2"


class TestCredentialStorageEnvironmentSnapshot:
    def test_environment_snapshot_independent(self, monkeypatch, storage_no_keyring_no_crypto):
        """Environment snapshot should be independent of later env changes."""
        storage_no_keyring_no_crypto._environment = {"OPBUYING_FOO": "bar"}
        monkeypatch.setenv("OPBUYING_FOO", "changed_value")
        val = storage_no_keyring_no_crypto.get_credential("FOO")
        assert val == "bar"
