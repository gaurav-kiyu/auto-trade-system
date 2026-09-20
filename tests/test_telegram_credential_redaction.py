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
