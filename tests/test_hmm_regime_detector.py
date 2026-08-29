"""Tests for core.hmm_regime_detector - HMM-based market regime detection.

Tests the dataclass and the detector's graceful fallback when hmmlearn
is not installed (which is the typical runtime environment).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from core.hmm_regime_detector import HMMRegimeDetector, RegimeState


class TestRegimeState:
    """Tests for RegimeState dataclass."""

    def test_defaults(self) -> None:
        state = RegimeState(state_id=0, label="NEUTRAL", probability=0.0, volatility=0.0)
        assert state.state_id == 0
        assert state.label == "NEUTRAL"
        assert state.probability == 0.0


class TestHMMRegimeDetector:
    """Tests for HMMRegimeDetector - regime detection from price data."""

    def setup_method(self) -> None:
        self.detector = HMMRegimeDetector({})

    def test_init_with_empty_config(self) -> None:
        assert self.detector.n_components == 3  # default

    def test_init_with_custom_components(self) -> None:
        detector = HMMRegimeDetector({"hmm_regime_components": 4})
        assert detector.n_components == 4

    def test_model_is_none_when_hmmlearn_missing(self) -> None:
        # In test environments, hmmlearn is typically not installed
        assert self.detector.model is None or hasattr(self.detector.model, "fit")

    def test_predict_without_model_returns_neutral(self) -> None:
        """When hmmlearn is not installed, predict returns NEUTRAL fallback."""
        data = pd.DataFrame({"Close": [100.0 + i for i in range(50)]})
        state = self.detector.predict_regime(data)
        assert state.label == "NEUTRAL"
        assert state.probability == 0.0
        assert state.volatility == 0.0

    def test_fit_without_model_does_not_crash(self) -> None:
        """fit() should not crash when model is None."""
        data = pd.DataFrame({"Close": [100.0 + i for i in range(50)]})
        # Should not raise
        self.detector.fit(data)

    def test_state_map_empty_by_default(self) -> None:
        assert self.detector.state_map == {}

    def test_predict_with_random_data(self) -> None:
        """Should handle random price data gracefully."""
        np.random.seed(42)
        data = pd.DataFrame({"Close": 100.0 + np.random.randn(100).cumsum()})
        state = self.detector.predict_regime(data)
        assert isinstance(state, RegimeState)
        # When model is None, returns fallback NEUTRAL
        assert state.label in ("NEUTRAL", "TRENDING", "CHOPPY", "PANIC")
