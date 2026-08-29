"""Tests for core/schema_registry.py."""

from __future__ import annotations

import core.schema_registry as _mod


class TestSchema_registry:
    """Test suite for core/schema_registry.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
