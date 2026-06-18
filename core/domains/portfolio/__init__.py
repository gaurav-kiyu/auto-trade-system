"""Portfolio Domain Models - Portfolio snapshots, performance, and exposure tracking.

Models portfolio-level data structures:
  - PositionSnapshot: Single position at a point in time
  - PortfolioSnapshot: Full portfolio state
  - PortfolioPerformance: Performance metrics over a period
  - ExposureRecord: Per-asset-class exposure tracking
  - MarginRequirement: Broker margin requirement breakdown
  - StrategyBudget: Capital budget per strategy

Usage:
    from core.domains.portfolio import (
        PortfolioSnapshot, PortfolioPerformance,
        PositionSnapshot, ExposureRecord, StrategyBudget
    )
"""
from core.domains.portfolio.model import (
    ExposureRecord,
    MarginRequirement,
    PortfolioPerformance,
    PortfolioSnapshot,
    PositionSnapshot,
    StrategyBudget,
)

__all__ = [
    "ExposureRecord",
    "MarginRequirement",
    "PortfolioPerformance",
    "PortfolioSnapshot",
    "PositionSnapshot",
    "StrategyBudget",
]
