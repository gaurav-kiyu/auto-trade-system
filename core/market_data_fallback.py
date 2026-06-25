"""
Dual-Source Market Data Fallback

Primary source: Broker feed
Fallback: Secondary provider (Yahoo Finance, etc.)

If mismatch > threshold, pause trading.

Config keys:
- market_data_secondary_enabled: bool (default false)
- market_data_mismatch_threshold_pct: float (default 1.0)
- market_data_secondary_provider: str ("yahoo", "nse_api")
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from core.datetime_ist import now_ist

log = logging.getLogger("market_data_fallback")


@dataclass
class PriceQuote:
    """Price quote from a data source."""
    symbol: str
    price: float
    timestamp: datetime
    source: str  # "primary", "fallback"


@dataclass
class PriceValidationResult:
    """Result of comparing two price sources."""
    is_valid: bool
    primary_price: float
    fallback_price: float
    mismatch_pct: float
    reason: str = ""
    should_pause: bool = False


class DualSourceMarketData:
    """
    Manages dual-source market data with automatic fallback.
    """

    def __init__(
        self,
        primary_getter: Callable[[str], float | None],
        fallback_getter: Callable[[str], float | None] | None = None,
        config: dict | None = None
    ):
        self._primary_getter = primary_getter
        self._fallback_getter = fallback_getter
        self._config = config or {}
        self._lock = threading.RLock()

        # Config
        self._enabled = self._config.get("market_data_secondary_enabled", False)
        self._mismatch_threshold_pct = self._config.get("market_data_mismatch_threshold_pct", 1.0)

        # State
        self._last_prices: dict[str, dict[str, float]] = {}  # symbol -> {source: price}
        self._last_check: dict[str, datetime] = {}
        self._paused: bool = False
        self._pause_reason: str = ""

    def get_price(self, symbol: str) -> tuple[float | None, str]:
        """
        Get price from primary source with fallback.
        Returns (price, source).
        """
        try:
            primary_price = self._primary_getter(symbol)

            if primary_price is not None and primary_price > 0:
                return primary_price, "primary"

            # Primary unavailable, try fallback
            if self._fallback_getter is not None and self._enabled:
                fallback_price = self._fallback_getter(symbol)
                if fallback_price is not None and fallback_price > 0:
                    log.warning(f"Using fallback price for {symbol}: {fallback_price}")
                    return fallback_price, "fallback"

            # All sources failed
            return None, "none"

        except Exception as e:
            log.error(f"Error getting price for {symbol}: {e} (type: {type(e).__name__})")
            return None, "error"

    def validate_price(self, symbol: str, primary_price: float) -> PriceValidationResult:
        """
        Validate primary price against fallback source.
        Returns validation result with mismatch info.
        """
        if not self._enabled or self._fallback_getter is None:
            return PriceValidationResult(
                is_valid=True,
                primary_price=primary_price,
                fallback_price=0,
                mismatch_pct=0,
                reason="Fallback disabled"
            )

        try:
            fallback_price = self._fallback_getter(symbol)

            if fallback_price is None or fallback_price <= 0:
                return PriceValidationResult(
                    is_valid=True,  # Can't validate without fallback
                    primary_price=primary_price,
                    fallback_price=0,
                    mismatch_pct=0,
                    reason="Fallback unavailable"
                )

            # Calculate mismatch
            if primary_price <= 0:
                return PriceValidationResult(
                    is_valid=False,
                    primary_price=primary_price,
                    fallback_price=fallback_price,
                    mismatch_pct=100,
                    reason="Invalid primary price",
                    should_pause=True
                )

            mismatch_pct = abs(primary_price - fallback_price) / primary_price * 100

            # Store for history
            with self._lock:
                self._last_prices[symbol] = {
                    "primary": primary_price,
                    "fallback": fallback_price
                }
                self._last_check[symbol] = now_ist()

            if mismatch_pct > self._mismatch_threshold_pct:
                log.warning(
                    f"Price mismatch for {symbol}: primary={primary_price}, "
                    f"fallback={fallback_price}, mismatch={mismatch_pct:.2f}% "
                    f"(threshold={self._mismatch_threshold_pct}%)"
                )
                return PriceValidationResult(
                    is_valid=False,
                    primary_price=primary_price,
                    fallback_price=fallback_price,
                    mismatch_pct=mismatch_pct,
                    reason=f"Mismatch {mismatch_pct:.2f}% > {self._mismatch_threshold_pct}%",
                    should_pause=True
                )

            return PriceValidationResult(
                is_valid=True,
                primary_price=primary_price,
                fallback_price=fallback_price,
                mismatch_pct=mismatch_pct
            )

        except Exception as e:
            log.error(f"Price validation error for {symbol}: {e} (type: {type(e).__name__})")
            return PriceValidationResult(
                is_valid=True,
                primary_price=primary_price,
                fallback_price=0,
                mismatch_pct=0,
                reason=f"Validation error: {e}"
            )

    def is_paused(self) -> tuple[bool, str]:
        """Check if trading is paused due to data issues."""
        return self._paused, self._pause_reason

    def pause(self, reason: str) -> None:
        """Pause trading due to data issues."""
        self._paused = True
        self._pause_reason = reason
        log.critical(f"Market data PAUSED: {reason}")

    def resume(self) -> None:
        """Resume trading."""
        self._paused = False
        self._pause_reason = ""
        log.info("Market data RESUMED")

    def get_last_prices(self) -> dict[str, dict[str, float]]:
        """Get last known prices for all symbols."""
        with self._lock:
            return dict(self._last_prices)

    def health_check(self) -> dict:
        """Return health status."""
        return {
            "enabled": self._enabled,
            "paused": self._paused,
            "pause_reason": self._pause_reason,
            "tracked_symbols": len(self._last_prices),
            "mismatch_threshold_pct": self._mismatch_threshold_pct,
        }


# Yahoo Finance fallback getter
def get_yahoo_price(symbol: str) -> float | None:
    """Get price from Yahoo Finance as fallback."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d", interval="1m")
        if data is not None and len(data) > 0:
            return float(data['Close'].iloc[-1])
    except Exception as e:
        log.debug(f"Yahoo Finance fetch failed for {symbol}: {e} (type: {type(e).__name__})")
    return None


# Singleton
_market_data: DualSourceMarketData | None = None


def get_market_data(
    primary_getter: Callable[[str], float | None] | None = None,
    fallback_getter: Callable[[str], float | None] | None = None,
    config: dict | None = None
) -> DualSourceMarketData:
    """Get or create singleton market data manager."""
    global _market_data
    if _market_data is None:
        _market_data = DualSourceMarketData(
            primary_getter=primary_getter or (lambda s: None),
            fallback_getter=fallback_getter,
            config=config
        )
    return _market_data


__all__ = [
    "DualSourceMarketData",
    "PriceQuote",
    "PriceValidationResult",
    "get_market_data",
    "get_yahoo_price",
    "log",
]

