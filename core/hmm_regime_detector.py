import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

try:
    from hmmlearn.hmm import GaussianHMM
except ImportError:
    GaussianHMM = None

@dataclass
class RegimeState:
    state_id: int
    label: str  # TRENDING, CHOPPY, PANIC, NEUTRAL
    probability: float
    volatility: float

class HMMRegimeDetector:
    """
    Sovereign HMM-based regime detector.
    Discovers hidden market states using unsupervised Gaussian Hidden Markov Models.
    """
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.logger = logging.getLogger(__name__)
        self.n_components = int(cfg.get("hmm_regime_components", 3))
        self.model = self._init_model()
        self.state_map = {} # state_id -> label

    def _init_model(self):
        if GaussianHMM is None:
            self.logger.error("hmmlearn not installed. HMM Regime Detection disabled.")
            return None

        model = GaussianHMM(
            n_components=self.n_components,
            covariance_type="full",
            n_iter=100,
            random_state=42
        )
        return model

    def fit(self, data: pd.DataFrame):
        """
        Trains the HMM on historical returns and volatility.
        data: DataFrame with 'Close' prices.
        """
        if self.model is None: return

        # Feature Engineering: Log Returns and Volatility
        returns = np.log(data['Close'] / data['Close'].shift(1)).fillna(0).values
        vol = data['Close'].pct_change().rolling(window=20).std().fillna(0).values

        X = np.column_stack([returns, vol])

        try:
            self.model.fit(X)
            self._map_states()
            self.logger.info(f"[HMM] Model trained. States discovered: {self.n_components}")
        except Exception as e:
            self.logger.error(f"HMM fitting failed: {e}")

    def _map_states(self):
        """Maps hidden states to functional labels based on mean return and variance."""
        # Simplified mapping:
        # High Variance + High Return/Loss = PANIC
        # Low Variance + Low Return = CHOPPY
        # Med Variance + Consistent Direction = TRENDING
        for i in range(self.n_components):
            np.mean(self.model.means_[i])
            var = np.mean(self.model.covars_[i])

            if var > np.percentile([np.mean(c) for c in self.model.covars_], 75):
                self.state_map[i] = "PANIC"
            elif var < np.percentile([np.mean(c) for c in self.model.covars_], 25):
                self.state_map[i] = "CHOPPY"
            else:
                self.state_map[i] = "TRENDING"

    def predict_regime(self, data: pd.DataFrame) -> RegimeState:
        """Predicts the current regime for the given price series."""
        if self.model is None:
            return RegimeState(0, "NEUTRAL", 0.0, 0.0)

        returns = np.log(data['Close'] / data['Close'].shift(1)).fillna(0).values
        vol = data['Close'].pct_change().rolling(window=20).std().fillna(0).values
        X = np.column_stack([returns, vol])

        try:
            state = self.model.predict(X)[-1]
            probs = self.model.predict_proba(X)[-1]
            label = self.state_map.get(state, "NEUTRAL")
            return RegimeState(state, label, probs[state], vol[-1])
        except Exception as e:
            self.logger.error(f"HMM prediction failed: {e}")
            return RegimeState(0, "NEUTRAL", 0.0, 0.0)
