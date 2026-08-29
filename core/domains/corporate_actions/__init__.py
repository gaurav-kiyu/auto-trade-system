"""IPO / FPO / OFS / QIP Domain — Primary Market Models (Phase 10 — Master Prompt).

Supports:
- IPO (Initial Public Offering)
- FPO (Follow-on Public Offering)
- OFS (Offer for Sale)
- QIP (Qualified Institutional Placement)
- Rights Issue
- Bonus Issue
- Stock Split
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CorporateAction",
    "CorporateActionType",
    "IPOEvent",
    "IssueType",
]

CORPORATE_ACTION_TYPES = (
    "DIVIDEND", "STOCK_SPLIT", "BONUS_ISSUE", "RIGHTS_ISSUE",
    "BUYBACK", "MERGER", "DEMERGER", "DELISTING",
)

ISSUE_TYPES = ("IPO", "FPO", "OFS", "QIP", "RIGHTS")


class IssueType:
    """Primary market issue type constants."""
    IPO = "IPO"
    FPO = "FPO"
    OFS = "OFS"
    QIP = "QIP"
    RIGHTS = "RIGHTS"


class CorporateActionType:
    """Corporate action type constants."""
    DIVIDEND = "DIVIDEND"
    STOCK_SPLIT = "STOCK_SPLIT"
    BONUS_ISSUE = "BONUS_ISSUE"
    RIGHTS_ISSUE = "RIGHTS_ISSUE"
    BUYBACK = "BUYBACK"
    MERGER = "MERGER"
    DEMERGER = "DEMERGER"
    DELISTING = "DELISTING"


@dataclass
class IPOEvent:
    """An IPO / FPO / OFS / QIP event.

    Attributes:
        symbol: Trading symbol.
        issue_type: IPO, FPO, OFS, QIP, or RIGHTS.
        company_name: Company full name.
        open_date: Subscription open date.
        close_date: Subscription close date.
        price_band_low: Lower price band.
        price_band_high: Upper price band.
        lot_size: Minimum lot size.
        lot_size_max: Maximum lot size for retail (defaults to 1 lot).
        total_issue_crores: Total issue size in crores.
        fresh_issue_crores: Fresh issue component (IPO/FPO).
        ofs_crores: OFS component.
        listing_date: Expected listing date.
        status: OPEN, CLOSED, LISTED, CANCELLED.
    """

    symbol: str
    issue_type: str = IssueType.IPO
    company_name: str = ""
    open_date: str = ""
    close_date: str = ""
    price_band_low: float = 0.0
    price_band_high: float = 0.0
    lot_size: int = 1
    lot_size_max: int = 1
    total_issue_crores: float = 0.0
    fresh_issue_crores: float = 0.0
    ofs_crores: float = 0.0
    listing_date: str = ""
    status: str = "OPEN"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "issue_type": self.issue_type,
            "company_name": self.company_name,
            "open_date": self.open_date,
            "close_date": self.close_date,
            "price_band": f"{self.price_band_low}–{self.price_band_high}",
            "lot_size": self.lot_size,
            "total_issue_crores": self.total_issue_crores,
            "fresh_issue_crores": self.fresh_issue_crores,
            "ofs_crores": self.ofs_crores,
            "listing_date": self.listing_date,
            "status": self.status,
        }

    def summary(self) -> str:
        return (
            f"{self.issue_type}: {self.company_name} ({self.symbol})\n"
            f"  Price Band: ₹{self.price_band_low}–{self.price_band_high}\n"
            f"  Subscription: {self.open_date} → {self.close_date}\n"
            f"  Lot Size: {self.lot_size} | Issue: ₹{self.total_issue_crores:.0f}Cr\n"
            f"  Status: {self.status}"
        )


@dataclass
class CorporateAction:
    """A corporate action event.

    Attributes:
        symbol: Trading symbol.
        action_type: DIVIDEND, STOCK_SPLIT, BONUS_ISSUE, etc.
        ex_date: Ex-date for the action.
        record_date: Record date.
        details: Action-specific details (dividend amount, split ratio, etc.).
        description: Human-readable description.
    """

    symbol: str
    action_type: str = CorporateActionType.DIVIDEND
    ex_date: str = ""
    record_date: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action_type": self.action_type,
            "ex_date": self.ex_date,
            "record_date": self.record_date,
            "details": self.details,
            "description": self.description,
        }

    def summary(self) -> str:
        return (
            f"{self.action_type}: {self.symbol}\n"
            f"  Ex-Date: {self.ex_date} | Record: {self.record_date}\n"
            f"  Details: {self.description or self.details}"
        )
