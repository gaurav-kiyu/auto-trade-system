"""Tests for core/control_plane/rbac.py."""

from __future__ import annotations

import core.control_plane.rbac as _mod


class TestControl_planeRbac:
    """Test suite for core/control_plane/rbac.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
