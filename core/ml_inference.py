import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# Lazy import for ML libraries to ensure the bot starts even if ML deps are missing


__all__ = [
    "MLInferenceEngine",
    "MLPrediction",
    "init_ml_engine",
    "log",
    "ml_engine",
]

try:
    import joblib

    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False

log = logging.getLogger("ml_inference")

@dataclass
class MLPrediction:
    win_probability: float
    confidence_score: float
    features_used: list[str]
    regime_aware: bool
    fallback_triggered: bool = False
    error: str | None = None

class MLInferenceEngine:
    """
    Abstraction layer for ML models.
    Decouples the strategy from the specific ML implementation (LightGBM, PyTorch, etc.)
    and provides safety gates for feature validation.
    """

    def __init__(self, model_path: str, feature_cols: list[str]):
        self.model_path = Path(model_path)
        self.feature_cols = feature_cols
        self.model = None
        self._load_model()

    def _load_model(self):
        """Loads the model from disk with safety checks."""
        if not ML_AVAILABLE:
            log.error("ML libraries not installed. Inference engine will operate in FALLBACK mode.")
            return

        try:
            if self.model_path.exists():
                self.model = joblib.load(self.model_path)
                log.info(f"ML Model loaded successfully from {self.model_path}")
            else:
                log.warning(f"Model file not found at {self.model_path}. Using fallback logic.")
        except Exception as e:
            log.exception(f"Failed to load ML model: {e} (type: {type(e).__name__})")
            self.model = None

    def _validate_features(self, features: dict[str, Any]) -> tuple[np.ndarray | None, bool]:
        """
        Sanity check for ML features.
        Returns (feature_vector, fallback_triggered).
        """
        try:
            vector = []
            for col in self.feature_cols:
                val = features.get(col)
                if val is None or np.isnan(val):
                    return None, True # Trigger fallback on any NaN
                vector.append(float(val))

            # Outlier detection: If any feature is 10x the expected range, trigger fallback
            # (Simplified example: check if any value is absurdly high)
            if any(abs(v) > 1e6 for v in vector):
                return None, True

            return np.array(vector).reshape(1, -1), False
        except Exception as e:
            log.debug(f"Feature validation failed: {e} (type: {type(e).__name__})")
            return None, True

    def predict(self, features: dict[str, Any], regime: str = "NEUTRAL") -> MLPrediction:
        """
        Predicts win probability with a safety-first approach.
        """
        # 1. Feature Validation
        vector, fallback = self._validate_features(features)

        if not self.model or fallback:
            # Safe Fallback: Return 0.5 (neutral) if model is missing or data is corrupt
            return MLPrediction(
                win_probability=0.5,
                confidence_score=0.0,
                features_used=self.feature_cols,
                regime_aware=False,
                fallback_triggered=True,
                error="Model missing or feature validation failed" if not self.model else "Feature validation failed"
            )

        try:
            # 2. Inference
            prob = self.model.predict(vector)[0]

            # 3. Regime Adjustment
            # If we are in a HIGH_VOL regime, we penalize the confidence
            confidence = prob
            if regime == "HIGH_VOL":
                confidence *= 0.8

            return MLPrediction(
                win_probability=float(prob),
                confidence_score=float(confidence),
                features_used=self.feature_cols,
                regime_aware=True
            )
        except Exception as e:
            log.exception(f"Inference error: {e} (type: {type(e).__name__})")
            return MLPrediction(
                win_probability=0.5,
                confidence_score=0.0,
                features_used=self.feature_cols,
                regime_aware=False,
                fallback_triggered=True,
                error=str(e)
            )

# Singleton instance
ml_engine: MLInferenceEngine | None = None

def init_ml_engine(model_path: str, feature_cols: list[str]):
    global ml_engine
    ml_engine = MLInferenceEngine(model_path, feature_cols)
