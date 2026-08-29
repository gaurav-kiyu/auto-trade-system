"""Intraday performance feedback loop (Item 9 - v2.44).

Adapts signal thresholds and position sizing based on current session
win-rate quality - separate from the loss-based circuit breaker.

Config keys
-----------
  intraday_monitor_enabled          : bool   default true
  intraday_min_trades_to_adapt      : int    default 3
  intraday_defensive_win_rate       : float  default 0.25
  intraday_cautious_win_rate        : float  default 0.40
  intraday_defensive_size_mult      : float  default 0.50
  intraday_cautious_size_mult       : float  default 0.75
  intraday_defensive_score_boost    : int    default 10
  intraday_cautious_score_boost     : int    default 5
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class IntradayStats:
    trades_today:         int
    wins_today:           int
    losses_today:         int
    session_win_rate:     float   # wins / trades
    consecutive_losses:   int
    avg_pnl_today:        float
    adaptation_level:     str     # "NORMAL" | "CAUTIOUS" | "DEFENSIVE"


@dataclass(frozen=True)
class AdaptationParams:
    score_threshold_boost: int    # add to STRONG/MODERATE thresholds
    position_size_mult:    float  # multiply base lots
    reason:                str
    level:                 str    # "NORMAL" | "CAUTIOUS" | "DEFENSIVE"


_NORMAL_PARAMS    = AdaptationParams(0,  1.00, "Normal session", "NORMAL")
_CAUTIOUS_PARAMS  = AdaptationParams(5,  0.75, "Cautious: session win rate low", "CAUTIOUS")
_DEFENSIVE_PARAMS = AdaptationParams(10, 0.50, "Defensive: session win rate very low", "DEFENSIVE")


class IntradayPerformanceMonitor:

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self._cfg   = cfg or {}
        self._lock  = threading.RLock()
        self._session_date: str = ""
        self._reset_state()

    def _reset_state(self) -> None:
        self._trades:        list[tuple[float, bool]] = []  # (pnl, is_winner)
        self._consec_losses: int  = 0
        self._level:         str  = "NORMAL"
        self._last_level:    str  = "NORMAL"

    def _roll_session_if_new_day(self) -> None:
        """Self-resetting on IST calendar-date change, rather than relying on
        an external "day start" caller — reset_intraday_pnl() (the analogous
        hook for daily P&L) has no real call site anywhere in the live loop
        today, so a monitor that depended on an equivalent external trigger
        would silently never reset either."""
        from core.datetime_ist import now_ist
        today = now_ist().date().isoformat()
        if today != self._session_date:
            self._session_date = today
            self._reset_state()

    # ── Public API ─────────────────────────────────────────────────────────────

    def record_trade_close(
        self,
        pnl:        float,
        was_winner: bool,
    ) -> AdaptationParams:
        """Call after every trade close. Returns updated adaptation params."""
        with self._lock:
            self._roll_session_if_new_day()
            self._trades.append((float(pnl), bool(was_winner)))
            if was_winner:
                self._consec_losses = 0
            else:
                self._consec_losses += 1
            return self._compute_adaptation()

    def get_current_params(self) -> AdaptationParams:
        """Returns current adaptation. Call before each signal evaluation."""
        with self._lock:
            self._roll_session_if_new_day()
            return self._compute_adaptation()

    def reset_daily(self) -> None:
        """Call at trading day start."""
        with self._lock:
            self._reset_state()

    def get_stats(self) -> IntradayStats:
        """Returns current session stats for dashboard/Telegram."""
        with self._lock:
            self._roll_session_if_new_day()
            params = self._compute_adaptation()
            wins   = sum(1 for _, w in self._trades if w)
            n      = len(self._trades)
            total_pnl = sum(p for p, _ in self._trades)
            return IntradayStats(
                trades_today=n,
                wins_today=wins,
                losses_today=n - wins,
                session_win_rate=round(wins / n, 4) if n else 0.0,
                consecutive_losses=self._consec_losses,
                avg_pnl_today=round(total_pnl / n, 2) if n else 0.0,
                adaptation_level=params.level,
            )

    def update_config(self, cfg: dict[str, Any]) -> None:
        """Allow hot-reload of config."""
        with self._lock:
            self._cfg = cfg

    # ── Internal ──────────────────────────────────────────────────────────────

    def _compute_adaptation(self) -> AdaptationParams:
        c   = self._cfg
        if not c.get("intraday_monitor_enabled", True):
            return _NORMAL_PARAMS

        min_trades     = int(c.get("intraday_min_trades_to_adapt",   3))
        def_win_rate   = float(c.get("intraday_defensive_win_rate",  0.25))
        cau_win_rate   = float(c.get("intraday_cautious_win_rate",   0.40))
        def_mult       = float(c.get("intraday_defensive_size_mult", 0.50))
        cau_mult       = float(c.get("intraday_cautious_size_mult",  0.75))
        def_boost      = int(  c.get("intraday_defensive_score_boost", 10))
        cau_boost      = int(  c.get("intraday_cautious_score_boost",   5))

        n    = len(self._trades)
        if n < min_trades:
            return _NORMAL_PARAMS

        wins     = sum(1 for _, w in self._trades if w)
        win_rate = wins / n

        # Recovery: last 3 all won → relax one level
        if n >= 3 and all(w for _, w in self._trades[-3:]):
            if self._level == "DEFENSIVE":
                _log.info("[INTRADAY] Recovering: DEFENSIVE → CAUTIOUS (last 3 wins)")
                self._level = "CAUTIOUS"
            elif self._level == "CAUTIOUS":
                _log.info("[INTRADAY] Recovering: CAUTIOUS → NORMAL (last 3 wins)")
                self._level = "NORMAL"

        # Escalate based on win rate
        if win_rate < def_win_rate:
            self._level = "DEFENSIVE"
        elif win_rate < cau_win_rate:
            if self._level != "DEFENSIVE":
                self._level = "CAUTIOUS"
        elif self._level == "NORMAL":
            pass  # stay NORMAL

        reason = (
            f"Win rate {win_rate:.0%} over {n} trades "
            f"(d<{def_win_rate:.0%} c<{cau_win_rate:.0%})"
        )

        if self._level == "DEFENSIVE":
            return AdaptationParams(def_boost, def_mult, reason, "DEFENSIVE")
        if self._level == "CAUTIOUS":
            return AdaptationParams(cau_boost, cau_mult, reason, "CAUTIOUS")
        return _NORMAL_PARAMS


_monitor_lock = threading.Lock()
_monitor_instance: IntradayPerformanceMonitor | None = None


def get_intraday_monitor(cfg: dict[str, Any] | None = None) -> IntradayPerformanceMonitor:
    """Process-wide singleton so position_service.py (position sizing) and
    the signal-scoring pipeline (score threshold boost) observe the same
    session state without needing to be wired to each other directly.
    On first call, cfg seeds the instance; later calls refresh its config
    (update_config) if cfg is given, so a config reload takes effect.
    """
    global _monitor_instance
    with _monitor_lock:
        if _monitor_instance is None:
            _monitor_instance = IntradayPerformanceMonitor(cfg)
        elif cfg is not None:
            _monitor_instance.update_config(cfg)
        return _monitor_instance


def reset_intraday_monitor() -> None:
    """Test/day-start helper: drop the singleton so the next get_intraday_monitor()
    call starts a fresh session (no carried-over trades/consecutive-loss state)."""
    global _monitor_instance
    with _monitor_lock:
        _monitor_instance = None


__all__ = [
    "AdaptationParams",
    "IntradayPerformanceMonitor",
    "IntradayStats",
    "get_intraday_monitor",
    "reset_intraday_monitor",
]

