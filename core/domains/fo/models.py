"""
Futures & Options Domain Models - Core data structures for equity derivatives.

Covers:
  - Index Futures (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX)
  - Stock Futures (RELIANCE, TCS, HDFCBANK, etc.)
  - Index Options (CE/PE)
  - Stock Options (CE/PE)
  - Contract specifications (lot size, tick size, expiry calendar)
  - Spread positions (calendar, vertical, inter-commodity)
  - Greeks tracking for option positions

All models include __post_init__ validation and follow the same
pattern as existing domain models in core/domains/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class UnderlyingType(Enum):
    """Type of underlying asset for F&O contracts."""
    INDEX = "index"
    EQUITY = "equity"
    COMMODITY = "commodity"
    CURRENCY = "currency"


class ExpiryType(Enum):
    """Expiry type for derivative contracts."""
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    HALF_YEARLY = "half_yearly"


class PositionType(Enum):
    """Position classification."""
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class SpreadType(Enum):
    """Types of spread positions."""
    VERTICAL = "vertical"                # Same expiry, different strikes
    CALENDAR = "calendar"                # Different expiries, same strike
    DIAGONAL = "diagonal"                # Different expiries and strikes
    BOX = "box"                          # Box spread
    IRON_CONDOR = "iron_condor"          # Iron Condor
    IRON_BUTTERFLY = "iron_butterfly"    # Iron Butterfly
    STRANGLE = "strangle"                # OTM Call + OTM Put
    STRADDLE = "straddle"                # ATM Call + ATM Put
    CUSTOM = "custom"                    # User-defined


@dataclass(frozen=True)
class ContractSpec:
    """Standardised contract specification for an F&O instrument.

    Attributes:
        symbol: Trading symbol (e.g. "NIFTY", "RELIANCE")
        exchange: Exchange (NFO, BFO)
        underlying_type: Type of underlying (index, equity)
        lot_size: Number of units per contract
        tick_size: Minimum price movement
        expiry_day: Day of week for weekly expiry (e.g. 3 = Thursday)
        monthly_expiry_day: Day of month for monthly expiry
        strike_interval: Interval between strike prices
        max_strikes_otm: Maximum OTM strikes from ATM
        freeze_qty: Freeze quantity (max order qty)
        price_band_pct: Daily price band percentage
    """
    symbol: str
    exchange: str  # "NFO", "BFO"
    underlying_type: UnderlyingType
    lot_size: int
    tick_size: float
    expiry_day: int = 3  # Thursday for NIFTY/BANKNIFTY
    monthly_expiry_day: int = 0  # Last trading day of month
    strike_interval: float = 50.0  # NIFTY default
    max_strikes_otm: int = 20
    freeze_qty: int = 0  # 0 = no freeze limit
    price_band_pct: float = 10.0

    def __post_init__(self) -> None:
        if self.lot_size <= 0:
            raise ValueError(f"Lot size must be positive, got {self.lot_size}")
        if self.tick_size <= 0:
            raise ValueError(f"Tick size must be positive, got {self.tick_size}")
        if self.strike_interval <= 0:
            raise ValueError(f"Strike interval must be positive, got {self.strike_interval}")
        if self.price_band_pct <= 0:
            raise ValueError(f"Price band must be positive, got {self.price_band_pct}")


# ── Common F&O contract specifications for NSE indices ────────────────

NFO_CONTRACT_SPECS: dict[str, ContractSpec] = {
    "NIFTY": ContractSpec(
        symbol="NIFTY", exchange="NFO", underlying_type=UnderlyingType.INDEX,
        lot_size=50, tick_size=0.05, expiry_day=3, strike_interval=50.0,
        max_strikes_otm=16, freeze_qty=7200, price_band_pct=10.0,
    ),
    "BANKNIFTY": ContractSpec(
        symbol="BANKNIFTY", exchange="NFO", underlying_type=UnderlyingType.INDEX,
        lot_size=15, tick_size=0.05, expiry_day=3, strike_interval=100.0,
        max_strikes_otm=16, freeze_qty=3600, price_band_pct=10.0,
    ),
    "FINNIFTY": ContractSpec(
        symbol="FINNIFTY", exchange="NFO", underlying_type=UnderlyingType.INDEX,
        lot_size=40, tick_size=0.05, expiry_day=2, strike_interval=50.0,
        max_strikes_otm=16, freeze_qty=6000, price_band_pct=10.0,
    ),
    "MIDCPNIFTY": ContractSpec(
        symbol="MIDCPNIFTY", exchange="NFO", underlying_type=UnderlyingType.INDEX,
        lot_size=75, tick_size=0.05, expiry_day=3, strike_interval=25.0,
        max_strikes_otm=12, freeze_qty=6000, price_band_pct=10.0,
    ),
    "SENSEX": ContractSpec(
        symbol="SENSEX", exchange="BFO", underlying_type=UnderlyingType.INDEX,
        lot_size=10, tick_size=0.05, expiry_day=3, strike_interval=100.0,
        max_strikes_otm=16, freeze_qty=1800, price_band_pct=10.0,
    ),
}


@dataclass
class FutureContract:
    """An equity index or stock futures contract.

    Attributes:
        symbol: Underlying symbol (e.g. "NIFTY", "RELIANCE")
        expiry: Contract expiry date
        contract_spec: Standardised contract specification
        last_price: Latest traded price
        open_interest: Open interest (number of contracts)
        change_oi: Change in OI from previous session
        premium_discount: Premium/discount to spot in points
    """
    symbol: str
    expiry: date
    contract_spec: ContractSpec | None = None
    last_price: float = 0.0
    open_interest: int = 0
    change_oi: int = 0
    premium_discount: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def days_to_expiry(self) -> int:
        """Days remaining until contract expiry."""
        delta = (self.expiry - date.today()).days
        return max(0, delta)

    @property
    def notional_value(self) -> float:
        """Notional contract value = last_price * lot_size."""
        lot = self.contract_spec.lot_size if self.contract_spec else 1
        return self.last_price * lot

    def __post_init__(self) -> None:
        if self.last_price < 0:
            raise ValueError(f"Last price cannot be negative, got {self.last_price}")
        if self.open_interest < 0:
            raise ValueError(f"Open interest cannot be negative, got {self.open_interest}")


@dataclass
class OptionContract:
    """An equity index or stock option contract (Call/Put).

    Attributes:
        symbol: Underlying symbol (e.g. "NIFTY", "RELIANCE")
        option_type: "CE" for Call, "PE" for Put
        strike: Strike price
        expiry: Expiry date
        contract_spec: Standardised contract specification
        last_price: Latest traded premium
        bid: Best bid price
        ask: Best ask price
        open_interest: Open interest
        change_oi: Change in OI
        implied_vol: Implied volatility
        delta: Option delta
        gamma: Option gamma
        theta: Option theta (daily)
        vega: Option vega
        rho: Option rho
        intrinsic_value: Intrinsic value (max(0, spot-strike) for CE)
        time_value: Premium - intrinsic value
    """
    symbol: str
    option_type: str  # "CE" or "PE"
    strike: float
    expiry: date
    contract_spec: ContractSpec | None = None

    # Market data
    last_price: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    open_interest: int = 0
    change_oi: int = 0
    volume: int = 0
    implied_vol: float = 0.0

    # Greeks
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0

    # Derived
    intrinsic_value: float = 0.0
    time_value: float = 0.0
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

    @property
    def moneyness(self) -> str:
        """Classify option moneyness: ITM, ATM, OTM."""
        if self.spot_price <= 0 or self.strike <= 0:
            return "UNKNOWN"
        if self.is_call:
            ratio = self.spot_price / self.strike
            if ratio > 1.02:
                return "ITM"
            elif ratio < 0.98:
                return "OTM"
            return "ATM"
        else:
            ratio = self.strike / self.spot_price
            if ratio > 1.02:
                return "ITM"
            elif ratio < 0.98:
                return "OTM"
            return "ATM"

    @property
    def bid_ask_spread_pct(self) -> float:
        """Bid-ask spread as percentage of mid price."""
        if self.bid <= 0 or self.ask <= 0:
            return 0.0
        mid = (self.bid + self.ask) / 2.0
        if mid <= 0:
            return 0.0
        return (self.ask - self.bid) / mid * 100.0

    def __post_init__(self) -> None:
        if self.option_type.upper() not in ("CE", "PE"):
            raise ValueError(f"Option type must be 'CE' or 'PE', got {self.option_type}")
        if self.strike <= 0:
            raise ValueError(f"Strike must be positive, got {self.strike}")
        if self.last_price < 0:
            raise ValueError(f"Last price cannot be negative, got {self.last_price}")


@dataclass
class FuturePosition:
    """Open futures position tracking.

    Attributes:
        contract: The futures contract details
        quantity: Position quantity (+ve long, -ve short)
        average_price: Average entry price
        current_price: Current market price
        unrealized_pnl: Mark-to-market P&L
        realized_pnl: Realized P&L from partial closes
        margin_used: Margin blocked for this position
        mtm_value: Current mark-to-market value
    """
    contract: FutureContract
    quantity: int
    average_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    margin_used: float = 0.0
    mtm_value: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def position_type(self) -> PositionType:
        if self.quantity > 0:
            return PositionType.LONG
        elif self.quantity < 0:
            return PositionType.SHORT
        return PositionType.FLAT

    @property
    def pnl_points(self) -> float:
        """P&L in index/stock points."""
        return self.quantity * (self.current_price - self.average_price)

    def __post_init__(self) -> None:
        if self.average_price <= 0:
            raise ValueError(f"Average price must be positive, got {self.average_price}")
        if self.current_price <= 0:
            raise ValueError(f"Current price must be positive, got {self.current_price}")


@dataclass
class OptionPosition:
    """Open option position tracking.

    Attributes:
        contract: The option contract details
        quantity: Position quantity (+ve long, -ve short)
        average_price: Average entry premium
        current_price: Current market premium
        unrealized_pnl: Mark-to-market P&L
        realized_pnl: Realized P&L
        premium_paid: Total premium paid/received
        delta_exposure: Delta * quantity * lot_size
        gamma_exposure: Gamma * quantity * lot_size
        theta_decay: Daily theta decay in INR
    """
    contract: OptionContract
    quantity: int
    average_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    premium_paid: float = 0.0
    delta_exposure: float = 0.0
    gamma_exposure: float = 0.0
    theta_decay: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def position_type(self) -> PositionType:
        if self.quantity > 0:
            return PositionType.LONG
        elif self.quantity < 0:
            return PositionType.SHORT
        return PositionType.FLAT

    @property
    def is_long_option(self) -> bool:
        """True if this is a long option position (buyer)."""
        return self.quantity > 0

    @property
    def is_short_option(self) -> bool:
        """True if this is a short option position (seller/writer)."""
        return self.quantity < 0

    def __post_init__(self) -> None:
        if self.average_price <= 0:
            raise ValueError(f"Average price must be positive, got {self.average_price}")
        if self.current_price <= 0:
            raise ValueError(f"Current price must be positive, got {self.current_price}")


@dataclass
class SpreadLeg:
    """A single leg of a multi-leg spread strategy.

    Attributes:
        leg_id: Leg identifier (1, 2, 3, 4)
        option_contract: The option for this leg
        quantity: Quantity for this leg
        action: "BUY" or "SELL"
        ratio: Ratio relative to leg 1 (e.g. 1:1, 1:2, etc.)
    """
    leg_id: int
    option_contract: OptionContract
    quantity: int
    action: str  # "BUY" or "SELL"
    ratio: float = 1.0

    def __post_init__(self) -> None:
        if self.action.upper() not in ("BUY", "SELL"):
            raise ValueError(f"Action must be 'BUY' or 'SELL', got {self.action}")
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {self.quantity}")
        if self.ratio <= 0:
            raise ValueError(f"Ratio must be positive, got {self.ratio}")


@dataclass
class SpreadPosition:
    """Multi-leg spread strategy position.

    Supports all spread types:
    - Vertical spreads (Bull Call/Bear Put/Put)
    - Calendar/Time spreads
    - Iron Condors (4-leg)
    - Iron Butterflies (4-leg)
    - Straddles (2-leg)
    - Strangles (2-leg)
    - Custom (any combination)

    Attributes:
        spread_type: Type of spread
        legs: List of spread legs
        net_premium: Net premium paid (positive) or received (negative)
        max_profit: Maximum potential profit
        max_loss: Maximum potential loss
        upper_breakeven: Upper breakeven point
        lower_breakeven: Lower breakeven point (for undefined risk spreads)
        current_pnl: Current P&L
        margin_required: Margin blocked for this spread
    """
    spread_type: SpreadType
    legs: list[SpreadLeg]
    net_premium: float = 0.0
    max_profit: float = 0.0
    max_loss: float = 0.0
    upper_breakeven: float = 0.0
    lower_breakeven: float = 0.0
    current_pnl: float = 0.0
    margin_required: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def num_legs(self) -> int:
        return len(self.legs)

    @property
    def is_credit_spread(self) -> bool:
        """True if net premium is received (credit spread)."""
        return self.net_premium < 0

    @property
    def is_debit_spread(self) -> bool:
        """True if net premium is paid (debit spread)."""
        return self.net_premium > 0

    @property
    def risk_reward_ratio(self) -> float:
        """Risk-reward ratio for the spread."""
        if self.max_loss <= 0:
            return 0.0
        return abs(self.max_profit / self.max_loss)

    def __post_init__(self) -> None:
        if not self.legs:
            raise ValueError("Spread must have at least one leg")


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
