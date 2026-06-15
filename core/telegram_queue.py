"""
Telegram priority queue (Item 7 — v2.44).

Replaces the simple ThreadPoolExecutor dispatch with a priority-heap queue
so CRITICAL alerts are always delivered even during a 30-msg/min cascade.

Rules
-----
  CRITICAL (0) : Never dropped. If queue is full, drop LOW first then NORMAL.
  HIGH     (1) : Queued and delayed, never dropped unless shutdown.
  NORMAL   (2) : Dropped if queue depth > tg_max_queue_depth AND older than
                 tg_normal_drop_age_secs.
  LOW      (3) : Dropped immediately if queue depth > tg_low_drop_threshold.

Config keys
-----------
  tg_max_queue_depth          : int   default 20
  tg_normal_drop_age_secs     : int   default 30
  tg_low_drop_threshold       : int   default 5
  tg_max_retries_critical     : int   default 3
  tg_max_retries_normal       : int   default 1
  tg_rate_limit_per_min       : int   default 25
"""
from __future__ import annotations

import heapq
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

_log = logging.getLogger(__name__)


class TelegramPriority(IntEnum):
    CRITICAL = 0   # trade closes, circuit breaker, daily loss hit
    HIGH     = 1   # trade entries, strong signals, config critical
    NORMAL   = 2   # status updates, regime changes, config high
    LOW      = 3   # heartbeat, info, debug


@dataclass(order=True)
class TelegramMessage:
    priority:    int                       # heap ordering key
    ts:          float = field(compare=False)
    text:        str   = field(compare=False)
    parse_mode:  str   = field(compare=False, default="text")
    retry_count: int   = field(compare=False, default=0)


