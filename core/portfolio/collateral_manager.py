import logging
from dataclasses import dataclass
from typing import List

_log = logging.getLogger(__name__)

@dataclass
class SweepAction:
    symbol: str
    action: str  # "BUY_ETF" or "SELL_ETF"
    quantity: int
    amount_inr: float
    reason: str

class CollateralManager:
    """
    Automated Idle Cash Sweeper.
    Maintains a 20% pure cash buffer. Sweeps excess into Liquid ETFs for margin pledging.
    """
    def __init__(self):
        self.CASH_BUFFER_PCT = 0.20
        self.LIQUID_ETF_SYMBOL = "LIQUIDBEES"
        self.LIQUID_ETF_PRICE = 1000.0  # Approx constant NAV

    def analyze_cash_drag(self, total_portfolio_val: float, current_cash: float, current_etf_qty: int) -> List[SweepAction]:
        """
        Determines if idle cash should be pledged, or if ETFs need to be sold to restore the buffer.
        """
        if total_portfolio_val <= 0:
            return []

        # Dynamically scale cash buffer based on India VIX
        try:
            from core.ai.live_indicators import get_live_indicator_engine
            vix = get_live_indicator_engine().fetch_india_vix()
        except ImportError:
            vix = 15.0

        if vix > 20.0:
            dynamic_buffer = 0.40 # High panic: 40% cash
        elif vix < 15.0:
            dynamic_buffer = 0.10 # Calm market: 10% cash (maximize yield)
        else:
            dynamic_buffer = 0.20 # Normal: 20% cash

        required_cash_buffer = total_portfolio_val * dynamic_buffer
        actions = []

        # Scenario 1: Too much idle cash. Sweep excess to ETFs.
        if current_cash > required_cash_buffer:
            excess_cash = current_cash - required_cash_buffer
            qty_to_buy = int(excess_cash // self.LIQUID_ETF_PRICE)

            if qty_to_buy > 0:
                amount = qty_to_buy * self.LIQUID_ETF_PRICE
                actions.append(SweepAction(
                    symbol=self.LIQUID_ETF_SYMBOL,
                    action="BUY_ETF",
                    quantity=qty_to_buy,
                    amount_inr=amount,
                    reason=f"Cash drag detected. Sweeping excess ₹{amount:,.2f} into margin-pledgable ETFs."
                ))

        # Scenario 2: Cash has fallen below buffer (due to losses or new entries). Sell ETFs to restore.
        elif current_cash < required_cash_buffer and current_etf_qty > 0:
            deficit = required_cash_buffer - current_cash
            qty_to_sell = int(deficit // self.LIQUID_ETF_PRICE) + 1 # Round up to restore buffer fully
            qty_to_sell = min(qty_to_sell, current_etf_qty)

            if qty_to_sell > 0:
                amount = qty_to_sell * self.LIQUID_ETF_PRICE
                actions.append(SweepAction(
                    symbol=self.LIQUID_ETF_SYMBOL,
                    action="SELL_ETF",
                    quantity=qty_to_sell,
                    amount_inr=amount,
                    reason=f"Cash buffer breached. Unpledging and selling {qty_to_sell} ETFs to restore liquidity."
                ))

        return actions

_collateral_mgr = CollateralManager()

def get_collateral_manager() -> CollateralManager:
    return _collateral_mgr
