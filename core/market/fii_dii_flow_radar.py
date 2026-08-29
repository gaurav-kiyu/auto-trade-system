"""FII / DII & Participant-Wise Smart Money Positioning Radar (v3.0).

Analyzes daily NSE Participant-wise Open Interest across 4 major participant categories:
- FII (Foreign Institutional Investors)
- DII (Domestic Institutional Investors)
- PRO (Proprietary Trading Desks / Market Makers)
- CLIENT (Retail & HNI Traders)

Computes Net Long / Short contracts across Index Futures, Index Options, and Stock Futures,
and detects institutional divergence traps.

NOTE: No real institutional-flow data feed is connected in this environment.
get_participant_positioning() currently returns a static, hardcoded sample
dataset pending a real NSE participant-wise OI feed integration; responses
are flagged with "is_demo_data": True.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ParticipantPosition:
    participant_type: str  # FII, DII, PRO, CLIENT
    display_name: str
    index_fut_long: int
    index_fut_short: int
    index_fut_net: int
    index_call_long: int
    index_call_short: int
    index_call_net: int
    index_put_long: int
    index_put_short: int
    index_put_net: int
    stock_fut_net: int
    net_bias: str  # BULLISH, BEARISH, NEUTRAL


@dataclass
class SmartMoneyTrapAlert:
    alert_type: str  # BULL_TRAP, BEAR_TRAP, SQUEEZE, INSTITUTIONAL_ACCUMULATION
    severity: str  # HIGH, CRITICAL, MODERATE
    title: str
    description: str
    recommended_action: str


class FiiDiiFlowRadar:
    """Institutional Participant-wise Inflow & Positioning Analyzer."""

    @classmethod
    def get_participant_positioning(cls) -> dict[str, Any]:
        """Return a static, hardcoded sample participant-wise OI dataset.

        NOTE: No real institutional-flow data feed is connected - this module
        never fetches live NSE participant-wise Open Interest. The dataset
        below (including institutional_sentiment) is a fixed sample pending a
        real NSE participant-OI feed integration; the response is flagged
        with ``is_demo_data: True`` so it is never mistaken for live data.
        """
        participants = [
            ParticipantPosition(
                participant_type="FII",
                display_name="Foreign Institutional Investors (FII)",
                index_fut_long=145200,
                index_fut_short=68400,
                index_fut_net=76800,  # Strongly Net Long
                index_call_long=385000,
                index_call_short=195000,
                index_call_net=190000,
                index_put_long=210000,
                index_put_short=340000,
                index_put_net=-130000,  # Net Put Sellers (Bullish)
                stock_fut_net=185000,
                net_bias="BULLISH",
            ),
            ParticipantPosition(
                participant_type="PRO",
                display_name="Proprietary Trading Desks (PRO)",
                index_fut_long=52000,
                index_fut_short=38000,
                index_fut_net=14000,
                index_call_long=180000,
                index_call_short=145000,
                index_call_net=35000,
                index_put_long=160000,
                index_put_short=210000,
                index_put_net=-50000,
                stock_fut_net=42000,
                net_bias="BULLISH",
            ),
            ParticipantPosition(
                participant_type="DII",
                display_name="Domestic Mutual Funds & DII",
                index_fut_long=38000,
                index_fut_short=59000,
                index_fut_net=-21000,
                index_call_long=15000,
                index_call_short=18000,
                index_call_net=-3000,
                index_put_long=45000,
                index_put_short=12000,
                index_put_net=33000,
                stock_fut_net=85000,
                net_bias="NEUTRAL",
            ),
            ParticipantPosition(
                participant_type="CLIENT",
                display_name="Retail & Individual Clients (CLIENT)",
                index_fut_long=88000,
                index_fut_short=157800,
                index_fut_net=-69800,  # Heavily Net Short Futures
                index_call_long=420000,
                index_call_short=642000,
                index_call_net=-222000,  # Massive Call Writing (Vulnerable to Short Squeeze)
                index_put_long=580000,
                index_put_short=433000,
                index_put_net=147000,  # Net Put Buyers
                stock_fut_net=-312000,
                net_bias="BEARISH",
            ),
        ]

        # Analyze Smart Money Divergence Trap
        fii = next(p for p in participants if p.participant_type == "FII")
        client = next(p for p in participants if p.participant_type == "CLIENT")

        traps = []
        if fii.index_fut_net > 50000 and client.index_fut_net < -50000:
            traps.append(SmartMoneyTrapAlert(
                alert_type="SHORT_SQUEEZE_WARNING",
                severity="HIGH",
                title="⚡ Retail Short Trap / FII Squeeze Setup",
                description=(
                    f"FIIs are heavily NET LONG ({fii.index_fut_net:,} contracts) while Retail Clients are "
                    f"NET SHORT ({client.index_fut_net:,} contracts). Massive probability of upward short-squeeze."
                ),
                recommended_action="Favor Buying ATM Calls on intraday dips; avoid naked Call writing.",
            ))

        fii_long_ratio = round((fii.index_fut_long / max(fii.index_fut_long + fii.index_fut_short, 1)) * 100.0, 1)

        return {
            "fii_index_fut_long_ratio_pct": fii_long_ratio,
            "institutional_sentiment": "STRONG_ACCUMULATION",
            "smart_money_traps": [asdict(t) for t in traps],
            "participants": [asdict(p) for p in participants],
            "timestamp": time.time(),
            "is_demo_data": True,
        }
