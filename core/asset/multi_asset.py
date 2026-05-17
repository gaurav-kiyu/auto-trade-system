"""
Multi-Asset Architecture - Item 26

Support multiple asset classes:
- equities
- futures
- options
- commodities
- FX

Abstraction layer for future asset expansion.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)


class AssetClass(Enum):
    """Asset class types"""
    EQUITY = "EQUITY"
    FUTURES = "FUTURES"
    OPTIONS = "OPTIONS"
    COMMODITIES = "COMMODITIES"
    FOREX = "FOREX"
    INDEX = "INDEX"


class AssetCategory(Enum):
    """Asset categories"""
    EQUITY_STOCK = "EQUITY_STOCK"
    EQUITY_ETF = "EQUITY_ETF"
    FUTURES_INDEX = "FUTURES_INDEX"
    FUTURES_COMMODITY = "FUTURES_COMMODITY"
    OPTIONS_INDEX = "OPTIONS_INDEX"
    OPTIONS_STOCK = "OPTIONS_STOCK"
    COMMODITY_GOLD = "COMMODITY_GOLD"
    COMMODITY_SILVER = "COMMODITY_SILVER"
    FOREX_CURRENCY = "FOREX_CURRENCY"


@dataclass
class AssetDefinition:
    """Asset definition"""
    symbol: str
    asset_class: AssetClass
    category: AssetCategory
    name: str
    exchange: str
    lot_size: int
    tick_size: float
    currency: str = "INR"


@dataclass
class AssetInfo:
    """Asset information"""
    symbol: str
    last_price: float
    bid: float
    ask: float
    volume: int
    open_interest: int = 0
    timestamp: str = ""


class MultiAssetManager:
    """
    Multi-asset management.
    Handles trading across different asset classes.
    """

    def __init__(self):
        self._assets: dict[str, AssetDefinition] = {}
        self._asset_handlers: dict[AssetClass, Any] = {}
        self._lock = threading.Lock()

        self._register_default_assets()

    def _register_default_assets(self) -> None:
        """Register default asset definitions"""
        default_assets = [
            AssetDefinition("NIFTY", AssetClass.INDEX, AssetCategory.OPTIONS_INDEX, "Nifty 50", "NSE", 50, 0.05),
            AssetDefinition("BANKNIFTY", AssetClass.INDEX, AssetCategory.OPTIONS_INDEX, "Bank Nifty", "NSE", 25, 0.05),
            AssetDefinition("FINNIFTY", AssetClass.INDEX, AssetCategory.OPTIONS_INDEX, "Finnifty", "NSE", 40, 0.05),
            AssetDefinition("RELIANCE", AssetClass.EQUITY, AssetCategory.EQUITY_STOCK, "Reliance Industries", "NSE", 1, 0.05),
            AssetDefinition("ICICI", AssetClass.EQUITY, AssetCategory.EQUITY_STOCK, "ICICI Bank", "NSE", 1, 0.05),
            AssetDefinition("GOLD", AssetClass.COMMODITIES, AssetCategory.COMMODITY_GOLD, "Gold", "MCX", 1, 0.01),
            AssetDefinition("SILVER", AssetClass.COMMODITIES, AssetCategory.COMMODITY_SILVER, "Silver", "MCX", 1, 0.01),
        ]

        for asset in default_assets:
            self._assets[asset.symbol] = asset

    def register_asset(self, asset: AssetDefinition) -> None:
        """Register new asset"""
        with self._lock:
            self._assets[asset.symbol] = asset
            _log.info(f"Registered asset: {asset.symbol} ({asset.asset_class.value})")

    def get_asset(self, symbol: str) -> AssetDefinition | None:
        """Get asset definition"""
        return self._assets.get(symbol)

    def get_assets_by_class(self, asset_class: AssetClass) -> list[AssetDefinition]:
        """Get all assets of a specific class"""
        with self._lock:
            return [a for a in self._assets.values() if a.asset_class == asset_class]

    def is_supported(self, symbol: str) -> bool:
        """Check if asset is supported"""
        return symbol in self._assets

    def get_asset_class(self, symbol: str) -> AssetClass | None:
        """Get asset class for symbol"""
        asset = self.get_asset(symbol)
        return asset.asset_class if asset else None

    def get_margin_requirement(self, symbol: str, quantity: int, price: float) -> float:
        """Calculate margin requirement"""
        asset = self.get_asset(symbol)
        if not asset:
            return price * quantity

        margin_rates = {
            AssetClass.EQUITY: 0.20,
            AssetClass.INDEX: 0.10,
            AssetClass.OPTIONS: 0.15,
            AssetClass.FUTURES: 0.12,
            AssetClass.COMMODITIES: 0.15,
            AssetClass.FOREX: 0.10,
        }

        rate = margin_rates.get(asset.asset_class, 0.20)
        return price * quantity * rate

    def get_assets_summary(self) -> dict[str, Any]:
        """Get summary of all assets"""
        with self._lock:
            by_class = {}
            for asset in self._assets.values():
                class_name = asset.asset_class.value
                if class_name not in by_class:
                    by_class[class_name] = []
                by_class[class_name].append(asset.symbol)

            return {
                "total_assets": len(self._assets),
                "by_class": by_class,
            }


_asset_manager: MultiAssetManager | None = None
_manager_lock = threading.Lock()


def get_multi_asset_manager() -> MultiAssetManager:
    """Get singleton multi-asset manager"""
    global _asset_manager
    with _manager_lock:
        if _asset_manager is None:
            _asset_manager = MultiAssetManager()
        return _asset_manager
