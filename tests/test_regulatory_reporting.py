"""Unit tests for regulatory_reporting.py."""

from __future__ import annotations

import tempfile
from pathlib import Path

from core.regulatory_reporting import (
    CompliancePackage,
    ComplianceReport,
    RegulatoryReporter,
    TradeRegisterEntry,
)


class TestTradeRegisterEntry:
    """TradeRegisterEntry dataclass tests."""

    def test_basic_creation(self):
        entry = TradeRegisterEntry(
            trade_id="T1", symbol="NIFTY", entry_time="2026-01-01 09:30:00",
            exit_time=None, direction="CALL", entry_price=100.0,
            exit_price=None, quantity=50, net_pnl=None,
            exit_reason=None, mode="PAPER",
        )
        assert entry.trade_id == "T1"
        assert entry.symbol == "NIFTY"
        assert entry.mode == "PAPER"

    def test_to_dict(self):
        entry = TradeRegisterEntry(
            trade_id="T1", symbol="NIFTY", entry_time="2026-01-01",
            exit_time="2026-01-01 15:00", direction="CALL",
            entry_price=100.0, exit_price=150.0, quantity=50,
            net_pnl=2500.0, exit_reason="TARGET", mode="PAPER",
        )
        d = entry.to_dict()
        assert d["trade_id"] == "T1"
        assert d["net_pnl"] == 2500.0
        assert d["exit_reason"] == "TARGET"


class TestComplianceReport:
    """ComplianceReport dataclass tests."""

    def test_defaults(self):
        report = ComplianceReport(report_type="TRADE_REGISTER")
        assert report.report_type == "TRADE_REGISTER"
        assert report.warnings == []

    def test_to_dict_structure(self):
        report = ComplianceReport(
            report_type="TRADE_REGISTER",
            trader_id="OPB-001",
            entries=[{"trade_id": "T1"}],
            summary={"total_trades": 1},
        )
        d = report.to_dict()
        assert d["report_type"] == "TRADE_REGISTER"
        assert d["entries_count"] == 1

    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = ComplianceReport(
                report_type="TEST_REPORT",
                entries=[{"test": "data"}],
            )
            path = report.save(tmpdir)
            assert Path(path).exists()
            content = Path(path).read_text(encoding="utf-8")
            assert "TEST_REPORT" in content


class TestRegulatoryReporter:
    """RegulatoryReporter tests."""

    def test_init_defaults(self):
        reporter = RegulatoryReporter()
        assert reporter._trader_id == "OPB-INDEX-001"
        assert reporter._report_days == 90

    def test_init_with_custom_cfg(self):
        reporter = RegulatoryReporter({
            "regulatory_trader_id": "CUSTOM-001",
            "regulatory_report_days": 30,
        })
        assert reporter._trader_id == "CUSTOM-001"
        assert reporter._report_days == 30

    def test_generate_trade_register_no_db(self):
        reporter = RegulatoryReporter()
        report = reporter.generate_trade_register(db_path="nonexistent.db")
        assert report.summary.get("status") == "NO_DATA"
        assert len(report.warnings) >= 1

    def test_generate_risk_limits_report(self):
        reporter = RegulatoryReporter({"MAX_DAILY_LOSS": -5000, "MAX_DRAWDOWN": 0.15})
        report = reporter.generate_risk_limits_report()
        assert report.report_type == "RISK_LIMITS"
        assert len(report.entries) >= 3

    def test_risk_limits_contains_max_daily_loss(self):
        reporter = RegulatoryReporter()
        report = reporter.generate_risk_limits_report()
        limits = [e["limit"] for e in report.entries]
        assert "MAX_DAILY_LOSS" in limits

    def test_generate_broker_reconciliation_report(self):
        reporter = RegulatoryReporter()
        report = reporter.generate_broker_reconciliation_report(db_path="nonexistent.db")
        assert report.report_type == "BROKER_RECONCILIATION"

    def test_generate_system_health_report(self):
        reporter = RegulatoryReporter()
        report = reporter.generate_system_health_report()
        assert report.report_type == "SYSTEM_HEALTH"
        assert len(report.entries) >= 3  # cert gate, SLO, version, hard halt

    def test_system_health_includes_hard_halt(self):
        reporter = RegulatoryReporter()
        report = reporter.generate_system_health_report()
        checks = [e["check"] for e in report.entries]
        assert "hard_halt" in checks

    def test_system_health_includes_certification_gate(self):
        reporter = RegulatoryReporter()
        report = reporter.generate_system_health_report()
        checks = [e["check"] for e in report.entries]
        assert "certification_gate" in checks

    def test_generate_compliance_package(self):
        reporter = RegulatoryReporter()
        package = reporter.generate_compliance_package(db_path="nonexistent.db")
        assert package.trade_register is not None
        assert package.risk_limits_report is not None
        assert package.broker_recon_report is not None
        assert package.system_health_report is not None

    def test_compliance_package_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = RegulatoryReporter()
            package = reporter.generate_compliance_package(db_path="nonexistent.db")
            paths = package.save_to(tmpdir)
            assert len(paths) >= 1
            for path in paths.values():
                assert Path(path).exists()


class TestCompliancePackage:
    """CompliancePackage tests."""

    def test_defaults(self):
        pkg = CompliancePackage(trader_id="T1", broker_name="PAPER", report_period="90D")
        assert pkg.trader_id == "T1"
        assert pkg.trade_register is None

    def test_save_to_no_reports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = CompliancePackage(trader_id="T1", broker_name="PAPER", report_period="90D")
            paths = pkg.save_to(tmpdir)
            assert paths == {}
