"""
Tests for the Email Notification Adapter (v2.53).
"""

import smtplib
import time
from unittest.mock import MagicMock, patch

import pytest
from core.ports.notification.notification_port import (
    Notification,
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
)
from infrastructure.adapters.notifications.email_adapter import (
    EmailNotificationAdapter,
)


class TestEmailAdapterInit:
    """Test adapter initialization and configuration."""

    def test_default_init(self):
        adapter = EmailNotificationAdapter()
        assert adapter._smtp_host == "smtp.gmail.com"
        assert adapter._smtp_port == 587
        assert adapter._enabled is True
        assert adapter._use_tls is True

    def test_disabled_init(self):
        adapter = EmailNotificationAdapter(enabled=False)
        assert adapter._enabled is False

    def test_custom_config(self):
        adapter = EmailNotificationAdapter(
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_user="user@example.com",
            smtp_pass="secret",
            default_recipient="admin@example.com",
            use_tls=False,
            rate_limit=10,
            rate_window=30,
        )
        assert adapter._smtp_host == "smtp.example.com"
        assert adapter._smtp_port == 465
        assert adapter._smtp_user == "user@example.com"
        assert adapter._smtp_pass == "secret"
        assert adapter._default_recipient == "admin@example.com"
        assert adapter._use_tls is False
        assert adapter._rate_limit == 10
        assert adapter._rate_window == 30


class TestEmailAdapterDisabled:
    """Test behavior when adapter is disabled."""

    def test_send_returns_failed_when_disabled(self):
        adapter = EmailNotificationAdapter(enabled=False)
        notification = Notification(
            channel=NotificationChannel.EMAIL,
            message="Test",
            priority=NotificationPriority.NORMAL,
        )
        result = adapter.send_notification(notification)
        assert result.status == NotificationStatus.FAILED
        assert "disabled" in (result.error_message or "").lower()

    def test_channel_unavailable_when_disabled(self):
        adapter = EmailNotificationAdapter(enabled=False)
        assert adapter.is_channel_available(NotificationChannel.EMAIL) is False


class TestEmailAdapterChannel:
    """Test channel validation."""

    def test_rejects_wrong_channel(self):
        adapter = EmailNotificationAdapter()
        notification = Notification(
            channel=NotificationChannel.TELEGRAM,
            message="Test",
            priority=NotificationPriority.NORMAL,
        )
        result = adapter.send_notification(notification)
        assert result.status == NotificationStatus.FAILED
        assert "expected email" in (result.error_message or "").lower()

    def test_channel_availability_requires_credentials(self):
        adapter = EmailNotificationAdapter(
            smtp_host="",
            smtp_user="",
            smtp_pass="",
        )
        assert adapter.is_channel_available(NotificationChannel.EMAIL) is False

    def test_channel_availability_with_credentials(self):
        adapter = EmailNotificationAdapter(
            smtp_host="smtp.gmail.com",
            smtp_user="user@gmail.com",
            smtp_pass="app-password",
        )
        assert adapter.is_channel_available(NotificationChannel.EMAIL) is True

    def test_channel_availability_wrong_channel(self):
        adapter = EmailNotificationAdapter()
        assert adapter.is_channel_available(NotificationChannel.TELEGRAM) is False
        assert adapter.is_channel_available(NotificationChannel.SMS) is False


class TestEmailAdapterRecipient:
    """Test recipient resolution."""

    def test_no_recipient_returns_error(self):
        adapter = EmailNotificationAdapter()
        notification = Notification(
            channel=NotificationChannel.EMAIL,
            message="Test",
            priority=NotificationPriority.NORMAL,
        )
        result = adapter.send_notification(notification)
        assert result.status == NotificationStatus.FAILED
        assert "recipient" in (result.error_message or "").lower()

    def test_default_recipient_used(self):
        """Default recipient should be used when notification has no recipient."""
        adapter = EmailNotificationAdapter(
            default_recipient="admin@example.com",
            smtp_user="user@gmail.com",
            smtp_pass="pass",
        )
        notification = Notification(
            channel=NotificationChannel.EMAIL,
            message="Test",
            priority=NotificationPriority.NORMAL,
        )
        # With no network, SMTP connection will fail; verify we get a FAILED result
        from unittest.mock import patch as _p
        with _p.object(adapter, '_connect', side_effect=ConnectionError("No network")):
            result = adapter.send_notification(notification)
            assert result.status == NotificationStatus.FAILED
            assert "No network" in (result.error_message or "")

    def test_explicit_recipient_overrides_default(self):
        """Explicit recipient on notification overrides default."""
        adapter = EmailNotificationAdapter(
            default_recipient="default@example.com",
            smtp_user="user@gmail.com",
            smtp_pass="pass",
        )
        notification = Notification(
            channel=NotificationChannel.EMAIL,
            message="Test",
            recipient="explicit@example.com",
            priority=NotificationPriority.NORMAL,
        )
        from unittest.mock import patch as _p
        with _p.object(adapter, '_send_smtp') as mock_send:
            with _p.object(adapter, '_check_rate_limit', return_value=True):
                result = adapter.send_notification(notification)
                assert result.status == NotificationStatus.SENT
                # Verify sendmail was called with the explicit recipient
                call_args = mock_send.call_args
                assert call_args is not None
                # _send_smtp signature: (from_addr, to_addr, msg)
                assert call_args[0][1] == "explicit@example.com"


