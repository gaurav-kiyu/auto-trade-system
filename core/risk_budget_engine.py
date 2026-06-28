"""
Risk Budget Engine (Master Prompt Phase 9).

Manages risk budgets across asset classes and strategies. Wraps:
  - core/ports/capital_allocation/capital_allocation_port.py  (allocation framework)
  - core/services/risk_service.py                             (risk limits)
  - core/portfolio/optimizer.py                               (risk parity, ERC)

Usage:
    from core.risk_budget_engine import RiskBudgetEngine, BudgetAllocation

    engine = RiskBudgetEngine(total_capital=1_000_000)
    result = engine.allocate_risk_budget({
        "EQUITY": 0.30,
        "FUTURES_OPTIONS": 0.40,
        "COMMODITY": 0.10,
        "CURRENCY": 0.10,
        "FIXED_INCOME": 0.10,
    })
    print(result)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)


# ── Risk budget types ───────────────────────────────────────────────────────


class RiskBudgetStatus(str, Enum):
    """Status of a risk budget allocation."""
    UNDER_BUDGET = "UNDER_BUDGET"      # Within limits
    AT_BUDGET = "AT_BUDGET"            # At the limit
    OVER_BUDGET = "OVER_BUDGET"        # Exceeded the limit
    EXHAUSTED = "EXHAUSTED"            # No risk budget remaining


@dataclass
class BudgetAllocation:
    """A single risk budget allocation for an asset class.

    Attributes:
        asset_class: Asset class name (EQUITY, FUTURES_OPTIONS, etc.).
        risk_budget_pct: Target risk budget as percentage of total risk.
        allocated_capital: Capital allocated to this asset class (INR).
        used_risk_pct: Current risk utilization as percentage of allocation.
        status: Budget status (UNDER_BUDGET / AT_BUDGET / OVER_BUDGET / EXHAUSTED).
        remaining_capital: Unallocated capital remaining for this class.
    """
    asset_class: str
    risk_budget_pct: float = 0.0
    allocated_capital: float = 0.0
    used_risk_pct: float = 0.0
    status: RiskBudgetStatus = RiskBudgetStatus.UNDER_BUDGET
    remaining_capital: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"status": self.status.value}


@dataclass
class RiskBudgetResult:
    """Result of a risk budget allocation operation.

    Attributes:
        allocations: Per-asset-class budget allocations.
        total_risk_budget: Total risk budget allocated (INR).
        used_risk: Currently used risk (INR).
        remaining_risk: Remaining risk capacity (INR).
        timestamp: When this result was computed.
        warnings: Any warnings generated during allocation.
    """
    allocations: list[BudgetAllocation] = field(default_factory=list)
    total_capital: float = 0.0
    total_allocated: float = 0.0
    used_risk: float = 0.0
    remaining_capital: float = 0.0
    timestamp: str = ""
    warnings: list[str] = field(default_factory=list)


class RiskBudgetEngine:
    """Risk Budget Engine.

    Manages risk budgets across asset classes and strategies.
    Supports:
      - Target risk budget allocation by asset class
      - Risk utilization tracking
      - Over-budget detection and warnings
      - Integration with CapitalAllocationPort and PortfolioOptimizer
    """

    def __init__(self, total_capital: float = 0.0, cfg: dict[str, Any] | None = None):
        """Initialize the Risk Budget Engine.

        Args:
            total_capital: Total capital available for risk allocation.
            cfg: Optional config dict with risk budget parameters.
        """
        self._total_capital = total_capital
        self._cfg = cfg or {}
        self._lock = threading.RLock()
        self._allocations: dict[str, BudgetAllocation] = {}
        self._warning_threshold = float(self._cfg.get("risk_budget_warning_pct", 85.0))

    # ── Allocation ───────────────────────────────────────────────────────

    def allocate_risk_budget(
        self,
        budget_map: dict[str, float],
        total_capital: float | None = None,
    ) -> RiskBudgetResult:
        """Allocate risk budget across asset classes.

        Args:
            budget_map: Dict mapping asset class name → risk budget % (0-100).
                        E.g. {"EQUITY": 30, "FUTURES_OPTIONS": 40}
            total_capital: Optional override for total capital.

        Returns:
            RiskBudgetResult with per-class allocations.
        """
        with self._lock:
            capital = total_capital if total_capital is not None else self._total_capital
            ts = str(datetime.now())

            # Validate budget percentages sum to ~100
            total_pct = sum(budget_map.values())
            warnings: list[str] = []
            if abs(total_pct - 100.0) > 5.0:
                warnings.append(
                    f"Risk budget percentages sum to {total_pct:.1f}% "
                    f"(expected ~100%)"
                )

            allocations: list[BudgetAllocation] = []
            total_allocated = 0.0

            for asset_class, pct in budget_map.items():
                allocated = capital * (pct / 100.0)
                total_allocated += allocated

                allocations.append(BudgetAllocation(
                    asset_class=asset_class,
                    risk_budget_pct=pct,
                    allocated_capital=allocated,
                    used_risk_pct=0.0,
                    status=RiskBudgetStatus.UNDER_BUDGET,
                    remaining_capital=allocated,
                ))

                # Store for later tracking
                self._allocations[asset_class] = allocations[-1]

            remaining = capital - total_allocated
            if remaining < 0:
                warnings.append(
                    f"Total allocation ({total_allocated:.2f}) exceeds "
                    f"capital ({capital:.2f}) by {abs(remaining):.2f}"
                )

            return RiskBudgetResult(
                allocations=allocations,
                total_capital=capital,
                total_allocated=total_allocated,
                used_risk=0.0,
                remaining_capital=max(0.0, remaining),
                timestamp=ts,
                warnings=warnings,
            )

    # ── Tracking ─────────────────────────────────────────────────────────

    def update_risk_usage(
        self,
        asset_class: str,
        used_amount: float,
    ) -> BudgetAllocation | None:
        """Update the risk usage for an asset class and recalculate status.

        Args:
            asset_class: Asset class name.
            used_amount: Amount of risk budget currently used (INR).

        Returns:
            Updated BudgetAllocation or None if class not found.
        """
        with self._lock:
            alloc = self._allocations.get(asset_class)
            if alloc is None:
                _log.warning("No budget allocation for %s", asset_class)
                return None

            alloc.used_risk_pct = (
                (used_amount / alloc.allocated_capital * 100.0)
                if alloc.allocated_capital > 0 else 0.0
            )

            # Determine status
            if alloc.used_risk_pct >= 100.0:
                alloc.status = RiskBudgetStatus.EXHAUSTED
            elif alloc.used_risk_pct >= self._warning_threshold:
                alloc.status = RiskBudgetStatus.OVER_BUDGET
            elif alloc.used_risk_pct > 0:
                alloc.status = RiskBudgetStatus.AT_BUDGET
            else:
                alloc.status = RiskBudgetStatus.UNDER_BUDGET

            alloc.remaining_capital = max(0.0, alloc.allocated_capital - used_amount)

            # Warn if over budget
            if alloc.status in (RiskBudgetStatus.OVER_BUDGET, RiskBudgetStatus.EXHAUSTED):
                _log.warning(
                    "%s risk budget: %.1f%% used (%.2f / %.2f)",
                    asset_class, alloc.used_risk_pct, used_amount, alloc.allocated_capital,
                )

            return alloc

    def get_allocation(self, asset_class: str) -> BudgetAllocation | None:
        """Get the current budget allocation for an asset class.

        Args:
            asset_class: Asset class name.

        Returns:
            BudgetAllocation or None.
        """
        with self._lock:
            return self._allocations.get(asset_class)

    def get_all_allocations(self) -> dict[str, BudgetAllocation]:
        """Get all current budget allocations.

        Returns:
            Dict mapping asset class → BudgetAllocation.
        """
        with self._lock:
            return dict(self._allocations)

    def get_status_summary(self) -> dict[str, Any]:
        """Get a summary of all risk budget statuses.

        Returns:
            Dict with total budget, used, remaining, and per-class breakdown.
        """
        with self._lock:
            total_budget = sum(
                a.allocated_capital for a in self._allocations.values()
            )
            total_used = sum(
                a.allocated_capital * a.used_risk_pct / 100.0
                for a in self._allocations.values()
            )
            over_budget = [
                ac for ac, a in self._allocations.items()
                if a.status in (RiskBudgetStatus.OVER_BUDGET, RiskBudgetStatus.EXHAUSTED)
            ]

            return {
                "total_capital": self._total_capital,
                "total_budget": total_budget,
                "total_used": total_used,
                "remaining_capital": max(0.0, self._total_capital - total_used),
                "over_budget_classes": over_budget,
                "allocation_count": len(self._allocations),
                "allocations": {
                    ac: a.to_dict() for ac, a in self._allocations.items()
                },
            }

    # ── Risk parity integration ───────────────────────────────────────────

    def compute_risk_parity_allocation(
        self,
        volatilities: dict[str, float],
        total_capital: float | None = None,
    ) -> RiskBudgetResult:
        """Compute a risk-parity allocation based on inverse volatility.

        Delegates to core/portfolio/optimizer.py when available.

        Args:
            volatilities: Dict mapping asset class → annualized volatility.
            total_capital: Optional override for total capital.

        Returns:
            RiskBudgetResult with risk-parity allocations.
        """
        capital = total_capital if total_capital is not None else self._total_capital

        # Try portfolio optimizer for proper risk parity
        try:
            from core.portfolio.optimizer import PortfolioOptimizer

            opt = PortfolioOptimizer()
            # Build returns dict and cov matrix from volatilities
            returns = {k: 0.0 for k in volatilities}
            cov = {k: {k2: v * v2 * 0.3 for k2, v2 in volatilities.items()}
                   for k, v in volatilities.items()}

            result = opt.risk_parity(returns, cov)
            if result and result.get("weights"):
                budget_map = {
                    k: v * 100.0 for k, v in result["weights"].items()
                }
                return self.allocate_risk_budget(budget_map, capital)
        except ImportError:
            _log.info("PortfolioOptimizer not available; using inverse-vol")
        except Exception as e:
            _log.warning("Risk parity optimization failed: %s", e)

        # Fallback: simple inverse volatility
        total_inv_vol = sum(1.0 / max(v, 0.01) for v in volatilities.values())
        budget_map = {
            k: (1.0 / max(v, 0.01)) / total_inv_vol * 100.0
            for k, v in volatilities.items()
        }
        result = self.allocate_risk_budget(budget_map, capital)
        result.warnings.append("Used inverse-volatility fallback (portfolio optimizer unavailable)")
        return result

    def compute_equal_risk_contribution(
        self,
        volatilities: dict[str, float],
        correlations: dict[tuple[str, str], float] | None = None,
        total_capital: float | None = None,
    ) -> RiskBudgetResult:
        """Compute equal risk contribution (ERC) allocation.

        Delegates to core/portfolio/optimizer.py when available.

        Args:
            volatilities: Dict mapping asset class → annualized volatility.
            correlations: Optional dict of pairwise correlations.
            total_capital: Optional override.

        Returns:
            RiskBudgetResult with ERC allocations.
        """
        capital = total_capital if total_capital is not None else self._total_capital

        try:
            from core.portfolio.optimizer import PortfolioOptimizer

            opt = PortfolioOptimizer()
            returns = {k: 0.0 for k in volatilities}
            cov = {k: {k2: v * v2 * 0.3 for k2, v2 in volatilities.items()}
                   for k, v in volatilities.items()}

            if correlations:
                for (a, b), r in correlations.items():
                    if a in cov and b in cov[a]:
                        cov[a][b] = volatilities[a] * volatilities[b] * r
                        cov[b][a] = cov[a][b]

            result = opt.equal_risk_contribution(returns, cov)
            if result and result.get("weights"):
                budget_map = {
                    k: v * 100.0 for k, v in result["weights"].items()
                }
                return self.allocate_risk_budget(budget_map, capital)
        except ImportError:
            _log.info("PortfolioOptimizer not available; using equal-vol")
        except Exception as e:
            _log.warning("ERC optimization failed: %s", e)

        # Fallback: equal weights
        n = len(volatilities)
        if n == 0:
            return self.allocate_risk_budget({}, capital)
        equal_pct = 100.0 / n
        budget_map = {k: equal_pct for k in volatilities}
        result = self.allocate_risk_budget(budget_map, capital)
        result.warnings.append("Used equal-weight fallback (ERC optimizer unavailable)")
        return result

    # ── Utility ──────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset all budget allocations."""
        with self._lock:
            self._allocations.clear()
            _log.info("Risk budget engine reset")

    def set_total_capital(self, total_capital: float) -> None:
        """Update the total capital amount."""
        with self._lock:
            self._total_capital = total_capital
            _log.info("Total capital updated to %.2f", total_capital)

    def __repr__(self) -> str:
        return (
            f"RiskBudgetEngine(capital={self._total_capital:.2f}, "
            f"allocations={len(self._allocations)})"
        )


__all__ = [
    "BudgetAllocation",
    "RiskBudgetEngine",
    "RiskBudgetResult",
    "RiskBudgetStatus",
]
