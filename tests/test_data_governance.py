"""Tests for core.data_governance — DataGovernor and CleanupScheduler."""

from __future__ import annotations

import tempfile
import threading
from unittest.mock import MagicMock, patch

import pytest
from core.data_governance import CleanupScheduler, DataGovernor

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def minimal_cfg() -> dict:
    return {
        "log_dir": "logs",
        "data_dir": "data",
        "models_dir": "models",
        "reports_dir": "reports",
    }


@pytest.fixture
def full_cfg() -> dict:
    return {
        "log_dir": "logs",
        "data_dir": "data",
        "models_dir": "models",
        "reports_dir": "reports",
        "data_retention_logs_max_files": 50,
        "data_retention_logs_days": 60,
        "data_retention_logs_enabled": True,
        "data_retention_audit_max_files": 100,
        "data_retention_audit_days": 120,
        "data_retention_audit_enabled": False,
        "data_retention_models_max_files": 10,
        "data_retention_models_days": 365,
        "data_retention_models_enabled": True,
        "data_retention_reports_max_files": 30,
        "data_retention_reports_days": 45,
        "data_retention_reports_enabled": True,
        "data_retention_telemetry_max_files": 5,
        "data_retention_telemetry_days": 15,
        "data_retention_telemetry_enabled": False,
    }


# ── DataGovernor tests ────────────────────────────────────────────────────────

class TestDataGovernorConstruction:
    """Verify DataGovernor builds categories correctly."""

    def test_empty_cfg_defaults(self):
        """Empty config should produce 5 categories with safe defaults."""
        g = DataGovernor({})
        cats = g._categories
        assert len(cats) == 5
        names = {c.name for c in cats}
        assert names == {"logs", "audit", "models", "reports", "telemetry"}

    def test_cfg_applies_overrides(self, full_cfg: dict):
        """Config overrides should be reflected in category retention policies."""
        g = DataGovernor(full_cfg)
        cat_map = {c.name: c for c in g._categories}
        assert cat_map["logs"].retention.max_files == 50
        assert cat_map["logs"].retention.max_age_days == 60
        assert cat_map["audit"].retention.max_files == 100
        assert cat_map["audit"].retention.max_age_days == 120
        assert cat_map["audit"].enabled is False
        assert cat_map["models"].retention.max_files == 10
        assert cat_map["models"].retention.max_age_days == 365
        assert cat_map["reports"].retention.max_files == 30
        assert cat_map["reports"].retention.max_age_days == 45
        assert cat_map["telemetry"].retention.max_files == 5
        assert cat_map["telemetry"].retention.max_age_days == 15
        assert cat_map["telemetry"].enabled is False

    def test_none_cfg(self):
        """None config should be treated as empty dict."""
        g = DataGovernor(None)  # type: ignore
        assert len(g._categories) == 5

    def test_custom_dirs(self):
        """Custom directory paths should be used in categories."""
        cfg = {"log_dir": "/custom/logs", "data_dir": "/custom/data"}
        g = DataGovernor(cfg)
        cat_map = {c.name: c for c in g._categories}
        assert cat_map["logs"].path == "/custom/logs"
        assert cat_map["telemetry"].path == "/custom/data"


class TestDataGovernorApplyAll:
    """Test the apply_all() method under various conditions."""

    def test_apply_all_disabled_category(self, minimal_cfg: dict):
        """Disabled categories should return -1 sentinel."""
        g = DataGovernor({**minimal_cfg, "data_retention_audit_enabled": False})
        results = g.apply_all()
        assert results.get("audit") == -1

    def test_apply_all_nonexistent_dir(self, minimal_cfg: dict):
        """Missing directory should return 0 (no files found)."""
        g = DataGovernor({**minimal_cfg, "log_dir": "/nonexistent_path_xyz"})
        results = g.apply_all()
        assert results.get("logs") == 0

    @patch("core.data_governance._RetentionEngine")
    def test_apply_all_with_files(self, mock_engine_class, minimal_cfg: dict):
        """With valid dir and RetentionEngine, should return removal count."""
        mock_engine = MagicMock()
        mock_engine.apply.return_value = ["file1.log", "file2.log"]
        mock_engine_class.return_value = mock_engine

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = {**minimal_cfg, "log_dir": tmpdir}
            g = DataGovernor(cfg)
            results = g.apply_all()
            assert results.get("logs", 0) == 2

    @patch("core.data_governance._RetentionEngine")
    def test_apply_all_engine_error(self, mock_engine_class, minimal_cfg: dict):
        """Engine raising an error should return -2 sentinel."""
        mock_engine = MagicMock()
        mock_engine.apply.side_effect = OSError("Permission denied")
        mock_engine_class.return_value = mock_engine

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = {**minimal_cfg, "log_dir": tmpdir}
            g = DataGovernor(cfg)
            results = g.apply_all()
            assert results.get("logs", 0) == -2

    @patch("core.data_governance._RetentionEngine", None)
    def test_apply_all_engine_unavailable(self, minimal_cfg: dict):
        """Missing RetentionEngine should return -2 for all categories."""
        g = DataGovernor(minimal_cfg)
        results = g.apply_all()
        for cat_name in ("logs", "audit", "models", "reports", "telemetry"):
            assert results.get(cat_name) == -2


