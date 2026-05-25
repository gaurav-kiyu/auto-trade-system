"""
ML Model Adapter

Adapter that implements the MlModelPort interface using the existing ML classifier and performance tracker.
"""

from __future__ import annotations

import time
from typing import Any

from core.datetime_ist import now_ist

# Import the port interface and MLPrediction
from core.ports.ml_model import MlModelPort, MLPrediction

# Import existing ML components
try:
    from core.ml_classifier import (
        FEATURE_COLS,
        get_classifier,
        load_model,
        predict_win_prob,
        save_model,
    )
    from core.ml_classifier import (
        train as ml_train,
    )
    from core.ml_performance_tracker import get_feature_importance as get_performance_feature_importance
except ImportError:
    # Fallback for development
    FEATURE_COLS = []  # type: ignore
    get_classifier = None  # type: ignore
    predict_win_prob = None  # type: ignore
    ml_train = None  # type: ignore
    save_model = None  # type: ignore
    load_model = None  # type: ignore
    get_performance_feature_importance = None  # type: ignore


class MLModelAdapter(MlModelPort):
    """
    Adapter that implements MlModelPort using the existing ML classifier.

    This follows the Dependency Inversion Principle - high-level modules (trading logic)
    depend on abstractions (MlModelPort), not concretions (specific ML implementation).
    """

    def __init__(self, journal_path: str | None = None, config: dict[str, Any] | None = None):
        """
        Initialize the ML model adapter.

        Args:
            journal_path: Path to the trade journal database (for training/loading model).
            config: Configuration dictionary for the ML model.
        """
        self.journal_path = journal_path or "ml_tracker.db"
        self.config = config or {}
        self._model: Any = None
        self._model_loaded_at: float = 0.0
        self._model_version = "1.0.0"  # Fixed version for now; could be enhanced

        # Load the model on initialization
        self._reload_model()

    def _reload_model(self) -> None:
        """Load or reload the ML model from disk or cache."""
        if get_classifier is None:
            self._model = None
            return

        try:
            self._model = get_classifier(self.journal_path, self.config)
            self._model_loaded_at = time.time()
        except Exception as e:
            # Log error and set model to None
            import logging
            logging.getLogger(__name__).error(f"Failed to load ML model: {e}")
            self._model = None

    def predict_win_probability(self, features: dict[str, Any]) -> MLPrediction:
        """
        Predict the probability of a trade being successful based on input features.

        Args:
            features: Dictionary of feature names to values for the ML model

        Returns:
            MLPrediction object containing win probability and metadata

        Raises:
            ValueError: If features are invalid or missing required fields
            RuntimeError: If model is not ready or prediction fails
        """
        if not self.is_model_ready():
            raise RuntimeError("ML model is not ready")

        # Validate features
        is_valid, invalid_features = self.validate_features(features)
        if not is_valid:
            raise ValueError(f"Invalid or missing features: {invalid_features}")

        if predict_win_prob is None:
            raise RuntimeError("ML prediction function not available")

        try:
            # The existing predict_win_prob returns a float (win probability)
            win_probability = predict_win_prob(self._model, features)
            # Ensure it's within bounds
            win_probability = max(0.0, min(1.0, float(win_probability)))

            # For confidence, we use the win_probability as a placeholder.
            # In a more sophisticated model, we might have a separate confidence score.
            confidence = win_probability

            return MLPrediction(
                win_probability=win_probability,
                confidence=confidence,
                features_used=list(features.keys()),
                model_version=self._model_version,
                prediction_timestamp=now_ist(),
                metadata={}
            )
        except Exception as e:
            raise RuntimeError(f"ML prediction failed: {e}") from e

    def is_model_ready(self) -> bool:
        """
        Check if the ML model is loaded and ready for predictions.

        Returns:
            True if model is ready, False otherwise
        """
        return self._model is not None

    def get_model_info(self) -> dict[str, Any]:
        """
        Get information about the current ML model.

        Returns:
            Dictionary containing model metadata (version, features, training date, etc.)
        """
        info = {
            "model_version": self._model_version,
            "model_loaded_at": self._model_loaded_at,
            "features_expected": FEATURE_COLS.copy(),
            "journal_path": self.journal_path,
        }
        # Add any additional info from config if available
        if self.config:
            info["config"] = self.config.copy()
        return info

    def get_feature_importance(self) -> dict[str, float]:
        """
        Get feature importance scores from the ML model.

        Returns:
            Dictionary mapping feature names to importance scores (0.0 to 1.0)
        """
        if get_performance_feature_importance is None:
            return {}

        try:
            # The existing function might return a trend or dict; we assume it returns dict of feature->importance
            importance = get_performance_feature_importance()
            if isinstance(importance, dict):
                return importance
            else:
                # If it's not a dict, return empty
                return {}
        except Exception:
            return {}

    def retrain_model(self, training_data: list[dict[str, Any]], labels: list[int]) -> bool:
        """
        Retrain the ML model with new training data.

        Args:
            training_data: List of feature dictionaries for training
            labels: List of binary labels (1 for win, 0 for loss)

        Returns:
            True if retraining was successful, False otherwise
        """
        if ml_train is None or save_model is None:
            return False

        try:
            # Train the model
            model = ml_train(self.journal_path, self.config, training_data, labels)
            if model is None:
                return False

            # Save the model
            save_success = save_model(model, self.journal_path.replace(".db", "_model.pkl"))
            if not save_success:
                return False

            # Update the internal model
            self._model = model
            self._model_loaded_at = time.time()
            return True
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"ML model retraining failed: {e}")
            return False

    def validate_features(self, features: dict[str, Any]) -> tuple[bool, list[str]]:
        """
        Validate that input features match the model's expectations.

        Args:
            features: Dictionary of feature names to values to validate

        Returns:
            Tuple of (is_valid, list_of_missing_or_invalid_features)
        """
        if not FEATURE_COLS:
            # If we don't have expected features, assume valid
            return True, []

        missing = []
        for feature in FEATURE_COLS:
            if feature not in features:
                missing.append(feature)

        # Additionally, we could check for extra features, but the port doesn't require it.
        # We'll only report missing features.
        return len(missing) == 0, missing
