"""Conservative scan-loop stall DETECTOR — not a killer.

CLAUDE.md's "Safety Systems (Never Disable)" section describes a
"Watchdog thread — kills hung scan loop" that, as of this module's
introduction, does not exist anywhere in the codebase (no threading.Thread
implements scan-loop-killing behavior). This module replaces that
inaccurate claim with an honest, real, tested implementation: it detects
a stalled main loop and alerts — it NEVER kills or restarts any thread or
process. Autonomously killing a hung loop mid-order-placement could
double-submit an order or leave state inconsistent, so that behavior is
intentionally out of scope here.

Usage: the main scan loop calls heartbeat() once per cycle. Something
(here, the same loop, checked at the top of the next cycle) calls check()
to see whether WATCHDOG_TIMEOUT seconds have elapsed since the last
heartbeat. On a detected stall, a CRITICAL log line is always emitted and,
if a notify_fn was supplied, an alert is sent through it — no new
notification channel is created.

Config keys
-----------
  loop_watchdog_enabled : bool  default False  (opt-in; brand-new monitoring
                                                 infra with no track record)
  WATCHDOG_TIMEOUT      : int   default 300     (seconds without a heartbeat
                                                 before a stall is reported)
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

_log = logging.getLogger(__name__)

__all__ = [
    "LoopWatchdog",
    "get_loop_watchdog",
    "reset_loop_watchdog",
]


class LoopWatchdog:
    """Tracks the main scan loop's last heartbeat and detects stalls.

    Detect-and-alert only. Fail-open by design: any internal error is
    swallowed by callers via the same try/except idiom used elsewhere in
    this codebase, so a bug here can never break the trading loop it
    observes.
    """

    def __init__(
        self,
        cfg: dict[str, Any] | None = None,
        notify_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._cfg = cfg or {}
        self._notify_fn = notify_fn
        self._lock = threading.RLock()
        self._last_heartbeat = time.monotonic()
        self._alerted = False

    def heartbeat(self) -> None:
        """Call once per scan cycle from the main loop."""
        with self._lock:
            self._last_heartbeat = time.monotonic()
            self._alerted = False  # stall recovered; allow a future re-alert

    def update_config(self, cfg: dict[str, Any]) -> None:
        """Allow hot-reload of config."""
        with self._lock:
            self._cfg = cfg

    def set_notify_fn(self, notify_fn: Callable[[str], None] | None) -> None:
        with self._lock:
            self._notify_fn = notify_fn

    def _timeout(self) -> float:
        try:
            return float(self._cfg.get("WATCHDOG_TIMEOUT", 300))
        except (ValueError, TypeError):
            return 300.0

    def get_lag(self) -> float:
        """Seconds elapsed since the last heartbeat (for display/health-check use)."""
        with self._lock:
            return time.monotonic() - self._last_heartbeat

    def check(self) -> bool:
        """Return True if the configured timeout has been exceeded.

        Disabled (loop_watchdog_enabled=False, the default) always returns
        False without touching alert state. Fires the CRITICAL log line and
        notify_fn (if any) at most once per stall episode — heartbeat()
        clears the alert flag so a subsequent stall can alert again.
        """
        if not self._cfg.get("loop_watchdog_enabled", False):
            return False
        with self._lock:
            elapsed = time.monotonic() - self._last_heartbeat
            timeout = self._timeout()
            stalled = elapsed > timeout
            if stalled and not self._alerted:
                self._alerted = True
                _log.critical(
                    "[LOOP_WATCHDOG] Scan loop stalled: %.0fs since last heartbeat "
                    "(timeout=%.0fs). Detect-and-alert only - no automatic "
                    "restart/kill is performed.",
                    elapsed, timeout,
                )
                if self._notify_fn is not None:
                    try:
                        self._notify_fn(
                            f"Scan loop stalled: {elapsed:.0f}s since last heartbeat "
                            f"(timeout={timeout:.0f}s)",
                        )
                    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                        _log.debug("[LOOP_WATCHDOG] notify_fn failed", exc_info=True)
            return stalled


_watchdog_lock = threading.Lock()
_watchdog_instance: LoopWatchdog | None = None


def get_loop_watchdog(
    cfg: dict[str, Any] | None = None,
    notify_fn: Callable[[str], None] | None = None,
) -> LoopWatchdog:
    """Process-wide singleton (mirrors core.intraday_performance_monitor's
    get_intraday_monitor() pattern). On first call, cfg/notify_fn seed the
    instance; later calls refresh cfg (update_config) if cfg is given, and
    refresh notify_fn if one is passed, so a config reload takes effect.
    """
    global _watchdog_instance
    with _watchdog_lock:
        if _watchdog_instance is None:
            _watchdog_instance = LoopWatchdog(cfg, notify_fn)
        else:
            if cfg is not None:
                _watchdog_instance.update_config(cfg)
            if notify_fn is not None:
                _watchdog_instance.set_notify_fn(notify_fn)
        return _watchdog_instance


def reset_loop_watchdog() -> None:
    """Test helper: drop the singleton so the next get_loop_watchdog() call
    starts a fresh instance (no carried-over heartbeat/alert state)."""
    global _watchdog_instance
    with _watchdog_lock:
        _watchdog_instance = None
