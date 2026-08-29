"""Tests for core.ml_inference - ML inference engine with safety fallback."""

from __future__ import annotations

import core.ml_inference
from core.ml_inference import MLInferenceEngine, MLPrediction, init_ml_engine


class TestMLPrediction:
    """Tests for MLPrediction dataclass."""

    def test_defaults(self) -> None:
        pred = MLPrediction(win_probability=0.5, confidence_score=0.0, features_used=[], regime_aware=False)
        assert pred.win_probability == 0.5
        assert pred.fallback_triggered is False
        assert pred.error is None

    def test_fallback_defaults(self) -> None:
        pred = MLPrediction(win_probability=0.5, confidence_score=0.0, features_used=[], regime_aware=False, fallback_triggered=True, error="Model missing")
        assert pred.fallback_triggered is True
        assert "Model missing" in pred.error


class TestMLInferenceEngine:
    """Tests for MLInferenceEngine - ML inference with safety gates."""

    def test_init_with_nonexistent_model(self) -> None:
        """Engine should initialize without error even when model file doesn't exist."""
        engine = MLInferenceEngine("/nonexistent/model.pkl", ["score", "confidence"])
        assert engine.model is None

    def test_predict_with_no_model_returns_fallback(self) -> None:
        """When no model is loaded, predict returns neutral fallback."""
        engine = MLInferenceEngine("/nonexistent/model.pkl", ["score", "confidence"])
        pred = engine.predict({"score": 75.0, "confidence": 0.8})
        assert pred.win_probability == 0.5
        assert pred.fallback_triggered is True
        assert pred.regime_aware is False

    def test_feature_validation_none_value_triggers_fallback(self) -> None:
        """A missing feature should trigger fallback."""
        engine = MLInferenceEngine("/nonexistent/model.pkl", ["score", "confidence"])
        pred = engine.predict({"score": None, "confidence": 0.8})
        assert pred.fallback_triggered is True

    def test_feature_validation_nan_triggers_fallback(self) -> None:
        """A NaN feature should trigger fallback."""
        engine = MLInferenceEngine("/nonexistent/model.pkl", ["score", "confidence"])
        pred = engine.predict({"score": float("nan"), "confidence": 0.8})
        assert pred.fallback_triggered is True

    def test_feature_validation_outlier_triggers_fallback(self) -> None:
        """An absurdly high feature value should trigger fallback."""
        engine = MLInferenceEngine("/nonexistent/model.pkl", ["score", "confidence"])
        pred = engine.predict({"score": 1e7, "confidence": 0.8})
        assert pred.fallback_triggered is True

    def test_predict_with_no_model_high_vol(self) -> None:
        """HIGH_VOL regime with no model uses default fallback."""
        engine = MLInferenceEngine("/nonexistent/model.pkl", ["score"])
        pred = engine.predict({"score": 75.0}, regime="HIGH_VOL")
        assert pred.fallback_triggered is True  # no model, always fallback
        assert pred.regime_aware is False

    def test_custom_feature_cols(self) -> None:
        """Engine should accept custom feature columns."""
        cols = ["score", "confidence", "vix", "pcr"]
        engine = MLInferenceEngine("/nonexistent/model.pkl", cols)
        assert engine.feature_cols == cols
        pred = engine.predict({"score": 75, "confidence": 0.8, "vix": 15.0, "pcr": 1.2})
        assert pred.features_used == cols
        assert pred.fallback_triggered is True  # no model loaded

    def test_partial_features_returns_fallback(self) -> None:
        """Missing some features should return fallback prediction."""
        engine = MLInferenceEngine("/nonexistent/model.pkl", ["score", "confidence", "vix"])
        pred = engine.predict({"score": 75.0, "confidence": 0.8})  # missing vix
        assert pred.fallback_triggered is True


class TestInitMlEngine:
    """Tests for init_ml_engine convenience function."""

    def test_init_sets_global(self) -> None:
        init_ml_engine("/nonexistent/model.pkl", ["score"])
        # Note: ml_engine should be set via the module global
        assert core.ml_inference.ml_engine is not None
        assert core.ml_inference.ml_engine.model is None
