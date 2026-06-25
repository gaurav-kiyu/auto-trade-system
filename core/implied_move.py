"""
Implied Move Calculator (v2.45 Item 2).

Computes the option-market's expected weekly and daily price move using the
ATM straddle price (call + put premium at ATM strike).

Public API
----------
    compute_implied_move(option_chain, spot, cfg) → ImpliedMove | None
    check_implied_move_gate(implied_move, signal_move_pct, direction, cfg)
        → tuple[bool, str]   (True = allowed, reason string)

Config keys
-----------
    implied_move_enabled           : bool  default false
    implied_move_min_edge_mult     : float default 1.2
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ImpliedMove:
    move_pct:         float   # % of spot  (weekly, from ATM straddle)
    move_points:      float   # absolute index points
    weekly_move_pct:  float   # same as move_pct (alias for clarity)
    daily_move_pct:   float   # weekly / sqrt(5)
    atm_call_premium: float
    atm_put_premium:  float
    atm_strike:       int


# ── Core formula ──────────────────────────────────────────────────────────────

def compute_implied_move(
    option_chain: dict[str, Any] | None,
    spot:         float,
    cfg:          dict[str, Any] | None = None,
) -> ImpliedMove | None:
    """
    Compute the market's expected weekly move from the ATM straddle price.

    Args:
        option_chain: dict with keys "calls" and "puts", each mapping
                      strike (int/str) → premium (float).
        spot:         current index spot price.
        cfg:          config dict (for enabled gate).

    Returns:
        ImpliedMove dataclass or None if data is missing / disabled.
    """
    c = cfg or {}
    if not c.get("implied_move_enabled", False):
        return None
    if option_chain is None or spot <= 0:
        return None

    calls: dict = option_chain.get("calls") or {}
    puts:  dict = option_chain.get("puts")  or {}
    if not calls or not puts:
        return None

    # Find ATM strike (closest to spot)
    all_strikes = sorted(
        set(int(k) for k in calls) & set(int(k) for k in puts)
    )
    if not all_strikes:
        return None

    atm = min(all_strikes, key=lambda k: abs(k - spot))

    try:
        call_prem = float(calls[atm])
        put_prem  = float(puts[atm])
    except (KeyError, ValueError, TypeError):
        return None

    straddle   = call_prem + put_prem
    move_pct   = straddle / spot * 100.0
    move_pts   = straddle
    daily_pct  = move_pct / math.sqrt(5)

    return ImpliedMove(
        move_pct        = round(move_pct,    3),
        move_points     = round(move_pts,    2),
        weekly_move_pct = round(move_pct,    3),
        daily_move_pct  = round(daily_pct,   3),
        atm_call_premium= round(call_prem,   2),
        atm_put_premium = round(put_prem,    2),
        atm_strike      = atm,
    )


def check_implied_move_gate(
    implied_move:   ImpliedMove | None,
    signal_move_pct: float,
    direction:      str,
    cfg:            dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """
    Gate entry: signal_move_pct must be >= implied_move_pct × min_edge_mult.

    Args:
        implied_move:    computed ImpliedMove (or None → gate passes).
        signal_move_pct: the expected move % implied by the signal's TP level.
        direction:       "CALL" or "PUT" (informational only).
        cfg:             config dict.

    Returns:
        (True, "")                         - gate passes
        (False, reason_string)             - soft block reason
    """
    c = cfg or {}
    if not c.get("implied_move_enabled", False) or implied_move is None:
        return True, ""

    mult      = float(c.get("implied_move_min_edge_mult", 1.2))
    required  = implied_move.weekly_move_pct * mult
    if signal_move_pct >= required:
        return True, ""

    reason = (
        f"implied_move_gate: signal needs {signal_move_pct:.2f}% move "
        f"but market implies {implied_move.weekly_move_pct:.2f}% "
        f"(min_edge={mult}x → need {required:.2f}%)"
    )
    return False, reason


def get_implied_move_score_adj(
    implied_move:   ImpliedMove | None,
    signal_move_pct: float,
    cfg:            dict[str, Any] | None = None,
) -> int:
    """
    Return a soft score penalty (-5) when signal move < implied move threshold.
    Returns 0 when gate passes or feature is disabled.
    """
    c = cfg or {}
    if not c.get("implied_move_enabled", False):
        return 0
    passed, _ = check_implied_move_gate(implied_move, signal_move_pct, "", c)
    return 0 if passed else -5


__all__ = [
    "ImpliedMove",
    "check_implied_move_gate",
    "compute_implied_move",
    "get_implied_move_score_adj",
]

