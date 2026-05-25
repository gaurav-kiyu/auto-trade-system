"""
KiteTicker WebSocket Feed (v2.45 Item 22 — options chain viz companion).

Subclasses WebSocketFeedManager to implement a real KiteTicker connection
with built-in LTP cache and instrument token management.

Layer architecture
------------------
KiteTicker has its own internal reconnect (Twisted ReconnectingClientFactory).
This class adds a SECOND reconnect layer: if KiteTicker's internal reconnects
exhaust (on_noreconnect fires), our base-class reconnect loop re-creates the
entire KiteTicker instance from scratch.

Usage
-----
    from core.kite_ticker_feed import KiteTickerFeedManager
    kws = KiteTickerFeedManager(cfg)
    kws.connect(on_message=my_tick_handler)
    # LTPs arrive in cache automatically
    price = kws.get_ltp(256265)   # NIFTY index token
    kws.subscribe([738561])       # extra tokens at runtime
    kws.disconnect()

Config keys (extending ws_* base)
----------------------------------
    kite_ticker_enabled          : bool   default False
    kite_ticker_mode             : str    default "ltp"  (ltp|quote|full)
    kite_ticker_index_tokens     : list   default [256265, 260105, 260937]
                                          (NIFTY, BANKNIFTY, FINNIFTY)
    kite_ticker_subscribe_tokens : list   default []  (extra option tokens)
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from core.ws_feed_manager import WebSocketFeedManager

_log = logging.getLogger(__name__)

# Well-known NSE index tokens for Kite (indices segment = 9)
# These are the continuous index contracts — stable across expiries.
_DEFAULT_INDEX_TOKENS: list[int] = [
    256265,  # NIFTY 50
    260105,  # BANKNIFTY
    260937,  # FINNIFTY
]


class KiteTickerFeedManager(WebSocketFeedManager):
    """KiteTicker WebSocket feed with LTP cache and layered reconnect."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        super().__init__(cfg)
        self._cfg_store: dict[str, Any] = cfg or {}
        c = self._cfg_store

        self._enabled = bool(c.get("kite_ticker_enabled", False))
        self._tick_mode = str(c.get("kite_ticker_mode", "ltp")).lower()
        self._index_tokens: list[int] = list(
            c.get("kite_ticker_index_tokens", _DEFAULT_INDEX_TOKENS)
        )
        self._extra_tokens: list[int] = list(
            c.get("kite_ticker_subscribe_tokens", [])
        )

        # KiteTicker SDK instance (lazy, created in _do_connect)
        self._kws: Any = None

        # LTP cache: {instrument_token: {"last_price": float, "timestamp": float}}
        self._ltp_cache: dict[int, dict[str, Any]] = {}
        self._ltp_lock = threading.Lock()

        # Callbacks forwarded by the base class
        self._user_on_message: Callable[[Any], None] | None = None
        self._user_on_error: Callable[[Exception], None] | None = None

        # Flag set by on_noreconnect — tells our reconnect loop to recreate
        self._kite_gave_up = threading.Event()

    # ── Public API ──────────────────────────────────────────────────────────

    def enabled(self) -> bool:
        return self._enabled

    def subscribe(self, tokens: list[int]) -> bool:
        """Subscribe to additional instrument tokens at runtime."""
        if not self._kws or not self.is_connected():
            _log.warning("[KITE_WS] subscribe called while disconnected — tokens queued")
            self._extra_tokens.extend(tokens)
            return False
        try:
            self._kws.subscribe(tokens)
            return True
        except Exception as exc:
            _log.error("[KITE_WS] subscribe failed: %s", exc)
            return False

    def set_mode(self, mode: str, tokens: list[int]) -> bool:
        """Change streaming mode for given tokens."""
        if not self._kws or not self.is_connected():
            return False
        try:
            self._kws.set_mode(mode, tokens)
            return True
        except Exception as exc:
            _log.error("[KITE_WS] set_mode failed: %s", exc)
            return False

    def get_ltp(self, instrument_token: int) -> float | None:
        """Return last known price for a token, or None if not seen."""
        with self._ltp_lock:
            entry = self._ltp_cache.get(instrument_token)
            return entry["last_price"] if entry else None

    def get_ltp_cache(self) -> dict[int, dict[str, Any]]:
        """Return a snapshot of the entire LTP cache."""
        with self._ltp_lock:
            return dict(self._ltp_cache)

    # ── WebSocketFeedManager overrides ──────────────────────────────────────

    def connect(
        self,
        on_message: Callable[[Any], None] | None = None,
        on_error: Callable[[Any], None] | None = None,
    ) -> bool:
        if not self._enabled:
            _log.info("[KITE_WS] disabled by config (kite_ticker_enabled=false)")
            return False
        # Gate on real-broker mode: never connect in paper/sim/manual mode
        mode = str(self._cfg_store.get("EXECUTION_MODE", "")).upper()
        broker_enabled = bool(self._cfg_store.get("BROKER_API_ENABLED", False))
        broker_driver = str(self._cfg_store.get("BROKER_DRIVER", "")).upper()
        if mode in ("PAPER", "SIM", "TEST", "MANUAL", "SIGNAL_ONLY", ""):
            _log.info("[KITE_WS] skipped: EXECUTION_MODE=%s (paper/dev mode)", mode)
            return False
        if not broker_enabled:
            _log.info("[KITE_WS] skipped: BROKER_API_ENABLED=false")
            return False
        if broker_driver != "KITE":
            _log.info("[KITE_WS] skipped: BROKER_DRIVER=%s (requires KITE)", broker_driver)
            return False
        self._user_on_message = on_message
        self._user_on_error = on_error
        self._kite_gave_up.clear()
        return super().connect(on_message, on_error)

    def _do_connect(
        self,
        on_message: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> bool:
        """Create KiteTicker instance, set up callbacks, and connect."""
        try:
            # Lazy import — kiteconnect may not be installed in paper/dev env
            from kiteconnect.ticker import KiteTicker  # type: ignore
        except ImportError:
            _log.warning("[KITE_WS] kiteconnect not installed — cannot connect")
            return False

        # Resolve credentials via the standard broker secrets helper
        sec = self._broker_secrets()
        api_key = str(sec.get("api_key") or "").strip()
        access_token = str(sec.get("access_token") or "").strip()
        if not api_key or not access_token:
            _log.warning("[KITE_WS] missing api_key or access_token")
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

            # Wire KiteTicker callbacks to our handlers
            kws.on_connect = self._on_kite_connect
            kws.on_close = self._on_kite_close
            kws.on_error = self._on_kite_error
            kws.on_ticks = self._on_kite_ticks
            kws.on_reconnect = self._on_kite_reconnect
            kws.on_noreconnect = self._on_kite_noreconnect
            kws.on_order_update = self._on_kite_order_update

            # Connect in threaded mode (Twisted reactor runs in daemon thread)
            kws.connect(threaded=True)

            self._kws = kws
            return True

        except Exception as exc:
            _log.error("[KITE_WS] _do_connect failed: %s", exc)
            if on_error:
                on_error(exc)
            return False

    def _do_disconnect(self) -> None:
        """Close the KiteTicker connection."""
        kws = self._kws
        if kws is not None:
            try:
                kws.stop_retry()
                kws.close()
            except Exception as exc:
                _log.debug("[KITE_WS] disconnect error: %s", exc)
            self._kws = None
        self._kite_gave_up.set()

    # ── KiteTicker callbacks ────────────────────────────────────────────────

    def _on_kite_connect(self, ws: Any, response: Any) -> None:
        """Called after KiteTicker connects successfully."""
        _log.info("[KITE_WS] connected")
        with self._lock:
            self._connected = True
            self._last_connect_ts = time.time()
            self._last_error = ""
            self._reconnect_count = 0

        # Subscribe to configured tokens
        all_tokens = list(self._index_tokens)
        for t in self._extra_tokens:
            if t not in all_tokens:
                all_tokens.append(t)
        if all_tokens:
            try:
                ws.subscribe(all_tokens)
                ws.set_mode(self._tick_mode, all_tokens)
                _log.info(
                    "[KITE_WS] subscribed to %d tokens in %s mode",
                    len(all_tokens), self._tick_mode,
                )
            except Exception as exc:
                _log.error("[KITE_WS] initial subscribe failed: %s", exc)

        # Forward on_message to user callback (fires once on first connect)
        if self._user_on_message and not hasattr(self, "_connect_fired"):
            self._user_on_message({"type": "connect", "status": "connected"})
            self._connect_fired = True  # type: ignore[attr-defined]

    def _on_kite_close(self, ws: Any, code: int, reason: str) -> None:
        """Called when KiteTicker connection closes."""
        _log.warning("[KITE_WS] closed: code=%s reason=%s", code, reason)
        with self._lock:
            self._connected = False
            self._last_disconnect_ts = time.time()
            self._last_error = f"close code={code} reason={reason}"

    def _on_kite_error(self, ws: Any, code: int, reason: str) -> None:
        """Called when KiteTicker encounters an error."""
        _log.error("[KITE_WS] error: code=%s reason=%s", code, reason)
        msg = f"code={code} reason={reason}"
        with self._lock:
            self._last_error = msg
        if self._user_on_error:
            self._user_on_error(ConnectionError(msg))

    def _on_kite_ticks(self, ws: Any, ticks: list[dict[str, Any]]) -> None:
        """Called when ticks arrive. Updates LTP cache + forwards to user."""
        now = time.time()
        with self._ltp_lock:
            for tick in ticks:
                token = tick.get("instrument_token")
                if token is None:
                    continue
                ltp_val = float(tick.get("last_price", 0))
                if ltp_val <= 0:
                    continue  # Skip zero/invalid ticks — don't poison cache
                self._ltp_cache[token] = {
                    "last_price": ltp_val,
                    "timestamp": now,
                    "mode": tick.get("mode", self._tick_mode),
                }
        if self._user_on_message:
            self._user_on_message({"type": "ticks", "data": ticks})

    def _on_kite_reconnect(self, ws: Any, attempts_count: int) -> None:
        """Called by KiteTicker's internal reconnect on each attempt."""
        _log.info("[KITE_WS] internal reconnect attempt %d", attempts_count)

    def _on_kite_noreconnect(self, ws: Any) -> None:
        """Called when KiteTicker's internal reconnect exhausts.

        This signals our outer reconnect loop to re-create the instance.
        """
        _log.error("[KITE_WS] internal reconnect exhausted — signalling outer layer")
        self._kite_gave_up.set()
        with self._lock:
            self._connected = False

    def _on_kite_order_update(self, ws: Any, data: Any) -> None:
        """Called when order updates arrive (optional)."""
        if self._user_on_message:
            self._user_on_message({"type": "order_update", "data": data})

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _broker_secrets(self) -> dict[str, str]:
        """Resolve Kite broker credentials from config."""
        try:
            from core.adapters.broker_adapters import broker_connection_secrets
            return broker_connection_secrets(self._cfg or {}, "KITE")
        except ImportError:
            return {}

    def status(self) -> dict[str, Any]:
        base = super().status()
        base["enabled"] = self._enabled
        base["tick_mode"] = self._tick_mode
        base["index_tokens"] = list(self._index_tokens)
        base["extra_tokens"] = list(self._extra_tokens)
        base["ltp_cache_size"] = len(self._ltp_cache)
        base["kite_gave_up"] = self._kite_gave_up.is_set()
        base["has_kws"] = self._kws is not None
        return base

    @property
    def _cfg(self) -> dict[str, Any]:
        """Expose config for _broker_secrets lookup."""
        return self._cfg_store
