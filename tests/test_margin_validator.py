"""Tests for core/risk/margin_validator.py."""

from __future__ import annotations

import core.risk.margin_validator as _mod


class TestRiskMargin_validator:
    """Test suite for core/risk/margin_validator.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
