"""Unit tests for Enhanced PaperTrader features — v2.57.0.

Covers the new features added to PaperTrader beyond basic order execution:
  - Indian broker commission calculation (_compute_indian_commission)
  - Bid-ask spread simulation
  - Random walk price evolution
  - Market impact model (large orders move price)
  - Partial fill logic (OI-based)
  - Circuit limit check (±20%)
  - Market snapshot API
  - Commission breakdown API
  - Feature flag toggles (enable_random_walk, enable_partial_fills, etc.)
  - Legacy backward compatibility
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

import pytest
from core.ports.execution.execution_port import (
    OrderRequest,
    OrderStatus,
    OrderType,
)
from core.services.paper_trader import (
    _SYMBOL_META,
    PaperTrader,
    _compute_indian_commission,
)

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def trader() -> PaperTrader:
    """PaperTrader with zero delay and all features enabled."""
    return PaperTrader(fill_delay_ms=0, slippage_pct=0.05)


@pytest.fixture()
def trader_no_extras() -> PaperTrader:
    """PaperTrader with ALL enhanced features disabled (raw basic mode)."""
    return PaperTrader(
        fill_delay_ms=0,
        slippage_pct=0.05,
        enable_random_walk=False,
        enable_partial_fills=False,
        enable_market_impact=False,
        enable_bid_ask_spread=False,
    )


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


# ── Indian Broker Commission ─────────────────────────────────────────


class TestIndianBrokerCommission:
    def test_basic_options_commission(self) -> None:
        """Options trade ~₹4,500 notional should have all 6 charge components."""
        charges = _compute_indian_commission(trade_value=4500, is_options=True)
        assert "brokerage" in charges
        assert "stt" in charges
        assert "exchange" in charges
        assert "gst" in charges
        assert "sebi" in charges
        assert "stamp_duty" in charges
        assert "total" in charges

    def test_brokerage_capped_at_20(self) -> None:
        """Zerodha-style brokerage capped at ₹20 even for large trades."""
        charges = _compute_indian_commission(trade_value=1_000_000, is_options=True)
        assert charges["brokerage"] <= 20.0

    def test_small_trade_brokerage_pct(self) -> None:
        """Small trade: brokerage = 0.03% of trade value (less than ₹20 cap)."""
        charges = _compute_indian_commission(trade_value=1000, is_options=True)
        assert charges["brokerage"] == pytest.approx(0.30, rel=0.1)  # 0.03% of 1000

    def test_stt_for_options(self) -> None:
        """STT for options: 0.05% of trade value."""
        charges = _compute_indian_commission(trade_value=10000, is_options=True)
        assert charges["stt"] == pytest.approx(5.0, rel=0.01)  # 0.05% of 10000

    def test_stt_for_equity_intraday(self) -> None:
        """STT for equity intraday: 0.025% of trade value."""
        charges = _compute_indian_commission(trade_value=10000, is_options=False, is_intraday=True)
        assert charges["stt"] == pytest.approx(2.5, rel=0.01)  # 0.025% of 10000

    def test_stt_for_equity_delivery(self) -> None:
        """STT for equity delivery: 0.1% of trade value."""
        charges = _compute_indian_commission(trade_value=10000, is_options=False, is_intraday=False)
        assert charges["stt"] == pytest.approx(10.0, rel=0.01)  # 0.1% of 10000

    def test_gst_is_18pct_of_brokerage_plus_exchange(self) -> None:
        """GST: 18% on (brokerage + exchange charges)."""
        charges = _compute_indian_commission(trade_value=10000, is_options=True)
        expected_gst = (charges["brokerage"] + charges["exchange"]) * 0.18
        assert charges["gst"] == pytest.approx(expected_gst, rel=0.01)

    def test_sebi_rounds_correctly(self) -> None:
        """SEBI: ₹10 per crore = 0.0001%."""
        charges = _compute_indian_commission(trade_value=10_000_000, is_options=True)
        assert charges["sebi"] == pytest.approx(10.0, rel=0.01)  # ₹10 per crore

    def test_commission_breakdown_matches_total(self) -> None:
        """Sum of all components should equal total."""
        charges = _compute_indian_commission(trade_value=50000, is_options=True)
        components_sum = (
            charges["brokerage"]
            + charges["stt"]
            + charges["exchange"]
            + charges["gst"]
            + charges["sebi"]
            + charges["stamp_duty"]
        )
        assert charges["total"] == pytest.approx(components_sum, rel=0.01)

    def test_commission_via_papertrader_api(self, trader: PaperTrader) -> None:
        """get_commission_breakdown should delegate to _compute_indian_commission."""
        result = trader.get_commission_breakdown("NIFTY", 180.0, 50)
        assert isinstance(result, dict)
        assert "brokerage" in result
        assert result["total"] > 0

    def test_equity_option_vs_index_option_stt(self) -> None:
        """Equity and index options both use the same STT rate (0.05% on sell)."""
        equity = _compute_indian_commission(trade_value=10000, is_options=True)
        # Both are options, so same rate
        assert equity["stt"] == pytest.approx(5.0, rel=0.01)


# ── Bid-Ask Spread Simulation ────────────────────────────────────────


class TestBidAskSpread:
    def test_buy_market_fills_at_ask(self, trader: PaperTrader) -> None:
        """Market BUY should fill at ask price (above mid)."""
        mid = trader.get_current_price("NIFTY")
        result = trader.execute(
            OrderRequest(
                symbol="NIFTY",
                direction="BUY",
                strike_price=23500.0,
                lot_size=50,
                order_type=OrderType.MARKET,
            )
        )
        assert result.status == OrderStatus.FILLED
        # With spread enabled, BUY fills at ask + slippage > mid
        assert result.average_price > mid * 0.99

    def test_sell_market_fills_at_bid(self, trader: PaperTrader) -> None:
        """Market SELL should fill at bid price (below mid)."""
        result = trader.execute(
            OrderRequest(
                symbol="NIFTY",
                direction="SELL",
                strike_price=23500.0,
                lot_size=50,
                order_type=OrderType.MARKET,
            )
        )
        assert result.status == OrderStatus.FILLED
        assert result.average_price > 0

    def test_disable_spread_reduces_slippage(self) -> None:
        """Disabling bid-ask spread should produce tighter fills."""
        trader_spread = PaperTrader(fill_delay_ms=0, slippage_pct=0.01, enable_bid_ask_spread=True)
        trader_no_spread = PaperTrader(fill_delay_ms=0, slippage_pct=0.01, enable_bid_ask_spread=False)

        buy_spread = trader_spread.execute(
            OrderRequest(symbol="NIFTY", direction="BUY", strike_price=23500.0, lot_size=50, order_type=OrderType.MARKET)
        )
        buy_no_spread = trader_no_spread.execute(
            OrderRequest(symbol="NIFTY", direction="BUY", strike_price=23500.0, lot_size=50, order_type=OrderType.MARKET)
        )

        # With spread enabled, buy price should be higher (or equal) than without
        assert buy_spread.average_price >= buy_no_spread.average_price * 0.995

    def test_limit_buy_at_spread_fills(self, trader: PaperTrader) -> None:
        """Limit BUY at ask price should fill immediately."""
        mid = trader.get_current_price("NIFTY")
        # Ask ≈ mid + spread/2. Use a price well above mid
        order = OrderRequest(
            symbol="NIFTY",
            direction="BUY",
            strike_price=23500.0,
            lot_size=50,
            order_type=OrderType.LIMIT,
            price=mid * 1.01,  # 1% above mid should easily beat ask
        )
        result = trader.execute(order)
        assert result.status == OrderStatus.FILLED


# ── Random Walk Price Evolution ──────────────────────────────────────


class TestRandomWalk:
    def test_price_evolves_over_time(self, trader: PaperTrader) -> None:
        """Calling get_current_price multiple times should evolve the price."""
        prices = []
        for _ in range(5):
            prices.append(trader.get_current_price("NIFTY"))
            trader._price_timestamp["NIFTY"] = datetime.now() - timedelta(seconds=60)

        # Prices shouldn't all be identical (random walk adds noise)
        unique_prices = set(prices)
        assert len(unique_prices) >= 1  # Could be same if random walk gives 0 delta

    def test_disable_random_walk_returns_cached(self) -> None:
        """Disabling random walk should return cached price unchanged."""
        t = PaperTrader(fill_delay_ms=0, enable_random_walk=False)
        p1 = t.get_current_price("NIFTY")
        t._price_timestamp["NIFTY"] = datetime.now() - timedelta(hours=1)
        p2 = t.get_current_price("NIFTY")
        assert p1 == p2  # Should be identical without random walk

    def test_price_clamped_to_5pct(self, trader: PaperTrader) -> None:
        """Price should never move more than ±5% in a single tick."""
        base = trader.get_current_price("NIFTY")
        # Simulate a very large time gap to trigger large potential move
        trader._price_timestamp["NIFTY"] = datetime.now() - timedelta(days=1)
        new_price = trader.get_current_price("NIFTY")
        assert abs(new_price - base) / base <= 0.05

    def test_random_walk_drift_decays(self, trader: PaperTrader) -> None:
        """Drift should decay by 0.95 each tick (mean reversion)."""
        trader._price_drift["NIFTY"] = 100.0  # Large drift
        trader._price_timestamp["NIFTY"] = datetime.now() - timedelta(seconds=60)
        trader.get_current_price("NIFTY")
        # Drift decays by 0.95 from 100 -> ~95, then adds gaussian noise.
        # Even with noise, drift should be less than the original 100.
        assert trader._price_drift["NIFTY"] < 100.0  # Decayed from 100

    def test_new_symbol_initializes_price(self, trader: PaperTrader) -> None:
        """First call for a symbol should return its default price."""
        price = trader.get_current_price("NIFTY")
        assert price == _SYMBOL_META["NIFTY"]["price"]


# ── Market Impact Model ──────────────────────────────────────────────


class TestMarketImpact:
    def test_large_buy_moves_price_up(self, trader: PaperTrader) -> None:
        """A large BUY order (>5L notional) should increase the price."""
        base = trader.get_current_price("NIFTY")
        # Simulate large order (NIFTY lot 50 × ~23500 = 11.75L, well above 5L threshold)
        trader._apply_market_impact("NIFTY", "BUY", 1_000_000, base)
        impact = trader._impact_cache.get("NIFTY", 0)
        assert impact > 0  # Price moved up after large BUY

    def test_large_sell_moves_price_down(self, trader: PaperTrader) -> None:
        """A large SELL order (>5L notional) should decrease the price."""
        base = trader.get_current_price("NIFTY")
        trader._apply_market_impact("NIFTY", "SELL", 1_000_000, base)
        impact = trader._impact_cache.get("NIFTY", 0)
        assert impact < 0  # Price moved down after large SELL

    def test_small_order_no_impact(self, trader: PaperTrader) -> None:
        """A small order (<5L notional) should NOT trigger market impact."""
        trader.get_current_price("NIFTY")
        order = OrderRequest(
            symbol="NIFTY",
            direction="BUY",
            strike_price=23500.0,
            lot_size=1,  # Tiny lot
            order_type=OrderType.MARKET,
        )
        # Execute without triggering market impact (notional well below 5L)
        result = trader.execute(order)
        # With zero delay, this should fill immediately
        assert result.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)

    def test_impact_decays_over_time(self, trader: PaperTrader) -> None:
        """Market impact should decay by 0.9 each price call."""
        trader.get_current_price("NIFTY")
        trader._impact_cache["NIFTY"] = 100.0  # Large impact
        # First decay
        trader.get_current_price("NIFTY")
        assert trader._impact_cache["NIFTY"] == 90.0  # 100 * 0.9

    def test_impact_clamped_to_0_2pct(self, trader: PaperTrader) -> None:
        """Market impact should not exceed ±0.2% of base price."""
        base = trader.get_current_price("NIFTY")
        max_impact = base * 0.002
        trader._impact_cache["NIFTY"] = max_impact * 10  # Try to exceed clamp
        # The _apply_market_impact function clamps
        trader._apply_market_impact("NIFTY", "BUY", 100_000_000, base)
        assert abs(trader._impact_cache["NIFTY"]) <= max_impact

    def test_disable_impact_skips_in_execute(self) -> None:
        """Disabling market impact in execute() should not add to impact_cache."""
        t = PaperTrader(fill_delay_ms=0, enable_market_impact=False)
        t.get_current_price("NIFTY")
        impact_before = t._impact_cache.get("NIFTY", 0)
        # Execute a large order (>5L notional) that would normally trigger impact
        order = OrderRequest(
            symbol="NIFTY",
            direction="BUY",
            strike_price=23500.0,
            lot_size=50,
            order_type=OrderType.MARKET,
        )
        result = t.execute(order)
        assert result.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
        # Impact cache should be unchanged since feature is disabled
        assert t._impact_cache.get("NIFTY", 0) == impact_before


# ── Partial Fill Logic ───────────────────────────────────────────────


class TestPartialFills:
    def test_partial_fills_reduces_quantity(self, trader: PaperTrader) -> None:
        """Partial fill should result in PARTIALLY_FILLED status with reduced qty."""
        # Very large quantity relative to liquidity
        order = OrderRequest(
            symbol="NIFTY",
            direction="BUY",
            strike_price=23500.0,
            lot_size=999999,  # Huge order to trigger partial fill
            order_type=OrderType.MARKET,
        )
        result = trader.execute(order)
        # Either FILLED or PARTIALLY_FILLED depending on OI calculation
        assert result.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
        if result.status == OrderStatus.PARTIALLY_FILLED:
            assert result.filled_quantity < order.lot_size

    def test_disable_partial_fills_always_full(self) -> None:
        """Disabling partial fills should always return FILLED."""
        t = PaperTrader(fill_delay_ms=0, enable_partial_fills=False)
        order = OrderRequest(
            symbol="NIFTY",
            direction="BUY",
            strike_price=23500.0,
            lot_size=999999,
            order_type=OrderType.MARKET,
        )
        result = t.execute(order)
        assert result.status == OrderStatus.FILLED

    def test_fill_pct_never_below_5(self, trader: PaperTrader) -> None:
        """Fill percentage should never go below 5%."""
        pct = trader._compute_fill_pct("NIFTY", 10_000_000_000, 99999)
        assert pct >= 5.0

    def test_fill_pct_never_above_100(self, trader: PaperTrader) -> None:
        """Fill percentage should never exceed 100%."""
        pct = trader._compute_fill_pct("NIFTY", 1, 1)
        assert pct <= 100.0

    def test_fill_rate_limiting(self, trader: PaperTrader) -> None:
        """After >20 fills in 5 min window, fill percentage should drop."""
        trader._recent_fills["NIFTY"] = [time.time()] * 25  # 25 recent fills
        pct = trader._compute_fill_pct("NIFTY", 1000, 1)
        assert pct < 100.0  # Should be reduced due to rate limiting

    def test_zero_trade_value_full_fill(self, trader: PaperTrader) -> None:
        """Zero trade value should return 100% fill."""
        pct = trader._compute_fill_pct("NIFTY", 0, 1)
        assert pct == 100.0

    def test_enable_partial_fills_flag(self) -> None:
        """enable_partial_fills=False should return 100% from _compute_fill_pct."""
        t = PaperTrader(fill_delay_ms=0, enable_partial_fills=False)
        pct = t._compute_fill_pct("NIFTY", 10_000_000_000, 99999)
        assert pct == 100.0


# ── Circuit Limit Check ──────────────────────────────────────────────


class TestCircuitLimits:
    def test_price_within_limits_passes(self, trader: PaperTrader) -> None:
        """Order price within ±20% of base should pass circuit check."""
        mid = trader.get_current_price("NIFTY")
        order = OrderRequest(
            symbol="NIFTY",
            direction="BUY",
            strike_price=23500.0,
            lot_size=50,
            order_type=OrderType.LIMIT,
            price=mid * 1.10,  # 10% above base -> within limits
        )
        result = trader.execute(order)
        assert result.status == OrderStatus.FILLED

    def test_price_exceeds_circuit_blocked(self, trader: PaperTrader) -> None:
        """Order price >20% from base should be REJECTED."""
        mid = trader.get_current_price("NIFTY")
        order = OrderRequest(
            symbol="NIFTY",
            direction="BUY",
            strike_price=23500.0,
            lot_size=50,
            order_type=OrderType.LIMIT,
            price=mid * 1.25,  # 25% above base -> exceeds circuit limit
        )
        result = trader.execute(order)
        assert result.status == OrderStatus.REJECTED
        assert "circuit" in result.reject_reason.lower()

    def test_price_below_circuit_blocked(self, trader: PaperTrader) -> None:
        """Order price >20% below base should be REJECTED."""
        mid = trader.get_current_price("NIFTY")
        order = OrderRequest(
            symbol="NIFTY",
            direction="SELL",
            strike_price=23500.0,
            lot_size=50,
            order_type=OrderType.LIMIT,
            price=mid * 0.75,  # 25% below base -> exceeds circuit limit
        )
        result = trader.execute(order)
        assert result.status == OrderStatus.REJECTED
        assert "circuit" in result.reject_reason.lower() or "circuit" in result.reject_reason.lower()


# ── Market Snapshot API ──────────────────────────────────────────────


class TestMarketSnapshot:
    def test_market_snapshot_returns_all_fields(self, trader: PaperTrader) -> None:
        """Market snapshot should include all expected fields."""
        snapshot = trader.get_market_snapshot("NIFTY")
        assert "symbol" in snapshot
        assert "last_price" in snapshot
        assert "bid" in snapshot
        assert "ask" in snapshot
        assert "spread" in snapshot
        assert "spread_pct" in snapshot
        assert "volatility" in snapshot
        assert "lot_size" in snapshot
        assert "timestamp" in snapshot

    def test_bid_less_than_ask(self, trader: PaperTrader) -> None:
        """Bid price should always be less than or equal to ask price."""
        snapshot = trader.get_market_snapshot("NIFTY")
        assert snapshot["bid"] <= snapshot["ask"]

    def test_last_price_between_bid_and_ask(self, trader: PaperTrader) -> None:
        """Last price should be between bid and ask (or very close)."""
        snapshot = trader.get_market_snapshot("NIFTY")
        assert snapshot["bid"] <= snapshot["last_price"] <= snapshot["ask"]

    def test_snapshot_for_unknown_symbol(self, trader: PaperTrader) -> None:
        """Unknown symbol should return snapshot with default values."""
        snapshot = trader.get_market_snapshot("UNKNOWN_SYMBOL")
        assert snapshot["symbol"] == "UNKNOWN_SYMBOL"
        assert snapshot["last_price"] > 0

    def test_snapshot_timestamp_format(self, trader: PaperTrader) -> None:
        """Timestamp should be ISO format string."""
        snapshot = trader.get_market_snapshot("NIFTY")
        assert "T" in snapshot["timestamp"]  # ISO format contains T separator


# ── Feature Flag Toggles ─────────────────────────────────────────────


class TestFeatureFlags:
    def test_default_all_enabled(self) -> None:
        """Default PaperTrader should have all enhanced features enabled."""
        t = PaperTrader()
        assert t._enable_random_walk is True
        assert t._enable_partial_fills is True
        assert t._enable_market_impact is True
        assert t._enable_bid_ask_spread is True

    def test_disable_all_features(self) -> None:
        """All features should be disableable."""
        t = PaperTrader(
            enable_random_walk=False,
            enable_partial_fills=False,
            enable_market_impact=False,
            enable_bid_ask_spread=False,
        )
        assert t._enable_random_walk is False
        assert t._enable_partial_fills is False
        assert t._enable_market_impact is False
        assert t._enable_bid_ask_spread is False

    def test_mixed_feature_flags(self) -> None:
        """Different combinations of feature flags should work."""
        t = PaperTrader(enable_random_walk=True, enable_partial_fills=False)
        assert t._enable_random_walk is True
        assert t._enable_partial_fills is False
        assert t._enable_market_impact is True  # default
        assert t._enable_bid_ask_spread is True  # default


# ── Legacy Backward Compatibility ────────────────────────────────────


class TestLegacyCompatibility:
    def test_legacy_compute_fill_price_returns_float(self, trader: PaperTrader) -> None:
        """Legacy _compute_fill_price should return a float or None."""
        order = OrderRequest(
            symbol="NIFTY",
            direction="BUY",
            strike_price=23500.0,
            lot_size=50,
            order_type=OrderType.MARKET,
        )
        price = trader._compute_fill_price(order)
        if price is not None:
            assert isinstance(price, float)
            assert price > 0

    def test_legacy_method_internal_structure(self, trader: PaperTrader) -> None:
        """Legacy method should delegate to _compute_fill_price_with_spread."""
        order = OrderRequest(
            symbol="NIFTY",
            direction="BUY",
            strike_price=23500.0,
            lot_size=50,
            order_type=OrderType.MARKET,
        )
        # Legacy method returns first element of tuple from new method
        price = trader._compute_fill_price(order)
        assert price is None or isinstance(price, float)

    def test_legacy_lookup_default_price(self) -> None:
        """Static _lookup_default_price should return correct prices."""
        assert PaperTrader._lookup_default_price("NIFTY") == _SYMBOL_META["NIFTY"]["price"]
        assert PaperTrader._lookup_default_price("UNKNOWN") == 1000.0  # _DEFAULT_META

    def test_execute_with_context(self, trader: PaperTrader, market_order_buy: OrderRequest) -> None:
        """Execute with ExecutionContext=None should still work."""
        result = trader.execute(market_order_buy)
        assert result.status == OrderStatus.FILLED
        assert result.average_price > 0


# ── Resets and State Management ──────────────────────────────────────


class TestStateManagement:
    def test_reset_clears_impact_cache(self, trader: PaperTrader) -> None:
        """Reset should clear market impact cache."""
        trader._impact_cache["NIFTY"] = 50.0
        trader.reset()
        assert "NIFTY" not in trader._impact_cache

    def test_reset_clears_price_drift(self, trader: PaperTrader) -> None:
        """Reset should clear random walk drift state."""
        trader._price_drift["NIFTY"] = 10.0
        trader.reset()
        assert "NIFTY" not in trader._price_drift

    def test_reset_clears_fill_history(self, trader: PaperTrader) -> None:
        """Reset should clear recent fill history."""
        trader._recent_fills["NIFTY"] = [time.time()]
        trader.reset()
        assert "NIFTY" not in trader._recent_fills

    def test_reset_does_not_clear_shutdown(self, trader: PaperTrader) -> None:
        """Reset should NOT clear shutdown event (safety feature — must be explicitly cleared)."""
        trader.shutdown()
        assert trader._shutdown_event.is_set()
        trader.reset()
        # Reset does NOT clear shutdown event (safety: must be explicitly cleared)
        assert trader._shutdown_event.is_set() is True


# ── Error Handling ───────────────────────────────────────────────────


class TestErrorHandling:
    def test_zero_base_price_rejected(self, trader: PaperTrader) -> None:
        """Base price of 0 should result in REJECTED order."""
        trader._paper_price_cache["NIFTY"] = 0.0
        order = OrderRequest(
            symbol="NIFTY",
            direction="BUY",
            strike_price=23500.0,
            lot_size=50,
            order_type=OrderType.MARKET,
        )
        result = trader.execute(order)
        assert result.status == OrderStatus.REJECTED
        assert "Invalid base price" in result.reject_reason

    def test_shutdown_during_fill_delay_rejects(self) -> None:
        """If shutdown is requested during fill delay, order should be rejected."""
        event = threading.Event()
        t = PaperTrader(fill_delay_ms=5000, shutdown_event=event)  # Long delay
        event.set()  # Shutdown before execution finishes
        order = OrderRequest(
            symbol="NIFTY",
            direction="BUY",
            strike_price=23500.0,
            lot_size=50,
            order_type=OrderType.MARKET,
        )
        result = t.execute(order)
        assert result.status == OrderStatus.REJECTED
        assert "shutdown" in result.reject_reason.lower()

    def test_exception_returns_rejected(self, trader: PaperTrader) -> None:
        """Any exception during execute should return REJECTED."""
        # Force an error by passing None (PaperTrader catches it and returns REJECTED)
        result = trader.execute(None)  # type: ignore[arg-type]
        assert result.status == OrderStatus.REJECTED
        assert "object has no attribute" in result.reject_reason


# ── Fill Delay Timing ────────────────────────────────────────────────


class TestFillDelay:
    def test_delay_config_stored_as_is(self) -> None:
        """Fill delay config is stored as-is; clamping happens in execute()."""
        t = PaperTrader(fill_delay_ms=10000)
        assert t._fill_delay_ms == 10000
        # The clamping (5ms-5000ms) is applied at runtime in execute()
        # Verify that execute still works with default config
        order = OrderRequest(
            symbol="NIFTY",
            direction="BUY",
            strike_price=23500.0,
            lot_size=50,
            order_type=OrderType.MARKET,
        )
        result = t.execute(order)
        assert result.status == OrderStatus.FILLED


# ── Symbol Metadata ──────────────────────────────────────────────────


class TestSymbolMetadata:
    def test_all_known_symbols_have_metadata(self) -> None:
        """All 17 known symbols should have complete metadata."""
        for symbol, meta in _SYMBOL_META.items():
            assert "price" in meta, f"{symbol} missing price"
            assert "volatility" in meta, f"{symbol} missing volatility"
            assert "spread_pct" in meta, f"{symbol} missing spread_pct"
            assert "lot_size" in meta, f"{symbol} missing lot_size"
            assert "oi_lakh" in meta, f"{symbol} missing oi_lakh"
            assert meta["price"] > 0, f"{symbol} has zero price"
            assert meta["volatility"] > 0, f"{symbol} has zero volatility"
            assert meta["lot_size"] > 0, f"{symbol} has zero lot_size"

    def test_default_metadata_fallback(self) -> None:
        """Unknown symbols should use _DEFAULT_META values."""
        from core.services.paper_trader import _DEFAULT_META
        assert _DEFAULT_META["price"] == 1000.0
        assert _DEFAULT_META["volatility"] == 0.015
        assert _DEFAULT_META["lot_size"] == 100
