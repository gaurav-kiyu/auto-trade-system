"""
Futures & Options (F&O) Domain Models - Equity derivatives on NFO/BFO.

Models the complete lifecycle of equity derivative contracts:
  - Future contracts (monthly/weekly expiry)
  - Option contracts (CE/PE with Greeks)
  - Contract specifications (lot size, tick size, expiry)
  - Position tracking with margin
  - Spread positions (calendar, inter-commodity)
  - Strategy positions (straddles, strangles, iron condors)

Usage:
    from core.domains.fo import (
        FutureContract, OptionContract,
        ContractSpec, FOPosition, SpreadPosition
    )
"""
from core.domains.fo.models import (
    ContractSpec,
    ExpiryType,
    FutureContract,
    FuturePosition,
    NFO_CONTRACT_SPECS,
    OptionContract,
    OptionPosition,
    PositionType,
    SpreadLeg,
    SpreadPosition,
    SpreadType,
    UnderlyingType,
)

__all__ = [
    "ContractSpec",
    "ExpiryType",
    "FutureContract",
    "FuturePosition",
    "NFO_CONTRACT_SPECS",
    "OptionContract",
    "OptionPosition",
    "PositionType",
    "SpreadLeg",
    "SpreadPosition",
    "SpreadType",
    "UnderlyingType",
]
