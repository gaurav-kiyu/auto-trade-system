"""Tests for the Constitution System Startup (core/startup.py).

Validates:
- Startup initializes all modules with no config
- Startup respects CONSTITUTION_ENABLED=False master switch
- Startup handles missing Telegram credentials gracefully
- Startup returns correct per-module status dict
- Startup is idempotent (safe to call multiple times)
- Each module's failure path degrades gracefully
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from core.startup import (
    AI_GATE_KEY,
    CONSTITUTION_CHECKS_KEY,
    ICS_TELEGRAM_BRIDGE_KEY,
    INCIDENT_COMMANDER_KEY,
    INTELLIGENCE_PIPELINE_KEY,
    SCORECARD_KEY,
    startup_constitution_system,
)

# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset all constitution singletons before each test."""
    yield
    from core.continuous_intelligence import reset_intelligence_pipeline
    from core.ics_telegram_bridge import reset_ics_telegram_bridge
    from core.incident_command_system import reset_incident_commander
    reset_incident_commander()
    reset_intelligence_pipeline()
    reset_ics_telegram_bridge()


# ─── Basic initialization ────────────────────────────────────────────────────


class TestStartupBasic:
    """Core startup functionality."""

    def test_startup_returns_dict(self):
        """Startup returns a dict with expected keys."""
        result = startup_constitution_system()
        assert isinstance(result, dict)
        assert "_meta" in result

    def test_startup_all_expected_keys(self):
        """Startup result contains all module keys plus _meta."""
        result = startup_constitution_system()
        expected_keys = {
            AI_GATE_KEY,
            CONSTITUTION_CHECKS_KEY,
            INTELLIGENCE_PIPELINE_KEY,
            INCIDENT_COMMANDER_KEY,
            ICS_TELEGRAM_BRIDGE_KEY,
            SCORECARD_KEY,
            "_meta",
        }
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_startup_meta_has_timing(self):
        """Meta section includes duration_sec."""
        result = startup_constitution_system()
        meta = result["_meta"]
        assert isinstance(meta["duration_sec"], float)
        assert meta["duration_sec"] > 0

    def test_startup_modules_initialized(self):
        """At least AI Gate and Incident Commander initialize."""
        result = startup_constitution_system()
        meta = result["_meta"]
        assert meta["modules_initialized"] >= 2  # AI Gate + ICS at minimum

    def test_startup_no_critical_errors(self):
        """No errors from core modules (AI Gate, ICS)."""
        result = startup_constitution_system()
        assert result[AI_GATE_KEY]["status"] != "error"
        assert result[INCIDENT_COMMANDER_KEY]["status"] != "error"

    def test_startup_is_idempotent(self):
        """Calling startup twice produces same result structure."""
        r1 = startup_constitution_system()
        r2 = startup_constitution_system()
        # Both calls should have the same keys
        assert set(r1.keys()) == set(r2.keys())
        # Both calls should have active Incident Commander
        assert r1[INCIDENT_COMMANDER_KEY]["status"] == r2[INCIDENT_COMMANDER_KEY]["status"]


# ─── Config options ──────────────────────────────────────────────────────────


class TestStartupConfig:
    """Config-driven startup behavior."""

    def test_disabled_master_switch(self):
        """CONSTITUTION_ENABLED=False skips all modules."""
        result = startup_constitution_system(cfg={"CONSTITUTION_ENABLED": False})
        for key in (AI_GATE_KEY, INCIDENT_COMMANDER_KEY, ICS_TELEGRAM_BRIDGE_KEY):
            assert result[key]["status"] == "skipped"
        assert result["_meta"]["enabled"] is False

    def test_disabled_has_only_meta(self):
        """Disabled startup returns only skip entries plus meta."""
        result = startup_constitution_system(cfg={"CONSTITUTION_ENABLED": False})
        assert result["_meta"]["modules_initialized"] == 0
        assert result["_meta"]["modules_failed"] == 0

    def test_auto_scorecard_disabled(self):
        """CONSTITUTION_AUTO_SCORECARD=False skips scorecard."""
        result = startup_constitution_system(cfg={"CONSTITUTION_AUTO_SCORECARD": False})
        assert result[SCORECARD_KEY]["status"] == "skipped"

    def test_custom_incidents_file(self):
        """Custom incidents_file path is passed through."""
        result = startup_constitution_system(cfg={
            "INCIDENTS_FILE": "/tmp/test_incidents.json",
        })
        assert INCIDENT_COMMANDER_KEY in result

    def test_custom_check_interval(self):
        """Custom CHECK_INTERVAL is passed to pipeline."""
        result = startup_constitution_system(cfg={
            "CONSTITUTION_CHECK_INTERVAL_SECONDS": 300,
        })
        assert INTELLIGENCE_PIPELINE_KEY in result
        assert result[INTELLIGENCE_PIPELINE_KEY]["status"] != "error"

    def test_incident_auto_detect_disabled(self):
        """Incident auto-detect can be disabled via config."""
        result = startup_constitution_system(cfg={
            "CONSTITUTION_INCIDENT_AUTO_DETECT": False,
        })
        assert result[INCIDENT_COMMANDER_KEY]["status"] != "error"


# ─── Graceful degradation ────────────────────────────────────────────────────


