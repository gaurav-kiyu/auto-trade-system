"""0DTE Expiry Day Smart Straddle & Delta-Neutral Harvester Engine (v3.0).

Describes the intended automated expiry lifecycle engine:
- Automated 09:20 AM IST entry on current index expiry (Nifty/BankNifty/Sensex)
- Dynamic individual leg trailing stop loss (25%)
- Auto-Delta Hedging: Shifting winning leg when underlying drifts >0.4%
- Hard Square-off at 15:15 PM IST to capture 100% Theta burn

NOTE: No real active position is tracked by this module - it never places or
monitors a real straddle order, and no real broker/market-data connection is
wired in. get_live_harvest_status() returns a static, hardcoded sample leg
snapshot (fixed premiums/decay/entry_time) pending a real execution engine;
responses are flagged with "is_demo_data": True.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class StraddleLeg:
    leg_type: str  # CE or PE
    strike: float
    entry_premium: float
    current_premium: float
    stop_loss: float
    decay_pct: float
    status: str  # ACTIVE, SL_HIT, PROFIT_LOCKED


@dataclass
class ExpiryHarvesterStatus:
    index_symbol: str
    spot_price: float
    entry_time: str
    combined_entry_premium: float
    combined_current_premium: float
    total_theta_decay_pct: float
    total_pnl_rupees: float
    delta_exposure: float  # Net portfolio delta
    rebalance_count: int
    legs: list[StraddleLeg]
    engine_state: str  # HARVESTING, REBALANCING, SQUARED_OFF


class Expiry0DTEHarvester:
    """Automated 0DTE Expiry Straddle / Strangle Delta Harvester."""

    @classmethod
    def get_live_harvest_status(cls, index_symbol: str = "NIFTY", spot: float = 24520.0) -> dict[str, Any]:
        """Return a static, hardcoded sample 0DTE straddle status.

        NOTE: No real active position is tracked - the leg premiums, stop
        losses, decay percentages, and entry_time below are fixed sample
        values, not a live straddle being monitored. Flagged with
        ``is_demo_data: True`` so it is never mistaken for a real position.
        """
        atm_strike = round(spot / 50.0) * 50.0

        leg_ce = StraddleLeg(
            leg_type="CE",
            strike=atm_strike,
            entry_premium=84.50,
            current_premium=48.20,
            stop_loss=105.60,
            decay_pct=42.9,
            status="ACTIVE",
        )
        leg_pe = StraddleLeg(
            leg_type="PE",
            strike=atm_strike,
            entry_premium=88.00,
            current_premium=51.40,
            stop_loss=110.00,
            decay_pct=41.6,
            status="ACTIVE",
        )

        combined_entry = leg_ce.entry_premium + leg_pe.entry_premium
        combined_current = leg_ce.current_premium + leg_pe.current_premium
        decay_pct = round(((combined_entry - combined_current) / combined_entry) * 100.0, 1)
        pnl_rs = round((combined_entry - combined_current) * 1000, 2)  # Assuming 1,000 qty (20 lots)

        status = ExpiryHarvesterStatus(
            index_symbol=index_symbol,
            spot_price=spot,
            entry_time="09:20:00 IST",
            combined_entry_premium=round(combined_entry, 2),
            combined_current_premium=round(combined_current, 2),
            total_theta_decay_pct=decay_pct,
            total_pnl_rupees=pnl_rs,
            delta_exposure=0.03,  # Delta-neutral
            rebalance_count=1,
            legs=[leg_ce, leg_pe],
            engine_state="HARVESTING",
        )

        res = asdict(status)
        res["timestamp"] = time.time()
        res["is_demo_data"] = True
        return res
