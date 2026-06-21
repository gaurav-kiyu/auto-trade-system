"""Unit tests for risk_dashboard.py."""

from __future__ import annotations

import pytest

from core.risk_dashboard import (
    RiskAlert,
    RiskDashboard,
    RiskMetric,
    RiskProbe,
    RiskSnapshot,
    get_risk_dashboard,
    get_risk_snapshot,
)


class TestRiskMetric:
    """RiskMetric dataclass tests."""

    def test_basic_creation(self):
        m = RiskMetric(name="exposure", current_value=50000.0,
                      limit_value=100000.0, unit="Rs", status="OK",
                      category="position_risk")
        assert m.name == "exposure"
        assert m.utilization_pct == 50.0

    def test_utilization_zero_limit(self):
        m = RiskMetric(name="test", current_value=100.0, limit_value=0.0)
        assert m.utilization_pct == 0.0

    def test_utilization_at_limit(self):
        m = RiskMetric(name="test", current_value=100.0, limit_value=100.0)
        assert m.utilization_pct == 100.0

    def test_utilization_capped(self):
        m = RiskMetric(name="test", current_value=200.0, limit_value=100.0)
        assert m.utilization_pct <= 100.0

    def test_to_dict(self):
        m = RiskMetric(name="exposure", current_value=50000.0,
                      limit_value=100000.0, status="WARN")
        d = m.to_dict()
        assert d["name"] == "exposure"
        assert d["utilization_pct"] == 50.0
        assert d["status"] == "WARN"


class TestRiskAlert:
    """RiskAlert dataclass tests."""

    def test_basic_creation(self):
        a = RiskAlert(level="CRITICAL", source="safety_state",
                     message="Hard halt active")
        assert a.level == "CRITICAL"
        assert a.acknowledged is False

    def test_to_dict(self):
        a = RiskAlert(level="WARN", source="test", message="Warning")
        d = a.to_dict()
        assert d["level"] == "WARN"
        assert d["acknowledged"] is False


class TestRiskSnapshot:
    """RiskSnapshot dataclass tests."""

    def test_defaults(self):
        snap = RiskSnapshot()
        assert snap.overall_status == "OK"
        assert snap.metrics == []
        assert snap.alerts == []

    def test_summary_text(self):
        snap = RiskSnapshot(
            metrics=[RiskMetric(name="test", current_value=50.0, limit_value=100.0, status="OK")],
            n_ok=1,
        )
        text = snap.summary()
        assert "Risk Dashboard" in text
        assert "test" in text

    def test_to_dict(self):
        snap = RiskSnapshot(n_ok=1, n_warn=1, overall_status="WARN")
        d = snap.to_dict()
        assert d["overall_status"] == "WARN"
        assert d["n_ok"] == 1


class TestRiskProbe:
    """RiskProbe tests."""

    def test_init(self):
        probe = RiskProbe()
        assert probe._cfg == {}

    def test_init_with_config(self):
        probe = RiskProbe({"MAX_EXPOSURE": 50000})
        assert probe._cfg["MAX_EXPOSURE"] == 50000

    def test_collect_metrics_returns_list(self):
        probe = RiskProbe()
        metrics = probe.collect_metrics()
        assert isinstance(metrics, list)
        # At minimum capital metrics are always added
        assert len(metrics) >= 2

    def test_collect_metrics_includes_capital(self):
        probe = RiskProbe({"TOTAL_CAPITAL": 100000})
        metrics = probe.collect_metrics()
        names = [m.name for m in metrics]
        assert "capital_utilization" in names
        assert "max_risk_per_trade" in names

    def test_collect_alerts_returns_list(self):
        probe = RiskProbe()
        alerts = probe.collect_alerts()
        assert isinstance(alerts, list)


class TestRiskDashboard:
    """RiskDashboard tests."""

    def test_init(self):
        dash = RiskDashboard()
        assert dash._probe is not None

    def test_get_snapshot(self):
        dash = RiskDashboard()
        snap = dash.get_snapshot()
        assert isinstance(snap, RiskSnapshot)
        assert snap.overall_status in ("OK", "WARN", "CRITICAL")

    def test_get_snapshot_has_metrics(self):
        dash = RiskDashboard()
        snap = dash.get_snapshot()
        assert len(snap.metrics) >= 2

    def test_add_alert(self):
        dash = RiskDashboard()
        alert = RiskAlert(level="WARN", source="test", message="Test alert")
        dash.add_alert(alert)
        alerts = dash.get_alerts()
        assert len(alerts) >= 1
        assert alerts[-1].message == "Test alert"

    def test_acknowledge_alert(self):
        dash = RiskDashboard()
        alert = RiskAlert(level="INFO", source="test", message="Info")
        dash.add_alert(alert)
        assert dash.acknowledge_alert(0) is True
        assert dash.get_alerts()[0].acknowledged is True

    def test_acknowledge_invalid_index(self):
        dash = RiskDashboard()
        assert dash.acknowledge_alert(999) is False

    def test_get_unacknowledged(self):
        dash = RiskDashboard()
        dash.add_alert(RiskAlert(level="INFO", source="test", message="Unacked"))
        alerts = dash.get_alerts(unacknowledged_only=True)
        assert len(alerts) >= 1
        assert all(not a.acknowledged for a in alerts)

    def test_singleton(self):
        d1 = get_risk_dashboard()
        d2 = get_risk_dashboard()
        assert d1 is d2

    def test_get_risk_snapshot(self):
        snap = get_risk_snapshot()
        assert isinstance(snap, RiskSnapshot)
