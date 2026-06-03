from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Import our market data cache
try:
    from infrastructure.market_data.market_data_cache import (
        create_historical_data_validation_rule,
        create_option_chain_validation_rule,
        create_quote_validation_rule,
        get_market_data_cache,
    )
    MARKET_DATA_CACHE_AVAILABLE = True
except ImportError:
    MARKET_DATA_CACHE_AVAILABLE = False
    get_market_data_cache = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketDataSnapshot:
    source: str
    healthy: bool
    frames: dict[str, Any]
    note: str = ""


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    ok: bool
    data: Any = None
    note: str = ""


class ProviderChain:
    """Try providers in configured order until one returns usable data."""

    def __init__(
        self,
        providers: dict[str, Callable[..., Any]] | None = None,
        *,
        enabled: set[str] | None = None,
    ) -> None:
        self._providers = dict(providers or {})
        self._enabled = {str(name) for name in (enabled or set(self._providers))}

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        self._providers[str(name)] = fn
        if not self._enabled:
            self._enabled.add(str(name))

    def set_enabled(self, names: list[str] | set[str]) -> None:
        self._enabled = {str(name) for name in names}

    def fetch(
        self,
        provider_order: list[str],
        *args: Any,
        validator: Callable[[Any], bool] | None = None,
        **kwargs: Any,
    ) -> ProviderResult:
        validate = validator or (lambda data: data is not None)
        notes: list[str] = []
        for provider in provider_order:
            name = str(provider)
            if self._enabled and name not in self._enabled:
                notes.append(f"{name}:disabled")
                continue
            fn = self._providers.get(name)
            if fn is None:
                notes.append(f"{name}:missing")
                continue
            try:
                data = fn(*args, **kwargs)
            except (OSError, ConnectionError, TimeoutError, ValueError, TypeError) as exc:
                notes.append(f"{name}:error:{exc}")
                continue
            if validate(data):
                return ProviderResult(provider=name, ok=True, data=data, note="ok")
            notes.append(f"{name}:empty")
        return ProviderResult(provider="", ok=False, data=None, note=" | ".join(notes) or "no providers")


