from typing import Any

from .strategy_engine_v2 import (
    ATRStrategy,
    BaseStrategy,
    MeanReversionStrategy,
    MomentumStrategy,
    RSIStrategy,
    SmartMoneyStrategy,
    TrendAlignmentStrategy,
    VolumeStrategy,
    VWAPStrategy,
)


class ScoringEngine:
    def __init__(self, config: dict[str, Any]):
        self.config = config

        # Initialize strategies
        self.strategies: list[BaseStrategy] = [
            TrendAlignmentStrategy("Trend", config),
            VWAPStrategy("VWAP", config),
            VolumeStrategy("Volume", config),
            ATRStrategy("ATR", config),
            MomentumStrategy("MACD", config),
            RSIStrategy("RSI", config),
            SmartMoneyStrategy("SmartMoney", config),
            MeanReversionStrategy("MeanReversion", config)
        ]

    def score(self, features: dict[str, Any], direction: str) -> dict[str, Any]:
        """
        Aggregates strategy scores and builds the detailed breakdown.
        """
        total_score = 0
        components = []
        reasons = []

        for strategy in self.strategies:
            result = strategy.evaluate(features, direction)
            total_score += result["score"]

            components.append({
                "name": strategy.name,
                "score": result["score"]
            })

            reasons.append({
                "name": strategy.name,
                "status": result["status"],
                "msg": result["reason"]
            })

        # Optional: AI enrichment or learning adjustments could be added to the score later

        return {
            "total_score": max(0, min(100, total_score)),  # clamp 0-100
            "direction": direction,
            "components": components,
            "reasons": reasons
        }
