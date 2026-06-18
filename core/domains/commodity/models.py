"""
Commodity Derivatives Domain Models - Core data structures for MCX/CCOM trading.

Covers:
  - Bullion (Gold, Silver) - spot & futures
  - Energy (Crude Oil, Natural Gas)
  - Base Metals (Copper, Zinc, Aluminium, Lead, Nickel)
  - Agricultural commodities
  - Contract specifications (lot size, tick size, expiry calendar)
  - Position tracking with margin requirements

All models include __post_init__ validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class CommodityCategory(Enum):
    """Category of commodity for MCX/CCOM trading."""
    BULLION = "bullion"                  # Gold, Silver
    ENERGY = "energy"                    # Crude Oil, Natural Gas
    BASE_METAL = "base_metal"            # Copper, Zinc, Aluminium, Lead, Nickel
    PRECIOUS_METAL = "precious_metal"    # Gold Mini, Silver Micro
    AGRI = "agri"                        # Cotton, Guar Seed, etc.
    OTHER = "other"


class DeliveryType(Enum):
    """Delivery settlement type for commodity contracts."""
    PHYSICAL = "physical"        # Actual delivery
    CASH_SETTLED = "cash"        # Cash settlement
    COMPULSORY_DELIVERY = "compulsory"


class PositionType(Enum):
    """Position classification."""
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass(frozen=True)
class ContractSpec:
    """Standardised contract specification for a commodity derivative.

    Attributes:
        symbol: Trading symbol (e.g. "GOLD", "CRUDEOIL")
        exchange: Exchange (MCX, CCOM)
        category: Commodity category
        lot_size: Number of units per contract
        tick_size: Minimum price movement
        tick_value: Rupee value per tick
        expiry_day: Day of month for expiry
        delivery_type: Physical or cash settlement
        freeze_qty: Freeze quantity (max order qty)
        price_band_pct: Daily price band percentage
        margin_pct: Initial margin as percentage
    """
    symbol: str
    exchange: str  # "MCX", "CCOM"
    category: CommodityCategory
    lot_size: int
    tick_size: float
    tick_value: float
    expiry_day: int = 0  # 0 = Last trading day of month
    delivery_type: DeliveryType = DeliveryType.CASH_SETTLED
    freeze_qty: int = 0
    price_band_pct: float = 10.0
    margin_pct: float = 5.0

    def __post_init__(self) -> None:
        if self.lot_size <= 0:
            raise ValueError(f"Lot size must be positive, got {self.lot_size}")
        if self.tick_size <= 0:
            raise ValueError(f"Tick size must be positive, got {self.tick_size}")
        if self.price_band_pct <= 0:
            raise ValueError(f"Price band must be positive, got {self.price_band_pct}")
        if self.margin_pct <= 0:
            raise ValueError(f"Margin percentage must be positive, got {self.margin_pct}")


# ── Common MCX contract specifications ─────────────────────────────────

MCX_CONTRACT_SPECS: dict[str, ContractSpec] = {
    "GOLD": ContractSpec(
        symbol="GOLD", exchange="MCX", category=CommodityCategory.BULLION,
        lot_size=1, tick_size=1.0, tick_value=1.0, delivery_type=DeliveryType.PHYSICAL,
        freeze_qty=600, price_band_pct=5.0, margin_pct=5.0,
    ),
    "GOLDM": ContractSpec(
        symbol="GOLDM", exchange="MCX", category=CommodityCategory.PRECIOUS_METAL,
        lot_size=10, tick_size=0.1, tick_value=1.0, delivery_type=DeliveryType.CASH_SETTLED,
        freeze_qty=6000, price_band_pct=5.0, margin_pct=5.0,
    ),
    "SILVER": ContractSpec(
        symbol="SILVER", exchange="MCX", category=CommodityCategory.BULLION,
        lot_size=30, tick_size=0.1, tick_value=3.0, delivery_type=DeliveryType.PHYSICAL,
        freeze_qty=600, price_band_pct=5.0, margin_pct=7.0,
    ),
    "SILVERM": ContractSpec(
        symbol="SILVERM", exchange="MCX", category=CommodityCategory.PRECIOUS_METAL,
        lot_size=1, tick_size=0.1, tick_value=0.1, delivery_type=DeliveryType.CASH_SETTLED,
        freeze_qty=6000, price_band_pct=5.0, margin_pct=7.0,
    ),
    "CRUDEOIL": ContractSpec(
        symbol="CRUDEOIL", exchange="MCX", category=CommodityCategory.ENERGY,
        lot_size=100, tick_size=1.0, tick_value=100.0, delivery_type=DeliveryType.CASH_SETTLED,
        freeze_qty=600, price_band_pct=5.0, margin_pct=8.0,
    ),
    "NATURALGAS": ContractSpec(
        symbol="NATURALGAS", exchange="MCX", category=CommodityCategory.ENERGY,
        lot_size=1250, tick_size=0.1, tick_value=125.0, delivery_type=DeliveryType.CASH_SETTLED,
        freeze_qty=600, price_band_pct=5.0, margin_pct=8.0,
    ),
    "COPPER": ContractSpec(
        symbol="COPPER", exchange="MCX", category=CommodityCategory.BASE_METAL,
        lot_size=1, tick_size=0.05, tick_value=0.05, delivery_type=DeliveryType.CASH_SETTLED,
        freeze_qty=6000, price_band_pct=4.0, margin_pct=5.0,
    ),
    "ZINC": ContractSpec(
        symbol="ZINC", exchange="MCX", category=CommodityCategory.BASE_METAL,
        lot_size=5, tick_size=0.05, tick_value=0.25, delivery_type=DeliveryType.CASH_SETTLED,
        freeze_qty=6000, price_band_pct=4.0, margin_pct=5.0,
    ),
    "ALUMINIUM": ContractSpec(
        symbol="ALUMINIUM", exchange="MCX", category=CommodityCategory.BASE_METAL,
        lot_size=5, tick_size=0.05, tick_value=0.25, delivery_type=DeliveryType.CASH_SETTLED,
        freeze_qty=6000, price_band_pct=4.0, margin_pct=5.0,
    ),
}


@dataclass
class CommodityContract:
    """A commodity futures contract on MCX/CCOM.

    Attributes:
        symbol: Trading symbol (e.g. "GOLD", "CRUDEOIL")
        expiry: Contract expiry date
        contract_spec: Standardised contract specification
        last_price: Latest traded price
        open_interest: Open interest (number of contracts)
        change_oi: Change in OI from previous session
        basis: Difference between futures and spot price
    """
    symbol: str
    expiry: date
    contract_spec: ContractSpec | None = None
    last_price: float = 0.0
    open_interest: int = 0
    change_oi: int = 0
    basis: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def days_to_expiry(self) -> int:
        delta = (self.expiry - date.today()).days
        return max(0, delta)

    @property
    def notional_value(self) -> float:
        lot = self.contract_spec.lot_size if self.contract_spec else 1
        return self.last_price * lot

    @property
    def margin_required(self) -> float:
        if not self.contract_spec:
            return 0.0
        return self.notional_value * self.contract_spec.margin_pct / 100.0

    def __post_init__(self) -> None:
        if self.last_price < 0:
            raise ValueError(f"Last price cannot be negative, got {self.last_price}")
        if self.open_interest < 0:
            raise ValueError(f"Open interest cannot be negative, got {self.open_interest}")


@dataclass
class CommodityPosition:
    """Open commodity futures position tracking.

    Attributes:
        contract: The commodity contract details
        quantity: Position quantity (+ve long, -ve short)
        average_price: Average entry price
        current_price: Current market price
        unrealized_pnl: Mark-to-market P&L
        realized_pnl: Realized P&L from partial closes
        margin_used: Margin blocked for this position
        mtm_value: Current mark-to-market value
    """
    contract: CommodityContract
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
        return self.quantity * (self.current_price - self.average_price)

    def __post_init__(self) -> None:
        if self.average_price <= 0:
            raise ValueError(f"Average price must be positive, got {self.average_price}")
        if self.current_price <= 0:
            raise ValueError(f"Current price must be positive, got {self.current_price}")


__all__ = [
    "CommodityCategory",
    "CommodityContract",
    "CommodityPosition",
    "ContractSpec",
    "DeliveryType",
    "MCX_CONTRACT_SPECS",
    "PositionType",
]
