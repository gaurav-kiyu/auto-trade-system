"""
Gamma Exposure (GEX) Analyzer (v2.45 Item 3).

Computes net dealer gamma exposure across all option strikes and identifies
the gamma-flip level (strike where net GEX crosses zero).

Formula
-------
    GEX_strike = (call_OI - put_OI) × gamma × lot_size × spot² / 100
    Net_GEX    = Σ GEX_strike across all strikes

    Black-Scholes gamma:
        d1    = (ln(S/K) + (r + σ²/2)·T) / (σ·√T)
        gamma = φ(d1) / (S·σ·√T)
    where φ is the standard normal PDF.

    For options buying with IV approximation (σ ≈ VIX/100):
        T in years (DTE / 365)

Public API
----------
    compute_gex(option_chain, spot, cfg) → GEXResult | None
    get_gex_score_adj(gex_result, direction, cfg) → int

Config keys
-----------
    gex_enabled            : bool  default false
    gex_lot_size           : int   default 50
    gex_dte                : int   default 7
    gex_vix_proxy          : float default 15.0  (σ proxy when VIX unknown)
    gex_long_gamma_adj     : int   default -5
    gex_short_gamma_adj    : int   default 5
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)

_SQRT_2PI = math.sqrt(2 * math.pi)


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StrikeGEX:
    strike:  int
    gex:     float   # signed GEX contribution


@dataclass
class GEXResult:
    net_gex:      float          # total signed GEX (positive = long gamma)
    gamma_flip:   float          # strike where GEX crosses zero (0 if none found)
    regime:       str            # "LONG_GAMMA" or "SHORT_GAMMA"
    top_strikes:  list[StrikeGEX] = field(default_factory=list)


# ── Math helpers ──────────────────────────────────────────────────────────────

def _phi(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _bs_gamma(spot: float, strike: float, sigma: float, T: float) -> float:
    """Black-Scholes gamma for a European option."""
    if spot <= 0 or strike <= 0 or sigma <= 0 or T <= 0:
        return 0.0
    try:
        d1 = (math.log(spot / strike) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
        return _phi(d1) / (spot * sigma * math.sqrt(T))
    except (ValueError, TypeError, ArithmeticError, OverflowError):
        return 0.0


# ── Core computation ──────────────────────────────────────────────────────────

def compute_gex(
    option_chain: dict[str, Any] | None,
    spot:         float,
    cfg:          dict[str, Any] | None = None,
) -> GEXResult | None:
    """
    Compute net GEX and gamma-flip strike from the option chain.

    Args:
        option_chain: dict with:
            "calls": {strike: {"oi": float, "premium": float}}
            "puts":  {strike: {"oi": float, "premium": float}}
            (also accepts simplified {strike: premium} maps)
        spot:  current index spot price.
        cfg:   config dict.

    Returns:
        GEXResult or None if disabled or data missing.
    """
    c = cfg or {}
    if not c.get("gex_enabled", False):
        return None
    if option_chain is None or spot <= 0:
        return None

    calls_raw = option_chain.get("calls") or {}
    puts_raw  = option_chain.get("puts")  or {}
    if not calls_raw and not puts_raw:
        return None

    lot_size = int(c.get("gex_lot_size", 50))
    dte      = int(c.get("gex_dte", 7))
    vix_px   = float(c.get("gex_vix_proxy", 15.0))
    sigma    = vix_px / 100.0
    T        = max(dte, 1) / 365.0

    def _extract_oi(chain: dict, strike: int) -> float:
        v = chain.get(strike) or chain.get(str(strike)) or 0
        if isinstance(v, dict):
            return float(v.get("oi") or v.get("OI") or 0)
        return 0.0   # simplified map has no OI

    all_strikes = sorted(
        set(int(k) for k in calls_raw) | set(int(k) for k in puts_raw)
    )
    if not all_strikes:
        return None

    strike_gex_list: list[StrikeGEX] = []
    for k in all_strikes:
        call_oi = _extract_oi(calls_raw, k)
        put_oi  = _extract_oi(puts_raw,  k)
        gamma   = _bs_gamma(spot, float(k), sigma, T)
        gex     = (call_oi - put_oi) * gamma * lot_size * spot * spot / 100.0
        strike_gex_list.append(StrikeGEX(strike=k, gex=gex))

    net_gex = sum(s.gex for s in strike_gex_list)

    # Find gamma-flip: strike where cumulative GEX changes sign
    gamma_flip = 0.0
    if len(strike_gex_list) >= 2:
        cumulative = 0.0
        prev_k     = 0
        for sg in sorted(strike_gex_list, key=lambda x: x.strike):
            cumulative += sg.gex
            if prev_k > 0 and (
                (cumulative >= 0 and net_gex < 0) or
                (cumulative <= 0 and net_gex > 0)
            ):
                gamma_flip = float(sg.strike)
                break
            prev_k = sg.strike

    top5 = sorted(strike_gex_list, key=lambda x: abs(x.gex), reverse=True)[:5]
    regime = "LONG_GAMMA" if net_gex >= 0 else "SHORT_GAMMA"

    return GEXResult(
        net_gex     = round(net_gex, 2),
        gamma_flip  = round(gamma_flip, 0),
        regime      = regime,
        top_strikes = top5,
    )


def get_gex_score_adj(
    gex_result: GEXResult | None,
    direction:  str,
    cfg:        dict[str, Any] | None = None,
) -> int:
    """
    Return score delta based on GEX regime:
        LONG_GAMMA  → dampened moves → penalise momentum signals
        SHORT_GAMMA → accelerated moves → bonus for breakout/momentum signals

    Args:
        gex_result: from compute_gex() (None → returns 0).
        direction:  "CALL" or "PUT".
        cfg:        config dict.
    """
    c = cfg or {}
    if not c.get("gex_enabled", False) or gex_result is None:
        return 0
    if gex_result.regime == "LONG_GAMMA":
        return int(c.get("gex_long_gamma_adj", -5))
    return int(c.get("gex_short_gamma_adj", 5))
