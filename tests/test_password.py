"""Tests for core/auth/handler/password.py."""

from __future__ import annotations

import core.auth.handler.password as _mod


class TestAuthHandlerPassword:
    """Test suite for core/auth/handler/password.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