class TestDataGovernorPolicySummary:
    """Test get_policy_summary() output."""

    def test_summary_structure(self, minimal_cfg: dict):
        """Summary should contain category info for all 5 categories."""
        g = DataGovernor(minimal_cfg)
        summary = g.get_policy_summary()
        assert len(summary) == 5
        for entry in summary:
            assert "category" in entry
            assert "path" in entry
            assert "max_files" in entry
            assert "max_age_days" in entry
            assert "enabled" in entry

    def test_summary_values(self, full_cfg: dict):
        """Summary values should match config overrides."""
        g = DataGovernor(full_cfg)
        summary_map = {s["category"]: s for s in g.get_policy_summary()}
        assert summary_map["logs"]["max_files"] == 50
        assert summary_map["logs"]["max_age_days"] == 60
        assert summary_map["audit"]["enabled"] is False
        assert summary_map["models"]["max_age_days"] == 365
        assert summary_map["telemetry"]["enabled"] is False


# ── CleanupScheduler tests ───────────────────────────────────────────────────

class TestCleanupScheduler:
    """Test CleanupScheduler start/stop and lifecycle."""

    @pytest.fixture
    def mock_governor(self) -> MagicMock:
        g = MagicMock()
        g.apply_all.return_value = {"logs": 5, "models": 0}
        return g

    def test_initial_state(self, mock_governor: MagicMock):
        """Scheduler should not have a thread running initially."""
        sched = CleanupScheduler(mock_governor, interval_hours=24)
        assert sched._thread is None or not sched._thread.is_alive()

    def test_start_creates_thread(self, mock_governor: MagicMock):
        """start() should create and start a daemon thread."""
        sched = CleanupScheduler(mock_governor, interval_hours=24)
        sched.start()
        assert sched._thread is not None
        assert sched._thread.is_alive()
        assert sched._thread.daemon is True
        assert sched._thread.name == "cleanup-scheduler"
        sched.stop(timeout=5)

    def test_start_twice_is_noop(self, mock_governor: MagicMock):
        """Calling start() again should not create a second thread."""
        sched = CleanupScheduler(mock_governor, interval_hours=24)
        sched.start()
        thread_id = id(sched._thread)
        sched.start()
        assert id(sched._thread) == thread_id
        sched.stop(timeout=5)

    def test_stop_sets_event(self, mock_governor: MagicMock):
        """stop() should set the stop event."""
        sched = CleanupScheduler(mock_governor, interval_hours=24)
        sched.start()
        sched.stop(timeout=5)
        assert sched._stop_event.is_set()

    def test_stop_clears_thread_ref(self, mock_governor: MagicMock):
        """After successful stop(), thread ref should be None."""
        sched = CleanupScheduler(mock_governor, interval_hours=24)
        sched.start()
        sched.stop(timeout=5)
        assert sched._thread is None

    def test_restart_after_stop(self, mock_governor: MagicMock):
        """Scheduler should be restartable after stop()."""
        sched = CleanupScheduler(mock_governor, interval_hours=24)
        sched.start()
        sched.stop(timeout=5)
        sched.start()
        assert sched._thread is not None and sched._thread.is_alive()
        sched.stop(timeout=5)

    def test_run_loop_calls_apply_all(self, mock_governor: MagicMock):
        """The run loop should call apply_all()."""
        sched = CleanupScheduler(mock_governor, interval_hours=0.0001)
        sched.start()
        import time
        time.sleep(0.05)
        sched.stop(timeout=5)
        assert mock_governor.apply_all.called

    def test_run_loop_handles_error(self):
        """Scheduler should not crash if apply_all raises."""
        bad_governor = MagicMock()
        bad_governor.apply_all.side_effect = ValueError("test error")
        sched = CleanupScheduler(bad_governor, interval_hours=0.0001)
        sched.start()
        import time
        time.sleep(0.05)
        sched.stop(timeout=5)
        # Should not have raised — test passes if we reach here

    def test_stop_timeout_does_not_raise(self, mock_governor: MagicMock):
        """stop() should not raise even if thread takes longer than timeout."""
        sched = CleanupScheduler(mock_governor, interval_hours=24)
        sched.start()
        sched.stop(timeout=0.001)  # Very short timeout

    def test_concurrent_stop_safe(self, mock_governor: MagicMock):
        """Concurrent stop() calls should be thread-safe."""
        sched = CleanupScheduler(mock_governor, interval_hours=24)
        sched.start()
        errors = []

        def _do_stop():
            try:
                sched.stop(timeout=5)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_do_stop) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors

    def test_stop_without_start(self, mock_governor: MagicMock):
        """stop() on a never-started scheduler should not raise."""
        sched = CleanupScheduler(mock_governor, interval_hours=24)
        sched.stop(timeout=5)
