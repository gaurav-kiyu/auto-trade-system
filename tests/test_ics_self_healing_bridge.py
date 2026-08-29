"""Tests for ICS-Self-Healing Bridge (core/ics_self_healing_bridge.py).

Validates:
- Basic wiring between IncidentCommander and SelfHealingOrchestrator
- Processing healing cycle results (success → auto-resolve, failure → escalate)
- Triggering healing for incidents
- Graceful degradation (missing components, disabled bridge)
- Singleton and idempotency
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from core.ics_self_healing_bridge import (
    PATTERN_TO_INCIDENT_SOURCE,
    RECOVERY_TO_SOURCE,
    ICSSelfHealingBridge,
    get_ics_self_healing_bridge,
    reset_ics_self_healing_bridge,
    wire_ics_self_healing,
)
from core.self_healing.models import (
    HealingAction,
    HealingCycleResult,
    HealthStatus,
    RecoveryAction,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_bridge():
    """Reset bridge singleton before each test."""
    reset_ics_self_healing_bridge()
    yield
    reset_ics_self_healing_bridge()


@pytest.fixture
def bridge():
    """Create a fresh ICSSelfHealingBridge."""
    return ICSSelfHealingBridge()


@pytest.fixture
def mock_commander():
    """Create a mock IncidentCommander."""
    cmdr = MagicMock()
    # get_open_incidents returns empty list by default
    cmdr.get_open_incidents.return_value = []
    # create_incident returns a mock incident
    mock_incident = MagicMock()
    mock_incident.to_dict.return_value = {
        "incident_id": "INC-0001",
        "title": "Test incident",
        "source": "test_component",
        "severity": "CRITICAL",
    }
    cmdr.create_incident.return_value = mock_incident
    cmdr._alert_fn = None
    return cmdr


@pytest.fixture
def mock_orchestrator():
    """Create a mock SelfHealingOrchestrator."""
    orch = MagicMock()
    orch.enabled = True
    return orch


@pytest.fixture
def mock_healing_action_success():
    """Create a successful healing action."""
    return HealingAction(
        action=RecoveryAction.RESET_CIRCUIT_BREAKER,
        component="circuit_breaker",
        status="SUCCESS",
        message="Circuit breaker reset to CLOSED",
    )


@pytest.fixture
def mock_healing_action_failed():
    """Create a failed healing action."""
    return HealingAction(
        action=RecoveryAction.RECONNECT_BROKER,
        component="broker",
        status="FAILED",
        message="Broker reconnect failed: timeout",
    )


@pytest.fixture
def mock_healing_result_success(mock_healing_action_success):
    """Create a successful healing cycle result."""
    result = HealingCycleResult()
    result.overall_health = HealthStatus.HEALTHY
    result.actions_taken = [mock_healing_action_success]
    result.n_actions = 1
    result.n_success = 1
    result.n_failed = 0
    result.summary = "1 action taken (1 success, 0 failed)"
    return result


@pytest.fixture
def mock_healing_result_failed(mock_healing_action_failed):
    """Create a failed healing cycle result."""
    result = HealingCycleResult()
    result.overall_health = HealthStatus.UNHEALTHY
    result.actions_taken = [mock_healing_action_failed]
    result.n_actions = 1
    result.n_success = 0
    result.n_failed = 1
    result.summary = "1 action taken (0 success, 1 failed)"
    return result


# ─── Data Mapping Tests ─────────────────────────────────────────────────────


class TestDataMappings:
    """Verify the mapping tables are consistent."""

    def test_pattern_to_incident_source_coverage(self):
        """All failure pattern names map to a known source."""
        known_sources = {
            "circuit_breaker", "broker", "market_feed", "database",
            "configuration", "safety_system", "watchdog", "system_resources",
            "authentication", "network", "consensus", "trading_engine",
            "operator", "runbook", "unknown",
        }
        for source in PATTERN_TO_INCIDENT_SOURCE.values():
            assert source in known_sources, f"Unknown source: {source}"

    def test_recovery_to_source_coverage(self):
        """All recovery actions map to a known source."""
        from core.self_healing.models import RecoveryAction
        recovery_values = {a.value for a in RecoveryAction}
        mapped_values = set(RECOVERY_TO_SOURCE.keys())
        # Every recovery action should have a mapping
        for rv in recovery_values:
            assert rv in mapped_values, f"Missing mapping for recovery action: {rv}"


# ─── Basic Bridge Tests ─────────────────────────────────────────────────────


class TestBasicBridge:
    """Core bridge functionality."""

    def test_bridge_default_enabled(self):
        """Bridge is enabled by default."""
        b = ICSSelfHealingBridge()
        assert b.enabled is True

    def test_bridge_can_be_disabled(self):
        """Bridge can be created disabled."""
        b = ICSSelfHealingBridge(enabled=False)
        assert b.enabled is False

    def test_bridge_not_wired_initially(self):
        """Bridge starts unwired."""
        b = ICSSelfHealingBridge()
        assert b.is_wired is False

    def test_wire_returns_false_when_disabled(self):
        """Disabled bridge returns False from wire()."""
        b = ICSSelfHealingBridge(enabled=False)
        result = b.wire(MagicMock(), MagicMock())
        assert result is False
        assert b.is_wired is False

    def test_wire_success(self, bridge, mock_commander, mock_orchestrator):
        """Bridge wires successfully with valid components."""
        result = bridge.wire(mock_commander, mock_orchestrator)
        assert result is True
        assert bridge.is_wired is True

    def test_wire_idempotent(self, bridge, mock_commander, mock_orchestrator):
        """Wire is idempotent — calling twice returns True both times."""
        r1 = bridge.wire(mock_commander, mock_orchestrator)
        r2 = bridge.wire(mock_commander, mock_orchestrator)
        assert r1 is True
        assert r2 is True

    def test_wire_sets_notify_fn(self, bridge, mock_commander, mock_orchestrator):
        """Wire installs the alert handler as the orchestrator's notify fn."""
        bridge.wire(mock_commander, mock_orchestrator)
        mock_orchestrator.set_notify_fn.assert_called_once()

    def test_unwire_clears(self, bridge, mock_commander, mock_orchestrator):
        """Unwire clears all references."""
        bridge.wire(mock_commander, mock_orchestrator)
        bridge.unwire()
        assert bridge.is_wired is False
        assert bridge.commander is None
        assert bridge.orchestrator is None

    def test_unwire_idempotent(self, bridge):
        """Unwire is safe to call multiple times."""
        bridge.unwire()
        bridge.unwire()
        assert bridge.is_wired is False


