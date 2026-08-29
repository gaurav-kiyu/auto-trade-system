"""Tests for core/portfolio/optimizer.py."""

from __future__ import annotations

import core.portfolio.optimizer as _mod


class TestPortfolioOptimizer:
    """Test suite for core/portfolio/optimizer.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
