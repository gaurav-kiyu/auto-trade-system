"""Tests for scripts.check_stale_doc_refs — pre-commit stale doc reference detector."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.check_stale_doc_refs import (
    _EXCLUDED_PREFIXES,
    _MODULE_REF_RE,
    _line_number,
    check_file,
    main,
)


class TestModuleRefRegex:
    """Tests for the _MODULE_REF_RE regex pattern."""

    def test_matches_core_module_simple(self):
        assert _MODULE_REF_RE.search("see `core/foo.py`") is not None

    def test_matches_core_module_with_underscore(self):
        assert _MODULE_REF_RE.search("see `core/my_module.py`") is not None

    def test_matches_with_trailing_text(self):
        m = _MODULE_REF_RE.search("Uses `core/signal.py` for signals.")
        assert m is not None
        assert m.group(1) == "core/signal.py"

    def test_does_not_match_non_core(self):
        assert _MODULE_REF_RE.search("see `scripts/foo.py`") is None

    def test_does_not_match_no_backtick(self):
        assert _MODULE_REF_RE.search("see core/foo.py") is None

    def test_does_not_match_single_backtick(self):
        assert _MODULE_REF_RE.search("see `core/foo.py") is None

    def test_matches_multiple_refs(self):
        matches = _MODULE_REF_RE.findall("`core/a.py` and `core/b.py`")
        assert matches == ["core/a.py", "core/b.py"]

    def test_does_not_match_nested_path(self):
        """Only single-level like core/foo.py, not core/services/foo.py."""
        assert _MODULE_REF_RE.search("see `core/services/foo.py`") is None

    def test_does_not_match_non_alpha(self):
        """Module paths must be [a-z_]+ — numbers and hyphens excluded."""
        assert _MODULE_REF_RE.search("see `core/foo-bar.py`") is None
        assert _MODULE_REF_RE.search("see `core/foo123.py`") is None
        assert _MODULE_REF_RE.search("see `core/123foo.py`") is None

    def test_matches_init_py(self):
        """__init__.py and __main__.py should match (valid module paths)."""
        assert _MODULE_REF_RE.search("see `core/__init__.py`") is not None
        assert _MODULE_REF_RE.search("see `core/__main__.py`") is not None


class TestLineNumber:
    """Tests for the _line_number helper."""

    def test_first_line(self):
        assert _line_number("hello world", 0) == 1

    def test_middle_of_first_line(self):
        assert _line_number("hello world", 5) == 1

    def test_second_line(self):
        content = "line1\nline2"
        # Position 7 = 'l' in line2
        assert _line_number(content, 7) == 2

    def test_third_line(self):
        content = "a\nb\nc"
        # Position 4 = 'c'
        assert _line_number(content, 4) == 3

    def test_at_newline_char(self):
        """Position at the newline character itself should still be on the first line."""
        content = "line1\nline2"
        assert _line_number(content, 5) == 1  # '\n' is at position 5

    def test_empty_content(self):
        assert _line_number("", 0) == 1


class TestExcludedPrefixes:
    """_EXCLUDED_PREFIXES should contain expected archive paths."""

    def test_archive_excluded(self):
        assert "docs/archive/" in _EXCLUDED_PREFIXES

    def test_no_other_exclusions_by_default(self):
        assert len(_EXCLUDED_PREFIXES) == 1


class TestCheckFile:
    """Tests for the check_file() function."""

    def test_non_existent_file(self, tmp_path):
        result = check_file(str(tmp_path / "nonexistent.md"))
        assert result == []

    def test_clean_file_no_refs(self, tmp_path):
        f = tmp_path / "clean.md"
        f.write_text("# No references here\nJust documentation.\n")
        result = check_file(str(f))
        assert result == []

    def test_clean_file_with_existing_refs(self, tmp_path):
        """References to modules that exist on disk should not flag."""
        f = tmp_path / "good.md"
        f.write_text("Uses `core/smoke.py` for startup checks.\n")
        with patch.object(Path, "exists", return_value=True):
            result = check_file(str(f))
        assert result == []

    def test_stale_ref_detected(self, tmp_path):
        f = tmp_path / "bad.md"
        f.write_text("Uses `core/deleted_module.py` for analysis.\n")
        with patch.object(Path, "exists", return_value=False):
            result = check_file(str(f))
        assert len(result) == 1
        assert "core/deleted_module.py" in result[0]

    def test_multiple_stale_refs_in_one_file(self, tmp_path):
        f = tmp_path / "multi.md"
        f.write_text("Uses `core/a.py` and `core/b.py` for features.\n")
        with patch.object(Path, "exists", return_value=False):
            result = check_file(str(f))
        assert len(result) == 2
        assert "core/a.py" in result[0]
        assert "core/b.py" in result[1]

    def test_mixed_existing_and_stale(self, tmp_path):
        """Existing refs are skipped, stale refs are flagged."""
        f = tmp_path / "mixed.md"
        f.write_text("Uses `core/existing.py` and `core/stale.py`.\n")
        with patch.object(Path, "exists", side_effect=[True, False]):
            result = check_file(str(f))
        assert len(result) == 1
        assert "core/stale.py" in result[0]

    def test_skipped_when_no_stale_refs(self, tmp_path):
        """All refs exist — should return empty list."""
        f = tmp_path / "all_good.md"
        f.write_text("Uses `core/a.py` and `core/b.py`.\n")
        with patch.object(Path, "exists", return_value=True):
            result = check_file(str(f))
        assert result == []

    def test_excluded_path_skipped(self):
        """Files under docs/archive/ should be skipped regardless of content."""
        # Mock is_file to return True so we reach the exclusion prefix check
        # Mock read_text to return content with a stale ref
        # If exclusion works, it returns []; if broken, it would flag the stale ref
        with (
            patch.object(Path, "is_file", return_value=True),
            patch.object(Path, "read_text", return_value="Uses `core/gone.py`\n"),
        ):
            result = check_file("docs/archive/2026-07-20/CLEANUP_REPORT.md")
        assert result == []

    def test_unreadable_file_returns_warning(self, tmp_path):
        f = tmp_path / "locked.md"
        f.write_text("Some content")

        def broken_read(self_obj, **kwargs):
            raise PermissionError("Access denied")

        with patch.object(Path, "read_text", broken_read):
            result = check_file(str(f))
        assert len(result) == 1
        assert "Cannot read" in result[0]

    def test_windows_path_handling(self, tmp_path):
        """Windows-style backslash paths should still work."""
        f = tmp_path / "win_test.md"
        f.write_text("Uses `core/foo.py`\n")
        # Convert to Windows-style path string
        win_path = str(f).replace("/", "\\")
        with patch.object(Path, "exists", return_value=False):
            result = check_file(str(win_path))
        assert len(result) == 1

    def test_line_number_in_error_message(self, tmp_path):
        f = tmp_path / "lined.md"
        content = "Line 1\nLine 2\nUses `core/stale.py`\nLine 4\n"
        f.write_text(content)
        with patch.object(Path, "exists", return_value=False):
            result = check_file(str(f))
        assert len(result) == 1
        # The stale ref is on line 3, so error should reference line 3
        assert ":3:" in result[0]

    def test_no_false_positive_on_scripts_ref(self, tmp_path):
        """scripts/xxx.py references should not be flagged."""
        f = tmp_path / "scripts_ref.md"
        f.write_text("Uses `scripts/tool.py` for automation.\n")
        result = check_file(str(f))
        assert result == []

    def test_no_false_positive_on_infra_ref(self, tmp_path):
        """infra/xxx.py references should not be flagged."""
        f = tmp_path / "infra_ref.md"
        f.write_text("Uses `infra/adapter.py` for data.\n")
        result = check_file(str(f))
        assert result == []

    def test_handles_unicode_content(self, tmp_path):
        """Unicode characters in markdown should not break scanning."""
        f = tmp_path / "unicode_test.md"
        # Write as UTF-8 bytes to avoid cp1252 encoding issues on Windows
        f.write_bytes("# Café Dashboard\nUses `core/café.py` — accents shouldn't match\n".encode())
        result = check_file(str(f))
        # The regex [a-z_]+ wouldn't match accented characters, so no false positive
        assert result == []

    def test_ref_at_end_of_file_no_newline(self, tmp_path):
        f = tmp_path / "eof.md"
        f.write_text("Final ref: `core/end.py`")  # No trailing newline
        with patch.object(Path, "exists", return_value=False):
            result = check_file(str(f))
        assert len(result) == 1
        assert "core/end.py" in result[0]

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.md"
        f.write_text("")
        result = check_file(str(f))
        assert result == []


class TestMainFunction:
    """Tests for the main() CLI entry point."""

    def test_no_args_returns_zero(self):
        with patch("sys.argv", ["check_stale_doc_refs.py"]):
            assert main() == 0

    def test_clean_files_returns_zero(self, tmp_path):
        f = tmp_path / "clean.md"
        f.write_text("# Clean doc\n")
        with patch("sys.argv", ["check_stale_doc_refs.py", str(f)]):
            assert main() == 0

    def test_stale_ref_returns_nonzero(self, tmp_path):
        f = tmp_path / "stale.md"
        f.write_text("Uses `core/gone.py`\n")
        with (
            patch("sys.argv", ["check_stale_doc_refs.py", str(f)]),
            patch.object(Path, "exists", return_value=False),
        ):
            assert main() == 1

    def test_mixed_files_returns_nonzero(self, tmp_path):
        """If any file has stale refs, the whole check fails."""
        clean = tmp_path / "clean.md"
        clean.write_text("# Clean\n")
        stale = tmp_path / "stale.md"
        stale.write_text("Uses `core/gone.py`\n")
        with (
            patch("sys.argv", ["check_stale_doc_refs.py", str(clean), str(stale)]),
            patch.object(Path, "exists", return_value=False),
        ):
            assert main() == 1

    def test_excluded_files_ignored_by_main(self):
        """Archive files passed via CLI should be ignored."""
        with (
            patch(
                "sys.argv",
                [
                    "check_stale_doc_refs.py",
                    "docs/archive/2026-07-20/CLEANUP_REPORT.md",
                ],
            ),
            patch.object(Path, "is_file", return_value=True),
            patch.object(Path, "read_text", return_value="Uses `core/gone.py`\n"),
        ):
            assert main() == 0
