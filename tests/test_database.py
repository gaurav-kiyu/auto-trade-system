"""Tests for core/ports/database.py."""

from __future__ import annotations

import core.ports.database as _mod


class TestPortsDatabase:
    """Test suite for core/ports/database.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