# ─── Processing Healing Results ─────────────────────────────────────────────


class TestProcessHealingResult:
    """Processing healing cycle results."""

    def test_process_success_resolves_incident(
        self, bridge, mock_commander, mock_orchestrator,
        mock_healing_result_success,
    ):
        """Successful healing action triggers incident resolution."""
        bridge.wire(mock_commander, mock_orchestrator)
        # Have open incidents to resolve
        mock_commander.get_open_incidents.return_value = [
            {"incident_id": "INC-0001", "source": "circuit_breaker"},
        ]

        result = bridge.process_healing_result(mock_healing_result_success)
        assert result["resolved"] >= 1
        mock_commander.resolve_incident.assert_called()

    def test_process_failure_creates_incident(
        self, bridge, mock_commander, mock_orchestrator,
        mock_healing_result_failed,
    ):
        """Failed healing action creates a critical incident."""
        bridge.wire(mock_commander, mock_orchestrator)
        result = bridge.process_healing_result(mock_healing_result_failed)
        assert result["created"] >= 1
        assert result["escalated"] >= 1
        mock_commander.create_incident.assert_called()

    def test_process_empty_result_does_nothing(
        self, bridge, mock_commander, mock_orchestrator,
    ):
        """Empty healing result doesn't create incidents."""
        empty_result = HealingCycleResult()
        bridge.wire(mock_commander, mock_orchestrator)
        result = bridge.process_healing_result(empty_result)
        assert result["created"] == 0
        assert result["resolved"] == 0
        assert result["escalated"] == 0

    def test_process_disabled_bridge(self, mock_commander, mock_orchestrator):
        """Disabled bridge returns zeros."""
        b = ICSSelfHealingBridge(enabled=False)
        result = b.process_healing_result(MagicMock())
        assert result["created"] == 0
        assert result["resolved"] == 0

    def test_process_no_commander(self, bridge):
        """No commander wired returns zeros."""
        result = bridge.process_healing_result(HealingCycleResult())
        assert result["created"] == 0
        assert result["resolved"] == 0

    def test_process_mixed_actions(
        self, bridge, mock_commander, mock_orchestrator,
        mock_healing_action_success, mock_healing_action_failed,
    ):
        """Mixed success/failure actions are processed independently."""
        mixed_result = HealingCycleResult()
        mixed_result.actions_taken = [
            mock_healing_action_success,
            mock_healing_action_failed,
        ]
        bridge.wire(mock_commander, mock_orchestrator)
        mock_commander.get_open_incidents.return_value = [
            {"incident_id": "INC-0001", "source": "circuit_breaker"},
        ]

        result = bridge.process_healing_result(mixed_result)
        assert result["resolved"] >= 1
        assert result["created"] >= 1
        assert result["escalated"] >= 1


