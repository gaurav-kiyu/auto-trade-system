"""Tests for core/ics_telegram_bridge.py — ICS-Telegram Alert Bridge.

Tests the bridge's ability to wire Incident Commander alerts to Telegram
notifications, including credential management, singleton pattern,
and callback invocation.

Run with: pytest tests/test_ics_telegram_bridge.py -v
"""

from __future__ import annotations

import pytest
from core.ics_telegram_bridge import (
    ICSTelegramBridge,
    get_ics_telegram_bridge,
    reset_ics_telegram_bridge,
    wire_ics_telegram_alerts,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_telegram_env(monkeypatch):
    monkeypatch.delenv("OPBUYING_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("OPBUYING_TELEGRAM_CHAT_ID", raising=False)


@pytest.fixture(autouse=True)
def cleanup_bridge():
    """Reset the telegram bridge singleton before and after each test."""
    reset_ics_telegram_bridge()
    yield
    reset_ics_telegram_bridge()


@pytest.fixture
def mock_commander():
    """Create a simple mock IncidentCommander-like object."""

    class MockCommander:
        def __init__(self):
            self.alert_fn = None
            self.alerts_received: list[tuple[str, bool]] = []

        def set_alert_fn(self, fn):
            self.alert_fn = fn

        def trigger_alert(self, message: str, is_critical: bool):
            if self.alert_fn:
                self.alert_fn(message, is_critical)
            self.alerts_received.append((message, is_critical))

    return MockCommander()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. BASIC CONSTRUCTION TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestBridgeConstruction:
    """Verify bridge construction and properties."""

    def test_create_with_valid_credentials(self):
        """Verify bridge creates with valid bot token and chat ID."""
        bridge = ICSTelegramBridge(bot_token="test:token", chat_id="-10012345")
        assert bridge.is_enabled is True
        assert bridge.is_wired is False
        assert bridge._bot_token == "test:token"
        assert bridge._chat_id == "-10012345"

    def test_create_with_empty_credentials(self):
        """Verify bridge creates gracefully with empty credentials."""
        bridge = ICSTelegramBridge(bot_token="", chat_id="")
        assert bridge.is_enabled is True
        assert bridge.is_wired is False

    def test_create_disabled(self):
        """Verify bridge can be explicitly disabled."""
        bridge = ICSTelegramBridge(bot_token="token", chat_id="id", enabled=False)
        assert bridge.is_enabled is False

    def test_create_with_empty_token_only(self):
        """Verify bridge works with empty token but valid chat_id."""
        bridge = ICSTelegramBridge(bot_token="", chat_id="-10012345")
        assert bridge.is_enabled is True


class TestBridgeUsesPublicTelegramAdapter:
    """Regression: the bridge used to reach into the *private*
    infrastructure.adapters.notifications.telegram_adapter._TelegramClient
    directly - a core-to-infra architecture violation flagged by
    core.architecture_analyzer. It now constructs the public
    TelegramNotificationAdapter and calls its public send_raw() passthrough."""

    def test_ensure_client_constructs_public_adapter_class(self):
        pytest.importorskip("requests")
        from infrastructure.adapters.notifications.telegram_adapter import (
            TelegramNotificationAdapter,
        )

        bridge = ICSTelegramBridge(bot_token="test:token", chat_id="-10012345")
        ok = bridge._ensure_client()
        assert ok is True
        assert isinstance(bridge._client, TelegramNotificationAdapter)

    def test_alert_callback_reaches_send_raw_on_public_adapter(self, mock_commander, monkeypatch):
        pytest.importorskip("requests")
        bridge = ICSTelegramBridge(bot_token="test:token", chat_id="-10012345")
        bridge.wire(mock_commander)

        calls = []
        bridge._ensure_client()
        monkeypatch.setattr(
            bridge._client, "send_raw",
            lambda text, chat_id=None, critical=False: calls.append((text, chat_id, critical)) or True,
        )
        mock_commander.trigger_alert("Broker connection lost", True)
        assert len(calls) == 1
        assert "Broker connection lost" in calls[0][0]
        assert calls[0][2] is True


class TestBridgeProperties:
    """Verify property accessors."""

    def test_is_wired_default_false(self):
        """Verify is_wired returns False before wiring."""
        bridge = ICSTelegramBridge(bot_token="x", chat_id="y")
        assert bridge.is_wired is False

    def test_is_enabled_default_true(self):
        """Verify is_enabled returns True by default."""
        bridge = ICSTelegramBridge(bot_token="x", chat_id="y")
        assert bridge.is_enabled is True

    def test_is_enabled_explicit_false(self):
        """Verify is_enabled can be set to False."""
        bridge = ICSTelegramBridge(bot_token="x", chat_id="y", enabled=False)
        assert bridge.is_enabled is False


# ═══════════════════════════════════════════════════════════════════════════════
# 2. WIRING TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestBridgeWiring:
    """Verify bridge wiring to IncidentCommander."""

    def test_wire_sets_alert_fn(self, mock_commander):
        """Verify wire() sets the alert callback on the commander."""
        bridge = ICSTelegramBridge(bot_token="test:tok", chat_id="-100abc")
        result = bridge.wire(mock_commander)
        assert result is True
        assert bridge.is_wired is True
        assert mock_commander.alert_fn is not None

    def test_wire_twice_is_idempotent(self, mock_commander):
        """Verify wiring twice is safe."""
        bridge = ICSTelegramBridge(bot_token="test:tok", chat_id="-100abc")
        first = bridge.wire(mock_commander)
        second = bridge.wire(mock_commander)
        assert first is True
        assert second is True
        assert bridge.is_wired is True

    def test_wire_disabled_bridge(self, mock_commander):
        """Verify wire() returns False when bridge is disabled."""
        bridge = ICSTelegramBridge(bot_token="x", chat_id="y", enabled=False)
        result = bridge.wire(mock_commander)
        assert result is False
        assert bridge.is_wired is False

    def test_unwire_removes_alert_fn(self, mock_commander):
        """Verify unwire() removes the alert callback."""
        bridge = ICSTelegramBridge(bot_token="x", chat_id="y")
        bridge.wire(mock_commander)
        assert mock_commander.alert_fn is not None

        bridge.unwire(mock_commander)
        assert bridge.is_wired is False
        assert mock_commander.alert_fn is None

    def test_unwire_without_wire(self, mock_commander):
        """Verify unwire() without prior wire() is safe."""
        bridge = ICSTelegramBridge(bot_token="x", chat_id="y")
        bridge.unwire(mock_commander)  # Should not raise
        assert bridge.is_wired is False

    def test_callback_invocation_no_error(self, mock_commander):
        """Verify alert callback can be invoked without sending (no client)."""
        bridge = ICSTelegramBridge(bot_token="test:tok", chat_id="-100abc")
        bridge.wire(mock_commander)

        # Trigger alert - should not raise even without real Telegram client
        mock_commander.trigger_alert("Test message", True)
        assert len(mock_commander.alerts_received) == 1
        assert mock_commander.alerts_received[0] == ("Test message", True)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SINGLETON TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestBridgeSingleton:
    """Verify singleton pattern."""

    def test_get_bridge_returns_singleton(self):
        """Verify get_ics_telegram_bridge returns the same instance."""
        b1 = get_ics_telegram_bridge()
        b2 = get_ics_telegram_bridge()
        assert b1 is b2

    def test_reset_creates_new_instance(self):
        """Verify reset creates a new singleton instance."""
        b1 = get_ics_telegram_bridge()
        reset_ics_telegram_bridge()
        b2 = get_ics_telegram_bridge()
        assert b1 is not b2

    def test_get_bridge_creates_passive_when_no_env(self):
        """Verify bridge creates in passive mode when no env vars set."""
        bridge = get_ics_telegram_bridge()
        assert bridge.is_enabled is False  # No creds = disabled
        assert bridge.is_wired is False

    def test_get_bridge_with_env_vars(self, monkeypatch):
        """Verify bridge activates when env vars are set."""
        monkeypatch.setenv("OPBUYING_TELEGRAM_BOT_TOKEN", "bot123:abc")
        monkeypatch.setenv("OPBUYING_TELEGRAM_CHAT_ID", "-10099999")

        reset_ics_telegram_bridge()
        bridge = get_ics_telegram_bridge()
        assert bridge.is_enabled is True
        assert bridge._bot_token == "bot123:abc"
        assert bridge._chat_id == "-10099999"

    def test_get_bridge_explicit_params_override_env(self, monkeypatch):
        """Verify explicit params override env vars."""
        monkeypatch.setenv("OPBUYING_TELEGRAM_BOT_TOKEN", "env_token")
        monkeypatch.setenv("OPBUYING_TELEGRAM_CHAT_ID", "env_chat")

        bridge = get_ics_telegram_bridge(
            bot_token="explicit_token",
            chat_id="explicit_chat",
        )
        assert bridge._bot_token == "explicit_token"
        assert bridge._chat_id == "explicit_chat"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. WIRE_ICS_TELEGRAM_ALERTS CONVENIENCE FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════


class TestWireFunction:
    """Verify the convenience wire_ics_telegram_alerts() function."""

    def test_wire_function_no_credentials(self):
        """Verify wire function returns False without credentials."""
        result = wire_ics_telegram_alerts()
        assert result is False  # No creds = not active

    def test_wire_function_with_explicit_credentials(self):
        """Verify wire function returns True with explicit credentials."""
        result = wire_ics_telegram_alerts(
            bot_token="test:token",
            chat_id="-100test",
        )
        assert result is True

    def test_wire_function_with_explicit_disabled(self):
        """Verify wire function returns False when explicitly disabled."""
        result = wire_ics_telegram_alerts(
            bot_token="test:token",
            chat_id="-100test",
            enabled=False,
        )
        assert result is False

    def test_wire_function_idempotent(self):
        """Verify calling wire function twice is safe."""
        result1 = wire_ics_telegram_alerts(bot_token="x", chat_id="y")
        result2 = wire_ics_telegram_alerts(bot_token="x", chat_id="y")
        assert result1 is True
        assert result2 is True

    def test_wire_function_with_env_vars(self, monkeypatch):
        """Verify wire function reads from env vars."""
        monkeypatch.setenv("OPBUYING_TELEGRAM_BOT_TOKEN", "env:token")
        monkeypatch.setenv("OPBUYING_TELEGRAM_CHAT_ID", "-100env")

        reset_ics_telegram_bridge()
        result = wire_ics_telegram_alerts()
        assert result is True


# ═══════════════════════════════════════════════════════════════════════════════
# 5. CLOSE & CLEANUP TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestBridgeCleanup:
    """Verify bridge cleanup."""

    def test_close_sets_client_to_none(self):
        """Verify close() cleans up the underlying client."""
        bridge = ICSTelegramBridge(bot_token="test:tok", chat_id="-100abc")
        # Ensure client is attempted to be created
        bridge._ensure_client()
        bridge.close()
        assert bridge._client is None, "Client should be None after close()"

    def test_close_is_idempotent(self):
        """Verify close() can be called multiple times."""
        bridge = ICSTelegramBridge(bot_token="x", chat_id="y")
        bridge.close()
        bridge.close()  # Should not raise

    def test_reset_cleans_up_singleton(self):
        """Verify reset_ics_telegram_bridge cleans up properly."""
        get_ics_telegram_bridge(bot_token="x", chat_id="y")
        reset_ics_telegram_bridge()
        new_bridge = get_ics_telegram_bridge()
        assert new_bridge is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 6. FORMATTING & EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════


class TestBridgeEdgeCases:
    """Verify edge cases and error handling."""

    def test_callback_with_empty_message(self, mock_commander):
        """Verify callback handles empty message gracefully (no crash)."""
        bridge = ICSTelegramBridge(bot_token="x", chat_id="y")
        bridge.wire(mock_commander)

        # Trigger with empty message
        mock_commander.trigger_alert("", is_critical=True)
        assert len(mock_commander.alerts_received) == 1

    def test_callback_with_very_long_message(self, mock_commander):
        """Verify callback handles very long messages gracefully."""
        bridge = ICSTelegramBridge(bot_token="x", chat_id="y")
        bridge.wire(mock_commander)

        long_msg = "X" * 5000
        mock_commander.trigger_alert(long_msg, is_critical=False)
        assert len(mock_commander.alerts_received) == 1

    def test_callback_non_critical_alert(self, mock_commander):
        """Verify non-critical alert is processed."""
        bridge = ICSTelegramBridge(bot_token="x", chat_id="y")
        bridge.wire(mock_commander)

        mock_commander.trigger_alert("Info message", is_critical=False)
        assert mock_commander.alerts_received[0][1] is False

    def test_callback_critical_alert(self, mock_commander):
        """Verify critical alert passes is_critical=True."""
        bridge = ICSTelegramBridge(bot_token="x", chat_id="y")
        bridge.wire(mock_commander)

        mock_commander.trigger_alert("Critical error", is_critical=True)
        assert mock_commander.alerts_received[0][1] is True

    def test_disabled_bridge_does_not_wire(self, mock_commander):
        """Verify disabled bridge does not wire and reports disabled."""
        bridge = ICSTelegramBridge(bot_token="x", chat_id="y", enabled=False)
        result = bridge.wire(mock_commander)
        assert result is False
        assert mock_commander.alert_fn is None
