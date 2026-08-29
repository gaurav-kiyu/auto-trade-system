"""Tests for core/ports/market_data.py."""

from __future__ import annotations

import core.ports.market_data as _mod


class TestPortsMarket_data:
    """Test suite for core/ports/market_data.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
