"""
SME Equity Domain Models - Core data structures for NSE EMERGE / BSE SME stocks.

SME (Small and Medium Enterprise) stocks have distinct characteristics
from mainboard equities:
  - Listed on dedicated SME platforms (NSE EMERGE, BSE SME)
  - Stricter entry criteria for companies
  - Higher minimum lot sizes for trading
  - Trade-to-Trade (T2T) settlement
  - Price band circuit limits (5% or 10% vs 20% for mainboard)
  - Minimum application quantity for retail investors in SME IPO
  - Lock-in periods for promoters
  - Limited analyst coverage and institutional participation

All models include __post_init__ validation following the same pattern
as core.domains.equity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any

from core.domains.equity import CorporateAction, CorporateActionType, Sector


class SmePlatform(Enum):
    """SME listing platform."""
    NSE_EMERGE = "nse_emerge"
    BSE_SME = "bse_sme"


class SmeIssueType(Enum):
    """Type of SME issue."""
    FRESH = "fresh"              # Fresh issue of shares
    FRESH_OFS = "fresh_plus_ofs"  # Fresh issue + Offer for Sale


class SmeListingBasis(Enum):
    """Basis of allotment for SME listing."""
    PROPORTIONATE = "proportionate"  # Pro-rata allotment
    FORTY_X = "forty_x"             # 40x subscription threshold
    LOTTERY = "lottery"              # Lottery basis


class SmeTradingRestriction(Enum):
    """Trading restrictions applicable to SME stocks."""
    TRADE_TO_TRADE = "t2t"                       # T2T settlement only
    FIXED_PRICE_BAND = "fixed_price_band"         # Fixed 5% or 10% circuit
    NO_IPO_FRESH_SALE = "no_fresh_sale"           # Promoter lock-in
    MIN_LOT_TRADING = "min_lot_trading"           # Minimum lot trading
    TRADING_SUSPENDED = "trading_suspended"       # Currently suspended
    ASM_GRADED = "asm_graded"                     # ASM/GSM framework
    NONE = "none"                                  # No special restrictions


@dataclass
class SmeStockFundamentals:
    """Fundamental data specific to SME stocks.

    Extends base equity fundamental data with SME-specific fields.

    Attributes:
        market_cap: Market capitalisation in crores (typically < 250)
        pe_ratio: Price-to-earnings ratio
        eps: Earnings per share (₹)
        book_value: Book value per share (₹)
        roce: Return on capital employed (%)
        roe: Return on equity (%)
        debt_to_equity: Debt-to-equity ratio
        promoter_holding: Promoter holding percentage
        public_holding: Public holding percentage
        face_value: Face value per share (₹)
        shares_outstanding: Total shares outstanding (crores)
        ipo_price: Price at which the SME was listed via IPO
        ipo_listing_gains_pct: Listing day gains as percentage
        lock_in_end_date: Promoter lock-in end date
        min_lot_size: Minimum trading lot size (unique to SME)
        t2t_settlement: Whether trade-to-trade settlement applies
        circuit_limit_pct: Daily price band / circuit limit
        days_to_free_trading: Days remaining for restricted trading
        asm_gsm_stage: ASM/GSM stage if applicable (I, II, III, IV)
        is_sme_ipo: Whether newly listed via SME IPO
        anchor_investors: Number of anchor investors
        qib_portion: QIB portion in SME IPO (%)
        retail_portion: Retail portion in SME IPO (%)
    """
    market_cap: float = 0.0
    pe_ratio: float = 0.0
    eps: float = 0.0
    book_value: float = 0.0
    roce: float = 0.0
    roe: float = 0.0
    debt_to_equity: float = 0.0
    promoter_holding: float = 0.0
    public_holding: float = 0.0
    face_value: float = 10.0
    shares_outstanding: float = 0.0
    ipo_price: float = 0.0
    ipo_listing_gains_pct: float = 0.0
    lock_in_end_date: date | None = None
    min_lot_size: int = 0
    t2t_settlement: bool = False
    circuit_limit_pct: float = 5.0
    days_to_free_trading: int = 0
    asm_gsm_stage: str = ""
    is_sme_ipo: bool = False
    anchor_investors: int = 0
    qib_portion: float = 0.0
    retail_portion: float = 35.0

    def __post_init__(self) -> None:
        if self.face_value <= 0:
            raise ValueError(f"Face value must be positive, got {self.face_value}")
        if self.market_cap < 0:
            raise ValueError(f"Market cap cannot be negative, got {self.market_cap}")
        if self.promoter_holding < 0 or self.promoter_holding > 100:
            raise ValueError(f"Promoter holding must be 0-100%, got {self.promoter_holding}")
        if self.circuit_limit_pct <= 0 or self.circuit_limit_pct > 20:
            raise ValueError(f"Circuit limit must be 0-20%, got {self.circuit_limit_pct}")

    @property
    def is_small_cap(self) -> bool:
        """SME stocks are micro/small cap by definition (< 250 cr typical)."""
        return self.market_cap < 250


@dataclass
class SmeStock:
    """An SME equity stock listed on NSE EMERGE or BSE SME.

    Attributes:
        symbol: Trading symbol (e.g. "XYZLTD" on NSE EMERGE)
        name: Company name
        isin: ISIN
        sector: Sector classification
        platform: Listing platform (NSE EMERGE, BSE SME)
        face_value: Face value per share (₹)
        last_price: Latest traded price
        change_pct: Percentage change from previous close
        week_52_high: 52-week high price
        week_52_low: 52-week low price
        average_volume_10d: 10-day average volume (in shares)
        average_delivery_pct: Average delivery percentage
        fundamentals: SME-specific fundamental data
        corporate_actions: Recent corporate actions
        restrictions: Active trading restrictions
        issue_price: SME IPO issue price (if newly listed)
        listed_date: Date of SME platform listing
        is_active: Whether the stock is actively trading
    """
    symbol: str
    name: str = ""
    isin: str = ""
    sector: Sector = Sector.OTHER
    platform: SmePlatform = SmePlatform.NSE_EMERGE
    face_value: float = 10.0
    last_price: float = 0.0
    change_pct: float = 0.0
    week_52_high: float = 0.0
    week_52_low: float = 0.0
    average_volume_10d: int = 0
    average_delivery_pct: float = 0.0
    fundamentals: SmeStockFundamentals | None = None
    corporate_actions: list[CorporateAction] = field(default_factory=list)
    restrictions: list[SmeTradingRestriction] = field(default_factory=list)
    issue_price: float = 0.0
    listed_date: date | None = None
    is_active: bool = True
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def has_t2t_restriction(self) -> bool:
        """Whether the stock has trade-to-trade settlement."""
        return SmeTradingRestriction.TRADE_TO_TRADE in self.restrictions

    @property
    def circuit_percentage(self) -> float:
        """Effective circuit limit percentage for the day."""
        if self.fundamentals:
            return self.fundamentals.circuit_limit_pct
        return 5.0

    @property
    def upper_circuit(self) -> float:
        """Upper circuit price level for the day."""
        return self.last_price * (1 + self.circuit_percentage / 100)

    @property
    def lower_circuit(self) -> float:
        """Lower circuit price level for the day."""
        return self.last_price * (1 - self.circuit_percentage / 100)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("SME stock symbol cannot be empty")
        if self.last_price < 0:
            raise ValueError(f"Last price cannot be negative, got {self.last_price}")
        if self.face_value <= 0:
            raise ValueError(f"Face value must be positive, got {self.face_value}")
        if self.issue_price < 0:
            raise ValueError(f"Issue price cannot be negative, got {self.issue_price}")


@dataclass
class SmeIpo:
    """An SME IPO on NSE EMERGE / BSE SME.

    SME IPOs have distinct characteristics from mainboard IPOs:
      - Smaller issue size (typically < ₹50 crores)
      - Higher minimum lot sizes
      - Higher retail oversubscription multiples
      - Staggered listing timeline
      - Minimum 35% retail quota
      - 3-year lock-in for promoters
      - No pre-IPO placement for certain categories

    Attributes:
        company_name: Name of the company
        symbol: Proposed trading symbol
        platform: Listing platform
        issue_type: Fresh issue or Fresh + OFS
        issue_price_min: Lower end of price band
        issue_price_max: Upper end of price band
        lot_size: Minimum lot size for retail (₹)
        lot_shares: Number of shares per lot
        min_lots_retail: Minimum lots for retail category
        max_lots_retail: Maximum lots for retail category (typically 1-2)
        open_date: Subscription open date
        close_date: Subscription close date
        listing_date: Expected listing date
        basis_of_allotment: Basis of allotment
        total_issue_size: Total issue size in crores
        fresh_issue: Fresh issue portion in crores
        offer_for_sale: OFS portion in crores
        retail_quota: Retail allocation percentage (min 35%)
        qib_quota: QIB allocation percentage
        hni_quota: HNI allocation percentage
        anchor_portion: Anchor investor portion (%)
        listing_gains_pct: Listing day gains percentage (post-listing)
        total_subscription: Total subscription times subscribed
        retail_subscription: Retail subscription times
        status: Current status
        registrar: Registrar name
        lot_sizes: Lot size table for different categories
        is_active: Whether IPO is currently active/coming up
    """
    company_name: str
    symbol: str = ""
    platform: SmePlatform = SmePlatform.NSE_EMERGE
    issue_type: SmeIssueType = SmeIssueType.FRESH
    issue_price_min: float = 0.0
    issue_price_max: float = 0.0
    lot_size: int = 0
    lot_shares: int = 0
    min_lots_retail: int = 1
    max_lots_retail: int = 1
    open_date: date | None = None
    close_date: date | None = None
    listing_date: date | None = None
    basis_of_allotment: SmeListingBasis = SmeListingBasis.PROPORTIONATE
    total_issue_size: float = 0.0
    fresh_issue: float = 0.0
    offer_for_sale: float = 0.0
    retail_quota: float = 35.0
    qib_quota: float = 0.0
    hni_quota: float = 65.0
    anchor_portion: float = 0.0
    listing_gains_pct: float = 0.0
    total_subscription: float = 0.0
    retail_subscription: float = 0.0
    status: str = "ANNOUNCED"  # ANNOUNCED, OPEN, CLOSED, LISTED, WITHDRAWN
    registrar: str = ""
    lot_sizes: list[dict[str, Any]] = field(default_factory=list)
    is_active: bool = True
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_open(self) -> bool:
        return self.status == "OPEN"

    @property
    def price_band(self) -> tuple[float, float]:
        return (self.issue_price_min, self.issue_price_max)

    @property
    def min_investment_retail(self) -> float:
        """Minimum investment required for retail category."""
        return float(self.lot_size) * self.min_lots_retail

    def __post_init__(self) -> None:
        if not self.company_name:
            raise ValueError("Company name cannot be empty")
        if self.issue_price_min < 0:
            raise ValueError(f"Issue price min cannot be negative, got {self.issue_price_min}")
        if self.issue_price_max < 0:
            raise ValueError(f"Issue price max cannot be negative, got {self.issue_price_max}")
        if self.issue_price_min > self.issue_price_max > 0:
            raise ValueError(f"Min price ({self.issue_price_min}) > max price ({self.issue_price_max})")
        if self.total_issue_size < 0:
            raise ValueError(f"Issue size cannot be negative, got {self.total_issue_size}")
        if self.retail_quota < 0 or self.retail_quota > 100:
            raise ValueError(f"Retail quota must be 0-100%, got {self.retail_quota}")


@dataclass
class SmePosition:
    """Open SME equity position tracking.

    SME positions have additional tracking compared to mainboard equities:
      - T2T settlement flag
      - Minimum lot trading enforcement
      - Restricted stock period tracking

    Attributes:
        sme_stock: The SME stock held
        quantity: Position quantity (+ve long, -ve short)
        average_price: Average entry price
        current_price: Current market price
        unrealized_pnl: Mark-to-market P&L
        realized_pnl: Realized P&L from partial closes
        is_intraday: Whether this is an intraday position
        is_t2t: Whether position is in a T2T stock
        min_lot_quantity: Minimum lot quantity for trading
    """
    sme_stock: SmeStock
    quantity: int
    average_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    is_intraday: bool = False
    is_t2t: bool = False
    min_lot_quantity: int = 0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def position_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def pnl_points(self) -> float:
        return self.quantity * (self.current_price - self.average_price)

    @property
    def is_valid_lot(self) -> bool:
        """Check if position quantity is a valid multiple of min lot size."""
        if self.min_lot_quantity <= 0:
            return True
        return self.quantity % self.min_lot_quantity == 0

    def __post_init__(self) -> None:
        if self.average_price <= 0:
            raise ValueError(f"Average price must be positive, got {self.average_price}")
        if self.current_price <= 0:
            raise ValueError(f"Current price must be positive, got {self.current_price}")


__all__ = [
    "SmeIpo",
    "SmeIssueType",
    "SmeListingBasis",
    "SmePlatform",
    "SmePosition",
    "SmeStock",
    "SmeStockFundamentals",
    "SmeTradingRestriction",
]
