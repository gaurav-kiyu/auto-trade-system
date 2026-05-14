"""
Data Quality Monitor - Detects anomalies in market data (price, volume, spread)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import logging

_log = logging.getLogger(__name__)


@dataclass
class DataQualityConfig:
    enabled: bool = True
    max_price_change_pct: float = 0.05
    volume_spike_mult: float = 5.0
    max_spread_pct: float = 0.03


class DataQualityMonitor:
    def __init__(self, config: DataQualityConfig):
        self.config = config
        self._last_price: Optional[float] = None
        self._last_volume: Optional[float] = None

    def check_price_anomaly(
        self,
        current_price: float,
        volume: float,
        bid: float,
        ask: float,
    ) -> tuple[bool, str]:
        if not self.config.enabled:
            return False, ""

        if self._last_price is not None and self._last_price > 0:
            price_change = abs(current_price - self._last_price) / self._last_price
            if price_change > self.config.max_price_change_pct:
                reason = f"PRICE SPIKE: {price_change*100:.2f}% change (threshold: {self.config.max_price_change_pct*100}%)"
                _log.warning(f"Data anomaly detected: {reason}")
                return True, reason

        if self._last_volume is not None and self._last_volume > 0:
            if volume > self._last_volume * self.config.volume_spike_mult:
                reason = f"VOLUME SPIKE: {volume/self._last_volume:.1f}x normal (threshold: {self.config.volume_spike_mult}x)"
                _log.warning(f"Data anomaly detected: {reason}")
                return True, reason

        if bid > 0 and ask > 0:
            spread_pct = (ask - bid) / bid
            if spread_pct > self.config.max_spread_pct:
                reason = f"WIDE SPREAD: {spread_pct*100:.2f}% (threshold: {self.config.max_spread_pct*100}%)"
                _log.warning(f"Data anomaly detected: {reason}")
                return True, reason

        self._last_price = current_price
        self._last_volume = volume
        return False, ""

    def reset(self):
        self._last_price = None
        self._last_volume = None


def create_data_quality_monitor(config: dict) -> DataQualityMonitor:
    cfg = DataQualityConfig(
        enabled=config.get("DATA_ANOMALY_DETECTION_ENABLED", True),
        max_price_change_pct=config.get("DATA_ANOMALY_PRICE_CHANGE_MAX_PCT", 0.05),
        volume_spike_mult=config.get("DATA_ANOMALY_VOLUME_SPIKE_MULT", 5.0),
        max_spread_pct=config.get("DATA_ANOMALY_SPREAD_MAX_PCT", 0.03),
    )
    return DataQualityMonitor(cfg)