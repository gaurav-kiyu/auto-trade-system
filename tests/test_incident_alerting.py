"""
Tests for core/incident_alerting.py - Incident Alerting System.

Covers:
- IncidentType and IncidentSeverity enums
- Incident dataclass
- IncidentAlerting (start/stop, report_incident, cooldown, queue, processing, formatting)
- Convenience methods (alert_broker_disconnect, alert_risk_breach, alert_hard_halt, etc.)
- Singleton get_incident_alerting and quick-access functions
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from core.incident_alerting import (
    Incident,
    IncidentAlerting,
    IncidentSeverity,
    IncidentType,
    alert_broker_disconnect,
    alert_risk_breach,
    get_incident_alerting,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def alerting():
    """IncidentAlerting instance with disabled thread (manual processing)."""
    a = IncidentAlerting(
        config={
            "INCIDENT_ALERTING_ENABLED": True,
            "INCIDENT_COOLDOWN_SECONDS": 0,  # No cooldown for tests
        }
    )
    return a


@pytest.fixture
def alerting_with_callback():
    """IncidentAlerting with mock callback."""
    callback = MagicMock()
    a = IncidentAlerting(
        send_alert_fn=callback,
        config={
            "INCIDENT_ALERTING_ENABLED": True,
            "INCIDENT_COOLDOWN_SECONDS": 0,
        }
    )
    return a, callback


# ── Enum Tests ────────────────────────────────────────────────────────────────


class TestIncidentType:
    """IncidentType enum - 12 incident types."""

    def test_values(self):
        assert IncidentType.BROKER_DISCONNECT.value == "broker_disconnect"
        assert IncidentType.RECONCILIATION_MISMATCH.value == "reconciliation_mismatch"
        assert IncidentType.STALE_QUOTE.value == "stale_quote"
        assert IncidentType.RETRY_STORM.value == "retry_storm"
        assert IncidentType.RISK_BREACH.value == "risk_breach"
        assert IncidentType.CIRCUIT_BREAKER.value == "circuit_breaker"
        assert IncidentType.ORPHAN_ORDER.value == "orphan_order"
        assert IncidentType.DB_FAILURE.value == "db_failure"
        assert IncidentType.HARD_HALT.value == "hard_halt"
        assert IncidentType.SYSTEM_MODE_CHANGE.value == "system_mode_change"
        assert IncidentType.UNKNOWN_STATE.value == "unknown_state"
        assert IncidentType.ORDER_MODIFICATION_FAILED.value == "order_modification_failed"


class TestIncidentSeverity:
    """IncidentSeverity enum - 4 severity levels."""

    def test_ordering(self):
        assert IncidentSeverity.CRITICAL.value < IncidentSeverity.HIGH.value
        assert IncidentSeverity.HIGH.value < IncidentSeverity.NORMAL.value
        assert IncidentSeverity.NORMAL.value < IncidentSeverity.LOW.value


# ── IncidentAlerting Tests ────────────────────────────────────────────────────


class TestIncidentAlertingBasics:
    """Basic incident reporting."""

    def test_report_incident(self, alerting):
        alerting.report_incident(
            IncidentType.BROKER_DISCONNECT,
            IncidentSeverity.CRITICAL,
            "Broker lost",
        )
        assert alerting.get_queue_size() == 1

    def test_report_incident_with_details(self, alerting):
        alerting.report_incident(
            IncidentType.RISK_BREACH,
            IncidentSeverity.CRITICAL,
            "Loss limit hit",
            details={"current": -500, "limit": -600},
        )
        assert alerting.get_queue_size() == 1

    def test_report_disabled(self):
        a = IncidentAlerting(config={"INCIDENT_ALERTING_ENABLED": False})
        a.report_incident(IncidentType.BROKER_DISCONNECT, IncidentSeverity.CRITICAL, "x")
        assert a.get_queue_size() == 0

    def test_queue_size_limit(self, alerting):
        alerting._max_queue_size = 2
        alerting.report_incident(IncidentType.BROKER_DISCONNECT, IncidentSeverity.CRITICAL, "a")
        alerting.report_incident(IncidentType.RISK_BREACH, IncidentSeverity.CRITICAL, "b")
        alerting.report_incident(IncidentType.HARD_HALT, IncidentSeverity.CRITICAL, "c")
        assert alerting.get_queue_size() == 2


class TestIncidentAlertingCooldown:
    """Cooldown prevents duplicate alert storms."""

    def test_cooldown_skips_duplicate(self):
        a = IncidentAlerting(config={
            "INCIDENT_ALERTING_ENABLED": True,
            "INCIDENT_COOLDOWN_SECONDS": 60,
        })
        a.report_incident(IncidentType.BROKER_DISCONNECT, IncidentSeverity.CRITICAL, "first")
        a.report_incident(IncidentType.BROKER_DISCONNECT, IncidentSeverity.CRITICAL, "second")
        assert a.get_queue_size() == 1

    def test_different_types_not_cooldowned(self, alerting):
        alerting.report_incident(IncidentType.BROKER_DISCONNECT, IncidentSeverity.CRITICAL, "a")
        alerting.report_incident(IncidentType.RISK_BREACH, IncidentSeverity.CRITICAL, "b")
        assert alerting.get_queue_size() == 2

    def test_no_cooldown_when_configured_zero(self, alerting):
        alerting.report_incident(IncidentType.BROKER_DISCONNECT, IncidentSeverity.CRITICAL, "a")
        alerting.report_incident(IncidentType.BROKER_DISCONNECT, IncidentSeverity.CRITICAL, "b")
        assert alerting.get_queue_size() == 2


class TestIncidentAlertingQueue:
    """Priority queue behavior."""

    def test_priority_ordering(self, alerting):
        alerting.report_incident(IncidentType.STALE_QUOTE, IncidentSeverity.LOW, "low")
        alerting.report_incident(IncidentType.BROKER_DISCONNECT, IncidentSeverity.CRITICAL, "critical")
        alerting.report_incident(IncidentType.RECONCILIATION_MISMATCH, IncidentSeverity.HIGH, "high")

        # Process manually
        alerting._process_incidents()

        # All should be popped
        assert alerting.get_queue_size() == 0

    def test_clear_queue(self, alerting):
        alerting.report_incident(IncidentType.BROKER_DISCONNECT, IncidentSeverity.CRITICAL, "x")
        alerting.clear_queue()
        assert alerting.get_queue_size() == 0


class TestIncidentAlertingProcess:
    """Event processing and callback invocation."""

    def test_process_sends_alert(self, alerting_with_callback):
        a, callback = alerting_with_callback
        a.report_incident(IncidentType.BROKER_DISCONNECT, IncidentSeverity.CRITICAL, "Broker lost")
        a._process_incidents()
        callback.assert_called_once()

    def test_process_critical_alert(self, alerting_with_callback):
        a, callback = alerting_with_callback
        a.report_incident(IncidentType.HARD_HALT, IncidentSeverity.CRITICAL, "HALT")
        a._process_incidents()
        args, _ = callback.call_args
        msg = args[0] if args else ""
        assert "HARD_HALT" in msg

    def test_process_normal_alert_suppressed(self, alerting_with_callback):
        """NORMAL incidents are suppressed below HIGH delivery threshold."""
        a, callback = alerting_with_callback
        a.report_incident(IncidentType.STALE_QUOTE, IncidentSeverity.NORMAL, "stale")
        a._process_incidents()
        # NORMAL (2) is below delivery threshold HIGH (1) -> suppressed
        assert callback.call_count == 0, "NORMAL incidents should be suppressed"
        # Queue should now be empty
        assert a.get_queue_size() == 0

    def test_callback_error_does_not_crash(self, alerting_with_callback):
        a, callback = alerting_with_callback
        callback.side_effect = RuntimeError("callback fail")
        a.report_incident(IncidentType.BROKER_DISCONNECT, IncidentSeverity.CRITICAL, "x")
        # Should not raise
        a._process_incidents()


class TestIncidentAlertingFormat:
    """Alert message formatting."""

    def test_format_critical(self, alerting):
        incident = Incident(
            severity=0, timestamp=time.time(),
            incident_type="broker_disconnect", message="Broker lost",
        )
        msg = alerting._format_alert(incident)
        assert "BROKER_DISCONNECT" in msg
        assert "Broker lost" in msg

    def test_format_with_details(self, alerting):
        incident = Incident(
            severity=0, timestamp=time.time(),
            incident_type="risk_breach", message="Loss limit",
            details={"current": -500, "limit": -600},
        )
        msg = alerting._format_alert(incident)
        assert "RISK_BREACH" in msg
        assert "current=-500" in msg or "current" in msg


class TestIncidentAlertingStartStop:
    """Thread lifecycle management."""

    def test_start_stop(self, alerting):
        alerting.start()
        assert alerting._running is True
        alerting.stop()
        assert alerting._running is False

    def test_start_disabled_does_nothing(self):
        a = IncidentAlerting(config={"INCIDENT_ALERTING_ENABLED": False})
        a.start()
        assert a._running is False

    def test_start_twice_no_error(self, alerting):
        alerting.start()
        alerting.start()  # Should not raise
        alerting.stop()

    def test_stop_without_start(self, alerting):
        alerting.stop()  # Should not raise


class TestConvenienceMethods:
    """Convenience alert methods."""

    def test_alert_broker_disconnect(self, alerting):
        alerting.alert_broker_disconnect({"broker": "Zerodha"})
        assert alerting.get_queue_size() == 1

    def test_alert_reconciliation_mismatch(self, alerting):
        alerting.alert_reconciliation_mismatch({"diff": 3})
        assert alerting.get_queue_size() == 1

    def test_alert_stale_quote(self, alerting):
        alerting.alert_stale_quote("NIFTY", 120.0)
        assert alerting.get_queue_size() == 1

    def test_alert_risk_breach(self, alerting):
        alerting.alert_risk_breach("max_daily_loss", {"value": -500})
        assert alerting.get_queue_size() == 1

    def test_alert_hard_halt(self, alerting):
        alerting.alert_hard_halt("Manual stop triggered")
        assert alerting.get_queue_size() == 1

    def test_alert_orphan_order(self, alerting):
        alerting.alert_orphan_order("OPB-123")
        assert alerting.get_queue_size() == 1

    def test_alert_system_mode_change(self, alerting):
        alerting.alert_system_mode_change("PAPER", "LIVE", "upgrade")
        assert alerting.get_queue_size() == 1

    def test_alert_order_modification_failed(self, alerting):
        alerting.alert_order_modification_failed(
            order_id="OPB-456",
            reason="Broker rejected modification",
            details={"qty": 75, "price": 150.0},
        )
        assert alerting.get_queue_size() == 1

    def test_alert_order_modification_failed_without_details(self, alerting):
        alerting.alert_order_modification_failed(
            order_id="OPB-789",
            reason="Timeout",
        )
        assert alerting.get_queue_size() == 1

    def test_alert_order_modification_failed_formatting(self, alerting_with_callback):
        a, callback = alerting_with_callback
        a.alert_order_modification_failed(
            order_id="OPB-999",
            reason="Network error",
            details={"latency_ms": 5000},
        )
        a._process_incidents()
        args, _ = callback.call_args
        msg = args[0] if args else ""
        assert "ORDER_MODIFICATION_FAILED" in msg
        assert "OPB-999" in msg
        assert "Network error" in msg


# ── Singleton Tests ───────────────────────────────────────────────────────────


class TestSingleton:
    """Module-level singleton get_incident_alerting."""

    def test_returns_alerting(self):
        a = get_incident_alerting()
        assert isinstance(a, IncidentAlerting)

    def test_singleton_identity(self):
        a1 = get_incident_alerting()
        a2 = get_incident_alerting()
        assert a1 is a2

    def test_quick_access_functions_no_crash(self):
        """Quick-access functions should not crash if singleton not initialized."""
        alert_broker_disconnect({"test": True})
        alert_risk_breach("test_breach")
