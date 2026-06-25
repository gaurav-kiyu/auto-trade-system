"""Multi-Asset Market Data Service - aggregator with automatic failover.

Provides a unified entry point for all market data across equity, F&O,
commodity, currency, fixed income, and WebSocket feeds.

Architecture
------------
The ``MarketDataService`` holds a registry of ``MarketDataPort`` adapters,
each tagged with an asset-type label and priority.  When data is requested
for a given asset class, the service tries adapters in priority order (highest
first) and falls back if the primary adapter returns no data.

Priority scheme
---------------
    100   - WebSocket / real-time feed (lowest latency)
     50   - Broker API / exchange adapter
     10   - RESTful fallback (yfinance, NSE API, etc.)

Usage
-----
    service = MarketDataService()
    service.register("kite_ws", nse_ws_adapter, asset_classes=["equity", "index"], priority=100)
    service.register("yf_nse", yf_adapter, asset_classes=["equity", "index"], priority=10)

    quote = service.get_quote("NIFTY", asset_class="index")  # tries WS first, falls back to yf
    hist  = service.get_historical_data("NIFTY", from_date, to_date)
"""

from __future__ import annotations

import logging

__all__ = [
    "AdapterEntry",
    "MarketDataService",
]
from collections import defaultdict
from datetime import datetime
from typing import Any

from core.ports.market_data import MarketDataPort, MarketDataProvider

_log = logging.getLogger(__name__)


class AdapterEntry:
    """A registered adapter with its asset-class scope and priority."""

    __slots__ = ("name", "adapter", "asset_classes", "priority", "_connected")

    def __init__(
        self,
        name: str,
        adapter: MarketDataPort,
        asset_classes: list[str] | None = None,
        priority: int = 10,
    ):
        self.name = name
        self.adapter = adapter
        self.asset_classes = set(asset_classes or [])
        self.priority = priority
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @connected.setter
    def connected(self, value: bool) -> None:
        self._connected = value


