"""Tests for core/auth/dependencies.py."""

from __future__ import annotations

import core.auth.dependencies as _mod


class TestAuthDependencies:
    """Test suite for core/auth/dependencies.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
