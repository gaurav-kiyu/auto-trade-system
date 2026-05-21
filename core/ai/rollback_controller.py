"""
AD-KIYU AI Governance — Rollback Controller.

Monitors model performance drift and triggers automated rollback
to the last known-good model within 15 minutes of detection threshold breach.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

_log = logging.getLogger(__name__)


@dataclass
class RollbackEvent:
    model_id: str
    name: str
    version: str
    reason: str
    metric_name: str
    metric_value: float
    threshold: float
    ts: float = field(default_factory=time.time)
    rollback_to_id: str = ""


class RollbackController:
    """Monitors drift and triggers rollback to last ACTIVE model."""

    def __init__(self, drift_detector: Any = None, model_registry: Any = None):
        self._lock = threading.Lock()
        self._history: list[RollbackEvent] = []
        self._drift_detector = drift_detector
        self._model_registry = model_registry
        self._rollback_callback: Callable[[str], None] | None = None
        self._rolling_window_minutes: int = 60
        self._drift_threshold: float = 0.15
        self._brier_threshold: float = 0.30
        self._accuracy_threshold: float = 0.45

    def set_rollback_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback invoked with (model_id) on rollback."""
        self._rollback_callback = callback

    def evaluate(self, model_id: str, name: str, version: str, metrics: dict[str, float]) -> bool:
        """Evaluate metrics against thresholds. Returns True if rollback triggered."""
        reasons: list[str] = []
        if "brier_score" in metrics and metrics["brier_score"] > self._brier_threshold:
            reasons.append(f"brier {metrics['brier_score']:.3f} > {self._brier_threshold}")
        if "accuracy" in metrics and metrics["accuracy"] < self._accuracy_threshold:
            reasons.append(f"accuracy {metrics['accuracy']:.3f} < {self._accuracy_threshold}")
        if self._drift_detector is not None:
            try:
                drift = self._drift_detector.detect()
                if drift and drift.get("psi", 0) > self._drift_threshold:
                    reasons.append(f"drift PSI {drift.get('psi', 0):.3f} > {self._drift_threshold}")
            except Exception as e:
                _log.warning(f"[ROLLBACK] drift_detector error: {e}")

        if not reasons:
            return False

        rollback_to = model_id
        if self._model_registry is not None:
            prev = self._model_registry.get(model_id)  # fallback: same model
            # find last ACTIVE model with same name
            all_models = self._model_registry.list_by_name(name)
            for m in all_models:
                if m.status == "ACTIVE" and m.model_id != model_id:
                    rollback_to = m.model_id
                    break

        event = RollbackEvent(
            model_id=model_id,
            name=name,
            version=version,
            reason="; ".join(reasons),
            metric_name=reasons[0].split(" ")[0] if reasons else "",
            metric_value=metrics.get("brier_score", 0),
            threshold=self._brier_threshold,
            rollback_to_id=rollback_to,
        )
        with self._lock:
            self._history.append(event)

        _log.warning(
            f"[ROLLBACK] Triggered for {name} v{version} ({model_id}): "
            f"{event.reason}. Rolling back to {rollback_to}"
        )

        if self._rollback_callback:
            try:
                self._rollback_callback(rollback_to)
            except Exception as e:
                _log.error(f"[ROLLBACK] callback failed: {e}")

        return True

    def get_history(self) -> list[RollbackEvent]:
        """Get all rollback events."""
        with self._lock:
            return list(self._history)

    def recent_rollbacks(self, minutes: int = 60) -> list[RollbackEvent]:
        """Get rollback events within the last N minutes."""
        cutoff = time.time() - minutes * 60
        with self._lock:
            return [e for e in self._history if e.ts >= cutoff]

    def configure(self, **kwargs) -> None:
        """Update thresholds at runtime."""
        if "drift_threshold" in kwargs:
            self._drift_threshold = float(kwargs["drift_threshold"])
        if "brier_threshold" in kwargs:
            self._brier_threshold = float(kwargs["brier_threshold"])
        if "accuracy_threshold" in kwargs:
            self._accuracy_threshold = float(kwargs["accuracy_threshold"])
        if "rolling_window_minutes" in kwargs:
            self._rolling_window_minutes = int(kwargs["rolling_window_minutes"])
