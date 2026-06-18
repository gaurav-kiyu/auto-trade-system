"""
Scale-In Entry Manager (v2.45 Item 9).

Splits a signal entry into two legs to improve average entry price on
pullbacks.  Default-disabled; requires explicit config opt-in.

Logic
-----
    On signal (score >= scalein_min_score):
        Leg 1: buy scalein_first_pct% of total lots
        Set trigger price:
            CALL: entry_price × (1 - scalein_pullback_pct)
            PUT:  entry_price × (1 + scalein_pullback_pct)
        Set timeout: entry_ts + scalein_timeout_mins

    Each scan cycle for open scale-in states:
        If price ≤ trigger (CALL) or ≥ trigger (PUT) → Leg 2 fills
        If timeout expired → Leg 2 fills at market (do not miss trade)

Public API
----------
    ScaleInState - dataclass representing a pending second leg
    ScaleInManager.create_state(trade_id, entry_price, total_lots, direction, cfg) → ScaleInState
    ScaleInManager.should_fill_leg2(state, current_price, current_time) → bool
    ScaleInManager.compute_avg_price(state, leg2_fill_price) → float
    ScaleInManager.leg1_lots(total_lots, cfg) → int
    ScaleInManager.leg2_lots(total_lots, cfg) → int

Config keys
-----------
    scalein_enabled          : bool  default false
    scalein_first_pct        : float default 0.5
    scalein_pullback_pct     : float default 0.003
    scalein_timeout_mins     : int   default 5
    scalein_min_score        : int   default 80
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class ScaleInState:
    trade_id:       str
    entry_price:    float
    direction:      str          # "CALL" or "PUT"
    trigger_price:  float        # price at which Leg 2 fires
    timeout_ts:     float        # time.time() deadline
    leg1_lots:      int
    leg2_lots:      int
    completed:      bool = False # True once Leg 2 has been filled
    leg2_fill_price: float = 0.0


# ── Manager ───────────────────────────────────────────────────────────────────

class ScaleInManager:
    """Stateless helper - state objects are persisted externally."""

    @staticmethod
    def is_enabled(cfg: dict[str, Any]) -> bool:
        return bool(cfg.get("scalein_enabled", False))

    @staticmethod
    def qualifies(score: int, cfg: dict[str, Any]) -> bool:
        """Returns True if the signal score warrants a scale-in entry."""
        if not ScaleInManager.is_enabled(cfg):
            return False
        return score >= int(cfg.get("scalein_min_score", 80))

    @staticmethod
    def leg1_lots(total_lots: int, cfg: dict[str, Any]) -> int:
        """Leg 1 lot count (scalein_first_pct × total, min 1)."""
        pct = float(cfg.get("scalein_first_pct", 0.5))
        return max(1, int(total_lots * pct))

    @staticmethod
    def leg2_lots(total_lots: int, cfg: dict[str, Any]) -> int:
        """Leg 2 lot count (remainder after Leg 1, min 1)."""
        l1 = ScaleInManager.leg1_lots(total_lots, cfg)
        return max(1, total_lots - l1)

    @staticmethod
    def create_state(
        trade_id:    str,
        entry_price: float,
        total_lots:  int,
        direction:   str,
        cfg:         dict[str, Any],
    ) -> ScaleInState:
        """
        Create a pending scale-in state after Leg 1 fills.

        Args:
            trade_id    : unique trade identifier.
            entry_price : Leg 1 fill price.
            total_lots  : total lots for the complete position.
            direction   : "CALL" or "PUT".
            cfg         : config dict.

        Returns:
            ScaleInState with trigger_price and timeout set.
        """
        pb_pct   = float(cfg.get("scalein_pullback_pct",  0.003))
        t_mins   = int(cfg.get("scalein_timeout_mins",    5))
        l1_lots  = ScaleInManager.leg1_lots(total_lots, cfg)
        l2_lots  = ScaleInManager.leg2_lots(total_lots, cfg)
        now      = time.time()

        if direction.upper() == "CALL":
            trigger = entry_price * (1.0 - pb_pct)
        else:
            trigger = entry_price * (1.0 + pb_pct)

        return ScaleInState(
            trade_id      = trade_id,
            entry_price   = entry_price,
            direction     = direction.upper(),
            trigger_price = round(trigger, 2),
            timeout_ts    = now + t_mins * 60,
            leg1_lots     = l1_lots,
            leg2_lots     = l2_lots,
        )

    @staticmethod
    def should_fill_leg2(
        state:        ScaleInState,
        current_price: float,
        current_time:  float | None = None,
    ) -> bool:
        """
        Check whether Leg 2 should fill now.

        Returns True if:
          - Price has reached trigger level, OR
          - Timeout has expired (force-fill at market)
        """
        if state.completed:
            return False
        t = current_time if current_time is not None else time.time()
        if t >= state.timeout_ts:
            _log.debug("[SCALEIN] %s timeout expired → force Leg 2", state.trade_id)
            return True
        if state.direction == "CALL" and current_price <= state.trigger_price:
            return True
        if state.direction == "PUT" and current_price >= state.trigger_price:
            return True
        return False

    @staticmethod
    def compute_avg_price(state: ScaleInState, leg2_fill: float) -> float:
        """
        Compute the weighted average fill price across both legs.

        Args:
            state       : ScaleInState (with leg1_lots).
            leg2_fill   : fill price of Leg 2.

        Returns:
            Weighted average price.
        """
        total = state.leg1_lots + state.leg2_lots
        if total == 0:
            return leg2_fill
        return round(
            (state.entry_price * state.leg1_lots + leg2_fill * state.leg2_lots) / total,
            2,
        )
