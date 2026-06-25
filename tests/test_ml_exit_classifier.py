"""Tests for core.ml_exit_classifier - ML-based exit prediction."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from core.ml_exit_classifier import ExitPrediction, MLExitClassifier


class TestExitPrediction:
    """Tests for ExitPrediction dataclass."""

    def test_defaults(self) -> None:
        pred = ExitPrediction(exit_probability=0.0, should_exit=False, reasoning="test", confidence=0.0)
        assert pred.exit_probability == 0.0
        assert pred.should_exit is False
        assert pred.reasoning == "test"


class TestMLExitClassifier:
    """Tests for MLExitClassifier - exit prediction from trade state."""

    def setup_method(self) -> None:
        self.classifier = MLExitClassifier(model_path="/nonexistent/model.joblib")

    def test_no_model_returns_safe_default(self) -> None:
        """When model file doesn't exist, should not crash."""
        pred = self.classifier.predict_exit({
            "entry_price": 100.0,
            "current_price": 105.0,
            "peak_price": 107.0,
            "entry_time": datetime.now() - timedelta(minutes=30),
            "current_time": datetime.now(),
            "current_atr": 1.5,
            "entry_atr": 1.2,
        })
        assert pred.should_exit is False
        assert pred.exit_probability == 0.0
        assert "Model not loaded" in pred.reasoning

    def test_model_path_is_configurable(self) -> None:
        classifier = MLExitClassifier(model_path="/custom/path/model.joblib")
        assert classifier.model_path == "/custom/path/model.joblib"
        assert classifier.model is None

    def test_confidence_threshold_default(self) -> None:
        assert self.classifier.confidence_threshold == 0.80

    def test_prepare_features_returns_correct_shape(self) -> None:
        trade_data = {
            "entry_price": 100.0,
            "current_price": 105.0,
            "peak_price": 107.0,
            "entry_time": datetime.now() - timedelta(minutes=30),
            "current_time": datetime.now(),
            "current_atr": 1.5,
            "entry_atr": 1.2,
        }
        features = self.classifier.prepare_features(trade_data)
        assert isinstance(features, np.ndarray)
        assert features.shape == (1, 4)  # 4 features: age, pnl_pct, decay, vol_ratio

    def test_prepare_features_age_is_positive(self) -> None:
        trade_data = {
            "entry_price": 100.0,
            "current_price": 105.0,
            "peak_price": 107.0,
            "entry_time": datetime.now() - timedelta(minutes=30),
            "current_time": datetime.now(),
            "current_atr": 1.5,
            "entry_atr": 1.2,
        }
        features = self.classifier.prepare_features(trade_data)
        assert features[0][0] > 0  # age in minutes should be positive

    def test_prepare_features_pnl_correct(self) -> None:
        trade_data = {
            "entry_price": 100.0,
            "current_price": 105.0,
            "peak_price": 107.0,
            "entry_time": datetime.now() - timedelta(minutes=30),
            "current_time": datetime.now(),
            "current_atr": 1.5,
            "entry_atr": 1.2,
        }
        features = self.classifier.prepare_features(trade_data)
        # PnL = ((105 - 100) / 100) * 100 = 5%
        assert abs(features[0][1] - 5.0) < 0.01

    def test_prepare_features_decay_correct(self) -> None:
        trade_data = {
            "entry_price": 100.0,
            "current_price": 105.0,
            "peak_price": 107.0,
            "entry_time": datetime.now() - timedelta(minutes=30),
            "current_time": datetime.now(),
            "current_atr": 1.5,
            "entry_atr": 1.2,
        }
        features = self.classifier.prepare_features(trade_data)
        # Peak PnL = ((107 - 100) / 100) * 100 = 7%
        # Decay = 7 - 5 = 2%
        assert abs(features[0][2] - 2.0) < 0.01

    def test_prepare_features_vol_ratio(self) -> None:
        trade_data = {
            "entry_price": 100.0,
            "current_price": 105.0,
            "peak_price": 107.0,
            "entry_time": datetime.now() - timedelta(minutes=30),
            "current_time": datetime.now(),
            "current_atr": 1.5,
            "entry_atr": 1.2,
        }
        features = self.classifier.prepare_features(trade_data)
        # Vol ratio = 1.5 / 1.2 = 1.25
        assert abs(features[0][3] - 1.25) < 0.01

    def test_prepare_features_zero_entry_atr_defaults_to_one(self) -> None:
        trade_data = {
            "entry_price": 100.0,
            "current_price": 105.0,
            "peak_price": 107.0,
            "entry_time": datetime.now() - timedelta(minutes=30),
            "current_time": datetime.now(),
            "current_atr": 1.5,
            "entry_atr": 0.0,
        }
        features = self.classifier.prepare_features(trade_data)
        assert features[0][3] == 1.0  # default ratio when entry_atr is 0

    def test_losing_trade_pnl_negative(self) -> None:
        trade_data = {
            "entry_price": 100.0,
            "current_price": 95.0,
            "peak_price": 101.0,
            "entry_time": datetime.now() - timedelta(minutes=30),
            "current_time": datetime.now(),
            "current_atr": 1.5,
            "entry_atr": 1.2,
        }
        features = self.classifier.prepare_features(trade_data)
        assert features[0][1] < 0  # negative PnL
