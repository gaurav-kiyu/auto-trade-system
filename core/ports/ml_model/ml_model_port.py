"""
ML Model Port Interface - Abstract interface for ML model implementations.
Defines the contract for ML services that can be used throughout the trading system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class MLPrediction:
    """Container for ML model prediction results."""
    win_probability: float  # Probability of winning trade (0.0 to 1.0)
    confidence: float       # Confidence in the prediction (0.0 to 1.0)
    features_used: list[str]  # List of feature names used in prediction
    model_version: str      # Version of the model used
    prediction_timestamp: datetime  # When the prediction was made
    metadata: dict[str, Any]  # Additional metadata from the model


class MlModelPort(ABC):
    """
    Abstract interface for ML model services.

    This interface defines the contract that all ML model implementations
    must follow to be compatible with the trading system. It supports:
    - Win probability prediction for trading signals
    - Feature importance and model explainability
    - Model versioning and hot-swapping
    - Both synchronous and asynchronous prediction modes
    """

    @abstractmethod
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
        pass

    @abstractmethod
    def is_model_ready(self) -> bool:
        """
        Check if the ML model is loaded and ready for predictions.

        Returns:
            True if model is ready, False otherwise
        """
        pass

    @abstractmethod
    def get_model_info(self) -> dict[str, Any]:
        """
        Get information about the current ML model.

        Returns:
            Dictionary containing model metadata (version, features, training date, etc.)
        """
        pass

    @abstractmethod
    def get_feature_importance(self) -> dict[str, float]:
        """
        Get feature importance scores from the ML model.

        Returns:
            Dictionary mapping feature names to importance scores (0.0 to 1.0)
        """
        pass

    @abstractmethod
    def retrain_model(self, training_data: list[dict[str, Any]], labels: list[int]) -> bool:
        """
        Retrain the ML model with new training data.

        Args:
            training_data: List of feature dictionaries for training
            labels: List of binary labels (1 for win, 0 for loss)

        Returns:
            True if retraining was successful, False otherwise
        """
        pass

    @abstractmethod
    def validate_features(self, features: dict[str, Any]) -> tuple[bool, list[str]]:
        """
        Validate that input features match the model's expectations.

        Args:
            features: Dictionary of feature names to values to validate

        Returns:
            Tuple of (is_valid, list_of_missing_or_invalid_features)
        """
        pass


__all__ = [
    "MLPrediction",
    "MlModelPort",
]

