"""Tests for core/adapters/database/sqlite_adapter.py."""

from __future__ import annotations

import core.adapters.database.sqlite_adapter as _mod


class TestAdaptersDatabaseSqlite_adapter:
    """Test suite for core/adapters/database/sqlite_adapter.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
