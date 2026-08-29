"""ETF Domain — Exchange-Traded Fund Models (Phase 10 — Master Prompt).

Supports:
- Equity ETFs (NIFTY 50 ETF, BANKNIFTY ETF, etc.)
- Debt ETFs (Bharat Bond, etc.)
- Gold ETFs
- International ETFs (if available on Indian exchanges)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "ETF",
    "ETFType",
    "ETF_PRODUCT_TYPES",
]

ETF_PRODUCT_TYPES = ("EQUITY", "DEBT", "GOLD", "INTERNATIONAL", "LIQUID", "OTHER")


class ETFType:
    """ETF type constants."""
    EQUITY = "EQUITY"
    DEBT = "DEBT"
    GOLD = "GOLD"
    INTERNATIONAL = "INTERNATIONAL"
    LIQUID = "LIQUID"
    OTHER = "OTHER"


@dataclass
class ETF:
    """An Exchange-Traded Fund listing.

    Attributes:
        symbol: Trading symbol (e.g., "NIFTYBEES").
        name: Full fund name (e.g., "Nippon India ETF Nifty 50 Bees").
        etf_type: ETF category (EQUITY, DEBT, GOLD, etc.).
        underlying_index: Underlying index name (e.g., "NIFTY 50").
        expense_ratio: Annual expense ratio (e.g., 0.05 for 0.05%).
        aum_crores: Assets under management in crores.
        lot_size: Minimum trading lot size.
        isin: ISIN identifier.
        amc: Asset management company name.
    """

    symbol: str
    name: str = ""
    etf_type: str = ETFType.EQUITY
    underlying_index: str = ""
    expense_ratio: float = 0.0
    aum_crores: float = 0.0
    lot_size: int = 1
    isin: str = ""
    amc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "etf_type": self.etf_type,
            "underlying_index": self.underlying_index,
            "expense_ratio": self.expense_ratio,
            "aum_crores": self.aum_crores,
            "lot_size": self.lot_size,
            "isin": self.isin,
            "amc": self.amc,
        }

    def summary(self) -> str:
        return (
            f"ETF {self.symbol} ({self.name})\n"
            f"  Type: {self.etf_type} | Underlying: {self.underlying_index}\n"
            f"  AUM: ₹{self.aum_crores:.0f}Cr | Expense: {self.expense_ratio:.3f}%\n"
            f"  Lot Size: {self.lot_size} | AMC: {self.amc}"
        )
