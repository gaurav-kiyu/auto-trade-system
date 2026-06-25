"""
Data Quality Monitor — Enhanced Institutional-Grade Version.

Detects anomalies in market data using multiple complementary methods:
  1. Rule-based (existing): price spikes, volume spikes, wide spreads
  2. Statistical (new): z-score, rolling window mean/std, IQR
  3. Completeness checks (new): missing values, stale data, gap detection
  4. Schema validation (new): expected fields, types, value ranges
  5. Data freshness monitoring (new): age-based staleness detection

All findings are recorded as DataQualityFinding objects and can be
reported to the SLO governance system for automated alerting.

Usage
-----
    from core.data_quality_monitor import DataQualityMonitor

    dqm = DataQualityMonitor(config)
    findings = dqm.check_price_anomaly(price, volume, bid, ask)
    findings += dqm.check_data_freshness(timestamp, max_age_seconds=30)
    findings += dqm.check_schema(data, expected_fields={"last_price": float})

    for f in findings:
        print(f.severity, f.message)
"""

from __future__ import annotations

import logging
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

_log = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class DataQualityConfig:
    """Configuration for the Data Quality Monitor."""
    # Global
    enabled: bool = True

    # Rule-based thresholds (existing)
    max_price_change_pct: float = 0.05       # 5% max single-bar change
    volume_spike_mult: float = 5.0           # 5x normal volume
    max_spread_pct: float = 0.03             # 3% max bid-ask spread

    # Statistical anomaly detection (new)
    zscore_threshold: float = 3.0            # Values beyond 3 sigma are anomalous
    rolling_window_size: int = 20            # Bars for rolling statistics
    iqr_multiplier: float = 1.5              # IQR outlier multiplier

    # Data freshness (new)
    max_data_age_seconds: float = 60.0       # Max age before data is stale
    stale_data_warn_seconds: float = 30.0    # Warning threshold

    # Completeness checks (new)
    max_missing_pct: float = 10.0            # Max % missing fields before warning
    min_data_points_for_trend: int = 5       # Min points for trend analysis

    # Schema validation (new)
    expected_numeric_fields: list[str] = field(default_factory=lambda: [
        "last_price", "open", "high", "low", "close", "volume", "bid", "ask"
    ])
    expected_string_fields: list[str] = field(default_factory=lambda: [
        "symbol", "timestamp"
    ])

    # Trend/seasonality detection (new)
    enable_trend_detection: bool = True
    trend_window_hours: int = 1


@dataclass
class DataQualityFinding:
    """A single data quality observation."""
    category: str          # "PRICE", "VOLUME", "SPREAD", "FRESHNESS", "COMPLETENESS", "SCHEMA", "STATISTICAL"
    severity: str          # "INFO", "WARN", "ERROR", "CRITICAL"
    message: str
    value: float | None = None
    threshold: float | None = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ── Data Quality Monitor ──────────────────────────────────────────────────────

