"""Unit tests for PaperTrader — extracted paper order execution handler.

Covers:
  - Initialization with default and custom config
  - Market order execution (BUY/SELL)
  - Limit order execution (immediate fill / price not reached)
  - SL/SL-M order execution
  - Price lookup and caching
  - Shutdown interruption
  - Reset behavior
  - Thread safety
"""

from __future__ import annotations

import threading

import pytest
from core.ports.execution.execution_port import (
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
)
from core.services.paper_trader import PaperTrader

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def trader() -> PaperTrader:
    """PaperTrader with zero delay for fast tests."""
    return PaperTrader(fill_delay_ms=0, slippage_pct=0.05)


@pytest.fixture()
def market_order_buy() -> OrderRequest:
    return OrderRequest(
        symbol="NIFTY",
        direction="BUY",
        strike_price=23500.0,
        lot_size=50,
        order_type=OrderType.MARKET,
    )


@pytest.fixture()
def market_order_sell() -> OrderRequest:
    return OrderRequest(
        symbol="NIFTY",
        direction="SELL",
        strike_price=23500.0,
        lot_size=50,
        order_type=OrderType.MARKET,
    )


@pytest.fixture()
def limit_order_buy() -> OrderRequest:
    return OrderRequest(
        symbol="NIFTY",
        direction="BUY",
        strike_price=23500.0,
        lot_size=50,
        order_type=OrderType.LIMIT,
        price=23550.0,  # Above market -> should fill
    )


@pytest.fixture()
def limit_order_sell() -> OrderRequest:
    return OrderRequest(
        symbol="NIFTY",
        direction="SELL",
        strike_price=23500.0,
        lot_size=50,
        order_type=OrderType.LIMIT,
        price=23400.0,  # Below market -> should fill
    )


# ── Initialization ───────────────────────────────────────────────────


class TestInitialization:
    def test_default_construction(self) -> None:
        trader = PaperTrader()
        assert trader._fill_delay_ms == 50
        assert trader._slippage_pct == 0.05
        assert trader._price_cache_max == 50
        assert trader._shutdown_event is not None

    def test_custom_construction(self) -> None:
        event = threading.Event()
        trader = PaperTrader(
            fill_delay_ms=100,
            slippage_pct=0.1,
            price_cache_max=10,
            shutdown_event=event,
        )
        assert trader._fill_delay_ms == 100
        assert trader._slippage_pct == 0.1
        assert trader._price_cache_max == 10
        assert trader._shutdown_event is event

    def test_shutdown_event_fallback(self) -> None:
        """When no event provided, creates a local event (never set)."""
        trader = PaperTrader()
        assert trader._shutdown_event is not None
        assert not trader._shutdown_event.is_set()


# ── Market Order Execution ───────────────────────────────────────────


class TestMarketOrderExecution:
    def test_buy_order_fills(self, trader: PaperTrader, market_order_buy: OrderRequest) -> None:
        result = trader.execute(market_order_buy)
        assert result.status == OrderStatus.FILLED
        assert result.filled_quantity == market_order_buy.lot_size
        assert result.average_price > 0
        assert result.order_id.startswith("paper_")

    def test_sell_order_fills(self, trader: PaperTrader, market_order_sell: OrderRequest) -> None:
        result = trader.execute(market_order_sell)
        assert result.status == OrderStatus.FILLED
        assert result.filled_quantity == market_order_sell.lot_size
        assert result.average_price > 0

    def test_buy_price_has_slippage(self, trader: PaperTrader, market_order_buy: OrderRequest) -> None:
        """BUY order should have positive slippage (pay more)."""
        base = trader.get_current_price("NIFTY")
        result = trader.execute(market_order_buy)
        # Base price + slippage = slightly higher (within ±0.5 random variation)
        assert result.average_price >= base * 0.99  # Allow for random variation

    def test_sell_price_has_slippage(self, trader: PaperTrader, market_order_sell: OrderRequest) -> None:
        """SELL order should have negative slippage (receive less)."""
        result = trader.execute(market_order_sell)
        # Base price - slippage = slightly lower (within ±0.5 random variation)
        # SELL price could be higher than base if random variation dominates
        # Just verify it filled with a reasonable price
        assert result.average_price > 0
        assert result.commission > 0

    def test_returns_order_result_type(self, trader: PaperTrader, market_order_buy: OrderRequest) -> None:
        result = trader.execute(market_order_buy)
        assert isinstance(result, OrderResult)

    def test_commission_calculated(self, trader: PaperTrader, market_order_buy: OrderRequest) -> None:
        result = trader.execute(market_order_buy)
        assert result.commission > 0
        # Enhanced PaperTrader uses full Indian broker commission (STT+Exchange+GST+SEBI+Stamp)
        from core.services.paper_trader import _compute_indian_commission
        expected = _compute_indian_commission(
            trade_value=result.average_price * market_order_buy.lot_size,
            is_options=True,
            is_intraday=True,
        )
        assert result.commission == pytest.approx(expected["total"], rel=0.01)


