"""
Notification Service

Implements a complete notification service that handles Telegram messaging
with fallback mechanisms, rate limiting, and priority-based queuing.
This service provides a clean interface for sending notifications throughout
the trading system.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from queue import Empty, PriorityQueue
from threading import Event, Thread

from core.datetime_ist import now_ist

# Import the new LoggingService
from core.logging import LoggingService
from core.ports.notification.notification_port import (
    Notification,
    NotificationChannel,
    NotificationPort,
    NotificationPriority,
    NotificationResult,
    NotificationStatus,
)
from infrastructure.adapters.notifications.email_adapter import EmailNotificationAdapter
from infrastructure.adapters.notifications.telegram_adapter import TelegramNotificationAdapter


class ServiceStatus(Enum):
    """Service operational status."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class QueuedNotification:
    """Notification wrapper for priority queuing."""
    priority: int
    timestamp: float
    notification: Notification
    callback: Callable[[NotificationResult], None] | None = None

    def __lt__(self, other):
        # Lower priority number = higher priority
        if self.priority != other.priority:
            return self.priority < other.priority
        # Earlier timestamp = higher priority
        return self.timestamp < other.timestamp


@dataclass
class ServiceMetrics:
    """Service performance metrics."""
    notifications_sent: int = 0
    notifications_failed: int = 0
    notifications_rate_limited: int = 0
    last_notification_time: datetime | None = None
    average_processing_time: float = 0.0
    uptime_seconds: float = 0.0
    start_time: datetime | None = None


