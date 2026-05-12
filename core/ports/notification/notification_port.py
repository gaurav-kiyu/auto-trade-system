"""
Notification Port Interface

This interface defines the contract that all notification services must implement.
It provides a unified way to send notifications through different channels (Telegram, email, etc.)
with support for rate limiting, fallback mechanisms, and priority-based queuing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any


class NotificationChannel(Enum):
    """Supported notification channels."""
    TELEGRAM = "telegram"
    EMAIL = "email"
    SMS = "sms"
    WEBHOOK = "webhook"
    IN_APP = "in_app"


class NotificationPriority(Enum):
    """Notification priority levels."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


class NotificationStatus(Enum):
    """Notification delivery status."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"


class Notification:
    """Data model for a notification."""

    def __init__(
        self,
        message: str,
        channel: NotificationChannel,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        recipient: str | None = None,
        subject: str | None = None,
        metadata: dict[str, Any] | None = None,
        timestamp: datetime | None = None
    ):
        self.message = message
        self.channel = channel
        self.priority = priority
        self.recipient = recipient
        self.subject = subject
        self.metadata = metadata or {}
        self.timestamp = timestamp or datetime.now()
        self.status = NotificationStatus.PENDING
        self.error_message: str | None = None


class NotificationResult:
    """Result of a notification sending operation."""

    def __init__(
        self,
        notification_id: str,
        status: NotificationStatus,
        channel: NotificationChannel,
        timestamp: datetime,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None
    ):
        self.notification_id = notification_id
        self.status = status
        self.channel = channel
        self.timestamp = timestamp
        self.error_message = error_message
        self.metadata = metadata or {}


class NotificationPort(ABC):
    """
    Abstract base class for notification services.

    All notification implementations (Telegram, email, etc.) must inherit from this class
    and implement the required methods.
    """

    @abstractmethod
    def send_notification(self, notification: Notification) -> NotificationResult:
        """
        Send a notification through the specified channel.

        Args:
            notification: The notification to send

        Returns:
            NotificationResult indicating success or failure
        """
        pass

    @abstractmethod
    def send_notifications(
        self,
        notifications: list[Notification]
    ) -> list[NotificationResult]:
        """
        Send multiple notifications.

        Args:
            notifications: List of notifications to send

        Returns:
            List of NotificationResults corresponding to each notification
        """
        pass

    @abstractmethod
    def is_channel_available(self, channel: NotificationChannel) -> bool:
        """
        Check if a notification channel is available/configured.

        Args:
            channel: The channel to check

        Returns:
            True if channel is available, False otherwise
        """
        pass

    @abstractmethod
    def get_rate_limit_status(self, channel: NotificationChannel) -> dict[str, Any]:
        """
        Get current rate limit status for a channel.

        Args:
            channel: The channel to check

        Returns:
            Dictionary containing rate limit information
        """
        pass
