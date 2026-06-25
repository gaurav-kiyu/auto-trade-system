"""
Re-entry evaluator (Item 2 - v2.44).

Checks whether a new entry is warranted after a stop-loss on the same index.
NSE intraday moves frequently fake-out stops before resuming original direction.

Config keys
-----------
  reentry_enabled              : bool  default false
  reentry_cooldown_mins        : int   default 15
  reentry_score_boost          : int   default 5    (extra score required vs original)
  max_reentries_per_day        : int   default 1
  reentry_same_direction_only  : bool  default true
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReentryDecision:
    allowed:               bool
    reason:                str
    cooldown_remaining_secs: int  # 0 if allowed
    score_required:        int    # minimum score for re-entry
    original_score:        int
    current_score:         int
    direction_intact:      bool   # same direction as original?


@dataclass
class ReentryTracker:
    """Per-index re-entry state. One instance per index."""

    index_name:          str
    last_sl_ts:          float | None = None
    last_sl_direction:   str | None   = None   # "CALL" | "PUT"
    last_sl_score:       int          = 0
    reentries_today:     int          = 0

    def record_stop_loss(self, direction: str, score: int) -> None:
        """Call immediately when a position exits on SL_HIT."""
        self.last_sl_ts        = time.time()
        self.last_sl_direction = str(direction).upper()
        self.last_sl_score     = int(score)
        _log.info(
            "[REENTRY] %s SL recorded dir=%s score=%d",
            self.index_name, self.last_sl_direction, self.last_sl_score,
        )

    def evaluate_reentry(
        self,
        current_score:     int,
        current_direction: str,
        cfg:               dict[str, Any] | None = None,
    ) -> ReentryDecision:
        """
        Returns ReentryDecision.  Allows re-entry only when ALL hold:
          1. A prior SL exists for this index today.
          2. Cooldown elapsed (reentry_cooldown_mins).
          3. same_direction_only → direction must match.
          4. current_score >= last_sl_score + reentry_score_boost.
          5. reentries_today < max_reentries_per_day.
          6. reentry_enabled = true.
        """
        c             = cfg or {}
        enabled       = bool(c.get("reentry_enabled", False))
        cooldown_secs = int(float(c.get("reentry_cooldown_mins", 15)) * 60)
        score_boost   = int(c.get("reentry_score_boost", 5))
        max_reentries = int(c.get("max_reentries_per_day", 1))
        same_dir_only = bool(c.get("reentry_same_direction_only", True))

        cur_dir  = str(current_direction).upper()
        cur_sc   = int(current_score)

        def _no(reason: str, cooldown: int = 0) -> ReentryDecision:
            return ReentryDecision(
                allowed=False, reason=reason,
                cooldown_remaining_secs=cooldown,
                score_required=self.last_sl_score + score_boost,
                original_score=self.last_sl_score,
                current_score=cur_sc,
                direction_intact=(cur_dir == self.last_sl_direction),
            )

        if not enabled:
            return ReentryDecision(
                allowed=True, reason="reentry_enabled=false (pass-through)",
                cooldown_remaining_secs=0,
                score_required=0, original_score=0, current_score=cur_sc,
                direction_intact=True,
            )

        if self.last_sl_ts is None:
            # No SL hit today - first entry, always allow
            return ReentryDecision(
                allowed=True, reason="First entry (no prior SL today)",
                cooldown_remaining_secs=0,
                score_required=0, original_score=0, current_score=cur_sc,
                direction_intact=True,
            )

        elapsed = time.time() - self.last_sl_ts
        if elapsed < cooldown_secs:
            remaining = int(cooldown_secs - elapsed)
            return _no(f"Cooldown: {remaining}s remaining", remaining)

        if same_dir_only and cur_dir != self.last_sl_direction:
            return _no(
                f"Direction changed: original={self.last_sl_direction} current={cur_dir}"
            )

        required_score = self.last_sl_score + score_boost
        if cur_sc < required_score:
            return _no(
                f"Score {cur_sc} < required {required_score} "
                f"(original {self.last_sl_score} + boost {score_boost})"
            )

        if self.reentries_today >= max_reentries:
            return _no(
                f"Max re-entries reached ({self.reentries_today}/{max_reentries})"
            )

        return ReentryDecision(
            allowed=True,
            reason=f"Re-entry allowed: score={cur_sc} dir={cur_dir} cooldown_elapsed={int(elapsed)}s",
            cooldown_remaining_secs=0,
            score_required=required_score,
            original_score=self.last_sl_score,
            current_score=cur_sc,
            direction_intact=True,
        )

    def record_reentry(self) -> None:
        """Call when a re-entry trade is actually placed."""
        self.reentries_today += 1
        _log.info("[REENTRY] %s re-entry #%d placed", self.index_name, self.reentries_today)

    def reset_daily(self) -> None:
        """Call at the start of each trading day."""
        self.last_sl_ts        = None
        self.last_sl_direction = None
        self.last_sl_score     = 0
        self.reentries_today   = 0


def build_reentry_trackers(index_names: list[str]) -> dict[str, ReentryTracker]:
    """Convenience: build one ReentryTracker per index."""
    return {name: ReentryTracker(index_name=name) for name in index_names}


__all__ = [
    "ReentryDecision",
    "ReentryTracker",
    "build_reentry_trackers",
]

