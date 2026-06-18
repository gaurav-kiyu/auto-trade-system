"""Currency Derivatives Domain Models - CDS/FX products.

Models currency futures and options on NSE Currency Derivatives Segment (CDS):
  - USD/INR
  - EUR/INR
  - GBP/INR
  - JPY/INR
  - Cross-currency pairs
  - Contract specifications (lot size, tick size, expiry)
  - Position tracking with margin

Usage:
    from core.domains.currency import (
        CurrencyPair, CurrencyContract, CurrencyPosition,
        ContractSpec, CurrencyOptionContract
    )
"""
from core.domains.currency.models import (
    ContractSpec,
    CURRENCY_CONTRACT_SPECS,
    CurrencyContract,
    CurrencyOptionContract,
    CurrencyPair,
    CurrencyPosition,
    PositionType,
    SettlementType,
)

__all__ = [
    "ContractSpec",
    "CURRENCY_CONTRACT_SPECS",
    "CurrencyContract",
    "CurrencyOptionContract",
    "CurrencyPair",
    "CurrencyPosition",
    "PositionType",
    "SettlementType",
]