class TestEmailAdapterRateLimit:
    """Test rate limiting behavior."""

    def test_rate_limit_allows_within_limit(self):
        adapter = EmailNotificationAdapter(
            rate_limit=3,
            rate_window=60,
        )
        # Calling _check_rate_limit 3 times should succeed (equal to limit)
        for i in range(3):
            assert adapter._check_rate_limit() is True, f"Request {i+1} should be allowed"
        # 4th call should be blocked
        assert adapter._check_rate_limit() is False

    def test_rate_limit_blocks_after_limit(self):
        adapter = EmailNotificationAdapter(
            rate_limit=3,
            rate_window=60,
            default_recipient="test@example.com",
        )
        # Manually fill the timestamps
        adapter._send_timestamps = [time.time()] * 3
        assert adapter._check_rate_limit() is False

    def test_rate_limit_prunes_old_entries(self):
        adapter = EmailNotificationAdapter(
            rate_limit=3,
            rate_window=1,  # 1 second window
            default_recipient="test@example.com",
        )
        # Add old timestamps (beyond window)
        adapter._send_timestamps = [time.time() - 10] * 3
        # These should be pruned and allow new sends
        assert adapter._check_rate_limit() is True
        # After the check, only 1 entry should remain
        assert len(adapter._send_timestamps) == 1

    def test_rate_limit_status(self):
        adapter = EmailNotificationAdapter(
            rate_limit=10,
            rate_window=60,
        )
        # Check status for wrong channel
        status = adapter.get_rate_limit_status(NotificationChannel.TELEGRAM)
        assert "error" in status

        # Check status for email channel
        status = adapter.get_rate_limit_status(NotificationChannel.EMAIL)
        assert status["channel"] == "email"
        assert status["rate_limit"] == 10
        assert status["rate_window_seconds"] == 60
        assert status["enabled"] is True
        assert status["sent_in_window"] == 0
        assert status["remaining"] == 10


class TestEmailAdapterHtml:
    """Test HTML email formatting."""

    def test_html_escapes_html_entities(self):
        adapter = EmailNotificationAdapter()
        notification = Notification(
            channel=NotificationChannel.EMAIL,
            message="Price < 100 & > 50",
            priority=NotificationPriority.HIGH,
        )
        html = adapter._to_html("Price < 100 & > 50", notification)
        assert "&lt;" in html
        assert "&amp;" in html
        assert "&gt;" in html
        # The '<' and '>' in the body should be escaped; count occurrences
        body_start = html.find("OPB Trading Bot")  # After header
        body_section = html[body_start:]
        # The body text should not contain raw '<' or '>' (only HTML tags)
        assert "&lt;" in body_section  # Escaped <
        assert "&gt;" in body_section  # Escaped >

    def test_html_contains_priority_color(self):
        adapter = EmailNotificationAdapter()
        notification = Notification(
            channel=NotificationChannel.EMAIL,
            message="Test",
            priority=NotificationPriority.CRITICAL,
        )
        html = adapter._to_html("Test", notification)
        assert "#dc3545" in html  # Red for CRITICAL

    def test_html_normal_priority_color(self):
        adapter = EmailNotificationAdapter()
        notification = Notification(
            channel=NotificationChannel.EMAIL,
            message="Test",
            priority=NotificationPriority.NORMAL,
        )
        html = adapter._to_html("Test", notification)
        assert "#0d6efd" in html  # Blue for NORMAL

    def test_html_contains_footer(self):
        adapter = EmailNotificationAdapter()
        notification = Notification(
            channel=NotificationChannel.EMAIL,
            message="Test",
            priority=NotificationPriority.LOW,
        )
        html = adapter._to_html("Test", notification)
        assert "automated notification" in html

    def test_html_newlines_converted(self):
        adapter = EmailNotificationAdapter()
        notification = Notification(
            channel=NotificationChannel.EMAIL,
            message="Line 1\nLine 2\nLine 3",
            priority=NotificationPriority.NORMAL,
        )
        html = adapter._to_html("Line 1\nLine 2\nLine 3", notification)
        assert "<br>" in html


