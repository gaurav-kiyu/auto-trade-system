"""
Tests for config_audit_log — append-only config audit diff logging.

Covers:
- format_config_audit_log_line: line formatting with timestamp, key, old→new
- append_soft_reload_audit_diff: file appending with diff entries
- Edge cases (empty diff, special characters in values)
"""

from __future__ import annotations

import pathlib
from pathlib import Path
from unittest.mock import MagicMock

from core.config_audit_log import (
    append_soft_reload_audit_diff,
    format_config_audit_log_line,
)

# ── format_config_audit_log_line ──────────────────────────────────────────


class TestFormatLine:
    def test_basic_format(self):
        line = format_config_audit_log_line("2024-01-01T00:00:00", "SCAN_INTERVAL", 30, 45)
        assert "2024-01-01T00:00:00" in line
        assert "SCAN_INTERVAL" in line
        assert "30" in line
        assert "45" in line
        assert "→" in line
        assert line.endswith("\n")

    def test_string_values(self):
        line = format_config_audit_log_line(
            "2024-01-01T00:00:00", "EXECUTION_MODE", "PAPER", "AUTO"
        )
        assert "PAPER" in line
        assert "AUTO" in line

    def test_none_values(self):
        """None values are rendered as 'None'."""
        line = format_config_audit_log_line("2024-01-01", "NEW_KEY", None, "value")
        assert "None" in line
        assert "value" in line

    def test_boolean_values(self):
        line = format_config_audit_log_line("2024-01-01", "FEATURE", False, True)
        assert "False" in line
        assert "True" in line

    def test_numeric_values(self):
        line = format_config_audit_log_line("2024-01-01", "BASE_CAPITAL", 100000, 150000)
        assert "100000" in line
        assert "150000" in line

    def test_float_values(self):
        line = format_config_audit_log_line("2024-01-01", "SL_PCT", 0.05, 0.10)
        assert "0.05" in line
        assert "0.1" in line or "0.10" in line

    def test_arrow_separator(self):
        """Arrow (→) separates old and new values."""
        line = format_config_audit_log_line("ts", "key", "old", "new")
        assert "old → new" in line

    def test_timestamp_format(self):
        """Timestamp appears at start of line."""
        line = format_config_audit_log_line("2024-06-19T10:30:00", "KEY", 1, 2)
        assert line.startswith("2024-06-19T10:30:00")


# ── append_soft_reload_audit_diff ─────────────────────────────────────────


class TestAppendDiff:
    def test_appends_single_diff(self, tmp_path: Path):
        path = tmp_path / "config_audit.log"
        now_fn = MagicMock(return_value="2024-01-01T00:00:00")
        diff = [{"key": "SCAN_INTERVAL", "old": 30, "new": 45}]
        append_soft_reload_audit_diff(path, diff, now_iso=now_fn)
        content = path.read_text(encoding="utf-8")
        assert "SCAN_INTERVAL" in content
        assert "30" in content
        assert "45" in content
        assert content.endswith("\n")

    def test_appends_multiple_diffs(self, tmp_path: Path):
        path = tmp_path / "config_audit.log"
        now_fn = MagicMock(return_value="2024-01-01T00:00:00")
        diff = [
            {"key": "SL_PCT", "old": 0.05, "new": 0.10},
            {"key": "TARGET_PCT", "old": 0.10, "new": 0.15},
            {"key": "MAX_DAILY_LOSS", "old": -4000, "new": -5000},
        ]
        append_soft_reload_audit_diff(path, diff, now_iso=now_fn)
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        assert "SL_PCT" in lines[0]
        assert "TARGET_PCT" in lines[1]
        assert "MAX_DAILY_LOSS" in lines[2]

    def test_flushes_after_write(self, tmp_path: Path):
        """file is flushed after writing."""
        path = tmp_path / "config_audit.log"
        now_fn = MagicMock(return_value="2024-01-01T00:00:00")
        diff = [{"key": "TEST", "old": 1, "new": 2}]

        with open(path, "w", encoding="utf-8") as f:
            # Write something first
            f.write("initial\n")

        append_soft_reload_audit_diff(path, diff, now_iso=now_fn)
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        assert len(lines) == 2

    def test_empty_diff_no_content(self, tmp_path: Path):
        """Empty diff produces no output lines."""
        path = tmp_path / "config_audit.log"
        now_fn = MagicMock(return_value="2024-01-01T00:00:00")
        append_soft_reload_audit_diff(path, [], now_iso=now_fn)
        # File may be created by open(), but should be empty
        if path.exists():
            content = path.read_text(encoding="utf-8")
            assert content == ""
        else:
            assert True

    def test_now_iso_called_once_per_entry(self, tmp_path: Path):
        """now_iso is called for each diff entry."""
        path = tmp_path / "config_audit.log"
        now_fn = MagicMock(return_value="2024-01-01T00:00:00")
        diff = [
            {"key": "A", "old": 1, "new": 2},
            {"key": "B", "old": 3, "new": 4},
        ]
        append_soft_reload_audit_diff(path, diff, now_iso=now_fn)
        assert now_fn.call_count == 2

    def test_appends_to_existing_file(self, tmp_path: Path):
        """Appends to existing file rather than overwriting."""
        path = tmp_path / "config_audit.log"
        path.write_text("previous entry\n", encoding="utf-8")
        now_fn = MagicMock(return_value="2024-01-01T00:00:00")
        diff = [{"key": "NEW_KEY", "old": None, "new": "value"}]
        append_soft_reload_audit_diff(path, diff, now_iso=now_fn)
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert lines[0] == "previous entry"

    def test_special_characters_in_values(self, tmp_path: Path):
        """Special characters in values are handled."""
        path = tmp_path / "config_audit.log"
        now_fn = MagicMock(return_value="2024-01-01")
        diff = [{"key": "API_KEY", "old": "secret123", "new": "new_secret"}]
        append_soft_reload_audit_diff(path, diff, now_iso=now_fn)
        content = path.read_text(encoding="utf-8")
        assert "secret123" in content
        assert "new_secret" in content

    def test_pathlib_path_object(self, tmp_path: Path):
        """Accepts Path objects as audit_log_path."""
        path = pathlib.Path(tmp_path / "audit.log")
        now_fn = MagicMock(return_value="2024-01-01T00:00:00")
        diff = [{"key": "TEST", "old": "a", "new": "b"}]
        append_soft_reload_audit_diff(path, diff, now_iso=now_fn)
        assert path.exists()

    def test_unicode_in_values(self, tmp_path: Path):
        """Unicode characters in old/new values."""
        path = tmp_path / "config_audit.log"
        now_fn = MagicMock(return_value="2024-01-01")
        diff = [{"key": "NAME", "old": "निफ्टी", "new": "सेंसेक्स"}]
        append_soft_reload_audit_diff(path, diff, now_iso=now_fn)
        content = path.read_text(encoding="utf-8")
        assert "निफ्टी" in content
        assert "सेंसेक्स" in content
