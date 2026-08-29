"""Tests for the scheduled tasks / cron worker."""

from __future__ import annotations

from realestate.scheduler import (
    SchedulerEngine,
    initialize_scheduler,
)


class TestSchedulerEngine:
    def setup_method(self):
        self.sched = SchedulerEngine()

    def test_register_task(self):
        task = self.sched.register_task(
            task_id="test_task",
            name="Test Task",
            handler=lambda: {"processed": 5, "created": 2},
            interval_seconds=3600,
            description="A test task",
        )
        assert task.task_id == "test_task"
        assert task.name == "Test Task"
        assert task.interval_seconds == 3600
        assert task.next_run > 0

    def test_list_tasks(self):
        self.sched.register_task("t1", "Task 1", lambda: {}, 300)
        self.sched.register_task("t2", "Task 2", lambda: {}, 600)
        tasks = self.sched.list_tasks()
        assert len(tasks) == 2

    def test_get_task(self):
        self.sched.register_task("get_me", "Get Me", lambda: {}, 100)
        assert self.sched.get_task("get_me") is not None
        assert self.sched.get_task("nonexistent") is None

    def test_enable_disable_task(self):
        self.sched.register_task("tog", "Toggle", lambda: {}, 100)
        assert self.sched.enable_task("tog", False)
        assert not self.sched.get_task("tog").is_enabled
        assert self.sched.enable_task("tog", True)
        assert self.sched.get_task("tog").is_enabled

    def test_run_task_success(self):
        self.sched.register_task("ok", "OK", lambda: {"processed": 10}, 100)
        result = self.sched.run_task("ok")
        assert result.success
        assert result.items_processed == 10
        assert result.duration_ms > 0

    def test_run_task_not_found(self):
        result = self.sched.run_task("does_not_exist")
        assert not result.success
        assert result.error == "Task not found"

    def test_run_task_no_handler(self):
        self.sched._tasks["no_handler"] = type("task", (), {"handler": None, "task_id": "no_handler", "name": "NoHandler", "total_runs": 0, "total_errors": 0, "last_run": 0, "next_run": 0, "last_duration_ms": 0, "is_enabled": True})()
        result = self.sched.run_task("no_handler")
        assert not result.success
        assert "handler" in result.error.lower()

    def test_run_all_tasks(self):
        self.sched.register_task("a", "A", lambda: {"processed": 1}, 100)
        self.sched.register_task("b", "B", lambda: {"processed": 2}, 100)
        results = self.sched.run_all_tasks()
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_run_due_tasks(self):
        self.sched.register_task("due", "Due", lambda: {"processed": 3}, -1)  # Negative = already due
        results = self.sched.run_due_tasks()
        assert len(results) >= 1

    def test_get_stats(self):
        self.sched.register_task("stats1", "Stats1", lambda: {}, 100)
        self.sched.register_task("stats2", "Stats2", lambda: {}, 200)
        stats = self.sched.get_stats()
        assert stats["total_tasks"] == 2
        assert stats["enabled_tasks"] == 2

    def test_get_task_results(self):
        self.sched.register_task("res", "Res", lambda: {"processed": 7}, 100)
        self.sched.run_task("res")
        results = self.sched.get_task_results("res")
        assert len(results) == 1
        assert results[0].items_processed == 7

    def test_initialize_default_tasks(self):
        sched = initialize_scheduler()
        tasks = sched.list_tasks()
        assert len(tasks) >= 3  # cleanup_expired, cleanup_stale, check_saved
        task_ids = [t.task_id for t in tasks]
        assert "cleanup_expired_listings" in task_ids
        assert "cleanup_stale_notifications" in task_ids
        assert "check_saved_searches" in task_ids

    def test_task_to_dict(self):
        self.sched.register_task("dict_test", "Dict Test", lambda: {}, 3600)
        task = self.sched.get_task("dict_test")
        d = task.to_dict()
        assert d["task_id"] == "dict_test"
        assert d["name"] == "Dict Test"
        assert d["interval_seconds"] == 3600

    def test_run_task_tracks_stats(self):
        self.sched.register_task("track", "Track", lambda: {"processed": 1}, 100)
        self.sched.run_task("track")
        self.sched.run_task("track")
        stats = self.sched.get_stats()
        assert stats["total_runs"] == 2
