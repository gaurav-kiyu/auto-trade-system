"""Tests for core/data_governance.py — retention policies + cleanup scheduler."""

import tempfile

from core.data_governance import CleanupScheduler, DataGovernor


class TestDataGovernor:
    def test_policy_summary_structure(self):
        cfg = {}
        gov = DataGovernor(cfg)
        summary = gov.get_policy_summary()
        assert isinstance(summary, list)
        assert len(summary) >= 5
        categories = {s["category"] for s in summary}
        assert "logs" in categories
        assert "audit" in categories
        assert "models" in categories
        assert "reports" in categories
        assert "telemetry" in categories

    def test_policy_summary_has_required_fields(self):
        gov = DataGovernor({})
        for entry in gov.get_policy_summary():
            assert "category" in entry
            assert "path" in entry
            assert "max_files" in entry
            assert "max_age_days" in entry
            assert "enabled" in entry

    def test_apply_all_returns_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {
                "log_dir": tmp,
                "data_dir": tmp,
                "models_dir": tmp,
                "reports_dir": tmp,
            }
            gov = DataGovernor(cfg)
            results = gov.apply_all()
            assert isinstance(results, dict)
            for cat in ("logs", "audit", "models", "reports", "telemetry"):
                assert cat in results

    def test_apply_all_handles_missing_dir(self):
        gov = DataGovernor({
            "log_dir": "nonexistent_dir_xyz",
            "data_dir": "nonexistent_dir_xyz",
            "models_dir": "nonexistent_dir_xyz",
            "reports_dir": "nonexistent_dir_xyz",
        })
        results = gov.apply_all()
        for cat, count in results.items():
            assert count == 0  # no files in nonexistent dir

    def test_disabled_category_returns_minus_one(self):
        cfg = {
            "data_retention_logs_enabled": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            cfg.update({"log_dir": tmp, "data_dir": tmp, "models_dir": tmp, "reports_dir": tmp})
            gov = DataGovernor(cfg)
            results = gov.apply_all()
            assert results.get("logs") == -1


class TestCleanupScheduler:
    def test_start_stop(self):
        gov = DataGovernor({})
        scheduler = CleanupScheduler(gov, interval_hours=999)  # won't fire in test
        scheduler.start()
        thread = scheduler._thread
        assert thread is not None
        assert thread.is_alive()
        scheduler.stop()
        thread.join(timeout=5)
        assert not thread.is_alive()
        # After stop, _thread is reset to None for restartability
        assert scheduler._thread is None

    def test_does_not_start_twice(self):
        gov = DataGovernor({})
        scheduler = CleanupScheduler(gov, interval_hours=999)
        scheduler.start()
        t1 = scheduler._thread
        scheduler.start()
        t2 = scheduler._thread
        assert t1 is t2  # same thread object
        scheduler.stop(timeout=5)
        # After stop, _thread is reset to None
        assert scheduler._thread is None

    def test_restart_after_stop(self):
        """Scheduler can be started again after being stopped."""
        gov = DataGovernor({})
        scheduler = CleanupScheduler(gov, interval_hours=999)
        scheduler.start()
        t1 = scheduler._thread
        scheduler.stop(timeout=5)
        assert scheduler._thread is None
        # Restart
        scheduler.start()
        t2 = scheduler._thread
        assert t2 is not None
        assert t2 is not t1  # new thread
        assert t2.is_alive()
        scheduler.stop(timeout=5)
