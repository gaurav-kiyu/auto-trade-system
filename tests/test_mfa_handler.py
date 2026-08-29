"""Tests for core/auth/handler/mfa_handler.py."""

from __future__ import annotations

import core.auth.handler.mfa_handler as _mod


class TestAuthHandlerMfa_handler:
    """Test suite for core/auth/handler/mfa_handler.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
