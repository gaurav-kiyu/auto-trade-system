"""
Unit and regression tests for Telegram credential and token redaction (P0 Requirement).
Ensures bot tokens, passwords, and sensitive keys are never exposed in logs, exceptions,
URLs, or audit records.
"""
import logging
from unittest.mock import MagicMock, patch
import requests

from core.config_helpers import redact_credential_urls
from infrastructure.adapters.notifications.telegram_adapter import (
    TelegramNotificationAdapter,
    _TelegramClient,
)
from core.ports.notification.notification_port import (
    Notification,
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
)


class TestTelegramCredentialRedaction:
    def test_redact_credential_urls_patterns(self):
        """Test regex redaction on diverse Telegram URLs and credential patterns."""
        sample_token = "1234567890:ABCdef_GHI-jklMNOpqrsTUVwxyz123"
        url = f"https://api.telegram.org/bot{sample_token}/sendMessage"
        redacted = redact_credential_urls(url)
        assert sample_token not in redacted
        assert "https://api.telegram.org/bot<REDACTED>/sendMessage" == redacted

        # Relative path / query param
        path = f"/bot{sample_token}/getUpdates"
        assert redact_credential_urls(path) == "/bot<REDACTED>/getUpdates"

        # Password / secret param
        query = "https://example.com/api?user=admin&password=SuperSecretPassword123&token=tok_998877"
        redacted_query = redact_credential_urls(query)
        assert "SuperSecretPassword123" not in redacted_query
        assert "tok_998877" not in redacted_query
        assert "password=<REDACTED>" in redacted_query
        assert "token=<REDACTED>" in redacted_query

        # Bearer header
        auth_hdr = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0"
        redacted_auth = redact_credential_urls(auth_hdr)
        assert "eyJhbGciOi" not in redacted_auth
        assert "Bearer <REDACTED>" in redacted_auth

    def test_telegram_client_send_exception_redacts_token(self, caplog):
        """When requests raises an exception with the full URL, the log contains only redacted URL."""
        secret_token = "987654321:XYZ_token_secret_value"
        client = _TelegramClient(
            bot_token=secret_token,
            default_chat_id="123456",
            enabled=True,
        )

        mock_session = MagicMock()
        # Simulate requests ConnectionError containing full URL in error message
        mock_session.post.side_effect = requests.exceptions.ConnectionError(
            f"HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries exceeded with url: /bot{secret_token}/sendMessage"
        )
        client._session = mock_session

        with caplog.at_level(logging.ERROR):
            success = client._send_message("123456", "Test message")

        assert success is False
        # Verify secret_token is NEVER in logs
        assert secret_token not in caplog.text
        assert "bot<REDACTED>" in caplog.text

    def test_telegram_adapter_error_message_is_redacted(self):
        """NotificationResult.error_message must never contain the bot token."""
        secret_token = "555666777:SecretBotTokenHere"
        adapter = TelegramNotificationAdapter(
            bot_token=secret_token,
            default_chat_id="123456",
            enabled=True,
        )

        # Mock client to raise exception with token in string
        adapter._client = MagicMock()
        adapter._client.send_signal_alert.side_effect = requests.exceptions.HTTPError(
            f"502 Bad Gateway for url: https://api.telegram.org/bot{secret_token}/sendMessage"
        )

        notif = Notification(
            message="Test signal message",
            channel=NotificationChannel.TELEGRAM,
            priority=NotificationPriority.HIGH,
            recipient="123456",
        )

        result = adapter.send_notification(notif)
        assert result.status != NotificationStatus.SENT
        assert secret_token not in result.error_message
        assert "bot<REDACTED>" in result.error_message

    def test_telegram_client_pin_exception_redacts_token(self, caplog):
        """Pin failure log never exposes token."""
        secret_token = "111222333:SecretPinTokenValue"
        client = _TelegramClient(
            bot_token=secret_token,
            default_chat_id="123456",
            enabled=True,
        )
        mock_session = MagicMock()
        mock_session.post.side_effect = requests.exceptions.Timeout(
            f"Timeout connecting to https://api.telegram.org/bot{secret_token}/pinChatMessage"
        )
        client._session = mock_session

        with caplog.at_level(logging.WARNING):
            client._pin_message("123456", 999)

        assert secret_token not in caplog.text
        assert "bot<REDACTED>" in caplog.text

    def test_non_signal_alert_does_not_emit_qualifying_signal_template(self):
        """Plain text alerts (DLQ, constitution, system) must return raw message, not dummy signal format."""
        adapter = TelegramNotificationAdapter(
            bot_token="123456:FAKE_TOKEN",
            default_chat_id="123456",
            enabled=True,
        )

        notif = Notification(
            message="Notification delivery to kiyu failed after 3 attempts",
            channel=NotificationChannel.TELEGRAM,
            priority=NotificationPriority.CRITICAL,
            recipient="admin",
            subject="Delivery Failure",
        )

        sig = adapter._notification_to_signal(notif)
        formatted = _TelegramClient.format_alert(sig)
        # Must NOT contain the dummy [OPB QUALIFYING SIGNAL] template with 0 price
        assert "[OPB QUALIFYING SIGNAL]" not in formatted
        assert "₹0.00" not in formatted
        assert "Notification delivery to kiyu failed" in formatted

    def test_dummy_signal_is_never_pinned_even_if_critical(self):
        """_TelegramClient must NEVER pin a dummy signal with ₹0.00 price or unknown symbol."""
        client = _TelegramClient(
            bot_token="123456:FAKE_TOKEN",
            default_chat_id="123456",
            enabled=True,
        )
        client._send_message = MagicMock(return_value=True)
        client._pin_message = MagicMock()

        dummy_signal = {
            "symbol": "UNKNOWN",
            "price": 0.0,
            "signal": "ALERT",
            "strength": "STRONG",
            "score": 50,
            "direction": "NONE",
        }

        sent = client.send_signal_alert(dummy_signal)
        assert sent is True
        client._send_message.assert_called_once()
        # Pin argument passed to _send_message must be False
        assert client._send_message.call_args[1]["pin"] is False

    def test_multi_user_telegram_cooldown_isolation(self):
        """User A receiving a signal does not trigger cooldown block for User B with different chat ID."""
        client = _TelegramClient(
            bot_token="123456:FAKE_TOKEN",
            default_chat_id="111111",
            enabled=True,
            cooldown_seconds=900,
        )
        client._send_message = MagicMock(return_value=True)

        sig_user_a = {
            "symbol": "FINNIFTY",
            "price": 25000.0,
            "signal": "BUY",
            "strength": "STRONG",
            "direction": "CALL",
            "score": 85,
            "chat_id": "111111",
        }
        sig_user_b = {
            "symbol": "FINNIFTY",
            "price": 25000.0,
            "signal": "BUY",
            "strength": "STRONG",
            "direction": "CALL",
            "score": 85,
            "chat_id": "222222",
        }

        # User A sends successfully
        assert client.send_signal_alert(sig_user_a) is True
        # User B should NOT be blocked by User A's cooldown
        assert client.send_signal_alert(sig_user_b) is True
        # But User A sending AGAIN immediately is blocked by User A's cooldown
        assert client.send_signal_alert(sig_user_a) is False

