"""
Fixed Income Domain Models - Core data structures for Indian fixed income.

Covers:
  - Government Securities (G-Sec) - Central Government dated securities
  - State Development Loans (SDL)
  - Treasury Bills (T-Bills) - 91-day, 182-day, 364-day
  - Corporate Bonds & Debentures (secured/unsecured)
  - Tax-Free Bonds
  - Sovereign Gold Bonds (SGB)
  - Fixed Deposit / Bond equivalent modeling
  - Accrued interest, yield calculations, duration, convexity

All models include __post_init__ validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class SecurityType(Enum):
    """Type of fixed income security."""
    GOVERNMENT_SECURITY = "gsec"            # Central Govt dated security
    STATE_DEVELOPMENT_LOAN = "sdl"          # State Govt security
    TREASURY_BILL = "tbill"                 # 91/182/364 day T-Bill
    CORPORATE_BOND = "corporate_bond"       # Corporate debenture/bond
    TAX_FREE_BOND = "tax_free_bond"         # Tax-free infrastructure bond
    SOVEREIGN_GOLD_BOND = "sgb"             # Sovereign Gold Bond
    MUNICIPAL_BOND = "municipal_bond"       # Municipal corporation bond
    CERTIFICATE_OF_DEPOSIT = "cd"           # Bank CD
    COMMERCIAL_PAPER = "cp"                 # Corporate CP


class YieldType(Enum):
    """Yield interpretation."""
    YTM = "ytm"              # Yield to Maturity
    CURRENT = "current"      # Current Yield
    YTC = "ytc"              # Yield to Call
    SPOT = "spot"            # Spot Yield
    PAR = "par"              # Par Yield


class AccrualBasis(Enum):
    """Day count convention for accrued interest."""
    ACTUAL_365 = "actual/365"            # G-Sec, Corporate Bonds
    ACTUAL_360 = "actual/360"            # Money market
    THIRTY_360 = "30/360"                # Some corporate bonds
    ACTUAL_ACTUAL = "actual/actual"      # Some G-Sec


@dataclass(frozen=True)
class CouponSchedule:
    """Coupon payment schedule for a fixed income security.

    Attributes:
        coupon_rate: Annual coupon rate (as decimal, e.g. 0.0725 for 7.25%)
        frequency: Coupon payment frequency per year (1=annual, 2=semi-annual)
        next_coupon_date: Next coupon payment date
        maturity_date: Final maturity date
        accrual_basis: Day count convention
        is_taxable: Whether coupon is taxable
    """
    coupon_rate: float
    frequency: int  # 1=annual, 2=semi-annual
    next_coupon_date: date | None = None
    maturity_date: date | None = None
    accrual_basis: AccrualBasis = AccrualBasis.ACTUAL_365
    is_taxable: bool = True

    def __post_init__(self) -> None:
        if self.coupon_rate < 0:
            raise ValueError(f"Coupon rate cannot be negative, got {self.coupon_rate}")
        if self.frequency not in (1, 2, 4, 12):
            raise ValueError(f"Frequency must be 1, 2, 4, or 12, got {self.frequency}")

    @property
    def coupon_per_period(self) -> float:
        """Coupon payment per period as decimal."""
        return self.coupon_rate / self.frequency


@dataclass
class Bond:
    """Generic fixed income bond/security representation.

    Attributes:
        symbol: ISIN or trading symbol
        name: Security name / description
        security_type: Type of fixed income security
        face_value: Face value of the bond (typically ₹100 for G-Sec)
        issue_date: Date of issuance
        maturity_date: Date of maturity
        coupon: Coupon schedule
        last_price: Latest traded price (clean price)
        accrued_interest: Accrued interest since last coupon
        yield_to_maturity: YTM as decimal (e.g. 0.0725)
        duration: Modified duration in years
        convexity: Convexity measure
        credit_rating: Credit rating (e.g. "AAA", "AA+")
        is_listed: Whether listed on exchange (BSE/NSE)
        is_taxable: Whether interest is taxable
        timestamp: Last update time
    """
    symbol: str
    name: str
    security_type: SecurityType
    face_value: float = 100.0
    issue_date: date | None = None
    maturity_date: date | None = None
    coupon: CouponSchedule | None = None
    last_price: float = 0.0
    accrued_interest: float = 0.0
    yield_to_maturity: float = 0.0
    duration: float = 0.0
    convexity: float = 0.0
    credit_rating: str = ""
    is_listed: bool = True
    is_taxable: bool = True
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def years_to_maturity(self) -> float:
        if not self.maturity_date:
            return 0.0
        delta = (self.maturity_date - date.today()).days
        return max(0.0, delta / 365.0)

    @property
    def dirty_price(self) -> float:
        """Clean price + accrued interest."""
        return self.last_price + self.accrued_interest

    @property
    def current_yield(self) -> float:
        """Current yield = annual coupon / dirty price."""
        if self.dirty_price <= 0 or not self.coupon:
            return 0.0
        annual_coupon = self.coupon.coupon_rate * self.face_value
        return annual_coupon / self.dirty_price

    def __post_init__(self) -> None:
        if self.face_value <= 0:
            raise ValueError(f"Face value must be positive, got {self.face_value}")
        if self.last_price < 0:
            raise ValueError(f"Last price cannot be negative, got {self.last_price}")
        if self.yield_to_maturity < 0:
            raise ValueError(f"YTM cannot be negative, got {self.yield_to_maturity}")
        if self.duration < 0:
            raise ValueError(f"Duration cannot be negative, got {self.duration}")


@dataclass
class GovernmentSecurity(Bond):
    """Government Security - Central Government dated security or SDL.

    Extends Bond with:
        - is_sdl: Whether this is a State Development Loan
        - state_name: State name for SDL
        - maturity_type: "dated" or "floating rate bond (FRB)"
    """
    is_sdl: bool = False
    state_name: str = ""
    maturity_type: str = "dated"  # "dated" or "frb"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.is_sdl and not self.state_name:
            raise ValueError("SDL must have a state_name")


@dataclass
class CorporateBond(Bond):
    """Corporate Bond / Debenture.

    Extends Bond with:
        - issuer: Issuer company name
        - issue_type: "secured" or "unsecured"
        - is_convertible: Whether convertible to equity
        - conversion_price: Conversion price for convertible bonds
        - call_date: Earliest call date
        - put_date: Earliest put date
    """
    issuer: str = ""
    issue_type: str = "secured"  # "secured" or "unsecured"
    is_convertible: bool = False
    conversion_price: float = 0.0
    call_date: date | None = None
    put_date: date | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.issue_type not in ("secured", "unsecured"):
            raise ValueError(f"Issue type must be 'secured' or 'unsecured', got {self.issue_type}")
        if self.is_convertible and self.conversion_price <= 0:
            raise ValueError("Convertible bonds must have a positive conversion price")


@dataclass
class TBill:
    """Treasury Bill - Short-term zero-coupon government security.

    Attributes:
        symbol: ISIN or symbol
        tenor_days: Tenor in days (91, 182, 364)
        issue_date: Issue date
        maturity_date: Maturity date
        face_value: Face value (typically ₹100)
        discounted_price: Discounted purchase price
        yield_discount: Discounted yield as decimal
        cut_off_price: Auction cut-off price
        bid_cover_ratio: Auction bid-cover ratio
    """
    symbol: str
    tenor_days: int  # 91, 182, or 364
    issue_date: date | None = None
    maturity_date: date | None = None
    face_value: float = 100.0
    discounted_price: float = 0.0
    yield_discount: float = 0.0
    cut_off_price: float = 0.0
    bid_cover_ratio: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def days_to_maturity(self) -> int:
        if not self.maturity_date:
            return 0
        delta = (self.maturity_date - date.today()).days
        return max(0, delta)

    @property
    def discount_amount(self) -> float:
        return self.face_value - self.discounted_price

    @property
    def annualized_yield(self) -> float:
        if self.discounted_price <= 0:
            return 0.0
        return (self.discount_amount / self.discounted_price) * (365 / self.tenor_days)

    def __post_init__(self) -> None:
        if self.tenor_days not in (91, 182, 364):
            raise ValueError(f"T-Bill tenor must be 91, 182, or 364, got {self.tenor_days}")
        if self.face_value <= 0:
            raise ValueError(f"Face value must be positive, got {self.face_value}")
        if self.discounted_price < 0:
            raise ValueError(f"Discounted price cannot be negative, got {self.discounted_price}")


@dataclass
class BondPosition:
    """Fixed income position tracking.

    Attributes:
        bond: The bond/security held
        quantity: Number of bonds held (+ve long, -ve short)
        average_price: Average purchase price (clean)
        current_price: Current market price (clean)
        accrued_interest: Accrued interest on this position
        unrealized_pnl: Mark-to-market P&L
        realized_pnl: Realized P&L from partial closes
        interest_income: Coupon interest income received
    """
    bond: Bond
    quantity: int
    average_price: float
    current_price: float
    accrued_interest: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    interest_income: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def investment_value(self) -> float:
        return self.quantity * self.average_price

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    def __post_init__(self) -> None:
        if self.average_price <= 0:
            raise ValueError(f"Average price must be positive, got {self.average_price}")
        if self.current_price < 0:
            raise ValueError(f"Current price cannot be negative, got {self.current_price}")


__all__ = [
    "AccrualBasis",
    "Bond",
    "BondPosition",
    "CorporateBond",
    "CouponSchedule",
    "GovernmentSecurity",
    "SecurityType",
    "TBill",
    "YieldType",
]
