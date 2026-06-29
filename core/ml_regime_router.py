import logging
import os
from dataclasses import dataclass
from typing import Any

import joblib

__all__ = [
    "MLRegimeRouter",
    "ModelMeta",
]

@dataclass
class ModelMeta:
    path: str
    regime: str
    version: str

class MLRegimeRouter:
    """
    Routes signal requests to the model best suited for the current market regime.
    """
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.logger = logging.getLogger(__name__)
        self.model_dir = cfg.get("ml_model_dir", "models/")

        # Map regimes to specific model files
        self.regime_map = {
            "TRENDING": "model_trending.joblib",
            "CHOPPY": "model_choppy.joblib",
            "PANIC": "model_panic.joblib",
            "NEUTRAL": "model_default.joblib"
        }
        self._loaded_models = {}

    def get_model_for_regime(self, regime: str):
        """Returns the loaded model for the given regime."""
        regime_upper = str(regime).upper()
        model_file = self.regime_map.get(regime_upper, self.regime_map["NEUTRAL"])

        if model_file not in self._loaded_models:
            path = os.path.join(self.model_dir, model_file)
            if os.path.exists(path):
                try:
                    self._loaded_models[model_file] = joblib.load(path)
                    self.logger.info(f"[ML_ROUTER] Loaded {regime_upper} model from {path}")
                except Exception as e:
                    self.logger.error(f"[ML_ROUTER] Failed to load {model_file}: {e} (type: {type(e).__name__})")
                    return self._get_default_model()
            else:
                return self._get_default_model()

        return self._loaded_models[model_file]

    def _get_default_model(self):
        """Fallback to the main classifier if regime-specific model is missing."""
        default_path = os.path.join(self.model_dir, "model_default.joblib")
        if os.path.exists(default_path):
            try:
                return joblib.load(default_path)
            except Exception as e:
                self.logger.warning("[ML_ROUTER] Failed to load default model from %s: %s", default_path, e)
        return None

    def update_model_weights(self, regime: str, new_data_path: str):
        """
        Trigger for incremental learning (warm start).
        In a full implementation, this would call LightGBM's init_model parameter.
        """
        # Placeholder for incremental training logic
        self.logger.info(f"[ML_ONLINE] Updating weights for {regime} using {new_data_path}")
        # Logic: Load existing model -> Train on new_data -> Save as new version
