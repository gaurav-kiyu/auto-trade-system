"""
Mutual Fund & ETF Domain Models - Core data structures for Indian MF ecosystem.

Covers:
  - Open-ended & close-ended mutual fund schemes
  - Equity, Debt, Hybrid, Liquid, Index, FOF, GOLD ETF, International
  - Direct & Regular plans, Growth & Dividend options
  - ETFs (index, gold, international, sectoral)
  - REITs (Real Estate Investment Trusts)
  - InvITs (Infrastructure Investment Trusts)
  - NAV tracking with historical records
  - SIP/STP/SWP modeling
  - Portfolio holdings and sector/stock allocation

All models include __post_init__ validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class FundCategory(Enum):
    """Mutual fund category as per SEBI classification."""
    # Equity
    LARGE_CAP = "large_cap"
    LARGE_MID_CAP = "large_mid_cap"
    MID_CAP = "mid_cap"
    SMALL_CAP = "small_cap"
    MULTI_CAP = "multi_cap"
    ELSS = "elss"  # Tax saver
    VALUE = "value"
    CONTRARIAN = "contrarian"
    FOCUSED = "focused"
    SECTORAL = "sectoral"  # e.g. Banking, Pharma, IT
    THEMATIC = "thematic"
    # Debt
    LIQUID = "liquid"
    ULTRA_SHORT = "ultra_short"
    LOW_DURATION = "low_duration"
    MONEY_MARKET = "money_market"
    SHORT_DURATION = "short_duration"
    MEDIUM_DURATION = "medium_duration"
    LONG_DURATION = "long_duration"
    CORPORATE_BOND = "corporate_bond"
    CREDIT_RISK = "credit_risk"
    BANKING_PSU = "banking_psu"
    GILT = "gilt"
    GILT_10Y = "gilt_10y"
    FLOATING_RATE = "floating_rate"
    # Hybrid
    AGGRESSIVE_HYBRID = "aggressive_hybrid"
    BALANCED_HYBRID = "balanced_hybrid"
    CONSERVATIVE_HYBRID = "conservative_hybrid"
    EQUITY_SAVINGS = "equity_savings"
    ARBITRAGE = "arbitrage"
    # Other
    INDEX = "index"
    ETF = "etf"
    FOF = "fof"  # Fund of Funds
    INTERNATIONAL = "international"
    GOLD_ETF = "gold_etf"
    REIT = "reit"
    INVIT = "invit"
    SOLUTION = "solution"  # Retirement, Children's
    OTHER = "other"


class FundType(Enum):
    """Fund structure type."""
    OPEN_ENDED = "open_ended"
    CLOSE_ENDED = "close_ended"
    INTERVAL = "interval"
    ETF = "etf"
    INDEX = "index"


class FundPlan(Enum):
    """Mutual fund plan type."""
    DIRECT = "direct"
    REGULAR = "regular"


class FundOption(Enum):
    """Mutual fund option type (IDCW / Growth)."""
    GROWTH = "growth"
    IDCW_PAYOUT = "idcw_payout"      # Income Distribution cum Capital Withdrawal
    IDCW_REINVEST = "idcw_reinvest"
    IDCW_QUARTERLY = "idcw_quarterly"
    IDCW_HALF_YEARLY = "idcw_half_yearly"
    IDCW_ANNUAL = "idcw_annual"
    BONUS = "bonus"
    SWP = "swp"  # Systematic Withdrawal Plan


class DividendType(Enum):
    """Dividend option for MFs."""
    PAYOUT = "payout"
    REINVEST = "reinvest"
    ACCUMULATION = "accumulation"  # Growth


class ExpenseRatioType(Enum):
    """Expense ratio components."""
    TOTAL = "total"
    MANAGEMENT = "management"
    LOAD = "load"
    EXIT_LOAD = "exit_load"


class SIPFrequency(Enum):
    """SIP frequency."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class MFTransactionType(Enum):
    """Mutual fund transaction type."""
    PURCHASE = "purchase"
    REDEMPTION = "redemption"
    SWITCH_IN = "switch_in"
    SWITCH_OUT = "switch_out"
    DIVIDEND = "dividend"
    STP_IN = "stp_in"
    STP_OUT = "stp_out"
    SWP = "swp"
    REBALANCE = "rebalance"