class NotificationService:
    """
    Complete notification service with:
    - Multiple channel support (Telegram, email, etc.)
    - Priority-based queuing
    - Rate limiting per channel
    - Fallback mechanisms
    - Async processing
    - Monitoring and metrics
    """

    def __init__(self):
        self._status = ServiceStatus.STOPPED
        self._status_lock = threading.RLock()

        # Initialize logger
        self._logger = LoggingService(
            log_dir="logs",
            log_filename_prefix="notification_service_",
            retain_days=30,
            json_log_file="",
            version="UNKNOWN",
            enable_correlation_ids=True,
            enable_contextual_logging=True
        )

        # Channel adapters
        self._adapters: dict[NotificationChannel, NotificationPort] = {}

        # Notification queues (one per priority level)
        self._queues: dict[NotificationPriority, PriorityQueue] = {
            priority: PriorityQueue() for priority in NotificationPriority
        }

        # Rate limiting tracking
        self._rate_limit_windows: dict[NotificationChannel, list[float]] = {
            channel: [] for channel in NotificationChannel
        }
        self._rate_limit_lock = threading.RLock()

        # Service configuration
        self._config = {
            # Rate limits (notifications per minute)
            "rate_limits": {
                NotificationChannel.TELEGRAM: 20,
                NotificationChannel.EMAIL: 60,
                NotificationChannel.SMS: 30,
                NotificationChannel.WEBHOOK: 100,
                NotificationChannel.IN_APP: 1000
            },
            # Rate window in seconds
            "rate_window_seconds": 60,
            # Max queue size before dropping low priority notifications
            "max_queue_size": 1000,
            # Worker thread count
            "worker_count": 3,
            # Enable fallback channels
            "enable_fallback": True,
            # Fallback channel order (when primary fails)
            "fallback_channels": {
                NotificationChannel.TELEGRAM: [
                    NotificationChannel.EMAIL,
                    NotificationChannel.IN_APP
                ],
                NotificationChannel.EMAIL: [
                    NotificationChannel.IN_APP,
                    NotificationChannel.SMS
                ],
                NotificationChannel.SMS: [
                    NotificationChannel.IN_APP
                ],
                NotificationChannel.WEBHOOK: [
                    NotificationChannel.IN_APP
                ],
                NotificationChannel.IN_APP: []  # No fallback for in-app
            }
        }

        # Worker threads
        self._workers: list[Thread] = []
        self._stop_event = Event()

        # Metrics
        self._metrics = ServiceMetrics()
        self._metrics_lock = threading.RLock()

        self._logger.info("NotificationService initialized")

    def start(self) -> bool:
        """Start the notification service."""
        with self._status_lock:
            if self._status == ServiceStatus.RUNNING:
                self._logger.warning("Notification service is already running")
                return True

            if self._status in (ServiceStatus.STARTING, ServiceStatus.STOPPING):
                self._logger.warning("Notification service is already %s", self._status.value)
                return False

            self._status = ServiceStatus.STARTING

        try:
            self._logger.info("Starting notification service...")

            # Initialize default adapters
            self._initialize_default_adapters()

            # Reset stop event
            self._stop_event.clear()

            # Start worker threads
            self._start_workers()

            # Update metrics
            with self._metrics_lock:
                self._metrics.start_time = now_ist()
                self._metrics.status = ServiceStatus.RUNNING.value

            self._status = ServiceStatus.RUNNING
            self._logger.info("Notification service started successfully")
            return True

        except Exception as e:
            self._logger.error(f"Failed to start notification service: {e}")
            self._status = ServiceStatus.ERROR
            return False

    def stop(self) -> bool:
        """Stop the notification service."""
        with self._status_lock:
            if self._status == ServiceStatus.STOPPED:
                self._logger.warning("Notification service is already stopped")
                return True

            if self._status == ServiceStatus.STOPPING:
                self._logger.warning("Notification service is already stopping")
                return False

            self._status = ServiceStatus.STOPPING

        try:
            self._logger.info("Stopping notification service...")

            # Signal workers to stop
            self._stop_event.set()

            # Wait for workers to finish
            for worker in self._workers:
                worker.join(timeout=5.0)

            self._workers.clear()

            # Update metrics
            with self._metrics_lock:
                if self._metrics.start_time:
                    self._metrics.uptime_seconds = (
                        now_ist() - self._metrics.start_time
                    ).total_seconds()

            self._status = ServiceStatus.STOPPED
            self._logger.info("Notification service stopped")
            return True

        except Exception as e:
            self._logger.error(f"Error stopping notification service: {e}")
            self._status = ServiceStatus.ERROR
            return False

    def send_notification(
        self,
        notification: Notification,
        blocking: bool = False,
        timeout: float | None = None
    ) -> NotificationResult | None:
        """
        Send a notification.

        Args:
            notification: The notification to send
            blocking: If True, wait for result; if False, return immediately
            timeout: Maximum time to wait for blocking call (seconds)

        Returns:
            NotificationResult if blocking=True, None if blocking=False
        """
        if self._status != ServiceStatus.RUNNING:
            self._logger.warning("Cannot send notification - service is %s", self._status.value)
            if blocking:
                return NotificationResult(
                    notification_id="service_not_running",
                    status=NotificationStatus.FAILED,
                    channel=notification.channel,
                    timestamp=now_ist(),
                    error_message=f"Notification service is {self._status.value}"
                )
            return None

        # Add to appropriate priority queue
        priority_queue = self._queues[notification.priority]

        # Check queue size limits
        total_queued = sum(q.qsize() for q in self._queues.values())
        if total_queued >= self._config["max_queue_size"]:
            # Drop lowest priority notifications if queue is full
            if notification.priority == NotificationPriority.LOW:
                self._logger.warning("Dropping low priority notification due to queue limits")
                if blocking:
                    return NotificationResult(
                        notification_id="queue_full",
                        status=NotificationStatus.FAILED,
                        channel=notification.channel,
                        timestamp=now_ist(),
                        error_message="Notification queue is full"
                    )
                return None

        queued_notif = QueuedNotification(
            priority=notification.priority.value,
            timestamp=time.time(),
            notification=notification
        )

        priority_queue.put(queued_notif)
        self._logger.debug(
            "Queued %s notification (priority: %s, queue size: %d)",
            notification.channel.value,
            notification.priority.name,
            priority_queue.qsize()
        )

        if blocking:
            # For blocking calls, we need to process immediately
            return self._process_notification(notification)

        return None

    def send_notifications(
        self,
        notifications: list[Notification],
        blocking: bool = False
    ) -> list[NotificationResult]:
        """
        Send multiple notifications.

        Args:
            notifications: List of notifications to send
            blocking: If True, wait for all results; if False, return immediately

        Returns:
            List of NotificationResults if blocking=True, empty list if blocking=False
        """
        if blocking:
            results = []
            for notification in notifications:
                result = self.send_notification(notification, blocking=True)
                results.append(result)
            return results
        else:
            for notification in notifications:
                self.send_notification(notification, blocking=False)
            return []

    def get_service_status(self) -> ServiceStatus:
        """Get current service status."""
        with self._status_lock:
            return self._status

    def get_metrics(self) -> ServiceMetrics:
        """Get service performance metrics."""
        with self._metrics_lock:
            # Update uptime if running
            if (self._status == ServiceStatus.RUNNING and
                self._metrics.start_time):
                self._metrics.uptime_seconds = (
                    now_ist() - self._metrics.start_time
                ).total_seconds()
            return ServiceMetrics(
                notifications_sent=self._metrics.notifications_sent,
                notifications_failed=self._metrics.notifications_failed,
                notifications_rate_limited=self._metrics.notifications_rate_limited,
                last_notification_time=self._metrics.last_notification_time,
                average_processing_time=self._metrics.average_processing_time,
                uptime_seconds=self._metrics.uptime_seconds,
                start_time=self._metrics.start_time
            )

    def get_queue_sizes(self) -> dict[NotificationPriority, int]:
        """Get current queue sizes for each priority level."""
        return {
            priority: queue.qsize()
            for priority, queue in self._queues.items()
        }

    def _initialize_default_adapters(self):
        """Initialize default notification adapters."""
        # Try to initialize Telegram adapter if credentials are available
        try:
            # In a real implementation, these would come from secure config
            bot_token = "placeholder_bot_token"  # Would be from secure config
            default_chat_id = "placeholder_chat_id"  # Would be from secure config

            if bot_token and default_chat_id and bot_token != "placeholder_bot_token":
                telegram_adapter = TelegramNotificationAdapter(
                    bot_token=bot_token,
                    default_chat_id=default_chat_id
                )
                self._adapters[NotificationChannel.TELEGRAM] = telegram_adapter
                self._logger.info("Telegram notification adapter initialized")
            else:
                self._logger.info("Telegram credentials not configured - Telegram notifications disabled")
        except Exception as e:
            self._logger.warning(f"Could not initialize Telegram adapter: {e}")

        # Initialize email adapter if SMTP credentials are configured
        try:
            # These values would ideally come from secure config / environment variables
            # Defaults match index_config.defaults.json EMAIL_* keys
            smtp_host = os.environ.get("OPBUYING_EMAIL_SMTP", "smtp.gmail.com")
            smtp_port = int(os.environ.get("OPBUYING_EMAIL_PORT", "587"))
            smtp_user = os.environ.get("OPBUYING_EMAIL_USER", "")
            smtp_pass = os.environ.get("OPBUYING_EMAIL_PASS", "")
            smtp_to = os.environ.get("OPBUYING_EMAIL_TO", "")
            email_enabled = os.environ.get("OPBUYING_EMAIL_ENABLED", "false").lower() == "true"

            if smtp_user and smtp_pass and email_enabled:
                email_adapter = EmailNotificationAdapter(
                    smtp_host=smtp_host,
                    smtp_port=smtp_port,
                    smtp_user=smtp_user,
                    smtp_pass=smtp_pass,
                    default_recipient=smtp_to,
                    enabled=True,
                )
                self._adapters[NotificationChannel.EMAIL] = email_adapter
                self._logger.info(
                    "Email notification adapter initialized (host=%s, user=%s, to=%s)",
                    smtp_host, smtp_user, smtp_to or "default",
                )
            else:
                self._logger.info(
                    "Email credentials not configured (OPBUYING_EMAIL_USER/PASS) "
                    "or EMAIL_ENABLED=false - email notifications disabled"
                )
        except Exception as e:
            self._logger.warning("Could not initialize email adapter: %s", e)

        # Placeholder for future adapters (SMS, webhook, etc.)

    def _start_workers(self):
        """Start worker threads for processing notifications."""
        worker_count = self._config["worker_count"]

        for i in range(worker_count):
            worker = Thread(
                target=self._worker_loop,
                name=f"NotificationWorker-{i}",
                daemon=True
            )
            worker.start()
            self._workers.append(worker)

        self._logger.info("Started %d notification worker threads", worker_count)

    def _worker_loop(self):
        """Main worker loop for processing notifications."""
        self._logger.debug("Notification worker started")

        while not self._stop_event.is_set():
            try:
                # Process queues in priority order (CRITICAL first)
                notification_to_process = None

                # Check queues from highest to lowest priority
                for priority in sorted(NotificationPriority, key=lambda p: p.value, reverse=True):
                    queue = self._queues[priority]
                    try:
                        # Try to get a notification with short timeout to check for stop signal
                        queued_notif = queue.get(timeout=0.1)
                        notification_to_process = queued_notif.notification
                        queue.task_done()
                        break
                    except Empty:
                        continue

                if notification_to_process is None:
                    # No notifications available, wait briefly (interruptible via stop_event)
                    if self._stop_event.wait(0.1):
                        break
                    continue

                # Process the notification
                start_time = time.time()
                result = self._process_notification(notification_to_process)
                processing_time = time.time() - start_time

                # Update metrics
                with self._metrics_lock:
                    if result.status == NotificationStatus.SENT:
                        self._metrics.notifications_sent += 1
                    elif result.status == NotificationStatus.FAILED:
                        self._metrics.notifications_failed += 1
                    elif result.status == NotificationStatus.RATE_LIMITED:
                        self._metrics.notifications_rate_limited += 1

                    self._metrics.last_notification_time = result.timestamp

                    # Update average processing time
                    total_processed = (
                        self._metrics.notifications_sent +
                        self._metrics.notifications_failed +
                        self._metrics.notifications_rate_limited
                    )
                    if total_processed > 0:
                        self._metrics.average_processing_time = (
                            (self._metrics.average_processing_time * (total_processed - 1) + processing_time) /
                            total_processed
                        )

                # Call callback if provided
                # Note: In a full implementation, we'd need to store callbacks with queued notifications

            except Exception as e:
                self._logger.error(f"Error in notification worker: {e}")
                if self._stop_event.wait(1.0):  # Avoid tight loop on error, interruptible
                    break

        self._logger.debug("Notification worker stopped")

    def _process_notification(self, notification: Notification) -> NotificationResult:
        """
        Process a single notification (attempt to send via primary or fallback channels).

        Args:
            notification: The notification to process

        Returns:
            NotificationResult indicating success or failure
        """
        # Check if primary channel is available
        primary_adapter = self._adapters.get(notification.channel)

        if primary_adapter and primary_adapter.is_channel_available(notification.channel):
            # Check rate limiting
            if self._check_rate_limit(notification.channel):
                # Attempt to send via primary channel
                try:
                    result = primary_adapter.send_notification(notification)
                    if result.status == NotificationStatus.SENT:
                        return result
                    # If primary failed and fallback is enabled, try fallbacks
                except Exception as e:
                    self._logger.error(
                        "Error sending notification via primary channel %s: %s",
                        notification.channel.value, str(e)
                    )

        # Try fallback channels if enabled
        if self._config["enable_fallback"]:
            fallback_channels = self._config["fallback_channels"].get(notification.channel, [])
            for fallback_channel in fallback_channels:
                fallback_adapter = self._adapters.get(fallback_channel)
                if (fallback_adapter and
                    fallback_adapter.is_channel_available(fallback_channel) and
                    self._check_rate_limit(fallback_channel)):

                    try:
                        # Create a fallback notification
                        fallback_notif = Notification(
                            message=f"[FALLBACK] {notification.message}",
                            channel=fallback_channel,
                            priority=notification.priority,
                            recipient=notification.recipient,
                            subject=notification.subject,
                            metadata={**notification.metadata, "original_channel": notification.channel.value},
                            timestamp=notification.timestamp
                        )

                        result = fallback_adapter.send_notification(fallback_notif)
                        if result.status == NotificationStatus.SENT:
                            self._logger.info(
                                "Sent notification via fallback channel %s after primary %s failed",
                                fallback_channel.value, notification.channel.value
                            )
                            return result
                    except Exception as e:
                        self._logger.error(
                            "Error sending notification via fallback channel %s: %s",
                            fallback_channel.value, str(e)
                        )
                        continue

        # If we get here, all attempts failed
        return NotificationResult(
            notification_id=f"failed_{int(time.time())}",
            status=NotificationStatus.FAILED,
            channel=notification.channel,
            timestamp=now_ist(),
            error_message="All notification channels failed or unavailable"
        )

    def _check_rate_limit(self, channel: NotificationChannel) -> bool:
        """
        Check if we're within rate limits for a channel.

        Args:
            channel: The channel to check

        Returns:
            True if within rate limit, False otherwise
        """
        with self._rate_limit_lock:
            now = time.time()
            window_start = now - self._config["rate_window_seconds"]

            # Clean old entries
            self._rate_limit_windows[channel] = [
                t for t in self._rate_limit_windows[channel] if t > window_start
            ]

            # Check if we're at the limit
            rate_limit = self._config["rate_limits"].get(channel, 0)
            if len(self._rate_limit_windows[channel]) >= rate_limit:
                return False

            # Add current timestamp
            self._rate_limit_windows[channel].append(now)
            return True
