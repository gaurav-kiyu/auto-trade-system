"""
Position Sizing Manager.

Calculates appropriate trade sizes based on risk, volatility, and capital.
"""

from __future__ import annotations

from typing import Any

from core.ports.risk.risk_port import PositionSizingInput


class PositionSizingManager:
    def __init__(self, config: Any):
        self.config = config

    def calculate_size(self, sizing_input: PositionSizingInput, volatility_multiplier: float) -> int:
        try:
            if sizing_input.stop_loss_price <= 0 or sizing_input.entry_price <= 0:
                return 0

            risk_amount = sizing_input.capital_available * sizing_input.risk_per_trade
            price_diff = abs(sizing_input.entry_price - sizing_input.stop_loss_price)
            if price_diff <= 0:
                return 0

            raw_lots = risk_amount / (price_diff * sizing_input.lot_size)
            base_lots = max(1, int(raw_lots))

            adjusted_lots = int(base_lots * volatility_multiplier)

            # Apply portfolio and capital constraints (simplified)
            # In a full implementation, this would call back to RiskLimitsManager
            return max(0, adjusted_lots)
        except (ValueError, TypeError, ZeroDivisionError):
            return 0

    def get_volatility_multiplier(self, volatility: float) -> float:
        if volatility <= self.config.vix_threshold_low:
            return self.config.vix_size_multiplier_low
        elif volatility >= self.config.vix_threshold_high:
            return self.config.vix_size_multiplier_high
        else:
            ratio = (volatility - self.config.vix_threshold_low) / (self.config.vix_threshold_high - self.config.vix_threshold_low)
            ratio = max(0, min(1, ratio))
            return self.config.vix_size_multiplier_low + (ratio * (self.config.vix_size_multiplier_high - self.config.vix_size_multiplier_low))