@dataclass
class NavRecord:
    """Net Asset Value record for a mutual fund/ETF.

    Attributes:
        date: NAV date
        nav: Net Asset Value (₹ per unit)
        repurchase_price: Repurchase price (if different)
        sale_price: Sale price (if different)
        change_pct: Day change percentage
        aum: Assets Under Management on this date (₹ crores)
    """
    date: date
    nav: float
    repurchase_price: float = 0.0
    sale_price: float = 0.0
    change_pct: float = 0.0
    aum: float = 0.0

    def __post_init__(self) -> None:
        if self.nav <= 0:
            raise ValueError(f"NAV must be positive, got {self.nav}")
        if self.repurchase_price < 0:
            raise ValueError(f"Repurchase price cannot be negative, got {self.repurchase_price}")
        if self.sale_price < 0:
            raise ValueError(f"Sale price cannot be negative, got {self.sale_price}")


@dataclass
class FundHolding:
    """Portfolio holding of a mutual fund scheme.

    Attributes:
        name: Company / security name
        symbol: Trading symbol (if listed)
        isin: ISIN (if available)
        sector: Sector classification
        allocation_pct: Percentage of AUM allocated
        quantity: Number of units/shares held
        market_value: Market value (₹ crores)
        change_pct: Percentage change in holding vs previous period
        holding_type: "equity", "debt", "cash", "others"
    """
    name: str
    symbol: str = ""
    isin: str = ""
    sector: str = ""
    allocation_pct: float = 0.0
    quantity: int = 0
    market_value: float = 0.0
    change_pct: float = 0.0
    holding_type: str = "equity"  # "equity", "debt", "cash", "others"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Holding name cannot be empty")
        if self.allocation_pct < 0 or self.allocation_pct > 100:
            raise ValueError(f"Allocation must be 0-100%, got {self.allocation_pct}")


@dataclass
class PortfolioAllocation:
    """Sector / asset class allocation for a fund.

    Attributes:
        equities: Equity allocation percentage
        debt: Debt allocation percentage
        cash: Cash & equivalents percentage
        others: Other assets percentage
        sector_allocations: Dict of sector -> percentage
        market_cap_breakup: Dict of market cap -> percentage
    """
    equities: float = 0.0
    debt: float = 0.0
    cash: float = 0.0
    others: float = 0.0
    sector_allocations: dict[str, float] = field(default_factory=dict)
    market_cap_breakup: dict[str, float] = field(default_factory=dict)

    @property
    def is_invested(self) -> bool:
        return self.equities > 0 or self.debt > 0

    def __post_init__(self) -> None:
        total = self.equities + self.debt + self.cash + self.others
        if total > 100.1:  # Allow small rounding
            raise ValueError(f"Total allocation ({total}) exceeds 100%")


@dataclass
class MutualFund:
    """A mutual fund scheme.

    Attributes:
        scheme_code: AMFI/SEBI scheme code (e.g. 119551)
        scheme_name: Full scheme name
        fund_house: AMC / fund house name
        fund_category: SEBI category
        fund_type: Fund structure type
        plan: Direct or Regular
        option: Fund option (Growth, IDCW, etc.)
        isin: ISIN of the scheme (growth + IDCW)
        isin_idcw_reinvest: ISIN for IDCW reinvestment option
        amfi_code: AMFI code
        rta_code: RTA code (CAMS/KFintech)
        benchmark: Benchmark index name
        expense_ratio: Total expense ratio (%)
        exit_load: Exit load structure (e.g. "1% if redeemed within 90D")
        lock_in_period: Lock-in period in days (0 = no lock-in)
        min_sip_amount: Minimum SIP investment (₹)
        min_lumpsum_amount: Minimum lump sum investment (₹)
        aum: Current AUM (₹ crores)
        nav: Current NAV
        nav_date: Date of current NAV
        nav_history: Historical NAV records
        portfolio: Portfolio holdings
        allocation: Asset class allocation
        fund_manager: Fund manager name
        launch_date: Scheme launch date
        maturity_date: Maturity date (for close-ended)
        rating: CRISIL/Morningstar rating
        risk_level: "LOW", "MODERATE", "HIGH", "VERY_HIGH"
        is_active: Whether scheme is active
    """
    scheme_code: str
    scheme_name: str
    fund_house: str = ""
    fund_category: FundCategory = FundCategory.OTHER
    fund_type: FundType = FundType.OPEN_ENDED
    plan: FundPlan = FundPlan.DIRECT
    option: FundOption = FundOption.GROWTH
    isin: str = ""
    isin_idcw_reinvest: str = ""
    amfi_code: str = ""
    rta_code: str = ""
    benchmark: str = ""
    expense_ratio: float = 0.0
    exit_load: str = ""
    lock_in_period: int = 0
    min_sip_amount: float = 500.0
    min_lumpsum_amount: float = 5000.0
    aum: float = 0.0
    nav: float = 0.0
    nav_date: date | None = None
    nav_history: list[NavRecord] = field(default_factory=list)
    portfolio: list[FundHolding] = field(default_factory=list)
    allocation: PortfolioAllocation | None = None
    fund_manager: str = ""
    launch_date: date | None = None
    maturity_date: date | None = None
    rating: str = ""
    risk_level: str = "MODERATE"
    is_active: bool = True
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def return_1y(self) -> float:
        """1-year return percentage (placeholder, would calc from nav_history)."""
        return 0.0

    @property
    def return_3y(self) -> float:
        """3-year CAGR return percentage."""
        return 0.0

    @property
    def return_5y(self) -> float:
        """5-year CAGR return percentage."""
        return 0.0

    @property
    def return_since_inception(self) -> float:
        """Since inception return percentage."""
        return 0.0

    def __post_init__(self) -> None:
        if not self.scheme_code:
            raise ValueError("Scheme code cannot be empty")
        if not self.scheme_name:
            raise ValueError("Scheme name cannot be empty")
        if self.nav < 0:
            raise ValueError(f"NAV cannot be negative, got {self.nav}")
        if self.expense_ratio < 0:
            raise ValueError(f"Expense ratio cannot be negative, got {self.expense_ratio}")
        if self.lock_in_period < 0:
            raise ValueError(f"Lock-in period cannot be negative, got {self.lock_in_period}")


