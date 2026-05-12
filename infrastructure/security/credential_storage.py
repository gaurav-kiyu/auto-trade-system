"""
Secure Credential Storage

This module provides a secure way to store and retrieve credentials, with the following backends in order of preference:
1. System keyring (if keyring library is available and functional)
2. Encrypted file (if cryptography library is available)
3. Environment variables (as a last resort, with a warning)

The service name used for all credentials is "opb_trading_platform".
"""

from __future__ import annotations

import json
import os
import base64
from typing import Optional
from pathlib import Path

# Try to import keyring
# We avoid importing logging to prevent recursion issues with secure config
try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    keyring = None  # type: ignore

# Try to import cryptography for encrypted fallback
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
    Fernet = None  # type: ignore
    PBKDF2HMAC = None  # type: ignore
    hashes = None  # type: ignore


class CredentialStorageError(Exception):
    """Custom exception for credential storage errors."""
    pass


class CredentialStorage:
    """
    Secure credential storage with multiple backends.
    """

    # The service name used for all credentials in this application
    SERVICE_NAME = "opb_trading_platform"

    # Default path for the encrypted file fallback
    DEFAULT_ENCRYPTED_FILE_PATH = Path.home() / ".config" / "opb" / "secrets.json.enc"

    def __init__(self,
                 encrypted_file_path: Optional[Path] = None,
                 env_var_for_encryption_key: str = "OPBUYING_SECURE_CONFIG_KEY"):
        """
        Initialize the credential storage.

        Args:
            encrypted_file_path: Path to the encrypted file for fallback storage.
                                 If None, uses the default path.
            env_var_for_encryption_key: Name of the environment variable that holds
                                        the encryption key for the encrypted file fallback.
        """
        self.encrypted_file_path = encrypted_file_path or self.DEFAULT_ENCRYPTED_FILE_PATH
        self.env_var_for_encryption_key = env_var_for_encryption_key
        # Take a snapshot of the environment to avoid recursion issues
        self._environment = dict(os.environ)
        # Read the encryption key from the environment snapshot once to avoid repeated access
        self._encryption_key: Optional[str] = None
        if CRYPTOGRAPHY_AVAILABLE:
            self._encryption_key = self._environment.get(self.env_var_for_encryption_key)

        # Ensure the directory for the encrypted file exists
        self.encrypted_file_path.parent.mkdir(parents=True, exist_ok=True)

    def get_credential(self, username: str) -> Optional[str]:
        """
        Retrieve a credential for the given username.

        The credential is looked up in the following order:
        1. System keyring (service: SERVICE_NAME, username: username)
        2. Encrypted file (if available and functional, and encryption key is set)
        3. Environment variable (with OPBUYING_* prefix) - with a warning

        Args:
            username: The username/key for the credential (e.g., "BOT_TOKEN")

        Returns:
            The credential value if found, None otherwise.
        """
        # 1. Try keyring
        if KEYRING_AVAILABLE:
            try:
                credential = keyring.get_password(self.SERVICE_NAME, username)
                if credential is not None:
                    return credential
            except Exception:
                # Fall through to next backend
                pass

        # 2. Try encrypted file (only if encryption key is set)
        if CRYPTOGRAPHY_AVAILABLE and self._encryption_key:
            try:
                credential = self._get_from_encrypted_file(username)
                if credential is not None:
                    return credential
            except Exception:
                # Fall through to next backend
                pass

        # 3. Fall back to environment variable (with warning)
        env_var_name = f"OPBUYING_{username}"
        credential = self._environment.get(env_var_name)
        if credential is not None:
            return credential

        return None

    def _get_from_encrypted_file(self, username: str) -> Optional[str]:
        """
        Retrieve a credential from the encrypted file.

        Args:
            username: The username/key for the credential

        Returns:
            The credential value if found and decrypted successfully, None otherwise.
        """
        if not self.encrypted_file_path.exists():
            return None

        try:
            with open(self.encrypted_file_path, 'rb') as f:
                data = f.read()

            # The file format is: <salt><encrypted_data>
            # We assume the salt is 16 bytes (as used by PBKDF2) and the rest is the encrypted data
            if len(data) < 16:
                return None

            salt = data[:16]
            encrypted_data = data[16:]

            # Get the encryption key from the environment variable
            env_key = os.environ.get(self.env_var_for_encryption_key)
            if not env_key:
                return None

            # Derive the key using PBKDF2
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(env_key.encode()))
            fernet = Fernet(key)

            # Decrypt the data
            decrypted_data = fernet.decrypt(encrypted_data)
            credentials = json.loads(decrypted_data.decode('utf-8'))

            return credentials.get(username)

        except Exception:
            return None

    def set_credential(self, username: str, credential: str) -> None:
        """
        Store a credential for the given username.

        Tries to store in the following order:
        1. System keyring
        2. Encrypted file (only if encryption key is set in environment)

        Args:
            username: The username/key for the credential
            credential: The credential value to store
        """
        # 1. Try keyring
        if KEYRING_AVAILABLE:
            try:
                keyring.set_password(self.SERVICE_NAME, username, credential)
                return
            except Exception:
                # Fall through to encrypted file
                pass

        # 2. Try encrypted file (only if encryption key is set)
        if CRYPTOGRAPHY_AVAILABLE and os.environ.get(self.env_var_for_encryption_key):
            try:
                self._set_in_encrypted_file(username, credential)
                return
            except Exception as e:
                raise CredentialStorageError(
                    f"Failed to store credential in encrypted file: {e}"
                ) from e

        # If we get here, neither backend worked (or encryption key not set for encrypted file)
        raise CredentialStorageError(
            "Unable to store credential: keyring not available or encryption key not set for encrypted file backend. "
            "Please set up keyring or define the environment variable '{}' to use encrypted file storage.".format(self.env_var_for_encryption_key)
        )

    def _set_in_encrypted_file(self, username: str, credential: str) -> None:
        """
        Store a credential in the encrypted file.

        Args:
            username: The username/key for the credential
            credential: The credential value to store
        """
        # Read existing credentials if the file exists
        credentials = {}
        if self.encrypted_file_path.exists():
            try:
                with open(self.encrypted_file_path, 'rb') as f:
                    data = f.read()

                if len(data) >= 16:
                    salt = data[:16]
                    encrypted_data = data[16:]

                    env_key = os.environ.get(self.env_var_for_encryption_key)
                    if env_key:
                        kdf = PBKDF2HMAC(
                            algorithm=hashes.SHA256(),
                            length=32,
                            salt=salt,
                            iterations=100000,
                        )
                        key = base64.urlsafe_b64encode(kdf.derive(env_key.encode()))
                        fernet = Fernet(key)
                        decrypted_data = fernet.decrypt(encrypted_data)
                        credentials = json.loads(decrypted_data.decode('utf-8'))
                    else:
                        # Environment variable not set, creating new encrypted file
                        pass
                else:
                    # Encrypted file is mal creating new encrypted file
                    pass
            except Exception:
                # Error reading existing encrypted file, creating new encrypted file
                pass

        # Update the credential
        credentials[username] = credential

        # Generate a new salt and encrypt
        salt = os.urandom(16)
        env_key = os.environ.get(self.env_var_for_encryption_key)
        if not env_key:
            raise CredentialStorageError(
                f"Environment variable '{self.env_var_for_encryption_key}' not set"
            )

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(env_key.encode()))
        fernet = Fernet(key)

        encrypted_data = fernet.encrypt(json.dumps(credentials).encode('utf-8'))

        # Write the salt and encrypted data
        with open(self.encrypted_file_path, 'wb') as f:
            f.write(salt + encrypted_data)