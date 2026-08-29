"""Tests for core/ml/feature_store.py."""

from __future__ import annotations

import core.ml.feature_store as _mod


class TestMlFeature_store:
    """Test suite for core/ml/feature_store.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