@dataclass
class ETF(MutualFund):
    """An Exchange-Traded Fund (ETF) - extends MutualFund.

    Adds:
        - underlying_index: Tracked index (e.g. "NIFTY 50")
        - expense_ratio: Typically lower for ETFs
        - lot_size: Minimum lot size for exchange trading
        - market_price: Current market price on exchange
        - premium_discount: Premium or discount to NAV (%)
        - average_spread: Average bid-ask spread
        - tracking_error: Tracking error vs index
        - replication: "Physical", "Synthetic", or "Sampling"
        - is_gold: Whether gold ETF
        - is_international: Whether international ETF
    """
    underlying_index: str = ""
    lot_size: int = 1
    market_price: float = 0.0
    premium_discount: float = 0.0
    average_spread: float = 0.0
    tracking_error: float = 0.0
    replication: str = "physical"  # "physical", "synthetic", "sampling"
    is_gold: bool = False
    is_international: bool = False
    derivative_based: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.lot_size <= 0:
            raise ValueError(f"Lot size must be positive, got {self.lot_size}")
        if self.market_price < 0:
            raise ValueError(f"Market price cannot be negative, got {self.market_price}")

    @property
    def is_premium(self) -> bool:
        """True if trading at premium to NAV."""
        return self.premium_discount > 0


@dataclass
class REIT:
    """Real Estate Investment Trust (REIT) - listed on NSE/BSE.

    Attributes:
        symbol: Trading symbol (e.g. "EMBASSY", "MINDTREE")
        name: Trust name
        isin: ISIN
        listed_date: Date of listing
        units_outstanding: Total outstanding units
        nav_per_unit: NAV per unit (₹)
        market_price: Current market price (₹)
        dividend_yield: Annual dividend yield (%)
        distribution_per_unit: Distribution per unit (₹)
        occupancy: Occupancy rate (%)
        wale: Weighted Average Lease Expiry (years)
        portfolio_value: Total portfolio value (₹ crores)
        gearing: Gearing / leverage ratio
        dscr: Debt Service Coverage Ratio
        latest_dpru: Latest distribution per unit (₹)
        frequency: Distribution frequency (quarterly/half-yearly/annual)
    """
    symbol: str
    name: str = ""
    isin: str = ""
    listed_date: date | None = None
    units_outstanding: int = 0
    nav_per_unit: float = 0.0
    market_price: float = 0.0
    dividend_yield: float = 0.0
    distribution_per_unit: float = 0.0
    occupancy: float = 0.0
    wale: float = 0.0
    portfolio_value: float = 0.0
    gearing: float = 0.0
    dscr: float = 0.0
    latest_dpru: float = 0.0
    frequency: str = "quarterly"
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def market_cap(self) -> float:
        return self.market_price * self.units_outstanding / 10000000  # in crores

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("Symbol cannot be empty")
        if self.market_price < 0:
            raise ValueError(f"Market price cannot be negative, got {self.market_price}")


