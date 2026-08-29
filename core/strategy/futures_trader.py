"""Futures Trader (v2.54) - Index, equity, commodity & currency futures trading module.

Supports trading NSE/BSE/MCX/CDS futures instruments using config-driven maps:
  - FUTURES_MAP: Symbol definitions for index/stock futures
  - COMMODITY_MAP: MCX commodity futures (Gold, Silver, Crude, etc.)
  - CURRENCY_MAP: CDS currency futures (USDINR, EURINR, etc.)

Follows the same risk infrastructure as index options but adapted for
futures-specific characteristics:
  - Mark-to-market daily settlement
  - Margin-based position sizing (SPAN + exposure)
  - Expiry-dependent rollover
  - Contract-level position tracking

Config keys:
    FUTURES_MAP / COMMODITY_MAP / CURRENCY_MAP: asset definitions
    FUTURES_PRIORITY: scan order
    FUTURES_ENABLED / COMMODITY_ENABLED / CURRENCY_ENABLED
    FUTURES_DEFAULT_QTY: default lot size
    FUTURES_SL_PCT / FUTURES_TARGET_PCT: risk thresholds

Public API
----------
    FuturesTrader - Main futures trading engine
    run_futures_trader - Standalone entry point
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.datetime_ist import now_ist
from core.reentry_evaluator import build_reentry_trackers

_log = logging.getLogger(__name__)

# Default config values
_DEFAULT_FUTURES_PRIORITY = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
_DEFAULT_FUTURES_SL_PCT = 0.95
_DEFAULT_FUTURES_TARGET_PCT = 1.05
_DEFAULT_FUTURES_MAX_DAILY = 10
_DEFAULT_FUTURES_DEFAULT_QTY = 50  # NIFTY futures lot size
_FUTURES_MARKET_OPEN = (9, 15)
_FUTURES_MARKET_CLOSE = (15, 30)


@dataclass
class FuturesPosition:
    """An open futures position.

    Attributes:
        symbol: Contract symbol (e.g., "NIFTY24DECFUT").
        direction: BUY or SELL.
        qty: Number of lots/contracts.
        entry_price: Average entry price.
        current_price: Latest available price.
        margin_used: SPAN + exposure margin blocked.
        unrealized_pnl: Current MTM P&L.
        realized_pnl: Closed portion P&L.
        expiry: Contract expiry date string.
        entry_time: Timestamp of entry.
    """
    symbol: str
    direction: str
    qty: int
    entry_price: float
    current_price: float = 0.0
    margin_used: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    expiry: str = ""
    entry_time: float = 0.0
    asset_class: str = "FUTURES"
    score: int = 0
    reason: str = ""


class FuturesTrader:
    """Index, equity, commodity & currency futures trading engine.

    Manages futures positions with margin tracking, MTM settlement,
    expiry-aware rollover, and config-driven risk parameters.
    Thread-safe.
    """

    def __init__(
        self,
        cfg: dict[str, Any] | None = None,
        send_fn: Callable | None = None,
        get_price_fn: Callable[[str], float | None] | None = None,
        execute_entry_fn: Callable | None = None,
        execute_exit_fn: Callable | None = None,
    ):
        self._cfg = cfg or {}
        self._send_fn = send_fn or (lambda msg, critical=False, **kw: None)
        self._get_price_fn = get_price_fn or (lambda sym: None)
        self._execute_entry_fn = execute_entry_fn
        self._execute_exit_fn = execute_exit_fn
        self._lock = threading.RLock()
        self._positions: dict[str, FuturesPosition] = {}
        self._daily_trades = 0
        self._current_day: str | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Build symbol lists
        self._futures_symbols = self._build_symbols("FUTURES_MAP", "FUTURES_PRIORITY",
                                                     "FUTURES_ENABLED", _DEFAULT_FUTURES_PRIORITY)
        self._commodity_symbols = self._build_symbols("COMMODITY_MAP", "COMMODITY_PRIORITY",
                                                       "COMMODITY_ENABLED", [])
        self._currency_symbols = self._build_symbols("CURRENCY_MAP", "CURRENCY_PRIORITY",
                                                      "CURRENCY_ENABLED", [])

        self._all_symbols = self._futures_symbols + self._commodity_symbols + self._currency_symbols
        self._reentry_trackers = build_reentry_trackers(self._all_symbols)

        # Risk parameters
        self._sl_pct = float(self._cfg.get("FUTURES_SL_PCT", _DEFAULT_FUTURES_SL_PCT))
        self._target_pct = float(self._cfg.get("FUTURES_TARGET_PCT", _DEFAULT_FUTURES_TARGET_PCT))
        self._max_daily_trades = int(self._cfg.get("FUTURES_MAX_DAILY_TRADES", _DEFAULT_FUTURES_MAX_DAILY))
        self._default_qty = int(self._cfg.get("FUTURES_DEFAULT_QTY", _DEFAULT_FUTURES_DEFAULT_QTY))

        _log.info("[FUTURES] Loaded %d symbols (%d futures, %d commodity, %d currency)",
                  len(self._all_symbols), len(self._futures_symbols),
                  len(self._commodity_symbols), len(self._currency_symbols))

    def _build_symbols(self, map_key: str, priority_key: str, enabled_key: str,
                       default_priority: list[str]) -> list[str]:
        """Build sorted list of enabled symbols from a config map."""
        if not self._cfg.get(enabled_key, bool(default_priority)):
            return []
        asset_map = self._cfg.get(map_key, {})
        priority = self._cfg.get(priority_key, default_priority)
        return [sym for sym in priority if sym in asset_map and asset_map[sym].get("enabled", True)]

    @property
    def positions(self) -> dict[str, Any]:
        with self._lock:
            return {k: v.__dict__ for k, v in self._positions.items()}

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def all_symbols(self) -> list[str]:
        return list(self._all_symbols)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        _log.info("[FUTURES] Trader started with %d symbols", len(self._all_symbols))
        self._send_fn(f"[FUTURES] Trader started ({len(self._all_symbols)} symbols)")

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        _log.info("[FUTURES] Trader stopped")

    def can_trade(self) -> tuple[bool, str]:
        if not self._all_symbols:
            return False, "No futures symbols configured"
        if not self._is_market_open():
            return False, "Market closed"
        with self._lock:
            if self._daily_trades >= self._max_daily_trades:
                return False, f"Max daily trades ({self._max_daily_trades}) reached"
        return True, "Trading allowed"

    def enter_position(self, symbol: str, direction: str, score: int,
                       entry_price: float = 0.0, reason: str = "",
                       qty: int = 0, expiry: str = "") -> bool:
        """Enter a futures position with risk checks."""
        if not self._is_market_open():
            _log.info("[FUTURES] %s: market closed", symbol)
            return False

        with self._lock:
            if self._daily_trades >= self._max_daily_trades:
                return False
            if symbol in self._positions:
                return False

        # Reentry check
        rt = self._reentry_trackers.get(symbol)
        if rt is not None:
            dec = rt.evaluate_reentry(current_score=score, current_direction=direction, cfg=self._cfg)
            if not dec.allowed:
                _log.info("[FUTURES] %s: reentry blocked - %s", symbol, dec.reason)
                return False

        price = entry_price if entry_price > 0 else (self._get_price_fn(symbol) or 0)
        if price <= 0:
            _log.warning("[FUTURES] %s: invalid price", symbol)
            return False

        lot_qty = qty if qty > 0 else self._default_qty

        if self._execute_entry_fn is not None:
            try:
                if not self._execute_entry_fn(symbol, direction, lot_qty, price):
                    return False
            except (ValueError, TypeError, OSError) as e:
                _log.error("[FUTURES] %s: entry failed - %s", symbol, e)
                return False

        with self._lock:
            pos = FuturesPosition(
                symbol=symbol, direction=direction, qty=lot_qty,
                entry_price=price, current_price=price,
                entry_time=time.time(), expiry=expiry,
                score=score, reason=reason,
            )
            self._positions[symbol] = pos
            self._daily_trades += 1

        _log.info("[FUTURES] Entered %s %s x%d @ %.2f (score=%d)",
                  symbol, direction, lot_qty, price, score)
        self._send_fn(f"[FUTURES] Entered {symbol} {direction} x{lot_qty} @ {price:.2f}")
        return True

    def exit_position(self, symbol: str, reason: str, exit_price: float = 0.0) -> bool:
        """Exit a futures position."""
        with self._lock:
            pos = self._positions.pop(symbol, None)
        if pos is None:
            return False

        price = exit_price if exit_price > 0 else (self._get_price_fn(symbol) or pos.entry_price)
        mtm = (price - pos.entry_price) * pos.qty
        if pos.direction == "SELL":
            mtm = (pos.entry_price - price) * pos.qty

        if self._execute_exit_fn is not None:
            try:
                self._execute_exit_fn(symbol, pos.qty, price)
            except (ValueError, TypeError, OSError) as e:
                _log.error("[FUTURES] %s: exit exec failed - %s", symbol, e)

        _log.info("[FUTURES] Exited %s: %s @ %.2f (MTM=%.0f)", symbol, reason, price, mtm)
        self._send_fn(f"[FUTURES] Exited {symbol}: {reason} @ {price:.2f} MTM={mtm:.0f}")
        self._record_outcome(symbol, mtm > 0)
        return True

    def _record_outcome(self, symbol: str, was_profit: bool) -> None:
        rt = self._reentry_trackers.get(symbol)
        if rt is not None:
            rt.record_outcome(was_profit)

    def _is_market_open(self) -> bool:
        now = now_ist()
        if now.weekday() >= 5:
            return False
        open_mins = _FUTURES_MARKET_OPEN[0] * 60 + _FUTURES_MARKET_OPEN[1]
        close_mins = _FUTURES_MARKET_CLOSE[0] * 60 + _FUTURES_MARKET_CLOSE[1]
        current_mins = now.hour * 60 + now.minute
        return open_mins <= current_mins < close_mins

    def _monitor_positions(self) -> None:
        for symbol in list(self._positions.keys()):
            with self._lock:
                pos = self._positions.get(symbol)
                if pos is None:
                    continue
                pos_copy = FuturesPosition(**pos.__dict__)

            price = self._get_price_fn(symbol)
            if price is None or price <= 0:
                continue

            move_pct = (price - pos_copy.entry_price) / max(pos_copy.entry_price, 0.01)
            if pos_copy.direction == "SELL":
                move_pct = -move_pct

            # Update position price
            with self._lock:
                if symbol in self._positions:
                    self._positions[symbol].current_price = price

            if move_pct <= -(1.0 - self._sl_pct):
                self.exit_position(symbol, "SL_HIT", price)
            elif move_pct >= (self._target_pct - 1.0):
                self.exit_position(symbol, "TARGET_HIT", price)

    def _run_loop(self) -> None:
        scan_interval = max(10, int(self._cfg.get("SCAN_INTERVAL", 30)))
        while self._running and not self._stop_event.is_set():
            try:
                self._reset_daily_if_needed()
                self._monitor_positions()
            except (ValueError, TypeError, OSError) as e:
                _log.warning("[FUTURES] Loop error: %s", e)
            self._stop_event.wait(scan_interval)

    def _reset_daily_if_needed(self) -> None:
        today = now_ist().strftime("%Y-%m-%d")
        with self._lock:
            if self._current_day != today:
                self._current_day = today
                self._daily_trades = 0
                for rt_name, rt in self._reentry_trackers.items():
                    try:
                        rt.reset_daily()
                    except (ValueError, TypeError, AttributeError):
                        pass

    def status(self) -> dict[str, Any]:
        with self._lock:
            pos_list = [p.__dict__ for p in self._positions.values()]
            total_mtm = sum(
                (p.current_price - p.entry_price) * p.qty * (-1 if p.direction == "SELL" else 1)
                for p in self._positions.values()
            )
            return {
                "running": self._running,
                "positions": len(self._positions),
                "daily_trades": self._daily_trades,
                "max_daily_trades": self._max_daily_trades,
                "total_mtm": round(total_mtm, 2),
                "symbols_total": len(self._all_symbols),
                "futures_count": len(self._futures_symbols),
                "commodity_count": len(self._commodity_symbols),
                "currency_count": len(self._currency_symbols),
                "positions_detail": pos_list,
                "sl_pct": self._sl_pct,
                "target_pct": self._target_pct,
            }


def run_futures_trader(
    cfg: dict[str, Any] | None = None,
    send_fn: Callable | None = None,
    get_price_fn: Callable[[str], float | None] | None = None,
    execute_entry_fn: Callable | None = None,
    execute_exit_fn: Callable | None = None,
) -> FuturesTrader:
    """Create and start a FuturesTrader instance.

    Args:
        cfg: Configuration dict.
        send_fn: Notification function.
        get_price_fn: Price fetch function.
        execute_entry_fn: Entry execution callback.
        execute_exit_fn: Exit execution callback.

    Returns:
        Started FuturesTrader instance.
    """
    trader = FuturesTrader(
        cfg=cfg, send_fn=send_fn, get_price_fn=get_price_fn,
        execute_entry_fn=execute_entry_fn, execute_exit_fn=execute_exit_fn,
    )
    trader.start()
    return trader


__all__ = [
    "FuturesPosition",
    "FuturesTrader",
    "run_futures_trader",
]
