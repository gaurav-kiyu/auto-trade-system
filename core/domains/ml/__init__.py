"""ML Domain Models - Machine learning predictions, features, and model metrics.

Models ML-related data structures:
  - MLPrediction: Prediction output from ML model
  - MLConfidence: Confidence level (LOW, MEDIUM, HIGH)
  - ModelFeature: Individual feature with importance
  - ModelMetrics: Model performance metrics (accuracy, precision, etc.)

Usage:
    from core.domains.ml import (
        MLPrediction, MLConfidence, ModelFeature, ModelMetrics
    )
"""
from core.domains.ml.model import (
    MLConfidence,
    MLPrediction,
    ModelFeature,
    ModelMetrics,
)

__all__ = [
    "MLConfidence",
    "MLPrediction",
    "ModelFeature",
    "ModelMetrics",
]