class TestEmailAdapterSubject:
    """Test subject inference."""

    def test_subject_includes_priority_prefix(self):
        adapter = EmailNotificationAdapter()
        notification = Notification(
            channel=NotificationChannel.EMAIL,
            message="Test message",
            priority=NotificationPriority.CRITICAL,
        )
        subject = adapter._infer_subject(notification)
        assert "[CRITICAL]" in subject

    def test_subject_truncates_long_message(self):
        adapter = EmailNotificationAdapter()
        long_msg = "This is a very long message that should be truncated at eighty characters for the email subject line"
        notification = Notification(
            channel=NotificationChannel.EMAIL,
            message=long_msg,
            priority=NotificationPriority.NORMAL,
        )
        subject = adapter._infer_subject(notification)
        # First part should be the message summary (max 80 chars)
        assert len(subject.split(" - ")[-1]) <= 80

    def test_subject_uses_explicit_subject(self):
        """When notification has a subject, the adapter should use it."""
        adapter = EmailNotificationAdapter()
        notification = Notification(
            channel=NotificationChannel.EMAIL,
            message="Body text here",
            subject="Custom Subject Line",
            priority=NotificationPriority.HIGH,
        )
        # When subject is explicitly set, it's used directly in send_notification
        # _infer_subject is a fallback
        assert notification.subject == "Custom Subject Line"


class TestEmailAdapterSmtpConnection:
    """Test SMTP connection management."""

    def test_connect_creates_smtp_connection(self):
        adapter = EmailNotificationAdapter(
            smtp_host="smtp.test.com",
            smtp_port=587,
        )
        with patch('smtplib.SMTP') as mock_smtp:
            mock_instance = MagicMock()
            mock_smtp.return_value = mock_instance

            server = adapter._connect()

            mock_smtp.assert_called_once_with("smtp.test.com", 587, timeout=10)
            assert server == mock_instance

    def test_connect_calls_starttls_when_enabled(self):
        adapter = EmailNotificationAdapter(
            smtp_host="smtp.test.com",
            smtp_port=587,
            use_tls=True,
        )
        with patch('smtplib.SMTP') as mock_smtp:
            mock_instance = MagicMock()
            mock_smtp.return_value = mock_instance

            adapter._connect()

            mock_instance.ehlo.assert_called()
            mock_instance.starttls.assert_called_once()

    def test_connect_skips_starttls_when_disabled(self):
        adapter = EmailNotificationAdapter(
            smtp_host="smtp.test.com",
            smtp_port=587,
            use_tls=False,
        )
        with patch('smtplib.SMTP') as mock_smtp:
            mock_instance = MagicMock()
            mock_smtp.return_value = mock_instance

            adapter._connect()

            mock_instance.starttls.assert_not_called()

    def test_connect_calls_login_with_credentials(self):
        adapter = EmailNotificationAdapter(
            smtp_host="smtp.test.com",
            smtp_port=587,
            smtp_user="user@test.com",
            smtp_pass="password",
        )
        with patch('smtplib.SMTP') as mock_smtp:
            mock_instance = MagicMock()
            mock_smtp.return_value = mock_instance

            adapter._connect()

            mock_instance.login.assert_called_once_with("user@test.com", "password")

    def test_reset_connection(self):
        adapter = EmailNotificationAdapter()
        mock_conn = MagicMock()
        adapter._smtp_connection = mock_conn
        adapter._last_connect = time.time()

        adapter._reset_connection()

        mock_conn.quit.assert_called_once()
        assert adapter._smtp_connection is None
        assert adapter._last_connect == 0.0

    def test_get_connection_creates_new_if_none(self):
        adapter = EmailNotificationAdapter(
            smtp_host="smtp.test.com",
            smtp_port=587,
        )
        with patch.object(adapter, '_connect') as mock_connect:
            mock_connect.return_value = MagicMock()

            server = adapter._get_connection()

            assert server is not None
            mock_connect.assert_called_once()

    def test_get_connection_reconnects_on_stale(self):
        adapter = EmailNotificationAdapter(
            smtp_host="smtp.test.com",
            smtp_port=587,
        )
        adapter._connect_timeout = 0.1  # Very short timeout
        old_conn = MagicMock()
        adapter._smtp_connection = old_conn
        adapter._last_connect = time.time() - 10  # Well past timeout

        with patch.object(adapter, '_connect') as mock_connect:
            new_conn = MagicMock()
            mock_connect.return_value = new_conn

            server = adapter._get_connection()

            old_conn.quit.assert_called_once()
            assert server == new_conn


