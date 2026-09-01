"""Telegram notification filtering + periodic scheduling.

Wires six previously-dead config keys into real behavior:
    TG_QUIET_MODE, TG_TRADE_ONLY, TG_TRADE_ALERTS_STRICT, TG_CACHE_TTL_SEC,
    TG_HEARTBEAT_INTERVAL, TG_PERIODIC_SUMMARY_TELEGRAM

Design principle (see json/index_config.defaults.json's
``_comment_notification_filters_enabled`` / ``_comment_tg_heartbeat_enabled``):
TG_QUIET_MODE/TG_TRADE_ONLY/TG_TRADE_ALERTS_STRICT/TG_CACHE_TTL_SEC already
ship with "real" defaults (true/true/true/55) that would silently reduce
today's Telegram traffic the moment they were honored. They are only
consulted when the fresh ``notification_filters_enabled`` master switch
(default False) is on. Likewise, ``TG_HEARTBEAT_ENABLED`` (default False)
gates whether the heartbeat scheduler is allowed to actually send anything
-- kept separate from the master switch above because that one only ever
*suppresses* messages, never originates new ones.

Every public function here is fail-open: on any error it behaves as if the
filter/scheduler were not consulted at all (message sent / nothing
suppressed) and never raises, so a bug in notification filtering can never
break the trade logic that calls ``send()``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "IntervalGate",
    "maybe_send_heartbeat",
    "maybe_send_periodic_summary",
    "reset_dedupe_cache",
    "should_send_notification",
]

# Errors any of the filter/scheduler functions below fail open on -- a bug
# in a notification filter must never be able to block the underlying trade
# logic that is calling send().
_SAFE_EXCEPTIONS = (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError)

# ── Trade-alert classification (TG_TRADE_ONLY / TG_TRADE_ALERTS_STRICT) ─────
# Strict markers are messages this codebase actually emits for real trade
# events (see core/position_service.py's "EXIT {name}: ..." / "[MANUAL
# SIGNAL] ..." text and index_trader.py's entry/exit logging).
_STRICT_TRADE_MARKERS = (
    "ENTRY", "EXIT", "ENTERED", "EXITED", "STOP LOSS", "SL HIT",
    "TARGET HIT", "P&L=", "STOPPED OUT", "[MANUAL SIGNAL]", "TRADE ENTERED",
    "TRADE EXITED",
)
# Loose mode (TG_TRADE_ALERTS_STRICT=false) additionally treats these
# broader keywords as trade-related, at the cost of catching more chatter.
_LOOSE_EXTRA_MARKERS = (
    "SIGNAL", "TRADE", "POSITION", " BUY ", " SELL ", "BLOCK",
)


def _is_trade_alert(message: str, strict: bool) -> bool:
    """Heuristic: does this message look like a real trade event?"""
    upper = f" {message.upper()} "
    if any(marker in upper for marker in _STRICT_TRADE_MARKERS):
        return True
    if strict:
        return False
    return any(marker in upper for marker in _LOOSE_EXTRA_MARKERS)


class _DedupeCache:
    """Tracks last-sent timestamp per message text for TG_CACHE_TTL_SEC dedup."""

    _MAX_ENTRIES = 500

    def __init__(self) -> None:
        self._last_sent: dict[str, float] = {}
        self._lock = threading.RLock()

    def is_duplicate(self, message: str, ttl_sec: float, now: float | None = None) -> bool:
        """Return True (and record ``now``) if ``message`` was already sent within ttl_sec."""
        now = time.time() if now is None else now
        with self._lock:
            last = self._last_sent.get(message)
            self._last_sent[message] = now
            if len(self._last_sent) > self._MAX_ENTRIES:
                cutoff = now - max(ttl_sec, 1.0) * 10
                self._last_sent = {k: v for k, v in self._last_sent.items() if v >= cutoff}
            if last is None:
                return False
            return (now - last) < ttl_sec

    def reset(self) -> None:
        with self._lock:
            self._last_sent.clear()


_dedupe_cache = _DedupeCache()


def reset_dedupe_cache() -> None:
    """Clear the module-level dedupe cache. For test isolation."""
    _dedupe_cache.reset()


def should_send_notification(message: str, critical: bool, cfg: dict[str, Any]) -> bool:
    """Decide whether a Telegram message should actually go out.

    Precedence (only evaluated when ``notification_filters_enabled`` is
    True): critical bypasses everything > TG_QUIET_MODE (suppress all
    non-critical messages) > TG_TRADE_ONLY + TG_TRADE_ALERTS_STRICT
    (suppress non-trade messages) > TG_CACHE_TTL_SEC dedup.

    Fail-open: returns True (send) on any error, and always returns True
    when the master switch is off -- i.e. byte-for-byte the pre-existing
    behavior of this codebase before this module existed.
    """
    try:
        cfg = cfg or {}
        if not bool(cfg.get("notification_filters_enabled", False)):
            return True

        if critical:
            # Critical alerts are never gated by quiet/trade-only/dedup.
            return True

        if bool(cfg.get("TG_QUIET_MODE", True)):
            return False

        if bool(cfg.get("TG_TRADE_ONLY", True)):
            strict = bool(cfg.get("TG_TRADE_ALERTS_STRICT", True))
            if not _is_trade_alert(message, strict=strict):
                return False

        ttl = float(cfg.get("TG_CACHE_TTL_SEC", 55))
        if ttl > 0 and _dedupe_cache.is_duplicate(message, ttl):
            return False

        return True
    except _SAFE_EXCEPTIONS as exc:
        log.debug("Notification filter error, failing open (message sent): %s", exc)
        return True


# ── Periodic scheduling (TG_HEARTBEAT_INTERVAL / TG_PERIODIC_SUMMARY_TELEGRAM) ──


class IntervalGate:
    """Thread-safe 'has enough time passed since I last fired' tracker.

    Shared shape used by both the heartbeat and periodic-summary schedulers
    below -- callable once per scan-loop iteration from wherever the main
    loop already does its own periodic housekeeping (see
    index_app/domains/trading/service.py::TradingLoopService._execute_cycle,
    which already runs ``_periodic_reconcile()`` on every cycle).
    """

    def __init__(self) -> None:
        # None (never fired) is always due, regardless of what `now` happens
        # to be -- using 0.0 here would make a fresh gate wrongly non-due
        # whenever a caller passes a small deterministic `now` (e.g. in
        # tests), since real time.time() epoch values are large enough that
        # "0.0" accidentally worked in production but not under test control.
        self._last_fired: float | None = None
        self._lock = threading.RLock()

    def due(self, interval_sec: float, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            if self._last_fired is None:
                return True
            return (now - self._last_fired) >= max(1.0, float(interval_sec))

    def mark_fired(self, now: float | None = None) -> None:
        with self._lock:
            self._last_fired = time.time() if now is None else now

    def reset(self) -> None:
        with self._lock:
            self._last_fired = None


def maybe_send_heartbeat(
    cfg: dict[str, Any],
    send_fn: Callable[..., Any] | None,
    gate: IntervalGate,
    now: float | None = None,
) -> bool:
    """Send a heartbeat ping once per TG_HEARTBEAT_INTERVAL seconds.

    Gated behind TG_HEARTBEAT_ENABLED (default False) -- nothing new is
    ever sent until an admin opts in. Deliberately reuses the already-wired
    ``send_fn`` (index_trader.py's ``send()`` -> NotificationService.send())
    rather than core.telegram_queue.send_heartbeat(), which sits on a
    separate, still-unwired priority-queue system with no other production
    caller -- routing through it here would create a second parallel
    Telegram path instead of reusing the one real choke point.
    """
    try:
        cfg = cfg or {}
        if send_fn is None or not bool(cfg.get("TG_HEARTBEAT_ENABLED", False)):
            return False
        interval = float(cfg.get("TG_HEARTBEAT_INTERVAL", 3600))
        if not gate.due(interval, now=now):
            return False
        send_fn("Heartbeat: bot is alive and scanning.")
        gate.mark_fired(now=now)
        return True
    except _SAFE_EXCEPTIONS as exc:
        log.debug("Heartbeat scheduling error, skipped (trade logic unaffected): %s", exc)
        return False


def maybe_send_periodic_summary(
    cfg: dict[str, Any],
    send_fn: Callable[..., Any] | None,
    gate: IntervalGate,
    summary_fn: Callable[..., str] | None = None,
    now: float | None = None,
) -> bool:
    """Send a compact performance summary once per TG_PERIODIC_SUMMARY_INTERVAL_SEC.

    Gated behind TG_PERIODIC_SUMMARY_TELEGRAM (already defaults False, so
    this is comparatively low-risk to wire). Content is produced by
    ``core.performance_metrics.periodic_summary()`` -- already built for
    exactly this ("call from scheduler / index_trader") but never actually
    called from anywhere until now; no new metrics logic is invented here.
    """
    try:
        cfg = cfg or {}
        if send_fn is None or not bool(cfg.get("TG_PERIODIC_SUMMARY_TELEGRAM", False)):
            return False
        interval = float(cfg.get("TG_PERIODIC_SUMMARY_INTERVAL_SEC", 3600))
        if not gate.due(interval, now=now):
            return False

        fn = summary_fn
        if fn is None:
            from core.performance_metrics import periodic_summary as fn

        db_path = str(cfg.get("DB_PATH", "db/trades.db"))
        mode = str(cfg.get("EXECUTION_MODE", "PAPER"))
        text = fn(db_path=db_path, mode=mode)
        send_fn(f"Periodic summary:\n{text}")
        gate.mark_fired(now=now)
        return True
    except _SAFE_EXCEPTIONS as exc:
        log.debug("Periodic summary scheduling error, skipped: %s", exc)
        return False
