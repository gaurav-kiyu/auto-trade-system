"""
MFA Handler Mixin — extracted from AuthHandler for SRP compliance.

Provides MFA (Multi-Factor Authentication) management methods that
are mixed into the AuthHandler class.
"""

from __future__ import annotations

import json
import logging

_log = logging.getLogger(__name__)


class MfaHandlerMixin:
    """Mixin providing MFA management for AuthHandler.

    Expects the host class to provide:
      - self._get_conn() -> sqlite3.Connection
      - self._audit_log(event_type, username, ip_address, details)
      - self._db_path (string)
    """

    def get_mfa_secret(self, username: str) -> str:
        """Get the MFA secret for a user. Returns empty string if not set."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT mfa_secret FROM users WHERE username = ?",
                (username.strip().lower(),),
            )
            row = cursor.fetchone()
            if row is None:
                return ""
            return row["mfa_secret"] or ""
        finally:
            conn.close()

    def set_mfa_secret(self, username: str, secret: str) -> bool:
        """Set (or reset) the MFA secret for a user. MFA remains disabled until verified."""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE users SET mfa_secret = ?, mfa_enabled = 0 WHERE username = ?",
                (secret, username.strip().lower()),
            )
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    def enable_mfa(self, username: str, recovery_codes: list[str]) -> bool:
        """Enable MFA for a user by setting mfa_enabled=1 and storing recovery codes."""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE users SET mfa_enabled = 1, mfa_recovery_codes = ? WHERE username = ?",
                (json.dumps(recovery_codes), username.strip().lower()),
            )
            conn.commit()
            ok = conn.total_changes > 0
            if ok:
                _log.info("[AUTH] MFA enabled for %s", username)
                self._audit_log("mfa_enabled", username, "")
            return ok
        finally:
            conn.close()

    def disable_mfa(self, username: str) -> bool:
        """Disable MFA for a user by clearing the secret and recovery codes."""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE users SET mfa_enabled = 0, mfa_secret = '', mfa_recovery_codes = '[]' "
                "WHERE username = ?",
                (username.strip().lower(),),
            )
            conn.commit()
            ok = conn.total_changes > 0
            if ok:
                _log.info("[AUTH] MFA disabled for %s", username)
                self._audit_log("mfa_disabled", username, "")
            return ok
        finally:
            conn.close()

    def is_mfa_enabled(self, username: str) -> bool:
        """Check if MFA is enabled for a user."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT mfa_enabled FROM users WHERE username = ?",
                (username.strip().lower(),),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            return bool(row["mfa_enabled"])
        finally:
            conn.close()

    def get_mfa_recovery_codes(self, username: str) -> list[str]:
        """Get the hashed recovery codes for a user."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT mfa_recovery_codes FROM users WHERE username = ?",
                (username.strip().lower(),),
            )
            row = cursor.fetchone()
            if row is None or not row["mfa_recovery_codes"]:
                return []
            try:
                return json.loads(row["mfa_recovery_codes"])
            except (json.JSONDecodeError, TypeError):
                return []
        finally:
            conn.close()

    def update_mfa_recovery_codes(self, username: str, recovery_codes: list[str]) -> bool:
        """Update (e.g., after consuming a recovery code) the stored recovery codes."""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE users SET mfa_recovery_codes = ? WHERE username = ?",
                (json.dumps(recovery_codes), username.strip().lower()),
            )
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    def use_recovery_code(self, username: str, code: str) -> bool:
        """Verify and consume a recovery code for a user."""
        from core.auth.mfa import consume_recovery_code, verify_recovery_code
        codes = self.get_mfa_recovery_codes(username)
        if not codes:
            return False
        if not verify_recovery_code(code, codes):
            return False
        updated = consume_recovery_code(code, codes)
        self.update_mfa_recovery_codes(username, updated)
        self._audit_log("mfa_recovery_code_used", username, "", {"remaining": len(updated)})
        return True


__all__ = [
    "MfaHandlerMixin",
]
