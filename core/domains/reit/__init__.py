"""REIT & InvIT Domain — Real Estate & Infrastructure Investment Trust Models (Phase 10).

Supports:
- REITs (Real Estate Investment Trusts): Embassy, Mindspace, Brookfield, etc.
- InvITs (Infrastructure Investment Trusts): IRB, PowerGrid, etc.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "REITInvIT",
    "TrustType",
    "TRUST_TYPES",
]

TRUST_TYPES = ("REIT", "INVIT")


class TrustType:
    REIT = "REIT"
    INVIT = "INVIT"


@dataclass
class REITInvIT:
    """A REIT or InvIT listing.

    Attributes:
        symbol: Trading symbol.
        name: Full trust name.
        trust_type: REIT or INVIT.
        sector: Infrastructure sector (for InvITs) or property type (for REITs).
        lot_size: Minimum trading lot.
        aum_crores: Assets under management in crores.
        distribution_yield: Annual distribution yield (fraction, e.g., 0.06 for 6%).
        listing_date: Date of listing.
        isin: ISIN identifier.
    """

    symbol: str
    name: str = ""
    trust_type: str = TrustType.REIT
    sector: str = ""
    lot_size: int = 1
    aum_crores: float = 0.0
    distribution_yield: float = 0.0
    listing_date: str = ""
    isin: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "trust_type": self.trust_type,
            "sector": self.sector,
            "lot_size": self.lot_size,
            "aum_crores": self.aum_crores,
            "distribution_yield": self.distribution_yield,
            "listing_date": self.listing_date,
            "isin": self.isin,
        }

    def summary(self) -> str:
        return (
            f"{self.trust_type} {self.symbol} ({self.name})\n"
            f"  Sector: {self.sector} | AUM: ₹{self.aum_crores:.0f}Cr\n"
            f"  Distribution Yield: {self.distribution_yield:.2%} | Lot Size: {self.lot_size}"
        )
