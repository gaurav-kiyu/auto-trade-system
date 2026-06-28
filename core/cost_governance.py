"""
Cost Governance — Phase 27: FinOps & Cost Governance

Provides cost tracking, budgeting, and financial governance for the trading platform.
Integrates with core/finops.py for cost analysis and optimization.

Usage:
    from core.cost_governance import CostGovernance
    gov = CostGovernance()
    report = gov.generate_cost_report()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

_log = logging.getLogger(__name__)


# ── Cost Categories ────────────────────────────────────────────────────

@dataclass
class CostCategory:
    """A cost category with budget tracking."""
    name: str
    monthly_budget: float
    ytd_spend: float = 0.0
    monthly_spend: float = 0.0
    alerts_enabled: bool = True


@dataclass
class CostReport:
    """Periodic cost report."""
    period_start: date
    period_end: date
    categories: list[CostCategory] = field(default_factory=list)
    total_budget: float = 0.0
    total_spend: float = 0.0
    total_overspend: float = 0.0
    alerts: list[str] = field(default_factory=list)

    @property
    def utilization_pct(self) -> float:
        """Budget utilization percentage."""
        if self.total_budget <= 0:
            return 0.0
        return (self.total_spend / self.total_budget) * 100.0


# ── Default Budgets ────────────────────────────────────────────────────

_DEFAULT_BUDGETS: dict[str, float] = {
    "infrastructure": 5000.0,      # Server, hosting, Docker
    "data_feeds": 2000.0,          # Market data subscriptions
    "broker_fees": 1000.0,         # Brokerage, exchange fees (STT)
    "api_services": 500.0,         # Third-party API subscriptions
    "monitoring": 300.0,           # Monitoring, alerting services
    "development": 2000.0,         # Dev tools, CI/CD
    "ml_compute": 1000.0,          # ML training compute
    "miscellaneous": 500.0,        # Uncategorized
}


class CostGovernance:
    """
    Cost governance and budget management for the trading platform.

    Tracks spending across categories, enforces budgets,
    generates periodic cost reports, and integrates with FinOps.
    """

    def __init__(self, budgets: dict[str, float] | None = None) -> None:
        self._budgets: dict[str, float] = budgets or dict(_DEFAULT_BUDGETS)
        self._categories: dict[str, CostCategory] = {
            name: CostCategory(name=name, monthly_budget=budget)
            for name, budget in self._budgets.items()
        }
        self._alerts: list[str] = []

    def record_spend(self, category: str, amount: float, description: str = "") -> None:
        """Record a spend against a category."""
        cat = self._categories.get(category)
        if cat is None:
            _log.warning("Unknown cost category: %s", category)
            return
        cat.monthly_spend += amount
        cat.ytd_spend += amount
        _log.info("Spend recorded: %s %.2f - %s", category, amount, description)

        # Check budget thresholds
        if cat.monthly_spend >= cat.monthly_budget * 0.9:
            msg = f"WARNING: {category} at {cat.monthly_spend:.0f}/{cat.monthly_budget:.0f} ({(cat.monthly_spend / cat.monthly_budget) * 100:.0f}%)"
            self._alerts.append(msg)
            _log.warning(msg)

        if cat.monthly_spend >= cat.monthly_budget:
            msg = f"CRITICAL: {category} exceeded budget: {cat.monthly_spend:.0f} > {cat.monthly_budget:.0f}"
            self._alerts.append(msg)
            _log.critical(msg)

    def set_budget(self, category: str, budget: float) -> None:
        """Set or update a category budget."""
        if category in self._categories:
            self._categories[category].monthly_budget = budget
        else:
            self._categories[category] = CostCategory(name=category, monthly_budget=budget)
        _log.info("Budget set: %s = %.2f", category, budget)

    def get_category(self, name: str) -> CostCategory | None:
        """Get a cost category."""
        return self._categories.get(name)

    def get_alerts(self, clear: bool = True) -> list[str]:
        """Get pending budget alerts."""
        alerts = list(self._alerts)
        if clear:
            self._alerts.clear()
        return alerts

    def generate_cost_report(self, period_days: int = 30) -> CostReport:
        """Generate a cost report for the specified period."""
        end = date.today()
        start = end - timedelta(days=period_days)

        categories = list(self._categories.values())
        total_budget = sum(c.monthly_budget for c in categories)
        total_spend = sum(c.monthly_spend for c in categories)
        total_overspend = sum(
            max(0, c.monthly_spend - c.monthly_budget)
            for c in categories
        )

        return CostReport(
            period_start=start,
            period_end=end,
            categories=categories,
            total_budget=total_budget,
            total_spend=total_spend,
            total_overspend=total_overspend,
            alerts=self.get_alerts(),
        )

    def reset_monthly(self) -> None:
        """Reset monthly spend counters (call at start of each month)."""
        for cat in self._categories.values():
            cat.monthly_spend = 0.0
        _log.info("Monthly cost counters reset")

    def to_dict(self) -> dict[str, Any]:
        """Export governance state to dictionary."""
        return {
            "categories": {
                name: {
                    "budget": cat.monthly_budget,
                    "monthly_spend": cat.monthly_spend,
                    "ytd_spend": cat.ytd_spend,
                    "utilization_pct": round(
                        (cat.monthly_spend / cat.monthly_budget) * 100, 1
                    ) if cat.monthly_budget > 0 else 0.0,
                }
                for name, cat in self._categories.items()
            },
            "alerts": self._alerts,
        }


__all__ = [
    "CostCategory",
    "CostGovernance",
    "CostReport",
]
