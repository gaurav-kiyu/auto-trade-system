"""Tests for core/auth/csrf.py."""

from __future__ import annotations

import core.auth.csrf as _mod


class TestAuthCsrf:
    """Test suite for core/auth/csrf.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
