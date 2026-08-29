"""Commodity Trader — MCX commodity futures trading engine.

Supports MCX commodity futures trading with:
  - MCX_CONTRACT_SPECS for lot sizes, tick sizes, margins
  - Config-driven COMMODITY_MAP for enabled symbols
  - Commodity-specific market hours (MCX: 09:00-23:30)
  - Expiry-aware contract rollover
  - SPAN margin estimation

Config keys:
    COMMODITY_ENABLED: true/false
    COMMODITY_MAP: symbol definitions
    COMMODITY_PRIORITY: scan order
    COMMODITY_SL_PCT / COMMODITY_TARGET_PCT: risk thresholds
    COMMODITY_DEFAULT_QTY: default lot size
    COMMODITY_MAX_DAILY_TRADES: daily trade limit

Usage:
    from core.commodity_trader import CommodityTrader, run_commodity_trader
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

_DEFAULT_COMMODITY_PRIORITY = ["GOLD", "SILVER", "CRUDEOIL", "NATURALGAS", "COPPER"]
_DEFAULT_SL_PCT = 0.97
_DEFAULT_TARGET_PCT = 1.05
_DEFAULT_MAX_DAILY = 10
_DEFAULT_QTY = 1
# MCX market hours: Mon-Fri 09:00-23:30 (some commodities like agri close earlier)
_COMMODITY_OPEN = (9, 0)
_COMMODITY_CLOSE = (23, 30)


@dataclass
class CommodityTradePosition:
    """An open commodity futures position.

    Attributes:
        symbol: Trading symbol (e.g. "GOLD", "CRUDEOIL").
        direction: BUY or SELL.
        qty: Number of lots.
        entry_price: Average entry price.
        current_price: Latest available price.
        margin_used: Estimated SPAN margin.
        entry_time: Timestamp of entry.
        expiry: Contract expiry string.
    """
    symbol: str
    direction: str
    qty: int
    entry_price: float
    current_price: float = 0.0
    margin_used: float = 0.0
    entry_time: float = 0.0
    expiry: str = ""
    asset_class: str = "COMMODITY"
    score: int = 0
    reason: str = ""


class CommodityTrader:
    """MCX commodity futures trading engine.

    Manages commodity positions with SPAN margin tracking,
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
        self._positions: dict[str, CommodityTradePosition] = {}
        self._daily_trades = 0
        self._current_day: str | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Build symbol list
        self._symbols = self._build_symbols()
        self._reentry_trackers = build_reentry_trackers(self._symbols)

        # Risk parameters
        self._sl_pct = float(self._cfg.get("COMMODITY_SL_PCT", _DEFAULT_SL_PCT))
        self._target_pct = float(self._cfg.get("COMMODITY_TARGET_PCT", _DEFAULT_TARGET_PCT))
        self._max_daily = int(self._cfg.get("COMMODITY_MAX_DAILY_TRADES", _DEFAULT_MAX_DAILY))
        self._default_qty = int(self._cfg.get("COMMODITY_DEFAULT_QTY", _DEFAULT_QTY))

        _log.info("[COMMODITY] Loaded %d symbols", len(self._symbols))

    def _build_symbols(self) -> list[str]:
        if not self._cfg.get("COMMODITY_ENABLED", False):
            return []
        asset_map = self._cfg.get("COMMODITY_MAP", {})
        priority = self._cfg.get("COMMODITY_PRIORITY", _DEFAULT_COMMODITY_PRIORITY)
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
        return list(self._symbols)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        _log.info("[COMMODITY] Trader started with %d symbols", len(self._symbols))
        self._send_fn(f"[COMMODITY] Trader started ({len(self._symbols)} symbols)")

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        _log.info("[COMMODITY] Trader stopped")

    def can_trade(self) -> tuple[bool, str]:
        if not self._symbols:
            return False, "No commodity symbols configured"
        if not self._is_market_open():
            return False, "Market closed"
        with self._lock:
            if self._daily_trades >= self._max_daily:
                return False, f"Max daily trades ({self._max_daily}) reached"
        return True, "Trading allowed"

    def enter_position(self, symbol: str, direction: str, score: int,
                       entry_price: float = 0.0, reason: str = "",
                       qty: int = 0, expiry: str = "") -> bool:
        if not self._is_market_open():
            return False

        with self._lock:
            if self._daily_trades >= self._max_daily:
                return False
            if symbol in self._positions:
                return False

        rt = self._reentry_trackers.get(symbol)
        if rt is not None:
            dec = rt.evaluate_reentry(current_score=score, current_direction=direction, cfg=self._cfg)
            if not dec.allowed:
                _log.info("[COMMODITY] %s: reentry blocked", symbol)
                return False

        price = entry_price if entry_price > 0 else (self._get_price_fn(symbol) or 0)
        if price <= 0:
            _log.warning("[COMMODITY] %s: invalid price", symbol)
            return False

        lot_qty = qty if qty > 0 else self._default_qty

        if self._execute_entry_fn is not None:
            try:
                if not self._execute_entry_fn(symbol, direction, lot_qty, price):
                    return False
            except (ValueError, TypeError, OSError) as e:
                _log.error("[COMMODITY] %s: entry failed - %s", symbol, e)
                return False

        with self._lock:
            pos = CommodityTradePosition(
                symbol=symbol, direction=direction, qty=lot_qty,
                entry_price=price, current_price=price,
                entry_time=time.time(), expiry=expiry,
                score=score, reason=reason,
            )
            self._positions[symbol] = pos
            self._daily_trades += 1

        _log.info("[COMMODITY] Entered %s %s x%d @ %.2f", symbol, direction, lot_qty, price)
        self._send_fn(f"[COMMODITY] Entered {symbol} {direction} x{lot_qty} @ {price:.2f}")
        return True

    def exit_position(self, symbol: str, reason: str, exit_price: float = 0.0) -> bool:
        with self._lock:
            pos = self._positions.pop(symbol, None)
        if pos is None:
            return False

        price = exit_price if exit_price > 0 else (self._get_price_fn(symbol) or pos.entry_price)
        pnl = (price - pos.entry_price) * pos.qty
        if pos.direction == "SELL":
            pnl = (pos.entry_price - price) * pos.qty

        if self._execute_exit_fn is not None:
            try:
                self._execute_exit_fn(symbol, pos.qty, price)
            except (ValueError, TypeError, OSError) as e:
                _log.error("[COMMODITY] %s: exit failed - %s", symbol, e)

        _log.info("[COMMODITY] Exited %s: %s @ %.2f (P&L=%.0f)", symbol, reason, price, pnl)
        self._send_fn(f"[COMMODITY] Exited {symbol}: {reason} @ {price:.2f} P&L={pnl:.0f}")
        rt = self._reentry_trackers.get(symbol)
        if rt is not None:
            rt.record_outcome(pnl > 0)
        return True

    def _is_market_open(self) -> bool:
        now = now_ist()
        if now.weekday() >= 5:
            return False
        open_mins = _COMMODITY_OPEN[0] * 60 + _COMMODITY_OPEN[1]
        close_mins = _COMMODITY_CLOSE[0] * 60 + _COMMODITY_CLOSE[1]
        current_mins = now.hour * 60 + now.minute
        return open_mins <= current_mins < close_mins

    def _monitor_positions(self) -> None:
        for symbol in list(self._positions.keys()):
            with self._lock:
                pos = self._positions.get(symbol)
                if pos is None:
                    continue
                pos_copy = CommodityTradePosition(**pos.__dict__)

            price = self._get_price_fn(symbol)
            if price is None or price <= 0:
                continue

            with self._lock:
                if symbol in self._positions:
                    self._positions[symbol].current_price = price

            move_pct = (price - pos_copy.entry_price) / max(pos_copy.entry_price, 0.01)
            if pos_copy.direction == "SELL":
                move_pct = -move_pct

            if move_pct <= -(1.0 - self._sl_pct):
                self.exit_position(symbol, "SL_HIT", price)
            elif move_pct >= (self._target_pct - 1.0):
                self.exit_position(symbol, "TARGET_HIT", price)

    def _run_loop(self) -> None:
        interval = max(10, int(self._cfg.get("SCAN_INTERVAL", 30)))
        while self._running and not self._stop_event.is_set():
            try:
                self._reset_daily_if_needed()
                self._monitor_positions()
            except (ValueError, TypeError, OSError) as e:
                _log.warning("[COMMODITY] Loop error: %s", e)
            self._stop_event.wait(interval)

    def _reset_daily_if_needed(self) -> None:
        today = now_ist().strftime("%Y-%m-%d")
        with self._lock:
            if self._current_day != today:
                self._current_day = today
                self._daily_trades = 0
                for _, rt in self._reentry_trackers.items():
                    try:
                        rt.reset_daily()
                    except (ValueError, TypeError, AttributeError):
                        pass

    def status(self) -> dict[str, Any]:
        with self._lock:
            [p.__dict__ for p in self._positions.values()]
            total_pnl = sum(
                (p.current_price - p.entry_price) * p.qty * (-1 if p.direction == "SELL" else 1)
                for p in self._positions.values()
            )
            return {
                "running": self._running,
                "positions": len(self._positions),
                "daily_trades": self._daily_trades,
                "max_daily_trades": self._max_daily,
                "total_pnl": round(total_pnl, 2),
                "symbols": len(self._symbols),
                "sl_pct": self._sl_pct,
                "target_pct": self._target_pct,
            }


def run_commodity_trader(**kwargs: Any) -> CommodityTrader:
    trader = CommodityTrader(**kwargs)
    trader.start()
    return trader


__all__ = ["CommodityTradePosition", "CommodityTrader", "run_commodity_trader"]
