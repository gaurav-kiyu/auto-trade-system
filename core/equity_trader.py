"""
Equity Trader (v2.54) - Stock, ETF, REIT, InvIT & SME (cash market) trading module.

Supports trading NSE/BSE cash market instruments using config-driven asset maps:
  - EQUITY_MAP: Individual equity stocks (RELIANCE, TCS, HDFCBANK, etc.)
  - ETF_MAP: Exchange-traded funds (NIFTYBEES, BANKBEES, GOLDBEES, etc.)
  - REIT_MAP: Real Estate Investment Trusts (EMBASSY, MINDSPACE, BROOKFIELD)
  - INVIT_MAP: Infrastructure Investment Trusts (IRBINVIT, POWERGRID_INVIT)
  - SME_MAP: SME stocks (NSE Emerge / BSE SME)

Follows the same risk infrastructure as index options trading but adapted for
cash-market-specific characteristics:
  - Market hours: 09:15-15:30 IST (same as indices)
  - Position sizing based on price × lot size
  - Separate reentry trackers per instrument
  - No expiry day concerns for cash equities/ETFs
  - Uses yfinance for price data (.NS suffix)

Config keys:
    EQUITY_MAP / ETF_MAP / REIT_MAP / INVIT_MAP / SME_MAP: asset definitions
    EQUITY_PRIORITY / ETF_PRIORITY: scan order
    EQUITY_ENABLED / ETF_ENABLED / REIT_ENABLED / INVIT_ENABLED / SME_ENABLED
    EQUITY_DEFAULT_QTY / ETF_DEFAULT_QTY: default quantities
    EQUITY_MAX_DAILY_TRADES: max equity trades per day
    EQUITY_SL_PCT / EQUITY_TARGET_PCT: risk thresholds

Public API
----------
    EquityTrader          - Main equity/ETF/REIT/InvIT/SME trading engine
    run_equity_trader     - Standalone entry point
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from core.datetime_ist import now_ist
from core.reentry_evaluator import build_reentry_trackers

log = logging.getLogger(__name__)

# Default config values
_DEFAULT_EQUITY_PRIORITY = ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"]
_DEFAULT_ETF_PRIORITY = ["NIFTYBEES", "BANKBEES", "GOLDBEES", "SILVERBEES"]
_DEFAULT_EQUITY_SL_PCT = 0.95
_DEFAULT_EQUITY_TARGET_PCT = 1.05
_DEFAULT_EQUITY_MAX_DAILY_TRADES = 5
_DEFAULT_EQUITY_DEFAULT_QTY = 1
_DEFAULT_ETF_DEFAULT_QTY = 1
_EQUITY_MARKET_OPEN = (9, 15)
_EQUITY_MARKET_CLOSE = (15, 30)

# Map names for asset class config sections
_ASSET_MAP_NAMES = {
    "EQUITY": {"map_key": "EQUITY_MAP", "enabled_key": "EQUITY_ENABLED", "priority_key": "EQUITY_PRIORITY",
               "default_qty_key": "EQUITY_DEFAULT_QTY", "default_priority": _DEFAULT_EQUITY_PRIORITY,
               "default_qty": _DEFAULT_EQUITY_DEFAULT_QTY},
    "ETF":    {"map_key": "ETF_MAP",    "enabled_key": "ETF_ENABLED",    "priority_key": "ETF_PRIORITY",
               "default_qty_key": "ETF_DEFAULT_QTY", "default_priority": _DEFAULT_ETF_PRIORITY,
               "default_qty": _DEFAULT_ETF_DEFAULT_QTY},
    "REIT":   {"map_key": "REIT_MAP",   "enabled_key": "REIT_ENABLED",   "priority_key": None,
               "default_qty_key": None, "default_priority": None,
               "default_qty": 1},
    "INVIT":  {"map_key": "INVIT_MAP",  "enabled_key": "INVIT_ENABLED",  "priority_key": None,
               "default_qty_key": None, "default_priority": None,
               "default_qty": 1},
    "SME":    {"map_key": "SME_MAP",    "enabled_key": "SME_ENABLED",    "priority_key": None,
               "default_qty_key": None, "default_priority": None,
               "default_qty": 1},
}


def _build_asset_symbols(cfg: dict[str, Any], map_name: str) -> list[str]:
    """Build sorted list of enabled symbols from an asset map.

    Args:
        cfg: Config dict.
        map_name: One of 'EQUITY', 'ETF', 'REIT', 'INVIT', 'SME'.

    Returns:
        List of enabled symbol strings in priority order.
    """
    info = _ASSET_MAP_NAMES[map_name]
    # EQUITY defaults to enabled (backward compat), others default to disabled
    default_enabled = (map_name == "EQUITY")
    if not cfg.get(info["enabled_key"], default_enabled):
        return []

    asset_map = cfg.get(info["map_key"], {})
    # Priority list if available
    priority = cfg.get(info["priority_key"]) if info["priority_key"] else None
    if priority is not None:
        symbols = [sym for sym in priority if sym in asset_map and asset_map[sym].get("enabled", True)]
    else:
        # For REIT/INVIT/SME without priority, use all enabled symbols in key order
        symbols = [sym for sym, data in asset_map.items() if data.get("enabled", False)]

    return symbols


class EquityTrader:
    """Equity, ETF, REIT, InvIT & SME (cash market) trading engine.

    Manages positions across multiple asset classes with config-driven
    risk parameters, market hours, and position sizing. Thread-safe.
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

        # Build asset symbol lists from all enabled maps
        self._asset_map_index: dict[str, str] = {}  # symbol -> asset class name
        all_symbols: list[str] = []

        for asset_class in ("EQUITY", "ETF", "REIT", "INVIT", "SME"):
            symbols = _build_asset_symbols(self._cfg, asset_class)
            for sym in symbols:
                self._asset_map_index[sym] = asset_class
            all_symbols.extend(symbols)

        self._all_symbols = all_symbols
        # Backward compat: _equity_symbols is the EQUITY-only subset
        self._equity_symbols = _build_asset_symbols(self._cfg, "EQUITY")
        self._reentry_trackers: dict[str, Any] = build_reentry_trackers(self._all_symbols)

        # Risk parameters (shared across all asset classes)
        self._sl_pct = float(self._cfg.get("EQUITY_SL_PCT", _DEFAULT_EQUITY_SL_PCT))
        self._target_pct = float(self._cfg.get("EQUITY_TARGET_PCT", _DEFAULT_EQUITY_TARGET_PCT))
        self._max_daily_trades = int(self._cfg.get("EQUITY_MAX_DAILY_TRADES", _DEFAULT_EQUITY_MAX_DAILY_TRADES))

        # Backward compat: _default_qty = EQUITY class default quantity
        self._default_qty = int(self._cfg.get("EQUITY_DEFAULT_QTY", _DEFAULT_EQUITY_DEFAULT_QTY))

        # Per-asset-class default quantities (new)
        self._default_qtys: dict[str, int] = {}
        for asset_class, info in _ASSET_MAP_NAMES.items():
            qty_key = info.get("default_qty_key")
            if qty_key:
                self._default_qtys[asset_class] = int(self._cfg.get(qty_key, info["default_qty"]))
            else:
                self._default_qtys[asset_class] = info["default_qty"]

        # Count symbols per class for logging
        class_counts = {
            k: len(_build_asset_symbols(self._cfg, k))
            for k in ("EQUITY", "ETF", "REIT", "INVIT", "SME")
        }
        active_counts = {k: v for k, v in class_counts.items() if v > 0}
        log.info("[EQUITY] Loaded %d total symbols: %s", len(self._all_symbols), active_counts)

    @property
    def positions(self) -> dict[str, dict[str, Any]]:
        """Return a snapshot of current positions."""
        with self._lock:
            return dict(self._positions)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def all_symbols(self) -> list[str]:
        """Return all configured trading symbols across all asset classes."""
        return list(self._all_symbols)

    @property
    def equity_symbols(self) -> list[str]:
        """Return configured equity symbols (backward compat)."""
        return list(self._equity_symbols)

    def start(self) -> None:
        """Start trading loop in background thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        log.info("[EQUITY] Trader started with %d symbols across %d asset classes",
                 len(self._all_symbols),
                 len({self._asset_map_index[s] for s in self._all_symbols}))
        self._send_fn(f"[EQUITY] Trader started ({len(self._all_symbols)} symbols)", critical=False)

    def stop(self) -> None:
        """Stop trading loop gracefully."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        log.info("[EQUITY] Trader stopped")

    def can_trade(self) -> tuple[bool, str]:
        """Check if trading is currently allowed."""
        if not self._equity_symbols:
            return False, "No equity symbols configured"
        if not self._is_market_open():
            return False, "Market closed"
        with self._lock:
            if self._daily_trades >= self._max_daily_trades:
                return False, f"Max daily trades ({self._max_daily_trades}) reached"
        return True, "Trading allowed"

    def get_position_size(self, symbol: str, price: float) -> int:
        """Determine position size for an entry.

        Uses asset-class-specific default quantity.
        """
        if price <= 0:
            return self._default_qty
        asset_class = self._asset_map_index.get(symbol, "EQUITY")
        return self._default_qtys.get(asset_class, self._default_qty)

    def enter_position(self, symbol: str, direction: str, score: int,
                       reason: str = "") -> bool:
        """Enter a position with risk checks.

        Args:
            symbol: Trading symbol.
            direction: BUY or SELL.
            score: Signal score (0-100).
            reason: Optional entry reason description.

        Returns:
            True if position was entered.
        """
        if not self._is_market_open():
            log.info("[EQUITY] %s: market closed - cannot enter", symbol)
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
                log.info("[EQUITY] %s: reentry blocked - %s", symbol, reentry_dec.reason)
                return False

        price = self._get_price_fn(symbol)
        if price is None or price <= 0:
            log.warning("[EQUITY] %s: cannot get price", symbol)
            return False

        qty = self.get_position_size(symbol, price)
        entry_price = price

        asset_class = self._asset_map_index.get(symbol, "UNKNOWN")

        if self._execute_entry_fn is not None:
            try:
                result = self._execute_entry_fn(symbol, direction, qty, entry_price)
                if not result:
                    return False
            except (ValueError, TypeError, OSError) as e:
                log.error("[EQUITY] %s: entry failed - %s", symbol, e)
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
                "asset_class": asset_class,
            }
            self._daily_trades += 1

        log.info("[EQUITY] Entered %s [%s] %s x%d @ %.2f (score=%d)",
                 symbol, asset_class, direction, qty, entry_price, score)
        self._send_fn(f"[EQUITY] Entered {symbol} [{asset_class}] {direction} x{qty} @ {entry_price:.2f}")
        return True

    def exit_position(self, symbol: str, reason: str) -> bool:
        """Exit a position.

        Args:
            symbol: Trading symbol to exit.
            reason: Exit reason (SL_HIT, TARGET_HIT, MANUAL, etc.).

        Returns:
            True if position was found and exited.
        """
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
                log.error("[EQUITY] %s: exit execution failed - %s", symbol, e)

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
        """Check if cash market is currently open."""
        now = now_ist()
        if now.weekday() >= 5:
            return False
        open_mins = _EQUITY_MARKET_OPEN[0] * 60 + _EQUITY_MARKET_OPEN[1]
        close_mins = _EQUITY_MARKET_CLOSE[0] * 60 + _EQUITY_MARKET_CLOSE[1]
        current_mins = now.hour * 60 + now.minute
        return open_mins <= current_mins < close_mins

    def _monitor_positions(self) -> None:
        """Monitor open positions for SL/Target conditions."""
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
            move_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0.0

            if direction == "BUY":
                if move_pct <= -(1.0 - self._sl_pct):
                    self.exit_position(symbol, "SL_HIT")
                    continue
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
        """Main trading loop."""
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

    def evaluate_equity_signal(self, symbol: str, df1m: Any) -> dict[str, Any] | None:
        """Generate a comprehensive trading signal from 1m OHLCV data.

        Uses FeatureEngine indicators (VWAP, ATR, volume ratio, MACD, EMA trends,
        RSI, ADX, price deltas) — matching the indicator quality of the
        AdaptiveSignal pipeline used for index options. Score components are
        broken down per-contributor similar to ``core.pure_index_signal``.

        Returns a signal dict with keys: direction, score, price, strength,
        score_components, regime, features, risk, rsi, momentum_pct, vol_ratio,
        vwap, atr, symbol, macd — or None if no actionable signal or insufficient data.
        """
        if df1m is None or len(df1m) < 30:
            return None

        try:
            from core.feature_engine import FeatureEngine as _FE

            price      = _FE.get_price(df1m)
            vwap       = _FE.get_vwap(df1m)
            atr        = _FE.get_atr(df1m)
            vol_ratio  = _FE.get_vol_ratio(df1m)
            rsi_val    = _FE.get_rsi(df1m)
            macd       = _FE.get_macd(df1m)
            adx_val    = _FE.get_adx(df1m)
            d10        = _FE.price_delta(df1m, 10)
            d30        = _FE.price_delta(df1m, 30)  # longer-term momentum
            ema_trend  = _FE.ema_trend(df1m)

            if price <= 0:
                return None

            # ── Regime detection from ADX ─────────────────────────────────
            regime = "TRENDING" if adx_val > 25 else ("CHOPPY" if adx_val < 20 else "NEUTRAL")
            if adx_val < 15:
                regime = "WEAK"

            # ── Score components (modelled after core.pure_index_signal) ──
            _score = 0
            direction: str | None = None
            score_comps: dict[str, int] = {}

            # EMA trend direction
            if ema_trend == "UP":
                _score += 15
                score_comps["ema_trend"] = 15
                direction = "BUY" if direction is None else direction
            elif ema_trend == "DOWN":
                _score += 15
                score_comps["ema_trend"] = 15
                direction = "SELL" if direction is None else direction
            else:
                score_comps["ema_trend"] = 0

            # VWAP position check
            if price > vwap and direction == "BUY":
                _vwap_dist = abs(price - vwap) / max(vwap, 1.0)
                _vwap_pts = min(15, 5 + int(min(1.0, _vwap_dist / 0.005) * 10))
                _score += _vwap_pts
                score_comps["vwap"] = _vwap_pts
            elif price < vwap and direction == "SELL":
                _vwap_dist = abs(price - vwap) / max(vwap, 1.0)
                _vwap_pts = min(15, 5 + int(min(1.0, _vwap_dist / 0.005) * 10))
                _score += _vwap_pts
                score_comps["vwap"] = _vwap_pts
            else:
                score_comps["vwap"] = 0

            # Price momentum (10-bar)
            _d1_pts = 10 if (direction == "BUY" and d10 > 0) or (direction == "SELL" and d10 < 0) else 0
            _score += _d1_pts
            score_comps["momentum"] = _d1_pts

            # Longer momentum (30-bar)
            _d30_pts = 8 if (direction == "BUY" and d30 > 0) or (direction == "SELL" and d30 < 0) else 0
            _score += _d30_pts
            score_comps["momentum_30"] = _d30_pts

            # Volume confirmation
            if vol_ratio >= 1.2:
                _vol_excess = (vol_ratio - 1.2) / 1.2
                _vol_pts = min(12, 3 + int(min(1.0, _vol_excess) * 9))
                _score += _vol_pts
                score_comps["volume"] = _vol_pts
            else:
                score_comps["volume"] = 0

            # RSI healthy zone
            if direction == "BUY" and 40 <= rsi_val <= 70:
                score_comps["rsi_bonus"] = 8
                _score += 8
            elif direction == "SELL" and 30 <= rsi_val <= 60:
                score_comps["rsi_bonus"] = 8
                _score += 8
            else:
                score_comps["rsi_bonus"] = 0

            # ATR floor (minimum volatility to trade)
            if atr > price * 0.001:
                score_comps["atr_floor"] = 5
                _score += 5
            else:
                score_comps["atr_floor"] = 0

            # MACD histogram direction
            if macd["histogram"] > 0 and direction == "BUY":
                score_comps["macd"] = 5
                _score += 5
            elif macd["histogram"] < 0 and direction == "SELL":
                score_comps["macd"] = 5
                _score += 5
            else:
                score_comps["macd"] = 0

            # ADX trend bonus
            if adx_val >= 25:
                score_comps["adx_trend"] = 5
                _score += 5
            else:
                score_comps["adx_trend"] = 0

            # Regime penalty
            if regime == "CHOPPY":
                _pen = 8
                _score = max(0, _score - _pen)
                score_comps["regime_penalty"] = -_pen
            elif regime == "WEAK":
                _pen = 15
                _score = max(0, _score - _pen)
                score_comps["regime_penalty"] = -_pen
            else:
                score_comps["regime_penalty"] = 0

            # Clamp final score
            score = min(100, max(0, _score))

            # ── Strength classification ───────────────────────────────────
            if score >= 75:
                strength = "STRONG"
            elif score >= 55:
                strength = "MODERATE"
            elif score >= 35:
                strength = "WEAK"
            else:
                return None  # Not actionable

            # Features list (positive contributors)
            features = [k for k, v in score_comps.items() if v > 0]

            # ── Risk metadata ─────────────────────────────────────────────
            risk = {
                "atr_pct": round(atr / max(price, 1.0) * 100, 2),
                "regime": regime,
                "adx": round(adx_val, 1),
                "volatility_tier": "HIGH" if atr / max(price, 1.0) > 0.02 else "NORMAL",
            }

            return {
                "direction": direction,
                "score": score,
                "price": price,
                "strength": strength,
                "score_components": score_comps,
                "features": features,
                "regime": regime,
                "risk": risk,
                "rsi": round(rsi_val, 1),
                "momentum_pct": round(d10 / max(price, 1.0) * 100, 2),
                "vol_ratio": round(vol_ratio, 2),
                "vwap": round(vwap, 2),
                "atr": round(atr, 2),
                "adx": round(adx_val, 1),
                "macd": macd,
                "symbol": symbol,
            }
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as e:
            log.debug("[EQUITY] Signal eval failed for %s: %s", symbol, e)
            return None

    def status(self) -> dict[str, Any]:
        """Return current trader status with per-asset-class breakdown."""
        with self._lock:
            # Count positions by asset class
            positions_by_class: dict[str, int] = {}
            for pos_data in self._positions.values():
                ac = pos_data.get("asset_class", "UNKNOWN")
                positions_by_class[ac] = positions_by_class.get(ac, 0) + 1

            symbols_by_class: dict[str, int] = {}
            for sym, ac in self._asset_map_index.items():
                symbols_by_class[ac] = symbols_by_class.get(ac, 0) + 1

            return {
                "running": self._running,
                "symbols": list(self._all_symbols),
                "symbols_by_class": symbols_by_class,
                "positions": len(self._positions),
                "positions_by_class": positions_by_class,
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
        cfg: Configuration dict (expects EQUITY_MAP, ETF_MAP, etc.)
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


__all__ = [
    "EquityTrader",
    "log",
    "run_equity_trader",
]

