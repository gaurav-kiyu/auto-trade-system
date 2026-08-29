"""Tests for core/ai/model_registry.py."""

from __future__ import annotations

import core.ai.model_registry as _mod


class TestAiModel_registry:
    """Test suite for core/ai/model_registry.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
