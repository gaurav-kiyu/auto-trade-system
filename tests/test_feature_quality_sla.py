"""
Tests for core.feature_quality_sla module (P6 gap closure).

Tests cover:
  - Feature status update and SLA computation
  - Report generation and aggregation
  - Integration with DataQualityMonitor findings
  - Integration with DataFreshnessGuard results
  - SLO governance integration
  - Configuration overrides
  - Background poller lifecycle
  - Prometheus metrics emission
  - Registration of new features
  - Edge cases: empty state, zero checks, stale data, degraded quality
"""

from __future__ import annotations

import time
import threading
from unittest.mock import MagicMock, patch

import pytest

from core.feature_quality_sla import (
    FeatureQualitySLA,
    FeatureSLAConfig,
    FeatureSLAReport,
    FeatureSLAStatus,
    get_feature_quality_sla,
    start_feature_sla_poller,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sla_config() -> FeatureSLAConfig:
    return FeatureSLAConfig(
        enabled=True,
        max_age_seconds=300,
        min_coverage=0.8,
        quality_threshold=0.7,
        prometheus_enabled=False,  # Disable Prom metrics in tests
        report_interval_seconds=3600,
    )


@pytest.fixture
def sla(sla_config: FeatureSLAConfig) -> FeatureQualitySLA:
    """Create a fresh FeatureQualitySLA for each test (no SLO wiring)."""
    with patch.object(FeatureQualitySLA, "_wire_slo_governance", return_value=None):
        return FeatureQualitySLA(config=sla_config)


# ── Basic Status Updates ─────────────────────────────────────────────────────

class TestFeatureStatusUpdate:
    def test_initial_state(self, sla: FeatureQualitySLA):
        """All features start HEALTHY with no data."""
        report = sla.get_report()
        assert report.passed_count == len(report.features)
        assert report.overall_status == "HEALTHY"
        assert report.overall_score >= 0.9

    def test_update_feature_healthy(self, sla: FeatureQualitySLA):
        """Updating a feature with fresh data marks it HEALTHY."""
        status = sla.update_feature("score", age_seconds=0, total_checks=10)
        assert status.status == "HEALTHY"
        assert status.sla_passed is True
        assert status.quality_score >= 0.7

    def test_update_feature_stale(self, sla: FeatureQualitySLA):
        """Updating a feature with old age marks it STALE."""
        status = sla.update_feature("score", age_seconds=1000, total_checks=10)
        assert status.status == "STALE"
        assert status.sla_passed is False
        assert "1000s old" in status.message
        assert "SLA: 300s" in status.message

    def test_update_feature_degraded_age(self, sla: FeatureQualitySLA):
        """Feature approaching age limit marks DEGRADED."""
        max_age = sla.config.max_age_seconds
        status = sla.update_feature("score", age_seconds=max_age + 10, total_checks=10)
        assert status.status == "DEGRADED"

    def test_update_feature_degraded_quality(self, sla: FeatureQualitySLA):
        """Feature with low quality score marks DEGRADED."""
        status = sla.update_feature(
            "score", age_seconds=0, anomaly_count=50, total_checks=50
        )
        assert status.status == "DEGRADED"
        assert status.quality_score < 0.7

    def test_update_unknown_feature_creates_it(self, sla: FeatureQualitySLA):
        """Updating a feature not in defaults creates and tracks it."""
        status = sla.update_feature("custom_feature", age_seconds=10, total_checks=5)
        assert status.feature_name == "custom_feature"
        assert status.sla_passed is True
        report = sla.get_report()
        feature_names = [f.feature_name for f in report.features]
        assert "custom_feature" in feature_names

    def test_update_with_symbol(self, sla: FeatureQualitySLA):
        """Symbol is correctly associated with feature status."""
        status = sla.update_feature("score", age_seconds=0, symbol="BANKNIFTY")
        assert status.symbol == "BANKNIFTY"


# ── Report Generation ────────────────────────────────────────────────────────

class TestReportGeneration:
    def test_report_all_healthy(self, sla: FeatureQualitySLA):
        """Report shows all features passing."""
        report = sla.get_report()
        assert report.overall_status == "HEALTHY"
        assert report.failed_count == 0
        assert report.passed_count == len(sla._feature_slas)

    def test_report_some_failed(self, sla: FeatureQualitySLA):
        """Report accurately counts failures."""
        sla.update_feature("score", age_seconds=1000, total_checks=10)
        sla.update_feature("confidence", age_seconds=2000, total_checks=10)
        report = sla.get_report()
        assert report.failed_count >= 2
        assert report.overall_status in ("DEGRADED", "STALE")

    def test_report_coverage(self, sla: FeatureQualitySLA):
        """Coverage reflects features with data points."""
        # Freshly initialized — no data yet
        report = sla.get_report()
        assert report.coverage_pct >= 0  # Features initialized as healthy

        # After updating one feature
        sla.update_feature("score", age_seconds=0, total_checks=10)
        report = sla.get_report()
        assert report.coverage_pct > 0

    def test_report_to_dict(self, sla: FeatureQualitySLA):
        """Report serializes to dict correctly."""
        report = sla.get_report()
        d = report.to_dict()
        assert "overall_score" in d
        assert "passed_count" in d
        assert "failed_count" in d
        assert "features" in d
        assert isinstance(d["features"], list)

    def test_status_to_dict(self, sla: FeatureQualitySLA):
        """Individual status serializes to dict correctly."""
        status = sla.update_feature("score", age_seconds=0)
        d = status.to_dict()
        assert d["feature_name"] == "score"
        assert "quality_score" in d
        assert "age_seconds" in d
        assert "sla_passed" in d

    def test_report_summary_format(self, sla: FeatureQualitySLA):
        """Summary text is well-formed."""
        report = sla.get_report()
        summary = report.summary()
        assert "Feature Quality SLA Report" in summary
        assert "Overall Score" in summary
        assert "Passed" in summary
        assert "Failed" in summary


# ── DataQualityMonitor Integration ───────────────────────────────────────────

class TestDataQualityIntegration:
    def test_update_from_findings_empty(self, sla: FeatureQualitySLA):
        """Empty findings list doesn't degrade features."""
        sla.update_from_data_quality([])
        report = sla.get_report()
        assert report.overall_status == "HEALTHY"

    def test_update_from_findings_with_anomalies(self, sla: FeatureQualitySLA):
        """Anomaly findings degrade related features."""
        from core.data_quality_monitor import DataQualityFinding

        findings = [
            DataQualityFinding(category="PRICE", severity="ERROR", message="Price spike"),
            DataQualityFinding(category="VOLUME", severity="WARN", message="Volume spike"),
            DataQualityFinding(category="SCHEMA", severity="ERROR", message="Missing field"),
        ]
        sla.update_from_data_quality(findings)
        report = sla.get_report()

        # The score feature should have anomalies recorded
        score_status = None
        for f in report.features:
            if f.feature_name == "score":
                score_status = f
                break
        assert score_status is not None
        assert score_status.anomaly_count >= 1

    def test_update_from_findings_with_anomaly_counts(self, sla: FeatureQualitySLA):
        """Multiple anomalies on same feature degrade quality score."""
        from core.data_quality_monitor import DataQualityFinding

        findings = [
            DataQualityFinding(category="PRICE", severity="ERROR", message="Spike 1"),
            DataQualityFinding(category="PRICE", severity="ERROR", message="Spike 2"),
            DataQualityFinding(category="PRICE", severity="ERROR", message="Spike 3"),
        ]
        sla.update_from_data_quality(findings)
        report = sla.get_report()

        score_status = None
        for f in report.features:
            if f.feature_name == "score":
                score_status = f
                break
        assert score_status is not None
        assert score_status.anomaly_count >= 3


# ── FreshnessGuard Integration ────────────────────────────────────────────────

class TestFreshnessGuardIntegration:
    def test_update_from_freshness_healthy(self, sla: FeatureQualitySLA):
        """Fresh data doesn't degrade features."""
        from core.data_freshness_guard import FreshnessResult

        result = FreshnessResult(passed=True, stalest_bar_sec=5, stalest_bar_name="1m")
        updated = sla.update_from_freshness_guard(result)
        assert len(updated) > 0
        for status in updated:
            assert status.sla_passed is True

    def test_update_from_freshness_stale(self, sla: FeatureQualitySLA):
        """Stale freshness result degrades related features."""
        from core.data_freshness_guard import FreshnessResult

        result = FreshnessResult(
            passed=False, stalest_bar_sec=500,
            stalest_bar_name="1m",
            reject_reason="1m bar age 500s exceeds 90s limit",
        )
        updated = sla.update_from_freshness_guard(result)
        assert len(updated) > 0

    def test_update_from_freshness_vix_stale(self, sla: FeatureQualitySLA):
        """Stale VIX data degrades the vix feature."""
        from core.data_freshness_guard import FreshnessResult

        result = FreshnessResult(
            passed=False, stalest_bar_sec=600,
            stalest_bar_name="VIX",
            reject_reason="VIX age exceeds limit",
        )
        updated = sla.update_from_freshness_guard(result)
        vix_updated = [s for s in updated if s.feature_name == "vix"]
        assert len(vix_updated) > 0


# ── SLO Governance Integration ───────────────────────────────────────────────

class TestSLOGovernanceIntegration:
    def test_report_to_slo(self, sla: FeatureQualitySLA):
        """Report pushes metrics to SLO governance without error."""
        # Should not raise
        sla.report_to_slo()

    def test_slo_wiring(self):
        """Constructor wires SLOs via _wire_slo_governance.

        Sets up the SLO mock before __init__ so the lazy import inside
        _wire_slo_governance picks up the patched get_slo_governance.
        """
        with patch("core.slo_governance.get_slo_governance") as mock_getter:
            mock_instance = MagicMock()
            mock_getter.return_value = mock_instance
            # __init__ calls the real _wire_slo_governance which does a
            # lazy import: from core.slo_governance import get_slo_governance.
            # The patch on core.slo_governance.get_slo_governance makes that
            # import return our mock.
            sla_instance = FeatureQualitySLA()
            assert mock_instance.register_slo.called


# ── Feature Registration ─────────────────────────────────────────────────────

class TestFeatureRegistration:
    def test_register_new_feature(self, sla: FeatureQualitySLA):
        """New features can be registered dynamically."""
        initial_count = len(sla._feature_slas)
        sla.register_feature_sla("new_feature", max_age_sec=600, critical=False)
        assert len(sla._feature_slas) == initial_count + 1
        assert "new_feature" in sla._feature_slas

    def test_register_critical_feature(self, sla: FeatureQualitySLA):
        """Critical features are flagged correctly."""
        sla.register_feature_sla("critical_feature", max_age_sec=60, critical=True)
        assert sla._feature_slas["critical_feature"]["critical"] is True

    def test_register_creates_status(self, sla: FeatureQualitySLA):
        """Registering a feature creates an initial status entry."""
        sla.register_feature_sla("custom_feat")
        report = sla.get_report()
        names = [f.feature_name for f in report.features]
        assert "custom_feat" in names


# ── Background Poller ────────────────────────────────────────────────────────

class TestBackgroundPoller:
    def test_poller_starts_and_stops(self, sla: FeatureQualitySLA):
        """Poller thread starts and can be stopped."""
        stop = threading.Event()
        t = start_feature_sla_poller(sla, interval_seconds=60, stop_event=stop)
        assert t.is_alive()
        assert t.daemon is True
        assert t.name == "feature-sla-poller"
        stop.set()
        t.join(timeout=5)
        assert not t.is_alive()

    def test_poller_calls_report_to_slo(self, sla: FeatureQualitySLA):
        """Poller calls report_to_slo on each cycle."""
        stop = threading.Event()
        with patch.object(sla, "report_to_slo") as mock_report:
            t = start_feature_sla_poller(sla, interval_seconds=0.01, stop_event=stop)
            time.sleep(0.05)
            stop.set()
            t.join(timeout=5)
            assert mock_report.called


# ── Configuration ────────────────────────────────────────────────────────────

class TestConfiguration:
    def test_custom_max_age(self, sla: FeatureQualitySLA):
        """Custom max age affects SLA computation.

        Note: Per-feature max_age_sec in DEFAULT_FEATURE_SLAS takes
        precedence over the global config. This test updates the per-feature
        config to verify the SLA logic works.
        """
        sla._feature_slas["score"] = {"max_age_sec": 10, "critical": True}
        status = sla.update_feature("score", age_seconds=15, total_checks=10)
        assert status.sla_passed is False

    def test_custom_quality_threshold(self, sla: FeatureQualitySLA):
        """Custom quality threshold affects SLA pass/fail."""
        sla.config.quality_threshold = 0.9
        # Score of 1.0 with fresh data should still pass
        status = sla.update_feature("score", age_seconds=0, total_checks=10)
        assert status.sla_passed is True

    def test_disabled(self, sla: FeatureQualitySLA):
        """Disabling SLA tracking doesn't crash."""
        sla.config.enabled = False
        # Should not raise
        report = sla.get_report()
        assert report is not None


# ── Edge Cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_feature_slas(self):
        """Empty feature SLA dict doesn't crash."""
        with patch.object(FeatureQualitySLA, "_wire_slo_governance", return_value=None):
            custom = FeatureQualitySLA(feature_slas={})
            report = custom.get_report()
            assert report.passed_count == 0
            assert report.overall_score == 1.0

    def test_zero_checks(self, sla: FeatureQualitySLA):
        """Zero total checks doesn't cause division errors."""
        status = sla.update_feature("score", age_seconds=0, anomaly_count=0, total_checks=0)
        assert status.quality_score >= 0.9

    def test_extreme_values(self, sla: FeatureQualitySLA):
        """Extreme age values don't cause crashes."""
        status = sla.update_feature("score", age_seconds=1e9, total_checks=1)
        assert status.status == "STALE"
        assert status.sla_passed is False

    def test_negative_age(self, sla: FeatureQualitySLA):
        """Negative age (clock skew) doesn't cause crashes."""
        status = sla.update_feature("score", age_seconds=-100, total_checks=1)
        assert status.sla_passed is True  # Very fresh!

    def test_singleton(self):
        """Singleton returns the same instance.

        Note: Uses the global singleton (not the fixture) since
        singleton identity is a module-level invariant.
        """
        # Reset for test isolation
        import core.feature_quality_sla as fqs
        fqs._fq_sla = None
        with patch.object(FeatureQualitySLA, "_wire_slo_governance", return_value=None):
            a = get_feature_quality_sla()
            b = get_feature_quality_sla()
            assert a is b

    def test_thread_safety(self, sla: FeatureQualitySLA):
        """Concurrent updates don't corrupt state."""
        errors = []

        def update_thread(name: str):
            try:
                for _ in range(50):
                    sla.update_feature(name, age_seconds=10, total_checks=5)
            except Exception as e:
                errors.append(e)

        threads = []
        for name in ["score", "confidence", "iv_rank", "vix"]:
            t = threading.Thread(target=update_thread, args=(name,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Thread safety errors: {errors}"
        report = sla.get_report()
        assert report.passed_count >= 0
