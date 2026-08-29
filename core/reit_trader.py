"""REIT & InvIT Trader (v2.57.0) — NSE/BSE REIT/InvIT trading engine.

Supports NSE/BSE REIT and InvIT trading with:
  - Config-driven REIT_MAP / INVIT_MAP for enabled symbols
  - REIT/InvIT-specific market hours (same as cash: 09:15-15:30)
  - Distribution yield tracking for total return
  - Sector-level exposure monitoring
  - NAV-based position monitoring
  - Special tax treatment awareness

Config keys:
    REIT_ENABLED / INVIT_ENABLED: true/false
    REIT_MAP / INVIT_MAP: symbol definitions
    REIT_PRIORITY / INVIT_PRIORITY: scan order
    REIT_SL_PCT / REIT_TARGET_PCT: risk thresholds
    REIT_DEFAULT_QTY: default lot size
    REIT_MAX_DAILY_TRADES: daily trade limit

Usage:
    from core.reit_trader import REITTrader, run_reit_trader
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from core.datetime_ist import now_ist
from core.reentry_evaluator import build_reentry_trackers

_log = logging.getLogger(__name__)

_DEFAULT_REIT_SYMBOLS = ["EMBASSY", "MINDSPACE", "BROOKFIELD"]
_DEFAULT_INVIT_SYMBOLS = ["IRBINVIT", "POWERGRID_INVIT", "INDUCT_INVIT"]
_DEFAULT_SL_PCT = 0.93
_DEFAULT_TARGET_PCT = 1.07
_DEFAULT_MAX_DAILY = 5
_DEFAULT_QTY = 1
_REIT_OPEN = (9, 15)
_REIT_CLOSE = (15, 30)


class REITTradePosition:
    """An open REIT or InvIT position.

    Attributes:
        symbol: Trading symbol.
        direction: BUY or SELL.
        qty: Number of units.
        entry_price: Average entry price.
        current_price: Latest available price.
        nav_price: Net asset value per unit.
        distribution_yield: Annual distribution yield (fraction).
        trust_type: REIT or INVIT.
        sector: Property/infrastructure sector.
        aum_crores: Assets under management.
        entry_time: Timestamp of entry.
    """

    def __init__(
        self,
        symbol: str,
        direction: str,
        qty: int,
        entry_price: float,
        current_price: float = 0.0,
        nav_price: float = 0.0,
        distribution_yield: float = 0.0,
        trust_type: str = "REIT",
        sector: str = "",
        aum_crores: float = 0.0,
        entry_time: float = 0.0,
        asset_class: str = "REIT",
        score: int = 0,
        reason: str = "",
    ) -> None:
        self.symbol = symbol
        self.direction = direction
        self.qty = qty
        self.entry_price = entry_price
        self.current_price = current_price
        self.nav_price = nav_price
        self.distribution_yield = distribution_yield
        self.trust_type = trust_type
        self.sector = sector
        self.aum_crores = aum_crores
        self.entry_time = entry_time
        self.asset_class = asset_class
        self.score = score
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "nav_price": self.nav_price,
            "distribution_yield": self.distribution_yield,
            "trust_type": self.trust_type,
            "sector": self.sector,
            "aum_crores": self.aum_crores,
            "entry_time": self.entry_time,
            "asset_class": self.asset_class,
            "score": self.score,
            "reason": self.reason,
        }


class REITTrader:
    """NSE/BSE REIT & InvIT trading engine.

    Manages REIT/InvIT positions with NAV tracking, distribution yield awareness,
    sector-level exposure monitoring, and config-driven risk parameters.
    Thread-safe.
    """

    def __init__(
        self,
        cfg: dict[str, Any] | None = None,
        send_fn: Callable | None = None,
        get_price_fn: Callable[[str], float | None] | None = None,
        get_nav_fn: Callable[[str], float | None] | None = None,
        execute_entry_fn: Callable | None = None,
        execute_exit_fn: Callable | None = None,
    ):
        self._cfg = cfg or {}
        self._send_fn = send_fn or (lambda msg, critical=False, **kw: None)
        self._get_price_fn = get_price_fn or (lambda sym: None)
        self._get_nav_fn = get_nav_fn or (lambda sym: None)
        self._execute_entry_fn = execute_entry_fn
        self._execute_exit_fn = execute_exit_fn
        self._lock = threading.RLock()
        self._positions: dict[str, REITTradePosition] = {}
        self._daily_trades = 0
        self._current_day: str | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Initialize per-symbol trust type maps BEFORE building symbols
        self._trust_types: dict[str, str] = self._init_trust_types()
        # Build symbol lists from REIT_MAP and INVIT_MAP
        self._symbols = self._build_all_symbols()
        self._reentry_trackers = build_reentry_trackers(self._symbols)

        # Risk parameters (shared across REIT and InvIT)
        self._sl_pct = float(self._cfg.get("REIT_SL_PCT", _DEFAULT_SL_PCT))
        self._target_pct = float(self._cfg.get("REIT_TARGET_PCT", _DEFAULT_TARGET_PCT))
        self._max_daily = int(self._cfg.get("REIT_MAX_DAILY_TRADES", _DEFAULT_MAX_DAILY))
        self._default_qty = int(self._cfg.get("REIT_DEFAULT_QTY", _DEFAULT_QTY))

        _log.info("[REIT] Loaded %d symbols", len(self._symbols))

    def _init_trust_types(self) -> dict[str, str]:
        """Build a symbol -> trust_type map from REIT_MAP and INVIT_MAP config."""
        trust_types: dict[str, str] = {}
        for trust_type, map_key in [("REIT", "REIT_MAP"), ("INVIT", "INVIT_MAP")]:
            amap = self._cfg.get(map_key, {})
            for sym, meta in amap.items():
                if meta.get("enabled", True):
                    trust_types[sym] = trust_type
        return trust_types

    def _build_all_symbols(self) -> list[str]:
        symbols: list[str] = []
        for trust_type, map_key, enabled_key, priority_key, default_priority in [
            ("REIT", "REIT_MAP", "REIT_ENABLED", "REIT_PRIORITY", _DEFAULT_REIT_SYMBOLS),
            ("INVIT", "INVIT_MAP", "INVIT_ENABLED", "INVIT_PRIORITY", _DEFAULT_INVIT_SYMBOLS),
        ]:
            if not self._cfg.get(enabled_key, False):
                continue
            asset_map = self._cfg.get(map_key, {})
            priority = self._cfg.get(priority_key, default_priority)
            for sym in priority:
                if sym in asset_map and asset_map[sym].get("enabled", True):
                    symbols.append(sym)
        return symbols

    @property
    def positions(self) -> dict[str, Any]:
        with self._lock:
            return {k: v.to_dict() for k, v in self._positions.items()}

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
        _log.info("[REIT] Trader started with %d symbols", len(self._symbols))
        self._send_fn(f"[REIT] Trader started ({len(self._symbols)} symbols)")

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        _log.info("[REIT] Trader stopped")

    def can_trade(self) -> tuple[bool, str]:
        if not self._symbols:
            return False, "No REIT/InvIT symbols configured"
        if not self._is_market_open():
            return False, "Market closed"
        with self._lock:
            if self._daily_trades >= self._max_daily:
                return False, f"Max daily trades ({self._max_daily}) reached"
        return True, "Trading allowed"

    def get_sector_exposure(self) -> dict[str, float]:
        """Return current position exposure by sector."""
        with self._lock:
            exposure: dict[str, float] = {}
            for pos in self._positions.values():
                sec = pos.sector or pos.trust_type
                exposure[sec] = exposure.get(sec, 0) + abs(pos.qty * pos.current_price)
            return exposure

    def _get_trust_type(self, symbol: str) -> str:
        """Determine if a symbol is REIT or InvIT."""
        return self._trust_types.get(symbol, "REIT")

    def enter_position(
        self, symbol: str, direction: str, score: int,
        entry_price: float = 0.0, reason: str = "", qty: int = 0,
    ) -> bool:
        if not self._is_market_open():
            _log.info("[REIT] %s: market closed", symbol)
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
                _log.info("[REIT] %s: reentry blocked", symbol)
                return False

        price = entry_price if entry_price > 0 else (self._get_price_fn(symbol) or 0)
        if price <= 0:
            _log.warning("[REIT] %s: invalid price", symbol)
            return False

        lot_qty = qty if qty > 0 else self._default_qty
        trust_type = self._get_trust_type(symbol)
        nav_price = self._get_nav_fn(symbol) or price

        # Lookup metadata from config
        asset_map = self._cfg.get("REIT_MAP" if trust_type == "REIT" else "INVIT_MAP", {})
        meta = asset_map.get(symbol, {})
        distribution_yield = float(meta.get("distribution_yield", 0.0))
        sector = str(meta.get("sector", ""))
        aum_crores = float(meta.get("aum_crores", 0.0))

        if self._execute_entry_fn is not None:
            try:
                if not self._execute_entry_fn(symbol, direction, lot_qty, price):
                    return False
            except (ValueError, TypeError, OSError) as e:
                _log.error("[REIT] %s: entry failed - %s", symbol, e)
                return False

        with self._lock:
            pos = REITTradePosition(
                symbol=symbol, direction=direction, qty=lot_qty,
                entry_price=price, current_price=price,
                nav_price=nav_price, distribution_yield=distribution_yield,
                trust_type=trust_type, sector=sector, aum_crores=aum_crores,
                entry_time=time.time(), score=score, reason=reason,
            )
            self._positions[symbol] = pos
            self._daily_trades += 1

        _log.info(
            "[REIT] Entered %s [%s] %s x%d @ %.2f (yield=%.2f%%)",
            symbol, trust_type, direction, lot_qty, price, distribution_yield * 100,
        )
        self._send_fn(
            f"[REIT] Entered {symbol} [{trust_type}] {direction} x{lot_qty} @ {price:.2f}"
        )
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
                _log.error("[REIT] %s: exit failed - %s", symbol, e)

        _log.info("[REIT] Exited %s: %s @ %.2f (P&L=%.0f)", symbol, reason, price, pnl)
        self._send_fn(f"[REIT] Exited {symbol}: {reason} @ {price:.2f} P&L={pnl:.0f}")
        rt = self._reentry_trackers.get(symbol)
        if rt is not None:
            rt.record_outcome(pnl > 0)
        return True

    def _is_market_open(self) -> bool:
        now = now_ist()
        if now.weekday() >= 5:
            return False
        open_mins = _REIT_OPEN[0] * 60 + _REIT_OPEN[1]
        close_mins = _REIT_CLOSE[0] * 60 + _REIT_CLOSE[1]
        current_mins = now.hour * 60 + now.minute
        return open_mins <= current_mins < close_mins

    def _monitor_positions(self) -> None:
        for symbol in list(self._positions.keys()):
            with self._lock:
                pos = self._positions.get(symbol)
                if pos is None:
                    continue

            price = self._get_price_fn(symbol)
            if price is None or price <= 0:
                continue

            with self._lock:
                if symbol in self._positions:
                    self._positions[symbol].current_price = price

            move_pct = (price - pos.entry_price) / max(pos.entry_price, 0.01)
            if pos.direction == "SELL":
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
                _log.warning("[REIT] Loop error: %s", e)
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
                "sector_exposure": self.get_sector_exposure(),
            }


def run_reit_trader(**kwargs: Any) -> REITTrader:
    trader = REITTrader(**kwargs)
    trader.start()
    return trader


__all__ = ["REITTradePosition", "REITTrader", "run_reit_trader"]
