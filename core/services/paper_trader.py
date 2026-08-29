"""Paper Trading Handler — v2.57.0 Enhanced Realistic Simulation.

Handles simulated order execution for paper trading mode with realistic
broker-grade simulation including:
- Bid-ask spread simulation based on symbol volatility
- Partial fill simulation for large orders
- Market impact model (large orders move price)
- Random walk price evolution between calls
- Full Indian broker commission structure (STT, exchange, GST, SEBI)
- Volume/OI-based fill constraints
- Realistic fill delays with variance

Extracted from ``core/services/execution_service.py`` god object
decomposition and enhanced for live-like paper trading experience.
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from datetime import datetime
from typing import Any

from core.datetime_ist import now_ist
from core.ports.execution.execution_port import (
    ExecutionContext,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
)
from core.slippage_model import SlippageModel

_log = logging.getLogger(__name__)


# ── Default price map with volatility and spread metadata ─────────────────────

_SYMBOL_META: dict[str, dict] = {
    "NIFTY":      {"price": 23500.0, "volatility": 0.008, "spread_pct": 0.005, "lot_size": 50,  "oi_lakh": 150},
    "BANKNIFTY":  {"price": 50500.0, "volatility": 0.010, "spread_pct": 0.008, "lot_size": 25,  "oi_lakh": 80},
    "FINNIFTY":   {"price": 22000.0, "volatility": 0.007, "spread_pct": 0.004, "lot_size": 40,  "oi_lakh": 60},
    "NIFTYIT":    {"price": 35000.0, "volatility": 0.012, "spread_pct": 0.010, "lot_size": 25,  "oi_lakh": 20},
    "RELIANCE":   {"price": 3000.0,  "volatility": 0.015, "spread_pct": 0.010, "lot_size": 250, "oi_lakh": 200},
    "TCS":        {"price": 3900.0,  "volatility": 0.012, "spread_pct": 0.008, "lot_size": 150, "oi_lakh": 100},
    "HDFCBANK":   {"price": 1650.0,  "volatility": 0.014, "spread_pct": 0.010, "lot_size": 200, "oi_lakh": 180},
    "INFY":       {"price": 1600.0,  "volatility": 0.016, "spread_pct": 0.012, "lot_size": 300, "oi_lakh": 120},
    "ICICIBANK":  {"price": 1150.0,  "volatility": 0.015, "spread_pct": 0.012, "lot_size": 300, "oi_lakh": 160},
    "KOTAKBANK":  {"price": 1750.0,  "volatility": 0.013, "spread_pct": 0.010, "lot_size": 150, "oi_lakh": 80},
    "SBIN":       {"price": 800.0,   "volatility": 0.018, "spread_pct": 0.015, "lot_size": 350, "oi_lakh": 200},
    "LT":         {"price": 3600.0,  "volatility": 0.014, "spread_pct": 0.010, "lot_size": 150, "oi_lakh": 90},
    "BHARTIARTL": {"price": 1300.0,  "volatility": 0.014, "spread_pct": 0.012, "lot_size": 300, "oi_lakh": 100},
    "ASIANPAINT": {"price": 2700.0,  "volatility": 0.012, "spread_pct": 0.010, "lot_size": 200, "oi_lakh": 50},
    "MARUTI":     {"price": 11500.0, "volatility": 0.011, "spread_pct": 0.008, "lot_size": 50,  "oi_lakh": 30},
    "HINDUNILVR": {"price": 2500.0,  "volatility": 0.010, "spread_pct": 0.008, "lot_size": 200, "oi_lakh": 70},
    "AXISBANK":   {"price": 1100.0,  "volatility": 0.016, "spread_pct": 0.013, "lot_size": 300, "oi_lakh": 130},
}

_DEFAULT_META = {"price": 1000.0, "volatility": 0.015, "spread_pct": 0.010, "lot_size": 100, "oi_lakh": 50}


# ── Indian Broker Commission Calculator ───────────────────────────────────────

def _compute_indian_commission(
    trade_value: float,
    is_options: bool = True,
    is_intraday: bool = True,
) -> dict[str, float]:
    """Calculate realistic Indian broker charges for a trade.

    Args:
        trade_value: Notional trade value (price × qty × lot_size)
        is_options: True for options, False for equity
        is_intraday: True for intraday, False for delivery

    Returns:
        Dict with individual charge components and total
    """
    total = 0.0
    charges: dict[str, float] = {}

    # Brokerage: Zerodha-style ₹20 per executed order or 0.03% (whichever lower)
    pct_brokerage = trade_value * 0.0003  # 0.03%
    charges["brokerage"] = round(min(pct_brokerage, 20.0), 2)
    total += charges["brokerage"]

    # STT (Securities Transaction Tax): 0.05% on sell side for options
    if is_options:
        charges["stt"] = round(trade_value * 0.0005, 2)  # 0.05% on sell
    else:
        stt_rate = 0.00025 if is_intraday else 0.001
        charges["stt"] = round(trade_value * stt_rate, 2)
    total += charges["stt"]

    # Exchange transaction charges: NSE ~₹2 per lakh (0.002%)
    charges["exchange"] = round(trade_value * 0.00002, 2)
    total += charges["exchange"]

    # GST: 18% on (brokerage + exchange charges)
    charges["gst"] = round((charges["brokerage"] + charges["exchange"]) * 0.18, 2)
    total += charges["gst"]

    # SEBI turnover fees: ₹10 per crore (0.0001%)
    charges["sebi"] = round(trade_value * 0.000001, 2)
    total += charges["sebi"]

    # Stamp duty: 0.002% for options
    charges["stamp_duty"] = round(trade_value * 0.00002, 2)
    total += charges["stamp_duty"]

    charges["total"] = round(total, 2)
    return charges


class PaperTrader:
    """Enhanced paper order execution with live-like simulation.

    Simulates realistic broker behavior including bid-ask spreads,
    partial fills, market impact, random walk prices, and full Indian
    broker commission structure (STT, exchange, GST, SEBI, stamp duty).

    Usage::

        trader = PaperTrader(fill_delay_ms=50, slippage_pct=0.05)
        result = trader.execute(order_request, execution_context)
    """

    def __init__(
        self,
        fill_delay_ms: int = 50,
        slippage_pct: float = 0.05,
        price_cache_max: int = 50,
        shutdown_event: threading.Event | None = None,
        enable_random_walk: bool = True,
        enable_partial_fills: bool = True,
        enable_market_impact: bool = True,
        enable_bid_ask_spread: bool = True,
        calibrated_slippage_model: SlippageModel | None = None,
    ) -> None:
        self._fill_delay_ms = fill_delay_ms
        self._slippage_pct = slippage_pct
        # Opt-in (default None = today's static slippage_pct, unchanged):
        # a caller-supplied model from core.slippage_model.calibrate_model(),
        # fit on real trade-journal history. Falls back to slippage_pct
        # whenever no model is supplied - never worse than today's realism.
        self._calibrated_slippage_model = calibrated_slippage_model
        self._price_cache_max = price_cache_max
        self._shutdown_event = shutdown_event or threading.Event()
        self._lock = threading.RLock()

        # Feature flags (all enabled by default for max realism)
        self._enable_random_walk = enable_random_walk
        self._enable_partial_fills = enable_partial_fills
        self._enable_market_impact = enable_market_impact
        self._enable_bid_ask_spread = enable_bid_ask_spread

        # Price simulation state
        self._paper_price_cache: dict[str, float] = {}
        self._price_timestamp: dict[str, datetime] = {}
        self._price_drift: dict[str, float] = {}  # Random walk drift per symbol
        self._last_trade_time: dict[str, datetime] = {}

        # Market impact state (price moves from large trades persist)
        self._impact_cache: dict[str, float] = {}  # Accumulated impact

        # Fill history for volume-based fill limiting
        self._recent_fills: dict[str, list[float]] = {}  # symbol -> list of trade values
        self._fill_window_minutes = 5  # Rolling window for fill rate limiting

    # ── Public API ────────────────────────────────────────────────────────

    def execute(
        self,
        order_request: OrderRequest,
        execution_context: ExecutionContext | None = None,
    ) -> OrderResult:
        """Execute a paper/simulated order with live-like simulation.

        Simulates the full order lifecycle:
        1. Pre-trade checks (market open, circuit limits)
        2. Fill delay (network + exchange processing)
        3. Price determination (with spread and impact)
        4. Partial fill determination
        5. Commission calculation (Indian broker structure)
        6. Post-trade price impact

        Args:
            order_request: The order to simulate
            execution_context: Execution context

        Returns:
            OrderResult with simulated fill or rejection
        """
        try:
            # Step 1: Pre-trade validation
            symbol = order_request.symbol
            base_price = self.get_current_price(symbol)
            lot_size = order_request.lot_size

            # Price sanity gates (matches real broker behavior)
            if base_price <= 0:
                return OrderResult(
                    order_id="price_error",
                    status=OrderStatus.REJECTED,
                    reject_reason=f"Invalid base price {base_price} for {symbol}",
                    timestamp=now_ist(),
                )

            # Circuit limit check (±20% from base, like real NSE circuit filters)
            if order_request.price and abs(order_request.price - base_price) / base_price > 0.20:
                return OrderResult(
                    order_id="circuit_block",
                    status=OrderStatus.REJECTED,
                    reject_reason=f"Order price {order_request.price} exceeds ±20% circuit limit from {base_price}",
                    timestamp=now_ist(),
                )

            # Step 2: Simulate network + exchange delay (randomized for realism)
            actual_delay = self._fill_delay_ms * random.uniform(0.5, 2.0)
            actual_delay = max(5, min(actual_delay, 5000))  # Clamp 5ms - 5s
            if self._shutdown_event.wait(actual_delay / 1000.0):
                return OrderResult(
                    order_id="shutdown",
                    status=OrderStatus.REJECTED,
                    reject_reason="Shutdown requested during paper fill delay",
                    timestamp=now_ist(),
                )

            # Step 3: Re-check price after delay (prices move while waiting)
            current_price = self._evolve_price(symbol, base_price)

            # Generate order ID matching broker format
            order_id = (
                f"paper_{int(time.time()*1000)}_"
                f"{hash(symbol) % 10000:04d}"
            )

            # Step 4: Compute fill price with bid-ask spread
            fill_info = self._compute_fill_price_with_spread(
                order_request, current_price, symbol
            )
            if fill_info is None:
                return OrderResult(
                    order_id=order_id,
                    status=OrderStatus.PENDING,
                    reject_reason="Limit order not executed — price not reached",
                    timestamp=now_ist(),
                )

            fill_price, filled_pct = fill_info

            # Step 5: Apply market impact (large orders move price)
            notional = fill_price * lot_size
            dir_str = order_request.direction.upper()
            if self._enable_market_impact and notional > 500000:  # >5L notional
                self._apply_market_impact(symbol, dir_str, notional, base_price)

            # Step 6: Calculate Indian broker commission
            is_options = "NIFTY" in symbol or "BANKNIFTY" in symbol or "FINNIFTY" in symbol
            commission_breakup = _compute_indian_commission(
                trade_value=fill_price * lot_size,
                is_options=is_options,
                is_intraday=True,
            )
            total_commission = commission_breakup["total"]

            # Step 7: Determine fill result
            if filled_pct < 100:
                # Partial fill
                filled_qty = max(1, int(lot_size * filled_pct / 100))
                return OrderResult(
                    order_id=order_id,
                    status=OrderStatus.PARTIALLY_FILLED,
                    filled_quantity=filled_qty,
                    average_price=round(fill_price, 2),
                    commission=round(total_commission * filled_qty / max(lot_size, 1), 2),
                    timestamp=now_ist(),
                )

            # Full fill
            return OrderResult(
                order_id=order_id,
                status=OrderStatus.FILLED,
                filled_quantity=lot_size,
                average_price=round(fill_price, 2),
                commission=round(total_commission, 2),
                timestamp=now_ist(),
            )

        except (ValueError, OSError, AttributeError, ConnectionError) as e:
            _log.error("Error in paper order execution: %s", e, exc_info=True)
            return OrderResult(
                order_id="paper_error",
                status=OrderStatus.REJECTED,
                reject_reason=str(e),
                timestamp=now_ist(),
            )

    def get_current_price(self, symbol: str) -> float:
        """Get current price for a symbol with random walk price evolution.

        Each call evolves the price slightly (simulating real market ticks),
        making paper trading feel like a live market.

        Args:
            symbol: Trading symbol

        Returns:
            Current simulated price
        """
        with self._lock:
            now = now_ist()
            meta = _SYMBOL_META.get(symbol, _DEFAULT_META)
            volatility = meta["volatility"]

            # Initialize if not cached
            if symbol not in self._paper_price_cache:
                self._paper_price_cache[symbol] = meta["price"]
                self._price_timestamp[symbol] = now
                self._price_drift[symbol] = random.gauss(0, volatility)
                # Enforce cache size limit (evict oldest entries)
                self._evict_oldest_if_needed()
                return meta["price"]

            current = self._paper_price_cache[symbol]
            last_time = self._price_timestamp.get(symbol, now)

            # Evolve price using random walk (only if random walk is enabled)
            if self._enable_random_walk:
                elapsed_seconds = max(0.1, (now - last_time).total_seconds())

                # Scale volatility by sqrt(time) like real markets
                time_factor = math.sqrt(elapsed_seconds / 60.0)  # Per-minute scaling
                step = volatility * time_factor

                # Random walk with mean reversion drift
                drift = self._price_drift.get(symbol, 0)
                noise = random.gauss(0, step)

                # Apply drift decay (pulls back toward mean)
                drift *= 0.95  # Mean reversion
                drift += random.gauss(0, step * 0.3)
                self._price_drift[symbol] = drift

                # Apply any accumulated market impact
                impact = self._impact_cache.get(symbol, 0)
                self._impact_cache[symbol] = impact * 0.9  # Impact decays

                new_price = current + noise + drift + impact
                new_price = max(new_price, current * 0.95)  # Prevent >5% drops per tick
                new_price = min(new_price, current * 1.05)  # Prevent >5% jumps per tick

                self._paper_price_cache[symbol] = round(new_price, 2)
                self._price_timestamp[symbol] = now

            # Enforce cache size limit (evict oldest entries)
            self._evict_oldest_if_needed()

            return self._paper_price_cache[symbol]

    def shutdown(self) -> None:
        """Signal shutdown to interrupt pending fill delays."""
        self._shutdown_event.set()

    def reset(self) -> None:
        """Reset paper trader state completely.

        Clears price cache, market impact, drift state, and fill history.
        Does NOT reset shutdown event (safety: must be explicitly cleared).
        """
        with self._lock:
            self._paper_price_cache.clear()
            self._price_timestamp.clear()
            self._price_drift.clear()
            self._impact_cache.clear()
            self._recent_fills.clear()
            self._last_trade_time.clear()

    def get_commission_breakdown(self, symbol: str, price: float, qty: int) -> dict[str, float]:
        """Get detailed commission breakdown for a trade.

        Useful for displaying to the user for transparency.

        Args:
            symbol: Trading symbol
            price: Fill price
            qty: Lot quantity

        Returns:
            Dict with commission components
        """
        is_options = "NIFTY" in symbol or "BANKNIFTY" in symbol or "FINNIFTY" in symbol
        return _compute_indian_commission(
            trade_value=price * qty,
            is_options=is_options,
            is_intraday=True,
        )

    def get_market_snapshot(self, symbol: str) -> dict[str, Any]:
        """Get a snapshot of current simulated market conditions.

        Args:
            symbol: Trading symbol

        Returns:
            Dict with bid, ask, last, spread, volatility
        """
        meta = _SYMBOL_META.get(symbol, _DEFAULT_META)
        price = self.get_current_price(symbol)
        spread = price * meta["spread_pct"] / 100.0

        return {
            "symbol": symbol,
            "last_price": round(price, 2),
            "bid": round(price - spread / 2, 2),
            "ask": round(price + spread / 2, 2),
            "spread": round(spread, 2),
            "spread_pct": round(meta["spread_pct"], 4),
            "volatility": round(meta["volatility"], 4),
            "lot_size": meta["lot_size"],
            "timestamp": now_ist().isoformat(),
        }

    # ── Internal fill simulation ──────────────────────────────────────────

    def _compute_fill_price_with_spread(
        self,
        order_request: OrderRequest,
        base_price: float,
        symbol: str,
    ) -> tuple[float, float] | None:
        """Compute fill price with bid-ask spread and partial fill logic.

        Returns:
            (fill_price, fill_pct) or None if limit order not triggered
        """
        meta = _SYMBOL_META.get(symbol, _DEFAULT_META)
        spread_pct = meta["spread_pct"] / 100.0 if self._enable_bid_ask_spread else 0.0

        # Calculate bid and ask prices
        half_spread = base_price * spread_pct / 2
        bid = base_price - half_spread
        ask = base_price + half_spread

        direction = order_request.direction.upper()
        ot = order_request.order_type

        if ot == OrderType.MARKET:
            # Market order fills at ask (buy) or bid (sell) like real exchange
            fill_price = ask if direction == "BUY" else bid

            # Add additional slippage for market orders (your configurable %),
            # or a calibrated prediction when a slippage model was supplied.
            slippage_pct_value = self._slippage_pct
            if self._calibrated_slippage_model is not None:
                from core.slippage_model import predict_slippage
                slippage_pct_value = predict_slippage(
                    order_request.lot_size, meta["spread_pct"], self._calibrated_slippage_model,
                )
            slippage = base_price * (slippage_pct_value / 100.0)
            if direction == "BUY":
                fill_price += slippage
            else:
                fill_price -= slippage

            fill_price = max(0.01, fill_price)

            # Partial fill for large orders
            fill_pct = self._compute_fill_pct(
                symbol, fill_price * order_request.lot_size, order_request.lot_size
            )
            return fill_price, fill_pct

        if ot == OrderType.LIMIT:
            if not order_request.price:
                return base_price, 100.0
            # Limit order fills only if price is achievable
            if direction == "BUY":
                # Buy limit: order price must be >= ask (to fill immediately)
                if order_request.price >= ask:
                    # Fill at the better of limit price or ask
                    fill_price = min(order_request.price, ask)
                    return fill_price, 100.0
                return None  # Would not fill immediately
            else:
                # Sell limit: order price must be <= bid
                if order_request.price <= bid:
                    fill_price = max(order_request.price, bid)
                    return fill_price, 100.0
                return None

        if ot in (OrderType.STOP_LOSS, OrderType.STOP_LOSS_MARKET):
            trigger = order_request.price or base_price
            # SL triggers when price crosses the trigger price
            if direction == "BUY":
                if base_price >= trigger:
                    return ask, 100.0
            else:
                if base_price <= trigger:
                    return bid, 100.0
            return None  # SL not triggered yet

        return base_price, 100.0

    def _compute_fill_pct(self, symbol: str, trade_value: float, lot_qty: int) -> float:
        """Compute fill percentage based on simulated liquidity.

        Large orders relative to OI get partial fills, just like real markets.
        """
        if not self._enable_partial_fills:
            return 100.0

        meta = _SYMBOL_META.get(symbol, _DEFAULT_META)
        oi_value = meta["oi_lakh"] * 100000 * meta["price"]  # Approximate notional OI

        # Fill rate based on order size relative to market OI
        if trade_value <= 0:
            return 100.0

        # Calculate size relative to market
        size_ratio = trade_value / max(oi_value, 1)

        with self._lock:
            # Check recent fill volume
            recent = self._recent_fills.get(symbol, [])
            # Filter out fills older than the window. Timestamps are real epoch
            # (time.time()) so compare epoch-to-epoch; converting a naive IST
            # datetime via time.mktime() is machine-TZ-dependent and silently
            # mis-dates the window on non-IST (e.g. UTC CI) hosts.
            cutoff_epoch = time.time() - self._fill_window_minutes * 60
            recent_fresh = [v for v in recent if v > cutoff_epoch]
            recent_total = len(recent_fresh)

            # Fill rate limiting
            if recent_total > 20:  # More than 20 fills in 5 min = reduced fills
                base_fill = max(20, 100 - recent_total * 2)
            else:
                base_fill = 100.0

            # Size-based reduction
            if size_ratio > 0.01:  # >1% of OI
                size_factor = max(10, 100 * (0.01 / max(size_ratio, 0.0001)))
                base_fill = min(base_fill, size_factor)

            # Store this fill for rate limiting
            recent_fresh.append(time.time())
            self._recent_fills[symbol] = recent_fresh[-100:]  # Keep last 100

            # Only apply randomness if fill was reduced (realistic variance)
            if base_fill >= 100.0:
                fill_pct = 100.0
            else:
                fill_pct = base_fill * random.uniform(0.9, 1.0)
            return max(5, min(100, fill_pct))

    def _apply_market_impact(self, symbol: str, direction: str, notional: float, base_price: float) -> None:
        """Apply post-trade market impact (price moves against large orders)."""
        with self._lock:
            meta = _SYMBOL_META.get(symbol, _DEFAULT_META)
            oi_value = meta["oi_lakh"] * 100000 * meta["price"]
            size_ratio = notional / max(oi_value, 1)

            # Impact = 0.1% price move per 1% of OI traded
            impact_pct = size_ratio * 0.1
            impact_pts = base_price * impact_pct

            # Impact pushes price in opposite direction of trade
            if direction == "BUY":
                accumulated = self._impact_cache.get(symbol, 0) + impact_pts
            else:
                accumulated = self._impact_cache.get(symbol, 0) - impact_pts

            # Clamp impact to prevent unrealistic moves
            max_impact = base_price * 0.002  # Max 0.2% impact
            self._impact_cache[symbol] = max(-max_impact, min(max_impact, accumulated))

    def _evict_oldest_if_needed(self) -> None:
        """Evict oldest cached entries if cache exceeds price_cache_max."""
        if len(self._paper_price_cache) > self._price_cache_max:
            excess = len(self._paper_price_cache) - self._price_cache_max
            for _ in range(excess):
                oldest = next(iter(self._paper_price_cache))
                del self._paper_price_cache[oldest]
                self._price_timestamp.pop(oldest, None)
                self._price_drift.pop(oldest, None)
                self._impact_cache.pop(oldest, None)

    def _evolve_price(self, symbol: str, base_price: float) -> float:
        """Evolve price to simulate real-time movement during fill delay.

        This makes fills feel realistic — the price you see when you submit
        may differ slightly from the fill price.
        """
        if not self._enable_random_walk:
            return base_price
        return self.get_current_price(symbol)

    # ── Legacy API (backward compatible) ──────────────────────────────────

    def _compute_fill_price(self, order_request: OrderRequest) -> float | None:
        """Legacy fill price computation for backward compatibility.

        Deprecated: Use _compute_fill_price_with_spread instead.
        """
        result = self._compute_fill_price_with_spread(
            order_request,
            self.get_current_price(order_request.symbol),
            order_request.symbol,
        )
        if result is None:
            return None
        return result[0]

    # ── Static defaults (used by legacy get_current_price fallback) ────────

    @staticmethod
    def _lookup_default_price(symbol: str) -> float:
        """Return a reasonable default price for paper trading simulation."""
        meta = _SYMBOL_META.get(symbol, _DEFAULT_META)
        return meta["price"]


__all__ = ["PaperTrader", "_compute_indian_commission", "_SYMBOL_META"]
