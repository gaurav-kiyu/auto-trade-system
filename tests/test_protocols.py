"""Tests for core/auth/handler/protocols.py.

Verifies the structural Protocol types used by the auth handler.
"""
from __future__ import annotations

from typing import Protocol

from core.auth.handler.protocols import (
    HasAuditLog,
    HasConnection,
    MfaHandlerHost,
    SessionManagerHost,
)


def test_protocols_are_protocols():
    """Each exported type must be a typing.Protocol subclass."""
    for cls in (HasConnection, HasAuditLog, SessionManagerHost, MfaHandlerHost):
        assert issubclass(cls, Protocol)
