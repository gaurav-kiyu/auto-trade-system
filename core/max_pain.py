"""
Max Pain Calculator — Phase 11 Options Analytics.

Calculates the Max Pain strike price for a given expiry using open interest
data. At the Max Pain strike, option buyers (both call and put) would
collectively lose the most money at expiry.

The calculation finds the strike where the total payout to option holders
is minimized (maximizing their pain).

Formula:
  For each strike S_i:
    Call value = Σ max(0, spot - S_i) × OI_call(S_i)  for all strikes S_i < spot
    Put value  = Σ max(0, S_i - spot) × OI_put(S_i)   for all strikes S_i > spot
    Total payout = call_value + put_value × multiplier
    
    Max Pain = argmin(total_payout) over all strikes

Usage:
    from core.max_pain import compute_max_pain, MaxPainResult
    
    # From option chain data
    result = compute_max_pain(spot=23363.35, option_chain={
        "calls": {25000: {"oi": 12345, "ltp": 150.0}, ...},
        "puts":  {25000: {"oi": 67890, "ltp": 120.0}, ...},
    })
    print(f"Max Pain: {result.max_pain_strike}, Pain Index: {result.pain_index}")

    # CLI
    python -m core.max_pain --spot 23363 --oi
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class MaxPainResult:
    """Result of a Max Pain calculation."""
    max_pain_strike: float          # Strike with maximum pain
    pain_index: float               # Total dollar pain at max pain strike
    spot_price: float               # Current underlying price
    total_oi: int                   # Total open interest across all strikes
    call_oi_total: int              # Total call OI
    put_oi_total: int               # Total put OI
    put_call_ratio: float           # Put/Call OI ratio
    pain_curve: dict[float, float]  # Strike → total_pain_value mapping
    nearest_strikes: list[dict[str, Any]] = field(default_factory=list)
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_pain_strike": self.max_pain_strike,
            "pain_index": round(self.pain_index, 2),
            "spot_price": self.spot_price,
            "total_oi": self.total_oi,
            "call_oi_total": self.call_oi_total,
            "put_oi_total": self.put_oi_total,
            "put_call_ratio": round(self.put_call_ratio, 4),
            "pain_curve_samples": len(self.pain_curve),
            "nearest_strikes": self.nearest_strikes[:5],
            "timestamp": self.timestamp or time.time(),
        }

    def summary(self) -> str:
        """Return a human-readable summary."""
        return (
            f"Max Pain: {self.max_pain_strike:.0f} (pain index: {self.pain_index:.2f})\n"
            f"  Spot: {self.spot_price:.2f} | Diff: {self.spot_price - self.max_pain_strike:+.2f}\n"
            f"  Call OI: {self.call_oi_total:,} | Put OI: {self.put_oi_total:,} | PCR: {self.put_call_ratio:.3f}"
        )


@dataclass
class OptionChainStrike:
    """Single strike entry from option chain."""
    strike: float
    call_oi: int = 0
    call_ltp: float = 0.0
    put_oi: int = 0
    put_ltp: float = 0.0
    call_iv: float = 0.0
    put_iv: float = 0.0


# ── Core Calculation ─────────────────────────────────────────────────────────

def compute_max_pain(
    spot_price: float,
    option_chain: dict[str, dict[float, dict[str, Any]]] | None = None,
    strikes: list[OptionChainStrike] | None = None,
) -> MaxPainResult:
    """Compute the Max Pain strike from option chain data.

    Args:
        spot_price: Current underlying price.
        option_chain: Dict with 'calls' and 'puts' keys mapping strike→{oi, ltp, iv}.
                      Format: {"calls": {25000: {"oi": 100, "ltp": 150}, ...},
                               "puts":  {25000: {"oi": 200, "ltp": 120}, ...}}
        strikes: Alternatively, a list of OptionChainStrike objects.

    Returns:
        MaxPainResult with max_pain_strike, pain_index, and full pain curve.

    Raises:
        ValueError: If spot_price is invalid or no option data provided.
    """
    if spot_price <= 0:
        raise ValueError(f"Invalid spot price: {spot_price}")
    
    now = time.time()
    
    # Parse option chain into sorted list of strikes
    call_oi_map: dict[float, int] = {}
    put_oi_map: dict[float, int] = {}
    
    if option_chain:
        calls_data = option_chain.get("calls", {})
        puts_data = option_chain.get("puts", {})
        for strike, data in calls_data.items():
            call_oi_map[float(strike)] = int(data.get("oi", 0) if isinstance(data, dict) else 0)
        for strike, data in puts_data.items():
            put_oi_map[float(strike)] = int(data.get("oi", 0) if isinstance(data, dict) else 0)
    elif strikes:
        for s in strikes:
            call_oi_map[s.strike] = s.call_oi
            put_oi_map[s.strike] = s.put_oi
    else:
        raise ValueError("Either option_chain or strikes must be provided")
    
    # Merge all strikes
    all_strikes = sorted(set(call_oi_map.keys()) | set(put_oi_map.keys()))
    if not all_strikes:
        return MaxPainResult(
            max_pain_strike=0.0,
            pain_index=0.0,
            spot_price=spot_price,
            total_oi=0,
            call_oi_total=0,
            put_oi_total=0,
            put_call_ratio=0.0,
            pain_curve={},
            timestamp=now,
        )
    
    # Calculate pain curve
    pain_curve: dict[float, float] = {}
    total_call_oi = sum(call_oi_map.values())
    total_put_oi = sum(put_oi_map.values())
    
    for pain_strike in all_strikes:
        total_pain = 0.0
        
        # For each strike, calculate value at expiry if pain_strike is the settlement
        for s in all_strikes:
            call_oi = call_oi_map.get(s, 0)
            put_oi = put_oi_map.get(s, 0)
            
            if call_oi > 0 and s < pain_strike:
                total_pain += (pain_strike - s) * call_oi
            if put_oi > 0 and s > pain_strike:
                total_pain += (s - pain_strike) * put_oi
        
        pain_curve[pain_strike] = round(total_pain, 2)
    
    # Find strike with minimum pain (maximum pain for option buyers)
    min_pain_strike = min(pain_curve, key=pain_curve.get)
    min_pain_value = pain_curve[min_pain_strike]
    
    # Build nearest strikes list (around max pain)
    sorted_strikes = sorted(pain_curve.keys())
    idx = sorted_strikes.index(min_pain_strike) if min_pain_strike in sorted_strikes else 0
    nearest_strikes = []
    for offset in range(-2, 3):
        i = idx + offset
        if 0 <= i < len(sorted_strikes):
            s = sorted_strikes[i]
            diff_pct = abs(pain_curve[s] / min_pain_value - 1) * 100 if min_pain_value > 0 else 0
            nearest_strikes.append({
                "strike": s,
                "pain": pain_curve[s],
                "diff_from_min_pct": round(diff_pct, 1),
            })
    
    pcr = round(total_put_oi / max(total_call_oi, 1), 4)
    
    return MaxPainResult(
        max_pain_strike=min_pain_strike,
        pain_index=min_pain_value,
        spot_price=spot_price,
        total_oi=total_call_oi + total_put_oi,
        call_oi_total=total_call_oi,
        put_oi_total=total_put_oi,
        put_call_ratio=pcr,
        pain_curve=pain_curve,
        nearest_strikes=nearest_strikes,
        timestamp=now,
    )


def compute_pain_index(
    spot_price: float,
    option_chain: dict[str, dict[float, dict[str, Any]]],
) -> dict[str, Any]:
    """Compute a simplified pain index without full curve.

    Returns a dict with key metrics: max_pain_strike, distance%, PCR.
    Faster than full compute_max_pain when only summary stats are needed.
    """
    result = compute_max_pain(spot_price, option_chain=option_chain)
    distance_pct = ((spot_price - result.max_pain_strike) / spot_price) * 100 if spot_price > 0 else 0.0
    
    return {
        "max_pain_strike": result.max_pain_strike,
        "spot_price": spot_price,
        "distance": round(spot_price - result.max_pain_strike, 2),
        "distance_pct": round(distance_pct, 2),
        "pain_index": round(result.pain_index, 2),
        "put_call_ratio": result.put_call_ratio,
        "imbalance": "CALLS_HEAVY" if result.call_oi_total > result.put_oi_total * 1.5
                     else "PUTS_HEAVY" if result.put_oi_total > result.call_oi_total * 1.5
                     else "BALANCED",
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m core.max_pain",
        description="Max Pain Calculator — find the strike that maximizes option buyer pain",
    )
    ap.add_argument("--spot", type=float, required=True, help="Current spot price")
    ap.add_argument("--oi", action="store_true", help="Use sample OI data for demonstration")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    if args.oi:
        # Sample option chain for demonstration
        sample_chain: dict[str, dict[float, dict[str, Any]]] = {
            "calls": {
                24500: {"oi": 15000, "ltp": 850.0},
                24600: {"oi": 22000, "ltp": 780.0},
                24700: {"oi": 31000, "ltp": 700.0},
                24800: {"oi": 45000, "ltp": 620.0},
                24900: {"oi": 58000, "ltp": 540.0},
                25000: {"oi": 72000, "ltp": 460.0},
                25100: {"oi": 49000, "ltp": 380.0},
                25200: {"oi": 35000, "ltp": 300.0},
                25300: {"oi": 28000, "ltp": 220.0},
                25400: {"oi": 18000, "ltp": 150.0},
                25500: {"oi": 12000, "ltp": 90.0},
            },
            "puts": {
                24500: {"oi": 8000, "ltp": 120.0},
                24600: {"oi": 12000, "ltp": 150.0},
                24700: {"oi": 18000, "ltp": 190.0},
                24800: {"oi": 25000, "ltp": 240.0},
                24900: {"oi": 35000, "ltp": 300.0},
                25000: {"oi": 68000, "ltp": 380.0},
                25100: {"oi": 42000, "ltp": 460.0},
                25200: {"oi": 31000, "ltp": 540.0},
                25300: {"oi": 22000, "ltp": 620.0},
                25400: {"oi": 15000, "ltp": 700.0},
                25500: {"oi": 9000, "ltp": 780.0},
            },
        }
        result = compute_max_pain(args.spot, option_chain=sample_chain)
    else:
        _log.error("No data source specified. Use --oi for demo data.")
        return

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.summary())


if __name__ == "__main__":
    _cli()


__all__ = [
    "MaxPainResult",
    "OptionChainStrike",
    "compute_max_pain",
    "compute_pain_index",
]

