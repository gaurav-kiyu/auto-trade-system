"""
Equity Domain Models - Core data structures for Indian cash equity market.

Covers:
  - NSE/BSE equity symbols with fundamental data
  - Corporate actions (dividends, splits, bonuses, rights)
  - IPO/FPO/OFS block deals and buybacks
  - Holdings management
  - Position tracking
  - Sectors and industry classifications

All models include __post_init__ validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class Sector(Enum):
    """NSE/BSE stock sector classification."""
    AUTOMOBILE = "automobile"
    BANKING = "banking"
    CAPITAL_GOODS = "capital_goods"
    CHEMICALS = "chemicals"
    CONSTRUCTION = "construction"
    CONSUMER_DURABLES = "consumer_durables"
    CONSUMER_NONDURABLES = "consumer_nondurables"
    ENERGY = "energy"
    FINANCIAL_SERVICES = "financial_services"
    FMCG = "fmcg"
    HEALTHCARE = "healthcare"
    INFORMATION_TECHNOLOGY = "information_technology"
    MEDIA = "media"
    METALS = "metals"
    OIL_GAS = "oil_gas"
    PHARMA = "pharma"
    POWER = "power"
    PSU = "psu"
    REALTY = "realty"
    TELECOM = "telecom"
    TEXTILES = "textiles"
    SERVICES = "services"
    OTHER = "other"


class CorporateActionType(Enum):
    """Type of corporate action."""
    DIVIDEND = "dividend"
    BONUS = "bonus"
    STOCK_SPLIT = "stock_split"
    REVERSE_SPLIT = "reverse_split"
    RIGHTS_ISSUE = "rights_issue"
    BUYBACK = "buyback"
    MERGER = "merger"
    DEMERGER = "demerger"
    DELISTING = "delisting"
    FCCB_CONVERSION = "fccb_conversion"


class BoardLot(Enum):
    """Standard board lot sizes for Indian markets."""
    FV_1 = 1      # Face value ₹1
    FV_2 = 1      # Face value ₹2
    FV_5 = 1      # Face value ₹5
    FV_10 = 1     # Face value ₹10 (most common)
    FV_100 = 1    # Face value ₹100


class IPOStatus(Enum):
    """IPO lifecycle status."""
    ANNOUNCED = "announced"
    OPEN = "open"
    CLOSED = "closed"
    LISTED = "listed"
    WITHDRAWN = "withdrawn"
    CANCELLED = "cancelled"


@dataclass
class StockFundamentals:
    """Fundamental data for an equity stock.

    Attributes:
        market_cap: Market capitalisation in crores
        pe_ratio: Price-to-earnings ratio
        pb_ratio: Price-to-book ratio
        eps: Earnings per share (₹)
        book_value: Book value per share (₹)
        roce: Return on capital employed (%)
        roe: Return on equity (%)
        roa: Return on assets (%)
        debt_to_equity: Debt-to-equity ratio
        current_ratio: Current ratio
        dividend_yield: Dividend yield (%)
        dividend_payout: Dividend payout ratio (%)
        sales_growth_3y: 3-year sales growth CAGR (%)
        profit_growth_3y: 3-year profit growth CAGR (%)
        promoter_holding: Promoter holding percentage
        fii_holding: FII holding percentage
        dii_holding: DII holding percentage
        public_holding: Public holding percentage
        face_value: Face value per share (₹)
        shares_outstanding: Total shares outstanding (crores)
        free_float: Free float market cap in crores
        industry_pe: Industry average PE
    """
    market_cap: float = 0.0
    pe_ratio: float = 0.0
    pb_ratio: float = 0.0
    eps: float = 0.0
    book_value: float = 0.0
    roce: float = 0.0
    roe: float = 0.0
    roa: float = 0.0
    debt_to_equity: float = 0.0
    current_ratio: float = 0.0
    dividend_yield: float = 0.0
    dividend_payout: float = 0.0
    sales_growth_3y: float = 0.0
    profit_growth_3y: float = 0.0
    promoter_holding: float = 0.0
    fii_holding: float = 0.0
    dii_holding: float = 0.0
    public_holding: float = 0.0
    face_value: float = 10.0
    shares_outstanding: float = 0.0
    free_float: float = 0.0
    industry_pe: float = 0.0

    def __post_init__(self) -> None:
        if self.face_value <= 0:
            raise ValueError(f"Face value must be positive, got {self.face_value}")
        if self.market_cap < 0:
            raise ValueError(f"Market cap cannot be negative, got {self.market_cap}")
        if self.promoter_holding < 0 or self.promoter_holding > 100:
            raise ValueError(f"Promoter holding must be 0-100%, got {self.promoter_holding}")

    @property
    def total_holding(self) -> float:
        """Sum of all known holdings."""
        return self.promoter_holding + self.fii_holding + self.dii_holding + self.public_holding


@dataclass
class Stock:
    """An equity stock listed on NSE/BSE.

    Attributes:
        symbol: Trading symbol (e.g. "RELIANCE", "TCS")
        name: Company name
        isin: ISIN (International Securities Identification Number)
        sector: Sector classification
        exchange: Listed exchange (NSE, BSE)
        series: Equity series (EQ for normal, BE for T2T, etc.)
        face_value: Face value per share (₹)
        last_price: Latest traded price
        change_pct: Percentage change from previous close
        week_52_high: 52-week high price
        week_52_low: 52-week low price
        average_volume_10d: 10-day average volume
        average_delivery_pct: Average delivery percentage
        fundamentals: Fundamental data
        corporate_actions: Recent corporate actions
        is_active: Whether the stock is actively trading
        timestamp: Last update time
    """
    symbol: str
    name: str = ""
    isin: str = ""
    sector: Sector = Sector.OTHER
    exchange: str = "NSE"  # "NSE" or "BSE"
    series: str = "EQ"
    face_value: float = 10.0
    last_price: float = 0.0
    change_pct: float = 0.0
    week_52_high: float = 0.0
    week_52_low: float = 0.0
    average_volume_10d: int = 0
    average_delivery_pct: float = 0.0
    fundamentals: StockFundamentals | None = None
    corporate_actions: list['CorporateAction'] = field(default_factory=list)
    is_active: bool = True
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def day_range(self) -> tuple[float, float]:
        """Typical day range approximation."""
        return self.last_price * 0.98, self.last_price * 1.02

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("Stock symbol cannot be empty")
        if self.last_price < 0:
            raise ValueError(f"Last price cannot be negative, got {self.last_price}")
        if self.face_value <= 0:
            raise ValueError(f"Face value must be positive, got {self.face_value}")


@dataclass
class CorporateAction:
    """A corporate action event on an equity stock.

    Attributes:
        stock_symbol: Symbol of the stock
        action_type: Type of corporate action
        announcement_date: Date of announcement
        ex_date: Ex-date / record date
        payment_date: Payment/credit date (for dividends)
        amount: Amount per share (dividend/bonus ratio)
        ratio: Ratio for splits/bonus (e.g. 2 for 2:1 split)
        description: Human-readable description
        is_approved: Whether approved by board/regulators
    """
    stock_symbol: str
    action_type: CorporateActionType
    announcement_date: date | None = None
    ex_date: date | None = None
    record_date: date | None = None
    payment_date: date | None = None
    amount: float = 0.0  # Dividend per share or ratio
    ratio: str = ""       # e.g. "2:1" for bonus, "10:1" for split
    description: str = ""
    is_approved: bool = False

    def __post_init__(self) -> None:
        if not self.stock_symbol:
            raise ValueError("Stock symbol cannot be empty")
        if self.amount < 0:
            raise ValueError(f"Amount cannot be negative, got {self.amount}")


@dataclass
class IPO:
    """An Initial Public Offering / Follow-on Public Offering.

    Attributes:
        company_name: Name of the company
        symbol: Proposed trading symbol
        ipo_type: "IPO", "FPO", or "OFS"
        issue_price_min: Lower end of price band
        issue_price_max: Upper end of price band
        lot_size: Minimum lot size for retail
        lot_min_amount: Minimum investment for retail
        open_date: Subscription open date
        close_date: Subscription close date
        listing_date: Expected listing date
        total_issue_size: Total issue size in crores
        fresh_issue: Fresh issue portion in crores
        offer_for_sale: OFS portion in crores
        retail_quota: Retail allocation percentage
        qib_quota: QIB allocation percentage
        hni_quota: HNI allocation percentage
        listing_gains_pct: Listing day gains percentage
        status: Current status
        registrar: Registrar name
        lot_sizes: Lot size table (mp:lots)
    """
    company_name: str
    symbol: str = ""
    ipo_type: str = "IPO"  # "IPO", "FPO", "OFS"
    issue_price_min: float = 0.0
    issue_price_max: float = 0.0
    lot_size: int = 0
    lot_min_amount: float = 0.0
    open_date: date | None = None
    close_date: date | None = None
    listing_date: date | None = None
    total_issue_size: float = 0.0
    fresh_issue: float = 0.0
    offer_for_sale: float = 0.0
    retail_quota: float = 35.0
    qib_quota: float = 50.0
    hni_quota: float = 15.0
    listing_gains_pct: float = 0.0
    status: IPOStatus = IPOStatus.ANNOUNCED
    registrar: str = ""
    lot_sizes: list[dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_open(self) -> bool:
        return self.status == IPOStatus.OPEN

    @property
    def price_band(self) -> tuple[float, float]:
        return (self.issue_price_min, self.issue_price_max)

    @property
    def total_applications(self) -> int:
        """Total subscription applications (placeholder)."""
        return 0

    def __post_init__(self) -> None:
        if self.issue_price_min < 0:
            raise ValueError(f"Issue price min cannot be negative, got {self.issue_price_min}")
        if self.issue_price_max < 0:
            raise ValueError(f"Issue price max cannot be negative, got {self.issue_price_max}")
        if self.issue_price_min > self.issue_price_max > 0:
            raise ValueError(f"Min price ({self.issue_price_min}) > max price ({self.issue_price_max})")
        if self.total_issue_size < 0:
            raise ValueError(f"Issue size cannot be negative, got {self.total_issue_size}")


@dataclass
class Holding:
    """Demat holding record for a stock.

    Attributes:
        stock_symbol: Symbol of the stock
        quantity: Total quantity held
        available_quantity: Quantity available for trading
        blocked_quantity: Quantity blocked (pledged, in orders)
        average_cost: Average purchase price
        current_price: Current market price
        pnl: Profit/loss on this holding
        pnl_percentage: P&L as percentage of cost
        isin: ISIN of the stock
        pledge_flag: Whether shares are pledged
    """
    stock_symbol: str
    quantity: int
    available_quantity: int
    blocked_quantity: int = 0
    average_cost: float = 0.0
    current_price: float = 0.0
    pnl: float = 0.0
    pnl_percentage: float = 0.0
    isin: str = ""
    pledge_flag: bool = False
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def investment_value(self) -> float:
        return self.quantity * self.average_cost

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def is_pledged(self) -> bool:
        return self.pledge_flag

    def __post_init__(self) -> None:
        if self.quantity < 0:
            raise ValueError(f"Quantity cannot be negative, got {self.quantity}")
        if self.available_quantity < 0:
            raise ValueError(f"Available quantity cannot be negative, got {self.available_quantity}")
        if self.available_quantity > self.quantity:
            raise ValueError(f"Available quantity ({self.available_quantity}) > total quantity ({self.quantity})")
        if self.blocked_quantity < 0:
            raise ValueError(f"Blocked quantity cannot be negative, got {self.blocked_quantity}")
        if self.average_cost < 0:
            raise ValueError(f"Average cost cannot be negative, got {self.average_cost}")
        if self.current_price < 0:
            raise ValueError(f"Current price cannot be negative, got {self.current_price}")


@dataclass
class EquityPosition:
    """Active equity position tracking.

    Attributes:
        stock: The stock held
        quantity: Position quantity (+ve long, -ve short)
        average_price: Average entry price
        current_price: Current market price
        unrealized_pnl: Mark-to-market P&L
        realized_pnl: Realized P&L from partial closes
        is_intraday: Whether this is an intraday (MIS) position
        is_delivery: Whether this is a delivery (CNC) position
        margin_used: Margin blocked
    """
    stock: Stock
    quantity: int
    average_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    is_intraday: bool = False
    is_delivery: bool = False
    margin_used: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def position_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def pnl_points(self) -> float:
        return self.quantity * (self.current_price - self.average_price)

    def __post_init__(self) -> None:
        if self.average_price <= 0:
            raise ValueError(f"Average price must be positive, got {self.average_price}")
        if self.current_price <= 0:
            raise ValueError(f"Current price must be positive, got {self.current_price}")


__all__ = [
    "BoardLot",
    "CorporateAction",
    "CorporateActionType",
    "EquityPosition",
    "Holding",
    "IPO",
    "IPOStatus",
    "Sector",
    "Stock",
    "StockFundamentals",
]
