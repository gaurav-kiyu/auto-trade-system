"""Protocol classes for AuthHandler mixin host contract.

Defines the interface that host classes (like AuthHandler) must provide
for mixins to work correctly. This eliminates the need for
# type: ignore[attr-defined] annotations in mixin files.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class HasConnection(Protocol):
    """Provides a SQLite connection for database operations."""

    def _get_conn(self) -> Any:
        """Return a SQLite connection object."""
        ...


@runtime_checkable
class HasAuditLog(Protocol):
    """Provides audit logging capability."""

    def _audit_log(
        self,
        event_type: str,
        username: str,
        ip_address: str | None = None,
        details: Any | None = None,
    ) -> None:
        """Record an audit event."""
        ...


class SessionManagerHost(HasConnection, HasAuditLog, Protocol):
    """Protocol for classes that host SessionManagerMixin.

    Expected attributes (set by AuthHandler):
      - self._lock: threading.RLock
      - self._tokens: dict[str, AuthToken]
      - self._token_ttl: int
      - self._account_lockouts: dict[str, float]
      - self.get_user(username: str) -> AuthUser | None
    """

    _lock: Any  # threading.RLock
    _tokens: dict[str, Any]  # dict[str, AuthToken]
    _token_ttl: int
    _account_lockouts: dict[str, float]

    def get_user(self, username: str) -> Any | None:
        """Get a user by username."""
        ...


class MfaHandlerHost(HasConnection, HasAuditLog, Protocol):
    """Protocol for classes that host MfaHandlerMixin."""
    ...
