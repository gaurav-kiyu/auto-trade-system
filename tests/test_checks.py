"""Tests for core/invariants/checks.py."""

from __future__ import annotations

import core.invariants.checks as _mod


class TestInvariantsChecks:
    """Test suite for core/invariants/checks.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
