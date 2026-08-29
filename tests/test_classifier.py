"""Tests for core/execution/retry_policy/classifier.py."""

from __future__ import annotations

import core.execution.retry_policy.classifier as _mod


class TestExecutionRetry_policyClassifier:
    """Test suite for core/execution/retry_policy/classifier.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
