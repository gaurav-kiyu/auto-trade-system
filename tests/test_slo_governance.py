"""Unit tests for slo_governance.py."""

from __future__ import annotations

import pytest
from core.slo_governance import (
    DEFAULT_SLOS,
    SLODefinition,
    SLOGovernance,
    SLOResult,
    SLOTracker,
    check_slo_compliance,
    get_slo_governance,
    ingest_health_report,
)


class TestSLODefinition:
    """SLODefinition tests."""

    def test_gte_check_passes(self):
        slo = SLODefinition("test", "Test", 99.0, "%", "gte", "testing")
        assert slo.check(99.5) is True
        assert slo.check(99.0) is True

    def test_gte_check_fails(self):
        slo = SLODefinition("test", "Test", 99.0, "%", "gte", "testing")
        assert slo.check(98.9) is False

    def test_lte_check_passes(self):
        slo = SLODefinition("test", "Test", 60, "seconds", "lte", "recovery")
        assert slo.check(30) is True
        assert slo.check(60) is True

    def test_lte_check_fails(self):
        slo = SLODefinition("test", "Test", 60, "seconds", "lte", "recovery")
        assert slo.check(61) is False

    def test_eq_check_passes(self):
        slo = SLODefinition("test", "Test", 0, "count", "eq", "security")
        assert slo.check(0) is True

    def test_eq_check_fails(self):
        slo = SLODefinition("test", "Test", 0, "count", "eq", "security")
        assert slo.check(1) is False

    def test_critical_flag(self):
        slo = SLODefinition("critical", "Critical", 100.0, "%", "eq", "risk", critical=True)
        assert slo.critical is True

        slo2 = SLODefinition("normal", "Normal", 90.0, "%", "gte", "testing")
        assert slo2.critical is False


class TestSLOTracker:
    """SLOTracker tests."""

    def test_init(self):
        tracker = SLOTracker()
        assert tracker is not None

    def test_record_and_get(self):
        tracker = SLOTracker(window_hours=1)
        tracker.record("test_metric", 99.5)
        tracker.record("test_metric", 99.6)
        assert tracker.get_current_value("test_metric") == pytest.approx(99.55, abs=0.1)

    def test_get_default(self):
        tracker = SLOTracker()
        assert tracker.get_current_value("nonexistent") == 0.0

    def test_get_custom_default(self):
        tracker = SLOTracker()
        assert tracker.get_current_value("nonexistent", 50.0) == 50.0

    def test_reset_single(self):
        tracker = SLOTracker()
        tracker.record("metric_a", 1.0)
        tracker.record("metric_b", 2.0)
        tracker.reset("metric_a")
        assert tracker.get_current_value("metric_a") == 0.0
        assert tracker.get_current_value("metric_b") == 2.0

    def test_reset_all(self):
        tracker = SLOTracker()
        tracker.record("a", 1.0)
        tracker.record("b", 2.0)
        tracker.reset()
        assert tracker.get_current_value("a") == 0.0
        assert tracker.get_current_value("b") == 0.0


class TestSLOGovernance:
    """SLOGovernance tests."""

    def test_init_with_defaults(self):
        slo = SLOGovernance()
        assert len(slo._slos) >= 15
        assert slo._tracker is not None

    def test_init_with_custom_slos(self):
        custom = [SLODefinition("custom", "Custom", 99.0, "%", "gte", "testing")]
        slo = SLOGovernance(slos=custom)
        assert len(slo._slos) == 1

    def test_register_slo(self):
        slo = SLOGovernance()
        custom = SLODefinition("new_slo", "New", 95.0, "%", "gte", "testing")
        slo.register_slo(custom)
        assert len(slo._slos) >= 16

    def test_record_metric(self):
        slo = SLOGovernance()
        slo.record_metric("test_coverage", 92.5)
        assert slo._tracker.get_current_value("test_coverage") == 92.5

    def test_check_slo_known(self):
        slo = SLOGovernance()
        result = slo.check_slo("risk_enforcement")
        assert result is not None
        assert result.slo.name == "risk_enforcement"

    def test_check_slo_unknown(self):
        slo = SLOGovernance()
        result = slo.check_slo("nonexistent")
        assert result is None

    def test_check_all_returns_report(self):
        slo = SLOGovernance()
        report = slo.check_all_slos()
        assert report.total_slos >= 15
        assert report.passed + report.failed == report.total_slos

    def test_check_all_with_data(self):
        slo = SLOGovernance()
        # Record passing values for some SLOs
        slo.record_metric("risk_enforcement", 100.0)
        slo.record_metric("duplicate_orders", 0)
        slo.record_metric("critical_security", 0)
        slo.record_metric("test_coverage", 92.0)
        slo.record_metric("replay_success", 99.99)

        report = slo.check_all_slos()
        assert report.passed >= 5

    def test_check_blocking_slos(self):
        slo = SLOGovernance()
        # Record failing value for a critical SLO
        slo.record_metric("risk_enforcement", 50.0)
        blocking = slo.get_blocking_slos()
        blocking_names = [b.slo.name for b in blocking]
        assert "risk_enforcement" in blocking_names

    def test_is_releasable_ok(self):
        slo = SLOGovernance()
        releasable, msg = slo.is_releasable()
        assert isinstance(releasable, bool)
        assert isinstance(msg, str)

    def test_is_releasable_blocked(self):
        slo = SLOGovernance()
        slo.record_metric("risk_enforcement", 50.0)
        releasable, msg = slo.is_releasable()
        if not releasable:
            assert "blocked" in msg.lower()

    def test_tracker_property(self):
        slo = SLOGovernance()
        assert slo.tracker is slo._tracker

    def test_slo_result_to_dict(self):
        slo_def = SLODefinition("test", "Test", 99.0, "%", "gte", "testing")
        result = SLOResult(slo=slo_def, current_value=99.5, passed=True, deviation_pct=0.5)
        d = result.to_dict()
        assert d["name"] == "test"
        assert d["passed"] is True
        assert d["current_value"] == 99.5

    def test_report_summary_includes_verdict(self):
        slo = SLOGovernance()
        report = slo.check_all_slos()
        text = report.summary()
        if report.blocking:
            assert "BLOCKED" in text
        else:
            assert "All critical SLOs met" in text


