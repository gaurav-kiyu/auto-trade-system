"""
WebSocket Feed Resilience Manager (v2.45 hardening item).

Wraps any WebSocket connection with automatic reconnect using exponential
backoff with jitter.  Provides a foundation for real WebSocket feeds
(KiteTicker, etc.) when they are built out.

Connection lifecycle:
    connect() → auto-reconnect on failure → disconnect()

Backoff formula (matching ExecutionEngine pattern):
    delay = min(base_delay * (2 ** attempt), max_delay_s)
    jitter = delay * jitter_pct
    sleep = delay - jitter + random * 2 * jitter

Config keys
-----------
    ws_reconnect_max_attempts   : int    default 10
    ws_reconnect_base_delay_s   : float  default 1.0
    ws_reconnect_max_delay_s    : float  default 30.0
    ws_reconnect_jitter_pct     : float  default 0.25
    ws_heartbeat_interval_s     : float  default 30.0

Public API
----------
    WebSocketFeedManager.connect(on_message, on_error)     -> bool
    WebSocketFeedManager.disconnect()                       -> None
    WebSocketFeedManager.is_connected()                     -> bool
    WebSocketFeedManager.status()                           -> dict
"""
from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from typing import Any

_log = logging.getLogger(__name__)


class WebSocketFeedManager:
    """Thread-safe WebSocket feed manager with exponential-backoff reconnect."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        c = cfg or {}
        self._max_attempts = int(c.get("ws_reconnect_max_attempts", 10))
        self._base_delay_s = float(c.get("ws_reconnect_base_delay_s", 1.0))
        self._max_delay_s = float(c.get("ws_reconnect_max_delay_s", 30.0))
        self._jitter_pct = float(c.get("ws_reconnect_jitter_pct", 0.25))
        self._heartbeat_s = float(c.get("ws_heartbeat_interval_s", 30.0))
        self._lock = threading.RLock()
        self._connected = False
        self._reconnect_count = 0
        self._last_connect_ts: float = 0.0
        self._last_disconnect_ts: float = 0.0
        self._last_error: str = ""
        self._stop_event = threading.Event()
        self._reconnect_thread: threading.Thread | None = None

    def _backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff with jitter (matching ExecutionEngine)."""
        delay = min(self._base_delay_s * (2 ** (attempt - 1)), self._max_delay_s)
        jitter = delay * self._jitter_pct
        return delay - jitter + random.random() * 2 * jitter

    def connect(
        self,
        on_message: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> bool:
        """Establish the WebSocket connection.

        Subclasses override _do_connect() to implement the actual connection.
        Returns True if connection was established.
        """
        self._stop_event.clear()
        try:
            result = self._do_connect(on_message, on_error)
            with self._lock:
                self._connected = result
                if result:
                    self._reconnect_count = 0
                    self._last_connect_ts = time.time()
                    self._last_error = ""
            return result
        except Exception as exc:
            with self._lock:
                self._connected = False
                self._last_error = str(exc)
            _log.error("[WS_MANAGER] connect failed: %s", exc)
            return False

    def _do_connect(
        self,
        on_message: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> bool:
        """Override in subclass to implement actual WebSocket connection.

        Default implementation returns False (stub).
        """
        return False

    def disconnect(self) -> None:
        """Gracefully close the WebSocket connection."""
        self._stop_event.set()
        self._do_disconnect()
        with self._lock:
            self._connected = False
            self._last_disconnect_ts = time.time()

    def _do_disconnect(self) -> None:
        """Override in subclass to implement actual WebSocket disconnection."""

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    def start_reconnect_loop(
        self,
        on_message: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Start a background thread that attempts reconnection on failure.

        Call disconnect() to stop the loop.
        """
        if self._reconnect_thread is not None and self._reconnect_thread.is_alive():
            _log.warning("[WS_MANAGER] reconnect loop already running")
            return

        self._stop_event.clear()
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_worker,
            args=(on_message, on_error),
            daemon=True,
        )
        self._reconnect_thread.start()
        _log.info("[WS_MANAGER] reconnect loop started")

    def _reconnect_worker(
        self,
        on_message: Callable[[Any], None] | None,
        on_error: Callable[[Exception], None] | None,
    ) -> None:
        """Background worker that keeps reconnecting on failure."""
        attempt = 0
        while not self._stop_event.is_set():
            if self.is_connected():
                # Wait before checking again (heartbeat interval)
                self._stop_event.wait(self._heartbeat_s)
                continue

            attempt += 1
            if attempt > self._max_attempts:
                _log.error(
                    "[WS_MANAGER] max reconnect attempts (%d) reached, giving up",
                    self._max_attempts,
                )
                break

            delay = self._backoff_delay(attempt)
            _log.info(
                "[WS_MANAGER] reconnect attempt %d/%d in %.1fs",
                attempt, self._max_attempts, delay,
            )

            if self._stop_event.wait(delay):
                break

            ok = self.connect(on_message, on_error)
            if ok:
                _log.info(
                    "[WS_MANAGER] reconnected on attempt %d/%d",
                    attempt, self._max_attempts,
                )
                with self._lock:
                    self._reconnect_count += 1
                attempt = 0
            else:
                if on_error:
                    on_error(ConnectionError(f"reconnect attempt {attempt} failed"))

    def status(self) -> dict[str, Any]:
        """Return a status snapshot for health checks / web dashboard."""
        with self._lock:
            return {
                "connected": self._connected,
                "reconnect_count": self._reconnect_count,
                "max_attempts": self._max_attempts,
                "base_delay_s": self._base_delay_s,
                "max_delay_s": self._max_delay_s,
                "jitter_pct": self._jitter_pct,
                "heartbeat_s": self._heartbeat_s,
                "last_connect_ts": self._last_connect_ts,
                "last_disconnect_ts": self._last_disconnect_ts,
                "last_error": self._last_error,
            }


__all__ = [
    "WebSocketFeedManager",
]

