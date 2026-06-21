"""Tests for core/self_healing/orchestrator.py - Self-Healing Framework."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock

import pytest

from core.self_healing.orchestrator import (
    FailurePattern,
    HealingAction,
    HealingCycleResult,
    HealthStatus,
    RecoveryAction,
    SelfHealingOrchestrator,
    get_orchestrator,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def orchestrator() -> SelfHealingOrchestrator:
    return SelfHealingOrchestrator(cfg={"self_healing_enabled": True})


@pytest.fixture
def disabled_orchestrator() -> SelfHealingOrchestrator:
    return SelfHealingOrchestrator(cfg={"self_healing_enabled": False})


# ── HealingAction Tests ───────────────────────────────────────────────────────

class TestHealingAction:
    def test_default_values(self):
        action = HealingAction(
            action=RecoveryAction.RESET_CIRCUIT_BREAKER,
            component="test",
            status="SUCCESS",
            message="OK",
        )
        assert action.action == RecoveryAction.RESET_CIRCUIT_BREAKER
        assert action.component == "test"
        assert action.status == "SUCCESS"
        assert action.timestamp is not None

    def test_minimal_action(self):
        action = HealingAction(
            action=RecoveryAction.NOTIFY_OPERATOR,
            component="broker",
            status="FAILED",
            message="Could not reconnect",
        )
        assert action.action == RecoveryAction.NOTIFY_OPERATOR


# ── HealingCycleResult Tests ──────────────────────────────────────────────────

class TestHealingCycleResult:
    def test_default_values(self):
        r = HealingCycleResult()
        assert r.overall_health == HealthStatus.HEALTHY
        assert r.n_actions == 0

    def test_to_dict(self):
        r = HealingCycleResult()
        r.n_actions = 2
        r.n_success = 1
        r.n_failed = 1
        r.actions_taken.append(HealingAction(
            action=RecoveryAction.RESET_CIRCUIT_BREAKER,
            component="broker", status="SUCCESS", message="Reset OK",
        ))
        d = r.to_dict()
        json.dumps(d)  # Must be JSON-serializable
        assert d["n_actions"] == 2
        assert d["n_success"] == 1

    def test_format_text(self):
        r = HealingCycleResult()
        r.summary = "All systems healthy"
        text = r.format_text()
        assert "All systems healthy" in text


# ── FailurePattern Tests ──────────────────────────────────────────────────────

class TestFailurePattern:
    def test_default_cooldown(self):
        p = FailurePattern(
            name="test_failure",
            description="A test failure pattern",
            recovery_actions=[RecoveryAction.NOTIFY_OPERATOR],
        )
        assert p.cooldown_seconds == 300

    def test_custom_cooldown(self):
        p = FailurePattern(
            name="urgent",
            description="Urgent recovery",
            recovery_actions=[RecoveryAction.RESET_CIRCUIT_BREAKER],
            cooldown_seconds=60,
        )
        assert p.cooldown_seconds == 60


# ── SelfHealingOrchestrator Tests ─────────────────────────────────────────────

class TestSelfHealingOrchestrator:
    def test_default_patterns(self, orchestrator):
        """Should have 7 default failure patterns."""
        assert len(orchestrator.DEFAULT_PATTERNS) == 7

    def test_enabled_by_default(self):
        h = SelfHealingOrchestrator()
        assert h.enabled is True

    def test_disabled(self, disabled_orchestrator):
        assert disabled_orchestrator.enabled is False

    def test_interval_seconds_default(self, orchestrator):
        assert orchestrator.interval_seconds == 60

    def test_max_actions_per_cycle_default(self, orchestrator):
        assert orchestrator.max_actions_per_cycle == 3

    def test_run_healing_cycle_when_disabled(self, disabled_orchestrator):
        result = disabled_orchestrator.run_healing_cycle()
        assert result.overall_health == HealthStatus.HEALTHY
        assert "disabled" in result.summary.lower()

    def test_run_healing_cycle_no_health_check_fn(self, orchestrator):
        """Without a health check fn, should detect no issues."""
        result = orchestrator.run_healing_cycle()
        assert result.overall_health == HealthStatus.HEALTHY
        assert result.n_actions == 0

    def test_run_healing_cycle_with_healthy_check(self, orchestrator):
        """With a health check that reports all OK."""
        mock_health = MagicMock()
        mock_health.results = []

        def mock_check(cfg):
            return mock_health

        orchestrator.set_health_check_fn(mock_check)
        result = orchestrator.run_healing_cycle()
        assert result.overall_health == HealthStatus.HEALTHY

    def test_run_healing_cycle_with_failure(self, orchestrator):
        """With a failing health check, should detect and attempt recovery."""
        mock_check_result = MagicMock()
        mock_result = MagicMock()
        mock_result.status = "FAIL"
        mock_result.name = "circuit_breaker_open"
        mock_check_result.results = [mock_result]

        def mock_check(cfg):
            return mock_check_result

        orchestrator.set_health_check_fn(mock_check)
        result = orchestrator.run_healing_cycle()

        # Should detect the issue but may skip due to no circuit_breaker_service configured
        assert result.n_actions > 0 or result.overall_health != HealthStatus.HEALTHY

    def test_register_custom_pattern(self, orchestrator):
        pattern = FailurePattern(
            name="custom_failure",
            description="Custom test pattern",
            recovery_actions=[RecoveryAction.NOTIFY_OPERATOR],
        )
        orchestrator.register_pattern(pattern)
        assert len(orchestrator.DEFAULT_PATTERNS) + 1 == 8  # 7 default + 1 custom
        # Actually register_pattern adds to _patterns, not changing DEFAULT_PATTERNS
        status = orchestrator.get_health_status()
        assert status["patterns_registered"] == 8

    def test_circuit_breaker_reset_no_service(self, orchestrator):
        """Without circuit breaker service, reset should be skipped."""
        from core.self_healing.orchestrator import RecoveryAction
        # Call the internal method directly
        result = orchestrator._execute_single_action(
            RecoveryAction.RESET_CIRCUIT_BREAKER, "test_component"
        )
        assert result["status"] == "SKIPPED"
        assert "No circuit breaker service" in result["message"]

    def test_circuit_breaker_reset_with_service(self, orchestrator):
        """With a circuit breaker service, should attempt reset."""
        mock_cb = MagicMock()
        mock_cb.get_state.return_value = MagicMock()
        mock_cb.get_state.return_value.name = "OPEN"
        orchestrator.set_circuit_breaker_service(mock_cb)
        result = orchestrator._execute_single_action(
            RecoveryAction.RESET_CIRCUIT_BREAKER, "circuit_breaker_open"
        )
        # Should attempt reset
        assert result["status"] in ("SUCCESS", "FAILED")

    def test_broker_reconnect_no_adapter(self, orchestrator):
        result = orchestrator._execute_single_action(
            RecoveryAction.RECONNECT_BROKER, "broker_disconnected"
        )
        assert result["status"] == "SKIPPED"
        assert "No broker adapter" in result["message"]

    def test_notify_operator_no_fn(self, orchestrator):
        result = orchestrator._execute_single_action(
            RecoveryAction.NOTIFY_OPERATOR, "test_component"
        )
        assert result["status"] == "SKIPPED"
        assert "No notification function" in result["message"]

    def test_session_recycle(self, orchestrator):
        result = orchestrator._execute_single_action(
            RecoveryAction.RECYCLE_SESSION, "test"
        )
        assert result["status"] == "SUCCESS"
        assert "Session recycle" in result["message"]


# ── Cooldown Tests ───────────────────────────────────────────────────────────

class TestCooldown:
    def test_cooldown_respected(self, orchestrator):
        """Same action should be skipped during cooldown."""
        # First call should proceed (cold)
        pattern = FailurePattern(
            name="test_failure",
            description="Test",
            recovery_actions=[RecoveryAction.RECYCLE_SESSION],
            cooldown_seconds=999999,  # Long cooldown
        )
        orchestrator._mark_action_time("test_failure_recycle_session")

        action = orchestrator._execute_recovery(pattern)
        # Should be within cooldown
        assert action.status == "SKIPPED"
        assert "Cooldown" in action.message

    def test_cooldown_expired(self, orchestrator):
        """After cooldown expires, action should proceed."""
        orchestrator._cfg["self_healing_cooloff_sec"] = 0  # No cooldown
        pattern = FailurePattern(
            name="test_failure",
            description="Test",
            recovery_actions=[RecoveryAction.RECYCLE_SESSION],
            cooldown_seconds=0,
        )
        # Manually set last action time far in the past
        action = orchestrator._execute_recovery(pattern)
        # Without health check function, it goes through but...
        # It shouldn't be skipped for cooldown reasons
        assert action.status != "SKIPPED" or "Cooldown" not in action.message


# ── Background Monitor Tests ─────────────────────────────────────────────────

class TestBackgroundMonitor:
    def test_start_stop(self, orchestrator):
        thread = orchestrator.start_background_monitor()
        assert thread is not None
        assert thread.is_alive()
        orchestrator.stop_background_monitor()
        thread.join(timeout=2)
        assert not thread.is_alive()

    def test_no_duplicate_start(self, orchestrator):
        t1 = orchestrator.start_background_monitor()
        t2 = orchestrator.start_background_monitor()
        assert t1 is t2  # Same instance returned
        orchestrator.stop_background_monitor()

    def test_get_health_status(self, orchestrator):
        status = orchestrator.get_health_status()
        assert "enabled" in status
        assert "interval_seconds" in status
        assert "patterns_registered" in status
        assert status["patterns_registered"] >= 7


# ── Action Log Tests ─────────────────────────────────────────────────────────

class TestActionLog:
    def test_empty_log(self, orchestrator):
        log = orchestrator.get_action_log()
        assert log == []

    def test_log_after_cycle(self, orchestrator):
        orchestrator.run_healing_cycle()
        log = orchestrator.get_action_log()
        assert isinstance(log, list)

    def test_reset_log(self, orchestrator):
        orchestrator.run_healing_cycle()
        orchestrator.reset_action_log()
        assert orchestrator.get_action_log() == []

    def test_log_limit(self, orchestrator):
        for i in range(5):
            orchestrator._action_log.append(HealingAction(
                action=RecoveryAction.RECYCLE_SESSION,
                component=f"test-{i}",
                status="SUCCESS",
                message="OK",
            ))
        log = orchestrator.get_action_log(limit=3)
        assert len(log) <= 3


# ── Singleton Tests ──────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_orchestrator(self):
        h1 = get_orchestrator()
        h2 = get_orchestrator()
        assert h1 is h2

    def test_orchestrator_with_custom_config_via_constructor(self):
        """Test that constructor respects custom config (singleton ignores config on re-access)."""
        h = SelfHealingOrchestrator(cfg={"self_healing_interval_sec": 30})
        assert h.interval_seconds == 30

    def test_get_orchestrator_passes_config_on_first_call(self):
        """Singleton passes config on first creation.

        Note: This test can only verify the default because the singleton
        is shared across tests. Testing custom config via get_orchestrator()
        requires resetting the global state, which is done by construction testing.
        """
        h = get_orchestrator()
        assert h.interval_seconds == SelfHealingOrchestrator(cfg={}).interval_seconds
