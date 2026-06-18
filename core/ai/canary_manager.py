"""
AD-KIYU AI Governance - Canary Manager.

Staged canary rollout of ML models:
  10% → 50% → 100% over configured trading days.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

_log = logging.getLogger(__name__)


@dataclass
class CanaryState:
    model_id: str
    name: str
    version: str
    stage: int          # 0=10%, 1=50%, 2=100%
    start_ts: float
    trades_seen: int = 0
    trades_won: int = 0
    trades_lost: int = 0


class CanaryManager:
    """Manages canary deployment lifecycle for ML models."""

    def __init__(
        self,
        stage_days: tuple[int, int, int] = (1, 2, 2),
        stage_thresholds: tuple[float, float, float] = (0.10, 0.50, 1.0),
    ):
        """
        Args:
            stage_days: Trading days at each stage (10%, 50%, 100%)
            stage_thresholds: Fraction of trades routed to canary at each stage
        """
        self._lock = threading.RLock()
        self._canaries: dict[str, CanaryState] = {}
        self._stage_days = stage_days
        self._stage_thresholds = stage_thresholds

    def start_canary(self, model_id: str, name: str, version: str) -> CanaryState:
        """Register a new canary deployment at stage 0 (10%)."""
        state = CanaryState(
            model_id=model_id,
            name=name,
            version=version,
            stage=0,
            start_ts=time.time(),
        )
        with self._lock:
            self._canaries[model_id] = state
        _log.info(f"[CANARY] Started canary for {name} v{version} ({model_id}) stage=10%")
        return state

    def should_route_to_canary(self, model_id: str) -> bool:
        """Return True if the current trade should be routed to the canary model."""
        with self._lock:
            state = self._canaries.get(model_id)
        if state is None:
            return False
        threshold = self._stage_thresholds[state.stage]

        import random
        return random.random() < threshold

    def record_trade_result(self, model_id: str, won: bool) -> None:
        """Record whether the canary model's trade won or lost."""
        with self._lock:
            state = self._canaries.get(model_id)
        if state is None:
            return
        state.trades_seen += 1
        if won:
            state.trades_won += 1
        else:
            state.trades_lost += 1

    def advance_stage(self, model_id: str) -> bool:
        """Advance canary to next stage. Returns True if advanced, False if at max."""
        with self._lock:
            state = self._canaries.get(model_id)
        if state is None:
            return False
        if state.stage >= 2:
            return False
        state.stage += 1
        pct = int(self._stage_thresholds[state.stage] * 100)
        _log.info(f"[CANARY] Canary {model_id} advanced to stage={pct}%")
        return True

    def get_state(self, model_id: str) -> CanaryState | None:
        """Get current canary state."""
        with self._lock:
            return self._canaries.get(model_id)

    def is_canary_ready_for_promotion(self, model_id: str, min_trades: int = 20, min_win_rate: float = 0.55) -> bool:
        """Check if canary has enough data to be promoted to ACTIVE."""
        state = self.get_state(model_id)
        if state is None:
            return False
        if state.trades_seen < min_trades:
            return False
        if state.trades_seen == 0:
            return False
        win_rate = state.trades_won / state.trades_seen
        return win_rate >= min_win_rate

    def end_canary(self, model_id: str) -> CanaryState | None:
        """End a canary deployment and return final stats."""
        with self._lock:
            return self._canaries.pop(model_id, None)

    def list_active(self) -> list[CanaryState]:
        """List all active canary deployments."""
        with self._lock:
            return list(self._canaries.values())
