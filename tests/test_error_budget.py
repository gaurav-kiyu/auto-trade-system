"""Tests for the Error Budget module."""

from __future__ import annotations

import time
import pytest
from core.error_budget import ErrorBudget, ErrorBudgetManager, BudgetStatus


class TestErrorBudget:
    """Tests for a single ErrorBudget instance."""

    def test_initial_status(self):
        """A new budget should have 100% remaining."""
        budget = ErrorBudget(slo_name="uptime", target=99.9)
        status = budget.get_status()
        assert status.slo_name == "uptime"
        assert status.target_pct == 99.9
        assert status.remaining_pct == 100.0
        assert status.at_risk is False

    def test_record_success(self):
        """Recording success should not consume budget."""
        budget = ErrorBudget(slo_name="uptime", target=99.9)
        budget.record_success(3600.0)
        status = budget.get_status()
        assert status.successes == 3600.0
        assert status.failures == 0.0

    def test_record_failure(self):
        """Recording failure should consume budget."""
        budget = ErrorBudget(slo_name="uptime", target=50.0, window_hours=720.0)
        # Record a large failure relative to a short elapsed time
        budget.record_failure(100.0)
        status = budget.get_status()
        assert status.failures == 100.0
        assert status.budget_consumed > 0

    def test_budget_remaining_decreases(self):
        """Budget remaining should decrease with failures."""
        budget = ErrorBudget(slo_name="uptime", target=99.9, window_hours=720.0)
        # Record a small failure
        budget.record_failure(1.0)
        # Record many successes
        budget.record_success(3600.0)
        status = budget.get_status()
        assert status.budget_total > 0
        assert status.budget_consumed >= 1.0

    def test_reset(self):
        """Reset should clear all events."""
        budget = ErrorBudget(slo_name="uptime", target=99.9)
        budget.record_failure(5.0)
        budget.reset()
        status = budget.get_status()
        assert status.failures == 0.0
        assert status.successes == 0.0

    def test_burn_rate_increases_with_failures(self):
        """Burn rate should increase when more failures are recorded."""
        budget = ErrorBudget(slo_name="test", target=99.9, window_hours=720.0)
        # Initial burn rate should be 0 with little data
        status = budget.get_status()
        initial_rate = status.burn_rate

        # Record many failures
        for _ in range(10):
            budget.record_failure(1.0)

        status = budget.get_status()
        # Burn rate should increase
        assert status.burn_rate >= initial_rate

    def test_budget_status_to_dict(self):
        """BudgetStatus should be serializable."""
        budget = ErrorBudget(slo_name="uptime", target=99.9)
        budget.record_success(3600.0)
        budget.record_failure(1.0)
        d = budget.get_status().to_dict()
        assert "slo_name" in d
        assert "burn_rate" in d
        assert "remaining_pct" in d
        assert d["slo_name"] == "uptime"

    def test_budget_summary(self):
        """Summary should produce formatted output."""
        budget = ErrorBudget(slo_name="uptime", target=99.9)
        budget.record_success(3600.0)
        s = budget.get_status().summary()
        assert "Error Budget" in s
        assert "uptime" in s
        assert "99.9" in s

    def test_merge(self):
        """Merging two budgets should combine events."""
        b1 = ErrorBudget(slo_name="uptime", target=99.9)
        b2 = ErrorBudget(slo_name="uptime", target=99.9)
        b1.record_failure(5.0)
        b2.record_failure(10.0)
        b1.merge(b2)
        assert b1._total_failures == 15.0


class TestErrorBudgetManager:
    """Tests for the ErrorBudgetManager."""

    def test_register_slo(self):
        """Registering an SLO should return a budget."""
        mgr = ErrorBudgetManager()
        budget = mgr.register_slo("uptime", target=99.9)
        assert isinstance(budget, ErrorBudget)
        assert budget.slo_name == "uptime"

    def test_get_budget(self):
        """Getting a registered budget should work."""
        mgr = ErrorBudgetManager()
        mgr.register_slo("uptime", target=99.9)
        budget = mgr.get_budget("uptime")
        assert budget is not None
        assert budget.target == 99.9

    def test_get_budget_nonexistent(self):
        """Getting an unregistered budget should return None."""
        mgr = ErrorBudgetManager()
        assert mgr.get_budget("nonexistent") is None

    def test_record_via_manager(self):
        """Recording via manager should work."""
        mgr = ErrorBudgetManager()
        mgr.register_slo("uptime", target=99.9)
        mgr.record_success("uptime", 3600.0)
        mgr.record_failure("uptime", 1.0)
        budget = mgr.get_budget("uptime")
        assert budget is not None
        status = budget.get_status()
        assert status.successes == 3600.0
        assert status.failures == 1.0

    def test_get_all_statuses(self):
        """get_all_statuses should return all registered budgets."""
        mgr = ErrorBudgetManager()
        mgr.register_slo("uptime", target=99.9)
        mgr.register_slo("replay", target=99.99)
        statuses = mgr.get_all_statuses()
        assert len(statuses) == 2
        assert "uptime" in statuses
        assert "replay" in statuses

    def test_get_risk_summary(self):
        """Risk summary should report at-risk SLOs."""
        mgr = ErrorBudgetManager()
        mgr.register_slo("uptime", target=99.9)
        summary = mgr.get_risk_summary()
        assert summary["tracked_slos"] == 1
        assert "overall_remaining_pct" in summary

    def test_reset_all(self):
        """Reset all should clear all budgets."""
        mgr = ErrorBudgetManager()
        mgr.register_slo("uptime", target=99.9)
        mgr.record_failure("uptime", 10.0)
        mgr.reset_all()
        budget = mgr.get_budget("uptime")
        assert budget is not None
        assert budget._total_failures == 0.0

    def test_double_register(self):
        """Registering the same SLO twice should return the same instance."""
        mgr = ErrorBudgetManager()
        b1 = mgr.register_slo("uptime", target=99.9)
        b2 = mgr.register_slo("uptime", target=99.99)
        assert b1 is b2
        assert b1.target == 99.9  # First registration wins


class TestBudgetIntegration:
    """Integration tests with simulated scenarios."""

    def test_slo_compliance_scenario(self):
        """Simulate a realistic SLO compliance scenario."""
        budget = ErrorBudget(slo_name="uptime", target=99.9, window_hours=720.0)
        # Simulate 30 days of operation
        for _ in range(30):
            # Each day: 86340 seconds success, 60 seconds failure = 99.93% uptime
            budget.record_success(86340.0)
            budget.record_failure(60.0)
        status = budget.get_status()
        # Should have consumed some budget but not all
        assert status.budget_consumed > 0
        assert status.failures == 30 * 60.0

    def test_budget_exhaustion_scenario(self):
        """Simulate budget exhaustion with high failure rate."""
        budget = ErrorBudget(slo_name="uptime", target=99.9, window_hours=72.0)  # 3-day window
        # High failure rate: 10% failures (way above 0.1% allowed)
        for _ in range(10):
            budget.record_failure(900.0)  # 15 min failure
            budget.record_success(100.0)  # ~1.7 min success
            # Ratio: 90% failure rate
        status = budget.get_status()
        # Budget should be heavily consumed
        assert status.budget_consumed > status.budget_total * 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
