"""Tests for core/auth/handler/protocols.py — Protocol classes for AuthHandler.

Tests that the protocol classes correctly identify compliant classes
via runtime_checkable isinstance checks.
"""

from __future__ import annotations

import threading
from typing import Any

from core.auth.handler.protocols import (
    HasAuditLog,
    HasConnection,
    MfaHandlerHost,
    SessionManagerHost,
)

# ── Compliant test classes ──────────────────────────────────────────────────


class GoodConnection:
    """Class that satisfies HasConnection protocol."""

    def _get_conn(self) -> Any:
        return "sqlite_connection"


class BadConnection:
    """Class that does NOT satisfy HasConnection protocol."""

    def _get_conn(self) -> int:
        return 42  # Wrong return type but runtime_checkable doesn't check return types


class NoConnection:
    """Class missing _get_conn entirely."""
    pass


class GoodAuditLog:
    """Class that satisfies HasAuditLog protocol."""

    def _audit_log(
        self,
        event_type: str,
        username: str,
        ip_address: str | None = None,
        details: Any | None = None,
    ) -> None:
        pass


class BadAuditLog:
    """Class with wrong signature for _audit_log."""

    def _audit_log(self, x: int) -> None:
        pass


class GoodSessionManagerHost:
    """Class that satisfies SessionManagerHost protocol."""

    _lock = threading.RLock()
    _tokens: dict[str, Any] = {}
    _token_ttl: int = 3600
    _account_lockouts: dict[str, float] = {}

    def _get_conn(self) -> Any:
        return "conn"

    def _audit_log(
        self,
        event_type: str,
        username: str,
        ip_address: str | None = None,
        details: Any | None = None,
    ) -> None:
        pass

    def get_user(self, username: str) -> Any | None:
        return None


class GoodMfaHandlerHost:
    """Class that satisfies MfaHandlerHost protocol."""

    def _get_conn(self) -> Any:
        return "conn"

    def _audit_log(
        self,
        event_type: str,
        username: str,
        ip_address: str | None = None,
        details: Any | None = None,
    ) -> None:
        pass


# ── Tests ────────────────────────────────────────────────────────────────────


class TestHasConnection:
    """Tests for HasConnection protocol."""

    def test_compliant_class_passes_isinstance(self):
        """Class with _get_conn should pass isinstance check."""
        assert isinstance(GoodConnection(), HasConnection)

    def test_non_compliant_class_fails_isinstance(self):
        """Class missing _get_conn should fail isinstance check."""
        assert not isinstance(NoConnection(), HasConnection)

    def test_bad_return_type_still_passes(self):
        """runtime_checkable only checks method existence, not signature."""
        assert isinstance(BadConnection(), HasConnection)  # Has _get_conn method


class TestHasAuditLog:
    """Tests for HasAuditLog protocol."""

    def test_compliant_class_passes_isinstance(self):
        """Class with _audit_log should pass isinstance check."""
        assert isinstance(GoodAuditLog(), HasAuditLog)

    def test_class_missing_method_fails(self):
        """Class without _audit_log should fail isinstance check."""
        assert not isinstance(NoConnection(), HasAuditLog)


class TestSessionManagerHost:
    """Tests for SessionManagerHost protocol."""

    def test_compliant_class_passes_isinstance(self):
        """Class satisfying all requirements should pass isinstance check."""
        assert isinstance(GoodSessionManagerHost(), SessionManagerHost)

    def test_missing_attributes_fails(self):
        """Class missing _lock should fail isinstance check."""
        class MissingLock:
            _tokens = {}
            _token_ttl = 3600
            _account_lockouts = {}
            def _get_conn(self):
                return "conn"
            def _audit_log(self, event_type, username, ip_address=None, details=None):
                pass
            def get_user(self, username):
                return None

        assert not isinstance(MissingLock(), SessionManagerHost)


class TestMfaHandlerHost:
    """Tests for MfaHandlerHost protocol."""

    def test_compliant_class_passes_isinstance(self):
        """Class satisfying MFA requirements should pass isinstance check."""
        assert isinstance(GoodMfaHandlerHost(), MfaHandlerHost)

    def test_missing_audit_log_fails(self):
        """Class missing _audit_log should fail isinstance check."""
        class NoAudit:
            def _get_conn(self):
                return "conn"
        assert not isinstance(NoAudit(), MfaHandlerHost)
