"""
Notification models for the Enterprise Dashboard.

Extracted from core/enterprise_dashboard.py for SRP compliance.
Provides Notification, NotificationManager, and DashboardNotifier classes.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import AsyncGenerator

_log = logging.getLogger(__name__)


__all__ = [
    "DashboardNotifier",
    "Notification",
    "NotificationManager",
]


class Notification:
    """A single system notification with severity, message, and metadata."""

    def __init__(
        self,
        message: str,
        severity: str = "INFO",
        category: str = "system",
        source: str = "dashboard",
        details: dict | None = None,
    ):
        self.id = uuid.uuid4().hex[:12]
        self.message = message
        self.severity = severity.upper()  # INFO, WARNING, ERROR, CRITICAL
        self.category = category
        self.source = source
        self.timestamp = time.time()
        self.details = details or {}
        self.acknowledged = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "message": self.message,
            "severity": self.severity,
            "category": self.category,
            "source": self.source,
            "timestamp": self.timestamp,
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.timestamp)),
            "timestamp_human": time.strftime("%H:%M:%S", time.localtime(self.timestamp)),
            "acknowledged": self.acknowledged,
        }


class NotificationManager:
    """Thread-safe notification manager with SSE subscriber support.

    Holds up to ``maxlen`` notifications in memory. Subscribers receive
    new notifications via an async generator for SSE streaming.
    """

    def __init__(self, maxlen: int = 200):
        self._notifications: deque[Notification] = deque(maxlen=maxlen)
        self._lock = threading.RLock()
        self._subscribers: list[asyncio.Queue] = []
        self._sub_lock = threading.RLock()

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._notifications)

    def push(
        self,
        message: str,
        severity: str = "INFO",
        category: str = "system",
        source: str = "dashboard",
        details: dict | None = None,
    ) -> Notification:
        """Create and broadcast a new notification."""
        notif = Notification(
            message=message,
            severity=severity,
            category=category,
            source=source,
            details=details,
        )
        with self._lock:
            self._notifications.append(notif)
        with self._sub_lock:
            dead: list[asyncio.Queue] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(notif.to_dict())
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)
        _log.debug("[NOTIFY] %s: %s", severity, message)
        return notif

    def recent(self, n: int = 50) -> list[dict]:
        """Return the ``n`` most recent notifications as dicts."""
        with self._lock:
            return [n.to_dict() for n in list(self._notifications)[-n:]]

    def acknowledge(self, notif_id: str) -> bool:
        """Mark a notification as acknowledged by ID."""
        with self._lock:
            for n in self._notifications:
                if n.id == notif_id:
                    n.acknowledged = True
                    return True
        return False

    def acknowledge_all(self, severity: str | None = None) -> int:
        """Acknowledge all notifications, optionally filtered by severity."""
        count = 0
        with self._lock:
            for n in self._notifications:
                if severity is None or n.severity == severity.upper():
                    n.acknowledged = True
                    count += 1
        return count

    def clear(self) -> int:
        """Clear all notifications. Returns the count cleared."""
        with self._lock:
            count = len(self._notifications)
            self._notifications.clear()
            return count

    async def subscribe(self) -> AsyncGenerator[dict, None]:
        """Async generator for SSE streaming. Yields notification dicts as they arrive.

        Usage:
            async for notif in manager.subscribe():
                yield f"data: {json.dumps(notif)}\n\n"
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        with self._sub_lock:
            self._subscribers.append(q)
        try:
            while True:
                notif = await q.get()
                yield notif
        except asyncio.CancelledError:
            pass
        finally:
            with self._sub_lock:
                if q in self._subscribers:
                    self._subscribers.remove(q)


class DashboardNotifier:
    """Lightweight HTTP client for pushing notifications to the dashboard API.

    Posts to POST /api/system/notifications/push. Thread-safe, silently fails
    when dashboard is unreachable. Auto-disables after 10 consecutive failures.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8765", timeout: float = 2.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._lock = threading.RLock()
        self._enabled = True
        self._consecutive_failures = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def disable(self) -> None:
        with self._lock:
            self._enabled = False

    def send(
        self,
        message: str,
        severity: str = "INFO",
        category: str = "system",
        source: str = "bot",
        details: dict | None = None,
    ) -> bool:
        if not self._enabled:
            return False
        try:
            import requests as _req

            resp = _req.post(
                f"{self._base_url}/api/system/notifications/push",
                json={
                    "message": message,
                    "severity": severity,
                    "category": category,
                    "source": source,
                    "details": details or {},
                },
                timeout=self._timeout,
            )
            if resp.status_code in (200, 201):
                with self._lock:
                    self._consecutive_failures = 0
                return True
            self._track_failure()
            return False
        except Exception:
            self._track_failure()
            return False

    def _track_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 10:
                self._enabled = False

    def push_bot_start(self, mode: str = "paper") -> None:
        self.send("Bot started - mode=" + mode, severity="INFO", category="system")

    def push_trade_entry(self, symbol: str, direction: str, score: int, price: float) -> None:
        msg = f"Trade entered: {symbol} {direction} @ {price:.2f} (score={score})"
        self.send(msg, severity="INFO", category="trade",
                  details={"symbol": symbol, "direction": direction, "score": score, "price": price})

    def push_trade_exit(self, symbol: str, reason: str, pnl: float) -> None:
        sev = "WARNING" if pnl < 0 else "INFO"
        msg = f"Trade exited: {symbol} {reason} P&L={pnl:+.2f}"
        self.send(msg, severity=sev, category="trade",
                  details={"symbol": symbol, "reason": reason, "pnl": pnl})

    def push_risk_breach(self, metric: str, value: float, limit: float) -> None:
        msg = f"Risk breach: {metric}={value:.2f} (limit={limit:.2f})"
        self.send(msg, severity="CRITICAL", category="risk",
                  details={"metric": metric, "value": value, "limit": limit})

    def push_shutdown(self, reason: str = "User initiated") -> None:
        self.send("Bot shutting down: " + reason, severity="INFO", category="system")
