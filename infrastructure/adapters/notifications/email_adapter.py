"""
Email Notification Adapter

Implements the NotificationPort interface using SMTP for email notifications.
Supports TLS encryption, configurable credentials, and rate limiting.
"""

from __future__ import annotations

import logging
import smtplib
import threading
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from core.datetime_ist import now_ist
from core.ports.notification.notification_port import (
    Notification,
    NotificationChannel,
    NotificationPort,
    NotificationPriority,
    NotificationResult,
    NotificationStatus,
)

logger = logging.getLogger(__name__)


class EmailNotificationAdapter(NotificationPort):
    """
    Email notification adapter that sends notifications via SMTP.

    Supports:
    - TLS and STARTTLS encryption
    - HTML and plain text messages
    - Configurable rate limiting
    - Per-recipient delivery
    """

    def __init__(
        self,
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_pass: str = "",
        default_recipient: str = "",
        use_tls: bool = True,
        rate_limit: int = 60,
        rate_window: int = 60,
        enabled: bool = True,
    ):
        """
        Initialize the email notification adapter.

        Args:
            smtp_host: SMTP server hostname
            smtp_port: SMTP server port (587 for TLS, 465 for SSL)
            smtp_user: SMTP authentication username (email address)
            smtp_pass: SMTP authentication password / app password
            default_recipient: Default recipient email address
            use_tls: Whether to use TLS encryption
            rate_limit: Maximum emails per rate_window
            rate_window: Time window for rate limiting (seconds)
            enabled: Whether the adapter is enabled
        """
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_user = smtp_user
        self._smtp_pass = smtp_pass
        self._default_recipient = default_recipient
        self._use_tls = use_tls
        self._enabled = enabled

        # Rate limiting state
        self._rate_limit_lock = threading.Lock()
        self._send_timestamps: list[float] = []
        self._rate_limit = rate_limit
        self._rate_window = rate_window

        # Reusable SMTP connection
        self._smtp_connection: smtplib.SMTP | None = None
        self._connection_lock = threading.Lock()
        self._last_connect: float = 0.0
        self._connect_timeout: float = 30.0  # reconnect after 30s idle

        logger.info(
            "EmailNotificationAdapter initialized (host=%s, port=%s, user=%s, tls=%s, enabled=%s)",
            smtp_host, smtp_port, smtp_user, use_tls, enabled,
        )

    # ── NotificationPort interface ─────────────────────────────────────

    def send_notification(self, notification: Notification) -> NotificationResult:
        """
        Send a single notification via email.

        Args:
            notification: The notification to send

        Returns:
            NotificationResult indicating success or failure
        """
        if not self._enabled:
            return NotificationResult(
                notification_id="disabled",
                status=NotificationStatus.FAILED,
                channel=NotificationChannel.EMAIL,
                timestamp=now_ist(),
                error_message="Email notifications are disabled",
            )

        if notification.channel != NotificationChannel.EMAIL:
            return NotificationResult(
                notification_id="wrong_channel",
                status=NotificationStatus.FAILED,
                channel=notification.channel,
                timestamp=now_ist(),
                error_message=f"Expected EMAIL channel, got {notification.channel}",
            )

        # Resolve recipient
        recipient = notification.recipient or self._default_recipient
        if not recipient:
            return NotificationResult(
                notification_id="no_recipient",
                status=NotificationStatus.FAILED,
                channel=NotificationChannel.EMAIL,
                timestamp=now_ist(),
                error_message="No recipient email address configured",
            )

        # Check rate limit
        if not self._check_rate_limit():
            return NotificationResult(
                notification_id="rate_limited",
                status=NotificationStatus.RATE_LIMITED,
                channel=NotificationChannel.EMAIL,
                timestamp=now_ist(),
                error_message="Email rate limit exceeded",
            )

        try:
            subject = notification.subject or self._infer_subject(notification)
            body = notification.message

            # Build email
            msg = MIMEMultipart("alternative")
            msg["From"] = self._smtp_user or "noreply@opbtrading.com"
            msg["To"] = recipient
            msg["Subject"] = subject

            # Plain text part
            msg.attach(MIMEText(body, "plain", "utf-8"))

            # HTML part for richer notifications
            html_body = self._to_html(body, notification)
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            # Send
            self._send_smtp(self._smtp_user or "noreply@opbtrading.com", recipient, msg)

            notification_id = f"email_{recipient}_{int(time.time())}"
            return NotificationResult(
                notification_id=notification_id,
                status=NotificationStatus.SENT,
                channel=NotificationChannel.EMAIL,
                timestamp=now_ist(),
            )

        except smtplib.SMTPAuthenticationError as e:
            logger.error("SMTP authentication failed: %s", e)
            return NotificationResult(
                notification_id="auth_error",
                status=NotificationStatus.FAILED,
                channel=NotificationChannel.EMAIL,
                timestamp=now_ist(),
                error_message=f"SMTP authentication failed: {e}",
            )
        except smtplib.SMTPException as e:
            logger.error("SMTP error sending email: %s", e)
            # Reset connection on SMTP errors
            self._reset_connection()
            return NotificationResult(
                notification_id="smtp_error",
                status=NotificationStatus.FAILED,
                channel=NotificationChannel.EMAIL,
                timestamp=now_ist(),
                error_message=f"SMTP error: {e}",
            )
        except (smtplib.SMTPException, OSError, ConnectionError, TimeoutError, ValueError) as e:
            logger.error("Error sending email notification: %s", e)
            return NotificationResult(
                notification_id="error",
                status=NotificationStatus.FAILED,
                channel=NotificationChannel.EMAIL,
                timestamp=now_ist(),
                error_message=str(e),
            )

    def send_notifications(
        self,
        notifications: list[Notification],
    ) -> list[NotificationResult]:
        """Send multiple notifications via email."""
        results = []
        for notification in notifications:
            results.append(self.send_notification(notification))
        return results

    def is_channel_available(self, channel: NotificationChannel) -> bool:
        """Check if email channel is available/configured."""
        if channel != NotificationChannel.EMAIL:
            return False
        return (
            self._enabled
            and bool(self._smtp_host)
            and bool(self._smtp_user)
            and bool(self._smtp_pass)
        )

    def get_rate_limit_status(self, channel: NotificationChannel) -> dict[str, Any]:
        """Get current rate limit status for email channel."""
        if channel != NotificationChannel.EMAIL:
            return {"error": "Invalid channel"}

        with self._rate_limit_lock:
            now = time.time()
            window_start = now - self._rate_window
            recent = [t for t in self._send_timestamps if t > window_start]

            return {
                "channel": "email",
                "enabled": self._enabled,
                "rate_limit": self._rate_limit,
                "rate_window_seconds": self._rate_window,
                "sent_in_window": len(recent),
                "remaining": max(0, self._rate_limit - len(recent)),
            }

    # ── Private helpers ────────────────────────────────────────────────

    def _check_rate_limit(self) -> bool:
        """Check if we're within the rate limit window."""
        with self._rate_limit_lock:
            now = time.time()
            window_start = now - self._rate_window

            # Prune old entries
            self._send_timestamps = [t for t in self._send_timestamps if t > window_start]

            if len(self._send_timestamps) >= self._rate_limit:
                return False

            self._send_timestamps.append(now)
            return True

    def _get_connection(self) -> smtplib.SMTP:
        """Get or create a reusable SMTP connection."""
        with self._connection_lock:
            now = time.time()

            # Check if existing connection is stale
            if self._smtp_connection is not None:
                if now - self._last_connect > self._connect_timeout:
                    try:
                        self._smtp_connection.quit()
                    except (smtplib.SMTPException, OSError):
                        pass
                    self._smtp_connection = None

            # Create new connection if needed
            if self._smtp_connection is None:
                self._smtp_connection = self._connect()
                self._last_connect = now

            return self._smtp_connection

    def _connect(self) -> smtplib.SMTP:
        """Establish a new SMTP connection with TLS."""
        try:
            server = smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=10)
            server.ehlo()
            if self._use_tls:
                server.starttls()
                server.ehlo()
            if self._smtp_user and self._smtp_pass:
                server.login(self._smtp_user, self._smtp_pass)
            logger.debug("SMTP connection established to %s:%s", self._smtp_host, self._smtp_port)
            return server
        except (smtplib.SMTPException, OSError, ConnectionError, TimeoutError, ValueError) as e:
            logger.error("Failed to connect to SMTP server %s:%s: %s", self._smtp_host, self._smtp_port, e)
            raise

    def _send_smtp(self, from_addr: str, to_addr: str, msg: MIMEMultipart) -> None:
        """Send the email via SMTP, with auto-reconnect on failure."""
        try:
            server = self._get_connection()
            server.sendmail(from_addr, [to_addr], msg.as_string())
            logger.debug("Email sent to %s (subject: %s)", to_addr, msg["Subject"])
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPException):
            # Reconnect and retry once
            self._reset_connection()
            server = self._get_connection()
            server.sendmail(from_addr, [to_addr], msg.as_string())

    def _reset_connection(self) -> None:
        """Reset the SMTP connection (called on errors)."""
        with self._connection_lock:
            if self._smtp_connection is not None:
                try:
                    self._smtp_connection.quit()
                except (smtplib.SMTPException, OSError, ConnectionError):
                    pass
                self._smtp_connection = None
            self._last_connect = 0.0

    def _infer_subject(self, notification: Notification) -> str:
        """Infer an email subject from the notification context."""
        prefix_map = {
            NotificationPriority.CRITICAL: "[CRITICAL] ",
            NotificationPriority.HIGH: "[HIGH] ",
            NotificationPriority.NORMAL: "",
            NotificationPriority.LOW: "[LOW] ",
        }
        prefix = prefix_map.get(notification.priority, "")

        # Extract a short summary from the message (first line or first 80 chars)
        first_line = notification.message.split("\n")[0].strip()
        summary = first_line[:80] if len(first_line) > 80 else first_line
        return f"{prefix}OPB Trading Notification - {summary}"

    def _to_html(self, body: str, notification: Notification) -> str:
        """Convert plain text body to a simple HTML email."""
        # Escape HTML entities
        html_body = (
            body.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>\n")
        )

        priority_colors = {
            NotificationPriority.CRITICAL: "#dc3545",
            NotificationPriority.HIGH: "#fd7e14",
            NotificationPriority.NORMAL: "#0d6efd",
            NotificationPriority.LOW: "#6c757d",
        }
        border_color = priority_colors.get(notification.priority, "#0d6efd")

        return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:600px;margin:20px auto;border:1px solid #ddd;border-top:3px solid {border_color};border-radius:6px;overflow:hidden;">
<div style="padding:16px 24px;background:#f8f9fa;border-bottom:1px solid #eee;">
<h2 style="margin:0;font-size:16px;color:#333;">OPB Trading Bot</h2>
</div>
<div style="padding:20px 24px;font-size:14px;line-height:1.6;color:#333;">
{html_body}
</div>
<div style="padding:12px 24px;background:#f8f9fa;border-top:1px solid #eee;font-size:11px;color:#888;text-align:center;">
This is an automated notification from your Options Buying Bot. Do not reply.
</div>
</div>
</body>
</html>"""
