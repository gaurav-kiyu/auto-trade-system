"""
Cost Accountant - Calculates true cost-adjusted PnL
v2.49: Adds realistic trading costs to PnL calculations
"""
from __future__ import annotations
import logging

_log = logging.getLogger(__name__)


class CostAccountant:
    """
    Calculates all trading costs for accurate PnL reporting.
    Costs are MANDATED and cannot be ignored.
    """

    # Default costs (can be overridden via config)
    STT_PCT = 0.0005  # 0.05% on sell side (SEBI)
    BROKERAGE_PER_ORDER = 20.0  # Flat brokerage
    EXCHANGE_FEE = 0.0  # NSE/BSE fees (typically included in brokerage)
    GST_PCT = 0.18  # 18% on brokerage
    STAMP_DUTY_PCT = 0.002  # 0.02% (NSE) / 0.01% (BSE) - varies by state
    BID_ASK_ESTIMATE = 3.0  # Estimated bid-ask cost per options contract

    def __init__(self, config: dict = None):
        if config:
            self.STT_PCT = config.get("MANDATE_COST_STT_PCT", self.STT_PCT)
            self.BROKERAGE_PER_ORDER = config.get("MANDATE_COST_BROKERAGE", self.BROKERAGE_PER_ORDER)
            self.GST_PCT = config.get("MANDATE_COST_GST_PCT", self.GST_PCT)
            self.BID_ASK_ESTIMATE = config.get("MANDATE_COST_BID_ASK", self.BID_ASK_ESTIMATE)

    def calculate_entry_costs(self, premium: float, qty: int) -> dict:
        """Costs when entering a position (BUY) - just fees, not premium"""
        brokerage = self.BROKERAGE_PER_ORDER
        gst = brokerage * self.GST_PCT
        stamp_duty = (premium * qty) * self.STAMP_DUTY_PCT  # Some states charge on buy too

        return {
            "premium": premium * qty,
            "brokerage": brokerage,
            "gst": gst,
            "stamp_duty": stamp_duty,
            "total_entry_cost": brokerage + gst + stamp_duty,
        }

    def calculate_exit_costs(self, premium: float, qty: int, is_buy: bool = False) -> dict:
        """Costs when exiting a position"""
        total_premium = premium * qty
        brokerage = self.BROKERAGE_PER_ORDER
        stt = total_premium * self.STT_PCT if not is_buy else 0  # STT on sell only
        stamp_duty = total_premium * self.STAMP_DUTY_PCT
        gst = brokerage * self.GST_PCT
        bid_ask = self.BID_ASK_ESTIMATE * qty

        return {
            "premium": total_premium,
            "brokerage": brokerage,
            "stt": stt,
            "stamp_duty": stamp_duty,
            "gst": gst,
            "bid_ask_slippage": bid_ask,
            "total_exit_cost": brokerage + stt + stamp_duty + gst + bid_ask,
        }

    def calculate_net_pnl(
        self,
        entry_premium: float,
        exit_premium: float,
        qty: int,
    ) -> dict:
        """Calculate gross and net PnL with all costs"""
        entry_costs = self.calculate_entry_costs(entry_premium, qty)
        exit_costs = self.calculate_exit_costs(exit_premium, qty, is_buy=False)

        gross_pnl = (exit_premium - entry_premium) * qty

        total_costs = entry_costs["total_entry_cost"] + exit_costs["total_exit_cost"]
        net_pnl = gross_pnl - total_costs

        return {
            "gross_pnl": gross_pnl,
            "entry_costs": entry_costs["total_entry_cost"],
            "exit_costs": exit_costs["total_exit_cost"],
            "total_costs": total_costs,
            "net_pnl": net_pnl,
            "cost_pct_of_trade": total_costs / (entry_premium * qty) if entry_premium * qty > 0 else 0,
        }

    def calculate_expected_costs(self, expected_premium: float, qty: int) -> float:
        """Estimate costs for expected value calculation"""
        entry = self.calculate_entry_costs(expected_premium, qty)
        exit = self.calculate_exit_costs(expected_premium, qty)
        return entry["total_entry_cost"] + exit["total_exit_cost"]


_cost_accountant: CostAccountant = None


def get_cost_accountant(config: dict = None) -> CostAccountant:
    """Singleton cost accountant"""
    global _cost_accountant
    if _cost_accountant is None:
        _cost_accountant = CostAccountant(config)
    return _cost_accountant