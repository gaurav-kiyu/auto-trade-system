"""Tests for core/incident_command_system.py — Incident Command System.

Tests incident creation, lifecycle management, deduplication,
detection cycles, auto-resolution, and persistence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from core.incident_command_system import (
    Incident,
    IncidentCommander,
    IncidentConfig,
    IncidentSeverity,
    IncidentStatus,
    get_incident_commander,
    reset_incident_commander,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def cleanup():
    """Reset singleton before and after each test."""
    reset_incident_commander()
    yield
    reset_incident_commander()


@pytest.fixture
def commander(tmp_path: Path) -> IncidentCommander:
    """Create a fresh commander with temp storage."""
    return IncidentCommander({
        "incidents_file": str(tmp_path / "test_incidents.json"),
        "notify_on_critical": False,
        "notify_on_high": False,
        "notify_on_resolve": False,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASS TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestIncidentDataClass:
    def test_default_construction(self):
        """Verify default incident has correct initial state."""
        inc = Incident(incident_id="INC-001", title="Test", description="Desc", source="test", severity=IncidentSeverity.HIGH)
        assert inc.status == IncidentStatus.DETECTED
        assert inc.is_open is True
        assert inc.created_at is not None
        assert inc.acknowledged_at is None

    def test_to_dict_serializable(self):
        """Verify to_dict produces valid JSON-serializable output."""
        inc = Incident(
            incident_id="INC-001", title="Test", description="Desc",
            source="test", severity=IncidentSeverity.CRITICAL,
            status=IncidentStatus.RESOLVED, resolved_at="2026-01-01T00:00:00",
        )
        d = inc.to_dict()
        assert d["incident_id"] == "INC-001"
        assert d["severity"] == "CRITICAL"
        assert d["status"] == "RESOLVED"
        json_str = json.dumps(d)
        assert len(json_str) > 0

    def test_is_open_true_for_detected(self):
        """Verify DETECTED incidents are open."""
        inc = Incident(incident_id="INC-001", title="T", description="D", source="s", severity=IncidentSeverity.LOW)
        assert inc.is_open is True

    def test_is_open_true_for_investigating(self):
        """Verify INVESTIGATING incidents are open."""
        inc = Incident(incident_id="INC-001", title="T", description="D", source="s", severity=IncidentSeverity.LOW, status=IncidentStatus.INVESTIGATING)
        assert inc.is_open is True

    def test_is_open_false_for_resolved(self):
        """Verify RESOLVED incidents are not open."""
        inc = Incident(incident_id="INC-001", title="T", description="D", source="s", severity=IncidentSeverity.LOW, status=IncidentStatus.RESOLVED)
        assert inc.is_open is False

    def test_is_open_false_for_closed(self):
        """Verify CLOSED incidents are not open."""
        inc = Incident(incident_id="INC-001", title="T", description="D", source="s", severity=IncidentSeverity.LOW, status=IncidentStatus.CLOSED)
        assert inc.is_open is False

    def test_severity_enum_values(self):
        """Verify severity enum has correct values."""
        assert IncidentSeverity.CRITICAL.value == "CRITICAL"
        assert IncidentSeverity.HIGH.value == "HIGH"
        assert IncidentSeverity.MEDIUM.value == "MEDIUM"
        assert IncidentSeverity.LOW.value == "LOW"

    def test_status_enum_values(self):
        """Verify status enum has correct values."""
        assert IncidentStatus.DETECTED.value == "DETECTED"
        assert IncidentStatus.INVESTIGATING.value == "INVESTIGATING"
        assert IncidentStatus.RESOLVED.value == "RESOLVED"
        assert IncidentStatus.CLOSED.value == "CLOSED"


class TestIncidentConfig:
    def test_default_config(self):
        """Verify default config values."""
        cfg = IncidentConfig()
        assert cfg.enabled is True
        assert cfg.notify_on_critical is True
        assert cfg.auto_resolve is True

    def test_config_from_dict(self):
        """Verify config from dict."""
        cfg = IncidentConfig(**{"enabled": False, "notify_on_critical": False})
        assert cfg.enabled is False
        assert cfg.notify_on_critical is False


# ═══════════════════════════════════════════════════════════════════════════════
# COMMANDER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestCommanderInitialization:
    def test_creates_with_defaults(self):
        """Verify commander creates with default config."""
        c = IncidentCommander()
        assert c._cfg.enabled is True
        assert c._cfg.notify_on_critical is True

    def test_get_stats_empty(self, commander: IncidentCommander):
        """Verify stats start at zero."""
        stats = commander.get_stats()
        assert stats["total_incidents"] == 0
        assert stats["open_incidents"] == 0


class TestIncidentCreation:
    def test_create_incident_basic(self, commander: IncidentCommander):
        """Verify basic incident creation."""
        inc = commander.create_incident(
            title="Test incident",
            description="Something went wrong",
            source="test_module",
            severity=IncidentSeverity.HIGH,
        )
        assert inc is not None
        assert inc.incident_id == "INC-0001"
        assert inc.title == "Test incident"
        assert inc.severity == IncidentSeverity.HIGH
        assert inc.status == IncidentStatus.DETECTED

    def test_create_incident_string_severity(self, commander: IncidentCommander):
        """Verify string severity is converted."""
        inc = commander.create_incident(
            title="Test", description="Desc", source="s",
            severity="critical",
        )
        assert inc is not None
        assert inc.severity == IncidentSeverity.CRITICAL

    def test_create_incident_deduplication(self, commander: IncidentCommander):
        """Verify duplicate incidents are prevented."""
        inc1 = commander.create_incident(
            title="Duplicate test", description="First", source="mod1",
            severity=IncidentSeverity.HIGH,
        )
        assert inc1 is not None

        inc2 = commander.create_incident(
            title="Duplicate test", description="Second", source="mod1",
            severity=IncidentSeverity.HIGH,
        )
        assert inc2 is None  # Duplicate prevented

    def test_create_different_source_allowed(self, commander: IncidentCommander):
        """Verify incidents from different sources with same title are allowed."""
        inc1 = commander.create_incident(title="Issue", description="A", source="mod1", severity=IncidentSeverity.LOW)
        inc2 = commander.create_incident(title="Issue", description="B", source="mod2", severity=IncidentSeverity.LOW)
        assert inc1 is not None
        assert inc2 is not None
        assert inc1.incident_id != inc2.incident_id

    def test_different_title_same_source_allowed(self, commander: IncidentCommander):
        """Verify different titles from same source are allowed."""
        inc1 = commander.create_incident(title="Issue A", description="A", source="mod1", severity=IncidentSeverity.LOW)
        inc2 = commander.create_incident(title="Issue B", description="B", source="mod1", severity=IncidentSeverity.LOW)
        assert inc1 is not None
        assert inc2 is not None


class TestIncidentLifecycle:
    def test_acknowledge_incident(self, commander: IncidentCommander):
        """Verify acknowledging an incident changes status."""
        inc = commander.create_incident(title="Test", description="D", source="s", severity=IncidentSeverity.HIGH)
        assert inc is not None
        result = commander.acknowledge_incident(inc.incident_id, "Looking into it")
        assert result is True
        updated = commander.get_incident(inc.incident_id)
        assert updated is not None
        assert updated["status"] == "INVESTIGATING"
        assert updated["acknowledged_at"] is not None

    def test_acknowledge_nonexistent(self, commander: IncidentCommander):
        """Verify acknowledging non-existent incident returns False."""
        assert commander.acknowledge_incident("INC-9999") is False

    def test_acknowledge_resolved(self, commander: IncidentCommander):
        """Verify acknowledging resolved incident returns False."""
        inc = commander.create_incident(title="T", description="D", source="s", severity=IncidentSeverity.LOW)
        assert inc is not None
        commander.resolve_incident(inc.incident_id)
        assert commander.acknowledge_incident(inc.incident_id) is False

    def test_resolve_incident(self, commander: IncidentCommander):
        """Verify resolving an incident."""
        inc = commander.create_incident(title="Test", description="D", source="s", severity=IncidentSeverity.HIGH)
        assert inc is not None
        result = commander.resolve_incident(inc.incident_id, "Fixed the issue")
        assert result is True
        updated = commander.get_incident(inc.incident_id)
        assert updated is not None
        assert updated["status"] == "RESOLVED"
        assert updated["resolved_at"] is not None
        assert "Fixed the issue" in updated["resolution_notes"]

    def test_resolve_nonexistent(self, commander: IncidentCommander):
        """Verify resolving non-existent incident returns False."""
        assert commander.resolve_incident("INC-9999") is False

    def test_close_incident(self, commander: IncidentCommander):
        """Verify closing a resolved incident."""
        inc = commander.create_incident(title="T", description="D", source="s", severity=IncidentSeverity.LOW)
        assert inc is not None
        commander.resolve_incident(inc.incident_id)
        result = commander.close_incident(inc.incident_id, "All good")
        assert result is True
        updated = commander.get_incident(inc.incident_id)
        assert updated is not None
        assert updated["status"] == "CLOSED"

    def test_close_unresolved(self, commander: IncidentCommander):
        """Verify closing unresolved incident returns False."""
        inc = commander.create_incident(title="T", description="D", source="s", severity=IncidentSeverity.LOW)
        assert inc is not None
        assert commander.close_incident(inc.incident_id) is False


class TestQueryMethods:
    def test_get_open_incidents(self, commander: IncidentCommander):
        """Verify get_open_incidents returns only open ones."""
        i1 = commander.create_incident(title="Issue 1", description="A", source="m1", severity=IncidentSeverity.HIGH)
        i2 = commander.create_incident(title="Issue 2", description="B", source="m2", severity=IncidentSeverity.LOW)
        assert i1 is not None and i2 is not None
        commander.resolve_incident(i1.incident_id)
        open_incs = commander.get_open_incidents()
        assert len(open_incs) == 1
        assert open_incs[0]["incident_id"] == i2.incident_id

    def test_get_all_incidents_order(self, commander: IncidentCommander):
        """Verify get_all_incidents returns most recent first."""
        i1 = commander.create_incident(title="First", description="A", source="m1", severity=IncidentSeverity.LOW)
        i2 = commander.create_incident(title="Second", description="B", source="m2", severity=IncidentSeverity.LOW)
        assert i1 is not None and i2 is not None
        all_incs = commander.get_all_incidents()
        assert len(all_incs) == 2
        assert all_incs[0]["incident_id"] == i2.incident_id  # Most recent first

    def test_get_stats_counts(self, commander: IncidentCommander):
        """Verify get_stats returns correct counts."""
        i1 = commander.create_incident(title="Critical", description="C", source="m1", severity=IncidentSeverity.CRITICAL)
        i2 = commander.create_incident(title="High", description="H", source="m2", severity=IncidentSeverity.HIGH)
        i3 = commander.create_incident(title="Low", description="L", source="m3", severity=IncidentSeverity.LOW)
        assert all(x is not None for x in [i1, i2, i3])
        commander.resolve_incident(i3.incident_id)
        stats = commander.get_stats()
        assert stats["total_incidents"] == 3
        assert stats["open_incidents"] == 2
        assert stats["critical_open"] == 1
        assert stats["high_open"] == 1
        assert stats["resolved"] == 1


class TestPersistence:
    def test_save_and_load_incidents(self, commander: IncidentCommander, tmp_path: Path):
        """Verify incidents persist across instances."""
        commander.create_incident(title="Saved", description="Test", source="mod", severity=IncidentSeverity.CRITICAL)
        assert os.path.exists(commander._cfg.incidents_file)

        # Load into new instance
        c2 = IncidentCommander({
            "incidents_file": commander._cfg.incidents_file,
            "notify_on_critical": False,
        })
        assert c2.get_stats()["total_incidents"] == 1
        assert c2.get_stats()["critical_open"] == 1


class TestDetectionCycle:
    def test_detection_cycle_runs(self, commander: IncidentCommander):
        """Verify detection cycle runs without error."""
        result = commander.run_detection_cycle()
        assert "created" in result
        assert "resolved" in result
        assert "open_after" in result


class TestSingleton:
    def test_get_incident_commander(self):
        """Verify singleton pattern."""
        c1 = get_incident_commander()
        c2 = get_incident_commander()
        assert c1 is c2

    def test_reset_incident_commander(self):
        """Verify reset creates new instance."""
        c1 = get_incident_commander()
        reset_incident_commander()
        c2 = get_incident_commander()
        assert c1 is not c2
