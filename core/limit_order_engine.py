"""
Limit Order Engine (v2.45 Item 12).

Computes limit prices and simulates fills for paper mode, and provides
pricing logic for live limit orders.

Pricing modes
-------------
    AGGRESSIVE : bid + (ask-bid) × 0.70  (fills quickly, pays up)
    PASSIVE    : bid + (ask-bid) × 0.30  (saves premium, may miss)
    ADAPTIVE   : starts at PASSIVE, steps toward ask every
                 limit_step_interval_secs until limit_timeout_secs

Paper fill simulation:
    Fills if market mid-price ≤ limit_price (conservative sim).
    After limit_timeout_secs: cancel + log miss.

Public API
----------
    compute_limit_price(bid, ask, mode, elapsed_secs, cfg) → float
    simulate_paper_fill(bid, ask, limit_price, elapsed_secs, cfg)
        → LimitOrderResult

Config keys
-----------
    limit_order_enabled          : bool  default false
    limit_order_mode             : str   default "ADAPTIVE"
    limit_step_pct               : float default 0.05
    limit_step_interval_secs     : int   default 5
    limit_timeout_secs           : int   default 30
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

_VALID_MODES = {"AGGRESSIVE", "PASSIVE", "ADAPTIVE"}


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class LimitOrderResult:
    filled:            bool
    fill_price:        float   # 0.0 if not filled
    limit_price:       float
    elapsed_secs:      float
    timed_out:         bool
    slippage_vs_limit: float   # fill_price - limit_price (0 if not filled)


# ── Pricing ───────────────────────────────────────────────────────────────────

def compute_limit_price(
    bid:          float,
    ask:          float,
    mode:         str,
    elapsed_secs: float = 0.0,
    cfg:          dict[str, Any] | None = None,
) -> float:
    """
    Compute the limit price for a buy order.

    Args:
        bid:          current best bid.
        ask:          current best ask.
        mode:         "AGGRESSIVE", "PASSIVE", or "ADAPTIVE".
        elapsed_secs: seconds since order was placed (for ADAPTIVE).
        cfg:          config dict.

    Returns:
        Limit price as float.
    """
    c = cfg or {}
    spread = max(0.0, ask - bid)

    m = (mode or "ADAPTIVE").upper()
    if m not in _VALID_MODES:
        m = "ADAPTIVE"

    if m == "AGGRESSIVE":
        frac = 0.70
    elif m == "PASSIVE":
        frac = 0.30
    else:  # ADAPTIVE
        step_pct = float(c.get("limit_step_pct",          0.05))
        interval = float(c.get("limit_step_interval_secs", 5.0))
        float(c.get("limit_timeout_secs",       30.0))
        steps    = math.floor(elapsed_secs / max(interval, 1)) if interval > 0 else 0
        frac     = 0.30 + steps * step_pct
        frac     = min(1.0, frac)   # cap at ask

    return round(bid + spread * frac, 2)


def simulate_paper_fill(
    bid:          float,
    ask:          float,
    limit_price:  float,
    elapsed_secs: float = 0.0,
    cfg:          dict[str, Any] | None = None,
) -> LimitOrderResult:
    """
    Simulate paper-mode limit fill.

    Fill condition: mid_price <= limit_price (conservative).
    Timeout condition: elapsed >= limit_timeout_secs → cancel.

    Args:
        bid:          current best bid.
        ask:          current best ask.
        limit_price:  the limit price submitted.
        elapsed_secs: time since order placement.
        cfg:          config dict.

    Returns:
        LimitOrderResult (filled=False + timed_out=True on cancel).
    """
    c = cfg or {}
    timeout = float(c.get("limit_timeout_secs", 30.0))

    if elapsed_secs >= timeout:
        return LimitOrderResult(
            filled=False, fill_price=0.0, limit_price=limit_price,
            elapsed_secs=elapsed_secs, timed_out=True, slippage_vs_limit=0.0,
        )

    mid = (bid + ask) / 2.0
    if mid <= limit_price:
        fill = min(limit_price, ask)  # fill at limit or better
        return LimitOrderResult(
            filled=True, fill_price=round(fill, 2), limit_price=limit_price,
            elapsed_secs=elapsed_secs, timed_out=False,
            slippage_vs_limit=round(fill - limit_price, 2),
        )

    return LimitOrderResult(
        filled=False, fill_price=0.0, limit_price=limit_price,
        elapsed_secs=elapsed_secs, timed_out=False, slippage_vs_limit=0.0,
    )


__all__ = [
    "LimitOrderResult",
    "compute_limit_price",
    "simulate_paper_fill",
]

