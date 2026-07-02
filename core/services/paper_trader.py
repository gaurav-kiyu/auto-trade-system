"""Paper Trading Handler — extracted from ExecutionService god object.

Handles simulated order execution for paper trading mode, including
fill simulation with slippage, price caching, and realistic delay.

Extracted from ``core/services/execution_service.py`` god object
decomposition.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from core.datetime_ist import now_ist
from core.ports.execution.execution_port import (
    ExecutionContext,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
)

_log = logging.getLogger(__name__)


class PaperTrader:
    """Simulated paper order execution with realistic fill simulation.

    Handles all paper/simulated order execution including:
    - Market order fills with configurable slippage
    - Limit order price-gate checks
    - SL/SL-M trigger price simulation
    - Price caching with TTL
    - Shutdown-interruptible delay simulation

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
    ) -> None:
        self._fill_delay_ms = fill_delay_ms
        self._slippage_pct = slippage_pct
        self._price_cache_max = price_cache_max
        self._paper_price_cache: dict[str, float] = {}
        # Use provided shutdown event so system-wide shutdown interrupts fill delays.
        # If none provided, create a local event that never gets set (safe fallback).
        self._shutdown_event = shutdown_event or threading.Event()
        self._lock = threading.RLock()

    # ── Public API ────────────────────────────────────────────────────────

    def execute(
        self,
        order_request: OrderRequest,
        execution_context: ExecutionContext | None = None,
    ) -> OrderResult:
        """Execute a paper/simulated order.

        Args:
            order_request: The order to simulate
            execution_context: Execution context (unused in paper mode)

        Returns:
            OrderResult with simulated fill or rejection
        """
        try:
            # Simulate network delay — interruptible on shutdown
            if self._shutdown_event.wait(self._fill_delay_ms / 1000.0):
                return OrderResult(
                    order_id="shutdown",
                    status=OrderStatus.REJECTED,
                    reject_reason="Shutdown requested during paper fill delay",
                    timestamp=now_ist(),
                )

            # Generate a fake order ID
            order_id = (
                f"paper_{int(time.time()*1000)}_"
                f"{hash(order_request.symbol) % 10000}"
            )

            fill_price = self._compute_fill_price(order_request)
            if fill_price is None:
                # Limit order would not execute immediately
                return OrderResult(
                    order_id=order_id,
                    status=OrderStatus.PENDING,
                    reject_reason="Limit order not executed — price not reached",
                    timestamp=now_ist(),
                )

            # Apply small random price variation for realism
            price_variation = random.uniform(-0.5, 0.5)
            fill_price = max(0.01, fill_price + price_variation)

            # Calculate commission (simplified: 0.05% of notional)
            commission = abs(fill_price) * order_request.lot_size * 0.0005

            return OrderResult(
                order_id=order_id,
                status=OrderStatus.FILLED,
                filled_quantity=order_request.lot_size,
                average_price=round(fill_price, 2),
                commission=round(commission, 2),
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
        """Get current price for a symbol (used for paper trading simulation).

        Uses a cached price map as fallback when live market data is unavailable.

        Args:
            symbol: Trading symbol

        Returns:
            Current price for the symbol
        """
        with self._lock:
            # Check cache first
            if symbol in self._paper_price_cache:
                return self._paper_price_cache[symbol]

            price = self._lookup_default_price(symbol)

            # Cache the price
            self._paper_price_cache[symbol] = price

            # Evict oldest entries if cache exceeds limit
            if len(self._paper_price_cache) > self._price_cache_max:
                keys = list(self._paper_price_cache.keys())[:10]
                for k in keys:
                    self._paper_price_cache.pop(k, None)

            return price

    def shutdown(self) -> None:
        """Signal shutdown to interrupt pending fill delays."""
        self._shutdown_event.set()

    def reset(self) -> None:
        """Reset paper trader state (price cache, shutdown flag)."""
        with self._lock:
            self._paper_price_cache.clear()
        self._shutdown_event.clear()

    # ── Internal helpers ──────────────────────────────────────────────────

    def _compute_fill_price(
        self,
        order_request: OrderRequest,
    ) -> float | None:
        """Compute simulated fill price based on order type and direction.

        Returns None if a limit order would not execute at current price.
        """
        base_price = self.get_current_price(order_request.symbol)
        slippage = base_price * (self._slippage_pct / 100.0)

        if order_request.order_type == OrderType.MARKET:
            if order_request.direction.upper() == "BUY":
                return base_price + slippage
            else:
                return base_price - slippage

        elif order_request.order_type == OrderType.LIMIT:
            if not order_request.price:
                return base_price
            if order_request.direction.upper() == "BUY":
                return order_request.price if order_request.price >= base_price else None
            else:
                return order_request.price if order_request.price <= base_price else None

        else:
            # SL, SL-M: use trigger price or current price
            return order_request.price or base_price

    @staticmethod
    def _lookup_default_price(symbol: str) -> float:
        """Return a reasonable default price for paper trading simulation.

        These values represent approximate current market levels and are used
        ONLY for paper trading when live market data is unavailable.
        """
        default_prices: dict[str, float] = {
            "NIFTY": 23500.0,
            "BANKNIFTY": 50500.0,
            "FINNIFTY": 22000.0,
            "RELIANCE": 3000.0,
            "TCS": 3900.0,
            "HDFCBANK": 1650.0,
            "INFY": 1600.0,
            "ICICIBANK": 1150.0,
            "KOTAKBANK": 1750.0,
            "LT": 3600.0,
            "SBIN": 800.0,
            "BHARTIARTL": 1300.0,
            "ASIANPAINT": 2700.0,
            "MARUTI": 11500.0,
            "HINDUNILVR": 2500.0,
            "AXISBANK": 1100.0,
        }
        return default_prices.get(symbol, 1000.0)


__all__ = ["PaperTrader"]
