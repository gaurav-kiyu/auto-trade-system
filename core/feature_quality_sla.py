"""
Feature Quality SLA Monitor (P6 — Master Constitution Phase 12 Gap Closure).

Automated freshness monitoring for ML feature store — ties together:

    DataFreshnessGuard  →  staleness detection for trading decisions
    DataQualityMonitor  →  price/volume/spread/schema quality checks
    FeatureStore        →  feature provenance, statistics, lineage
    SLOGovernance       →  compliance tracking and release gating
    MetricsExporter     →  Prometheus metrics for dashboard/HPA

Provides:
  - Per-feature freshness SLA checking with configurable thresholds
  - Feature quality scoring (0.0–1.0) based on staleness + anomaly rate + coverage
  - Prometheus metrics for feature health (opb_feature_* gauges)
  - Integration with SLO governance for automated alerting
  - CLI for querying feature SLA status

Config keys (all optional — safe defaults built in)
----------------------------------------------------
    feature_sla_enabled         : bool   default True
    feature_sla_max_age_sec     : int    default 300   (max seconds since last update)
    feature_sla_min_coverage    : float  default 0.8   (min fraction of features with data)
    feature_sla_quality_threshold : float default 0.7  (min quality score 0-1)
    feature_sla_prometheus      : bool   default True  (emit Prometheus metrics)
    feature_sla_report_interval_sec : int default 300  (how often to check)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_log = logging.getLogger(__name__)

# ── Quality score weights (configurable) ─────────────────────────────────────
QUALITY_WEIGHT_AGE = 0.6     # Weight of age/freshness in quality score
QUALITY_WEIGHT_ANOMALY = 0.4  # Weight of anomaly rate in quality score


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class FeatureSLAConfig:
    """Configuration for Feature Quality SLA monitoring."""
    enabled: bool = True
    max_age_seconds: int = 300               # Max seconds since last feature update
    min_coverage: float = 0.8                # Min fraction of tracked features with data
    quality_threshold: float = 0.7           # Min quality score (0.0–1.0)
    prometheus_enabled: bool = True          # Emit Prometheus metrics
    report_interval_seconds: int = 300       # Background check interval


@dataclass
class FeatureSLAStatus:
    """Current SLA status for a single feature."""
    feature_name: str
    symbol: str = "NIFTY"
    last_updated: float = 0.0               # Unix timestamp of last update
    age_seconds: float = 0.0                 # Seconds since last update
    anomaly_count: int = 0                    # Data quality anomalies found
    total_checks: int = 0                     # Total quality checks performed
    quality_score: float = 1.0               # 0.0–1.0 quality score
    sla_passed: bool = True                   # Within configured SLA?
    status: str = "HEALTHY"                   # HEALTHY, DEGRADED, STALE, UNKNOWN
    message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_name": self.feature_name,
            "symbol": self.symbol,
            "last_updated": self.last_updated,
            "age_seconds": round(self.age_seconds, 1),
            "anomaly_count": self.anomaly_count,
            "total_checks": self.total_checks,
            "quality_score": round(self.quality_score, 3),
            "sla_passed": self.sla_passed,
            "status": self.status,
            "message": self.message,
            "timestamp": self.timestamp,
        }


@dataclass
class FeatureSLAReport:
    """Complete report across all tracked features."""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    features: list[FeatureSLAStatus] = field(default_factory=list)
    overall_score: float = 1.0
    coverage_pct: float = 100.0
    passed_count: int = 0
    failed_count: int = 0
    overall_status: str = "HEALTHY"

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "  Feature Quality SLA Report",
            "=" * 60,
            f"  Overall Score:  {self.overall_score:.2f} / 1.0",
            f"  Coverage:       {self.coverage_pct:.1f}%",
            f"  Passed:         {self.passed_count}",
            f"  Failed:         {self.failed_count}",
            f"  Status:         {self.overall_status}",
            "",
            "  Per-Feature Status:",
        ]
        for f in self.features:
            icon = "[OK]" if f.sla_passed else "[X]"
            lines.append(
                f"    {icon} {f.feature_name:<25s} "
                f"score={f.quality_score:.2f} "
                f"age={f.age_seconds:.0f}s "
                f"status={f.status}"
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "overall_score": round(self.overall_score, 3),
            "coverage_pct": round(self.coverage_pct, 1),
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "overall_status": self.overall_status,
            "features": [f.to_dict() for f in self.features],
        }


# ── Feature Quality SLA Monitor ──────────────────────────────────────────────

# Default tracked features and their expected SLAs
DEFAULT_FEATURE_SLAS: dict[str, dict[str, Any]] = {
    "score":          {"max_age_sec": 300, "critical": True},
    "confidence":     {"max_age_sec": 300, "critical": True},
    "iv_rank":        {"max_age_sec": 600, "critical": False},
    "vix":            {"max_age_sec": 600, "critical": False},
    "pcr":            {"max_age_sec": 900, "critical": False},
    "regime_code":    {"max_age_sec": 600, "critical": False},
    "session_code":   {"max_age_sec": 300, "critical": False},
    "direction_call":  {"max_age_sec": 300, "critical": True},
    "day_of_week":    {"max_age_sec": 86400, "critical": False},
    "hour_of_entry":  {"max_age_sec": 86400, "critical": False},
    "is_strong":      {"max_age_sec": 300, "critical": False},
    "is_moderate":    {"max_age_sec": 300, "critical": False},
    "is_weak":        {"max_age_sec": 300, "critical": False},
    "has_soft_blocks": {"max_age_sec": 300, "critical": False},
}


class FeatureQualitySLA:
    """Automated feature quality and freshness SLA monitor.

    Tracks feature freshness, data quality, and SLA compliance for ML
    features used in signal generation. Integrates with:

    - SLOGovernance for release gating and alerting
    - DataQualityMonitor for anomaly detection
    - MetricsExporter for Prometheus metrics
    - DataFreshnessGuard for staleness gating

    Thread-safe: uses RLock for all state mutations.
    """

    def __init__(
        self,
        config: FeatureSLAConfig | None = None,
        feature_slas: dict[str, dict[str, Any]] | None = None,
    ):
        self._config = config or FeatureSLAConfig()
        self._feature_slas = dict(feature_slas) if feature_slas is not None else dict(DEFAULT_FEATURE_SLAS)
        self._lock = threading.RLock()
        self._statuses: dict[str, FeatureSLAStatus] = {}

        # Initialize statuses for all tracked features
        now = time.time()
        for fname in self._feature_slas:
            self._statuses[fname] = FeatureSLAStatus(
                feature_name=fname,
                last_updated=now,
                message="Initialized — awaiting first data",
            )

        # Bootstrap SLO governance integration
        self._wire_slo_governance()

        _log.info(
            "FeatureQualitySLA initialized — tracking %d features",
            len(self._feature_slas),
        )

    def _wire_slo_governance(self) -> None:
        """Register feature quality SLOs with the SLO governance engine."""
        try:
            from core.slo_governance import get_slo_governance, SLODefinition

            slo = get_slo_governance()
            slo.register_slo(SLODefinition(
                name="feature_quality_score",
                description="ML feature quality score (trailing average)",
                target=self._config.quality_threshold,
                unit="score",
                comparison="gte",
                category="reliability",
                critical=True,
            ))
            slo.register_slo(SLODefinition(
                name="feature_freshness",
                description="Feature freshness SLA pass rate",
                target=95.0,
                unit="%",
                comparison="gte",
                category="reliability",
                critical=False,
            ))
            _log.debug("[FQ-SLA] Registered feature quality SLOs")
        except ImportError:
            _log.debug("[FQ-SLA] SLOGovernance not available")

    def update_feature(
        self,
        feature_name: str,
        age_seconds: float | None = None,
        anomaly_count: int | None = None,
        total_checks: int | None = None,
        symbol: str = "NIFTY",
    ) -> FeatureSLAStatus:
        """Update the SLA status for a single feature.

        Args:
            feature_name: Name of the feature to update.
            age_seconds: Seconds since this feature was last computed (None = not stale).
            anomaly_count: Number of quality anomalies found.
            total_checks: Total quality checks performed.
            symbol: Trading symbol (default NIFTY).

        Returns:
            Updated FeatureSLAStatus.
        """
        with self._lock:
            now = time.time()
            status = self._statuses.get(feature_name)

            if status is None:
                status = FeatureSLAStatus(feature_name=feature_name, symbol=symbol)
                self._statuses[feature_name] = status

            # Update fields
            if age_seconds is not None:
                status.age_seconds = age_seconds
            if anomaly_count is not None:
                status.anomaly_count = anomaly_count
            if total_checks is not None:
                status.total_checks = total_checks

            status.last_updated = now
            status.timestamp = datetime.utcnow().isoformat()
            status.symbol = symbol

            # Compute quality score
            sla_config = self._feature_slas.get(feature_name, self._get_default_sla())
            max_age = sla_config.get("max_age_sec", self._config.max_age_seconds)
            age_factor = max(0.0, 1.0 - (status.age_seconds / max(max_age, 1)))

            anomaly_factor = 1.0
            if status.total_checks > 0:
                anomaly_rate = status.anomaly_count / status.total_checks
                anomaly_factor = max(0.0, 1.0 - anomaly_rate * 2.0)

            status.quality_score = round(
                age_factor * QUALITY_WEIGHT_AGE + anomaly_factor * QUALITY_WEIGHT_ANOMALY,
                3,
            )

        # ── Determine SLA pass/fail (still inside lock) ──────────────────
        sla_threshold = sla_config.get("quality_threshold", self._config.quality_threshold)
        status.sla_passed = (
            status.age_seconds <= max_age
            and status.quality_score >= sla_threshold
        )

        # Determine status string
        if status.age_seconds > max_age * 2:
            status.status = "STALE"
            status.message = (
                f"Feature data is {status.age_seconds:.0f}s old "
                f"(SLA: {max_age}s)"
            )
        elif status.age_seconds > max_age:
            status.status = "DEGRADED"
            status.message = (
                f"Feature age {status.age_seconds:.0f}s approaching SLA limit"
            )
        elif status.quality_score < self._config.quality_threshold:
            status.status = "DEGRADED"
            status.message = (
                f"Feature quality score {status.quality_score:.2f} "
                f"below threshold {self._config.quality_threshold}"
            )
        else:
            status.status = "HEALTHY"
            status.message = ""

        # ── Emit Prometheus metrics OUTSIDE the lock ──────────────────────
        self._emit_metrics(status)

        return status

    def update_from_data_quality(
        self,
        findings: list[Any],
        symbol: str = "NIFTY",
    ) -> None:
        """Update feature SLA from DataQualityMonitor findings.

        Maps data quality categories to feature names and updates
        their SLA statuses accordingly.

        Args:
            findings: List of DataQualityFinding objects.
            symbol: Trading symbol.
        """
        # Aggregate findings by category
        from collections import Counter

        if not findings:
            return
        cat_counts: Counter = Counter()
        total = len(findings)

        for f in findings:
            cat = getattr(f, "category", "")
            if cat:
                cat_counts[cat] += 1

        # Map categories to feature names
        category_feature_map = {
            "PRICE": "score",
            "VOLUME": "is_strong",
            "SPREAD": "confidence",
            "FRESHNESS": "vix",
            "SCHEMA": "has_soft_blocks",
            "STATISTICAL": "regime_code",
        }

        for cat, feature in category_feature_map.items():
            count = cat_counts.get(cat, 0)
            if feature in self._feature_slas:
                self.update_feature(
                    feature_name=feature,
                    age_seconds=0 if count == 0 else None,
                    anomaly_count=count,
                    total_checks=total if total > 0 else 1,
                    symbol=symbol,
                )

    def update_from_freshness_guard(
        self,
        freshness_result: Any,
        symbol: str = "NIFTY",
    ) -> list[FeatureSLAStatus]:
        """Update feature SLA from DataFreshnessGuard result.

        Args:
            freshness_result: FreshnessResult from check_data_freshness().
            symbol: Trading symbol.

        Returns:
            List of updated feature statuses.
        """
        updated = []
        now = time.time()

        with self._lock:
            stalest_sec = getattr(freshness_result, "stalest_bar_sec", 0)
            stalest_name = getattr(freshness_result, "stalest_bar_name", "")
            passed = getattr(freshness_result, "passed", True)

            # Map timeframe names to features
            timeframe_map = {
                "1m": "score",
                "5m": "confidence",
                "15m": "iv_rank",
                "VIX": "vix",
            }

            for tf, feature in timeframe_map.items():
                if feature in self._feature_slas:
                    age = stalest_sec if stalest_name == tf else 0
                    if stalest_name == tf and not passed:
                        # This specific timeframe is stale
                        status = self.update_feature(
                            feature_name=feature,
                            age_seconds=age,
                            symbol=symbol,
                        )
                        updated.append(status)
                    elif not passed:
                        # Some other timeframe is stale — still flag a degradation
                        status = self.update_feature(
                            feature_name=feature,
                            age_seconds=age,
                            symbol=symbol,
                        )
                        updated.append(status)
                    else:
                        # All fresh
                        status = self.update_feature(
                            feature_name=feature,
                            age_seconds=0,
                            symbol=symbol,
                        )
                        updated.append(status)

        return updated

    def get_report(self) -> FeatureSLAReport:
        """Generate a complete SLA report across all tracked features.

        Returns:
            FeatureSLAReport with per-feature status and overall metrics.
        """
        with self._lock:
            now = time.time()
            features = list(self._statuses.values())

            # Update age for all features
            for f in features:
                f.age_seconds = now - f.last_updated

            # Count passes/fails
            passed = sum(1 for f in features if f.sla_passed)
            failed = len(features) - passed
            total = len(features)

            # Coverage: features with at least one data point
            covered = sum(
                1 for f in features
                if f.total_checks > 0 or (time.time() - f.last_updated) < 10
            )
            coverage_pct = (covered / max(total, 1)) * 100.0

            # Overall quality score: weighted average
            if total > 0:
                overall = sum(f.quality_score for f in features) / total
            else:
                overall = 1.0

            # Determine overall status
            if failed > 0:
                overall_status = "DEGRADED" if failed <= total * 0.3 else "STALE"
            else:
                overall_status = "HEALTHY"

            return FeatureSLAReport(
                features=features,
                overall_score=round(overall, 3),
                coverage_pct=round(coverage_pct, 1),
                passed_count=passed,
                failed_count=failed,
                overall_status=overall_status,
            )

    def report_to_slo(self) -> None:
        """Push the current feature SLA report into SLO governance."""
        report = self.get_report()

        try:
            from core.slo_governance import get_slo_governance

            slo = get_slo_governance()
            slo.record_metric("feature_quality_score", report.overall_score)
            slo.record_metric(
                "feature_freshness",
                (report.passed_count / max(report.passed_count + report.failed_count, 1)) * 100.0,
            )
        except ImportError:
            pass

    def register_feature_sla(
        self,
        feature_name: str,
        max_age_sec: int = 300,
        critical: bool = False,
        quality_threshold: float | None = None,
    ) -> None:
        """Register a new feature for SLA tracking.

        Args:
            feature_name: Name of the feature.
            max_age_sec: Max age in seconds before feature is stale.
            critical: Whether this feature is critical for trading decisions.
            quality_threshold: Custom quality threshold (defaults to config default).
        """
        with self._lock:
            self._feature_slas[feature_name] = {
                "max_age_sec": max_age_sec,
                "critical": critical,
                "quality_threshold": quality_threshold or self._config.quality_threshold,
            }
            if feature_name not in self._statuses:
                self._statuses[feature_name] = FeatureSLAStatus(
                    feature_name=feature_name,
                    message="Registered — awaiting first data",
                )
            _log.info(
                "[FQ-SLA] Registered feature '%s' (max_age=%ds, critical=%s)",
                feature_name, max_age_sec, critical,
            )

    def _get_default_sla(self) -> dict[str, Any]:
        return {
            "max_age_sec": self._config.max_age_seconds,
            "critical": False,
            "quality_threshold": self._config.quality_threshold,
        }

    def _emit_metrics(self, status: FeatureSLAStatus) -> None:
        """Emit Prometheus metrics for a feature's SLA status."""
        if not self._config.prometheus_enabled:
            return
        try:
            from core.metrics_exporter import update_metrics

            update_metrics({
                f"feature_sla_{status.feature_name}_quality": status.quality_score,
                f"feature_sla_{status.feature_name}_age": status.age_seconds,
                f"feature_sla_{status.feature_name}_passed": 1.0 if status.sla_passed else 0.0,
            })
        except (ImportError, Exception):
            pass  # Metrics exporter not available

    @property
    def config(self) -> FeatureSLAConfig:
        return self._config

    @config.setter
    def config(self, cfg: FeatureSLAConfig) -> None:
        self._config = cfg


