"""Tests for core/telegram/hardening.py."""

from __future__ import annotations

import core.telegram.hardening as _mod


class TestTelegramHardening:
    """Test suite for core/telegram/hardening.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
