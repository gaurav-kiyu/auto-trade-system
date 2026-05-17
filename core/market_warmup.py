"""
Market Warm-Up / Throttled-Entry Mode (v2.45 hardening item).

At market open (09:15 IST), the bot enters a configurable warm-up period
during which entries are throttled:
  - Position size reduced by `warmup_size_mult`
  - Score threshold increased by `warmup_score_boost`
  - Max trades limited to `warmup_max_trades`

After the warm-up duration elapses, normal trading resumes automatically.

Config keys
-----------
    warmup_enabled         : bool   default true
    warmup_duration_mins   : int    default 15
    warmup_size_mult       : float  default 0.5
    warmup_score_boost     : int    default 10
    warmup_max_trades      : int    default 2

Public API
----------
    MarketWarmup.is_warmup_active()                    -> bool
    MarketWarmup.can_enter(name)                       -> bool
    MarketWarmup.position_size_mult()                  -> float
    MarketWarmup.score_threshold_adjustment()          -> int
    MarketWarmup.adjusted_position_size(base_size)     -> int
    MarketWarmup.status()                              -> dict
    MarketWarmup.try_mark_entry(name)                  -> bool
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any

_log = logging.getLogger(__name__)

# IST offset for timezone-naive comparisons
_IST_OFFSET = timedelta(hours=5, minutes=30)

# Market open time components
_MARKET_OPEN_HOUR = 9
_MARKET_OPEN_MINUTE = 15


class MarketWarmup:
    """Thread-safe warm-up period controller for market open."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        c = cfg or {}
        self._enabled = bool(c.get("warmup_enabled", True))
        self._duration_mins = int(c.get("warmup_duration_mins", 15))
        self._size_mult = float(c.get("warmup_size_mult", 0.5))
        self._score_boost = int(c.get("warmup_score_boost", 10))
        self._max_trades = int(c.get("warmup_max_trades", 2))
        self._lock = threading.Lock()
        self._entries: dict[str, float] = {}  # name -> timestamp
        self._current_day: date | None = None
        self._warmup_end: datetime | None = None

    def _market_open_today(self) -> datetime | None:
        """Return today's market open datetime (naive IST), or None if weekend."""
        now = datetime.now()
        # Check if today is a weekday (Mon=0, Sun=6)
        if now.weekday() >= 5:
            return None
        return now.replace(hour=_MARKET_OPEN_HOUR, minute=_MARKET_OPEN_MINUTE, second=0, microsecond=0)

    def _maybe_reset_day(self) -> None:
        """Reset warm-up state at the start of a new trading day."""
        now = datetime.now()
        today = now.date()
        with self._lock:
            if self._current_day != today:
                self._current_day = today
                self._entries.clear()
                open_dt = self._market_open_today()
                if open_dt is not None:
                    self._warmup_end = open_dt + timedelta(minutes=self._duration_mins)
                else:
                    self._warmup_end = None

    def is_warmup_active(self) -> bool:
        """Check if we are currently in the warm-up period."""
        if not self._enabled:
            return False
        self._maybe_reset_day()
        with self._lock:
            if self._warmup_end is None:
                return False
            return datetime.now() < self._warmup_end

    def can_enter(self, name: str) -> bool:
        """Check if an entry is allowed for the given index.

        During warm-up, limits the number of trades to warmup_max_trades.
        """
        if not self._enabled:
            return True
        if not self.is_warmup_active():
            return True
        with self._lock:
            active_count = sum(
                1 for ts in self._entries.values()
                if time.time() - ts < 3600  # entries within last hour
            )
            if active_count >= self._max_trades:
                _log.info("[WARMUP] max trades (%d) reached for warm-up period", self._max_trades)
                return False
            return True

    def try_mark_entry(self, name: str) -> bool:
        """Record an entry attempt. Returns True if allowed."""
        if not self.can_enter(name):
            return False
        with self._lock:
            self._entries[name] = time.time()
        return True

    def position_size_mult(self) -> float:
        """Return the position size multiplier during warm-up."""
        if not self._enabled or not self.is_warmup_active():
            return 1.0
        return self._size_mult

    def score_threshold_adjustment(self) -> int:
        """Return the extra score threshold boost during warm-up."""
        if not self._enabled or not self.is_warmup_active():
            return 0
        return self._score_boost

    def adjusted_position_size(self, base_size: int) -> int:
        """Apply warm-up position size scaling to a base lot size."""
        if not self._enabled or not self.is_warmup_active():
            return base_size
        adjusted = max(1, int(round(base_size * self._size_mult)))
        return adjusted

    def reset_day(self) -> None:
        """Force-reset warm-up state (used by tests)."""
        with self._lock:
            self._current_day = None
            self._warmup_end = None
            self._entries.clear()

    def status(self) -> dict[str, Any]:
        """Return a status snapshot for health checks / web dashboard."""
        active = self.is_warmup_active()
        with self._lock:
            remaining = ""
            if active and self._warmup_end is not None:
                remaining_secs = (self._warmup_end - datetime.now()).total_seconds()
                remaining = f"{max(0, int(remaining_secs // 60))}m {max(0, int(remaining_secs % 60))}s"
            return {
                "enabled": self._enabled,
                "warmup_active": active,
                "duration_mins": self._duration_mins,
                "size_mult": self._size_mult,
                "score_boost": self._score_boost,
                "max_trades": self._max_trades,
                "entries_in_warmup": len(self._entries),
                "remaining": remaining,
            }
