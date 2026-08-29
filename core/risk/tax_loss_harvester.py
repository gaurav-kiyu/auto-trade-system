import logging
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

@dataclass
class HarvestOpportunity:
    symbol: str
    pnl_pct: float
    pnl_value: float
    replacement_symbol: str
    harvest_reason: str

class TaxLossHarvester:
    def __init__(self) -> None:
        self.correlation_map = {
            "HDFCBANK": "ICICIBANK",
            "ICICIBANK": "AXISBANK",
            "AXISBANK": "KOTAKBANK",
            "TCS": "INFY",
            "INFY": "HCLTECH",
            "WIPRO": "TECHM",
            "RELIANCE": "ONGC",
            "TATAMOTORS": "M&M",
            "MARUTI": "TATAMOTORS",
            "SUNPHARMA": "CIPLA",
            "CIPLA": "DRREDDY",
            "SBIN": "PNB"
        }

    def scan_portfolio(self, positions: list[Any]) -> list[HarvestOpportunity]:
        """
        Scans portfolio for tax-loss harvesting candidates (pnl_pct < -10%).
        Suggests correlated replacement asset.
        """
        opportunities = []
        for p in positions:
            pnl_p = getattr(p, "pnl_pct", 0)
            pnl_val = getattr(p, "pnl", 0)
            sym = getattr(p, "symbol", "")

            if pnl_p < -10.0 and pnl_val < 0:
                # Find replacement
                clean_sym = sym.replace("-EQ", "").replace("_EQ", "").strip()
                replacement = self.correlation_map.get(clean_sym, "NIFTYBEES")

                opp = HarvestOpportunity(
                    symbol=sym,
                    pnl_pct=round(pnl_p, 1),
                    pnl_value=round(pnl_val, 2),
                    replacement_symbol=replacement,
                    harvest_reason=f"Book ₹{abs(round(pnl_val, 2))} capital loss for tax offset. Buy {replacement} to maintain sector exposure."
                )
                opportunities.append(opp)

        return sorted(opportunities, key=lambda x: x.pnl_value) # Most negative first

_harvester = TaxLossHarvester()

def get_tax_loss_harvester() -> TaxLossHarvester:
    return _harvester
