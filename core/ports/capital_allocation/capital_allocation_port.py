"""Capital Allocation Port Interface - Multi-asset capital allocation.

Defines the contract for intelligently allocating capital across
different asset classes: equity, F&O, commodity, currency, fixed income.

This port decouples capital allocation logic from specific allocation
strategies (e.g., risk-parity, equal-weight, volatility-target).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AssetClass(Enum):
    """Supported asset classes for capital allocation."""
    EQUITY = "equity"                    # Cash equity (stocks)
    FUTURES_OPTIONS = "futures_options"  # NFO/BFO index & stock derivatives
    COMMODITY = "commodity"              # MCX commodities
    CURRENCY = "currency"                # CDS currency derivatives
    FIXED_INCOME = "fixed_income"        # G-Sec, bonds, T-Bills
    MUTUAL_FUNDS = "mutual_funds"        # Mutual funds, ETFs, REITs, InvITs
    CASH = "cash"                        # Cash / money market


@dataclass
class AllocationRequest:
    """Request to allocate capital across asset classes.

    Attributes:
        total_capital: Total available capital to allocate (INR)
        existing_allocations: Current allocations per asset class
        volatility_target: Target portfolio volatility (optional)
        risk_budget: Risk budget per asset class (percentage of total risk)
        constraints: Additional constraints (min/max per asset class)
        metadata: Additional context for the allocation decision
    """
    total_capital: float
    existing_allocations: dict[AssetClass, float] = field(default_factory=dict)
    volatility_target: float | None = None
    risk_budget: dict[AssetClass, float] | None = None
    constraints: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AllocationResult:
    """Result of capital allocation across asset classes.

    Attributes:
        allocations: Allocated capital per asset class
        remaining_cash: Unallocated cash remaining
        strategy_used: Name of allocation strategy applied
        explanation: Human-readable explanation of allocation decisions
        risk_metrics: Estimated risk metrics for the allocation
    """
    allocations: dict[AssetClass, float]
    remaining_cash: float = 0.0
    strategy_used: str = ""
    explanation: str = ""
    risk_metrics: dict[str, float] = field(default_factory=dict)


class CapitalAllocationPort(ABC):
    """Port interface for multi-asset capital allocation strategies.

    Implementations can use different strategies:
    - Risk-parity: Allocate based on inverse volatility
    - Equal-weight: Equal capital across asset classes
    - Volatility-target: Target a specific portfolio volatility
    - Custom: User-defined allocation strategy
    """

    @abstractmethod
    def allocate(self, request: AllocationRequest) -> AllocationResult:
        """Allocate capital across asset classes based on the request.

        Args:
            request: Allocation parameters and constraints

        Returns:
            AllocationResult with per-asset-class capital allocations
        """
        ...

    @abstractmethod
    def rebalance(self, request: AllocationRequest) -> AllocationResult:
        """Rebalance existing allocations towards target weights.

        Args:
            request: Current state and target allocation parameters

        Returns:
            AllocationResult with rebalanced allocations
        """
        ...

    @abstractmethod
    def get_allocation_summary(self) -> dict[AssetClass, dict[str, Any]]:
        """Get a summary of current allocations across all asset classes.

        Returns:
            Dictionary mapping each asset class to its allocation details
        """
        ...