# ─── Trigger Healing for Incident ────────────────────────────────────────────


class TestTriggerHealing:
    """Triggering healing for specific incidents."""

    def test_trigger_healing_calls_orchestrator(
        self, bridge, mock_commander, mock_orchestrator,
    ):
        """Triggering healing for a critical incident calls orchestrator."""
        bridge.wire(mock_commander, mock_orchestrator)
        incident = {
            "incident_id": "INC-0001",
            "source": "broker",
            "severity": "CRITICAL",
        }
        mock_orchestrator.trigger_immediate_cycle.return_value = HealingCycleResult()

        result = bridge.trigger_healing_for_incident(incident)
        assert result["healing_triggered"] is True
        mock_orchestrator.trigger_immediate_cycle.assert_called_once()

    def test_trigger_healing_low_severity_skipped(
        self, bridge, mock_commander, mock_orchestrator,
    ):
        """Low severity incidents don't trigger healing."""
        bridge.wire(mock_commander, mock_orchestrator)
        incident = {
            "incident_id": "INC-0001",
            "source": "broker",
            "severity": "LOW",
        }
        result = bridge.trigger_healing_for_incident(incident)
        assert result["healing_triggered"] is False
        mock_orchestrator.trigger_immediate_cycle.assert_not_called()

    def test_trigger_healing_disabled_bridge(self, mock_commander, mock_orchestrator):
        """Disabled bridge doesn't trigger healing."""
        b = ICSSelfHealingBridge(enabled=False)
        result = b.trigger_healing_for_incident({
            "incident_id": "INC-0001",
            "source": "broker",
            "severity": "CRITICAL",
        })
        assert result["healing_triggered"] is False

    def test_trigger_healing_no_orchestrator(self, bridge):
        """No orchestrator wired doesn't trigger healing."""
        result = bridge.trigger_healing_for_incident({
            "incident_id": "INC-0001",
            "source": "broker",
            "severity": "CRITICAL",
        })
        assert result["healing_triggered"] is False


# ─── Orchestrator Alert Handler ──────────────────────────────────────────────


class TestOrchestratorAlertHandler:
    """Orchestrator alert handler creates incidents."""

    def test_alert_handler_creates_incident(
        self, bridge, mock_commander, mock_orchestrator,
    ):
        """Alert handler creates an incident for broker alerts."""
        bridge.wire(mock_commander, mock_orchestrator)
        bridge._orchestrator_alert_handler("⚠️ Self-Healing Alert\nBroker disconnected")
        mock_commander.create_incident.assert_called_once()

    def test_alert_handler_disabled_skips(
        self, mock_commander, mock_orchestrator,
    ):
        """Disabled bridge skips alert handling."""
        b = ICSSelfHealingBridge(enabled=False)
        b.wire(mock_commander, mock_orchestrator)
        b._orchestrator_alert_handler("⚠️ Self-Healing Alert\nTest")
        mock_commander.create_incident.assert_not_called()

    def test_alert_handler_no_commander(self, bridge):
        """No commander wired skips alert handling."""
        bridge._orchestrator_alert_handler("⚠️ Self-Healing Alert\nTest")
        # Should not crash


# ─── History and Stats ───────────────────────────────────────────────────────


class TestHistoryAndStats:
    """Bridge history and statistics."""

    def test_get_stats_after_wire(self, bridge, mock_commander, mock_orchestrator):
        """Stats reflect wired state."""
        stats = bridge.get_stats()
        assert stats["wired"] is False
        assert stats["enabled"] is True

        bridge.wire(mock_commander, mock_orchestrator)
        stats = bridge.get_stats()
        assert stats["wired"] is True
        assert stats["commander_available"] is True
        assert stats["orchestrator_available"] is True

    def test_get_history_after_processing(
        self, bridge, mock_commander, mock_orchestrator,
        mock_healing_result_success,
    ):
        """Processing a healing result adds to history."""
        bridge.wire(mock_commander, mock_orchestrator)
        bridge.process_healing_result(mock_healing_result_success)
        history = bridge.get_history()
        assert len(history) >= 1
        assert history[0]["status"] == "SUCCESS"

    def test_get_history_limit(
        self, bridge, mock_commander, mock_orchestrator,
    ):
        """History limit is respected."""
        bridge.wire(mock_commander, mock_orchestrator)
        for i in range(5):
            bridge._record_handler_event("test", f"comp-{i}", "SUCCESS", "OK")
        history = bridge.get_history(limit=3)
        assert len(history) == 3

    def test_stats_after_processing(
        self, bridge, mock_commander, mock_orchestrator,
        mock_healing_result_success, mock_healing_result_failed,
    ):
        """Stats reflect processing results."""
        bridge.wire(mock_commander, mock_orchestrator)
        bridge.process_healing_result(mock_healing_result_success)
        bridge.process_healing_result(mock_healing_result_failed)
        stats = bridge.get_stats()
        assert stats["total_events"] == 2
        assert stats["success_count"] >= 1
        assert stats["failed_count"] >= 1


