"""
Straddle / Strangle Strategy Engine (v2.45 Item 10).

Buy ATM call + ATM put (straddle) or OTM call + OTM put (strangle) when
market direction is genuinely uncertain (low IV + choppy regime or event day).

IMPORTANT: This is a DEBIT strategy (paying premium upfront).
Max loss = total_debit (if spot expires exactly at ATM).

Activation gates (all must pass):
  - straddle_strategy_enabled = true
  - Event day (event_calendar flag) AND iv_rank < straddle_max_iv_rank  OR
    ADX < 20 AND VIX < 15 AND regime = CHOPPY

Public API
----------
    build_straddle(spot, option_chain, cfg) → StraddlePosition | None
    build_strangle(spot, option_chain, cfg) → StraddlePosition | None
    evaluate_straddle_exit(position, current_call_prem, current_put_prem, cfg)
        → StraddleExitDecision
    check_straddle_conditions(regime, adx, vix, iv_rank, is_event_day, cfg)
        → tuple[bool, str]

Config keys
-----------
    straddle_strategy_enabled   : bool  default false
    straddle_max_iv_rank        : float default 20
    straddle_target_mult        : float default 1.5
    straddle_stop_mult          : float default 0.6
    straddle_close_both_on_target: bool default false
    strangle_width_steps        : int   default 2
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from core.strategy.config import get_strategy_cfg

_log = logging.getLogger(__name__)


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class StraddlePosition:
    call_strike:    int
    put_strike:     int
    expiry:         str
    call_premium:   float
    put_premium:    float
    total_debit:    float
    breakeven_up:   float   # spot + total_debit
    breakeven_down: float   # spot - total_debit
    max_loss:       float   # total_debit (debit strategy)
    spot_at_entry:  float
    strategy_type:  str     # "STRADDLE" or "STRANGLE"
    lot_size:       int = 1


@dataclass
class StraddleExitDecision:
    action:   str    # "HOLD", "PARTIAL_EXIT", "FULL_EXIT"
    reason:   str
    exit_leg: str    # "CALL", "PUT", "BOTH"


# ── Condition check ───────────────────────────────────────────────────────────

def check_straddle_conditions(
    regime:       str,
    adx:          float,
    vix:          float,
    iv_rank:      float,
    is_event_day: bool,
    cfg:          dict[str, Any],
) -> tuple[bool, str]:
    """
    Check if straddle entry conditions are met.

    Returns:
        (True, "")                  — conditions met
        (False, reason_string)      — blocked with reason
    """
    sc = get_strategy_cfg(cfg, "straddle")
    if not sc.get("enabled", False):
        return False, "straddle_strategy_enabled=false"

    max_iv = float(sc.get("max_iv_rank", 20))

    # Path 1: Event day + low IV
    if is_event_day and iv_rank < max_iv:
        return True, f"event_day + iv_rank={iv_rank:.0f}<{max_iv}"

    # Path 2: Genuine directionless market
    if regime in ("CHOPPY", "RANGING") and adx < 20 and vix < 15:
        if iv_rank < max_iv:
            return True, f"choppy_regime + adx={adx:.0f}<20 + vix={vix:.0f}<15"

    return False, f"conditions not met (regime={regime} adx={adx:.1f} vix={vix:.1f} iv={iv_rank:.0f})"


# ── Builders ──────────────────────────────────────────────────────────────────

def _find_atm(option_chain: dict, spot: float) -> int | None:
    calls = option_chain.get("calls") or {}
    puts  = option_chain.get("puts")  or {}
    strikes = sorted(set(int(k) for k in calls) & set(int(k) for k in puts))
    if not strikes:
        return None
    return min(strikes, key=lambda k: abs(k - spot))


def _get_premium(chain_side: dict, strike: int) -> float | None:
    v = chain_side.get(strike) or chain_side.get(str(strike))
    if v is None:
        return None
    if isinstance(v, dict):
        return float(v.get("premium") or v.get("ltp") or 0.0)
    return float(v)


def build_straddle(
    spot:          float,
    option_chain:  dict[str, Any] | None,
    cfg:           dict[str, Any] | None = None,
) -> StraddlePosition | None:
    """
    Build an ATM straddle position.

    Args:
        spot:         current index spot price.
        option_chain: dict with "calls" and "puts" maps.
        cfg:          config dict.

    Returns:
        StraddlePosition or None if chain data is insufficient.
    """
    c = cfg or {}
    sc = get_strategy_cfg(c, "straddle")
    if option_chain is None:
        return None

    atm = _find_atm(option_chain, spot)
    if atm is None:
        return None

    calls = option_chain.get("calls") or {}
    puts  = option_chain.get("puts")  or {}
    cp    = _get_premium(calls, atm)
    pp    = _get_premium(puts,  atm)
    if cp is None or pp is None:
        return None

    total_debit = cp + pp
    lot_size    = int(c.get("gex_lot_size", 50))  # reuse lot_size config
    expiry      = str(sc.get("expiry", ""))

    return StraddlePosition(
        call_strike    = atm,
        put_strike     = atm,
        expiry         = expiry,
        call_premium   = round(cp, 2),
        put_premium    = round(pp, 2),
        total_debit    = round(total_debit, 2),
        breakeven_up   = round(spot + total_debit, 2),
        breakeven_down = round(spot - total_debit, 2),
        max_loss       = round(total_debit, 2),
        spot_at_entry  = round(spot, 2),
        strategy_type  = "STRADDLE",
        lot_size       = lot_size,
    )


def build_strangle(
    spot:          float,
    option_chain:  dict[str, Any] | None,
    cfg:           dict[str, Any] | None = None,
) -> StraddlePosition | None:
    """
    Build an OTM strangle using ATM ± strangle_width_steps strikes.

    Args:
        spot:         current index spot price.
        option_chain: dict with "calls" and "puts" maps.
        cfg:          config dict.

    Returns:
        StraddlePosition (strategy_type="STRANGLE") or None.
    """
    c = cfg or {}
    sc = get_strategy_cfg(c, "strangle")
    if option_chain is None:
        return None

    calls = option_chain.get("calls") or {}
    puts  = option_chain.get("puts")  or {}

    # Find ATM from the union of all available strikes
    all_k = sorted(set(int(k) for k in calls) | set(int(k) for k in puts))
    if not all_k:
        return None
    atm   = min(all_k, key=lambda k: abs(k - spot))
    width = int(sc.get("width_steps", 2))

    # OTM call: w-th strike strictly above ATM in the calls side
    calls_above = [k for k in sorted(int(k) for k in calls) if k > atm]
    # OTM put: w-th strike strictly below ATM in the puts side
    puts_below  = [k for k in reversed(sorted(int(k) for k in puts)) if k < atm]

    if len(calls_above) < width or len(puts_below) < width:
        return None

    call_k = calls_above[width - 1]
    put_k  = puts_below[width - 1]

    cp = _get_premium(calls, call_k)
    pp = _get_premium(puts,  put_k)
    if cp is None or pp is None:
        return None

    total_debit = cp + pp
    lot_size    = int(c.get("gex_lot_size", 50))
    expiry      = str(c.get("straddle_expiry", ""))

    return StraddlePosition(
        call_strike    = call_k,
        put_strike     = put_k,
        expiry         = expiry,
        call_premium   = round(cp, 2),
        put_premium    = round(pp, 2),
        total_debit    = round(total_debit, 2),
        breakeven_up   = round(spot + total_debit, 2),
        breakeven_down = round(spot - total_debit, 2),
        max_loss       = round(total_debit, 2),
        spot_at_entry  = round(spot, 2),
        strategy_type  = "STRANGLE",
        lot_size       = lot_size,
    )


# ── Exit logic ────────────────────────────────────────────────────────────────

def evaluate_straddle_exit(
    position:         StraddlePosition,
    current_call_prem: float,
    current_put_prem:  float,
    cfg:               dict[str, Any] | None = None,
) -> StraddleExitDecision:
    """
    Evaluate whether to exit a straddle/strangle position.

    Exit conditions:
      - Profit: either leg > total_debit × straddle_target_mult → exit that leg
        (or both if straddle_close_both_on_target=true)
      - Stop:   current_value < total_debit × straddle_stop_mult → FULL_EXIT

    Args:
        position:          open straddle position.
        current_call_prem: current ATM call premium.
        current_put_prem:  current ATM put premium.
        cfg:               config dict.

    Returns:
        StraddleExitDecision with action and exit_leg.
    """
    sc = get_strategy_cfg(cfg or {}, "straddle")
    tgt_mult  = float(sc.get("target_mult", 1.5))
    stop_mult = float(sc.get("stop_mult",   0.6))
    close_both= bool(sc.get("close_both_on_target", False))

    current_value = current_call_prem + current_put_prem
    total_debit   = position.total_debit

    # Stop check first
    if total_debit > 0 and current_value < total_debit * stop_mult:
        return StraddleExitDecision(
            action="FULL_EXIT", exit_leg="BOTH",
            reason=f"stop: value={current_value:.1f} < {total_debit * stop_mult:.1f}",
        )

    # Profit check
    target = total_debit * tgt_mult
    if current_call_prem > target:
        leg = "BOTH" if close_both else "CALL"
        return StraddleExitDecision(
            action="FULL_EXIT", exit_leg=leg,
            reason=f"call_target: call={current_call_prem:.1f} > {target:.1f}",
        )
    if current_put_prem > target:
        leg = "BOTH" if close_both else "PUT"
        return StraddleExitDecision(
            action="FULL_EXIT", exit_leg=leg,
            reason=f"put_target: put={current_put_prem:.1f} > {target:.1f}",
        )

    return StraddleExitDecision(action="HOLD", exit_leg="", reason="within bounds")