class DataEngine:
    """Market-data boundary with primary and fallback fetch hooks."""

    def __init__(
        self,
        *,
        fetch_all_frames_fn: Callable[[list[str]], dict[str, Any]],
        safe_fetch_fn: Callable[[str, str, str], Any] | None = None,
        vix_fetch_fn: Callable[[], float] | None = None,
        last_close_fn: Callable[[], dict[str, Any]] | None = None,
        live_prices_fn: Callable[[], dict[str, Any]] | None = None,
        websocket_snapshot_fn: Callable[[], dict[str, Any]] | None = None,
        provider_chain: ProviderChain | None = None,
        frame_provider_order: list[str] | None = None,
        last_close_provider_order: list[str] | None = None,
        live_price_provider_order: list[str] | None = None,
        market_data_cache_ttl: float = 300.0,  # 5 minutes default cache TTL
    ) -> None:
        self._fetch_all_frames_fn = fetch_all_frames_fn
        self._safe_fetch_fn = safe_fetch_fn
        self._vix_fetch_fn = vix_fetch_fn
        self._last_close_fn = last_close_fn
        self._live_prices_fn = live_prices_fn
        self._websocket_snapshot_fn = websocket_snapshot_fn
        self._provider_chain = provider_chain
        self._frame_provider_order = list(frame_provider_order or [])
        self._last_close_provider_order = list(last_close_provider_order or [])
        self._live_price_provider_order = list(live_price_provider_order or [])

        # Initialize market data cache
        if MARKET_DATA_CACHE_AVAILABLE:
            self._market_data_cache = get_market_data_cache()
            # Set up validation rules for different data types
            self._market_data_cache.set_validation_rule('quote', create_quote_validation_rule())
            self._market_data_cache.set_validation_rule('option_chain', create_option_chain_validation_rule())
            self._market_data_cache.set_validation_rule('historical', create_historical_data_validation_rule())
            self._market_data_cache.default_ttl = market_data_cache_ttl
        else:
            self._market_data_cache = None
            logger.warning("Market data cache not available due to missing dependencies")

    def fetch_all_frames(self, indices: list[str]) -> dict[str, Any]:
        # Create a cache key based on the indices only
        # Cache freshness is controlled by TTL settings
        cache_key = f"all_frames:{','.join(sorted(indices))}"

        # Try to get from cache first
        if self._market_data_cache is not None:
            cached_data, is_fresh, source = self._market_data_cache.get(
                cache_key,
                data_type="historical"
                # Uses the cache's default TTL which is set to market_data_cache_ttl
            )
            if is_fresh and cached_data is not None:
                logger.debug(f"Cache hit for all_frames: {cache_key}")
                return cached_data

        # Fetch from provider chain or direct function
        if self._provider_chain and self._frame_provider_order:
            result = self._provider_chain.fetch(
                self._frame_provider_order,
                indices,
                validator=lambda data: isinstance(data, dict) and any(v is not None for v in data.values()),
            )
            if result.ok:
                data = dict(result.data or {})
                # Cache the result
                if self._market_data_cache is not None:
                    self._market_data_cache.put(
                        cache_key,
                        data,
                        data_type="historical",
                        source="provider_chain"
                    )
                return data

        # Fallback to direct function
        data = self._fetch_all_frames_fn(indices)
        # Cache the result
        if self._market_data_cache is not None:
            self._market_data_cache.put(
                cache_key,
                data,
                data_type="historical",
                source="direct_function"
            )
        return data

    def safe_fetch(self, symbol: str, interval: str, period: str = "1d") -> Any:
        if not self._safe_fetch_fn:
            return None

        # Create cache key
        cache_key = f"safe_fetch:{symbol}:{interval}:{period}"

        # Try to get from cache first (short TTL for live data)
        if self._market_data_cache is not None:
            cached_data, is_fresh, source = self._market_data_cache.get(
                cache_key,
                data_type="historical",
                max_age=10  # 10 seconds max for interval data
            )
            if is_fresh and cached_data is not None:
                logger.debug(f"Cache hit for safe_fetch: {cache_key}")
                return cached_data

        # Fetch from function
        data = self._safe_fetch_fn(symbol, interval, period)

        # Cache the result
        if self._market_data_cache is not None:
            self._market_data_cache.put(
                cache_key,
                data,
                data_type="historical",
                source="safe_fetch"
            )
        return data

    def get_india_vix(self) -> float:
        if not self._vix_fetch_fn:
            return 0.0
        try:
            return float(self._vix_fetch_fn() or 0.0)
        except (TypeError, ValueError, OSError):
            return 0.0

    def fetch_last_close_summary(self) -> dict[str, Any]:
        if self._provider_chain and self._last_close_provider_order:
            result = self._provider_chain.fetch(
                self._last_close_provider_order,
                validator=lambda data: isinstance(data, dict) and bool(data),
            )
            if result.ok:
                return dict(result.data or {})
        if not self._last_close_fn:
            return {}
        try:
            data = self._last_close_fn()
        except (TypeError, ValueError, OSError):
            return {}
        return dict(data or {})

    def get_live_prices(self) -> dict[str, Any]:
        if self._provider_chain and self._live_price_provider_order:
            result = self._provider_chain.fetch(
                self._live_price_provider_order,
                validator=lambda data: isinstance(data, dict) and bool(data),
            )
            if result.ok:
                return dict(result.data or {})
        if not self._live_prices_fn:
            return {}
        try:
            data = self._live_prices_fn()
        except (TypeError, ValueError, OSError):
            return {}
        return dict(data or {})

    def websocket_snapshot(self) -> dict[str, Any]:
        if not self._websocket_snapshot_fn:
            return {}
        try:
            snap = self._websocket_snapshot_fn()
        except (TypeError, ValueError, OSError):
            return {}
        return dict(snap or {})

    def fetch_market_snapshot(self, indices: list[str]) -> MarketDataSnapshot:
        ws = self.websocket_snapshot()
        if ws:
            return MarketDataSnapshot(source="websocket", healthy=True, frames=ws)
        try:
            frames = self.fetch_all_frames(indices)
        except (OSError, ConnectionError, TimeoutError, ValueError, TypeError) as exc:
            return MarketDataSnapshot(
                source="fallback",
                healthy=False,
                frames={},
                note=f"Fallback fetch failed: {exc}",
            )
        return MarketDataSnapshot(
            source="fallback",
            healthy=bool(frames),
            frames=frames,
            note="Fallback mode (non-websocket data source)" if frames else "No market data available",
        )
