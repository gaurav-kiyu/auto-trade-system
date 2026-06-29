import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    "RetailSentimentAnalyzer",
    "RetailSentimentResult",
]

@dataclass
class RetailSentimentResult:
    is_blocked: bool
    sentiment: str  # "EUPHORIA", "PANIC", "NEUTRAL"
    confidence: float
    reason: str

class RetailSentimentAnalyzer:
    """
    Sovereign Local Retail Sentiment Analyzer.
    Detects retail extremes (Euphoria/Panic) using Volume-Price clustering
    and Z-score volatility analysis to act as a contrarian filter.
    """
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.logger = logging.getLogger(__name__)
        self.vol_z_threshold = float(cfg.get("retail_vol_z_threshold", 2.0))
        self.price_stagnation_thresh = float(cfg.get("retail_stagnation_pct", 0.001))

    def analyze(self, symbol: str, direction: str, df: pd.DataFrame) -> RetailSentimentResult:
        """
        Analyzes volume and price action to detect retail extremes.
        df: DataFrame with 'Close' and 'Volume'
        """
        if df is None or len(df) < 30:
            return RetailSentimentResult(False, "NEUTRAL", 0.0, "Insufficient data")

        # 1. Volume Z-Score (Is current volume an extreme spike?)
        volumes = df['Volume'].tail(30).values
        avg_vol = np.mean(volumes[:-1])
        std_vol = np.std(volumes[:-1])
        current_vol = volumes[-1]

        z_score = (current_vol - avg_vol) / std_vol if std_vol > 0 else 0

        # 2. Price Action vs Volume (Absorption detection)
        recent_close = df['Close'].iloc[-1]
        prev_close = df['Close'].iloc[-2]
        price_change = abs(recent_close - prev_close) / prev_close

        # Retail Euphoria: Price is high, Volume spikes, but price stops moving up (Bull Trap)
        if direction == "CALL" and z_score > self.vol_z_threshold and price_change < self.price_stagnation_thresh:
            return RetailSentimentResult(
                is_blocked=True,
                sentiment="EUPHORIA",
                confidence=min(1.0, z_score/5.0),
                reason=f"Retail Euphoria detected: Extreme volume spike ({round(z_score,1)}z) with price stagnation."
            )

        # Retail Panic: Price is low, Volume spikes, but price stops falling (Bear Trap)
        if direction == "PUT" and z_score > self.vol_z_threshold and price_change < self.price_stagnation_thresh:
            return RetailSentimentResult(
                is_blocked=True,
                sentiment="PANIC",
                confidence=min(1.0, z_score/5.0),
                reason=f"Retail Panic detected: Extreme volume spike ({round(z_score,1)}z) with price stagnation."
            )

        return RetailSentimentResult(False, "NEUTRAL", 1.0, "Order flow is healthy")