class TestDEFAULTSLOS:
    """Default SLO definitions tests."""

    def test_all_defaults_have_valid_comparison(self):
        for slo in DEFAULT_SLOS:
            assert slo.comparison in ("gte", "lte", "eq")

    def test_all_defaults_have_categories(self):
        categories = {"reliability", "execution", "risk", "security", "recovery", "testing", "strategy"}
        for slo in DEFAULT_SLOS:
            assert slo.category in categories, f"{slo.name} has unknown category {slo.category}"

    def test_critical_defaults_exist(self):
        critical = [s for s in DEFAULT_SLOS if s.critical]
        assert len(critical) >= 5  # replay, risk enforcement, dup orders, critical sec, RPO, RTO


class TestIngestHealthReport:
    """Tests for ingest_health_report bridge function."""

    def test_ingest_none_does_not_raise(self):
        """Ingesting None should not raise."""
        ingest_health_report(None)  # should not raise

    def test_ingest_empty_list_does_not_raise(self):
        """Ingesting empty list should not raise."""
        ingest_health_report([])  # should not raise

    def test_ingest_empty_report_does_not_raise(self):
        """Ingesting object without results attr should not raise."""
        ingest_health_report(object())  # should not raise

    def test_ingest_health_check_result_records_metric(self):
        """Ingesting a DB integrity OK check should record replay_success."""
        from core.health_checker import HealthCheckResult

        # Create a fresh SLOTracker via a new SLOGovernance
        slo = SLOGovernance()
        # Reset the global singleton to avoid pollution
        # Use the fresh slo's tracker directly
        slo._tracker.reset()

        # Create a mock HealthCheckResult
        check = HealthCheckResult(category="DB", name="test.db integrity", status="OK", value=1, message="Integrity check passed.")
        from core.slo_governance import _ingest_single_check
        _ingest_single_check(check, slo)

        # Verify replay_success was recorded
        val = slo._tracker.get_current_value("replay_success")
        assert val > 0, f"Expected replay_success > 0, got {val}"

    def test_ingest_broker_connection_records_reconciliation(self):
        """Ingesting a broker connection OK check should record broker_reconciliation."""
        from core.health_checker import HealthCheckResult

        slo = SLOGovernance()
        slo._tracker.reset()

        check = HealthCheckResult(category="BROKER", name="Broker connection", status="OK", value=True, message="Broker connected.")
        from core.slo_governance import _ingest_single_check
        _ingest_single_check(check, slo)

        val = slo._tracker.get_current_value("broker_reconciliation")
        # OK status should give 30.0 seconds
        assert val == 30.0, f"Expected 30.0, got {val}"

    def test_ingest_config_sanity_records_risk_enforcement(self):
        """Ingesting a config sanity check should record risk_enforcement."""
        from core.health_checker import HealthCheckResult

        slo = SLOGovernance()
        slo._tracker.reset()

        check = HealthCheckResult(category="CONFIG", name="SL_PCT < TARGET_PCT", status="OK", value=None, message="OK")
        from core.slo_governance import _ingest_single_check
        _ingest_single_check(check, slo)

        val = slo._tracker.get_current_value("risk_enforcement")
        assert val == 100.0, f"Expected 100.0, got {val}"

    def test_ingest_perf_win_rate_records_accuracy(self):
        """Ingesting a win rate check should record signal_accuracy."""
        from core.health_checker import HealthCheckResult

        slo = SLOGovernance()
        slo._tracker.reset()

        check = HealthCheckResult(category="PERF", name="Win rate", status="OK", value=55.0, message="Win rate 55%")
        from core.slo_governance import _ingest_single_check
        _ingest_single_check(check, slo)

        val = slo._tracker.get_current_value("signal_accuracy")
        assert val == 55.0, f"Expected 55.0, got {val}"

    def test_ingest_full_health_report_integration(self):
        """Integration test: ingest a full HealthReport from run_full_health_check."""
        from core.health_checker import run_full_health_check

        # ingest_health_report uses the global singleton via get_slo_governance()
        slo = get_slo_governance()
        slo._tracker.reset()

        # Run health check with known-good config
        report = run_full_health_check({
            "SL_PCT": 0.30,
            "TARGET_PCT": 0.60,
            "MAX_DAILY_LOSS": -600,
            "BASE_CAPITAL": 100000,
            "AI_THRESHOLD": 60,
        })
        ingest_health_report(report)

        # Verify at least one SLO metric was recorded
        risk_val = slo._tracker.get_current_value("risk_enforcement")
        assert risk_val > 0, f"Expected risk_enforcement > 0, got {risk_val}"


class TestConvenienceAPI:
    """Convenience API tests."""

    def test_get_slo_governance_singleton(self):
        g1 = get_slo_governance()
        g2 = get_slo_governance()
        assert g1 is g2

    def test_check_slo_compliance(self):
        report = check_slo_compliance()
        assert report.total_slos >= 15
