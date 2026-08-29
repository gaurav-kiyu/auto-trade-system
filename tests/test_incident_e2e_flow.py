"""End-to-end integration test: complete incident lifecycle flow.

Validates the entire chain from incident creation through Telegram alert
delivery, verifying that all components work together correctly:

    IncidentCommander.create_incident()
      → _send_alert()
        → ICSTelegramBridge._alert_callback()
          → _TelegramClient.send_raw()
            → Telegram API (mocked)

Run with: pytest tests/test_incident_e2e_flow.py -v --tb=short

Design:
- Uses dependency injection (set_alert_fn) to avoid real Telegram API calls
- Mocks the Telegram _TelegramClient.send_raw() method
- Verifies message formatting, severity routing, and lifecycle integration
- Tests both critical and non-critical alert paths
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.ics_telegram_bridge import (
    ICSTelegramBridge,
    get_ics_telegram_bridge,
    reset_ics_telegram_bridge,
    wire_ics_telegram_alerts,
)
from core.incident_command_system import (
    IncidentCommander,
    IncidentSeverity,
    reset_incident_commander,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def cleanup_all():
    """Reset all singletons before and after each test."""
    reset_incident_commander()
    reset_ics_telegram_bridge()
    yield
    reset_incident_commander()
    reset_ics_telegram_bridge()


@pytest.fixture
def mock_telegram_client():
    """Mock _TelegramClient.send_raw to capture sent messages.

    Returns a MagicMock that records all calls to send_raw().
    """
    with patch(
        "infrastructure.adapters.notifications.telegram_adapter._TelegramClient.send_raw"
    ) as mock_send:
        mock_send.return_value = True
        yield mock_send


@pytest.fixture
def bridge(mock_telegram_client) -> ICSTelegramBridge:
    """Create a wired ICS-Telegram bridge with mocked Telegram client."""
    bridge = ICSTelegramBridge(
        bot_token="test:bot_token",
        chat_id="-100test_chat",
        enabled=True,
    )
    return bridge


@pytest.fixture
def commander(bridge) -> IncidentCommander:
    """Create an IncidentCommander wired to the Telegram bridge.

    The bridge's alert callback is set on the commander.
    Returns the commander with the bridge already wired.
    """
    commander = IncidentCommander({"incidents_file": ":memory:"})
    bridge.wire(commander)
    return commander


# ═══════════════════════════════════════════════════════════════════════════════
# 1. BASIC INCIDENT → TELEGRAM FLOW
# ═══════════════════════════════════════════════════════════════════════════════


class TestIncidentToTelegramBasic:
    """Verify the basic incident creation fires a Telegram alert."""

    def test_critical_incident_sends_telegram(
        self, commander: IncidentCommander, mock_telegram_client: MagicMock
    ):
        """Verify CRITICAL severity incident fires Telegram alert."""
        incident = commander.create_incident(
            title="Database connection lost",
            description="PostgreSQL connection pool exhausted after 5000 queries",
            source="health_check",
            severity=IncidentSeverity.CRITICAL,
            detected_by="e2e_test",
        )

        assert incident is not None
        assert mock_telegram_client.called, "send_raw() should be called"

        # Check the message content
        call_args = mock_telegram_client.call_args
        kwargs = call_args[1]
        text = kwargs.get("text", call_args[0][0] if call_args[0] else "")
        assert "🚨 CRITICAL" in text
        assert "Database connection lost" in text
        assert incident.incident_id in text

    def test_high_incident_sends_telegram(
        self, commander: IncidentCommander, mock_telegram_client: MagicMock
    ):
        """Verify HIGH severity incident fires Telegram alert."""
        incident = commander.create_incident(
            title="High memory usage",
            description="Memory usage exceeded 85% threshold",
            source="health_check",
            severity=IncidentSeverity.HIGH,
            detected_by="e2e_test",
        )

        assert incident is not None
        assert mock_telegram_client.called, "send_raw() should be called"
        call_args = mock_telegram_client.call_args
        kwargs = call_args[1]
        text = kwargs.get("text", call_args[0][0] if call_args[0] else "")
        assert "CRITICAL" in text or "NOTIFICATION" in text
        assert "High memory usage" in text

    def test_medium_incident_does_not_send_telegram(
        self, commander: IncidentCommander, mock_telegram_client: MagicMock
    ):
        """Verify MEDIUM severity does NOT fire Telegram alert."""
        incident = commander.create_incident(
            title="Minor warning",
            description="Non-critical warning message",
            source="health_check",
            severity=IncidentSeverity.MEDIUM,
            detected_by="e2e_test",
        )

        assert incident is not None
        assert not mock_telegram_client.called, "send_raw() should NOT be called for MEDIUM"

    def test_low_incident_does_not_send_telegram(
        self, commander: IncidentCommander, mock_telegram_client: MagicMock
    ):
        """Verify LOW severity does NOT fire Telegram alert."""
        incident = commander.create_incident(
            title="Info",
            description="Informational message",
            source="health_check",
            severity=IncidentSeverity.LOW,
            detected_by="e2e_test",
        )

        assert incident is not None
        assert not mock_telegram_client.called, "send_raw() should NOT be called for LOW"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. INCIDENT LIFECYCLE → TELEGRAM NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════════


class TestLifecycleNotifications:
    """Verify lifecycle transitions fire appropriate Telegram alerts."""

    def test_resolve_sends_telegram_notification(
        self, commander: IncidentCommander, mock_telegram_client: MagicMock
    ):
        """Verify resolving an open incident sends a notification."""
        mock_telegram_client.reset_mock()

        incident = commander.create_incident(
            title="Timeout error",
            description="Request timeout > 30s",
            source="api_gateway",
            severity=IncidentSeverity.HIGH,
        )

        mock_telegram_client.reset_mock()

        # Resolve the incident
        success = commander.resolve_incident(
            incident.incident_id,
            resolution_notes="Increased timeout to 60s",
        )

        assert success is True
        assert mock_telegram_client.called, "resolve should send notification"
        call_args = mock_telegram_client.call_args
        kwargs = call_args[1]
        text = kwargs.get("text", call_args[0][0] if call_args[0] else "")
        assert "RESOLVED" in text or "NOTIFICATION" in text
        assert incident.incident_id in text

    def test_close_after_resolve_no_alert(
        self, commander: IncidentCommander, mock_telegram_client: MagicMock
    ):
        """Verify closing a resolved incident does NOT send an alert."""
        # Create and resolve
        incident = commander.create_incident(
            title="Disk usage",
            description="Disk at 90%",
            source="monitoring",
            severity=IncidentSeverity.HIGH,
        )
        mock_telegram_client.reset_mock()

        commander.resolve_incident(incident.incident_id, "Cleaned up logs")
        mock_telegram_client.reset_mock()

        # Close - should NOT trigger alert
        commander.close_incident(incident.incident_id)
        assert not mock_telegram_client.called, "close should not send alert"

    def test_acknowledge_no_alert(
        self, commander: IncidentCommander, mock_telegram_client: MagicMock
    ):
        """Verify acknowledging an incident does NOT send an additional alert."""
        incident = commander.create_incident(
            title="API error rate",
            description="Error rate > 5%",
            source="monitoring",
            severity=IncidentSeverity.HIGH,
        )
        mock_telegram_client.reset_mock()

        commander.acknowledge_incident(incident.incident_id, "Investigating")
        assert not mock_telegram_client.called, "acknowledge should not send alert"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TELEGRAM BRIDGE INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestBridgeIntegration:
    """Verify the bridge correctly formats and routes alerts."""

    def test_critical_alert_sets_critical_flag(
        self, mock_telegram_client: MagicMock
    ):
        """Verify critical alerts pass critical=True to send_raw."""
        bridge = ICSTelegramBridge(bot_token="x", chat_id="-100y")
        commander = IncidentCommander({"incidents_file": ":memory:"})
        bridge.wire(commander)

        commander.create_incident(
            title="CRITICAL failure",
            description="System down",
            source="test",
            severity=IncidentSeverity.CRITICAL,
        )

        assert mock_telegram_client.called
        call_kwargs = mock_telegram_client.call_args[1]
        assert call_kwargs.get("critical") is True, "Critical should pass critical=True"

    def test_resolve_alert_sets_critical_false(
        self, mock_telegram_client: MagicMock
    ):
        """Verify resolve notifications pass critical=False."""
        bridge = ICSTelegramBridge(bot_token="x", chat_id="-100y")
        commander = IncidentCommander({"incidents_file": ":memory:"})
        bridge.wire(commander)

        incident = commander.create_incident(
            title="Issue resolved",
            description="Test issue",
            source="test",
            severity=IncidentSeverity.HIGH,
        )
        mock_telegram_client.reset_mock()

        commander.resolve_incident(incident.incident_id, "Fixed")
        assert mock_telegram_client.called
        call_kwargs = mock_telegram_client.call_args[1]
        assert call_kwargs.get("critical") is False, "Resolve should pass critical=False"

    def test_bridge_unwire_stops_alerts(
        self, commander: IncidentCommander, mock_telegram_client: MagicMock
    ):
        """Verify unwiring stops Telegram alerts."""
        # Create a second bridge for unwire testing
        test_bridge = ICSTelegramBridge(bot_token="x", chat_id="-100y")
        test_bridge.wire(commander)

        # Unwire
        test_bridge.unwire(commander)
        mock_telegram_client.reset_mock()

        # Create incident - should NOT fire Telegram
        incident = commander.create_incident(
            title="After unwire",
            description="Should not alert",
            source="test",
            severity=IncidentSeverity.CRITICAL,
        )

        assert incident is not None
        assert not mock_telegram_client.called, "No alert after unwire"

    def test_disabled_bridge_no_alerts(
        self, mock_telegram_client: MagicMock
    ):
        """Verify disabled bridge does not send alerts."""
        bridge = ICSTelegramBridge(
            bot_token="x", chat_id="-100y", enabled=False
        )
        commander = IncidentCommander({"incidents_file": ":memory:"})
        bridge.wire(commander)

        commander.create_incident(
            title="Should not send",
            description="Bridge disabled",
            source="test",
            severity=IncidentSeverity.CRITICAL,
        )

        assert not mock_telegram_client.called, "Disabled bridge should not send"

    def test_invalid_chat_id_does_not_crash(
        self, mock_telegram_client: MagicMock
    ):
        """Verify invalid chat_id does not crash the system."""
        # Make send_raw return False to simulate failed delivery
        mock_telegram_client.return_value = False

        bridge = ICSTelegramBridge(
            bot_token="invalid:token",
            chat_id="-100invalid",
            enabled=True,
        )
        commander = IncidentCommander({"incidents_file": ":memory:"})
        bridge.wire(commander)

        # Should not raise despite invalid chat_id
        incident = commander.create_incident(
            title="Delivery test",
            description="Should fail gracefully",
            source="test",
            severity=IncidentSeverity.HIGH,
        )
        assert incident is not None
        # Incident is still created even if alert delivery fails
        assert len(commander.get_all_incidents()) > 0

    def test_network_error_does_not_crash(
        self, mock_telegram_client: MagicMock
    ):
        """Verify a network error during send_raw does not crash the system."""
        # Simulate a network error (bot token revoked, API unreachable)
        mock_telegram_client.side_effect = ConnectionError("API unreachable")

        bridge = ICSTelegramBridge(
            bot_token="revoked:token",
            chat_id="-100dead",
            enabled=True,
        )
        commander = IncidentCommander({"incidents_file": ":memory:"})
        bridge.wire(commander)

        # Should NOT raise despite the ConnectionError
        incident = commander.create_incident(
            title="Network error test",
            description="Should not crash",
            source="test",
            severity=IncidentSeverity.CRITICAL,
        )
        assert incident is not None
        assert len(commander.get_all_incidents()) > 0

    def test_empty_credentials_graceful_degradation(
        self, mock_telegram_client: MagicMock
    ):
        """Verify empty bot token and CRITICAL incident still works (graceful degradation).

        The bridge's _ensure_client() either returns False (requests not installed)
        or creates _TelegramClient with empty token. Both paths are handled via
        try/except — the system should not crash.
        """
        bridge = ICSTelegramBridge(
            bot_token="",
            chat_id="",
            enabled=True,
        )
        commander = IncidentCommander({"incidents_file": ":memory:"})
        bridge.wire(commander)

        # CRITICAL severity triggers _send_alert → bridge._alert_callback
        # Even with empty credentials, the system should not crash
        incident = commander.create_incident(
            title="No Telegram config",
            description="Should work without Telegram",
            source="test",
            severity=IncidentSeverity.CRITICAL,
        )
        assert incident is not None
        assert len(commander.get_all_incidents()) == 1
        # Incident created successfully even without Telegram credentials


# ═══════════════════════════════════════════════════════════════════════════════
# 4. FORMATTING AND CONTENT VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestMessageFormatting:
    """Verify the alert message format and content."""

    def test_message_contains_incident_id(
        self, commander: IncidentCommander, mock_telegram_client: MagicMock
    ):
        """Verify the Telegram message includes the incident ID."""
        incident = commander.create_incident(
            title="Format test",
            description="Checking message format",
            source="test",
            severity=IncidentSeverity.CRITICAL,
        )

        call_args = mock_telegram_client.call_args
        kwargs = call_args[1]
        text = kwargs.get("text", call_args[0][0] if call_args[0] else "")
        assert incident.incident_id in text

    def test_message_contains_description(
        self, commander: IncidentCommander, mock_telegram_client: MagicMock
    ):
        """Verify the Telegram message includes the incident description."""
        commander.create_incident(
            title="Description test",
            description="This is a detailed description of the incident",
            source="test",
            severity=IncidentSeverity.HIGH,
        )

        call_args = mock_telegram_client.call_args
        kwargs = call_args[1]
        text = kwargs.get("text", call_args[0][0] if call_args[0] else "")
        assert "This is a detailed description of the incident" in text

    def test_critical_message_prefix(
        self, commander: IncidentCommander, mock_telegram_client: MagicMock
    ):
        """Verify critical alerts have the emergency prefix."""
        commander.create_incident(
            title="Emergency",
            description="Critical system failure",
            source="test",
            severity=IncidentSeverity.CRITICAL,
        )

        call_args = mock_telegram_client.call_args
        kwargs = call_args[1]
        text = kwargs.get("text", call_args[0][0] if call_args[0] else "")
        assert text.startswith("🚨 CRITICAL"), "Critical alert must start with 🚨 CRITICAL"

    def test_non_critical_message_prefix(
        self, mock_telegram_client: MagicMock
    ):
        """Verify non-critical alerts have the info prefix."""
        bridge = ICSTelegramBridge(bot_token="x", chat_id="-100y")
        commander = IncidentCommander({"incidents_file": ":memory:"})
        bridge.wire(commander)

        incident = commander.create_incident(
            title="Info test",
            description="Info message",
            source="test",
            severity=IncidentSeverity.HIGH,
        )

        # Reset mock to isolate the resolve notification from the create alert
        mock_telegram_client.reset_mock()

        # Resolve to trigger resolve notification
        commander.resolve_incident(incident.incident_id, "Resolved")
        call_args = mock_telegram_client.call_args
        kwargs = call_args[1]
        text = kwargs.get("text", call_args[0][0] if call_args[0] else "")
        assert text.startswith("ℹ️"), "Non-critical alert must start with ℹ️"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. SINGLETON WIRING
# ═══════════════════════════════════════════════════════════════════════════════


class TestSingletonWiring:
    """Verify the singleton auto-wiring works."""

    def test_get_bridge_auto_wires(self, mock_telegram_client: MagicMock):
        """Verify get_ics_telegram_bridge auto-wires into IncidentCommander."""
        reset_incident_commander()
        reset_ics_telegram_bridge()

        # This should auto-wire when env vars are present
        bridge = get_ics_telegram_bridge(
            bot_token="auto:token",
            chat_id="-100auto",
        )

        assert bridge.is_wired is True

    def test_wire_function_active(self, mock_telegram_client: MagicMock):
        """Verify wire_ics_telegram_alerts returns True with credentials."""
        reset_incident_commander()
        reset_ics_telegram_bridge()

        result = wire_ics_telegram_alerts(
            bot_token="test:active",
            chat_id="-100active",
        )
        assert result is True


# ═══════════════════════════════════════════════════════════════════════════════
# 6. EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Verify edge cases in the incident-to-Telegram flow."""

    def test_duplicate_incident_no_extra_alert(
        self, commander: IncidentCommander, mock_telegram_client: MagicMock
    ):
        """Verify duplicate incidents don't send extra alerts."""
        # Create first incident
        commander.create_incident(
            title="Dup test",
            description="First occurrence",
            source="test",
            severity=IncidentSeverity.CRITICAL,
        )

        first_call_count = mock_telegram_client.call_count

        # Create duplicate (same source + title)
        duplicate = commander.create_incident(
            title="Dup test",
            description="Second occurrence (should be deduped)",
            source="test",
            severity=IncidentSeverity.CRITICAL,
        )

        assert duplicate is None, "Duplicate should return None"
        # Alert count should NOT increase
        assert mock_telegram_client.call_count == first_call_count

    def test_rapid_successive_incidents_all_alert(
        self, commander: IncidentCommander, mock_telegram_client: MagicMock
    ):
        """Verify rapid successive incidents each send alerts."""
        for i in range(5):
            commander.create_incident(
                title=f"Rapid incident #{i}",
                description=f"Incident number {i}",
                source=f"source_{i}",
                severity=IncidentSeverity.CRITICAL,
            )

        # Each should send an alert (5 total)
        assert mock_telegram_client.call_count == 5

    def test_create_after_resolve_sends_new_alert(
        self, commander: IncidentCommander, mock_telegram_client: MagicMock
    ):
        """Verify resolved incident can be re-created and sends new alert."""
        first = commander.create_incident(
            title="Recurring issue",
            description="First occurrence",
            source="recurring",
            severity=IncidentSeverity.HIGH,
        )

        mock_telegram_client.reset_mock()

        # Resolve it
        commander.resolve_incident(first.incident_id, "Fixed")
        mock_telegram_client.reset_mock()

        # Create again (same source+title = new incident since old one is resolved)
        second = commander.create_incident(
            title="Recurring issue",
            description="Second occurrence",
            source="recurring",
            severity=IncidentSeverity.CRITICAL,
        )

        assert second is not None, "Should create new incident after resolve"
        assert mock_telegram_client.called, "New incident should send alert"