@dataclass
class InvIT:
    """Infrastructure Investment Trust (InvIT) - listed on NSE/BSE.

    Attributes:
        symbol: Trading symbol (e.g. "IRBINVIT", "POWERGRID")
        name: Trust name
        isin: ISIN
        listed_date: Date of listing
        units_outstanding: Total outstanding units
        nav_per_unit: NAV per unit (₹)
        market_price: Current market price (₹)
        distribution_yield: Annual distribution yield (%)
        dpru: Latest distribution per unit (₹)
        project_count: Number of infrastructure projects
        total_assets: Total assets under trust (₹ crores)
        debt_equity_ratio: Debt to equity ratio
        concession_life: Average remaining concession life (years)
        min_public_shareholding: Minimum public shareholding (%)
        sponsor: Sponsor name
        manager: Investment manager name
    """
    symbol: str
    name: str = ""
    isin: str = ""
    listed_date: date | None = None
    units_outstanding: int = 0
    nav_per_unit: float = 0.0
    market_price: float = 0.0
    distribution_yield: float = 0.0
    dpru: float = 0.0
    project_count: int = 0
    total_assets: float = 0.0
    debt_equity_ratio: float = 0.0
    concession_life: float = 0.0
    min_public_shareholding: float = 25.0
    sponsor: str = ""
    manager: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def market_cap(self) -> float:
        return self.market_price * self.units_outstanding / 10000000  # in crores

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("Symbol cannot be empty")
        if self.market_price < 0:
            raise ValueError(f"Market price cannot be negative, got {self.market_price}")


@dataclass
class SIP:
    """Systematic Investment Plan (SIP) registration.

    Attributes:
        sip_id: SIP identifier
        fund: Target mutual fund
        frequency: SIP frequency
        amount: Investment amount per instalment (₹)
        instalment_day: Day of month/week for SIP
        start_date: SIP start date
        end_date: SIP end date (None = open-ended)
        total_instalments: Total instalments (0 = unlimited)
        completed_instalments: Completed instalments
        total_invested: Total amount invested so far (₹)
        current_value: Current value of units (₹)
        xirr: XIRR return (%)
        is_active: Whether SIP is active
        sip_type: "sip", "stp", "swp"
        trigger_type: "date", "nav", "market_cap", "none"
        trigger_value: Trigger condition value
    """
    sip_id: str
    fund: MutualFund
    frequency: SIPFrequency
    amount: float
    instalment_day: int = 1
    start_date: date = field(default_factory=date.today)
    end_date: date | None = None
    total_instalments: int = 0
    completed_instalments: int = 0
    total_invested: float = 0.0
    current_value: float = 0.0
    xirr: float = 0.0
    is_active: bool = True
    sip_type: str = "sip"
    trigger_type: str = "date"
    trigger_value: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def return_pct(self) -> float:
        if self.total_invested <= 0:
            return 0.0
        return ((self.current_value - self.total_invested) / self.total_invested) * 100.0

    @property
    def gap_amount(self) -> float:
        """One-time gap if stopping SIP."""
        return self.amount * 1000000  # Placeholder

    def __post_init__(self) -> None:
        if not self.sip_id:
            raise ValueError("SIP ID cannot be empty")
        if self.amount <= 0:
            raise ValueError(f"SIP amount must be positive, got {self.amount}")
        if self.total_invested < 0:
            raise ValueError(f"Total invested cannot be negative, got {self.total_invested}")
        if self.current_value < 0:
            raise ValueError(f"Current value cannot be negative, got {self.current_value}")


@dataclass
class MFTransaction:
    """Mutual fund transaction record.

    Attributes:
        transaction_id: Transaction identifier
        scheme_code: Target scheme code
        transaction_type: Type of transaction
        amount: Transaction amount (₹)
        units: Units bought/sold
        nav: Applicable NAV
        transaction_date: Transaction date
        folio_no: Folio number
        order_placed_with: "AMC", "RTA", "broker"
        status: "PENDING", "COMPLETED", "FAILED"
        brokerage: Brokerage paid (₹)
        remarks: Additional remarks
    """
    transaction_id: str
    scheme_code: str
    transaction_type: MFTransactionType
    amount: float
    units: float
    nav: float
    transaction_date: date
    folio_no: str = ""
    order_placed_with: str = "broker"
    status: str = "COMPLETED"
    brokerage: float = 0.0
    remarks: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if not self.transaction_id:
            raise ValueError("Transaction ID cannot be empty")
        if self.amount < 0:
            raise ValueError(f"Amount cannot be negative, got {self.amount}")
        if self.units < 0:
            raise ValueError(f"Units cannot be negative, got {self.units}")
        if self.nav <= 0:
            raise ValueError(f"NAV must be positive, got {self.nav}")
        if self.status not in ("PENDING", "COMPLETED", "FAILED"):
            raise ValueError(f"Invalid status: {self.status}")


__all__ = [
    "DividendType",
    "ETF",
    "ExpenseRatioType",
    "FundCategory",
    "FundHolding",
    "FundOption",
    "FundPlan",
    "FundType",
    "InvIT",
    "MFTransaction",
    "MFTransactionType",
    "MutualFund",
    "NavRecord",
    "PortfolioAllocation",
    "REIT",
    "SIP",
    "SIPFrequency",
]
