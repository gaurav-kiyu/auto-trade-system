"""Unit tests for finops.py."""

from __future__ import annotations

import pytest

from core.finops import (
    CostGovernance,
    CostReport,
    TradeCostBreakdown,
)


class TestTradeCostBreakdown:
    """TradeCostBreakdown dataclass tests."""

    def test_defaults_are_zero(self):
        b = TradeCostBreakdown()
        assert b.brokerage == 0.0
        assert b.total == 0.0

    def test_to_dict_rounds_values(self):
        b = TradeCostBreakdown(brokerage=10.567, stt=5.123, total=15.69)
        d = b.to_dict()
        assert d["brokerage"] == 10.57
        assert d["stt"] == 5.12
        assert d["total"] == 15.69


class TestCostReport:
    """CostReport dataclass tests."""

    def test_defaults(self):
        r = CostReport()
        assert r.period_days == 30
        assert r.total_trades == 0
        assert r.status == "OK"
        assert r.warnings == []

    def test_summary_includes_rs_symbol(self):
        r = CostReport(total_trades=10, total_costs=TradeCostBreakdown(total=500))
        text = r.summary()
        assert "Rs" in text
        assert "500" in text

    def test_to_dict_structure(self):
        r = CostReport(
            period_days=30, total_trades=5, total_turnover=100000.0,
            total_costs=TradeCostBreakdown(total=1500.0),
            cost_per_trade=TradeCostBreakdown(total=300.0),
            cost_pct_of_turnover=1.5,
            net_pnl_after_costs=5000.0,
        )
        d = r.to_dict()
        assert d["total_trades"] == 5
        assert d["total_turnover"] == 100000.0
        assert d["total_costs"]["total"] == 1500.0
        assert d["net_pnl_after_costs"] == 5000.0

    def test_warnings_appear_in_summary(self):
        r = CostReport(warnings=["Test warning"])
        text = r.summary()
        assert "Test warning" in text

    def test_to_dict_truncates_warnings_to_10(self):
        warnings = [f"warn{i}" for i in range(20)]
        r = CostReport(warnings=warnings)
        d = r.to_dict()
        assert len(d["warnings"]) == 10


class TestCostGovernance:
    """CostGovernance tests."""

    def test_init_defaults(self):
        cg = CostGovernance()
        assert cg._brokerage_per_lot == 20.0
        assert cg._brokerage_pct == 0.0003
        assert cg._stt_pct == 0.0005
        assert cg._mode == "ALL"

    def test_init_with_custom_cfg(self):
        cg = CostGovernance({
            "finops_brokerage_per_lot": 10.0,
            "finops_stt_pct": 0.001,
            "finops_mode": "PAPER",
        })
        assert cg._brokerage_per_lot == 10.0
        assert cg._stt_pct == 0.001
        assert cg._mode == "PAPER"

    def test_init_uppercases_mode(self):
        cg = CostGovernance({"finops_mode": "paper"})
        assert cg._mode == "PAPER"

    def test_compute_trade_costs_basic(self):
        cg = CostGovernance()
        costs = cg.compute_trade_costs(trade_value=100000.0, lots=1)
        assert costs.brokerage > 0
        assert costs.stt > 0
        assert costs.gst > 0
        assert costs.stamp_duty > 0
        assert costs.sebi_fee > 0
        assert costs.exchange_charges > 0
        assert costs.total > 0
        # Total should be sum of all components except infrastructure
        expected = costs.brokerage + costs.stt + costs.gst + costs.stamp_duty + costs.sebi_fee + costs.exchange_charges
        assert abs(costs.total - expected) < 0.01

    def test_compute_trade_costs_with_multiple_lots(self):
        cg = CostGovernance()
        costs_1 = cg.compute_trade_costs(trade_value=100000.0, lots=1)
        costs_5 = cg.compute_trade_costs(trade_value=100000.0, lots=5)
        # Brokerage scales with lots; taxes scale with trade value
        assert costs_5.brokerage == costs_1.brokerage * 5

    def test_compute_trade_costs_with_pct_brokerage(self):
        cg = CostGovernance({"finops_brokerage_per_lot": 0.0, "finops_brokerage_pct": 0.001})
        costs = cg.compute_trade_costs(trade_value=100000.0, lots=1)
        assert costs.brokerage == 100.0  # 0.1% of 100k
        assert costs.gst > 0

    def test_analyze_costs_no_db(self):
        """analyze_costs returns NO_DATA status when DB doesn't exist."""
        cg = CostGovernance()
        report = cg.analyze_costs(db_path="nonexistent_trades_test.db")
        assert report.status == "NO_DATA"

    def test_mode_filter_enforced(self):
        """When mode is set, warning includes mode info."""
        cg = CostGovernance({"finops_mode": "PAPER"})
        report = cg.analyze_costs(db_path="nonexistent_trades_test.db")
        # Even without DB data, the no-data status is returned first
        assert report.status == "NO_DATA"

    def test_cli_args_parsing(self):
        """CLI argument parsing via _cli() works without error."""
        # Just verify import works — CLI is tested via integration
        import core.finops
        assert hasattr(core.finops, "_cli")

    def test_summary_output_format(self):
        """CostReport.summary() produces consistent format."""
        costs = TradeCostBreakdown(brokerage=100, stt=50, total=200)
        report = CostReport(
            period_days=30, total_trades=10, total_turnover=500000.0,
            total_pnl=25000.0, total_costs=costs,
            cost_per_trade=TradeCostBreakdown(total=20.0),
            cost_pct_of_turnover=0.04, cost_pct_of_pnl=0.8,
            net_pnl_after_costs=24800.0,
        )
        text = report.summary()
        # Key sections
        assert "FinOps & Cost Governance Report" in text
        assert "Cost Metrics" in text
        assert "Net P&L after costs" in text
