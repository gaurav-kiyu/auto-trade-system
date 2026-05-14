"""
Dynamic Risk Sizer - Regime-aware position sizing with configurable risk adjustments
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import logging

_log = logging.getLogger(__name__)


@dataclass
class DynamicRiskConfig:
    enabled: bool = True
    base_risk_pct: float = 0.03
    regime_trending_multiplier: float = 1.2
    regime_sideways_multiplier: float = 0.8
    regime_range_multiplier: float = 0.7


class DynamicRiskSizer:
    def __init__(self, config: DynamicRiskConfig):
        self.config = config
        self._regime_multipliers = {
            "TRENDING": config.regime_trending_multiplier,
            "SIDEWAYS": config.regime_sideways_multiplier,
            "RANGE": config.regime_range_multiplier,
            "NEUTRAL": 0.9,
            "CHOPPY": 0.5,
            "HIGH_VOLATILITY": 0.6,
            "EVENT": 0.3,
        }

    def get_risk_pct(self, regime: str) -> float:
        if not self.config.enabled:
            return self.config.base_risk_pct

        multiplier = self._regime_multipliers.get(regime, 1.0)
        adjusted_risk = self.config.base_risk_pct * multiplier
        _log.debug(f"Dynamic risk for {regime}: {adjusted_risk:.2%} (base {self.config.base_risk_pct:.2%} × {multiplier})")
        return adjusted_risk

    def calculate_position_size(
        self,
        capital: float,
        regime: str,
        entry_price: float,
        sl_pct: float,
    ) -> int:
        risk_amount = capital * self.get_risk_pct(regime)
        risk_per_lot = entry_price * (1 - sl_pct)
        if risk_per_lot > 0:
            max_lots = int(risk_amount / risk_per_lot)
            return max(1, max_lots)
        return 1


def create_dynamic_risk_sizer(config: dict) -> DynamicRiskSizer:
    cfg = DynamicRiskConfig(
        enabled=config.get("DYNAMIC_POSITION_SIZING_ENABLED", True),
        base_risk_pct=config.get("DYNAMIC_RISK_PER_TRADE_BASE", 0.03),
        regime_trending_multiplier=config.get("DYNAMIC_RISK_REGIME_ADJUST_TRENDING", 1.2),
        regime_sideways_multiplier=config.get("DYNAMIC_RISK_REGIME_ADJUST_SIDEWAYS", 0.8),
        regime_range_multiplier=config.get("DYNAMIC_RISK_REGIME_ADJUST_RANGE", 0.7),
    )
    return DynamicRiskSizer(cfg)