"""
LTP Resolver - fallback chain for underlying index prices (v2.45).

Provides a single ``resolve(index_name)`` call that tries, in order:
1. KiteTickerFeedManager LTP cache (live WebSocket tick)
2. Broker adapter ``get_ltp()`` (REST quote)
3. yfinance last close (EOD fallback)

Usage
-----
    resolver = LtpResolver(cfg, ws_feed_manager, broker_port)
    nifty_price = resolver.resolve("NIFTY")        # → 18500.0 or None
    banknifty = resolver.resolve("BANKNIFTY")       # → 42000.0 or None
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import pandas as pd

_log = logging.getLogger(__name__)

# Map index display names → Kite instrument tokens
# These match core/kite_ticker_feed.py defaults
_INDEX_TO_TOKEN: dict[str, int] = {
    "NIFTY": 256265,
    "BANKNIFTY": 260105,
    "FINNIFTY": 260937,
}

# Map index names → yfinance symbols (mirrors INDEX_MAP in index_trader.py)
_INDEX_TO_YF: dict[str, str] = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
}


class LtpResolver:
    """Three-tier LTP resolver with caching."""

    def __init__(
        self,
        cfg: dict[str, Any] | None = None,
        ws_feed: Any = None,
        broker_port: Any = None,
    ) -> None:
        self._cfg = cfg or {}
        self._ws_feed = ws_feed
        self._broker_port = broker_port

        # Fallback cache from yfinance (refreshed on each resolve miss)
        self._yf_cache: dict[str, float] = {}
        self._yf_cache_ts: float = 0
        self._yf_cache_ttl: float = 300.0  # 5 min
        self._cache_lock = threading.RLock()

    # ── Public API ──────────────────────────────────────────────────────────

    def resolve(self, index_name: str) -> float | None:
        """Return the latest known price for *index_name*, or None.

        Fallback order: WS cache → broker REST → yfinance → None.
        """
        # Layer 1: WebSocket LTP cache
        price = self._resolve_ws(index_name)
        if price is not None:
            return price

        # Layer 2: Broker REST get_ltp()
        price = self._resolve_broker(index_name)
        if price is not None:
            return price

        # Layer 3: yfinance last close (cached) - with staleness warning
        price = self._resolve_yfinance(index_name)
        if price is not None:
            _log.warning(
                "[LTP] yfinance fallback price used for %s: %.2f. "
                "This is the last daily close - may be stale during live hours.",
                index_name, price,
            )
        return price

    def resolve_token(self, instrument_token: int) -> float | None:
        """Resolve price directly by Kite instrument token (WS cache only)."""
        if self._ws_feed is not None:
            try:
                return self._ws_feed.get_ltp(instrument_token)
            except (ValueError, TypeError, AttributeError, KeyError, OSError, RuntimeError) as _ex:
                _log.debug(f"LTP resolve via WS failed for token {instrument_token}: {_ex}")
        return None

    def warm_cache(self, index_name: str) -> None:
        """Pre-populate cache for *index_name* from yfinance (non-blocking)."""
        self._resolve_yfinance(index_name)

    # ── Fallback layers ─────────────────────────────────────────────────────

    def _resolve_ws(self, index_name: str) -> float | None:
        token = _INDEX_TO_TOKEN.get(index_name)
        if token is None or self._ws_feed is None:
            return None
        try:
            if not self._ws_feed.is_connected():
                return None
            return self._ws_feed.get_ltp(token)
        except (ValueError, TypeError, AttributeError, KeyError, OSError, ConnectionError, RuntimeError) as exc:
            _log.debug("[LTP] WS resolve failed for %s: %s", index_name, exc)
            return None

    def _resolve_broker(self, index_name: str) -> float | None:
        bp = self._broker_port
        if bp is None:
            return None
        try:
            if hasattr(bp, "get_ltp"):
                return bp.get_ltp(index_name)
        except (ValueError, TypeError, AttributeError, KeyError, OSError, ConnectionError, RuntimeError) as exc:
            _log.debug("[LTP] broker resolve failed for %s: %s", index_name, exc)
        return None

    def _resolve_yfinance(self, index_name: str) -> float | None:
        now = time.time()
        with self._cache_lock:
            if self._yf_cache and now - self._yf_cache_ts < self._yf_cache_ttl:
                return self._yf_cache.get(index_name)

        yf_sym = _INDEX_TO_YF.get(index_name)
        if yf_sym is None:
            return None
        try:
            import yfinance as yf  # type: ignore

            ticker = yf.Ticker(yf_sym)
            hist = ticker.history(period="2d", interval="1d")
            if hist.empty:
                return None
            last_close_val = hist.iloc[-1]["Close"]
            if pd.isna(last_close_val):
                _log.debug("[LTP] yfinance close is NaN for %s - skipping", yf_sym)
                return None
            last_close = float(last_close_val)
            with self._cache_lock:
                self._yf_cache[index_name] = last_close
                self._yf_cache_ts = now
            return last_close
        except (ValueError, TypeError, AttributeError, KeyError, OSError, ConnectionError, RuntimeError) as exc:
            _log.debug("[LTP] yfinance resolve failed for %s: %s", index_name, exc)
            return None

    # ── Status ──────────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        return {
            "ws_connected": self._ws_feed.is_connected() if self._ws_feed else False,
            "has_broker": self._broker_port is not None,
            "yf_cache_size": len(self._yf_cache),
            "yf_cache_age_s": time.time() - self._yf_cache_ts if self._yf_cache_ts else -1,
        }