class TelegramQueue:
    """
    Priority-queue backed Telegram sender.
    A single daemon thread drains the queue respecting rate limits.
    Backward-compatible: existing send() callers work unchanged.
    """

    def __init__(
        self,
        send_fn:  Callable[[str], bool],  # raw HTTP send; returns True on success
        cfg:      dict[str, Any] | None = None,
    ) -> None:
        self._send_fn  = send_fn
        self._cfg      = cfg or {}
        self._heap:    list[TelegramMessage] = []
        self._lock     = threading.Lock()
        self._cond     = threading.Condition(self._lock)
        self._stop     = threading.Event()
        self._thread:  threading.Thread | None = None
        # Metrics
        self._dropped_by_level: dict[str, int] = {
            "CRITICAL": 0, "HIGH": 0, "NORMAL": 0, "LOW": 0,
        }
        self._sent_this_min: list[float] = []

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._drain_loop, name="tg-queue", daemon=True
        )
        self._thread.start()

    def stop(self, flush_timeout: float = 30.0) -> None:
        """Graceful shutdown — flushes CRITICAL + HIGH before exit."""
        self._stop.set()
        deadline = time.time() + flush_timeout
        while time.time() < deadline:
            with self._lock:
                has_important = any(
                    m.priority <= TelegramPriority.HIGH for m in self._heap
                )
                if not has_important:
                    break
            time.sleep(0.5)  # Intentional — stop event already set; polling with deadline
        if self._thread:
            self._thread.join(timeout=5.0)

    def enqueue(
        self,
        text:      str,
        priority:  TelegramPriority = TelegramPriority.NORMAL,
    ) -> None:
        """Add a message to the priority queue."""
        c               = self._cfg
        max_depth       = int(c.get("tg_max_queue_depth",        20))
        low_threshold   = int(c.get("tg_low_drop_threshold",      5))
        drop_age        = int(c.get("tg_normal_drop_age_secs",    30))

        msg = TelegramMessage(
            priority=int(priority), ts=time.time(), text=str(text)
        )

        with self._cond:
            current_depth = len(self._heap)

            if priority == TelegramPriority.LOW and current_depth > low_threshold:
                self._dropped_by_level["LOW"] += 1
                _log.debug("[TG_Q] LOW dropped (depth=%d)", current_depth)
                return

            if priority == TelegramPriority.NORMAL and current_depth >= max_depth:
                # Try dropping expired NORMAL/LOW first
                now = time.time()
                self._heap = [
                    m for m in self._heap
                    if m.priority <= TelegramPriority.HIGH
                    or (now - m.ts) <= drop_age
                ]
                heapq.heapify(self._heap)
                if len(self._heap) >= max_depth:
                    # Still full — drop this NORMAL
                    self._dropped_by_level["NORMAL"] += 1
                    _log.debug("[TG_Q] NORMAL dropped (queue full)")
                    return

            if priority == TelegramPriority.CRITICAL and current_depth >= max_depth:
                # Make room by dropping lowest-priority messages
                self._heap = sorted(self._heap, key=lambda m: m.priority)
                dropped = 0
                while len(self._heap) >= max_depth and self._heap:
                    worst = self._heap[-1]
                    if worst.priority <= TelegramPriority.HIGH:
                        break  # never drop HIGH or CRITICAL
                    heapq.heappop(self._heap)
                    level = TelegramPriority(worst.priority).name
                    self._dropped_by_level[level] += 1
                    dropped += 1
                heapq.heapify(self._heap)

            heapq.heappush(self._heap, msg)
            self._cond.notify()

    def get_metrics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "queue_depth":        len(self._heap),
                "dropped_critical":   self._dropped_by_level["CRITICAL"],
                "dropped_high":       self._dropped_by_level["HIGH"],
                "dropped_normal":     self._dropped_by_level["NORMAL"],
                "dropped_low":        self._dropped_by_level["LOW"],
                "dropped_today":      sum(self._dropped_by_level.values()),
            }

    def update_config(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg

    # ── Priority-aware send helpers ────────────────────────────────────────────

    def send(self, text: str, priority: TelegramPriority = TelegramPriority.NORMAL) -> None:
        self.enqueue(text, priority)

    def send_critical(self, text: str) -> None:
        self.enqueue(text, TelegramPriority.CRITICAL)

    def send_high(self, text: str) -> None:
        self.enqueue(text, TelegramPriority.HIGH)

    def send_trade_entry(self, text: str) -> None:
        self.enqueue(text, TelegramPriority.HIGH)

    def send_trade_close(self, text: str) -> None:
        self.enqueue(text, TelegramPriority.CRITICAL)

    def send_circuit_breaker(self, text: str) -> None:
        self.enqueue(text, TelegramPriority.CRITICAL)

    def send_heartbeat(self, text: str) -> None:
        self.enqueue(text, TelegramPriority.LOW)

    # ── Drain loop ─────────────────────────────────────────────────────────────

    def _drain_loop(self) -> None:
        while not self._stop.is_set() or self._heap:
            with self._cond:
                while not self._heap and not self._stop.is_set():
                    self._cond.wait(timeout=1.0)
                if not self._heap:
                    break
                msg = heapq.heappop(self._heap)

            self._rate_wait()
            self._deliver(msg)

    def _rate_wait(self) -> None:
        c        = self._cfg
        rate_lim = int(c.get("tg_rate_limit_per_min", 25))
        now      = time.time()
        self._sent_this_min = [t for t in self._sent_this_min if now - t < 60]
        if len(self._sent_this_min) >= rate_lim:
            sleep_secs = 60 - (now - self._sent_this_min[0]) + 1
            _log.debug("[TG_Q] Rate limit reached — sleeping %.1fs", sleep_secs)
            if self._stop.wait(max(0.1, sleep_secs)):
                return  # Shutdown during rate-limit wait
            now = time.time()
            self._sent_this_min = [t for t in self._sent_this_min if now - t < 60]

    def _deliver(self, msg: TelegramMessage) -> None:
        c           = self._cfg
        max_crit    = int(c.get("tg_max_retries_critical", 3))
        max_normal  = int(c.get("tg_max_retries_normal",   1))
        max_retries = max_crit if msg.priority <= TelegramPriority.CRITICAL else max_normal

        for attempt in range(max_retries + 1):
            try:
                success = self._send_fn(msg.text)
                if success:
                    self._sent_this_min.append(time.time())
                    return
            except (ValueError, TypeError, KeyError, AttributeError, ConnectionError, TimeoutError, OSError) as exc:
                _log.warning("[TG_Q] Deliver error attempt %d: %s", attempt, exc)
            except Exception as exc:
                _log.warning("[TG_Q] Deliver error attempt %d (unexpected: %s): %s", attempt, type(exc).__name__, exc)

            if attempt < max_retries:
                backoff = 2.0 ** attempt   # 1s, 2s, 4s
                if self._stop.wait(backoff):
                    _log.debug("[TG_Q] Retry interrupted by shutdown")
                    return

        level = TelegramPriority(msg.priority).name
        _log.warning("[TG_Q] %s message not delivered after %d attempts: %s",
                     level, max_retries + 1, msg.text[:80])
        self._dropped_by_level[level] += 1
