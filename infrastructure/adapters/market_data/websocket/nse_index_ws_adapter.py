"""NSE Index WebSocket Adapter - MarketDataPort implementation for real-time NSE index data.

Self-contained adapter that manages a KiteTicker WebSocket connection directly
instead of delegating to KiteTickerFeedManager.  Maintains an internal LTP cache
updated by the streaming tick feed - ``get_quote()`` and ``get_latest_data()``
read from this cache synchronously without blocking.

Architecture
------------
The adapter uses ``kiteconnect.ticker.KiteTicker`` (lazy-imported) for the actual
WebSocket connection.  Ticks arrive in ``_on_kite_ticks`` which immediately updates
the symbol-keyed LTP cache.  When KiteTicker is unavailable (paper/dev mode),
all data methods return ``None`` to allow transparent degradation to REST adapters.

Config keys
-----------
    kite_ticker_enabled          : bool   default False
    kite_ticker_index_tokens     : dict   default {"NIFTY": 256265, "BANKNIFTY": 260105, "FINNIFTY": 260937}
    kite_ticker_mode             : str    default "ltp"  (ltp|quote|full)
    ws_cache_ttl_seconds         : float  default 5.0

NSE Index Token Reference
-------------------------
    256265  - NIFTY 50      260105  - BANKNIFTY      260937  - FINNIFTY
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
from datetime import datetime
from typing import Any

from core.ports.market_data import MarketDataPort

_log = logging.getLogger(__name__)

# Well-known NSE index tokens for Kite (indices segment = 9)
NSE_INDEX_TOKENS: dict[str, int] = {
    "NIFTY": 256265,
    "BANKNIFTY": 260105,
    "FINNIFTY": 260937,
}


class NseIndexWebSocketAdapter(MarketDataPort):
    """Self-contained MarketDataPort for NSE indices via KiteTicker WebSocket.

    Manages the KiteTicker connection directly - no delegation to
    KiteTickerFeedManager.  Ticks update a symbol-keyed LTP cache that
    ``get_quote()`` reads from synchronously.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self._cfg = config or {}
        self._enabled = bool(self._cfg.get("kite_ticker_enabled", False))
        self._tick_mode = str(self._cfg.get("kite_ticker_mode", "ltp")).lower()
        self._cache_ttl = float(self._cfg.get("ws_cache_ttl_seconds", 5.0))

        # Mapping from display symbol -> Kite instrument token
        raw_tokens = self._cfg.get("kite_ticker_index_tokens", NSE_INDEX_TOKENS)
        self._token_map: dict[str, int] = (
            {k.upper(): v for k, v in raw_tokens.items()}
            if isinstance(raw_tokens, dict)
            else dict(NSE_INDEX_TOKENS)
        )
        # Inverse map: token -> symbol
        self._symbol_by_token: dict[int, str] = {v: k for k, v in self._token_map.items()}
        self._index_token_list: list[int] = list(self._token_map.values())

        # LTP cache: {symbol: {"last_price": float, "bid": float, "ask": float,
        #                       "volume": int, "timestamp": float, "source": str}}
        self._cache: dict[str, dict[str, Any]] = {}
        self._cache_lock = threading.RLock()

        # KiteTicker SDK instance
        self._kws: Any = None
        self._connected = False

    # ── Connection lifecycle (MarketDataPort) ─────────────────────────────

    def connect(self) -> bool:
        if not self._enabled:
            _log.info("[NSE_WS] disabled by config (kite_ticker_enabled=false)")
            return False
        if self._kws is not None:
            return self._connected

        # Lazy-import KiteTicker SDK
        try:
            _kt_mod = importlib.import_module("kiteconnect.ticker")
            KiteTicker = _kt_mod.KiteTicker
        except (ImportError, AttributeError) as exc:
            _log.warning("[NSE_WS] kiteconnect not installed: %s", exc)
            return False

        # Resolve broker credentials
        sec = self._broker_secrets()
        api_key = str(sec.get("api_key") or "").strip()
        access_token = str(sec.get("access_token") or "").strip()
        if not api_key or not access_token:
            _log.warning("[NSE_WS] missing api_key or access_token")
            return False

        try:
            kws = KiteTicker(
                api_key=api_key,
                access_token=access_token,
                debug=False,
                reconnect=True,
                reconnect_max_tries=50,
                reconnect_max_delay=60,
            )

            # Wire callbacks
            kws.on_connect = self._on_kite_connect
            kws.on_close = self._on_kite_close
            kws.on_error = self._on_kite_error
            kws.on_ticks = self._on_kite_ticks
            kws.on_reconnect = self._on_kite_reconnect
            kws.on_noreconnect = self._on_kite_noreconnect

            kws.connect(threaded=True)
            self._kws = kws
            self._connected = True
            _log.info("[NSE_WS] KiteTicker connected")
            return True

        except (ImportError, AttributeError, TypeError, ValueError, OSError, ConnectionError) as exc:
            _log.error("[NSE_WS] connect failed: %s", exc)
            return False

    def disconnect(self) -> None:
        kws = self._kws
        if kws is not None:
            try:
                kws.stop_retry()
                kws.close()
            except (AttributeError, TypeError, OSError) as exc:
                _log.debug("[NSE_WS] disconnect error: %s", exc)
            self._kws = None
        self._connected = False
        with self._cache_lock:
            self._cache.clear()

    # ── KiteTicker callbacks ──────────────────────────────────────────────

    def _on_kite_connect(self, ws: Any, response: Any) -> None:
        """Called after KiteTicker connects successfully - subscribe to tokens."""
        _log.info("[NSE_WS] connected")
        self._connected = True
        if self._index_token_list:
            try:
                ws.subscribe(self._index_token_list)
                ws.set_mode(self._tick_mode, self._index_token_list)
                _log.info(
                    "[NSE_WS] subscribed to %d tokens in %s mode",
                    len(self._index_token_list), self._tick_mode,
                )
            except (AttributeError, TypeError, ValueError, OSError) as exc:
                _log.error("[NSE_WS] initial subscribe failed: %s", exc)

    def _on_kite_close(self, ws: Any, code: int, reason: str) -> None:
        """Called when KiteTicker connection closes."""
        _log.warning("[NSE_WS] closed: code=%s reason=%s", code, reason)
        self._connected = False

    def _on_kite_error(self, ws: Any, code: int, reason: str) -> None:
        """Called when KiteTicker encounters an error."""
        _log.error("[NSE_WS] error: code=%s reason=%s", code, reason)

    @staticmethod
    def _extract_depth_price(tick: dict[str, Any], side: str, ltp: float) -> float:
        """Extract best bid/ask price from KiteTicker depth data.

        In ``ltp`` mode the depth dict is absent - falls back to ``ltp``.
        In ``full`` mode depth is a dict with ``"bid"`` and ``"ask"`` keys,
        each being a list of price levels sorted by proximity.
        """
        depth = tick.get("depth")
        if not isinstance(depth, dict):
            return ltp
        levels = depth.get(side, [])
        if not isinstance(levels, list) or not levels:
            return ltp
        first = levels[0]
        if not isinstance(first, dict):
            return ltp
        return float(first.get("price", ltp))

    def _on_kite_ticks(self, ws: Any, ticks: list[dict[str, Any]]) -> None:
        """Called when ticks arrive - updates the LTP cache."""
        now = time.time()
        with self._cache_lock:
            for tick in ticks:
                token = tick.get("instrument_token")
                if token is None:
                    continue
                symbol = self._symbol_by_token.get(token)
                if symbol is None:
                    continue
                ltp = float(tick.get("last_price", 0))
                if ltp <= 0:
                    continue
                # In ltp mode, bid/ask are inferred from last_price;
                # in full mode they come from the depth levels.
                self._cache[symbol] = {
                    "last_price": ltp,
                    "bid": self._extract_depth_price(tick, "bid", ltp),
                    "ask": self._extract_depth_price(tick, "ask", ltp),
                    "volume": int(tick.get("volume", 0)),
                    "timestamp": now,
                    "source": "websocket",
                    "mode": tick.get("mode", self._tick_mode),
                }

    def _on_kite_reconnect(self, ws: Any, attempts_count: int) -> None:
        _log.info("[NSE_WS] reconnect attempt %d", attempts_count)

    def _on_kite_noreconnect(self, ws: Any) -> None:
        _log.error("[NSE_WS] internal reconnect exhausted")
        self._connected = False

    # ── MarketDataPort interface ─────────────────────────────────────────

    def get_quote(self, symbol: str) -> Any:
        """Return current quote from the LTP cache if fresh, else None."""
        sym = symbol.upper().strip()
        with self._cache_lock:
            entry = self._cache.get(sym)
            if entry is None:
                return None
            age = time.time() - entry.get("timestamp", 0)
            if age > self._cache_ttl:
                return None

        from core.ports.broker import Quote
        return Quote(
            symbol=sym,
            bid=float(entry.get("bid", entry["last_price"])),
            ask=float(entry.get("ask", entry["last_price"])),
            last=float(entry["last_price"]),
            volume=int(entry.get("volume", 0)),
        )

    def get_latest_data(self, symbol: str) -> Any:
        """Return the raw cache entry for the symbol, or None if stale/missing."""
        sym = symbol.upper().strip()
        with self._cache_lock:
            entry = self._cache.get(sym)
            if entry is None:
                return None
            age = time.time() - entry.get("timestamp", 0)
            if age > self._cache_ttl:
                return None
            return dict(entry)

    def is_data_fresh(self, market_data: Any, max_age_seconds: int = 30) -> bool:
        if market_data is None:
            return False
        ts = market_data.get("timestamp", 0) if isinstance(market_data, dict) else 0
        if ts == 0:
            return False
        return (time.time() - ts) < max_age_seconds

    def subscribe_to_market_data(
        self, symbols: list[str], callback: Any,
    ) -> bool:
        """Subscribe to additional index symbols at runtime."""
        if self._kws is None or not self._connected:
            _log.warning("[NSE_WS] subscribe called while disconnected")
            return False
        tokens: list[int] = []
        for sym in symbols:
            token = self._token_map.get(sym.upper().strip())
            if token is not None:
                tokens.append(token)
        if not tokens:
            return False
        try:
            self._kws.subscribe(tokens)
            return True
        except (AttributeError, TypeError, OSError) as exc:
            _log.error("[NSE_WS] subscribe failed: %s", exc)
            return False

    def unsubscribe_from_market_data(self, symbol: str) -> bool:
        _log.warning("[NSE_WS] unsubscribe not implemented")
        return False

    def get_historical_data(
        self, symbol: str, from_date: datetime, to_date: datetime,
        interval: str = "day",
    ) -> list[dict[str, Any]]:
        """Historical data is not available via the WebSocket adapter."""
        _log.warning("[NSE_WS] historical data not available - use yfinance adapter")
        return []

    def get_option_chain(
        self, symbol: str, expiry_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        _log.warning("[NSE_WS] option chain not available via WebSocket")
        return []

    def get_instrument_details(self, symbol: str) -> dict[str, Any]:
        sym = symbol.upper().strip()
        token = self._token_map.get(sym)
        return {
            "symbol": sym, "exchange": "NSE", "asset_class": "index",
            "instrument_token": token, "segment": "indices",
        }

    # ── Extra utility ────────────────────────────────────────────────────

    def get_ltp(self, symbol: str) -> float | None:
        """Quick synchronous LTP lookup - returns None if not cached."""
        entry = self.get_latest_data(symbol)
        return float(entry["last_price"]) if entry else None

    def get_all_cached(self) -> dict[str, dict[str, Any]]:
        """Return a snapshot of the entire LTP cache."""
        with self._cache_lock:
            return dict(self._cache)

    def status(self) -> dict[str, Any]:
        """Return status for health checks."""
        return {
            "connected": self._connected,
            "enabled": self._enabled,
            "cache_size": len(self._cache),
            "cache_ttl": self._cache_ttl,
            "has_kws": self._kws is not None,
            "tick_mode": self._tick_mode,
            "tokens": dict(self._token_map),
            "index_tokens": list(self._index_token_list),
        }

    # ── Credential resolution ────────────────────────────────────────────

    def _broker_secrets(self) -> dict[str, str]:
        """Resolve Kite broker credentials from config."""
        try:
            from core.adapters.broker_adapters import broker_connection_secrets
            return broker_connection_secrets(self._cfg, "KITE")
        except ImportError:
            return {}