# ─── Component Matching ──────────────────────────────────────────────────────


class TestComponentMatching:
    """Matching text descriptions to components."""

    def test_match_circuit_breaker(self, bridge):
        """Circuit breaker keywords match."""
        assert bridge._match_component("Circuit breaker OPEN") == "circuit_breaker"

    def test_match_broker(self, bridge):
        """Broker keywords match."""
        assert bridge._match_component("Broker disconnected") == "broker"

    def test_match_database(self, bridge):
        """Database keywords match."""
        assert bridge._match_component("Database connection failed") == "database"

    def test_match_disk(self, bridge):
        """Disk space keywords match."""
        assert bridge._match_component("Disk space low") == "system_resources"

    def test_match_unknown(self, bridge):
        """Unknown text returns 'unknown'."""
        assert bridge._match_component("Something random") == "unknown"

    def test_match_case_insensitive(self, bridge):
        """Matching is case-insensitive."""
        assert bridge._match_component("CIRCUIT BREAKER TRIPPED") == "circuit_breaker"


# ─── Singleton Tests ─────────────────────────────────────────────────────────


class TestSingleton:
    """Singleton behavior."""

    def test_get_singleton(self):
        """get_ics_self_healing_bridge returns singleton."""
        b1 = get_ics_self_healing_bridge()
        b2 = get_ics_self_healing_bridge()
        assert b1 is b2

    def test_reset_singleton(self):
        """reset_ics_self_healing_bridge clears singleton."""
        b1 = get_ics_self_healing_bridge()
        reset_ics_self_healing_bridge()
        b2 = get_ics_self_healing_bridge()
        assert b1 is not b2

    def test_reset_clears_wired_state(self, mock_commander, mock_orchestrator):
        """Reset clears wired state."""
        bridge = get_ics_self_healing_bridge()
        bridge.wire(mock_commander, mock_orchestrator)
        reset_ics_self_healing_bridge()
        new_bridge = get_ics_self_healing_bridge()
        assert new_bridge.is_wired is False


# ─── wire_ics_self_healing Convenience Function ──────────────────────────────


class TestWireFunction:
    """Convenience wire function."""

    def test_wire_function_returns_bool(self):
        """wire_ics_self_healing returns a bool."""
        result = wire_ics_self_healing()
        assert isinstance(result, bool)

    def test_wire_function_wired_flag(self):
        """After wire, bridge reports wired=True."""
        result = wire_ics_self_healing()
        if result:
            bridge = get_ics_self_healing_bridge()
            assert bridge.is_wired is True


# ─── Edge Cases ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge case scenarios."""

    def test_process_malformed_result_dict(self, bridge, mock_commander, mock_orchestrator):
        """Processing a malformed dict doesn't crash."""
        bridge.wire(mock_commander, mock_orchestrator)
        result = bridge.process_healing_result({"invalid": True})
        assert isinstance(result, dict)
        assert "created" in result

    def test_process_none_result(self, bridge, mock_commander, mock_orchestrator):
        """Processing None doesn't crash."""
        bridge.wire(mock_commander, mock_orchestrator)
        result = bridge.process_healing_result(None)
        assert isinstance(result, dict)

    def test_trigger_healing_none_incident(self, bridge, mock_commander, mock_orchestrator):
        """Triggering healing with None doesn't crash."""
        bridge.wire(mock_commander, mock_orchestrator)
        result = bridge.trigger_healing_for_incident(None)
        assert result["healing_triggered"] is False

    def test_alert_handler_exception_doesnt_crash(self, bridge, mock_commander, mock_orchestrator):
        """Exception in alert handler is caught gracefully."""
        mock_commander.create_incident.side_effect = Exception("crash")
        bridge.wire(mock_commander, mock_orchestrator)
        # Should not raise
        bridge._orchestrator_alert_handler("⚠️ Self-Healing Alert\nTest")
