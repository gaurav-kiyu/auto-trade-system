"""Capital Allocation Port - Multi-asset capital allocation interface.

Defines the contract for allocating capital across different asset classes:
  - Equity (cash market)
  - Futures & Options (NFO/BFO)
  - Commodity derivatives (MCX)
  - Currency derivatives (CDS)
  - Fixed income (G-Sec, bonds)
  - Mutual funds / ETFs

Usage:
    from core.ports.capital_allocation import (
        CapitalAllocationPort,
        AssetClass,
        AllocationRequest,
        AllocationResult,
    )
"""
from core.ports.capital_allocation.capital_allocation_port import (
    AllocationRequest,
    AllocationResult,
    AssetClass,
    CapitalAllocationPort,
)

__all__ = [
    "AllocationRequest",
    "AllocationResult",
    "AssetClass",
    "CapitalAllocationPort",
]