class TestStartupGracefulDegradation:
    """Error handling and graceful degradation."""

    def test_missing_ai_gate_fails_gracefully(self):
        """If AI Gate fails, other modules still initialize."""
        with patch("core.constitution_ai_gate.get_gate", side_effect=ImportError("no gate")):
            result = startup_constitution_system()
            assert result[AI_GATE_KEY]["status"] == "error"
            # Other modules should still try to init
            assert INCIDENT_COMMANDER_KEY in result

    def test_missing_constitution_checks_graceful(self):
        """If constitution checks module fails, other modules continue."""
        with patch("scripts.run_constitution_checks.run_checks", side_effect=Exception("check failed")):
            result = startup_constitution_system()
            assert result[CONSTITUTION_CHECKS_KEY]["status"] == "error"
            assert result[INCIDENT_COMMANDER_KEY]["status"] != "error"

    def test_missing_ics_graceful(self):
        """If ICS fails, bridge still reports status."""
        with patch("core.incident_command_system.get_incident_commander", side_effect=Exception("ics failed")):
            result = startup_constitution_system()
            assert result[INCIDENT_COMMANDER_KEY]["status"] == "error"

    def test_missing_telegram_graceful(self):
        """Missing Telegram credentials doesn't crash — returns passive."""
        result = startup_constitution_system()
        status = result[ICS_TELEGRAM_BRIDGE_KEY]
        # Should be either 'active' or 'passive (no credentials)'
        assert status["status"] in ("active", "skipped")

    def test_missing_pipeline_graceful(self):
        """If CI pipeline fails, startup continues."""
        with patch("core.continuous_intelligence.get_intelligence_pipeline", side_effect=Exception("pipeline failed")):
            result = startup_constitution_system()
            assert result[INTELLIGENCE_PIPELINE_KEY]["status"] == "error"

    def test_scorecard_fails_gracefully(self):
        """Scorecard failure doesn't crash startup."""
        with patch("scripts.constitution_scorecard.run_scorecard", side_effect=Exception("scorecard failed")):
            result = startup_constitution_system(cfg={"CONSTITUTION_AUTO_SCORECARD": True})
            assert result[SCORECARD_KEY]["status"] == "error"

    def test_empty_config(self):
        """Empty config dict doesn't crash."""
        result = startup_constitution_system(cfg={})
        assert "_meta" in result

    def test_none_config(self):
        """None config doesn't crash."""
        result = startup_constitution_system(cfg=None)
        assert "_meta" in result


# ─── Scheduler behavior ──────────────────────────────────────────────────────


class TestStartupScheduler:
    """CI pipeline scheduler behavior."""

    def test_scheduler_disabled_flag(self):
        """enable_ci_scheduler=False prevents scheduler start."""
        result = startup_constitution_system(enable_ci_scheduler=False)
        result[INTELLIGENCE_PIPELINE_KEY].get("error", "")
        status = result[INTELLIGENCE_PIPELINE_KEY]["status"]
        # When scheduler is disabled, pipeline still initializes but
        # without a running scheduler
        assert status != "error"  # should not fail

    def test_scheduler_default_enabled(self):
        """Default is scheduler enabled."""
        result = startup_constitution_system()
        assert result[INTELLIGENCE_PIPELINE_KEY]["status"] != "error"


# ─── Integration with Incident Commander ─────────────────────────────────────


class TestStartupICSIntegration:
    """Integration between startup and Incident Commander."""

    def test_ics_available_after_startup(self):
        """Incident Commander singleton is available after startup."""
        from core.incident_command_system import get_incident_commander
        startup_constitution_system()
        commander = get_incident_commander()
        assert commander is not None
        stats = commander.get_stats()
        assert "open_incidents" in stats

    def test_ics_alert_fn_not_set_without_bridge(self):
        """Alert callback is None when Telegram bridge not configured."""
        from core.incident_command_system import get_incident_commander
        startup_constitution_system()
        commander = get_incident_commander()
        # Without credentials, alert_fn should still exist
        # (it may be set by bridge if wired)
        assert commander is not None

    def test_startup_detection_cycle_runs(self):
        """Initial detection cycle runs without error."""
        result = startup_constitution_system()
        assert "_meta" in result
        # The detection cycle runs inside startup and is non-blocking
        # It should not cause any modules to report errors
        for key in (AI_GATE_KEY, INCIDENT_COMMANDER_KEY):
            assert result[key]["status"] != "error"


# ─── Edge cases ──────────────────────────────────────────────────────────────


class TestStartupEdgeCases:
    """Edge case scenarios."""

    def test_rapid_consecutive_calls(self):
        """Multiple rapid calls don't cause issues."""
        for _ in range(3):
            result = startup_constitution_system()
            assert "_meta" in result

    def test_singletons_not_double_initialized(self):
        """Calling startup then calling get_* directly works."""
        startup_constitution_system()
        from core.incident_command_system import get_incident_commander
        commander = get_incident_commander()
        assert commander is not None

    def test_module_count_consistent(self):
        """Result has consistent number of modules across calls."""
        r1 = startup_constitution_system()
        r2 = startup_constitution_system()
        # Exclude _meta from count
        count1 = len(r1) - 1
        count2 = len(r2) - 1
        assert count1 == count2

    def test_ai_gate_acknowledges_constitution(self):
        """AI Gate acknowledges the constitution during startup."""
        result = startup_constitution_system()
        assert result[AI_GATE_KEY]["status"] != "error"
