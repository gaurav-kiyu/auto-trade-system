"""
Equity Trader (v2.54) — Stock (cash market) trading module.

Supports trading NSE cash market equities using the EQUITY_MAP config entries.
Follows the same risk infrastructure as index options trading but adapted for
equity-specific characteristics:
  - Equity market hours: 09:15–15:30 IST (same as indices)
  - Position sizing based on stock price × lot size
  - Separate reentry trackers from index trading
  - No expiry day concerns for cash equities
  - Uses yfinance for stock price data

Config keys (in EQUITY_MAP section):
    EQUITY_PRIORITY: scan order for equities
    EQUITY_ENABLED: enable/disable equity trading
    EQUITY_DEFAULT_QTY: default quantity for equity entries
    EQUITY_MAX_DAILY_TRADES: max equity trades per day
    EQUITY_SL_PCT: stop-loss percentage for equities
    EQUITY_TARGET_PCT: target percentage for equities

Public API
----------
    EquityTrader          — Main equity trading engine
    run_equity_trader     — Standalone entry point
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from core.datetime_ist import now_ist
from core.reentry_evaluator import ReentryTracker, build_reentry_trackers

log = logging.getLogger(__name__)

# Default config values
_DEFAULT_EQUITY_PRIORITY = ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"]
_DEFAULT_EQUITY_SL_PCT = 0.95
_DEFAULT_EQUITY_TARGET_PCT = 1.05
_DEFAULT_EQUITY_MAX_DAILY_TRADES = 5
_DEFAULT_EQUITY_DEFAULT_QTY = 1
_EQUITY_MARKET_OPEN = (9, 15)
_EQUITY_MARKET_CLOSE = (15, 30)


class EquityTrader:
    """Equity (cash market) trading engine.

    Manages stock positions with equity-specific risk parameters,
    market hours, and position sizing. Thread-safe.
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
        self._positions: dict[str, dict[str, Any]] = {}
        self._daily_trades = 0
        self._current_day: str | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Build equity priority list from config
        equity_map = self._cfg.get("EQUITY_MAP", {})
        equity_priority = self._cfg.get("EQUITY_PRIORITY", _DEFAULT_EQUITY_PRIORITY)
        self._equity_symbols = [
            sym for sym in equity_priority
            if sym in equity_map and equity_map[sym].get("enabled", True)
        ]
        self._reentry_trackers: dict[str, Any] = build_reentry_trackers(self._equity_symbols)
        self._sl_pct = float(self._cfg.get("EQUITY_SL_PCT", _DEFAULT_EQUITY_SL_PCT))
        self._target_pct = float(self._cfg.get("EQUITY_TARGET_PCT", _DEFAULT_EQUITY_TARGET_PCT))
        self._max_daily_trades = int(self._cfg.get("EQUITY_MAX_DAILY_TRADES", _DEFAULT_EQUITY_MAX_DAILY_TRADES))
        self._default_qty = int(self._cfg.get("EQUITY_DEFAULT_QTY", _DEFAULT_EQUITY_DEFAULT_QTY))

    @property
    def positions(self) -> dict[str, dict[str, Any]]:
        """Return a snapshot of current equity positions."""
        with self._lock:
            return dict(self._positions)

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Start equity trading loop in background thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        log.info("[EQUITY] Equity trader started with %d symbols", len(self._equity_symbols))
        self._send_fn("[EQUITY] Equity trader started", critical=False)

    def stop(self) -> None:
        """Stop equity trading loop gracefully."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        log.info("[EQUITY] Equity trader stopped")

    def can_trade(self) -> tuple[bool, str]:
        """Check if equity trading is currently allowed."""
        if not self._equity_symbols:
            return False, "No equity symbols configured"
        if not self._is_market_open():
            return False, "Market closed"
        with self._lock:
            if self._daily_trades >= self._max_daily_trades:
                return False, f"Max daily trades ({self._max_daily_trades}) reached"
        return True, "Equity trading allowed"

    def get_position_size(self, symbol: str, price: float) -> int:
        """Determine position size for an equity entry."""
        if price <= 0:
            return self._default_qty
        # Simple sizing based on default quantity
        return self._default_qty

    def enter_position(self, symbol: str, direction: str, score: int,
                       reason: str = "") -> bool:
        """Enter an equity position with risk checks."""
        if not self._is_market_open():
            log.info("[EQUITY] %s: market closed — cannot enter", symbol)
            return False

        with self._lock:
            if self._daily_trades >= self._max_daily_trades:
                log.info("[EQUITY] %s: max daily trades reached", symbol)
                return False
            if symbol in self._positions:
                log.info("[EQUITY] %s: already have position", symbol)
                return False

        # Reentry evaluator check
        _rt = self._reentry_trackers.get(symbol)
        if _rt is not None:
            reentry_dec = _rt.evaluate_reentry(
                current_score=score,
                current_direction=direction,
                cfg=self._cfg,
            )
            if not reentry_dec.allowed:
                log.info("[EQUITY] %s: reentry blocked — %s", symbol, reentry_dec.reason)
                return False

        price = self._get_price_fn(symbol)
        if price is None or price <= 0:
            log.warning("[EQUITY] %s: cannot get price", symbol)
            return False

        qty = self.get_position_size(symbol, price)
        entry_price = price

        if self._execute_entry_fn is not None:
            try:
                result = self._execute_entry_fn(symbol, direction, qty, entry_price)
                if not result:
                    return False
            except (ValueError, TypeError, OSError) as e:
                log.error("[EQUITY] %s: entry failed — %s", symbol, e)
                return False

        with self._lock:
            self._positions[symbol] = {
                "direction": direction,
                "qty": qty,
                "entry_price": entry_price,
                "entry_time": time.time(),
                "score": score,
                "reason": reason,
                "peak_price": entry_price,
            }
            self._daily_trades += 1

        log.info("[EQUITY] Entered %s %s x%d @ %.2f (score=%d)",
                 symbol, direction, qty, entry_price, score)
        self._send_fn(f"[EQUITY] Entered {symbol} {direction} x{qty} @ {entry_price:.2f}")
        return True

    def exit_position(self, symbol: str, reason: str) -> bool:
        """Exit an equity position."""
        with self._lock:
            if symbol not in self._positions:
                return False
            pos = self._positions.pop(symbol)

        current_price = self._get_price_fn(symbol) or pos["entry_price"]
        pnl = (current_price - pos["entry_price"]) * pos["qty"]
        if pos.get("direction") == "SELL":
            pnl = (pos["entry_price"] - current_price) * pos["qty"]

        if self._execute_exit_fn is not None:
            try:
                self._execute_exit_fn(symbol, pos["qty"], current_price)
            except (ValueError, TypeError, OSError) as e:
                log.error("[EQUITY] %s: exit execution failed — %s", symbol, e)

        log.info("[EQUITY] Exited %s: %s @ %.2f (P&L=%.0f)", symbol, reason, current_price, pnl)
        self._send_fn(f"[EQUITY] Exited {symbol}: {reason} @ {current_price:.2f} P&L={pnl:.0f}")
        self._record_trade_outcome(symbol, pnl > 0)
        return True

    def _record_trade_outcome(self, symbol: str, was_profit: bool) -> None:
        """Record trade outcome for reentry tracking."""
        _rt = self._reentry_trackers.get(symbol)
        if _rt is not None:
            if was_profit:
                _rt._wins += 1
            else:
                _rt._losses += 1

    def _is_market_open(self) -> bool:
        """Check if equity market is currently open."""
        now = now_ist()
        if now.weekday() >= 5:
            return False
        open_mins = _EQUITY_MARKET_OPEN[0] * 60 + _EQUITY_MARKET_OPEN[1]
        close_mins = _EQUITY_MARKET_CLOSE[0] * 60 + _EQUITY_MARKET_CLOSE[1]
        current_mins = now.hour * 60 + now.minute
        return open_mins <= current_mins < close_mins

    def _monitor_positions(self) -> None:
        """Monitor open equity positions for SL/Target conditions."""
        for symbol in list(self._positions.keys()):
            with self._lock:
                if symbol not in self._positions:
                    continue
                pos = dict(self._positions[symbol])

            current_price = self._get_price_fn(symbol)
            if current_price is None or current_price <= 0:
                continue

            entry_price = pos["entry_price"]
            if entry_price <= 0:
                continue

            # Update peak tracking
            if current_price > pos.get("peak_price", entry_price):
                with self._lock:
                    if symbol in self._positions:
                        self._positions[symbol]["peak_price"] = current_price

            direction = pos.get("direction", "BUY")
            move_pct = (current_price - entry_price) / entry_price

            if direction == "BUY":
                # SL: price dropped below stop-loss
                if move_pct <= -(1.0 - self._sl_pct):
                    self.exit_position(symbol, "SL_HIT")
                    continue
                # Target: price hit target
                if move_pct >= (self._target_pct - 1.0):
                    self.exit_position(symbol, "TARGET_HIT")
                    continue
            else:  # SELL
                if move_pct >= (1.0 - self._sl_pct):
                    self.exit_position(symbol, "SL_HIT")
                    continue
                if move_pct <= -(self._target_pct - 1.0):
                    self.exit_position(symbol, "TARGET_HIT")
                    continue

    def _run_loop(self) -> None:
        """Main equity trading loop."""
        scan_interval = max(10, int(self._cfg.get("SCAN_INTERVAL", 30)))

        while self._running and not self._stop_event.is_set():
            try:
                self._reset_daily_if_needed()
                self._monitor_positions()
            except (ValueError, TypeError, OSError) as e:
                log.warning("[EQUITY] Loop error: %s", e)

            self._stop_event.wait(scan_interval)

        log.info("[EQUITY] Trading loop stopped")

    def _reset_daily_if_needed(self) -> None:
        """Reset daily counters at the start of a new trading day."""
        today = now_ist().strftime("%Y-%m-%d")
        with self._lock:
            if self._current_day != today:
                self._current_day = today
                self._daily_trades = 0
                for _rt_name, _rt in self._reentry_trackers.items():
                    try:
                        _rt.reset_daily()
                    except (ValueError, TypeError, AttributeError):
                        pass

    def status(self) -> dict[str, Any]:
        """Return current equity trader status."""
        with self._lock:
            return {
                "running": self._running,
                "symbols": list(self._equity_symbols),
                "positions": len(self._positions),
                "daily_trades": self._daily_trades,
                "max_daily_trades": self._max_daily_trades,
                "sl_pct": self._sl_pct,
                "target_pct": self._target_pct,
            }


def run_equity_trader(
    cfg: dict[str, Any] | None = None,
    send_fn: Callable | None = None,
    get_price_fn: Callable[[str], float | None] | None = None,
    execute_entry_fn: Callable | None = None,
    execute_exit_fn: Callable | None = None,
) -> EquityTrader:
    """Create and start an EquityTrader instance.

    Args:
        cfg: Configuration dict (expects EQUITY_MAP, EQUITY_PRIORITY keys)
        send_fn: Notification function
        get_price_fn: Price fetch function
        execute_entry_fn: Entry execution callback
        execute_exit_fn: Exit execution callback

    Returns:
        Started EquityTrader instance
    """
    trader = EquityTrader(
        cfg=cfg,
        send_fn=send_fn,
        get_price_fn=get_price_fn,
        execute_entry_fn=execute_entry_fn,
        execute_exit_fn=execute_exit_fn,
    )
    trader.start()
    return trader
