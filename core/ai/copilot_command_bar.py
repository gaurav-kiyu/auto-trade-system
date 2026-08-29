"""Natural Language AI Copilot Command Bar & Query Engine (v3.0).

Enables traders and Super Admins to query the entire platform using natural language:
- Query Scanner: "Show me top strong conviction stocks in Nifty IT"
- Query Margins: "What is my total used margin across all connected brokers?"
- Query Signals: "How many signals were generated today?"
- Query Expiry: "What is the current 0DTE theta decay?"
"""

from __future__ import annotations

from typing import Any


class AICopilotEngine:
    """Processes natural language queries and dispatches to system engines."""

    @classmethod
    def process_query(cls, query: str) -> dict[str, Any]:
        q = query.strip().lower()

        if "margin" in q or "collateral" in q or "cash" in q:
            from core.portfolio.margin_radar import MultiBrokerMarginRadar
            data = MultiBrokerMarginRadar.get_consolidated_margins()
            return {
                "intent": "QUERY_MARGINS",
                "answer": (
                    f"📊 You have ₹{(data['total_available_cash']/100000):.2f}L in available cash and "
                    f"₹{(data['total_collateral_margin']/100000):.2f}L in collateral, giving a total purchasing "
                    f"power of ₹{(data['total_purchasing_power']/100000):.2f}L across {len(data['brokers'])} brokers. "
                    f"Overall margin utilization is {data['overall_utilization_pct']}%."
                ),
                "data": data,
            }

        elif "sector" in q or "rotation" in q or "leading" in q:
            from core.market.sector_rotation_radar import SectorRotationRadar
            sectors = SectorRotationRadar.get_live_sector_matrix()
            leading = [s["sector"] for s in sectors if s["quadrant"] == "LEADING"]
            return {
                "intent": "QUERY_SECTOR_RADAR",
                "answer": f"🚀 Currently, the LEADING sectors with institutional accumulation are: {', '.join(leading)}. Stocks in these sectors receive a +5 score boost.",
                "data": sectors,
            }

        elif "fii" in q or "dii" in q or "participant" in q or "smart money" in q:
            from core.market.fii_dii_flow_radar import FiiDiiFlowRadar
            data = FiiDiiFlowRadar.get_participant_positioning()
            return {
                "intent": "QUERY_FII_DII",
                "answer": f"🏛️ FII Net Index Long ratio is {data['fii_index_fut_long_ratio_pct']}%. Institutional sentiment is {data['institutional_sentiment']}.",
                "data": data,
            }

        elif "expiry" in q or "0dte" in q or "straddle" in q:
            from core.strategy.expiry_0dte_harvester import Expiry0DTEHarvester
            data = Expiry0DTEHarvester.get_live_harvest_status()
            return {
                "intent": "QUERY_0DTE_EXPIRY",
                "answer": f"⚡ 0DTE Straddle has captured {data['total_theta_decay_pct']}% Theta decay, generating +₹{data['total_pnl_rupees']:,.2f} in P&L.",
                "data": data,
            }

        else:
            # Default Scanner / Signals overview
            from core.signals.signal_tracker import SignalTracker
            tracker = SignalTracker.get_instance()
            analytics = tracker.get_admin_signal_analytics()
            return {
                "intent": "GENERAL_SIGNALS_SUMMARY",
                "answer": f"📈 System has generated {analytics['total_signals']} signals with an institutional win rate of {analytics['win_rate_pct']}%.",
                "data": analytics,
            }
