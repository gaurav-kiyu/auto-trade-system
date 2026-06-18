"""
Regime Transition Detector (v2.45 Item 4).

Detects when the market regime is in transition between states and provides
a score bonus/penalty at the moment of transition.

Transition conditions (all three must fire across the last N bars):
    CHOPPY → TRENDING   : ADX rising from <20 to >25 + MACD crosses zero
    TRENDING → CHOPPY   : ADX falling from >25 to <20 + VIX contracting
    ANY → VOLATILE      : VIX spikes > 20% in one bar

Public API
----------
    detect_transition(current_regime, prev_regime, adx_series,
                      vix, macd_hist_series, cfg) → TransitionSignal | None
    get_transition_score_adj(signal, cfg) → int

Config keys
-----------
    regime_transition_enabled  : bool  default false
    transition_score_bonus     : int   default 8
    transition_adx_look_bars   : int   default 3
    transition_vix_spike_pct   : float default 20.0
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TransitionSignal:
    from_regime:  str
    to_regime:    str
    confidence:   float   # 0.0-1.0
    score_bonus:  int     # positive = add to score, negative = subtract
    reason:       str


# ── Thread-safe VIX history tracker ──────────────────────────────────────────

class _VixHistoryTracker:
    """Thread-safe VIX history ring buffer for spike detection."""

    def __init__(self, max_size: int = 10) -> None:
        self._history: list[float] = []
        self._max_size = max_size
        self._lock = threading.RLock()

    def update(self, vix: float) -> None:
        if vix <= 0:
            return
        with self._lock:
            self._history.append(vix)
            if len(self._history) > self._max_size:
                self._history = self._history[-self._max_size:]

    def get_history(self) -> list[float]:
        with self._lock:
            return list(self._history)

    def __len__(self) -> int:
        with self._lock:
            return len(self._history)

    def reset(self) -> None:
        with self._lock:
            self._history.clear()


# Module-level singleton - preserves existing API while adding thread safety.
_vix_tracker = _VixHistoryTracker()


# ── Backward-compatible helpers ────────────────────────────────────────────────

def _update_vix_history(vix: float) -> None:
    _vix_tracker.update(vix)


def reset_vix_history() -> None:
    """Reset VIX history (useful for testing or session reset)."""
    _vix_tracker.reset()


# ── Transition detection ──────────────────────────────────────────────────────

def detect_transition(
    current_regime:    str,
    prev_regime:       str,
    adx_series:        list[float],
    vix:               float,
    macd_hist_series:  list[float],
    cfg:               dict[str, Any] | None = None,
) -> TransitionSignal | None:
    """
    Detect a regime transition and return a TransitionSignal if one is found.

    Args:
        current_regime:   current regime string (e.g. "TRENDING", "CHOPPY").
        prev_regime:      regime from the previous scan cycle.
        adx_series:       recent ADX values, newest last (min 3 values).
        vix:              current VIX level.
        macd_hist_series: recent MACD histogram values, newest last (min 3).
        cfg:              config dict.

    Returns:
        TransitionSignal if a transition is detected, else None.
    """
    c = cfg or {}
    if not c.get("regime_transition_enabled", False):
        return None

    bonus     = int(c.get("transition_score_bonus", 8))
    _ = int(c.get("transition_adx_look_bars", 3))  # lookback bars; used if needed
    vix_spike = float(c.get("transition_vix_spike_pct", 20.0))

    _update_vix_history(vix)

    if len(adx_series) < 2:
        return None

    adx_now  = adx_series[-1]
    adx_prev = adx_series[0]
    macd_now  = macd_hist_series[-1]  if macd_hist_series else 0.0
    macd_prev = macd_hist_series[-2]  if len(macd_hist_series) >= 2 else 0.0

    vix_history = _vix_tracker.get_history()

    # ── VIX spike → VOLATILE ──────────────────────────────────────────────
    if len(vix_history) >= 2:
        prev_vix = vix_history[-2]
        if prev_vix > 0:
            vix_chg_pct = (vix - prev_vix) / prev_vix * 100
            if vix_chg_pct >= vix_spike:
                return TransitionSignal(
                    from_regime  = current_regime,
                    to_regime    = "VOLATILE",
                    confidence   = min(1.0, vix_chg_pct / vix_spike / 2),
                    score_bonus  = -bonus,
                    reason       = f"VIX spike +{vix_chg_pct:.1f}% → VOLATILE",
                )

    # ── CHOPPY → TRENDING ────────────────────────────────────────────────
    adx_rising  = adx_now > 25 and adx_prev < 20
    macd_cross  = (macd_prev <= 0 and macd_now > 0) or (macd_prev >= 0 and macd_now < 0)
    if adx_rising and macd_cross and prev_regime in ("CHOPPY", "RANGING"):
        return TransitionSignal(
            from_regime  = prev_regime,
            to_regime    = "TRENDING",
            confidence   = min(1.0, (adx_now - 25) / 10.0 + 0.5),
            score_bonus  = bonus,
            reason       = f"ADX {adx_prev:.1f}→{adx_now:.1f} + MACD cross → TRENDING",
        )

    # ── TRENDING → CHOPPY ────────────────────────────────────────────────
    adx_falling = adx_now < 20 and adx_prev > 25
    if adx_falling and prev_regime in ("TRENDING", "STRONG_TREND"):
        return TransitionSignal(
            from_regime  = prev_regime,
            to_regime    = "CHOPPY",
            confidence   = min(1.0, (25 - adx_now) / 10.0 + 0.4),
            score_bonus  = -bonus,
            reason       = f"ADX {adx_prev:.1f}→{adx_now:.1f} → CHOPPY",
        )

    return None


def get_transition_score_adj(
    signal: TransitionSignal | None,
    cfg:    dict[str, Any] | None = None,
) -> int:
    """Return score delta from a transition signal (0 if None or disabled)."""
    c = cfg or {}
    if not c.get("regime_transition_enabled", False) or signal is None:
        return 0
    return signal.score_bonus
