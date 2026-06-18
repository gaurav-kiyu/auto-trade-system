"""
Currency Derivatives Domain Models - Core data structures for CDS/FX trading.

Covers:
  - USD/INR futures & options
  - EUR/INR, GBP/INR, JPY/INR
  - Contract specifications (lot size, tick size, expiry calendar)
  - Position tracking with margin
  - FX options (European-style, cash-settled)

All models include __post_init__ validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class CurrencyPair(Enum):
    """Reserve Bank of India (RBI) permitted currency pairs."""
    USD_INR = "USDINR"
    EUR_INR = "EURINR"
    GBP_INR = "GBPINR"
    JPY_INR = "JPYINR"


class SettlementType(Enum):
    """Settlement type for currency derivatives."""
    CASH_SETTLED = "cash"
    PHYSICAL = "physical"  # Not available in India for retail


class PositionType(Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass(frozen=True)
class ContractSpec:
    """Standardised contract specification for a currency derivative.

    Attributes:
        pair: Currency pair (e.g. USD/INR)
        exchange: Exchange (CDS, BSE-CDS)
        lot_size: Number of units per contract
        tick_size: Minimum price movement
        tick_value: Rupee value per tick
        expiry_day: Day of week for monthly expiry (typically Tuesday)
        is_futures: True for futures, False for options
        strike_interval: Strike interval for options (in paise)
        freeze_qty: Freeze quantity (max order qty)
        price_band_pct: Daily price band percentage
        margin_pct: Initial margin as percentage
    """
    pair: CurrencyPair
    exchange: str  # "CDS", "BSE-CDS"
    lot_size: int
    tick_size: float
    tick_value: float
    expiry_day: int = 1  # Tuesday for USD/INR
    is_futures: bool = True
    strike_interval: float = 0.25  # 25 paise for USD/INR options
    freeze_qty: int = 0
    price_band_pct: float = 5.0
    margin_pct: float = 2.0

    def __post_init__(self) -> None:
        if self.lot_size <= 0:
            raise ValueError(f"Lot size must be positive, got {self.lot_size}")
        if self.tick_size <= 0:
            raise ValueError(f"Tick size must be positive, got {self.tick_size}")
        if self.price_band_pct <= 0:
            raise ValueError(f"Price band must be positive, got {self.price_band_pct}")


# ── Common currency contract specifications ─────────────────────────────

CURRENCY_CONTRACT_SPECS: dict[str, ContractSpec] = {
    "USDINR": ContractSpec(
        pair=CurrencyPair.USD_INR, exchange="CDS",
        lot_size=1000, tick_size=0.0025, tick_value=2.5,
        strike_interval=0.25, freeze_qty=12000, margin_pct=2.0,
    ),
    "EURINR": ContractSpec(
        pair=CurrencyPair.EUR_INR, exchange="CDS",
        lot_size=1000, tick_size=0.0025, tick_value=2.5,
        strike_interval=0.25, freeze_qty=12000, margin_pct=3.0,
    ),
    "GBPINR": ContractSpec(
        pair=CurrencyPair.GBP_INR, exchange="CDS",
        lot_size=1000, tick_size=0.0025, tick_value=2.5,
        strike_interval=0.25, freeze_qty=12000, margin_pct=3.0,
    ),
    "JPYINR": ContractSpec(
        pair=CurrencyPair.JPY_INR, exchange="CDS",
        lot_size=100000, tick_size=0.0025, tick_value=2.5,
        strike_interval=0.25, freeze_qty=12000, margin_pct=3.0,
    ),
}


@dataclass
class CurrencyContract:
    """A currency futures contract on the NSE Currency Derivatives Segment.

    Attributes:
        pair: Currency pair (e.g. USD/INR)
        expiry: Contract expiry date
        contract_spec: Standardised contract specification
        last_price: Latest traded price (in INR per foreign currency)
        open_interest: Open interest (number of contracts)
        change_oi: Change in OI from previous session
        forward_points: Forward premium/discount
        rbi_reference_rate: RBI reference rate for the pair
    """
    pair: CurrencyPair
    expiry: date
    contract_spec: ContractSpec | None = None
    last_price: float = 0.0
    open_interest: int = 0
    change_oi: int = 0
    forward_points: float = 0.0
    rbi_reference_rate: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def days_to_expiry(self) -> int:
        delta = (self.expiry - date.today()).days
        return max(0, delta)

    @property
    def notional_value(self) -> float:
        lot = self.contract_spec.lot_size if self.contract_spec else 1
        return self.last_price * lot

    def __post_init__(self) -> None:
        if self.last_price < 0:
            raise ValueError(f"Last price cannot be negative, got {self.last_price}")
        if self.open_interest < 0:
            raise ValueError(f"Open interest cannot be negative, got {self.open_interest}")


@dataclass
class CurrencyOptionContract:
    """A currency option contract (European-style, cash-settled).

    Attributes:
        pair: Currency pair (e.g. USD/INR)
        option_type: "CE" for Call, "PE" for Put
        strike: Strike price in INR per foreign currency
        expiry: Expiry date
        contract_spec: Standardised contract specification
        last_price: Latest traded premium
        implied_vol: Implied volatility
        delta: Option delta
        gamma: Option gamma
        theta: Option theta (daily)
        vega: Option vega
        spot_price: Current spot rate
    """
    pair: CurrencyPair
    option_type: str  # "CE" or "PE"
    strike: float
    expiry: date
    contract_spec: ContractSpec | None = None
    last_price: float = 0.0
    implied_vol: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    spot_price: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_call(self) -> bool:
        return self.option_type.upper() == "CE"

    @property
    def is_put(self) -> bool:
        return self.option_type.upper() == "PE"

    @property
    def days_to_expiry(self) -> int:
        delta = (self.expiry - date.today()).days
        return max(0, delta)

    def __post_init__(self) -> None:
        if self.option_type.upper() not in ("CE", "PE"):
            raise ValueError(f"Option type must be 'CE' or 'PE', got {self.option_type}")
        if self.strike <= 0:
            raise ValueError(f"Strike must be positive, got {self.strike}")
        if self.last_price < 0:
            raise ValueError(f"Last price cannot be negative, got {self.last_price}")


@dataclass
class CurrencyPosition:
    """Open currency derivative position tracking.

    Attributes:
        contract: The currency futures contract
        quantity: Position quantity (+ve long, -ve short)
        average_price: Average entry price
        current_price: Current market price
        unrealized_pnl: Mark-to-market P&L
        realized_pnl: Realized P&L from partial closes
        margin_used: Margin blocked for this position
    """
    contract: CurrencyContract
    quantity: int
    average_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    margin_used: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def position_type(self) -> PositionType:
        if self.quantity > 0:
            return PositionType.LONG
        elif self.quantity < 0:
            return PositionType.SHORT
        return PositionType.FLAT

    def __post_init__(self) -> None:
        if self.average_price <= 0:
            raise ValueError(f"Average price must be positive, got {self.average_price}")
        if self.current_price <= 0:
            raise ValueError(f"Current price must be positive, got {self.current_price}")


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