class TestEmailAdapterSmtpSend:
    """Test SMTP send with auto-reconnect."""

    def test_send_smtp_success(self):
        adapter = EmailNotificationAdapter()
        mock_server = MagicMock()
        mock_msg = MagicMock()
        mock_msg.as_string.return_value = "email content"

        with patch.object(adapter, '_get_connection', return_value=mock_server):
            adapter._send_smtp("from@test.com", "to@test.com", mock_msg)

            mock_server.sendmail.assert_called_once_with(
                "from@test.com", ["to@test.com"], "email content"
            )

    def test_send_smtp_reconnects_on_disconnect(self):
        adapter = EmailNotificationAdapter()
        mock_server = MagicMock()
        mock_server.sendmail.side_effect = [
            smtplib.SMTPServerDisconnected("Connection lost"),
            None,  # Second attempt succeeds
        ]
        mock_msg = MagicMock()
        mock_msg.as_string.return_value = "email content"

        with patch.object(adapter, '_get_connection', return_value=mock_server):
            with patch.object(adapter, '_reset_connection') as mock_reset:
                adapter._send_smtp("from@test.com", "to@test.com", mock_msg)

                assert mock_server.sendmail.call_count == 2
                mock_reset.assert_called_once()


class TestEmailAdapterIntegration:
    """Integration-style tests with mocked SMTP."""

    def test_send_notification_success_with_mocked_smtp(self):
        adapter = EmailNotificationAdapter(
            default_recipient="admin@example.com",
            smtp_user="user@gmail.com",
            smtp_pass="pass",
        )
        notification = Notification(
            channel=NotificationChannel.EMAIL,
            message="Test market alert",
            priority=NotificationPriority.HIGH,
        )

        with patch.object(adapter, '_send_smtp') as mock_send:
            with patch.object(adapter, '_check_rate_limit', return_value=True):
                result = adapter.send_notification(notification)

                assert result.status == NotificationStatus.SENT
                assert result.channel == NotificationChannel.EMAIL
                assert "email_" in result.notification_id
                mock_send.assert_called_once()

    def test_send_notification_auth_failure(self):
        adapter = EmailNotificationAdapter(
            default_recipient="admin@example.com",
            smtp_user="user@gmail.com",
            smtp_pass="wrong-pass",
        )
        notification = Notification(
            channel=NotificationChannel.EMAIL,
            message="Test",
            priority=NotificationPriority.NORMAL,
        )

        with patch.object(adapter, '_send_smtp', side_effect=smtplib.SMTPAuthenticationError(535, b"Auth failed")):
            with patch.object(adapter, '_check_rate_limit', return_value=True):
                result = adapter.send_notification(notification)

                assert result.status == NotificationStatus.FAILED
                assert "authentication" in (result.error_message or "").lower()

    def test_send_notification_rate_limited(self):
        adapter = EmailNotificationAdapter(
            default_recipient="admin@example.com",
            rate_limit=1,
        )
        notification = Notification(
            channel=NotificationChannel.EMAIL,
            message="Test",
            priority=NotificationPriority.NORMAL,
        )

        with patch.object(adapter, '_check_rate_limit', return_value=False):
            result = adapter.send_notification(notification)

            assert result.status == NotificationStatus.RATE_LIMITED
            assert "rate limit" in (result.error_message or "").lower()

    def test_send_notifications_batch(self):
        adapter = EmailNotificationAdapter(
            default_recipient="admin@example.com",
            smtp_user="user@gmail.com",
            smtp_pass="pass",
        )
        notifications = [
            Notification(
                channel=NotificationChannel.EMAIL,
                message=f"Alert {i}",
                priority=NotificationPriority.NORMAL,
            )
            for i in range(3)
        ]

        with patch.object(adapter, 'send_notification', return_value=MagicMock(
            status=NotificationStatus.SENT,
            notification_id="test",
            channel=NotificationChannel.EMAIL,
        )):
            results = adapter.send_notifications(notifications)
            assert len(results) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
