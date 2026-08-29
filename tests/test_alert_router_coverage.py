"""Edge case tests for core.alert_router — additional coverage for uncovered paths.

These tests cover edge cases not covered by the main test_alert_router.py file.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.alert_router import (
    EmailAlerter,
    MultiChannelAlerter,
    WebhookAlerter,
)


class TestEmailAlerterEdgeCases:
    """Edge cases for EmailAlerter."""

    def test_init_empty_config(self):
        """Empty config should not crash."""
        alerter = EmailAlerter({})
        assert alerter.enabled is False

    def test_send_alert_disabled(self):
        alerter = EmailAlerter({})
        result = alerter.send_alert("Subject", "Body")
        assert result is False

    def test_recipients_parsed_from_comma_string(self):
        """Comma-separated EMAIL_TO string is parsed into a list."""
        alerter = EmailAlerter({"EMAIL_TO": "a@x.com, b@x.com, c@x.com"})
        assert len(alerter.recipients) == 3

    def test_recipients_single_address(self):
        alerter = EmailAlerter({"EMAIL_TO": "single@x.com"})
        assert len(alerter.recipients) == 1

    def test_recipients_empty_string(self):
        alerter = EmailAlerter({"EMAIL_TO": ""})
        assert alerter.recipients == []

    def test_recipients_not_present(self):
        alerter = EmailAlerter({})
        assert alerter.recipients == []

    def test_send_alert_with_creds_still_fails_smtp(self):
        """Patched SMTP to avoid real connection."""
        alerter = EmailAlerter({
            "EMAIL_ENABLED": True,
            "EMAIL_USER": "user@x.com",
            "EMAIL_PASS": "pass",
            "EMAIL_TO": "user@x.com",
        })
        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.starttls.side_effect = ConnectionError("no server")
            result = alerter.send_alert("Subject", "Body")
            assert result is False

    def test_send_alert_smtp_sendmail_error(self):
        """SMTP sendmail failure handled gracefully."""
        alerter = EmailAlerter({
            "EMAIL_ENABLED": True,
            "EMAIL_USER": "user@x.com",
            "EMAIL_PASS": "pass",
            "EMAIL_TO": "user@x.com",
        })
        with patch("smtplib.SMTP") as mock_smtp:
            mock_instance = MagicMock()
            mock_instance.sendmail.side_effect = ConnectionError("send failed")
            mock_smtp.return_value.__enter__.return_value = mock_instance
            mock_smtp.return_value = mock_instance
            result = alerter.send_alert("Subject", "Body")
            assert result is False

    def test_int_port_conversion(self):
        alerter = EmailAlerter({"EMAIL_PORT": "465"})
        assert alerter.smtp_port == 465


class TestWebhookAlerterEdgeCases:
    """Edge cases for WebhookAlerter."""

    def test_init_empty_config(self):
        alerter = WebhookAlerter({})
        assert alerter.enabled is False
        assert alerter.url == ""

    def test_send_alert_disabled(self):
        alerter = WebhookAlerter({})
        result = alerter.send_alert("Subject", "Body")
        assert result is False

    def test_send_alert_no_url(self):
        alerter = WebhookAlerter({"webhook_enabled": True})
        result = alerter.send_alert("Subject", "Body")
        assert result is False

    def test_rate_limit_exceeded(self):
        alerter = WebhookAlerter({
            "webhook_enabled": True,
            "webhook_url": "http://example.com/webhook",
            "webhook_rate_limit_per_min": 1,
        })
        # First call should pass
        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response
            result1 = alerter.send_alert("Test", "Body")
            assert result1 is True

        # Second call should fail (rate limit exceeded)
        result2 = alerter.send_alert("Test2", "Body2")
        assert result2 is False

    def test_send_alert_network_error(self):
        alerter = WebhookAlerter({
            "webhook_enabled": True,
            "webhook_url": "http://example.com/webhook",
        })
        with patch("requests.post", side_effect=ConnectionError("Network error")):
            result = alerter.send_alert("Test", "Body")
            assert result is False

    def test_send_alert_http_error(self):
        """raise_for_status triggers RequestException handling."""
        alerter = WebhookAlerter({
            "webhook_enabled": True,
            "webhook_url": "http://example.com/webhook",
        })
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = ConnectionError("HTTP error")
        with patch("requests.post", return_value=mock_response):
            result = alerter.send_alert("Test", "Body")
            assert result is False

    def test_allow_live_default(self):
        alerter = WebhookAlerter({})
        assert alerter.allow_live is False


class TestMultiChannelAlerterEdgeCases:
    """Edge cases for MultiChannelAlerter."""

    def test_init_empty_config(self):
        alerter = MultiChannelAlerter({})
        assert alerter.cfg == {}

    def test_send_alert_returns_dict(self):
        alerter = MultiChannelAlerter({})
        result = alerter.send_alert("Subject", "Body")
        assert isinstance(result, dict)

    def test_send_alert_default_chat_id(self):
        alerter = MultiChannelAlerter({"CHAT_ID": "test123"})
        assert alerter._default_chat_id == "test123"

    def test_send_alert_telegram_only_returns_telegram_key(self):
        """telegram_only=True should return dict with 'telegram' key."""
        alerter = MultiChannelAlerter({})
        result = alerter.send_alert("Subject", "Body", telegram_only=True)
        assert isinstance(result, dict)
        assert "telegram" in result
