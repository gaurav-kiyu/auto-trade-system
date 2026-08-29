"""Unified Multi-Broker Margin & Collateral Aggregator (v3.0).

Aggregates (currently static sample data - see get_consolidated_margins()):
- Available cash balance across all connected Indian brokers
- Pledged liquid collateral & equity holdings margin
- Used margin & utilization %
- 75% Peak Margin Threshold Safety Warning

NOTE: No real broker margin API is connected in this environment. Every
value returned is a hardcoded sample pending a real per-broker margin-fetch
integration; responses are flagged with "is_demo_data": True.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class BrokerMarginStatus:
    broker_code: str
    broker_name: str
    available_cash: float
    collateral_margin: float
    total_margin: float
    used_margin: float
    utilization_pct: float
    status: str  # SAFE (<60%), MODERATE (60-74%), WARNING_PEAK (>=75%)


class MultiBrokerMarginRadar:
    """Aggregates and monitors margin across 8 Indian brokers.

    NOTE: This currently returns static sample data only - see
    get_consolidated_margins() docstring. No real broker margin API is
    connected in this environment.
    """

    @classmethod
    def get_consolidated_margins(cls) -> dict[str, Any]:
        """Return a static, hardcoded sample margin snapshot across 8 brokers.

        NOTE: No real broker margin API is connected here - this module never
        calls core.adapters.broker_adapters or any broker SDK for live cash/
        collateral/margin figures. ``brokers_sample`` below is fixed demo data
        pending a real per-broker margin-fetch integration; every response is
        flagged with ``is_demo_data: True`` so it is never mistaken for a live
        account balance.
        """
        brokers_sample = [
            ("zerodha", "Zerodha (Kite)", 450000.0, 1200000.0, 1650000.0, 580000.0),
            ("angelone", "Angel One (SmartAPI)", 280000.0, 650000.0, 930000.0, 420000.0),
            ("upstox", "Upstox Pro", 195000.0, 350000.0, 545000.0, 180000.0),
            ("dhan", "DhanHQ", 310000.0, 800000.0, 1110000.0, 310000.0),
            ("fyers", "Fyers API v3", 150000.0, 400000.0, 550000.0, 430000.0),  # 78% Warning!
            ("kotakneo", "Kotak Neo", 220000.0, 500000.0, 720000.0, 260000.0),
            ("groww", "Groww Invest", 120000.0, 200000.0, 320000.0, 95000.0),
            ("icicidirect", "ICICI Direct Breeze", 550000.0, 1500000.0, 2050000.0, 620000.0),
        ]

        broker_list: list[BrokerMarginStatus] = []
        total_cash = 0.0
        total_collateral = 0.0
        total_margin = 0.0
        total_used = 0.0
        warning_brokers = []

        for code, name, cash, collat, tot, used in brokers_sample:
            util_pct = round((used / max(tot, 1.0)) * 100.0, 1)
            status = "WARNING_PEAK" if util_pct >= 75.0 else ("MODERATE" if util_pct >= 60.0 else "SAFE")

            if status == "WARNING_PEAK":
                warning_brokers.append(name)

            total_cash += cash
            total_collateral += collat
            total_margin += tot
            total_used += used

            broker_list.append(BrokerMarginStatus(
                broker_code=code,
                broker_name=name,
                available_cash=cash,
                collateral_margin=collat,
                total_margin=tot,
                used_margin=used,
                utilization_pct=util_pct,
                status=status,
            ))

        overall_util = round((total_used / max(total_margin, 1.0)) * 100.0, 1)

        return {
            "total_available_cash": total_cash,
            "total_collateral_margin": total_collateral,
            "total_purchasing_power": total_margin,
            "total_used_margin": total_used,
            "overall_utilization_pct": overall_util,
            "peak_margin_alert": len(warning_brokers) > 0,
            "warning_brokers": warning_brokers,
            "brokers": [asdict(b) for b in broker_list],
            "timestamp": time.time(),
            "is_demo_data": True,
        }
