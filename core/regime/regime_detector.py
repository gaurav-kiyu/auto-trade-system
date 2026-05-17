"""
Regime Detection - Item 20

System behavior adapts to market regimes:
- low_vol
- high_vol
- trending
- mean_reverting
- expiry_regime
- event_day_regime

Huge future alpha potential - adapts strategy to market conditions.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from core.datetime_ist import now_ist
from enum import Enum
from typing import Any

from core.time_provider import time_provider

_log = logging.getLogger(__name__)


class MarketRegime(Enum):
    """Market regime types"""
    LOW_VOL = "LOW_VOL"
    HIGH_VOL = "HIGH_VOL"
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    MEAN_REVERTING = "MEAN_REVERTING"
    CONSOLIDATING = "CONSOLIDATING"
    EXPIRY_REGIME = "EXPIRY_REGIME"
    EVENT_DAY = "EVENT_DAY"
    NORMAL = "NORMAL"


@dataclass
class RegimeSnapshot:
    """Regime state at a point in time"""
    regime: MarketRegime
    confidence: float
    volatility: float
    trend_strength: float
    timestamp: str
    metadata: dict[str, Any] = field(default_factory=dict)


class RegimeDetector:
    """
    Market regime detection system.
    Adapts strategy behavior based on detected market conditions.
    """

    PERSISTENCE_PATH = "regime_detector.db"

    def __init__(self):
        self._current_regime: MarketRegime = MarketRegime.NORMAL
        self._regime_history: deque = deque(maxlen=1000)
        self._price_history: deque = deque(maxlen=100)
        self._lock = threading.Lock()

        self._vol_threshold_low = 0.5
        self._vol_threshold_high = 2.0
        self._trend_lookback = 20
        self._init_durable_storage()

    def _init_durable_storage(self) -> None:
        """Initialize regime detector storage"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS regime_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        regime TEXT,
                        confidence REAL,
                        volatility REAL,
                        trend_strength REAL,
                        timestamp TEXT,
                        metadata_json TEXT
                    )
                """)
                conn.commit()
            _log.info("RegimeDetector: Storage initialized")
        except Exception as e:
            _log.error(f"RegimeDetector: Failed to init storage: {e}")

    def update_price(self, price: float, timestamp: str = None) -> None:
        """Update price for regime detection"""
        with self._lock:
            self._price_history.append({
                "price": price,
                "timestamp": timestamp or time_provider.format_ts(),
            })

            if len(self._price_history) >= 10:
                self._detect_regime()

    def _detect_regime(self) -> None:
        """Detect current market regime"""
        prices = [p["price"] for p in self._price_history]

        volatility = self._calculate_volatility(prices)
        trend_strength = self._calculate_trend_strength(prices)

        regime = MarketRegime.NORMAL
        confidence = 0.5

        if volatility < self._vol_threshold_low:
            regime = MarketRegime.LOW_VOL
            confidence = 0.7
        elif volatility > self._vol_threshold_high:
            regime = MarketRegime.HIGH_VOL
            confidence = 0.7

        if trend_strength > 0.6:
            if prices[-1] > prices[0]:
                regime = MarketRegime.TRENDING_UP
            else:
                regime = MarketRegime.TRENDING_DOWN
            confidence = min(0.9, confidence + 0.2)
        elif abs(trend_strength) < 0.2:
            regime = MarketRegime.CONSOLIDATING
            confidence = 0.6

        self._check_special_regimes(regime)

        snapshot = RegimeSnapshot(
            regime=regime,
            confidence=confidence,
            volatility=volatility,
            trend_strength=trend_strength,
            timestamp=time_provider.format_ts(),
        )

        self._current_regime = regime
        self._regime_history.append(snapshot)
        self._persist_regime(snapshot)

        _log.info(f"Detected regime: {regime.value} (confidence: {confidence:.2f})")

    def _calculate_volatility(self, prices: list[float]) -> float:
        """Calculate volatility (std dev of returns)"""
        if len(prices) < 2:
            return 0.0

        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]

        if not returns:
            return 0.0

        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)

        return variance ** 0.5

    def _calculate_trend_strength(self, prices: list[float]) -> float:
        """Calculate trend strength using linear regression"""
        if len(prices) < 2:
            return 0.0

        n = len(prices)
        x = list(range(n))

        sum_x = sum(x)
        sum_y = sum(prices)
        sum_xy = sum(x[i] * prices[i] for i in range(n))
        sum_xx = sum(x[i] * x[i] for i in range(n))

        slope = (n * sum_xy - sum_x * sum_y) / (n * sumxx - sum_x * sum_x) if (n * sumxx - sum_x * sum_x) != 0 else 0

        avg_price = sum_y / n
        normalized_slope = slope / avg_price if avg_price != 0 else 0

        return normalized_slope

    def _check_special_regimes(self, regime: MarketRegime) -> None:
        """Check for special regimes like expiry, event day"""
        now = now_ist()

        if now.weekday() == 4 and now.hour >= 14:
            self._current_regime = MarketRegime.EXPIRY_REGIME
            _log.info("Expiry regime detected - Thursday afternoon")

        if self._is_event_day(now):
            self._current_regime = MarketRegime.EVENT_DAY

    def _is_event_day(self, dt: datetime) -> bool:
        """Check if today is an event day"""
        event_days = [
            "01-01",
            "26-01",
            "15-08",
            "02-10",
            "25-12",
        ]

        date_str = dt.strftime("%m-%d")
        return date_str in event_days

    def get_current_regime(self) -> MarketRegime:
        """Get current regime"""
        return self._current_regime

    def get_regime_confidence(self) -> float:
        """Get confidence of current regime"""
        with self._lock:
            if self._regime_history:
                return self._regime_history[-1].confidence
            return 0.0

    def get_regime_history(self, limit: int = 100) -> list[RegimeSnapshot]:
        """Get regime history"""
        with self._lock:
            return list(self._regime_history)[-limit:]

    def get_regime_stats(self) -> dict[str, Any]:
        """Get regime statistics"""
        with self._lock:
            if not self._regime_history:
                return {"current": "NORMAL", "confidence": 0.0}

            latest = self._regime_history[-1]

            regime_counts = {}
            for snapshot in self._regime_history:
                regime_counts[snapshot.regime.value] = regime_counts.get(snapshot.regime.value, 0) + 1

            return {
                "current": latest.regime.value,
                "confidence": latest.confidence,
                "volatility": latest.volatility,
                "trend_strength": latest.trend_strength,
                "regime_distribution": regime_counts,
            }

    def apply_regime_adjustment(
        self,
        base_position_size: float,
        base_stop_loss: float,
        base_target: float,
    ) -> dict[str, float]:
        """
        Apply regime-based adjustments to trading parameters.
        
        Returns adjusted position size, stop loss, and target.
        """
        regime = self.get_current_regime()

        position_mult = 1.0
        sl_mult = 1.0
        target_mult = 1.0

        if regime == MarketRegime.LOW_VOL:
            position_mult = 1.5
            sl_mult = 0.8
            target_mult = 1.2
        elif regime == MarketRegime.HIGH_VOL:
            position_mult = 0.7
            sl_mult = 1.3
            target_mult = 0.8
        elif regime == MarketRegime.TRENDING_UP or regime == MarketRegime.TRENDING_DOWN:
            position_mult = 1.2
            sl_mult = 1.0
            target_mult = 1.3
        elif regime == MarketRegime.MEAN_REVERTING:
            position_mult = 0.8
            sl_mult = 0.7
            target_mult = 0.9
        elif regime == MarketRegime.CONSOLIDATING:
            position_mult = 0.6
            sl_mult = 1.2
            target_mult = 0.7
        elif regime == MarketRegime.EXPIRY_REGIME:
            position_mult = 0.5
            sl_mult = 1.5
            target_mult = 0.6
        elif regime == MarketRegime.EVENT_DAY:
            position_mult = 0.4
            sl_mult = 2.0
            target_mult = 0.5

        return {
            "position_size": base_position_size * position_mult,
            "stop_loss": base_stop_loss * sl_mult,
            "target": base_target * target_mult,
        }

    def _persist_regime(self, snapshot: RegimeSnapshot) -> None:
        """Persist regime snapshot"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    INSERT INTO regime_history
                    (regime, confidence, volatility, trend_strength, timestamp, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    snapshot.regime.value,
                    snapshot.confidence,
                    snapshot.volatility,
                    snapshot.trend_strength,
                    snapshot.timestamp,
                    json.dumps(snapshot.metadata),
                ))
                conn.commit()
        except Exception as e:
            _log.error(f"Failed to persist regime: {e}")


_regime_detector: RegimeDetector | None = None
_detector_lock = threading.Lock()


def get_regime_detector() -> RegimeDetector:
    """Get singleton regime detector"""
    global _regime_detector
    with _detector_lock:
        if _regime_detector is None:
            _regime_detector = RegimeDetector()
        return _regime_detector
