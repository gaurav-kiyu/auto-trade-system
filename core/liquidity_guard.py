"""
Pre-entry liquidity quality checks (Item 1 - v2.44).

Ensures options are tradeable before entry is attempted.
Runs synchronously in the entry gate; never raises.

Config keys
-----------
  liquidity_guard_enabled   : bool   default true
   max_entry_spread_pct      : float  default 3.0   (ask-bid)/mid*100
  min_option_premium        : float  default 5.0   rejects worthless deep-OTM
  min_entry_oi              : int    default 100
  min_entry_volume          : int    default 10
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

_DEF_MAX_SPREAD_PCT  = 3.0
_DEF_MIN_PREMIUM     = 5.0
_DEF_MIN_OI          = 100
_DEF_MIN_VOLUME      = 10


@dataclass(frozen=True)
class LiquidityCheck:
    passed:        bool
    spread_pct:    float           # (ask-bid)/mid * 100
    bid:           float
    ask:           float
    mid:           float
    oi:            int
    volume:        int
    reject_reason: str | None      # None if passed


def check_entry_liquidity(
    bid:    float,
    ask:    float,
    oi:     int,
    volume: int,
    cfg:    dict[str, Any] | None = None,
) -> LiquidityCheck:
    """
    Return LiquidityCheck.passed=True only if ALL conditions hold:
      1. bid > 0 and ask > 0
      2. ask > bid
      3. mid >= min_option_premium
      4. spread_pct <= max_entry_spread_pct
      5. oi >= min_oi_threshold
      6. volume >= min_volume_threshold

    If liquidity_guard_enabled=false: always passes.
    Never raises - returns a failed check on any error.
    """
    c = cfg or {}
    try:
        bid    = float(bid    or 0.0)
        ask    = float(ask    or 0.0)
        oi     = int(oi       or 0)
        volume = int(volume   or 0)
    except (TypeError, ValueError):
        return LiquidityCheck(False, 0.0, 0.0, 0.0, 0.0, 0, 0, "Invalid quote data")

    if not c.get("liquidity_guard_enabled", True):
        mid = (bid + ask) / 2.0 if (bid + ask) > 0 else 0.0
        return LiquidityCheck(True, 0.0, bid, ask, mid, oi, volume, None)

    max_spread = float(c.get("max_entry_spread_pct",  _DEF_MAX_SPREAD_PCT))
    min_prem   = float(c.get("min_option_premium",    _DEF_MIN_PREMIUM))
    min_oi     = int(  c.get("min_entry_oi",      _DEF_MIN_OI))
    min_vol    = int(  c.get("min_entry_volume",  _DEF_MIN_VOLUME))

    # Check 1: valid quotes
    if bid <= 0:
        return LiquidityCheck(False, 0.0, bid, ask, 0.0, oi, volume, "No bid quote")
    if ask <= 0:
        return LiquidityCheck(False, 0.0, bid, ask, 0.0, oi, volume, "No ask quote")

    # Check 2: non-inverted market
    if ask <= bid:
        return LiquidityCheck(False, 0.0, bid, ask, 0.0, oi, volume, "Inverted market (ask<=bid)")

    mid        = (bid + ask) / 2.0
    spread_pct = (ask - bid) / mid * 100.0 if mid > 0 else 999.0

    # Check 3: premium floor
    if mid < min_prem:
        return LiquidityCheck(False, spread_pct, bid, ask, mid, oi, volume,
                               f"Premium {mid:.2f} below minimum {min_prem}")

    # Check 4: spread width
    if spread_pct > max_spread:
        return LiquidityCheck(False, spread_pct, bid, ask, mid, oi, volume,
                               f"Spread {spread_pct:.1f}% > max {max_spread}%")

    # Check 5: OI
    if oi < min_oi:
        return LiquidityCheck(False, spread_pct, bid, ask, mid, oi, volume,
                               f"OI {oi} < minimum {min_oi}")

    # Check 6: volume
    if volume < min_vol:
        return LiquidityCheck(False, spread_pct, bid, ask, mid, oi, volume,
                               f"Volume {volume} < minimum {min_vol}")

    return LiquidityCheck(True, round(spread_pct, 2), bid, ask, round(mid, 2), oi, volume, None)


__all__ = [
    "LiquidityCheck",
    "check_entry_liquidity",
]

