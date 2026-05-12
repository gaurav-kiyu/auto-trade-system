"""
ML Domain Models

This module contains the data models used in the ML domain,
including predictions and confidence levels.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any


class MLConfidence(Enum):
    """Confidence levels for ML predictions."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class MLPrediction:
    """
    Represents a prediction from an ML model.

    Attributes:
        prediction_value: The predicted value (typically 0.0 to 1.0 for probabilities)
        confidence: Confidence level in the prediction
        features_used: List of feature names used for this prediction
        model_version: Version of the model that made this prediction
        prediction_timestamp: When the prediction was made
        metadata: Additional metadata about the prediction
    """
    prediction_value: float
    confidence: MLConfidence
    features_used: list[str] = None
    model_version: str = "unknown"
    prediction_timestamp: float = None  # Unix timestamp
    metadata: dict[str, Any] = None

    def __post_init__(self):
        """Validate prediction after initialization."""
        if self.features_used is None:
            self.features_used = []

        if self.prediction_timestamp is None:
            self.prediction_timestamp = time.time()

        if self.metadata is None:
            self.metadata = {}

        # Validate prediction value is between 0 and 1
        if not 0.0 <= self.prediction_value <= 1.0:
            raise ValueError(f"Prediction value must be between 0.0 and 1.0, got {self.prediction_value}")

        if not isinstance(self.confidence, MLConfidence):
            # Allow string values for backward compatibility
            if isinstance(self.confidence, str):
                try:
                    self.confidence = MLConfidence(self.confidence.lower())
                except ValueError:
                    self.confidence = MLConfidence.MEDIUM
            else:
                self.confidence = MLConfidence.MEDIUM


@dataclass
class ModelFeature:
    """
    Represents a feature used in ML models.

    Attributes:
        name: Feature name
        value: Feature value
        importance: Feature importance score (0.0 to 1.0)
        category: Feature category (e.g., "technical", "sentiment", "volume")
    """
    name: str
    value: Any
    importance: float = 0.0
    category: str = "general"

    def __post_init__(self):
        """Validate feature after initialization."""
        if not 0.0 <= self.importance <= 1.0:
            raise ValueError(f"Feature importance must be between 0.0 and 1.0, got {self.importance}")


@dataclass
class ModelMetrics:
    """
    Represents performance metrics for an ML model.

    Attributes:
        accuracy: Classification accuracy
        precision: Precision score
        recall: Recall score
        f1_score: F1 score
        auc_roc: AUC-ROC score
        brier_score: Brier score for probability calibration
        sharpe_ratio: Sharpe ratio of strategy using this model
        max_drawdown: Maximum drawdown
        total_trades: Total number of trades
        winning_trades: Number of winning trades
    """
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    auc_roc: float = 0.0
    brier_score: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0

    def __post_init__(self):
        """Validate metrics after initialization."""
        metrics_to_check = [
            ("accuracy", self.accuracy),
            ("precision", self.precision),
            ("recall", self.recall),
            ("f1_score", self.f1_score),
            ("auc_roc", self.auc_roc),
            ("brier_score", self.brier_score),
        ]

        for name, value in metrics_to_check:
            if not 0.0 <= value <= 1.0:
                # Some metrics like brier score can be >1 for poor predictions
                if name != "brier_score" or value < 0.0:
                    raise ValueError(f"{name} must be between 0.0 and 1.0, got {value}")

        if self.total_trades < 0:
            raise ValueError(f"Total trades must be non-negative, got {self.total_trades}")

        if self.winning_trades < 0:
            raise ValueError(f"Winning trades must be non-negative, got {self.winning_trades}")

        if self.winning_trades > self.total_trades:
            raise ValueError(
                f"Winning trades ({self.winning_trades}) cannot exceed total trades ({self.total_trades})"
            )
