import logging
import os
from dataclasses import dataclass

import joblib
import numpy as np


__all__ = [
    "ExitPrediction",
    "MLExitClassifier",
]

@dataclass
class ExitPrediction:
    exit_probability: float
    should_exit: bool
    reasoning: str
    confidence: float

class MLExitClassifier:
    """
    ML Classifier specifically tuned to predict when a winning trade
    is likely to reverse, preventing premature exits.
    """
    def __init__(self, model_path: str = "models/ml_exit_model.joblib"):
        self.model_path = model_path
        self.model = self._load_model()
        self.logger = logging.getLogger(__name__)
        self.confidence_threshold = 0.80

    def _load_model(self):
        if os.path.exists(self.model_path):
            try:
                return joblib.load(self.model_path)
            except Exception as e:
                self.logger.error(f"Failed to load ML Exit model: {e} (type: {type(e).__name__})")
        return None

    def prepare_features(self, trade_data: dict) -> np.array:
        """
        Converts real-time trade state into ML features.
        Expected trade_data keys:
        - 'entry_price', 'current_price', 'peak_price', 'entry_time', 'current_time', 'atr'
        """
        # 1. Trade Age (minutes)
        age = (trade_data['current_time'] - trade_data['entry_time']).total_seconds() / 60

        # 2. Current PnL %
        pnl_pct = ((trade_data['current_price'] - trade_data['entry_price']) / trade_data['entry_price']) * 100

        # 3. PnL Decay (Current PnL vs Peak PnL)
        peak_pnl = ((trade_data['peak_price'] - trade_data['entry_price']) / trade_data['entry_price']) * 100
        decay = peak_pnl - pnl_pct

        # 4. Volatility Ratio
        vol_ratio = trade_data['current_atr'] / trade_data['entry_atr'] if trade_data['entry_atr'] != 0 else 1.0

        return np.array([age, pnl_pct, decay, vol_ratio]).reshape(1, -1)

    def predict_exit(self, trade_data: dict) -> ExitPrediction:
        """
        Predicts if the current trade should be exited based on ML probability.
        """
        if self.model is None:
            return ExitPrediction(0.0, False, "Model not loaded", 0.0)

        features = self.prepare_features(trade_data)
        prob = self.model.predict_proba(features)[0][1] # Probability of class 1 (Exit)

        should_exit = prob >= self.confidence_threshold

        reason = "High probability of trend reversal" if should_exit else "Trend remains intact"
        if decay_val := (trade_data['peak_price'] - trade_data['current_price']):
            reason += f" (PnL Decay: {decay_val:.2f})"

        return ExitPrediction(
            exit_probability=prob,
            should_exit=should_exit,
            reasoning=reason,
            confidence=prob
        )