class MarketDataService:
    """Aggregated market data service with automatic failover across adapters.

    Adapters are registered by name with an asset-class label and priority.
    When data is requested, adapters matching the requested asset class are
    tried in descending priority order until one returns usable data.
    """

    def __init__(self):
        # Registry: asset_class -> list of AdapterEntry sorted by priority desc
        self._by_asset: dict[str, list[AdapterEntry]] = defaultdict(list)
        # Flat lookup by name
        self._by_name: dict[str, AdapterEntry] = {}

    # ── Registration ─────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        adapter: MarketDataPort,
        asset_classes: list[str] | None = None,
        priority: int = 10,
    ) -> None:
        """Register an adapter for one or more asset classes.

        Args:
            name: Unique name for this adapter (e.g. ``"kite_ws"``, ``"yf_nse"``).
            adapter: The ``MarketDataPort`` implementation.
            asset_classes: List of asset class labels this adapter covers.
                           Common labels: ``equity``, ``index``, ``commodity``,
                           ``currency``, ``fo``, ``fixed_income``.
            priority: Higher = tried first.  100=real-time, 50=broker, 10=REST.
        """
        entry = AdapterEntry(name, adapter, asset_classes, priority)
        self._by_name[name] = entry

        for ac in entry.asset_classes:
            self._by_asset[ac].append(entry)
            # Keep list sorted by priority descending so highest is tried first
            self._by_asset[ac].sort(key=lambda e: e.priority, reverse=True)

        _log.info(
            "[MDS] registered adapter %s for %s (priority=%d)",
            name, asset_classes, priority,
        )

    def unregister(self, name: str) -> None:
        """Remove a previously registered adapter by name."""
        entry = self._by_name.pop(name, None)
        if entry is None:
            return
        for ac in entry.asset_classes:
            self._by_asset[ac] = [e for e in self._by_asset[ac] if e.name != name]

    def get_entries_for(self, asset_class: str) -> list[AdapterEntry]:
        """Return all adapter entries for an asset class in priority order."""
        return list(self._by_asset.get(asset_class, []))

    def get_adapters_for(self, asset_class: str) -> list[MarketDataPort]:
        """Return all adapters for an asset class in priority order."""
        return [e.adapter for e in self._by_asset.get(asset_class, [])]

    # ── Unified data methods with failover ───────────────────────────────

    def connect_all(self) -> dict[str, bool]:
        """Connect all registered adapters.

        Returns:
            Dict mapping adapter name to connect result.
        """
        results: dict[str, bool] = {}
        for name, entry in self._by_name.items():
            try:
                ok = entry.adapter.connect()
                entry.connected = ok
                results[name] = ok
                if ok:
                    _log.info("[MDS] %s connected", name)
                else:
                    _log.warning("[MDS] %s connect returned False", name)
            except (OSError, ConnectionError, ValueError, TypeError) as exc:
                _log.error("[MDS] %s connect failed: %s", name, exc)
                entry.connected = False
                results[name] = False
        return results

    def disconnect_all(self) -> None:
        """Disconnect all registered adapters."""
        for name, entry in self._by_name.items():
            try:
                entry.adapter.disconnect()
                entry.connected = False
                _log.info("[MDS] %s disconnected", name)
            except (OSError, ConnectionError, ValueError, TypeError) as exc:
                _log.debug("[MDS] %s disconnect error: %s", name, exc)

    def get_quote(
        self,
        symbol: str,
        asset_class: str = "equity",
    ) -> Any:
        """Get a quote for a symbol, trying adapters in priority order.

        Args:
            symbol: Trading symbol (e.g. ``"NIFTY"``, ``"RELIANCE"``).
            asset_class: Asset class to scope adapter lookup.

        Returns:
            ``Quote`` from the first adapter that returns data, or ``None``.
        """
        entries = self.get_entries_for(asset_class)
        for entry in entries:
            try:
                quote = entry.adapter.get_quote(symbol)
                if quote is not None:
                    return quote
            except (OSError, ConnectionError, ValueError, TypeError, KeyError) as exc:
                _log.debug(
                    "[MDS] %s get_quote(%s) failed: %s",
                    entry.name, symbol, exc,
                )
        _log.warning("[MDS] all adapters exhausted for %s (asset_class=%s)", symbol, asset_class)
        return None

    def get_historical_data(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "day",
        asset_class: str = "equity",
    ) -> list[dict[str, Any]]:
        """Get historical data with failover across registered adapters.

        Returns non-empty list from the first adapter that succeeds, otherwise
        an empty list.
        """
        entries = self.get_entries_for(asset_class)
        for entry in entries:
            try:
                data = entry.adapter.get_historical_data(symbol, from_date, to_date, interval)
                if data:
                    return data
            except (OSError, ConnectionError, ValueError, TypeError) as exc:
                _log.debug(
                    "[MDS] %s get_historical_data(%s) failed: %s",
                    entry.name, symbol, exc,
                )
        _log.warning("[MDS] historical data exhausted for %s", symbol)
        return []

    def get_latest_data(
        self,
        symbol: str,
        asset_class: str = "equity",
    ) -> Any:
        """Get latest market data with failover."""
        entries = self.get_entries_for(asset_class)
        for entry in entries:
            try:
                data = entry.adapter.get_latest_data(symbol)
                if data is not None:
                    return data
            except (OSError, ConnectionError, ValueError, TypeError) as exc:
                _log.debug(
                    "[MDS] %s get_latest_data(%s) failed: %s",
                    entry.name, symbol, exc,
                )
        return None

    def subscribe_to_market_data(
        self,
        symbols: list[str],
        callback: Any,
        asset_class: str = "index",
    ) -> dict[str, bool]:
        """Subscribe to real-time data across matching adapters.

        Returns dict mapping adapter name to subscription result.
        """
        results: dict[str, bool] = {}
        for entry in self.get_entries_for(asset_class):
            try:
                ok = entry.adapter.subscribe_to_market_data(symbols, callback)
                results[entry.name] = ok
            except (OSError, ConnectionError, ValueError, TypeError) as exc:
                _log.debug("[MDS] %s subscribe failed: %s", entry.name, exc)
                results[entry.name] = False
        return results

    def get_instrument_details(
        self,
        symbol: str,
        asset_class: str = "equity",
    ) -> dict[str, Any]:
        """Get instrument details from the highest-priority matching adapter."""
        entries = self.get_entries_for(asset_class)
        for entry in entries:
            try:
                details = entry.adapter.get_instrument_details(symbol)
                if details:
                    return details
            except (OSError, ConnectionError, ValueError, TypeError) as exc:
                _log.debug(
                    "[MDS] %s get_instrument_details(%s) failed: %s",
                    entry.name, symbol, exc,
                )
        return {"symbol": symbol, "note": "unresolved"}

    # ── Config-driven population ────────────────────────────────────────

    def populate_from_config(self, config: dict[str, Any]) -> int:
        """Populate adapters from config using ``MarketDataProvider.adapters_from_config()``.

        This is typically called during bot startup after config is loaded.
        It creates and registers adapters based on ``DATA_PROVIDER_PRIORITY``
        and ``DATA_PROVIDER_ENABLED`` config keys.

        Args:
            config: Application configuration dict.

        Returns:
            Number of adapters successfully registered.
        """
        pairs = MarketDataProvider.adapters_from_config(config)
        count = 0
        for name, adapter in pairs:
            # Map provider name to asset class
            asset_class = self._provider_to_asset_class(name)
            if asset_class:
                self.register(name, adapter, asset_classes=asset_class, priority=self._provider_priority(name))
                count += 1
        _log.info("[MDS] populated %d adapters from config", count)
        return count

    @staticmethod
    def _provider_to_asset_class(name: str) -> list[str]:
        """Map a provider name to one or more asset classes."""
        mapping = {
            "yfinance": ["index", "equity"],
            "websocket": ["index"],
            "broker": ["equity", "index", "fo"],
            "nse": ["index"],
            "nse_equity": ["equity"],
            "mcx_commodity": ["commodity"],
            "cds_currency": ["currency"],
        }
        return mapping.get(name.lower().strip(), ["equity"])

    @staticmethod
    def _provider_priority(name: str) -> int:
        """Map a provider name to its recommended priority."""
        mapping = {
            "websocket": 100,
            "broker": 50,
            "yfinance": 10,
            "nse": 10,
            "nse_equity": 20,
            "mcx_commodity": 20,
            "cds_currency": 20,
        }
        return mapping.get(name.lower().strip(), 10)

    # ── Health & diagnostics ─────────────────────────────────────────────

    def list_adapters(self) -> dict[str, dict[str, Any]]:
        """Return a snapshot of all registered adapters."""
        result: dict[str, dict[str, Any]] = {}
        for name, entry in self._by_name.items():
            result[name] = {
                "asset_classes": list(entry.asset_classes),
                "priority": entry.priority,
                "connected": entry.connected,
                "adapter_type": type(entry.adapter).__name__,
            }
        return result

    def health_check(self) -> dict[str, Any]:
        """Return aggregate health status."""
        adapter_statuses = self.list_adapters()
        total = len(adapter_statuses)
        connected = sum(1 for v in adapter_statuses.values() if v["connected"])
        return {
            "total_adapters": total,
            "connected_adapters": connected,
            "disconnected_adapters": total - connected,
            "adapter_details": adapter_statuses,
        }
