"""Institutional Gamma Exposure (GEX) & Implied Volatility (IV) Smile Engine (v3.0).

Calculates:
- Strike-by-strike Call GEX, Put GEX, and Net Gamma Exposure in ₹ Crores
- Market Maker Zero-Gamma Flip Level (Volatility Transition Line)
- Major Call/Put Gamma Walls (Resistance & Support Pinning Levels)
- IV Rank (IVR) & IV Percentile (IVP) against 252-day historical volatility range
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class GEXResult:
    spot_price: float
    total_net_gex_cr: float
    zero_gamma_flip: float
    call_wall_strike: float
    put_wall_strike: float
    market_regime: str  # POSITIVE_GAMMA (Mean-Reverting / Low Vol) or NEGATIVE_GAMMA (High Vol / Trend Extension)
    strikes_gex: list[dict[str, Any]]
    iv_rank_pct: float
    iv_percentile_pct: float
    iv_status: str  # UNDERPRICED (Buy Options), FAIR, OVERPRICED (Sell Options)


class GammaExposureEngine:
    """Institutional Greeks & Volatility Surface Calculator."""

    @staticmethod
    def calculate_strike_gamma(
        spot: float,
        strike: float,
        days_to_expiry: float = 4.0,
        iv: float = 0.15,
        risk_free_rate: float = 0.065,
    ) -> float:
        """Calculate Black-Scholes theoretical Gamma."""
        if spot <= 0 or strike <= 0 or iv <= 0:
            return 0.0
        t = max(days_to_expiry / 365.0, 0.001)
        sigma = iv
        d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
        phi_d1 = (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * d1 * d1)
        gamma = phi_d1 / (spot * sigma * math.sqrt(t))
        return gamma

    @classmethod
    def analyze_options_chain(
        cls,
        spot_price: float,
        options_data: list[dict[str, Any]],
        lot_size: int = 50,
        historical_iv_series: list[float] | None = None,
    ) -> GEXResult:
        """Analyze full options chain and compute Net GEX and IV Percentile."""
        strikes_gex = []
        total_net_gex = 0.0
        max_call_gex = -1.0
        max_put_gex = -1.0
        call_wall = spot_price
        put_wall = spot_price

        for item in options_data:
            strike = float(item.get("strike", 0))
            if strike <= 0:
                continue

            call_oi = float(item.get("call_oi", 0))
            put_oi = float(item.get("put_oi", 0))
            call_iv = float(item.get("call_iv", 14.5)) / 100.0
            put_iv = float(item.get("put_iv", 15.0)) / 100.0
            dte = float(item.get("dte", 4.0))

            gamma_call = cls.calculate_strike_gamma(spot_price, strike, dte, call_iv)
            gamma_put = cls.calculate_strike_gamma(spot_price, strike, dte, put_iv)

            # GEX Formula (in ₹ Crores): OI * LotSize * Gamma * Spot^2 * 0.01 / 10,000,000
            call_gex_cr = (call_oi * lot_size * gamma_call * (spot_price ** 2) * 0.01) / 10_000_000.0
            put_gex_cr = -(put_oi * lot_size * gamma_put * (spot_price ** 2) * 0.01) / 10_000_000.0
            net_gex_cr = call_gex_cr + put_gex_cr

            total_net_gex += net_gex_cr

            if call_gex_cr > max_call_gex:
                max_call_gex = call_gex_cr
                call_wall = strike

            if abs(put_gex_cr) > max_put_gex:
                max_put_gex = abs(put_gex_cr)
                put_wall = strike

            strikes_gex.append({
                "strike": strike,
                "call_gex_cr": round(call_gex_cr, 2),
                "put_gex_cr": round(put_gex_cr, 2),
                "net_gex_cr": round(net_gex_cr, 2),
                "call_oi": int(call_oi),
                "put_oi": int(put_oi),
                "call_iv": round(call_iv * 100, 1),
                "put_iv": round(put_iv * 100, 1),
            })

        # Zero Gamma Flip Level (Approximated weighted strike where net GEX turns 0)
        strikes_sorted = sorted(strikes_gex, key=lambda x: x["strike"])
        zero_flip = spot_price
        for i in range(len(strikes_sorted) - 1):
            if (strikes_sorted[i]["net_gex_cr"] <= 0 and strikes_sorted[i+1]["net_gex_cr"] >= 0) or                (strikes_sorted[i]["net_gex_cr"] >= 0 and strikes_sorted[i+1]["net_gex_cr"] <= 0):
                zero_flip = (strikes_sorted[i]["strike"] + strikes_sorted[i+1]["strike"]) / 2.0
                break

        # IV Rank & Percentile
        current_iv = 14.8
        if strikes_gex:
            atm_strike = min(strikes_gex, key=lambda x: abs(x["strike"] - spot_price))
            current_iv = (atm_strike["call_iv"] + atm_strike["put_iv"]) / 2.0

        hist = historical_iv_series or [11.5, 12.0, 13.2, 14.5, 15.8, 17.2, 19.5, 21.0, 24.5, 13.8, 14.8]
        min_iv, max_iv = min(hist), max(hist)
        iv_rank = round(((current_iv - min_iv) / max(max_iv - min_iv, 0.1)) * 100, 1)
        below_cnt = sum(1 for v in hist if v < current_iv)
        iv_pct = round((below_cnt / max(len(hist), 1)) * 100, 1)

        iv_status = "UNDERPRICED" if iv_rank < 25 else ("OVERPRICED" if iv_rank > 75 else "FAIR")
        regime = "POSITIVE_GAMMA" if total_net_gex >= 0 else "NEGATIVE_GAMMA"

        return GEXResult(
            spot_price=spot_price,
            total_net_gex_cr=round(total_net_gex, 2),
            zero_gamma_flip=round(zero_flip, 2),
            call_wall_strike=round(call_wall, 2),
            put_wall_strike=round(put_wall, 2),
            market_regime=regime,
            strikes_gex=strikes_sorted,
            iv_rank_pct=iv_rank,
            iv_percentile_pct=iv_pct,
            iv_status=iv_status,
        )
