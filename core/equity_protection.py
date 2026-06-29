import logging
from dataclasses import dataclass
from typing import Any

__all__ = [
    "EquityProtection",
    "ProtectionState",
]

@dataclass
class ProtectionState:
    multiplier: float
    status: str
    current_drawdown: float

class EquityProtection:
    """
    Protects the equity curve by scaling down risk during drawdowns.
    """
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.logger = logging.getLogger(__name__)
        # Drawdown thresholds and corresponding multipliers
        self.thresholds = [
            (0.02, 1.0),  # <<  2% drawdown: 100% risk
            (0.05, 0.7),  # 2-5% drawdown: 70% risk
            (0.10, 0.4),  # 5-10% drawdown: 40% risk
            (float('inf'), 0.1) # > 10% drawdown: 10% risk
        ]

    def calculate_multiplier(self, current_capital: float, peak_capital: float) -> ProtectionState:
        """
        Calculates the risk multiplier based on current vs peak capital.
        """
        if peak_capital <= 0:
            return ProtectionState(1.0, "NORMAL", 0.0)

        drawdown = (peak_capital - current_capital) / peak_capital

        for limit, mult in self.thresholds:
            if drawdown < limit:
                status = "NORMAL" if mult == 1.0 else "REDUCED"
                if drawdown >= 0.05: status = "CAUTIOUS"
                if drawdown >= 0.10: status = "PROTECTIVE"
                return ProtectionState(mult, status, drawdown)

        return ProtectionState(0.1, "PROTECTIVE", drawdown)

    def apply_protection(self, base_qty: int, multiplier: float, lot_size: int) -> int:
        """Scales quantity down to the nearest lot size."""
        protected_qty = int(base_qty * multiplier)
        # Ensure we don't go below 1 lot if we are still taking the trade
        if protected_qty < lot_size and multiplier > 0:
            return lot_size
        return (protected_qty // lot_size) * lot_size
