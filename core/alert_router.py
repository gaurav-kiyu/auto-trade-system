"""
Multi-Channel Alert Router
Handles sending alerts via multiple channels: Telegram, Email, Webhook.
"""

from __future__ import annotations

import json
import logging
import smtplib
import threading
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import requests

# Import the existing TelegramEngine
from core.legacy.telegram_engine import TelegramEngine

_log = logging.getLogger(__name__)


class EmailAlerter:
    """Handles sending email alerts via SMTP."""

    def __init__(self, cfg: dict[str, Any]):
        self.enabled = cfg.get("EMAIL_ENABLED", False)
        self.smtp_server = cfg.get("EMAIL_SMTP", "smtp.gmail.com")
        self.smtp_port = int(cfg.get("EMAIL_PORT", 587))
        self.username = cfg.get("EMAIL_USER", "")
        self.password = cfg.get("EMAIL_PASS", "")
        self.recipients = cfg.get("EMAIL_TO", "")
        if isinstance(self.recipients, str):
            self.recipients = [addr.strip() for addr in self.recipients.split(",") if addr.strip()]

    def send_alert(self, subject: str, body: str) -> bool:
        """Send an email alert.
        Returns True if successful, False otherwise.
        """
        if not self.enabled or not self.username or not self.password or not self.recipients:
            _log.warning("Email alerts not configured or disabled")
            return False

        try:
            msg = MIMEMultipart()
            msg["From"] = self.username
            msg["To"] = ", ".join(self.recipients)
            msg["Subject"] = subject

            msg.attach(MIMEText(body, "plain"))

            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.username, self.password)
            text = msg.as_string()
            server.sendmail(self.username, self.recipients, text)
            server.quit()
            _log.info(f"Email alert sent to {len(self.recipients)} recipient(s)")
            return True
        except (smtplib.SMTPException, OSError, ConnectionError, TimeoutError, ValueError) as e:
            _log.error(f"Failed to send email alert: {e}")
            return False


class WebhookAlerter:
    """Handles sending alerts via HTTP webhook."""

    def __init__(self, cfg: dict[str, Any]):
        self.enabled = cfg.get("webhook_enabled", False)
        self.url = cfg.get("webhook_url", "")  # Should be configured in config.json
        self.allow_live = cfg.get("webhook_allow_live", False)
        self.rate_limit_per_min = int(cfg.get("webhook_rate_limit_per_min", 5))
        self._last_sent: list[float] = []  # timestamps of sent webhooks
        self._rate_lock = threading.RLock()

    def _check_rate_limit(self) -> bool:
        """Check if we can send a webhook without exceeding rate limit."""
        with self._rate_lock:
            now = time.time()
            # Remove timestamps older than 1 minute
            self._last_sent = [t for t in self._last_sent if now - t < 60]
            if len(self._last_sent) >= self.rate_limit_per_min:
                return False
            self._last_sent.append(now)
            return True

    def send_alert(self, subject: str, body: str) -> bool:
        """Send a webhook alert.
        Returns True if successful, False otherwise.
        """
        if not self.enabled or not self.url:
            _log.warning("Webhook alerts not configured or disabled")
            return False

        if not self._check_rate_limit():
            _log.warning("Webhook rate limit exceeded")
            return False

        try:
            payload = {
                "subject": subject,
                "body": body,
                "timestamp": time.time(),
            }
            headers = {"Content-Type": "application/json"}
            response = requests.post(
                self.url,
                data=json.dumps(payload),
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            _log.info("Webhook alert sent successfully")
            return True
        except (requests.RequestException, OSError, ConnectionError, TimeoutError, ValueError) as e:
            _log.error(f"Failed to send webhook alert: {e}")
            return False


class MultiChannelAlerter:
    """Sends alerts via multiple channels: Telegram, Email, Webhook."""

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.telegram = TelegramEngine(
            bot_token=cfg.get("BOT_TOKEN", ""),
            default_chat_id=cfg.get("CHAT_ID", ""),
            channel_map={},  # Use default channel mapping from TelegramEngine
            enabled=cfg.get("TG_TRADE_ONLY", True),  # Assuming we want trade alerts enabled
        )
        self.email = EmailAlerter(cfg)
        self.webhook = WebhookAlerter(cfg)

    def send_alert(self, subject: str, body: str, telegram_only: bool = False) -> dict[str, bool]:
        """Send an alert via all configured channels.
        Returns a dictionary with channel names as keys and boolean success as values.
        If telegram_only is True, only sends via Telegram (used for trade alerts).
        """
        results = {}

        # Always send via Telegram if enabled (unless telegram_only is False we still send via Telegram)
        try:
            # We assume the body is already formatted for Telegram by the caller
            # For simplicity, we'll send the same body to Telegram
            # In a real system, you might want different formatting per channel
            tg_success = self.telegram.send_raw(body, critical=True)
            results["telegram"] = tg_success
        except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as e:
            _log.error(f"Failed to send Telegram alert: {e}")
            results["telegram"] = False

        if not telegram_only:
            # Send via Email
            try:
                email_success = self.email.send_alert(subject, body)
                results["email"] = email_success
            except (smtplib.SMTPException, OSError, ConnectionError, TimeoutError) as e:
                _log.error(f"Failed to send Email alert: {e}")
                results["email"] = False

            # Send via Webhook
            try:
                webhook_success = self.webhook.send_alert(subject, body)
                results["webhook"] = webhook_success
            except (requests.RequestException, OSError, ConnectionError, TimeoutError) as e:
                _log.error(f"Failed to send Webhook alert: {e}")
                results["webhook"] = False

        return results


__all__ = [
    "EmailAlerter",
    "MultiChannelAlerter",
    "WebhookAlerter",
]

