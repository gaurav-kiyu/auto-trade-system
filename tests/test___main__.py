"""Tests for core/auto_tuner/__main__.py."""
from __future__ import annotations

from pathlib import Path


class TestAutoTunerMain:
    """Test suite for core/auto_tuner/__main__.py."""

    def test_file_exists(self):
        """Verify the module file exists (no import - __main__ has side effects)."""
        assert Path("core/auto_tuner/__main__.py").exists()
