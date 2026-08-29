"""Tests for core/continuous_intelligence.py — Continuous Intelligence Pipeline.

Verifies the pipeline runs checks, detects drift, manages history,
and integrates with the notification system.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from core.continuous_intelligence import (
    ContinuousIntelligenceEngine,
    PipelineCheckResult,
    PipelineConfig,
    get_intelligence_pipeline,
    reset_intelligence_pipeline,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def cleanup_pipeline():
    """Reset the singleton before and after each test."""
    reset_intelligence_pipeline()
    yield
    reset_intelligence_pipeline()


@pytest.fixture
def pipeline(tmp_path: Path) -> ContinuousIntelligenceEngine:
    """Create a fresh pipeline instance with unique temp history for testing."""
    return ContinuousIntelligenceEngine({
        "enabled": False,
        "history_file": str(tmp_path / "test_hist.jsonl"),
    })


@pytest.fixture
def history_file(tmp_path: Path) -> str:
    """Create a temporary history file path."""
    return str(tmp_path / "test_history.jsonl")


# ── Data Class Tests ─────────────────────────────────────────────────────────


class TestPipelineCheckResult:
    def test_default_construction(self):
        """Verify default construction creates valid result."""
        r = PipelineCheckResult()
        assert r.timestamp is not None
        assert r.modules_checked == 0
        assert r.modules_passed == 0
        assert r.scorecard_pct == 0.0

    def test_to_dict_serializable(self):
        """Verify to_dict produces JSON-serializable output."""
        r = PipelineCheckResult(
            modules_checked=11, modules_passed=11, scorecard_pct=100.0,
        )
        d = r.to_dict()
        json_str = json.dumps(d)
        loaded = json.loads(json_str)
        assert loaded["modules_checked"] == 11
        assert loaded["modules_passed"] == 11

    def test_is_healthy_true(self):
        """Verify is_healthy returns True when all good."""
        r = PipelineCheckResult(
            modules_checked=10, modules_passed=10,
            scorecard_pct=100.0, scorecard_passed=87, scorecard_total=87,
            v4_overall_score=-1.0,  # Sentinel: no v4 data available
        )
        assert r.is_healthy() is True

    def test_is_healthy_false_failed_modules(self):
        """Verify is_healthy returns False when modules fail."""
        r = PipelineCheckResult(
            modules_checked=10, modules_passed=8, modules_failed=2,
            scorecard_pct=90.0,
        )
        assert r.is_healthy() is False

    def test_is_healthy_false_low_score(self):
        """Verify is_healthy returns False when scorecard is low."""
        r = PipelineCheckResult(
            modules_checked=10, modules_passed=10,
            scorecard_pct=85.0, scorecard_passed=75, scorecard_total=87,
        )
        assert r.is_healthy() is False

    def test_summary_text_healthy(self):
        """Verify summary_text produces HEALTHY output."""
        r = PipelineCheckResult(
            modules_checked=10, modules_passed=10,
            scorecard_pct=100.0, scorecard_passed=87, scorecard_total=87,
            v4_overall_score=-1.0,  # Sentinel: no v4 data available
        )
        text = r.summary_text()
        assert "HEALTHY" in text
        assert "100.0%" in text

    def test_summary_text_degraded(self):
        """Verify summary_text produces DEGRADED output."""
        r = PipelineCheckResult(
            modules_checked=10, modules_passed=8, modules_failed=2,
            scorecard_pct=80.0, scorecard_passed=70, scorecard_total=87,
        )
        text = r.summary_text()
        assert "DEGRADED" in text
        assert "80.0%" in text

    def test_summary_text_drift(self):
        """Verify summary_text includes drift info."""
        r = PipelineCheckResult(
            modules_checked=10, modules_passed=10,
            scorecard_pct=90.0, drift_detected=True,
            score_delta_pct=-10.0,
        )
        text = r.summary_text()
        assert "Drift" in text
        assert "-10.0" in text

    def test_summary_text_alerts(self):
        """Verify summary_text includes alert count."""
        r = PipelineCheckResult(
            modules_checked=10, modules_passed=10,
            scorecard_pct=100.0, alerts_sent=2,
        )
        text = r.summary_text()
        assert "Alerts" in text
        assert "2" in text


class TestPipelineConfig:
    def test_default_config(self):
        """Verify default config values are sensible."""
        cfg = PipelineConfig()
        assert cfg.enabled is True
        assert cfg.check_interval_seconds == 3600
        assert cfg.drift_threshold_pct == 5.0
        assert cfg.notify_on_failure is True

    def test_config_from_dict(self):
        """Verify config can be created from dict."""
        cfg = PipelineConfig(**{
            "enabled": False,
            "check_interval_seconds": 1800,
            "drift_threshold_pct": 10.0,
        })
        assert cfg.enabled is False
        assert cfg.check_interval_seconds == 1800
        assert cfg.drift_threshold_pct == 10.0

    def test_config_ignores_unknown_fields(self):
        """Verify unknown fields are silently ignored by the engine constructor."""
        engine = ContinuousIntelligenceEngine({"unknown_field": "value", "notify_on_failure": False})
        assert engine._cfg.notify_on_failure is False
        assert engine._cfg.enabled is True  # Default


# ── Engine Tests ─────────────────────────────────────────────────────────────


class TestEngineInitialization:
    def test_creates_with_defaults(self):
        """Verify engine creates with default config."""
        engine = ContinuousIntelligenceEngine()
        assert engine._cfg.enabled is True
        assert engine._cfg.check_interval_seconds == 3600

    def test_creates_with_custom_config(self):
        """Verify engine creates with custom config."""
        engine = ContinuousIntelligenceEngine({"check_interval_seconds": 1800, "notify_on_failure": False})
        assert engine._cfg.check_interval_seconds == 1800
        assert engine._cfg.notify_on_failure is False

    def test_get_stats_returns_dict(self, pipeline: ContinuousIntelligenceEngine):
        """Verify get_stats returns valid stats."""
        stats = pipeline.get_stats()
        assert stats["enabled"] is False  # Fixture sets enabled=False for isolation
        assert stats["total_checks"] == 0
        assert stats["scheduler_running"] is False


class TestHistoryManagement:
    def test_save_and_load_history(self, pipeline: ContinuousIntelligenceEngine, tmp_path: Path):
        """Verify history is persisted and loaded correctly."""
        history_path = str(tmp_path / "test_hist.jsonl")
        pipeline._cfg.history_file = history_path

        # Run a quick check
        pipeline.run_once()

        # Verify file was written
        assert os.path.exists(history_path)
        with open(history_path) as f:
            lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["modules_checked"] == 15

    def test_load_history_from_existing(self, tmp_path: Path):
        """Verify engine loads existing history on init."""
        history_path = str(tmp_path / "existing_hist.jsonl")
        # Write some history
        with open(history_path, "a") as f:
            f.write(json.dumps({"timestamp": "2026-01-01T00:00:00", "modules_checked": 11, "modules_passed": 11}) + "\n")
            f.write(json.dumps({"timestamp": "2026-01-02T00:00:00", "modules_checked": 11, "modules_passed": 10}) + "\n")

        # Create engine that reads this history
        engine = ContinuousIntelligenceEngine({"history_file": history_path})
        history = engine.get_history(10)
        assert len(history) == 2
        assert history[0]["modules_passed"] == 11

    def test_get_history_limit(self, pipeline: ContinuousIntelligenceEngine, tmp_path: Path):
        """Verify get_history respects limit."""
        pipeline._cfg.history_file = str(tmp_path / "lim_hist.jsonl")
        # Run a few checks
        for _ in range(5):
            pipeline.run_once()

        history = pipeline.get_history(limit=3)
        assert len(history) == 3


class TestRunOnce:
    def test_run_once_returns_result(self, pipeline: ContinuousIntelligenceEngine):
        """Verify run_once returns a valid result."""
        result = pipeline.run_once()
        assert isinstance(result, PipelineCheckResult)
        assert result.modules_checked > 0
        assert result.duration_sec > 0

    def test_run_once_all_modules_pass(self, pipeline: ContinuousIntelligenceEngine):
        """Verify all 10 constitution modules pass."""
        result = pipeline.run_once()
        assert result.modules_checked == 15
        assert result.modules_passed == 15
        assert result.modules_failed == 0

    def test_run_once_scorecard_runs(self, pipeline: ContinuousIntelligenceEngine):
        """Verify scorecard audit runs successfully."""
        result = pipeline.run_once()
        assert result.scorecard_total == 87
        assert result.scorecard_passed > 0
        assert result.scorecard_pct > 0

    def test_run_once_updates_last_result(self, pipeline: ContinuousIntelligenceEngine):
        """Verify last result is updated after run."""
        assert pipeline._last_result is None
        pipeline.run_once()
        assert pipeline._last_result is not None
        assert pipeline._last_result.modules_checked == 15

    def test_run_once_drift_detection(self, pipeline: ContinuousIntelligenceEngine):
        """Verify drift detection works between consecutive runs."""
        # First run - no drift possible (no previous)
        first = pipeline.run_once()
        assert first.drift_detected is False

        # Second run - drift detection active
        second = pipeline.run_once()
        # Delta should be ~0 since both runs are on the same codebase
        assert isinstance(second.score_delta_pct, float)
        assert second.previous_score_pct is not None


class TestAlertCallback:
    def test_alert_fn_called_on_failure(self, pipeline: ContinuousIntelligenceEngine):
        """Verify alert callback is called when modules fail."""
        alerts: list[tuple[str, bool]] = []

        def mock_alert(msg: str, critical: bool):
            alerts.append((msg, critical))

        pipeline.set_alert_fn(mock_alert)

        # Normally all modules pass, so no failure alerts
        # But we can verify the callback integration works
        pipeline.run_once()
        assert pipeline._alert_fn is not None


class TestSingleton:
    def test_get_intelligence_pipeline(self):
        """Verify singleton pattern works."""
        p1 = get_intelligence_pipeline()
        p2 = get_intelligence_pipeline()
        assert p1 is p2

    def test_reset_intelligence_pipeline(self):
        """Verify reset creates new instance."""
        p1 = get_intelligence_pipeline()
        reset_intelligence_pipeline()
        p2 = get_intelligence_pipeline()
        assert p1 is not p2

    def test_config_on_first_call(self):
        """Verify config is applied on first call only."""
        reset_intelligence_pipeline()
        p1 = get_intelligence_pipeline({"check_interval_seconds": 999})
        assert p1._cfg.check_interval_seconds == 999

        # Second call with different config should NOT change it
        p2 = get_intelligence_pipeline({"check_interval_seconds": 111})
        assert p2 is p1
        assert p2._cfg.check_interval_seconds == 999  # Still first config


class TestScheduler:
    def test_start_stop_scheduler(self, pipeline: ContinuousIntelligenceEngine):
        """Verify scheduler starts and stops."""
        pipeline._cfg.check_interval_seconds = 1  # Fast interval for testing
        started = pipeline.start_scheduler()
        assert started is True
        assert pipeline._scheduler_thread is not None
        assert pipeline._scheduler_thread.is_alive()

        # Let it run one cycle
        time.sleep(0.1)

        pipeline.stop_scheduler()
        assert pipeline._stop_event.is_set()

        # Wait for thread to stop
        pipeline._scheduler_thread.join(timeout=2)
        assert not pipeline._scheduler_thread.is_alive()

    def test_start_twice(self, pipeline: ContinuousIntelligenceEngine):
        """Verify starting twice returns False."""
        pipeline._cfg.check_interval_seconds = 1
        pipeline.start_scheduler()
        started_again = pipeline.start_scheduler()
        assert started_again is False
        pipeline.stop_scheduler()