class DataQualityMonitor:
    """Enhanced data quality monitor with statistical and completeness checks.

    Thread-safe: uses deque for rolling windows (no explicit lock needed for
    CPython due to GIL on simple operations).
    """

    def __init__(self, config: DataQualityConfig | None = None):
        self.config = config or DataQualityConfig()

        # Rule-based state (existing)
        self._last_price: float | None = None
        self._last_volume: float | None = None

        # Statistical rolling windows (new)
        self._price_window: deque[float] = deque(maxlen=self.config.rolling_window_size)
        self._volume_window: deque[float] = deque(maxlen=self.config.rolling_window_size)
        self._spread_window: deque[float] = deque(maxlen=self.config.rolling_window_size)

        # Freshness tracking (new)
        self._last_data_timestamp: float | None = None
        self._data_gap_start: float | None = None

        # Completeness tracking (new)
        self._total_checks: int = 0
        self._total_findings: int = 0

    # ── Public API ──────────────────────────────────────────────────────────

    def check_price_anomaly(
        self,
        current_price: float,
        volume: float,
        bid: float,
        ask: float,
        symbol: str = "",
    ) -> list[DataQualityFinding]:
        """Run all anomaly checks on a market data tick.

        Returns a list of DataQualityFindings (empty = all healthy).
        """
        if not self.config.enabled:
            return []

        findings: list[DataQualityFinding] = []
        self._total_checks += 1

        # 1. Rule-based checks (existing)
        findings.extend(self._check_rule_based(current_price, volume, bid, ask))

        # 2. Statistical checks (new)
        findings.extend(self._check_statistical(current_price, volume, bid, ask))

        # Update rolling windows
        self._price_window.append(current_price)
        self._volume_window.append(volume)
        if bid > 0 and ask > 0:
            self._spread_window.append((ask - bid) / bid)
        else:
            self._spread_window.append(0.0)

        # Update last values for rule-based checks
        self._last_price = current_price
        self._last_volume = volume

        self._total_findings += len(findings)
        return findings

    def check_data_freshness(
        self,
        data_timestamp: float | None = None,
        max_age_seconds: float | None = None,
    ) -> list[DataQualityFinding]:
        """Check if data is fresh / detect staleness and gaps.

        Args:
            data_timestamp: Unix timestamp of the data point (None = use current time).
            max_age_seconds: Override max age threshold.

        Returns:
            List of DataQualityFindings (empty = fresh data).
        """
        if not self.config.enabled:
            return []

        findings: list[DataQualityFinding] = []
        now = time.time()
        age_limit = max_age_seconds or self.config.max_data_age_seconds
        warn_limit = self.config.stale_data_warn_seconds

        if data_timestamp is not None:
            age = now - data_timestamp
            if age > age_limit:
                findings.append(DataQualityFinding(
                    category="FRESHNESS",
                    severity="ERROR",
                    message=f"Data is {age:.0f}s old (limit: {age_limit:.0f}s)",
                    value=age,
                    threshold=age_limit,
                ))
            elif age > warn_limit:
                findings.append(DataQualityFinding(
                    category="FRESHNESS",
                    severity="WARN",
                    message=f"Data age {age:.0f}s approaching limit ({age_limit:.0f}s)",
                    value=age,
                    threshold=warn_limit,
                ))

        # Detect data gaps
        if self._last_data_timestamp is not None:
            gap = now - self._last_data_timestamp
            if gap > age_limit:
                if self._data_gap_start is None:
                    self._data_gap_start = self._last_data_timestamp
                gap_duration = now - self._data_gap_start
                findings.append(DataQualityFinding(
                    category="FRESHNESS",
                    severity="CRITICAL" if gap_duration > age_limit * 3 else "ERROR",
                    message=f"Data gap: {gap_duration:.0f}s since last data point (symbol may be stale)",
                    value=gap_duration,
                    threshold=age_limit,
                ))
            else:
                self._data_gap_start = None
        else:
            self._data_gap_start = None

        self._last_data_timestamp = now
        self._total_findings += len(findings)
        return findings

    def check_completeness(
        self,
        data: dict[str, Any],
        required_fields: list[str] | None = None,
    ) -> list[DataQualityFinding]:
        """Check data for missing fields, None values, and empty strings.

        Args:
            data: The data dictionary to check.
            required_fields: Override required fields list.

        Returns:
            List of DataQualityFindings (empty = complete data).
        """
        if not self.config.enabled:
            return []

        findings: list[DataQualityFinding] = []
        fields = required_fields or (
            self.config.expected_numeric_fields +
            self.config.expected_string_fields
        )

        missing_count = 0
        total_fields = len(fields)

        for field_name in fields:
            if field_name not in data:
                missing_count += 1
                findings.append(DataQualityFinding(
                    category="COMPLETENESS",
                    severity="WARN",
                    message=f"Missing field: {field_name}",
                ))
            elif data[field_name] is None:
                missing_count += 1
                findings.append(DataQualityFinding(
                    category="COMPLETENESS",
                    severity="WARN",
                    message=f"Field {field_name} is None",
                ))
            elif isinstance(data[field_name], str) and data[field_name].strip() == "":
                missing_count += 1
                findings.append(DataQualityFinding(
                    category="COMPLETENESS",
                    severity="INFO",
                    message=f"Field {field_name} is empty string",
                ))

        # Overall completeness assessment
        if total_fields > 0:
            missing_pct = (missing_count / total_fields) * 100.0
            if missing_pct > self.config.max_missing_pct:
                findings.append(DataQualityFinding(
                    category="COMPLETENESS",
                    severity="ERROR",
                    message=f"{missing_pct:.1f}% fields missing/empty (limit: {self.config.max_missing_pct}%)",
                    value=missing_pct,
                    threshold=self.config.max_missing_pct,
                ))

        self._total_findings += len(findings)
        return findings

    def check_schema(
        self,
        data: dict[str, Any],
        schema: dict[str, type] | None = None,
    ) -> list[DataQualityFinding]:
        """Validate data against an expected schema (field names + types).

        Args:
            data: The data dictionary to validate.
            schema: Dict of field_name -> expected_type, e.g.
                    {"last_price": float, "symbol": str, "volume": (int, float)}

        Returns:
            List of DataQualityFindings (empty = schema valid).
        """
        if not self.config.enabled:
            return []

        findings: list[DataQualityFinding] = []
        schema = schema or self._build_default_schema()

        for field_name, expected_type in schema.items():
            if field_name not in data:
                continue  # Handled by completeness check

            value = data[field_name]
            if value is None:
                continue  # Handled by completeness check

            if not isinstance(value, expected_type):
                type_name = type(value).__name__
                expected_name = self._type_to_name(expected_type)
                findings.append(DataQualityFinding(
                    category="SCHEMA",
                    severity="WARN",
                    message=f"Field {field_name}: expected {expected_name}, got {type_name} (value={value})",
                ))

            # Range validation for numeric fields
            if isinstance(value, (int, float)):
                if field_name in ("last_price", "open", "high", "low", "close", "bid", "ask"):
                    if value <= 0:
                        findings.append(DataQualityFinding(
                            category="SCHEMA",
                            severity="ERROR",
                            message=f"Field {field_name} has invalid non-positive value: {value}",
                            value=float(value),
                        ))

        self._total_findings += len(findings)
        return findings

    def health_summary(self) -> dict[str, Any]:
        """Get a summary of data quality health for reporting.

        Returns:
            Dict with quality metrics.
        """
        return {
            "total_checks": self._total_checks,
            "total_findings": self._total_findings,
            "finding_rate_pct": round(
                (self._total_findings / max(self._total_checks, 1)) * 100.0, 2
            ),
            "rolling_window_size": self.config.rolling_window_size,
            "price_window_filled": len(self._price_window),
            "volume_window_filled": len(self._volume_window),
            "spread_window_filled": len(self._spread_window),
            "last_data_age_since_reset": (
                time.time() - self._last_data_timestamp
                if self._last_data_timestamp is not None
                else None
            ),
        }

    def reset(self) -> None:
        """Reset all state (for testing or session restart)."""
        self._last_price = None
        self._last_volume = None
        self._price_window.clear()
        self._volume_window.clear()
        self._spread_window.clear()
        self._last_data_timestamp = None
        self._data_gap_start = None
        self._total_checks = 0
        self._total_findings = 0

    # ── Internal check methods ─────────────────────────────────────────────

    def _check_rule_based(
        self, price: float, volume: float, bid: float, ask: float,
    ) -> list[DataQualityFinding]:
        """Existing rule-based anomaly checks."""
        findings: list[DataQualityFinding] = []

        # Price spike
        if self._last_price is not None and self._last_price > 0:
            pct_change = abs(price - self._last_price) / self._last_price
            if pct_change > self.config.max_price_change_pct:
                findings.append(DataQualityFinding(
                    category="PRICE",
                    severity="WARN" if pct_change < self.config.max_price_change_pct * 2 else "ERROR",
                    message=f"Price spike: {pct_change*100:.2f}% change (threshold: {self.config.max_price_change_pct*100}%)",
                    value=pct_change,
                    threshold=self.config.max_price_change_pct,
                ))

        # Volume spike
        if self._last_volume is not None and self._last_volume > 0:
            vol_ratio = volume / self._last_volume
            if vol_ratio > self.config.volume_spike_mult:
                findings.append(DataQualityFinding(
                    category="VOLUME",
                    severity="WARN" if vol_ratio < self.config.volume_spike_mult * 2 else "ERROR",
                    message=f"Volume spike: {vol_ratio:.1f}x normal (threshold: {self.config.volume_spike_mult}x)",
                    value=vol_ratio,
                    threshold=self.config.volume_spike_mult,
                ))

        # Wide spread
        if bid > 0 and ask > 0:
            spread_pct = (ask - bid) / bid
            if spread_pct > self.config.max_spread_pct:
                findings.append(DataQualityFinding(
                    category="SPREAD",
                    severity="WARN" if spread_pct < self.config.max_spread_pct * 2 else "ERROR",
                    message=f"Wide spread: {spread_pct*100:.2f}% (threshold: {self.config.max_spread_pct*100}%)",
                    value=spread_pct,
                    threshold=self.config.max_spread_pct,
                ))

        return findings

    def _check_statistical(
        self, price: float, volume: float, bid: float, ask: float,
    ) -> list[DataQualityFinding]:
        """Statistical anomaly detection using z-score and IQR methods."""
        findings: list[DataQualityFinding] = []
        n = len(self._price_window)

        if n < self.config.min_data_points_for_trend:
            return findings  # Not enough data yet

        # Z-score for price
        price_z = self._zscore(price, list(self._price_window))
        if abs(price_z) > self.config.zscore_threshold:
            findings.append(DataQualityFinding(
                category="STATISTICAL",
                severity="WARN" if abs(price_z) < self.config.zscore_threshold * 1.5 else "ERROR",
                message=f"Price z-score={price_z:.2f} (threshold={self.config.zscore_threshold}) — statistical outlier",
                value=price_z,
                threshold=self.config.zscore_threshold,
            ))

        # Z-score for volume
        vol_samples = list(self._volume_window)
        if len(set(vol_samples)) > 1:  # Avoid division by zero if all same
            vol_z = self._zscore(volume, vol_samples)
            if abs(vol_z) > self.config.zscore_threshold:
                findings.append(DataQualityFinding(
                    category="STATISTICAL",
                    severity="INFO" if abs(vol_z) < self.config.zscore_threshold * 1.5 else "WARN",
                    message=f"Volume z-score={vol_z:.2f} (threshold={self.config.zscore_threshold}) — statistical outlier",
                    value=vol_z,
                    threshold=self.config.zscore_threshold,
                ))

        # IQR for spread (uses instance config value)
        spread_samples = [s for s in self._spread_window if s > 0]
        if len(spread_samples) >= self.config.min_data_points_for_trend:
            spread_val = (ask - bid) / bid if bid > 0 and ask > 0 else 0.0
            if spread_val > 0:
                is_outlier = self._iqr_outlier(spread_val, spread_samples, self.config.iqr_multiplier)
                if is_outlier:
                    sorted_s = sorted(spread_samples)
                    n = len(sorted_s)
                    q1 = statistics.median(sorted_s[:n // 2])
                    q3 = statistics.median(sorted_s[n // 2:]) if n % 2 == 0 else statistics.median(sorted_s[n // 2 + 1:])
                    iqr = q3 - q1
                    findings.append(DataQualityFinding(
                        category="STATISTICAL",
                        severity="INFO",
                        message=f"Spread IQR outlier: {spread_val*100:.3f}% (IQR={iqr*100:.3f}%)",
                        value=spread_val,
                        threshold=q3 + self.config.iqr_multiplier * iqr if iqr > 0 else 0,
                    ))

        return findings

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _build_default_schema(self) -> dict[str, type]:
        """Build a default schema from config field lists."""
        schema: dict[str, type] = {}
        for f in self.config.expected_numeric_fields:
            schema[f] = (int, float)
        for f in self.config.expected_string_fields:
            schema[f] = str
        return schema

    @staticmethod
    def _zscore(value: float, samples: list[float]) -> float:
        """Compute z-score of a value relative to a sample population."""
        if len(samples) < 2:
            return 0.0
        try:
            mean = statistics.mean(samples)
            stdev = statistics.stdev(samples)
            if stdev == 0:
                return 0.0
            return (value - mean) / stdev
        except statistics.StatisticsError:
            return 0.0

    @staticmethod
    def _iqr_outlier(value: float, samples: list[float], iqr_multiplier: float = 1.5) -> bool:
        """Check if value is an IQR outlier.

        Args:
            value: The value to check.
            samples: Population samples for IQR calculation.
            iqr_multiplier: IQR multiplier (default 1.5). Pass instance config value
                            to respect custom configuration.
        """
        if len(samples) < 4:
            return False
        sorted_s = sorted(samples)
        n = len(sorted_s)
        q1 = statistics.median(sorted_s[:n // 2])
        q3 = statistics.median(sorted_s[n // 2:]) if n % 2 == 0 else statistics.median(sorted_s[n // 2 + 1:])
        iqr = q3 - q1
        if iqr == 0:
            return False
        lower = q1 - iqr_multiplier * iqr
        upper = q3 + iqr_multiplier * iqr
        return value < lower or value > upper

    @staticmethod
    def _type_to_name(t: type | tuple) -> str:
        """Convert a type or tuple of types to a human-readable name."""
        if isinstance(t, tuple):
            return " | ".join(tp.__name__ for tp in t if tp is not None)
        return t.__name__ if t is not None else "unknown"


# ── Factory ────────────────────────────────────────────────────────────────────

def create_data_quality_monitor(config: dict | None = None) -> DataQualityMonitor:
    """Create a DataQualityMonitor from a config dict.

    Args:
        config: Config dict (can include DATA_ANOMALY_* keys for backward compat).

    Returns:
        Configured DataQualityMonitor instance.
    """
    cfg = config or {}
    return DataQualityMonitor(DataQualityConfig(
        enabled=cfg.get("DATA_ANOMALY_DETECTION_ENABLED", cfg.get("data_quality_enabled", True)),
        max_price_change_pct=cfg.get("DATA_ANOMALY_PRICE_CHANGE_MAX_PCT", cfg.get("data_quality_max_price_change_pct", 0.05)),
        volume_spike_mult=cfg.get("DATA_ANOMALY_VOLUME_SPIKE_MULT", cfg.get("data_quality_volume_spike_mult", 5.0)),
        max_spread_pct=cfg.get("DATA_ANOMALY_SPREAD_MAX_PCT", cfg.get("data_quality_max_spread_pct", 0.03)),
        zscore_threshold=float(cfg.get("data_quality_zscore_threshold", 3.0)),
        rolling_window_size=int(cfg.get("data_quality_rolling_window", 20)),
        max_data_age_seconds=float(cfg.get("data_quality_max_age_seconds", 60.0)),
        stale_data_warn_seconds=float(cfg.get("data_quality_stale_warn_seconds", 30.0)),
        max_missing_pct=float(cfg.get("data_quality_max_missing_pct", 10.0)),
        enable_trend_detection=bool(cfg.get("data_quality_enable_trend", True)),
    ))


__all__ = [
    "DataQualityConfig",
    "DataQualityFinding",
    "DataQualityMonitor",
    "create_data_quality_monitor",
]

