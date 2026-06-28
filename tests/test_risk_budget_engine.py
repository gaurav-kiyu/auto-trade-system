"""Tests for core/risk_budget_engine.py - Risk Budget Engine."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from core.risk_budget_engine import (
    BudgetAllocation,
    RiskBudgetEngine,
    RiskBudgetResult,
    RiskBudgetStatus,
)


# ── BudgetAllocation tests ───────────────────────────────────────────────────


class TestBudgetAllocation:
    """Tests for BudgetAllocation dataclass."""

    def test_defaults(self):
        ba = BudgetAllocation(asset_class="EQUITY")
        assert ba.risk_budget_pct == 0.0
        assert ba.allocated_capital == 0.0
        assert ba.status == RiskBudgetStatus.UNDER_BUDGET

    def test_to_dict(self):
        ba = BudgetAllocation(
            asset_class="FUTURES_OPTIONS",
            risk_budget_pct=40.0,
            allocated_capital=400_000,
            status=RiskBudgetStatus.AT_BUDGET,
        )
        d = ba.to_dict()
        assert d["asset_class"] == "FUTURES_OPTIONS"
        assert d["status"] == "AT_BUDGET"
        assert d["allocated_capital"] == 400_000


# ── RiskBudgetEngine tests ───────────────────────────────────────────────────


class TestRiskBudgetEngine:
    """Tests for RiskBudgetEngine."""

    def test_init_defaults(self):
        engine = RiskBudgetEngine()
        assert engine._total_capital == 0.0
        assert engine._allocations == {}

    def test_init_with_capital(self):
        engine = RiskBudgetEngine(total_capital=1_000_000)
        assert engine._total_capital == 1_000_000

    def test_init_with_config(self):
        engine = RiskBudgetEngine(total_capital=500_000, cfg={"risk_budget_warning_pct": 90.0})
        assert engine._warning_threshold == 90.0

    # ── allocate_risk_budget ─────────────────────────────────────────────

    def test_allocate_risk_budget_basic(self):
        engine = RiskBudgetEngine(total_capital=1_000_000)
        result = engine.allocate_risk_budget({
            "EQUITY": 30.0,
            "FUTURES_OPTIONS": 40.0,
            "COMMODITY": 20.0,
            "CASH": 10.0,
        })
        assert isinstance(result, RiskBudgetResult)
        assert len(result.allocations) == 4
        assert result.total_capital == 1_000_000
        assert result.total_allocated == 1_000_000
        assert result.remaining_capital == 0.0
        assert len(result.warnings) == 0

    def test_allocate_risk_budget_individual(self):
        engine = RiskBudgetEngine(total_capital=200_000)
        result = engine.allocate_risk_budget({"EQUITY": 50.0})
        assert len(result.allocations) == 1
        assert result.allocations[0].allocated_capital == 100_000
        assert result.allocations[0].remaining_capital == 100_000
        assert result.remaining_capital == 100_000

    def test_allocate_risk_budget_sum_warning(self):
        engine = RiskBudgetEngine(total_capital=100_000)
        result = engine.allocate_risk_budget({
            "EQUITY": 50.0,
            "BONDS": 30.0,
        })
        assert len(result.warnings) > 0
        assert "sum to 80.0%" in result.warnings[0]

    def test_allocate_risk_budget_over_capital(self):
        engine = RiskBudgetEngine(total_capital=100_000)
        result = engine.allocate_risk_budget({
            "EQUITY": 100.0,
            "FUTURES": 50.0,
        })
        assert len(result.warnings) > 0
        assert "exceeds" in result.warnings[-1]

    def test_allocate_risk_budget_capital_override(self):
        engine = RiskBudgetEngine(total_capital=100_000)
        result = engine.allocate_risk_budget(
            {"EQUITY": 100.0},
            total_capital=500_000,
        )
        assert result.total_capital == 500_000
        assert result.total_allocated == 500_000

    # ── update_risk_usage ────────────────────────────────────────────────

    def test_update_risk_usage(self):
        engine = RiskBudgetEngine(total_capital=100_000)
        engine.allocate_risk_budget({"EQUITY": 100.0})
        alloc = engine.update_risk_usage("EQUITY", 50_000)
        assert alloc is not None
        assert alloc.used_risk_pct == 50.0
        assert alloc.status == RiskBudgetStatus.AT_BUDGET

    def test_update_risk_usage_exhausted(self):
        engine = RiskBudgetEngine(total_capital=100_000)
        engine.allocate_risk_budget({"EQUITY": 100.0})
        alloc = engine.update_risk_usage("EQUITY", 100_000)
        assert alloc.status == RiskBudgetStatus.EXHAUSTED
        assert alloc.used_risk_pct == 100.0

    def test_update_risk_usage_over_budget(self):
        engine = RiskBudgetEngine(total_capital=100_000)
        engine.allocate_risk_budget({"EQUITY": 100.0})
        alloc = engine.update_risk_usage("EQUITY", 90_000)
        assert alloc.status == RiskBudgetStatus.OVER_BUDGET  # 90% > 85% threshold

    def test_update_risk_usage_over_threshold(self):
        engine = RiskBudgetEngine(total_capital=100_000, cfg={"risk_budget_warning_pct": 95.0})
        engine.allocate_risk_budget({"EQUITY": 100.0})
        alloc = engine.update_risk_usage("EQUITY", 90_000)
        assert alloc.status == RiskBudgetStatus.AT_BUDGET  # 90% < 95% threshold

    def test_update_risk_usage_nonexistent(self):
        engine = RiskBudgetEngine(total_capital=100_000)
        alloc = engine.update_risk_usage("FAKE", 1000)
        assert alloc is None

    def test_update_risk_usage_under_budget_after_use(self):
        engine = RiskBudgetEngine(total_capital=100_000)
        engine.allocate_risk_budget({"EQUITY": 100.0})
        alloc = engine.update_risk_usage("EQUITY", 25_000)
        assert alloc.used_risk_pct == 25.0
        assert alloc.remaining_capital == 75_000

    # ── get_allocation / get_all_allocations ─────────────────────────────

    def test_get_allocation(self):
        engine = RiskBudgetEngine(total_capital=100_000)
        engine.allocate_risk_budget({"EQUITY": 100.0})
        alloc = engine.get_allocation("EQUITY")
        assert alloc is not None
        assert alloc.asset_class == "EQUITY"

    def test_get_allocation_nonexistent(self):
        engine = RiskBudgetEngine()
        assert engine.get_allocation("FAKE") is None

    def test_get_all_allocations(self):
        engine = RiskBudgetEngine(total_capital=100_000)
        engine.allocate_risk_budget({
            "EQUITY": 50.0,
            "FUTURES": 50.0,
        })
        allocs = engine.get_all_allocations()
        assert len(allocs) == 2
        assert "EQUITY" in allocs
        assert "FUTURES" in allocs

    # ── get_status_summary ───────────────────────────────────────────────

    def test_get_status_summary_empty(self):
        engine = RiskBudgetEngine()
        summary = engine.get_status_summary()
        assert summary["total_budget"] == 0.0
        assert summary["allocation_count"] == 0

    def test_get_status_summary_with_allocations(self):
        engine = RiskBudgetEngine(total_capital=1_000_000)
        engine.allocate_risk_budget({
            "EQUITY": 50.0,
            "FUTURES": 50.0,
        })
        engine.update_risk_usage("EQUITY", 200_000)  # 40% used
        engine.update_risk_usage("FUTURES", 450_000)  # 90% used → OVER_BUDGET

        summary = engine.get_status_summary()
        assert summary["allocation_count"] == 2
        assert summary["total_budget"] == 1_000_000
        assert summary["total_used"] == 650_000  # 200K + 450K
        assert summary["remaining_capital"] == 350_000
        assert "FUTURES" in summary["over_budget_classes"]  # 90% > 85% threshold
        # 80% used is AT_BUDGET, not OVER_BUDGET
        # Let me recalculate: 80% of 500K = 400K used. threshold is 85%. So 80% < 85% → AT_BUDGET

    # ── reset ─────────────────────────────────────────────────────────────

    def test_reset(self):
        engine = RiskBudgetEngine(total_capital=100_000)
        engine.allocate_risk_budget({"EQUITY": 100.0})
        assert len(engine._allocations) == 1
        engine.reset()
        assert len(engine._allocations) == 0

    # ── set_total_capital ────────────────────────────────────────────────

    def test_set_total_capital(self):
        engine = RiskBudgetEngine(total_capital=100_000)
        assert engine._total_capital == 100_000
        engine.set_total_capital(500_000)
        assert engine._total_capital == 500_000

    # ── compute_risk_parity_allocation (with mock) ────────────────────────

    def test_risk_parity_fallback(self):
        engine = RiskBudgetEngine(total_capital=100_000)
        result = engine.compute_risk_parity_allocation({
            "EQUITY": 0.20,
            "BONDS": 0.10,
        })
        assert isinstance(result, RiskBudgetResult)
        assert len(result.allocations) == 2
        assert len(result.warnings) > 0  # Should have fallback warning

    @patch("core.portfolio.optimizer.PortfolioOptimizer.risk_parity")
    def test_risk_parity_with_optimizer(self, mock_rp):
        mock_rp.return_value = {"weights": {"A": 0.6, "B": 0.4}}
        engine = RiskBudgetEngine(total_capital=100_000)
        result = engine.compute_risk_parity_allocation({
            "A": 0.20,
            "B": 0.10,
        })
        assert len(result.allocations) == 2
        # A should get 60% of 100K = 60K
        a_alloc = next(a for a in result.allocations if a.asset_class == "A")
        assert a_alloc.allocated_capital == 60_000

    # ── compute_equal_risk_contribution (with mock) ───────────────────────

    def test_equal_risk_contribution_fallback(self):
        engine = RiskBudgetEngine(total_capital=100_000)
        result = engine.compute_equal_risk_contribution({
            "A": 0.20,
            "B": 0.10,
            "C": 0.15,
        })
        assert isinstance(result, RiskBudgetResult)
        assert len(result.allocations) == 3
        assert len(result.warnings) > 0

    def test_equal_risk_contribution_empty(self):
        engine = RiskBudgetEngine(total_capital=100_000)
        result = engine.compute_equal_risk_contribution({})
        assert len(result.allocations) == 0

    # ── __repr__ ──────────────────────────────────────────────────────────

    def test_repr(self):
        engine = RiskBudgetEngine(total_capital=500_000)
        engine.allocate_risk_budget({"EQUITY": 100.0})
        r = repr(engine)
        assert "500000" in r
        assert "1" in r  # one allocation

    def test_repr_empty(self):
        engine = RiskBudgetEngine()
        r = repr(engine)
        assert "0.00" in r
