"""
Telegram Notification Adapter

Implements the NotificationPort interface using the existing TelegramEngine
to provide a clean abstraction layer for Telegram notifications.
"""

from __future__ import annotations

import logging
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

# Try to import the existing TelegramEngine
try:
    from core.legacy.telegram_engine import TelegramEngine
    TELEGRAM_ENGINE_AVAILABLE = True
except ImportError:
    TELEGRAM_ENGINE_AVAILABLE = False
    logger.warning("TelegramEngine not available, Telegram notifications will be disabled")


class TelegramNotificationAdapter(NotificationPort):
    """
    Telegram notification adapter that wraps the existing TelegramEngine.

    This adapter provides a clean interface that conforms to the NotificationPort
    while leveraging the existing sophisticated Telegram alerting logic.
    """

    def __init__(
        self,
        bot_token: str,
        default_chat_id: str,
        channel_map: dict[str, str] | None = None,
        cooldown_seconds: int = 900,  # 15 minutes
        rate_limit: int = 20,         # messages per minute
        rate_window: int = 60,        # 60 second window
        send_timeout: int = 10,
        pin_timeout: int = 10,
        enabled: bool = True
    ):
        """
        Initialize the Telegram notification adapter.

        Args:
            bot_token: Telegram bot token
            default_chat_id: Default chat ID to send messages to
            channel_map: Mapping of categories to chat IDs
            cooldown_seconds: Cooldown period between similar messages
            rate_limit: Maximum messages per rate_window
            rate_window: Time window for rate limiting (seconds)
            send_timeout: Timeout for sending messages
            pin_timeout: Timeout for pinning messages
            enabled: Whether the adapter is enabled
        """
        if not TELEGRAM_ENGINE_AVAILABLE:
            raise ImportError("TelegramEngine is not available")

        self.bot_token = bot_token
        self.default_chat_id = default_chat_id
        self.enabled = enabled

        # Initialize the underlying Telegram engine
        self._telegram_engine = TelegramEngine(
            bot_token=bot_token,
            default_chat_id=default_chat_id,
            channel_map=channel_map or {},
            cooldown_seconds=cooldown_seconds,
            rate_limit=rate_limit,
            rate_window=rate_window,
            send_timeout=send_timeout,
            pin_timeout=pin_timeout,
            enabled=enabled
        )

        logger.info("TelegramNotificationAdapter initialized")

    def send_notification(self, notification: Notification) -> NotificationResult:
        """
        Send a single notification via Telegram.

        Args:
            notification: The notification to send

        Returns:
            NotificationResult indicating success or failure
        """
        if not self.enabled:
            return NotificationResult(
                notification_id="disabled",
                status=NotificationStatus.FAILED,
                channel=NotificationChannel.TELEGRAM,
                timestamp=now_ist(),
                error_message="Telegram notifications are disabled"
            )

        if notification.channel != NotificationChannel.TELEGRAM:
            return NotificationResult(
                notification_id="wrong_channel",
                status=NotificationStatus.FAILED,
                channel=notification.channel,
                timestamp=now_ist(),
                error_message=f"Expected TELEGRAM channel, got {notification.channel}"
            )

        try:
            # Convert our Notification to the format expected by TelegramEngine
            signal_dict = self._notification_to_signal(notification)

            # Send using the existing Telegram engine
            sent = self._telegram_engine.send_signal_alert(signal_dict)

            if sent:
                return NotificationResult(
                    notification_id=f"tg_{now_ist().timestamp()}",
                    status=NotificationStatus.SENT,
                    channel=NotificationChannel.TELEGRAM,
                    timestamp=now_ist()
                )
            else:
                return NotificationResult(
                    notification_id=f"tg_{now_ist().timestamp()}",
                    status=NotificationStatus.FAILED,
                    channel=NotificationChannel.TELEGRAM,
                    timestamp=now_ist(),
                    error_message="Failed to send Telegram notification"
                )

        except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as e:
            logger.error(f"Error sending Telegram notification: {e}")
            return NotificationResult(
                notification_id=f"tg_error_{now_ist().timestamp()}",
                status=NotificationStatus.FAILED,
                channel=NotificationChannel.TELEGRAM,
                timestamp=now_ist(),
                error_message=str(e)
            )

    def send_notifications(
        self,
        notifications: list[Notification]
    ) -> list[NotificationResult]:
        """
        Send multiple notifications via Telegram.

        Args:
            notifications: List of notifications to send

        Returns:
            List of NotificationResults corresponding to each notification
        """
        results = []
        for notification in notifications:
            result = self.send_notification(notification)
            results.append(result)
        return results

    def is_channel_available(self, channel: NotificationChannel) -> bool:
        """
        Check if Telegram channel is available/configured.

        Args:
            channel: The channel to check

        Returns:
            True if channel is available, False otherwise
        """
        if channel != NotificationChannel.TELEGRAM:
            return False

        return self.enabled and TELEGRAM_ENGINE_AVAILABLE and self._telegram_engine is not None

    def get_rate_limit_status(self, channel: NotificationChannel) -> dict[str, Any]:
        """
        Get current rate limit status for Telegram channel.

        Args:
            channel: The channel to check

        Returns:
            Dictionary containing rate limit information
        """
        if channel != NotificationChannel.TELEGRAM:
            return {"error": "Invalid channel"}

        # Return basic rate limit info - would need to enhance TelegramEngine to expose this
        return {
            "channel": "telegram",
            "enabled": self.enabled,
            "engine_available": TELEGRAM_ENGINE_AVAILABLE,
            "note": "Detailed rate limit stats would require enhancements to TelegramEngine"
        }

    def _notification_to_signal(self, notification: Notification) -> dict:
        """
        Convert our internal Notification format to the signal dict format
        expected by the TelegramEngine.

        Args:
            notification: The notification to convert

        Returns:
            Dictionary in the format expected by TelegramEngine.send_signal_alert
        """
        # Extract basic info
        signal = {
            "symbol": notification.recipient or "UNKNOWN",
            "signal": "BUY" if "BUY" in notification.message.upper() else "SELL" if "SELL" in notification.message.upper() else "ALERT",
            "price": 0.0,  # Would need to parse from message
            "strength": "STRONG" if notification.priority == NotificationPriority.CRITICAL else
                       "MODERATE" if notification.priority == NotificationPriority.HIGH else "WEAK",
            "direction": "BUY" if "BUY" in notification.message.upper() else "SELL" if "SELL" in notification.message.upper() else "NONE",
            "timestamp": notification.timestamp.strftime("%d-%b-%Y %H:%M:%S"),
            "sector": notification.metadata.get("sector", "GENERAL"),
            "category": notification.metadata.get("category", "DEFAULT"),
            "score": 50,  # Default score
            "message": notification.message
        }

        # Add metadata fields that TelegramEngine might use
        signal.update(notification.metadata)

        return signal
