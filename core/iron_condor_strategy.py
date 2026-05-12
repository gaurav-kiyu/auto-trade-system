"""
Iron Condor Strategy Engine (v2.45 Item 11).

Sell OTM call spread + sell OTM put spread for net credit.
Profits when the underlying stays between the short strikes until expiry.

IMPORTANT: Iron Condor is a PREMIUM SELLING strategy.
    Net credit received = income upfront.
    Max profit = net_credit (if spot stays between short strikes).
    Max loss   = spread_width - net_credit.
    P&L is INVERTED vs buying strategies:
        Position value DECREASING = PROFIT (theta decay works for us).
        Stop fires when current_value >= stop_threshold.

Activation gates (ALL must pass):
  - ic_strategy_enabled = true
  - regime == CHOPPY AND adx < ic_max_adx AND vix < ic_max_vix AND dte >= ic_min_dte

Public API
----------
    build_iron_condor(spot, option_chain, cfg) → IronCondorPosition | None
    evaluate_ic_exit(position, current_call_spread_value,
                     current_put_spread_value, cfg) → ICExitDecision
    check_ic_conditions(regime, adx, vix, dte, cfg) → tuple[bool, str]

Config keys
-----------
    ic_strategy_enabled  : bool  default false
    ic_max_adx           : float default 18
    ic_max_vix           : float default 15
    ic_min_dte           : int   default 3
    ic_wing_width_steps  : int   default 2
    ic_profit_target     : float default 0.5  (close at 50% of max profit)
    ic_stop_mult         : float default 0.8  (stop at 80% of max loss)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class IronCondorPosition:
    # Call spread: sell lower call (SC), buy higher call (BC)
    call_short_strike: int
    call_long_strike:  int
    # Put spread: sell higher put (SP), buy lower put (BP)
    put_short_strike:  int
    put_long_strike:   int

    # Credits received (positive = income)
    call_spread_credit:  float   # premium_SC - premium_BC
    put_spread_credit:   float   # premium_SP - premium_BP
    net_credit:          float   # call_spread_credit + put_spread_credit

    # Risk profile
    spread_width:   float   # distance between short and long on either wing
    max_profit:     float   # = net_credit
    max_loss:       float   # = spread_width - net_credit
    expiry:         str


@dataclass
class ICExitDecision:
    action:  str    # "HOLD", "FULL_EXIT"
    reason:  str


# ── Condition check ───────────────────────────────────────────────────────────

def check_ic_conditions(
    regime: str,
    adx:    float,
    vix:    float,
    dte:    int,
    cfg:    dict[str, Any],
) -> tuple[bool, str]:
    """
    Check if Iron Condor entry conditions are met.

    Returns:
        (True, "")          — all conditions pass
        (False, reason)     — blocked
    """
    if not cfg.get("ic_strategy_enabled", False):
        return False, "ic_strategy_enabled=false"

    max_adx = float(cfg.get("ic_max_adx", 18))
    max_vix = float(cfg.get("ic_max_vix", 15))
    min_dte = int(cfg.get("ic_min_dte",   3))

    if regime not in ("CHOPPY", "RANGING"):
        return False, f"ic_regime: need CHOPPY, got {regime}"
    if adx >= max_adx:
        return False, f"ic_adx: {adx:.1f} >= {max_adx}"
    if vix >= max_vix:
        return False, f"ic_vix: {vix:.1f} >= {max_vix}"
    if dte < min_dte:
        return False, f"ic_dte: {dte} < {min_dte}"

    return True, f"ic_ok (adx={adx:.1f} vix={vix:.1f} dte={dte})"


# ── Builder ───────────────────────────────────────────────────────────────────

def _get_premium(chain_side: dict, strike: int) -> float | None:
    v = chain_side.get(strike) or chain_side.get(str(strike))
    if v is None:
        return None
    if isinstance(v, dict):
        return float(v.get("premium") or v.get("ltp") or 0.0)
    return float(v)


def build_iron_condor(
    spot:          float,
    option_chain:  dict[str, Any] | None,
    cfg:           dict[str, Any] | None = None,
) -> IronCondorPosition | None:
    """
    Build a symmetric Iron Condor from the ATM level.

    Structure:
        ATM + width_steps = call short strike (SC)
        ATM + 2×width_steps = call long strike (BC)
        ATM - width_steps = put short strike (SP)
        ATM - 2×width_steps = put long strike (BP)

    Args:
        spot:         current index spot price.
        option_chain: dict with "calls" and "puts" maps.
        cfg:          config dict.

    Returns:
        IronCondorPosition or None if data insufficient.
    """
    c = cfg or {}
    if option_chain is None:
        return None

    calls = option_chain.get("calls") or {}
    puts  = option_chain.get("puts")  or {}

    # Find ATM from the union of all available strikes
    all_k = sorted(set(int(k) for k in calls) | set(int(k) for k in puts))
    if not all_k:
        return None
    atm = min(all_k, key=lambda k: abs(k - spot))
    w   = int(c.get("ic_wing_width_steps", 2))

    # Call spread uses strikes strictly ABOVE ATM from the calls side
    calls_above = [k for k in sorted(int(k) for k in calls) if k > atm]
    # Put spread uses strikes strictly BELOW ATM from the puts side
    puts_below  = [k for k in reversed(sorted(int(k) for k in puts)) if k < atm]

    if len(calls_above) < w * 2 or len(puts_below) < w * 2:
        return None

    sc_k = calls_above[w - 1]       # w-th step above ATM  (short call)
    bc_k = calls_above[w * 2 - 1]   # 2w-th step above ATM (long call)
    sp_k = puts_below[w - 1]        # w-th step below ATM  (short put)
    bp_k = puts_below[w * 2 - 1]    # 2w-th step below ATM (long put)

    # Validate no duplicate strikes
    if sc_k == bc_k or sp_k == bp_k:
        return None

    sc_p = _get_premium(calls, sc_k)
    bc_p = _get_premium(calls, bc_k)
    sp_p = _get_premium(puts,  sp_k)
    bp_p = _get_premium(puts,  bp_k)

    if any(x is None for x in (sc_p, bc_p, sp_p, bp_p)):
        return None

    call_credit = sc_p - bc_p   # premium of short minus premium of long
    put_credit  = sp_p - bp_p
    net_credit  = call_credit + put_credit

    if net_credit <= 0:
        _log.debug("[IC] zero/negative net credit %.2f — skipping", net_credit)
        return None

    spread_width = float(bc_k - sc_k)   # width of one wing (call spread = put spread)

    return IronCondorPosition(
        call_short_strike = sc_k,
        call_long_strike  = bc_k,
        put_short_strike  = sp_k,
        put_long_strike   = bp_k,
        call_spread_credit= round(call_credit, 2),
        put_spread_credit = round(put_credit,  2),
        net_credit        = round(net_credit,  2),
        spread_width      = round(spread_width, 0),
        max_profit        = round(net_credit,  2),
        max_loss          = round(max(0.0, spread_width - net_credit), 2),
        expiry            = str(c.get("ic_expiry", "")),
    )


# ── Exit logic ────────────────────────────────────────────────────────────────

def evaluate_ic_exit(
    position:               IronCondorPosition,
    current_call_spread_val: float,
    current_put_spread_val:  float,
    cfg:                     dict[str, Any] | None = None,
) -> ICExitDecision:
    """
    Evaluate Iron Condor exit.

    INVERTED P&L: current_value decreasing = profit (we sold premium).
      Profit target: close when remaining value <= net_credit × (1 - ic_profit_target)
      Stop loss: close when remaining value >= max_loss × ic_stop_mult

    Args:
        position:               open IC position.
        current_call_spread_val: current value of the call spread (debit to close).
        current_put_spread_val:  current value of the put spread (debit to close).
        cfg:                     config dict.

    Returns:
        ICExitDecision.
    """
    c = cfg or {}
    profit_tgt = float(c.get("ic_profit_target", 0.5))
    stop_mult  = float(c.get("ic_stop_mult",     0.8))

    current_val = current_call_spread_val + current_put_spread_val

    # Stop: cost to close approaches max_loss
    stop_threshold = position.max_loss * stop_mult
    if position.max_loss > 0 and current_val >= stop_threshold:
        return ICExitDecision(
            action="FULL_EXIT",
            reason=f"ic_stop: close_cost={current_val:.1f} >= {stop_threshold:.1f}",
        )

    # Profit target: remaining value <= net_credit × (1 - target_pct)
    profit_threshold = position.net_credit * (1.0 - profit_tgt)
    if current_val <= profit_threshold:
        return ICExitDecision(
            action="FULL_EXIT",
            reason=f"ic_profit: close_cost={current_val:.1f} <= {profit_threshold:.1f}",
        )

    return ICExitDecision(action="HOLD", reason="within bounds")
