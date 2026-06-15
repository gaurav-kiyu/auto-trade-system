"""
Tests for scripts/db_backup.py — automated database backup mechanism.

Remediates:
  - GAP-09: Add automated DB backup mechanism
"""

from __future__ import annotations

import os
from pathlib import Path


from scripts.db_backup import (
    cleanup_old_backups,
    create_backup,
    discover_db_files,
    find_project_root,
    run_backup,
)


class TestFindProjectRoot:
    """find_project_root — auto-detection of project root."""

    def test_returns_path(self):
        root = find_project_root()
        assert isinstance(root, Path)
        assert root.is_dir()

    def test_has_pyproject_toml(self):
        root = find_project_root()
        assert (root / "pyproject.toml").exists() or (root / "index_config.defaults.json").exists()


class TestDiscoverDbFiles:
    """discover_db_files — finding .db files."""

    def test_empty_directory(self, tmp_path):
        """Empty directory returns no files."""
        files = discover_db_files(tmp_path)
        assert files == []

    def test_finds_db_files(self, tmp_path):
        """Directory with .db files returns them."""
        (tmp_path / "trades.db").touch()
        (tmp_path / "trade_journal.db").touch()
        (tmp_path / "notes.txt").touch()  # Not a .db file

        files = discover_db_files(tmp_path)
        assert len(files) == 2
        assert any(f.name == "trades.db" for f in files)
        assert any(f.name == "trade_journal.db" for f in files)

    def test_excludes_patterns(self, tmp_path):
        """Files matching exclude patterns are skipped."""
        (tmp_path / "trades.db").touch()
        (tmp_path / "ml_tracker.db").touch()

        files = discover_db_files(tmp_path, exclude=["ml_tracker"])
        assert len(files) == 1
        assert files[0].name == "trades.db"

    def test_skips_directories(self, tmp_path):
        """Directories with .db extension are not included."""
        db_dir = tmp_path / "test.db"
        db_dir.mkdir()

        files = discover_db_files(tmp_path)
        assert files == []


class TestCreateBackup:
    """create_backup — timestamped backup copies."""

    def test_creates_backup_file(self, tmp_path):
        """Backup creates a copy of the source file."""
        source = tmp_path / "trades.db"
        source.write_text("test content")

        backup_dir = tmp_path / "backups"
        backup_path = create_backup(source, backup_dir, timestamp="20260101_120000")

        assert backup_path.exists()
        assert backup_path.name == "trades_20260101_120000.db"
        assert backup_path.read_text() == "test content"

    def test_creates_backup_dir_if_missing(self, tmp_path):
        """Backup directory is created if it doesn't exist."""
        source = tmp_path / "trades.db"
        source.write_text("data")

        backup_dir = tmp_path / "new_backups" / "subdir"
        backup_path = create_backup(source, backup_dir, timestamp="20260101_120000")

        assert backup_path.exists()
        assert backup_dir.is_dir()

    def test_auto_timestamp(self, tmp_path):
        """Timestamp is auto-generated if not provided."""
        source = tmp_path / "trades.db"
        source.write_text("data")

        backup_dir = tmp_path / "backups"
        backup_path = create_backup(source, backup_dir)

        assert backup_path.exists()
        assert backup_path.name.startswith("trades_")
        assert backup_path.suffix == ".db"


class TestCleanupOldBackups:
    """cleanup_old_backups — retention-based removal."""

    def test_removes_old_backups(self, tmp_path):
        """Backups older than retention_days are removed."""
        import time

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        # Create an "old" backup (modify mtime to be 40 days ago)
        old_backup = backup_dir / "trades_20250101_120000.db"
        old_backup.write_text("old")
        old_mtime = time.time() - (40 * 86400)
        os.utime(str(old_backup), (old_mtime, old_mtime))

        # Create a "new" backup (current time)
        new_backup = backup_dir / "trades_20260101_120000.db"
        new_backup.write_text("new")

        removed = cleanup_old_backups(backup_dir, retention_days=30)

        assert old_backup.exists() is False
        assert new_backup.exists() is True
        assert old_backup in removed

    def test_no_removal_for_recent_backups(self, tmp_path):
        """Backups within retention window are kept."""
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        recent = backup_dir / "trades_20260101_120000.db"
        recent.write_text("recent")

        removed = cleanup_old_backups(backup_dir, retention_days=30)
        assert len(removed) == 0
        assert recent.exists() is True

    def test_dry_run_does_not_delete(self, tmp_path):
        """Dry run does not actually delete files."""
        import time

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        old_backup = backup_dir / "trades_20250101_120000.db"
        old_backup.write_text("old")
        old_mtime = time.time() - (40 * 86400)
        os.utime(str(old_backup), (old_mtime, old_mtime))

        removed = cleanup_old_backups(backup_dir, retention_days=30, dry_run=True)

        # File should still exist after dry run
        assert old_backup.exists() is True
        # But should still be listed as "to be removed"
        assert len(removed) > 0

    def test_nonexistent_backup_dir(self, tmp_path):
        """Non-existent backup directory returns empty list."""
        removed = cleanup_old_backups(tmp_path / "nonexistent")
        assert removed == []


class TestRunBackup:
    """run_backup — full backup cycle."""

    def test_backup_cycle(self, tmp_path):
        """Full backup cycle: discover → backup → cleanup."""
        # Create test DB files
        (tmp_path / "trades.db").write_text("trades data")
        (tmp_path / "journal.db").write_text("journal data")

        results = run_backup(
            project_root=tmp_path,
            backup_dir_name="my_backups",
            retention_days=30,
            dry_run=False,
        )

        assert results["success"] is True
        assert len(results["db_files_found"]) == 2
        assert len(results["backups_created"]) == 2

        # Check backup files exist
        backup_dir = tmp_path / "my_backups"
        assert backup_dir.is_dir()
        backup_files = list(backup_dir.glob("*.db"))
        assert len(backup_files) == 2

    def test_dry_run(self, tmp_path):
        """Dry run does not create files."""
        (tmp_path / "trades.db").write_text("data")

        results = run_backup(
            project_root=tmp_path,
            backup_dir_name="backups",
            dry_run=True,
        )

        assert results["success"] is True
        assert len(results["db_files_found"]) == 1
        assert len(results["backups_created"]) == 0

        # Backup dir should not exist
        assert not (tmp_path / "backups").exists()

    def test_no_db_files(self, tmp_path):
        """No .db files produces empty results."""
        results = run_backup(
            project_root=tmp_path,
            dry_run=False,
        )

        assert results["success"] is True
        assert results["db_files_found"] == []
        assert results["backups_created"] == []

    def test_backup_creates_dir(self, tmp_path):
        """Backup directory is created if it doesn't exist."""
        (tmp_path / "trades.db").write_text("data")

        results = run_backup(
            project_root=tmp_path,
            backup_dir_name="deep/nested/backups",
            dry_run=False,
        )

        assert results["success"] is True
        backup_dir = tmp_path / "deep" / "nested" / "backups"
        assert backup_dir.is_dir()
        assert len(results["backups_created"]) == 1


class TestCLI:
    """CLI entry point parsing."""

    def test_help_does_not_crash(self):
        """python scripts/db_backup.py --help exits cleanly."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "scripts/db_backup.py", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "usage" in result.stdout.lower()

    def test_dry_run_flag(self):
        """--dry-run flag is accepted."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "scripts/db_backup.py", "--dry-run"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