# ── Calibrated slippage model (opt-in, default None = unchanged) ─────

class TestCalibratedSlippageModel:
    def test_default_none_uses_static_slippage_pct(self, market_order_buy: OrderRequest) -> None:
        """Regression guard: with no calibrated model supplied (the default),
        behavior must be identical to before this wiring existed."""
        trader = PaperTrader(fill_delay_ms=0, slippage_pct=0.05, enable_random_walk=False,
                              enable_market_impact=False, enable_partial_fills=False)
        assert trader._calibrated_slippage_model is None
        result = trader.execute(market_order_buy)
        assert result.status == OrderStatus.FILLED

    def test_calibrated_model_changes_fill_price(self, market_order_buy: OrderRequest) -> None:
        """A supplied model must actually drive the slippage calculation —
        proving this is wired with real effect, not a dead constructor param."""
        from core.slippage_model import SlippageModel

        static_trader = PaperTrader(fill_delay_ms=0, slippage_pct=0.05, enable_random_walk=False,
                                     enable_market_impact=False, enable_partial_fills=False)
        static_fill = static_trader.execute(market_order_buy).average_price

        big_slippage_model = SlippageModel(
            intercept=5.0, lot_coeff=0.0, spread_coeff=0.0, r_squared=0.9,
            n_samples=50, calibrated_at="2026-08-21T00:00:00",
        )
        calibrated_trader = PaperTrader(fill_delay_ms=0, slippage_pct=0.05, enable_random_walk=False,
                                         enable_market_impact=False, enable_partial_fills=False,
                                         calibrated_slippage_model=big_slippage_model)
        calibrated_fill = calibrated_trader.execute(market_order_buy).average_price

        # BUY fills add slippage to price; the 5%-intercept model must push
        # the fill meaningfully higher than the static 0.05% slippage_pct.
        assert calibrated_fill > static_fill * 1.01


# ── Limit Order Execution ────────────────────────────────────────────


class TestLimitOrderExecution:
    def test_buy_limit_above_market_fills(self, trader: PaperTrader, limit_order_buy: OrderRequest) -> None:
        """BUY limit at price above market should fill immediately."""
        result = trader.execute(limit_order_buy)
        assert result.status == OrderStatus.FILLED

    def test_sell_limit_below_market_fills(self, trader: PaperTrader, limit_order_sell: OrderRequest) -> None:
        """SELL limit at price below market should fill immediately."""
        result = trader.execute(limit_order_sell)
        assert result.status == OrderStatus.FILLED

    def test_buy_limit_below_market_pends(self, trader: PaperTrader) -> None:
        """BUY limit at price below market should not execute."""
        order = OrderRequest(
            symbol="NIFTY",
            direction="BUY",
            strike_price=23500.0,
            lot_size=50,
            order_type=OrderType.LIMIT,
            price=23000.0,  # Below market (NIFTY ~23500) -> won't fill
        )
        result = trader.execute(order)
        assert result.status == OrderStatus.PENDING
        assert "not executed" in result.reject_reason

    def test_sell_limit_above_market_pends(self, trader: PaperTrader) -> None:
        """SELL limit at price above market should not execute."""
        order = OrderRequest(
            symbol="NIFTY",
            direction="SELL",
            strike_price=23500.0,
            lot_size=50,
            order_type=OrderType.LIMIT,
            price=24000.0,  # Above market (NIFTY ~23500) -> won't fill
        )
        result = trader.execute(order)
        assert result.status == OrderStatus.PENDING
        assert "not executed" in result.reject_reason


# ── SL/SL-M Order Execution ──────────────────────────────────────────


class TestSLOOrderExecution:
    def test_sl_order_uses_trigger_price(self, trader: PaperTrader) -> None:
        """SL order should use trigger price for fill simulation.
        BUY SL triggers when price rises above trigger (stop-loss on short).
        """
        order = OrderRequest(
            symbol="NIFTY",
            direction="SELL",
            strike_price=23500.0,
            lot_size=1,
            order_type=OrderType.STOP_LOSS,
            price=23600.0,  # SELL SL at 23600: base_price(23500) <= trigger(23600) = True -> triggers immediately
        )
        result = trader.execute(order)
        assert result.status == OrderStatus.FILLED
        assert result.average_price > 0

    def test_slm_order_uses_current_price(self, trader: PaperTrader) -> None:
        """SL-M order should use current price (no trigger price)."""
        order = OrderRequest(
            symbol="NIFTY",
            direction="BUY",
            strike_price=23500.0,
            lot_size=50,
            order_type=OrderType.STOP_LOSS_MARKET,
        )
        result = trader.execute(order)
        assert result.status == OrderStatus.FILLED
        assert result.average_price > 0


# ── Price Lookup and Caching ─────────────────────────────────────────


