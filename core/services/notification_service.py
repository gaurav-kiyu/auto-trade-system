"""Notification Service

Implements a complete notification service that handles Telegram messaging
with fallback mechanisms, rate limiting, and priority-based queuing.
This service provides a clean interface for sending notifications throughout
the trading system.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

__all__ = [
    "NotificationService",
    "QueuedNotification",
    "ServiceMetrics",
    "ServiceStatus",
    "get_notification_service",
    "reset_notification_service",
]
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from queue import Empty, PriorityQueue
from threading import Event, Thread

from infrastructure.adapters.notifications.email_adapter import EmailNotificationAdapter
from infrastructure.adapters.notifications.telegram_adapter import TelegramNotificationAdapter

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
    """Complete notification service with:
    - Multiple channel support (Telegram, email, etc.)
    - Priority-based queuing
    - Rate limiting per channel
    - Fallback mechanisms
    - Async processing
    - Monitoring and metrics
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        # Effective config dict, used only by the notification-filter gate
        # in send() (core.notification_filters) -- optional and backward
        # compatible: omitting it (as all pre-existing call sites did)
        # leaves filtering fully off, since notification_filters_enabled
        # defaults to False and cfg.get() on an empty dict returns that
        # default.
        self._cfg: dict[str, Any] = cfg or {}
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
            enable_contextual_logging=True,
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
                NotificationChannel.IN_APP: 1000,
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
                    NotificationChannel.IN_APP,
                ],
                NotificationChannel.EMAIL: [
                    NotificationChannel.IN_APP,
                    NotificationChannel.SMS,
                ],
                NotificationChannel.SMS: [
                    NotificationChannel.IN_APP,
                ],
                NotificationChannel.WEBHOOK: [
                    NotificationChannel.IN_APP,
                ],
                NotificationChannel.IN_APP: [],  # No fallback for in-app
            },
        }

        # Worker threads
        self._workers: list[Thread] = []
        self._stop_event = Event()

        # Metrics
        self._metrics = ServiceMetrics()
        self._metrics_lock = threading.RLock()

        # Retry & Dead-Letter Queue Configuration (Exponential backoff [5, 15, 45]s)
        self.RETRY_BACKOFF_SECONDS = [5, 15, 45]
        self.MAX_RETRY_ATTEMPTS = 3
        self._watchdog_lock = threading.Lock()
        self._last_delivery_success: datetime | None = None
        self._last_delivery_failure: datetime | None = None
        self._consecutive_failures: int = 0

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
            self._logger.error(f"Failed to start notification service: {e} (type: {type(e).__name__})")
            self._status = ServiceStatus.ERROR
            return False

    @property
    def is_running(self) -> bool:
        """Return True if service is currently RUNNING."""
        return self._status == ServiceStatus.RUNNING

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
            self._logger.error(f"Error stopping notification service: {e} (type: {type(e).__name__})")
            self._status = ServiceStatus.ERROR
            return False

    def send_notification(
        self,
        notification: Notification,
        blocking: bool = False,
        timeout: float | None = None,
    ) -> NotificationResult | None:
        """Send a notification.

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
                    error_message=f"Notification service is {self._status.value}",
                )
            return None

        # Add to appropriate priority queue
        priority_queue = self._queues[notification.priority]

        # Check queue size limits
        total_queued = sum(q.qsize() for q in self._queues.values())
        max_q = int(self._config["max_queue_size"])
        if total_queued >= max_q:
            # Drop lowest priority notifications if queue is full
            if notification.priority == NotificationPriority.LOW:
                self._logger.warning("Dropping low priority notification due to queue limits")
                if blocking:
                    return NotificationResult(
                        notification_id="queue_full",
                        status=NotificationStatus.FAILED,
                        channel=notification.channel,
                        timestamp=now_ist(),
                        error_message="Notification queue is full",
                    )
                return None

        queued_notif = QueuedNotification(
            priority=notification.priority.value,
            timestamp=time.time(),
            notification=notification,
        )

        priority_queue.put(queued_notif)
        self._logger.debug(
            "Queued %s notification (priority: %s, queue size: %d)",
            notification.channel.value,
            notification.priority.name,
            priority_queue.qsize(),
        )

        if blocking:
            # For blocking calls, we need to process immediately
            return self._process_notification(notification)

        return None

    def send_notifications(
        self,
        notifications: list[Notification],
        blocking: bool = False,
    ) -> list[NotificationResult]:
        """Send multiple notifications.

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
                start_time=self._metrics.start_time,
            )

    def get_queue_sizes(self) -> dict[NotificationPriority, int]:
        """Get current queue sizes for each priority level."""
        return {
            priority: queue.qsize()
            for priority, queue in self._queues.items()
        }

    def send(self, message: str, critical: bool = False, **kwargs) -> Any:
        """Direct send method for trading signals and alerts."""
        # Notification filters (TG_QUIET_MODE / TG_TRADE_ONLY /
        # TG_TRADE_ALERTS_STRICT / TG_CACHE_TTL_SEC) -- no-op unless
        # notification_filters_enabled is set; fail-open by design. See
        # core/notification_filters.py for the full precedence rules.
        from core.notification_filters import should_send_notification
        if not should_send_notification(message, critical, self._cfg):
            self._logger.debug("Notification suppressed by filter: %s", message[:80])
            return None

        if self._status != ServiceStatus.RUNNING:
            self.start()

        priority = NotificationPriority.CRITICAL if critical else NotificationPriority.HIGH

        # Try Telegram dispatch
        tg_adapter = self._adapters.get(NotificationChannel.TELEGRAM)
        if tg_adapter is not None:
            try:
                notif = Notification(
                    message=message,
                    channel=NotificationChannel.TELEGRAM,
                    priority=priority,
                    recipient=kwargs.get("chat_id", ""),
                    subject=kwargs.get("subject", "Trading Signal"),
                    metadata=kwargs,
                )
                res = tg_adapter.send_notification(notif)
                if res and res.status == NotificationStatus.SENT:
                    return res
            except Exception as ex:
                self._logger.warning("Telegram direct send failed: %s", ex)

        # Enqueue as standard notification
        notif = Notification(
            message=message,
            channel=NotificationChannel.TELEGRAM,
            priority=priority,
            recipient=kwargs.get("chat_id", ""),
            subject=kwargs.get("subject", "Trading Signal"),
            metadata=kwargs,
        )
        return self.send_notification(notif, blocking=False)

    def send_alert(self, message: str, critical: bool = False, **kwargs) -> Any:
        """Alias for send() compatible with alert routers."""
        return self.send(message, critical=critical, **kwargs)

    def _initialize_default_adapters(self) -> None:
        """Initialize default notification adapters."""
        # Load from .env with override=True and config.json
        cfg = {}
        try:
            import json
            from pathlib import Path

            from dotenv import load_dotenv
            root = Path(__file__).resolve().parent.parent.parent
            env_file = root / ".env"
            if env_file.exists():
                load_dotenv(env_file, override=True)
            cfg_path = root / "json" / "config.json"
            if cfg_path.exists():
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = json.load(f)
        except Exception:
            pass

        # Try to initialize Telegram adapter if credentials are available
        try:
            bot_token = (
                os.environ.get("OPBUYING_TELEGRAM_BOT_TOKEN")
                or os.environ.get("OPBUYING_BOT_TOKEN")
                or os.environ.get("BOT_TOKEN")
                or str(cfg.get("BOT_TOKEN", ""))
            ).strip()
            default_chat_id = (
                os.environ.get("OPBUYING_TELEGRAM_CHAT_ID")
                or os.environ.get("OPBUYING_CHAT_ID")
                or os.environ.get("CHAT_ID")
                or str(cfg.get("CHAT_ID", "1148730533"))
            ).strip()

            if bot_token and default_chat_id:
                telegram_adapter = TelegramNotificationAdapter(
                    bot_token=bot_token,
                    default_chat_id=default_chat_id,
                )
                self._adapters[NotificationChannel.TELEGRAM] = telegram_adapter
                self._logger.info("Telegram notification adapter initialized (Chat ID: %s)", default_chat_id)
            else:
                self._logger.info("Telegram credentials not configured - Telegram notifications disabled")
        except Exception as e:
            self._logger.warning(f"Could not initialize Telegram adapter: {e} (type: {type(e).__name__})")

        # Initialize email adapter if SMTP credentials are configured
        try:
            smtp_host = str(os.environ.get("OPBUYING_EMAIL_SMTP") or cfg.get("EMAIL_SMTP", "smtp.gmail.com")).strip()
            smtp_port = int(os.environ.get("OPBUYING_EMAIL_PORT") or cfg.get("EMAIL_PORT", 587))
            smtp_user = str(os.environ.get("OPBUYING_EMAIL_USER") or cfg.get("EMAIL_USER", "")).strip()
            smtp_pass = str(os.environ.get("OPBUYING_EMAIL_PASS") or cfg.get("EMAIL_PASS", "")).strip()
            smtp_to = str(os.environ.get("OPBUYING_EMAIL_TO") or cfg.get("EMAIL_TO", "")).strip()
            email_enabled = bool(os.environ.get("OPBUYING_EMAIL_ENABLED", "").lower() == "true" or cfg.get("EMAIL_ENABLED", True))

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
                    "or EMAIL_ENABLED=false - email notifications disabled",
                )
        except (OSError, ValueError, TypeError, ConnectionError) as e:
            self._logger.warning("Could not initialize email adapter: %s", e)

        # Placeholder for future adapters (SMS, webhook, etc.)

    def _start_workers(self) -> None:
        """Start worker threads for processing notifications."""
        worker_count = int(self._config["worker_count"])

        for i in range(worker_count):
            worker = Thread(
                target=self._worker_loop,
                name=f"NotificationWorker-{i}",
                daemon=True,
            )
            worker.start()
            self._workers.append(worker)

        retry_worker = Thread(
            target=self._retry_worker_loop,
            name="NotificationRetryWorker",
            daemon=True,
        )
        retry_worker.start()
        self._workers.append(retry_worker)

        self._logger.info("Started %d notification worker threads plus 1 retry worker", worker_count)

    def _retry_worker_loop(self) -> None:
        """Periodic background sweeper for notification_retry_queue."""
        self._logger.debug("Notification retry worker started")
        while not self._stop_event.is_set():
            try:
                self.process_retry_queue(max_items=10)
            except Exception as e:
                self._logger.error("Error in notification retry worker: %s", e)
            if self._stop_event.wait(5.0):
                break
        self._logger.debug("Notification retry worker stopped")

    def _worker_loop(self) -> None:
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
                self._logger.error(f"Error in notification worker: {e} (type: {type(e).__name__})")
                if self._stop_event.wait(1.0):  # Avoid tight loop on error, interruptible
                    break

        self._logger.debug("Notification worker stopped")

    def _process_notification(self, notification: Notification) -> NotificationResult:
        """Process a single notification (attempt to send via primary or fallback channels).

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
                        "Error sending notification via primary channel %s: %s (type: %s)",
                        notification.channel.value, str(e), type(e).__name__,
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
                            timestamp=notification.timestamp,
                        )

                        result = fallback_adapter.send_notification(fallback_notif)
                        if result.status == NotificationStatus.SENT:
                            self._logger.info(
                                "Sent notification via fallback channel %s after primary %s failed",
                                fallback_channel.value, notification.channel.value,
                            )
                            return result
                    except Exception as e:
                        self._logger.error(
                            "Error sending notification via fallback channel %s: %s (type: %s)",
                            fallback_channel.value, str(e), type(e).__name__,
                        )
                        continue

        # If we get here, all attempts failed
        return NotificationResult(
            notification_id=f"failed_{int(time.time())}",
            status=NotificationStatus.FAILED,
            channel=notification.channel,
            timestamp=now_ist(),
            error_message="All notification channels failed or unavailable",
        )

    def _check_rate_limit(self, channel: NotificationChannel) -> bool:
        """Check if we're within rate limits for a channel.

        Args:
            channel: The channel to check

        Returns:
            True if within rate limit, False otherwise

        """
        with self._rate_limit_lock:
            now = time.time()
            rate_win = int(self._config.get("rate_window_seconds", 60))
            window_start = now - rate_win

            # Clean old entries
            self._rate_limit_windows[channel] = [
                t for t in self._rate_limit_windows[channel] if t > window_start
            ]

            # Check if we're at the limit
            rate_limits = self._config.get("rate_limits", {})
            rate_limit = int(rate_limits.get(channel, 0)) if isinstance(rate_limits, dict) else 0
            if len(self._rate_limit_windows[channel]) >= rate_limit:
                return False

            # Add current timestamp
            self._rate_limit_windows[channel].append(now)
            return True

    def dispatch_qualifying_signal(
        self,
        signal: dict[str, Any],
        eligible_users: list[Any] | None = None,
        sync: bool = True,
    ) -> dict[str, Any]:
        """Dispatch qualifying signal (MODERATE or STRONG) to eligible users via independent dual-channel (Telegram AND Email).

        Guarantees:
        - Out-of-band from trade execution (never touches orders, positions, capital, risk gates).
        - Independent channels: Telegram failure does not block Email; Email failure does not undo Telegram.
        - Idempotent: checks SignalTracker.is_signal_delivered to prevent spamming duplicate signals.
        - Auditable: every channel attempt and outcome is durably recorded in `signal_delivery_audit`.
        - Recipient-specific routing: respects user telegram_chat_id and user email.
        """
        if self._status != ServiceStatus.RUNNING:
            self.start()

        results: dict[str, Any] = {
            "signal_id": "",
            "deliveries": {},
            "status": "PROCESSED",
        }

        signal_id = str(signal.get("signal_id") or signal.get("sig_id") or "").strip()
        results["signal_id"] = signal_id
        if not signal_id:
            self._logger.warning("[SIGNAL_NOTIFICATION] Cannot dispatch signal without signal_id: %s", signal.get("symbol"))
            results["status"] = "NO_SIGNAL_ID"
            return results

        # 1. Canonical Tier Validation
        tier = str(signal.get("tier") or signal.get("strength") or "").upper()
        if not tier:
            score_val = signal.get("score") if signal.get("score") is not None else signal.get("raw_score")
            if score_val is not None:
                try:
                    s = float(score_val)
                    if s >= 80.0:
                        tier = "STRONG"
                    elif s >= 70.0:
                        tier = "MODERATE"
                    else:
                        tier = "WEAK"
                except (ValueError, TypeError):
                    pass

        if tier not in ("STRONG", "MODERATE"):
            self._logger.info("[SIGNAL_NOTIFICATION] Signal %s tier %s is not qualifying (MODERATE/STRONG); skipping dispatch", signal_id, tier)
            results["status"] = "NON_QUALIFYING_TIER"
            return results

        sym = str(signal.get("symbol") or "UNKNOWN").upper()
        direction = str(signal.get("direction") or "CALL").upper()
        category = str(signal.get("category") or "INDEX_OPTIONS").upper()
        score = int(signal.get("score") if signal.get("score") is not None else (signal.get("raw_score") or 70))
        entry_price = float(signal.get("entry_price") or signal.get("price") or 0.0)
        sl_price = float(signal.get("stop_loss") or round(entry_price * 0.97, 2))
        t1_price = float(signal.get("target_1") or round(entry_price * 1.04, 2))
        t2_price = float(signal.get("target_2") or round(entry_price * 1.08, 2))
        strategy = str(signal.get("strategy") or signal.get("strategy_name") or "position_service")
        ts_str = str(signal.get("timestamp") or now_ist().strftime("%d-%b-%Y %H:%M:%S IST"))

        # 2. Recipient Resolution
        recipients = list(eligible_users) if eligible_users is not None else []
        try:
            from core.auth.user_signal_permissions import UserPermissionManager
            perm_mgr = UserPermissionManager.get_instance()
            if not recipients:
                recipients = perm_mgr.get_eligible_recipients(category=category, tier=tier, symbol=sym)

            # Defensive guarantee: Ensure Super Admin is always evaluated for qualifying signals
            has_admin = any(getattr(u, "username", str(u)) == "admin" for u in recipients)
            if not has_admin:
                admin_perm = perm_mgr.get_user_permissions("admin")
                if admin_perm and admin_perm.is_active and admin_perm.signals_enabled:
                    admin_tier_ok = (admin_perm.min_signal_tier == "ALL" or
                                     (admin_perm.min_signal_tier == "MODERATE_AND_STRONG" and tier in ("STRONG", "MODERATE")) or
                                     (admin_perm.min_signal_tier == "STRONG_ONLY" and tier == "STRONG"))
                    cat_ok = not admin_perm.allowed_categories or any(c.upper() == category for c in admin_perm.allowed_categories)
                    if admin_tier_ok and cat_ok:
                        recipients.append(admin_perm)
        except Exception as perm_ex:
            self._logger.warning("[SIGNAL_NOTIFICATION] Recipient resolution exception: %s", perm_ex)

        if not recipients:
            self._logger.info("[SIGNAL_NOTIFICATION] No eligible recipients for signal %s (%s %s)", signal_id, sym, tier)
            results["status"] = "NO_RECIPIENTS"
            return results

        # 3. Message Formatting (Fintech standard, zero live trade implication)
        dir_emoji = "🟢" if direction == "CALL" else "🔴" if direction == "PUT" else "⚪"
        tier_emoji = "💎" if tier == "STRONG" else "🟡"
        sep = "─" * 32
        formatted_plain_msg = (
            f"{sep}\n"
            f"🔔 [OPB QUALIFYING SIGNAL]  {dir_emoji}\n"
            f"{sep}\n"
            f"📌 Symbol   : {sym}\n"
            f"💰 Price    : ₹{entry_price:,.2f}\n"
            f"🧭 Direction: {direction}\n"
            f"💪 Strength : {tier} (Score: {score}/100)\n"
            f"{tier_emoji} Tier     : {tier}\n"
            f"📊 Category : {category}\n"
            f"🎯 Strategy : {strategy}\n"
            f"🛑 Stop Loss: ₹{sl_price:,.2f}\n"
            f"🎯 Target 1 : ₹{t1_price:,.2f}\n"
            f"🎯 Target 2 : ₹{t2_price:,.2f}\n"
            f"🆔 Signal ID: {signal_id}\n"
            f"🕒 Time     : {ts_str}\n"
            f"{sep}\n"
            f"⚡ Mode     : PAPER / SIGNAL_ONLY\n"
            f"⚠️  Notification only — no live trade executed.\n"
            f"{sep}"
        )
        email_subject = f"[OPB QUALIFYING SIGNAL] {tier} {sym} {direction} (Score: {score})"

        from core.signals.signal_tracker import SignalTracker
        tracker = SignalTracker.get_instance()

        tg_adapter = self._adapters.get(NotificationChannel.TELEGRAM)
        email_adapter = self._adapters.get(NotificationChannel.EMAIL)

        # 4. Dispatch Loop across Eligible Recipients
        for u in recipients:
            uname = getattr(u, "username", str(u))
            user_deliveries: dict[str, str] = {}
            results["deliveries"][uname] = user_deliveries

            # ── CHANNEL 1: TELEGRAM ─────────────────────────────────────
            tg_enabled = bool(getattr(u, "telegram_enabled", True))
            tg_chat_id = str(
                getattr(u, "telegram_chat_id", "")
                or os.environ.get("OPBUYING_CHAT_ID")
                or os.environ.get("OPBUYING_TELEGRAM_CHAT_ID")
                or os.environ.get("CHAT_ID")
                or self._cfg.get("CHAT_ID", "1148730533")
            ).strip()

            if not tg_enabled:
                tracker.record_delivery_attempt(
                    signal_id=signal_id,
                    username=uname,
                    channel="TELEGRAM",
                    destination=tg_chat_id,
                    attempted=False,
                    status="DISABLED",
                    error_message="User telegram_enabled is false",
                )
                user_deliveries["TELEGRAM"] = "DISABLED"
            elif not tg_chat_id:
                tracker.record_delivery_attempt(
                    signal_id=signal_id,
                    username=uname,
                    channel="TELEGRAM",
                    destination="",
                    attempted=False,
                    status="NO_DESTINATION",
                    error_message="No telegram chat_id configured",
                )
                user_deliveries["TELEGRAM"] = "NO_DESTINATION"
            elif tracker.is_signal_delivered(signal_id, uname, "TELEGRAM"):
                self._logger.info("[SIGNAL_DEDUP] Telegram already delivered for %s/%s; suppressing duplicate", signal_id, uname)
                user_deliveries["TELEGRAM"] = "ALREADY_DELIVERED"
            else:
                audit_id = tracker.record_delivery_attempt(
                    signal_id=signal_id,
                    username=uname,
                    channel="TELEGRAM",
                    destination=tg_chat_id,
                    attempted=True,
                    status="ATTEMPTED",
                )
                tg_avail = tg_adapter is not None and (
                    getattr(tg_adapter, "enabled", False)
                    or getattr(tg_adapter, "_enabled", False)
                    or (hasattr(tg_adapter, "is_channel_available") and tg_adapter.is_channel_available(NotificationChannel.TELEGRAM))
                )
                if not tg_avail:
                    err_msg = "Telegram adapter is not enabled or not configured"
                    tracker.update_delivery_status(audit_id, "FAILED", error_message=err_msg)
                    self._logger.error("[SIGNAL_NOTIFICATION] signal_id=%s recipient=%s channel=TELEGRAM status=FAILED error=%s", signal_id, uname, err_msg)
                    with self._watchdog_lock:
                        self._last_delivery_failure = now_ist()
                        self._consecutive_failures += 1
                    tracker.enqueue_notification_retry(
                        signal_id=signal_id,
                        username=uname,
                        channel="TELEGRAM",
                        destination=tg_chat_id,
                        payload={
                            "signal": signal,
                            "custom_message": formatted_plain_msg,
                            "subject": email_subject,
                            "priority": "CRITICAL" if tier == "STRONG" else "HIGH",
                        },
                        error_message=err_msg,
                        max_attempts=self.MAX_RETRY_ATTEMPTS,
                        delay_seconds=self.RETRY_BACKOFF_SECONDS[0],
                    )
                    user_deliveries["TELEGRAM"] = "FAILED"
                else:
                    try:
                        tg_notif = Notification(
                            message=formatted_plain_msg,
                            channel=NotificationChannel.TELEGRAM,
                            priority=NotificationPriority.CRITICAL if tier == "STRONG" else NotificationPriority.HIGH,
                            recipient=tg_chat_id,
                            subject=email_subject,
                            metadata={
                                "signal_id": signal_id,
                                "symbol": sym,
                                "direction": direction,
                                "price": entry_price,
                                "score": score,
                                "tier": tier,
                                "strength": tier,
                                "stop_loss": sl_price,
                                "tp1": t1_price,
                                "tp2": t2_price,
                                "chat_id": tg_chat_id,
                                "category": category,
                                "strategy": strategy,
                                "custom_message": formatted_plain_msg,
                            },
                        )
                        tg_res = tg_adapter.send_notification(tg_notif)
                        if tg_res and getattr(tg_res, "status", None) == NotificationStatus.SENT:
                            tracker.update_delivery_status(audit_id, "SENT")
                            with self._watchdog_lock:
                                self._last_delivery_success = now_ist()
                                self._consecutive_failures = 0
                            self._logger.info("[SIGNAL_NOTIFICATION] signal_id=%s recipient=%s channel=TELEGRAM status=SENT", signal_id, uname)
                            user_deliveries["TELEGRAM"] = "SENT"
                        else:
                            err_msg = str(getattr(tg_res, "error_message", "") or "Telegram adapter send failed")
                            tracker.update_delivery_status(audit_id, "FAILED", error_message=err_msg)
                            self._logger.error("[SIGNAL_NOTIFICATION] signal_id=%s recipient=%s channel=TELEGRAM status=FAILED error=%s", signal_id, uname, err_msg)
                            with self._watchdog_lock:
                                self._last_delivery_failure = now_ist()
                                self._consecutive_failures += 1
                            tracker.enqueue_notification_retry(
                                signal_id=signal_id,
                                username=uname,
                                channel="TELEGRAM",
                                destination=tg_chat_id,
                                payload={
                                    "signal": signal,
                                    "custom_message": formatted_plain_msg,
                                    "subject": email_subject,
                                    "priority": "CRITICAL" if tier == "STRONG" else "HIGH",
                                },
                                error_message=err_msg,
                                max_attempts=self.MAX_RETRY_ATTEMPTS,
                                delay_seconds=self.RETRY_BACKOFF_SECONDS[0],
                            )
                            user_deliveries["TELEGRAM"] = "FAILED"
                    except Exception as tg_ex:
                        err_msg = str(tg_ex)
                        tracker.update_delivery_status(audit_id, "FAILED", error_message=err_msg)
                        self._logger.error("[SIGNAL_NOTIFICATION] signal_id=%s recipient=%s channel=TELEGRAM status=FAILED error=%s", signal_id, uname, tg_ex)
                        with self._watchdog_lock:
                            self._last_delivery_failure = now_ist()
                            self._consecutive_failures += 1
                        tracker.enqueue_notification_retry(
                            signal_id=signal_id,
                            username=uname,
                            channel="TELEGRAM",
                            destination=tg_chat_id,
                            payload={
                                "signal": signal,
                                "custom_message": formatted_plain_msg,
                                "subject": email_subject,
                                "priority": "CRITICAL" if tier == "STRONG" else "HIGH",
                            },
                            error_message=err_msg,
                            max_attempts=self.MAX_RETRY_ATTEMPTS,
                            delay_seconds=self.RETRY_BACKOFF_SECONDS[0],
                        )
                        user_deliveries["TELEGRAM"] = "FAILED"

            # ── CHANNEL 2: EMAIL ────────────────────────────────────────
            email_enabled = bool(getattr(u, "email_enabled", True))
            user_email = str(
                getattr(u, "email", "")
                or os.environ.get("OPBUYING_EMAIL_TO")
                or self._cfg.get("EMAIL_TO", "")
            ).strip()

            if not email_enabled:
                tracker.record_delivery_attempt(
                    signal_id=signal_id,
                    username=uname,
                    channel="EMAIL",
                    destination=user_email,
                    attempted=False,
                    status="DISABLED",
                    error_message="User email_enabled is false",
                )
                user_deliveries["EMAIL"] = "DISABLED"
            elif not user_email:
                tracker.record_delivery_attempt(
                    signal_id=signal_id,
                    username=uname,
                    channel="EMAIL",
                    destination="",
                    attempted=False,
                    status="NO_DESTINATION",
                    error_message="No email address configured",
                )
                user_deliveries["EMAIL"] = "NO_DESTINATION"
            elif tracker.is_signal_delivered(signal_id, uname, "EMAIL"):
                self._logger.info("[SIGNAL_DEDUP] Email already delivered for %s/%s; suppressing duplicate", signal_id, uname)
                user_deliveries["EMAIL"] = "ALREADY_DELIVERED"
            else:
                audit_id = tracker.record_delivery_attempt(
                    signal_id=signal_id,
                    username=uname,
                    channel="EMAIL",
                    destination=user_email,
                    attempted=True,
                    status="ATTEMPTED",
                )
                email_avail = email_adapter is not None and (
                    getattr(email_adapter, "enabled", False)
                    or getattr(email_adapter, "_enabled", False)
                    or (hasattr(email_adapter, "is_channel_available") and email_adapter.is_channel_available(NotificationChannel.EMAIL))
                )
                if not email_avail:
                    err_msg = "Email adapter is not enabled or credentials not configured"
                    tracker.update_delivery_status(audit_id, "FAILED", error_message=err_msg)
                    self._logger.error("[SIGNAL_NOTIFICATION] signal_id=%s recipient=%s channel=EMAIL status=FAILED error=%s", signal_id, uname, err_msg)
                    with self._watchdog_lock:
                        self._last_delivery_failure = now_ist()
                        self._consecutive_failures += 1
                    tracker.enqueue_notification_retry(
                        signal_id=signal_id,
                        username=uname,
                        channel="EMAIL",
                        destination=user_email,
                        payload={
                            "signal": signal,
                            "custom_message": formatted_plain_msg,
                            "subject": email_subject,
                            "priority": "CRITICAL" if tier == "STRONG" else "HIGH",
                        },
                        error_message=err_msg,
                        max_attempts=self.MAX_RETRY_ATTEMPTS,
                        delay_seconds=self.RETRY_BACKOFF_SECONDS[0],
                    )
                    user_deliveries["EMAIL"] = "FAILED"
                else:
                    try:
                        email_notif = Notification(
                            message=formatted_plain_msg,
                            channel=NotificationChannel.EMAIL,
                            priority=NotificationPriority.CRITICAL if tier == "STRONG" else NotificationPriority.HIGH,
                            recipient=user_email,
                            subject=email_subject,
                            metadata={
                                "signal_id": signal_id,
                                "symbol": sym,
                                "direction": direction,
                                "price": entry_price,
                                "score": score,
                                "tier": tier,
                                "category": category,
                                "strategy": strategy,
                            },
                        )
                        email_res = email_adapter.send_notification(email_notif)
                        if email_res and getattr(email_res, "status", None) == NotificationStatus.SENT:
                            tracker.update_delivery_status(audit_id, "SENT")
                            with self._watchdog_lock:
                                self._last_delivery_success = now_ist()
                                self._consecutive_failures = 0
                            self._logger.info("[SIGNAL_NOTIFICATION] signal_id=%s recipient=%s channel=EMAIL status=SENT", signal_id, uname)
                            user_deliveries["EMAIL"] = "SENT"
                        else:
                            err_msg = str(getattr(email_res, "error_message", "") or "Email adapter send failed")
                            tracker.update_delivery_status(audit_id, "FAILED", error_message=err_msg)
                            self._logger.error("[SIGNAL_NOTIFICATION] signal_id=%s recipient=%s channel=EMAIL status=FAILED error=%s", signal_id, uname, err_msg)
                            with self._watchdog_lock:
                                self._last_delivery_failure = now_ist()
                                self._consecutive_failures += 1
                            tracker.enqueue_notification_retry(
                                signal_id=signal_id,
                                username=uname,
                                channel="EMAIL",
                                destination=user_email,
                                payload={
                                    "signal": signal,
                                    "custom_message": formatted_plain_msg,
                                    "subject": email_subject,
                                    "priority": "CRITICAL" if tier == "STRONG" else "HIGH",
                                },
                                error_message=err_msg,
                                max_attempts=self.MAX_RETRY_ATTEMPTS,
                                delay_seconds=self.RETRY_BACKOFF_SECONDS[0],
                            )
                            user_deliveries["EMAIL"] = "FAILED"
                    except Exception as em_ex:
                        err_msg = str(em_ex)
                        tracker.update_delivery_status(audit_id, "FAILED", error_message=err_msg)
                        self._logger.error("[SIGNAL_NOTIFICATION] signal_id=%s recipient=%s channel=EMAIL status=FAILED error=%s", signal_id, uname, em_ex)
                        with self._watchdog_lock:
                            self._last_delivery_failure = now_ist()
                            self._consecutive_failures += 1
                        tracker.enqueue_notification_retry(
                            signal_id=signal_id,
                            username=uname,
                            channel="EMAIL",
                            destination=user_email,
                            payload={
                                "signal": signal,
                                "custom_message": formatted_plain_msg,
                                "subject": email_subject,
                                "priority": "CRITICAL" if tier == "STRONG" else "HIGH",
                            },
                            error_message=err_msg,
                            max_attempts=self.MAX_RETRY_ATTEMPTS,
                            delay_seconds=self.RETRY_BACKOFF_SECONDS[0],
                        )
                        user_deliveries["EMAIL"] = "FAILED"

        return results

    def process_retry_queue(self, max_items: int = 20) -> dict[str, int]:
        """Process pending notification retries that are due.

        Concurrency & Idempotency:
        - Atomically claims pending retries via tracker.claim_due_notification_retries
        - Checks is_signal_delivered to avoid redundant transmissions
        - Uses progressive backoff [5, 15, 45]s
        - Moves exhausted attempts to notification_dead_letter (DLQ)
        - Completely independent state between Telegram and Email channels
        """
        counts = {"processed": 0, "succeeded": 0, "retried": 0, "dead_lettered": 0}
        from core.signals.signal_tracker import SignalTracker
        tracker = SignalTracker.get_instance()

        claimed = tracker.claim_due_notification_retries(max_items=max_items)
        if not claimed:
            return counts

        for item in claimed:
            counts["processed"] += 1
            retry_id = item["retry_id"]
            sig_id = item["signal_id"]
            uname = item["username"]
            channel = str(item["channel"]).upper()
            dest = item["destination"]
            attempt_count = item["attempt_count"]
            max_attempts = item["max_attempts"]

            raw_payload = item.get("payload")
            payload: dict[str, Any] = {}
            if isinstance(raw_payload, dict):
                payload = raw_payload
            elif isinstance(raw_payload, str):
                try:
                    payload = json.loads(raw_payload)
                except Exception:
                    payload = {"custom_message": raw_payload}

            # Deduplication check: Has this signal already been delivered on this channel?
            if tracker.is_signal_delivered(sig_id, uname, channel):
                tracker.complete_notification_retry(retry_id)
                counts["succeeded"] += 1
                self._logger.info("[RETRY_QUEUE] Item %d (%s/%s/%s) already delivered; marked COMPLETED", retry_id, sig_id, uname, channel)
                continue

            success = False
            err_msg = ""

            if channel == "TELEGRAM":
                tg_adapter = self._adapters.get(NotificationChannel.TELEGRAM)
                tg_avail = tg_adapter is not None and (
                    getattr(tg_adapter, "enabled", False)
                    or getattr(tg_adapter, "_enabled", False)
                    or (hasattr(tg_adapter, "is_channel_available") and tg_adapter.is_channel_available(NotificationChannel.TELEGRAM))
                )
                if not tg_avail:
                    err_msg = "Telegram adapter is not available or not configured"
                else:
                    try:
                        msg_text = payload.get("custom_message") or payload.get("message") or f"[RETRY] Signal {sig_id}"
                        prio = NotificationPriority.CRITICAL if payload.get("priority") == "CRITICAL" else NotificationPriority.HIGH
                        tg_notif = Notification(
                            message=msg_text,
                            channel=NotificationChannel.TELEGRAM,
                            priority=prio,
                            recipient=dest,
                            subject=payload.get("subject", "Trading Signal"),
                            metadata=payload.get("signal", {}),
                        )
                        tg_res = tg_adapter.send_notification(tg_notif)
                        if tg_res and getattr(tg_res, "status", None) == NotificationStatus.SENT:
                            success = True
                        else:
                            err_msg = str(getattr(tg_res, "error_message", "") or "Telegram retry send failed")
                    except Exception as ex:
                        err_msg = str(ex)

            elif channel == "EMAIL":
                email_adapter = self._adapters.get(NotificationChannel.EMAIL)
                email_avail = email_adapter is not None and (
                    getattr(email_adapter, "enabled", False)
                    or getattr(email_adapter, "_enabled", False)
                    or (hasattr(email_adapter, "is_channel_available") and email_adapter.is_channel_available(NotificationChannel.EMAIL))
                )
                if not email_avail:
                    err_msg = "Email adapter is not available or not configured"
                else:
                    try:
                        msg_text = payload.get("custom_message") or payload.get("message") or f"[RETRY] Signal {sig_id}"
                        prio = NotificationPriority.CRITICAL if payload.get("priority") == "CRITICAL" else NotificationPriority.HIGH
                        email_notif = Notification(
                            message=msg_text,
                            channel=NotificationChannel.EMAIL,
                            priority=prio,
                            recipient=dest,
                            subject=payload.get("subject", "Trading Signal"),
                            metadata=payload.get("signal", {}),
                        )
                        email_res = email_adapter.send_notification(email_notif)
                        if email_res and getattr(email_res, "status", None) == NotificationStatus.SENT:
                            success = True
                        else:
                            err_msg = str(getattr(email_res, "error_message", "") or "Email retry send failed")
                    except Exception as ex:
                        err_msg = str(ex)
            else:
                err_msg = f"Unsupported retry channel: {channel}"

            if success:
                tracker.complete_notification_retry(retry_id)
                tracker.record_delivery_attempt(
                    signal_id=sig_id,
                    username=uname,
                    channel=channel,
                    destination=dest,
                    attempted=True,
                    status="SENT",
                )
                with self._watchdog_lock:
                    self._last_delivery_success = now_ist()
                    self._consecutive_failures = 0
                counts["succeeded"] += 1
                self._logger.info("[RETRY_QUEUE] Successfully delivered retry %d (%s/%s/%s)", retry_id, sig_id, uname, channel)
            else:
                with self._watchdog_lock:
                    self._last_delivery_failure = now_ist()
                    self._consecutive_failures += 1
                next_attempt = attempt_count + 1
                if next_attempt < max_attempts:
                    delay_idx = min(attempt_count, len(self.RETRY_BACKOFF_SECONDS) - 1)
                    delay_sec = self.RETRY_BACKOFF_SECONDS[delay_idx]
                    tracker.fail_notification_retry(retry_id, err_msg, next_delay_seconds=delay_sec)
                    counts["retried"] += 1
                    self._logger.warning("[RETRY_QUEUE] Retry %d attempt %d/%d failed: %s (rescheduled in %ds)", retry_id, next_attempt, max_attempts, err_msg, delay_sec)
                else:
                    tracker.fail_notification_retry(retry_id, err_msg, next_delay_seconds=None)
                    counts["dead_lettered"] += 1
                    self._logger.error("[RETRY_QUEUE] Retry %d reached max attempts (%d); moved to DEAD LETTER QUEUE (DLQ): %s", retry_id, max_attempts, err_msg)

        return counts

    def get_notification_health(self) -> dict[str, Any]:
        """Return comprehensive health assessment of notification delivery subsystems."""
        from core.signals.signal_tracker import SignalTracker
        tracker = SignalTracker.get_instance()
        queue_metrics = tracker.get_notification_queue_metrics()

        tg_adapter = self._adapters.get(NotificationChannel.TELEGRAM)
        email_adapter = self._adapters.get(NotificationChannel.EMAIL)

        with self._watchdog_lock:
            last_succ = self._last_delivery_success.strftime("%Y-%m-%d %H:%M:%S") if self._last_delivery_success else None
            last_fail = self._last_delivery_failure.strftime("%Y-%m-%d %H:%M:%S") if self._last_delivery_failure else None
            consecutive_fails = self._consecutive_failures

        tg_status = {
            "configured": bool(tg_adapter),
            "enabled": bool(tg_adapter and (getattr(tg_adapter, "enabled", False) or getattr(tg_adapter, "_enabled", False))),
        }
        email_status = {
            "configured": bool(email_adapter),
            "enabled": bool(email_adapter and (getattr(email_adapter, "enabled", False) or getattr(email_adapter, "_enabled", False))),
        }

        is_healthy = (
            self.is_running
            and queue_metrics.get("dlq_total", 0) == 0
            and consecutive_fails < 5
        )

        return {
            "service_status": self._status.value if hasattr(self._status, "value") else str(self._status),
            "healthy": is_healthy,
            "adapters": {
                "telegram": tg_status,
                "email": email_status,
            },
            "queue_metrics": queue_metrics,
            "consecutive_failures": consecutive_fails,
            "last_delivery_success": last_succ,
            "last_delivery_failure": last_fail,
        }


# ── Singleton factory ─────────────────────────────────────────────────────────

_notification_service_instance: NotificationService | None = None
_notification_service_lock = threading.RLock()


def get_notification_service(cfg: dict[str, Any] | None = None) -> NotificationService:
    """Return the process-level NotificationService singleton."""
    global _notification_service_instance
    with _notification_service_lock:
        if _notification_service_instance is None:
            _notification_service_instance = NotificationService(cfg=cfg)
            _notification_service_instance.start()
        elif cfg and not _notification_service_instance._cfg:
            _notification_service_instance._cfg = cfg
        return _notification_service_instance


def reset_notification_service() -> None:
    """Force-reset singleton (tests only)."""
    global _notification_service_instance
    with _notification_service_lock:
        if _notification_service_instance is not None:
            try:
                _notification_service_instance.stop()
            except Exception:
                pass
            _notification_service_instance = None
