"""Tests for core.log_helpers."""

from __future__ import annotations

import os
import time

from core.log_helpers import cleanup_old_prefixed_logs


def test_cleanup_removes_old_prefixed_logs(tmp_path):
    logd = tmp_path / "logs"
    logd.mkdir()
    old = logd / "app_20200101.log"
    old.write_text("x", encoding="utf-8")
    os.utime(old, (time.time() - 40 * 86400, time.time() - 40 * 86400))
    fresh = logd / "app_20990101.log"
    fresh.write_text("y", encoding="utf-8")
    cleanup_old_prefixed_logs(str(logd), "app_", retain_days=30, delete_rotated_variants=True)
    assert not old.is_file()
    assert fresh.is_file()


def test_cleanup_removes_old_rotated_variant(tmp_path):
    logd = tmp_path / "logs"
    logd.mkdir()
    rot = logd / "app_20200101.log.1"
    rot.write_text("z", encoding="utf-8")
    os.utime(rot, (time.time() - 40 * 86400, time.time() - 40 * 86400))
    cleanup_old_prefixed_logs(str(logd), "app_", retain_days=30, delete_rotated_variants=True)
    assert not rot.is_file()


def test_cleanup_skips_wrong_prefix(tmp_path):
    logd = tmp_path / "logs"
    logd.mkdir()
    other = logd / "other_20200101.log"
    other.write_text("x", encoding="utf-8")
    os.utime(other, (time.time() - 40 * 86400, time.time() - 40 * 86400))
    cleanup_old_prefixed_logs(str(logd), "app_", retain_days=30)
    assert other.is_file()