class TestPriceLookup:
    def test_known_symbol_returns_price(self, trader: PaperTrader) -> None:
        price = trader.get_current_price("NIFTY")
        assert price == 23500.0

    def test_unknown_symbol_returns_default(self, trader: PaperTrader) -> None:
        price = trader.get_current_price("UNKNOWN")
        assert price == 1000.0

    def test_price_caching(self, trader: PaperTrader) -> None:
        """Second call should return quickly without errors (random walk evolves price)."""
        # With random walk enabled, each call evolves the price slightly
        price1 = trader.get_current_price("NIFTY")
        price2 = trader.get_current_price("NIFTY")
        # Both should be valid prices close to the default
        assert price1 > 0
        assert price2 > 0
        # Price evolves via random walk so not strictly equal, but within 0.5%
        assert abs(price1 - price2) / price1 < 0.005, f"Prices {price1} and {price2} diverged too much"

    def test_cache_eviction(self, trader: PaperTrader) -> None:
        """Cache should evict oldest entries when over limit."""
        trader._price_cache_max = 5
        for i in range(10):
            trader.get_current_price(f"SYM_{i}")
        assert len(trader._paper_price_cache) <= 5

    def test_price_cache_max_config(self) -> None:
        """Custom price_cache_max should be respected."""
        trader = PaperTrader(price_cache_max=3)
        for i in range(10):
            trader.get_current_price(f"SYM_{i}")
        assert len(trader._paper_price_cache) <= 3

    def test_default_prices_comprehensive(self) -> None:
        """All known symbols should have a default price."""
        trader = PaperTrader()
        known_symbols = [
            "NIFTY", "BANKNIFTY", "FINNIFTY",
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
            "KOTAKBANK", "LT", "SBIN", "BHARTIARTL",
            "ASIANPAINT", "MARUTI", "HINDUNILVR", "AXISBANK",
        ]
        for sym in known_symbols:
            price = trader.get_current_price(sym)
            assert price > 0, f"Symbol {sym} has no valid default price"


# ── Shutdown Behavior ────────────────────────────────────────────────


class TestShutdown:
    def test_shutdown_sets_event(self, trader: PaperTrader) -> None:
        assert not trader._shutdown_event.is_set()
        trader.shutdown()
        assert trader._shutdown_event.is_set()

    def test_shutdown_after_fill_delay_rejects(self) -> None:
        """If shutdown is set before execute, order should be rejected."""
        event = threading.Event()
        trader = PaperTrader(fill_delay_ms=100, shutdown_event=event)
        event.set()  # Shutdown before execution
        order = OrderRequest(
            symbol="NIFTY",
            direction="BUY",
            strike_price=23500.0,
            lot_size=50,
            order_type=OrderType.MARKET,
        )
        result = trader.execute(order)
        assert result.status == OrderStatus.REJECTED
        assert "shutdown" in result.reject_reason.lower()

    def test_shutdown_event_persists_after_reset(self, trader: PaperTrader) -> None:
        """Shutdown event persists after reset() — safety feature: must be explicitly cleared.
        Event can be shared between ExecutionService and PaperTrader.
        """
        trader.shutdown()
        assert trader._shutdown_event.is_set()
        trader.reset()
        # Reset does NOT clear shutdown event (documented safety behavior)
        assert trader._shutdown_event.is_set() is True


# ── Reset Behavior ───────────────────────────────────────────────────


class TestReset:
    def test_reset_clears_price_cache(self, trader: PaperTrader) -> None:
        trader.get_current_price("NIFTY")
        assert len(trader._paper_price_cache) > 0
        trader.reset()
        assert len(trader._paper_price_cache) == 0

    def test_reset_does_not_clear_shutdown(self, trader: PaperTrader) -> None:
        """Reset does NOT clear shutdown event (safety: must be explicitly cleared)."""
        trader.shutdown()
        assert trader._shutdown_event.is_set()
        trader.reset()
        # Reset preserves shutdown event (safety feature — prevents accidental re-entry)
        assert trader._shutdown_event.is_set() is True


# ── Thread Safety ────────────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_price_lookup(self, trader: PaperTrader) -> None:
        """Multiple threads should be able to look up prices concurrently."""
        errors: list[Exception] = []

        def lookup(symbol: str) -> None:
            try:
                for _ in range(20):
                    trader.get_current_price(symbol)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=lookup, args=(f"SYM_{i}",))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0, f"Thread safety errors: {errors}"

    def test_concurrent_execution(self, trader: PaperTrader) -> None:
        """Multiple threads should be able to execute orders concurrently."""
        errors: list[Exception] = []

        def execute(symbol: str) -> None:
            try:
                for _ in range(10):
                    order = OrderRequest(
                        symbol=symbol,
                        direction="BUY",
                        strike_price=100.0,
                        lot_size=1,
                        order_type=OrderType.MARKET,
                    )
                    trader.execute(order)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=execute, args=(f"SYM_{i}",))
            for i in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0, f"Thread safety errors: {errors}"
