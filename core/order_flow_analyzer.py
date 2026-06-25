import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


__all__ = [
    "OrderFlowAnalyzer",
    "OrderFlowResult",
]

@dataclass
class OrderFlowResult:
    is_blocked: bool
    status: str  # "OK", "ABSORPTION", "EXHAUSTION", "DIVERGENCE"
    confidence: float
    reason: str

class OrderFlowAnalyzer:
    """
    Analyzes volume-price relationship to detect institutional absorption
    and exhaustion, preventing entries into "fake-out" breakouts.
    """
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.logger = logging.getLogger(__name__)
        # Config thresholds
        self.vol_spike_mult = float(cfg.get("order_flow_vol_spike_mult", 2.0))
        self.price_stagnation_thresh = float(cfg.get("order_flow_stagnation_pct", 0.001))

    def analyze(self, symbol: str, direction: str, df: pd.DataFrame) -> OrderFlowResult:
        """
        Analyzes recent candles for order flow anomalies.
        df: pandas DataFrame with 'Close', 'Volume'
        """
        if df is None or len(df) < 10:
            return OrderFlowResult(False, "OK", 0.0, "Insufficient data")

        # 1. Institutional Absorption Detection
        # High volume + minimal price movement = Absorption
        recent_vol = df['Volume'].tail(3).mean()
        avg_vol = df['Volume'].tail(20).mean()

        price_change = abs(df['Close'].iloc[-1] - df['Close'].iloc[-3]) / df['Close'].iloc[-3]

        # If volume is spiking but price isn't moving -> Absorption
        if recent_vol > (avg_vol * self.vol_spike_mult) and price_change < self.price_stagnation_thresh:
            return OrderFlowResult(
                is_blocked=True,
                status="ABSORPTION",
                confidence=0.85,
                reason=f"High volume ({round(recent_vol/avg_vol, 1)}x) with price stagnation - Institutional Absorption detected"
            )

        # 2. Exhaustion Detection
        # Price moving in signal direction but volume is drying up
        vol_trend = np.polyfit(range(len(df['Volume'].tail(5))), df['Volume'].tail(5), 1)[0]
        price_trend = np.polyfit(range(len(df['Close'].tail(5))), df['Close'].tail(5), 1)[0]

        # If price is rising but volume is falling -> Exhaustion (Bull Trap)
        if direction == "CALL" and price_trend > 0 and vol_trend < 0:
            return OrderFlowResult(
                is_blocked=True,
                status="EXHAUSTION",
                confidence=0.70,
                reason="Price rising on declining volume - Bull Exhaustion detected"
            )
        # If price is falling but volume is falling -> Exhaustion (Bear Trap)
        elif direction == "PUT" and price_trend < 0 and vol_trend < 0:
            return OrderFlowResult(
                is_blocked=True,
                status="EXHAUSTION",
                confidence=0.70,
                reason="Price falling on declining volume - Bear Exhaustion detected"
            )

        return OrderFlowResult(False, "OK", 1.0, "Order flow confirms trend")
