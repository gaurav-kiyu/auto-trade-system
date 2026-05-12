"""
Anomaly Detection System
Detects anomalies in key system metrics using statistical methods (z-score).
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

_log = logging.getLogger(__name__)

_DEFAULT_HISTORY_FILE = "anomaly_history.json"
_DEFAULT_WINDOW_SIZE = 100
_DEFAULT_Z_THRESHOLD = 3.0


class AnomalyDetector:
    """
    Detects anomalies in a time series of metric values using z-score.
    """

    def __init__(
        self,
        history_file: str = _DEFAULT_HISTORY_FILE,
        window_size: int = _DEFAULT_WINDOW_SIZE,
        z_threshold: float = _DEFAULT_Z_THRESHOLD,
    ):
        """
        Initialize the anomaly detector.

        Args:
            history_file: Path to JSON file storing metric history.
            window_size: Number of historical values to keep for each metric.
            z_threshold: Z-score threshold for anomaly detection (e.g., 3.0 for 3 sigma).
        """
        self.history_file = Path(history_file)
        self.window_size = window_size
        self.z_threshold = z_threshold
        self.history: dict[str, list[float]] = self._load_history()

    def _load_history(self) -> dict[str, list[float]]:
        """Load metric history from JSON file."""
        if not self.history_file.exists():
            return {}
        try:
            with open(self.history_file) as f:
                data = json.load(f)
                # Ensure each metric's history is a list and truncate to window size
                for key, values in data.items():
                    if isinstance(values, list):
                        data[key] = values[-self.window_size :]
                    else:
                        data[key] = []
                return data
        except Exception as e:
            _log.warning(f"Failed to load anomaly history from {self.history_file}: {e}")
            return {}

    def _save_history(self) -> None:
        """Save metric history to JSON file."""
        try:
            # Ensure the directory exists
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, "w") as f:
                json.dump(self.history, f, indent=2)
        except Exception as e:
            _log.error(f"Failed to save anomaly history to {self.history_file}: {e}")

    def update_and_check(self, metric_name: str, value: float) -> tuple[bool, float]:
        """
        Update the history for a metric and check if the new value is an anomaly.
        The anomaly is determined by considering the value in the context of
        historical values + [value] (i.e., what the z-score would be after adding this value).

        Returns:
            (is_anomaly, z_score)
                is_anomaly: True if the value is considered an anomaly.
                z_score: The computed z-score.
        """
        # Initialize history for this metric if not present
        if metric_name not in self.history:
            self.history[metric_name] = []

        # Create temporary history including current value for calculation
        historical_values = self.history[metric_name][:]
        # Truncate historical values to window size (most recent)
        if len(historical_values) > self.window_size:
            historical_values = historical_values[-self.window_size :]

        # Temporary dataset includes historical values + current value
        temp_history = historical_values + [value]

        # Calculate statistics on temp_history
        if len(temp_history) == 0:
            return False, 0.0
        elif len(temp_history) == 1:
            # Can't compute meaningful statistics with only one value
            # Add value to real history and return
            self.history[metric_name].append(value)
            if len(self.history[metric_name]) > self.window_size:
                self.history[metric_name] = self.history[metric_name][-self.window_size :]
            self._save_history()
            return False, 0.0

        # Calculate statistics from temp_history (history + current value)
        mean = sum(temp_history) / len(temp_history)
        # Compute population variance (divide by n, not n-1)
        variance = sum((x - mean) ** 2 for x in temp_history) / len(temp_history)
        std = math.sqrt(variance) if variance > 0 else 0.0

        if std == 0.0:
            # All values in temp_history are the same
            # Current value is not an anomaly if it equals the historical uniform value
            is_anomaly = value != temp_history[0] if temp_history else False
            z_score = 0.0
            if is_anomaly:
                _log.warning(
                    f"Anomaly detected in metric {metric_name}: value={value}, historical uniform value={temp_history[0] if temp_history else 'N/A'}"
                )
        else:
            # Calculate z-score of current value relative to the distribution
            z_score = abs((value - mean) / std)
            is_anomaly = z_score > self.z_threshold

            if is_anomaly:
                _log.warning(
                    f"Anomaly detected in metric {metric_name}: value={value}, mean={mean:.2f}, std={std:.2f}, z-score={z_score:.2f}"
                )

        # Append current value to history
        self.history[metric_name].append(value)
        # Truncate to window size
        if len(self.history[metric_name]) > self.window_size:
            self.history[metric_name] = self.history[metric_name][-self.window_size :]
        self._save_history()

        return is_anomaly, z_score

    def get_history(self, metric_name: str) -> list[float]:
        """Return the history list for a metric."""
        return self.history.get(metric_name, [])


# Convenience function for external use
def detect_anomaly(
    metric_name: str,
    value: float,
    history_file: str = _DEFAULT_HISTORY_FILE,
    window_size: int = _DEFAULT_WINDOW_SIZE,
    z_threshold: float = _DEFAULT_Z_THRESHOLD,
) -> tuple[bool, float]:
    """
    Detect if a single metric value is an anomaly.
    This function creates a temporary detector, updates history, and checks.
    Note: This is not efficient for frequent calls because it reloads history each time.
    For frequent updates, use the AnomalyDetector class directly.
    """
    detector = AnomalyDetector(history_file=history_file, window_size=window_size, z_threshold=z_threshold)
    return detector.update_and_check(metric_name, value)
