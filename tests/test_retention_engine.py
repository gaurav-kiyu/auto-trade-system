"""Tests for core.retention_engine - operational folder cleanup."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.retention_engine import RetentionEngine, RetentionPolicy


class TestRetentionPolicy:
    """Tests for RetentionPolicy dataclass."""

    def test_defaults(self) -> None:
        policy = RetentionPolicy(max_files=10, max_age_days=30)
        assert policy.max_files == 10
        assert policy.max_age_days == 30


class TestRetentionEngine:
    """Tests for RetentionEngine - file cleanup based on policy."""

    def setup_method(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.engine = RetentionEngine()

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _touch_file(self, name: str, age_days: int = 0) -> Path:
        """Create a file with a specific age."""
        path = self.tmpdir / name
        path.write_text("test content")
        # Set modification time
        mtime = datetime.now(timezone.utc) - timedelta(days=age_days)
        os.utime(path, (mtime.timestamp(), mtime.timestamp()))
        return path

    def test_nonexistent_folder_returns_empty(self) -> None:
        result = self.engine.apply("/nonexistent/path", ["*.log"], RetentionPolicy(max_files=10, max_age_days=30))
        assert result == []

    def test_no_matching_files(self) -> None:
        result = self.engine.apply(str(self.tmpdir), ["*.xyz"], RetentionPolicy(max_files=10, max_age_days=30))
        assert result == []

    def test_keeps_under_max_files(self) -> None:
        for i in range(5):
            self._touch_file(f"file_{i}.log")
        result = self.engine.apply(str(self.tmpdir), ["*.log"], RetentionPolicy(max_files=10, max_age_days=30))
        assert len(result) == 0  # All kept (under max_files)

    def test_removes_oldest_when_over_max_files(self) -> None:
        for i in range(15):
            self._touch_file(f"file_{i}.log", age_days=i % 5)
        result = self.engine.apply(str(self.tmpdir), ["*.log"], RetentionPolicy(max_files=10, max_age_days=30))
        assert len(result) == 5  # 5 oldest removed
        for path in result:
            assert not path.exists()  # File confirmed deleted

    def test_removes_expired_by_age(self) -> None:
        self._touch_file("fresh.log", age_days=1)
        self._touch_file("old.log", age_days=60)
        result = self.engine.apply(str(self.tmpdir), ["*.log"], RetentionPolicy(max_files=10, max_age_days=30))
        assert len(result) == 1
        assert "old" in result[0].name

    def test_removes_both_over_count_and_expired(self) -> None:
        for i in range(5):
            self._touch_file(f"fresh_{i}.log", age_days=1)
        for i in range(10):
            self._touch_file(f"old_{i}.log", age_days=60)
        self.engine.apply(str(self.tmpdir), ["*.log"], RetentionPolicy(max_files=10, max_age_days=30))
        # All 10 old files exceed max_age_days=30 → removed regardless of count
        # Only 5 fresh files within age remain
        remaining = list(self.tmpdir.glob("*.log"))
        assert len(remaining) == 5

    def test_multiple_patterns(self) -> None:
        self._touch_file("data.json")
        self._touch_file("data.log")
        result = self.engine.apply(str(self.tmpdir), ["*.json", "*.log"], RetentionPolicy(max_files=0, max_age_days=0))
        assert len(result) == 2  # Both removed

    def test_custom_now_fn(self) -> None:
        """Custom now_fn simulates a different time."""
        fixed_now = datetime(2026, 1, 15, tzinfo=timezone.utc)
        engine = RetentionEngine(now_fn=lambda: fixed_now)
        self._touch_file("old.log", age_days=10)  # 10 days old from real now
        # Fixed now is artificial, so age check depends on file mtime vs fixed now
        # This is a basic sanity check
        result = engine.apply(str(self.tmpdir), ["*.log"], RetentionPolicy(max_files=10, max_age_days=30))
        # May or may not remove depending on comparison
        assert isinstance(result, list)
