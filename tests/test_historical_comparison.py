"""Tests for scripts.historical_comparison — automated release-to-release comparison."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.historical_comparison import (
    ComparisonReport,
    ConfigDiff,
    DiffStat,
    DocDiff,
    HistoricalComparer,
    ModuleDiff,
    FileDiffReport,
)

from core.capacity_planning import ScalingTrigger


class TestDiffStat:
    """DiffStat dataclass tests."""

    def test_defaults(self):
        stat = DiffStat()
        assert stat.files_changed == 0
        assert stat.insertions == 0
        assert stat.deletions == 0
        assert stat.files_added == []
        assert stat.files_deleted == []
        assert stat.files_modified == []

    def test_to_dict(self):
        stat = DiffStat(files_changed=5, insertions=100, deletions=20)
        d = stat.to_dict()
        assert d["files_changed"] == 5
        assert d["insertions"] == 100
        assert d["deletions"] == 20


class TestModuleDiff:
    """ModuleDiff dataclass tests."""

    def test_defaults(self):
        diff = ModuleDiff()
        assert diff.modules_added == []
        assert diff.modules_removed == []
        assert diff.public_symbols_added == []

    def test_to_dict(self):
        diff = ModuleDiff(
            modules_added=["core/new_module.py"],
            modules_removed=["core/deleted.py"],
        )
        d = diff.to_dict()
        assert "core/new_module.py" in d["modules_added"]
        assert "core/deleted.py" in d["modules_removed"]


class TestFileDiffReport:
    """FileDiffReport dataclass tests."""

    def test_defaults(self):
        td = FileDiffReport()
        assert td.total_tests_current == 0
        assert td.total_tests_previous == 0

    def test_has_test_changes(self):
        td = FileDiffReport(test_files_added=["tests/test_new.py"])
        assert td.has_test_changes is True


class TestConfigDiff:
    """ConfigDiff dataclass tests."""

    def test_defaults(self):
        cd = ConfigDiff()
        assert cd.keys_added == []
        assert cd.keys_removed == []

    def test_counts(self):
        cd = ConfigDiff(keys_added=["NEW_KEY"], keys_removed=["OLD_KEY"])
        d = cd.to_dict()
        assert d["count_added"] == 1
        assert d["count_removed"] == 1


class TestDocDiff:
    """DocDiff dataclass tests."""

    def test_defaults(self):
        dd = DocDiff()
        assert dd.docs_stale == []
        assert dd.module_mismatches == 0


class TestComparisonReport:
    """ComparisonReport dataclass tests."""

    def test_defaults(self):
        report = ComparisonReport()
        assert report.has_regressions is False
        assert report.regressions == []

    def test_to_dict(self):
        report = ComparisonReport(
            source_revision="v2.52.0",
            target_revision="v2.53.0",
            has_regressions=False,
        )
        d = report.to_dict()
        assert d["source_revision"] == "v2.52.0"
        assert d["target_revision"] == "v2.53.0"
        assert d["has_regressions"] is False


class TestScalingTrigger:
    """ScalingTrigger dataclass tests."""

    def test_defaults(self):
        st = ScalingTrigger(
            name="test_trigger",
            resource="disk_free_space",
            threshold=5.0,
            direction="below",
            severity="WARN",
        )
        assert st.name == "test_trigger"
        assert st.threshold == 5.0
        assert st.direction == "below"
        assert st.severity == "WARN"
        assert st.action == "log"  # default
        assert st.cooldown_seconds == 3600  # default

    def test_should_fire_above(self):
        st = ScalingTrigger(
            name="high_usage",
            resource="disk_usage",
            threshold=90.0,
            direction="above",
            severity="WARN",
        )
        assert st.should_fire(95.0) is True
        assert st.should_fire(85.0) is False

    def test_should_fire_below(self):
        st = ScalingTrigger(
            name="low_space",
            resource="disk_free",
            threshold=5.0,
            direction="below",
            severity="WARN",
        )
        assert st.should_fire(3.0) is True
        assert st.should_fire(10.0) is False

    def test_cooldown_respects_timer(self):
        st = ScalingTrigger(
            name="test",
            resource="disk_free",
            threshold=5.0,
            direction="below",
            severity="WARN",
            cooldown_seconds=3600,
        )
        import time
        st.last_fired = time.time() - 100  # 100 seconds ago
        assert st.should_fire(3.0) is False  # Still in cooldown

    def test_cooldown_expired(self):
        st = ScalingTrigger(
            name="test",
            resource="disk_free",
            threshold=5.0,
            direction="below",
            severity="WARN",
            cooldown_seconds=3600,
        )
        import time
        st.last_fired = time.time() - 3700  # Over an hour ago
        assert st.should_fire(3.0) is True

    def test_to_dict(self):
        st = ScalingTrigger(
            name="test", resource="mem", threshold=500.0,
            direction="above", severity="WARN",
        )
        d = st.to_dict()
        assert d["name"] == "test"
        assert d["threshold"] == 500.0
        assert d["severity"] == "WARN"


class TestHistoricalComparer:
    """HistoricalComparer tests — uses mocked git commands."""

    def test_init_defaults(self):
        comparer = HistoricalComparer()
        assert comparer._exclude_dirs is not None
        assert comparer._exclude_exts is not None

    def test_init_with_config(self):
        comparer = HistoricalComparer({
            "historical_comparison_exclude_dirs": ["custom_dir"],
            "historical_comparison_exclude_exts": [".xyz"],
        })
        assert "custom_dir" in comparer._exclude_dirs
        assert ".xyz" in comparer._exclude_exts

    @patch.object(HistoricalComparer, '_is_git_repo', return_value=False)
    def test_compare_no_git(self, mock_is_git):
        comparer = HistoricalComparer()
        report = comparer.compare("v1", "v2")
        assert report.has_regressions is True
        assert "Not a git repository" in report.regressions

    @patch.object(HistoricalComparer, '_is_git_repo', return_value=True)
    @patch.object(HistoricalComparer, '_revision_exists', return_value=False)
    def test_compare_revision_not_found(self, mock_rev, mock_git):
        comparer = HistoricalComparer()
        report = comparer.compare("nonexistent", "HEAD")
        assert report.has_regressions is True
        assert any("nonexistent" in r for r in report.regressions)

    @patch.object(HistoricalComparer, '_is_git_repo', return_value=True)
    @patch.object(HistoricalComparer, '_revision_exists', side_effect=[True, True])
    @patch.object(HistoricalComparer, '_compute_diff_stat')
    @patch.object(HistoricalComparer, '_compute_module_diff')
    @patch.object(HistoricalComparer, '_compute_test_diff')
    @patch.object(HistoricalComparer, '_compute_config_diff')
    @patch.object(HistoricalComparer, '_compute_doc_diff')
    def test_compare_full_flow(
        self, mock_doc, mock_config, mock_test, mock_module, mock_stat, mock_rev, mock_git,
    ):
        """Happy path: all computations work."""
        mock_stat.return_value = DiffStat(files_changed=5, insertions=50, deletions=10)
        mock_module.return_value = ModuleDiff()
        mock_test.return_value = FileDiffReport()
        mock_config.return_value = ConfigDiff()
        mock_doc.return_value = DocDiff()

        comparer = HistoricalComparer()
        report = comparer.compare("v1", "v2")
        assert report.source_revision == "v1"
        assert report.target_revision == "v2"
        assert report.diff_stat.files_changed == 5

    def test_extract_public_symbols(self):
        comparer = HistoricalComparer()
        content = "\n".join([
            "import os",
            "",
            "class MyClass:",
            "    pass",
            "",
            "def my_function():",
            "    pass",
            "",
            "def _private_fn():",
            "    pass",
            "",
            "class _PrivateClass:",
            "    pass",
            "",
            "async def async_fn():",
            "    pass",
        ])
        symbols = comparer._extract_public_symbols(content)
        assert "MyClass" in symbols
        assert "my_function" in symbols
        assert "async_fn" in symbols
        assert "_private_fn" not in symbols
        assert "_PrivateClass" not in symbols

    def test_extract_public_symbols_empty(self):
        comparer = HistoricalComparer()
        symbols = comparer._extract_public_symbols("")
        assert symbols == set()

    def test_extract_public_symbols_no_matches(self):
        comparer = HistoricalComparer()
        content = "# just a comment\nimport sys\nx = 1\n"
        symbols = comparer._extract_public_symbols(content)
        assert symbols == set()

    @patch.object(HistoricalComparer, '_run_git')
    def test_list_python_files(self, mock_git):
        mock_git.return_value = "core/foo.py\ncore/bar.py\nscripts/baz.py"
        comparer = HistoricalComparer()
        files = comparer._list_python_files("HEAD")
        assert "core/foo.py" in files
        assert "core/bar.py" in files

    @patch.object(HistoricalComparer, '_run_git')
    def test_list_test_files(self, mock_git):
        mock_git.return_value = "core/foo.py\ntests/test_foo.py\nscripts/baz.py\ntests/test_bar.py"
        comparer = HistoricalComparer()
        files = comparer._list_test_files("HEAD")
        assert "tests/test_foo.py" in files
        assert "tests/test_bar.py" in files
        assert "core/foo.py" not in files

    @patch.object(HistoricalComparer, '_run_git', return_value="")
    def test_list_python_files_empty(self, mock_git):
        comparer = HistoricalComparer()
        assert comparer._list_python_files("HEAD") == []


class TestCapacityPlannerScalingIntegration:
    """Tests for scaling trigger integration with CapacityPlanner."""

    def test_load_default_triggers(self):
        from core.capacity_planning import CapacityPlanner, DEFAULT_SCALING_TRIGGERS
        planner = CapacityPlanner()
        triggers = planner.get_triggers()
        assert len(triggers) > 0
        assert len(triggers) == len(DEFAULT_SCALING_TRIGGERS)

    def test_custom_triggers_from_config(self):
        from core.capacity_planning import CapacityPlanner
        custom = [
            {"name": "custom_test", "resource": "test_resource",
             "threshold": 50.0, "direction": "above", "severity": "WARN"},
        ]
        planner = CapacityPlanner({"capacity_scaling_triggers": custom})
        triggers = planner.get_triggers()
        assert len(triggers) == 1
        assert triggers[0].name == "custom_test"
        assert triggers[0].threshold == 50.0

    def test_set_alert_callback(self):
        from core.capacity_planning import CapacityPlanner
        planner = CapacityPlanner()
        called = []

        def callback(msg):
            called.append(msg)

        planner.set_alert_callback(callback)
        assert planner._alert_callback is not None
        planner._alert_callback("test message")
        assert called == ["test message"]

    def test_check_triggers_no_fire(self):
        """Triggers should not fire when values are within thresholds."""
        from core.capacity_planning import CapacityPlanner, CapacityReport, ResourceMetric
        planner = CapacityPlanner()
        report = CapacityReport(
            metrics=[ResourceMetric(
                resource="disk_free_space", current_value=100.0,
                unit="GB", status="OK", threshold=5.0,
            )],
        )
        fired = planner.check_triggers(report)
        assert len(fired) == 0

    def test_check_triggers_fires(self):
        """Triggers should fire when values exceed thresholds."""
        from core.capacity_planning import CapacityPlanner, CapacityReport, ResourceMetric
        planner = CapacityPlanner()
        report = CapacityReport(
            metrics=[ResourceMetric(
                resource="disk_free_space", current_value=1.0,
                unit="GB", status="CRITICAL", threshold=5.0,
            )],
        )
        fired = planner.check_triggers(report)
        # At least disk_free_critical should fire
        disk_fired = [f for f in fired if "disk_free" in f["trigger"]["name"]]
        assert len(disk_fired) > 0

    def test_check_triggers_with_analyze(self):
        """check_triggers should work with auto-analyze (no report provided)."""
        from core.capacity_planning import CapacityPlanner
        planner = CapacityPlanner()
        fired = planner.check_triggers()  # No report = auto-analyze
        assert isinstance(fired, list)