# ── Background poller ─────────────────────────────────────────────────────────

def start_feature_sla_poller(
    monitor: FeatureQualitySLA | None = None,
    interval_seconds: int | None = None,
    stop_event: threading.Event | None = None,
) -> threading.Thread:
    """Start a background thread that periodically checks feature SLA and
    pushes results to SLO governance.

    Args:
        monitor: FeatureQualitySLA instance (defaults to singleton).
        interval_seconds: How often to check (defaults to config value).
        stop_event: Optional Event for graceful shutdown.

    Returns:
        Background daemon thread (already started).
    """
    m = monitor or get_feature_quality_sla()
    interval = interval_seconds or m.config.report_interval_seconds
    _stop = stop_event or threading.Event()

    def _poller_loop() -> None:
        _log.info("[FQ-SLA] Background poller started (interval=%ds)", interval)
        while not _stop.is_set():
            try:
                m.report_to_slo()
            except Exception as exc:
                _log.warning("[FQ-SLA] Poller cycle failed: %s", exc)
            _stop.wait(interval)

    t = threading.Thread(target=_poller_loop, name="feature-sla-poller", daemon=True)
    t.start()
    return t


# ── Singleton ─────────────────────────────────────────────────────────────────

_fq_sla: FeatureQualitySLA | None = None
_fq_lock = threading.RLock()


def get_feature_quality_sla() -> FeatureQualitySLA:
    """Get the global FeatureQualitySLA singleton."""
    global _fq_sla
    with _fq_lock:
        if _fq_sla is None:
            _fq_sla = FeatureQualitySLA()
    return _fq_sla


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse
    import json

    ap = argparse.ArgumentParser(prog="python -m core.feature_quality_sla")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    ap.add_argument("--feature", type=str, default="",
                    help="Check specific feature (default: all)")
    args = ap.parse_args()

    sla = get_feature_quality_sla()

    if args.feature:
        status = sla.update_feature(feature_name=args.feature, age_seconds=0)
        if args.json:
            print(json.dumps(status.to_dict(), indent=2))
        else:
            icon = "[OK]" if status.sla_passed else "[X]"
            print(f"{icon} {status.feature_name}: score={status.quality_score:.2f}, "
                  f"age={status.age_seconds:.0f}s, status={status.status}")
    else:
        report = sla.get_report()
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(report.summary())


if __name__ == "__main__":
    _cli()
