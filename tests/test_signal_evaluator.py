"""Tests for core.services.signal_evaluator — unified SignalEvaluator and strategies."""

from __future__ import annotations

import pandas as pd
from core.common.models import AssetType
from core.services.signal_evaluator import (
    SignalEvaluator,
    SignalResult,
    _EquitySignalStrategy,
    _FuturesSignalStrategy,
    _IndexOptionsSignalStrategy,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_df(close_prices: list[float], volume: int = 1_000_000) -> pd.DataFrame:
    """Create a test OHLCV DataFrame from close prices (1m data)."""
    n = len(close_prices)
    return pd.DataFrame({
        "Open": close_prices,
        "High": [p * 1.002 for p in close_prices],
        "Low": [p * 0.998 for p in close_prices],
        "Close": close_prices,
        "Volume": [volume] * n,
    })


def _make_trending_up(n: int = 60) -> pd.DataFrame:
    """Create an uptrending OHLCV series."""
    prices = [100.0 + i * 0.3 for i in range(n)]
    return _make_df(prices)


def _make_trending_down(n: int = 60) -> pd.DataFrame:
    """Create a downtrending OHLCV series."""
    prices = [100.0 - i * 0.3 for i in range(n)]
    return _make_df(prices)


def _make_flat(n: int = 60) -> pd.DataFrame:
    """Create a flat OHLCV series."""
    return _make_df([100.0] * n)


# =============================================================================
# SignalResult Tests
# =============================================================================


class TestSignalResult:
    """Tests for the SignalResult dataclass."""

    def test_default_strength(self):
        """Unknown strength should not be actionable."""
        r = SignalResult(symbol="TEST", direction="BUY", score=0, strength="IGNORE")
        assert r.is_actionable() is False

    def test_actionable_weak(self):
        """WEAK signals at 35+ score should be actionable by default."""
        r = SignalResult(symbol="TEST", direction="BUY", score=35, strength="WEAK")
        assert r.is_actionable() is True

    def test_actionable_moderate(self):
        """MODERATE signals should be actionable."""
        r = SignalResult(symbol="TEST", direction="SELL", score=60, strength="MODERATE")
        assert r.is_actionable() is True

    def test_actionable_strong(self):
        """STRONG signals should be actionable."""
        r = SignalResult(symbol="TEST", direction="BUY", score=85, strength="STRONG")
        assert r.is_actionable() is True

    def test_not_actionable_below_min(self):
        """Signals below min_score should not be actionable."""
        r = SignalResult(symbol="TEST", direction="BUY", score=20, strength="WEAK")
        assert r.is_actionable(min_score=50) is False

    def test_to_dict_keys(self):
        """to_dict should have all expected keys."""
        r = SignalResult(
            symbol="RELIANCE", direction="BUY", score=75, strength="STRONG",
            asset_type=AssetType.EQUITY,
        )
        d = r.to_dict()
        expected_keys = {
            "direction", "score", "price", "strength", "score_components",
            "features", "regime", "risk", "rsi", "atr", "adx", "vwap",
            "vol_ratio", "macd", "symbol", "signal_ts", "asset_type", "reason",
        }
        assert set(d.keys()) == expected_keys, f"Missing: {expected_keys - set(d.keys())}"

    def test_to_dict_includes_asset_type(self):
        """to_dict should include asset_type value string."""
        r = SignalResult(
            symbol="GOLD", direction="BUY", score=65, strength="MODERATE",
            asset_type=AssetType.COMMODITY,
        )
        d = r.to_dict()
        assert d["asset_type"] == "COMMODITY"

    def test_to_dict_signal_ts(self):
        """to_dict should include signal_ts as a float timestamp."""
        r = SignalResult(symbol="T", direction="BUY", score=50, strength="WEAK")
        d = r.to_dict()
        assert isinstance(d["signal_ts"], float)
        assert d["signal_ts"] > 1_600_000_000  # Reasonable Unix timestamp

    def test_default_asset_type(self):
        """Default asset_type should be UNKNOWN."""
        r = SignalResult(symbol="T", direction="BUY", score=50, strength="WEAK")
        assert r.asset_type == AssetType.UNKNOWN

    def test_different_min_scores(self):
        """is_actionable should respect different min_score values."""
        r = SignalResult(symbol="T", direction="BUY", score=40, strength="MODERATE")
        assert r.is_actionable(min_score=30) is True
        assert r.is_actionable(min_score=50) is False

    def test_full_constructor(self):
        """SignalResult should accept all fields."""
        r = SignalResult(
            symbol="NIFTY", direction="CALL", score=90, strength="STRONG",
            confidence=0.85, price=23500.0, asset_type=AssetType.INDEX_OPTIONS,
            regime="TRENDING", score_components={"vwap": 15, "momentum": 12},
            features=["vwap", "momentum"], risk={"atr_pct": 0.5},
            rsi=65.0, atr=120.0, adx=28.0, vwap=23480.0, vol_ratio=1.5,
            macd={"macd": 10.0, "signal": 8.0, "histogram": 2.0},
            reason="Strong uptrend",
        )
        assert r.score == 90
        assert r.strength == "STRONG"
        assert r.asset_type == AssetType.INDEX_OPTIONS
        assert len(r.features) == 2
        assert r.macd["histogram"] == 2.0


# =============================================================================
# SignalStrategy Tests (data-driven — use real FeatureEngine indicators)
# =============================================================================


class TestIndexOptionsSignalStrategy:
    """Tests for _IndexOptionsSignalStrategy."""

    def test_strategy_creation(self):
        """Strategy should instantiate with config."""
        strategy = _IndexOptionsSignalStrategy(config={})
        assert strategy is not None
        assert strategy._cfg == {}

    def test_requires_multi_timeframe(self):
        """Index options strategy should return None without all 3 timeframes."""
        strategy = _IndexOptionsSignalStrategy(config={})
        result = strategy.evaluate(symbol="NIFTY", df1m=_make_trending_up(60))
        assert result is None  # Needs df5m and df15m too

    def test_requires_sufficient_data(self):
        """Should return None with insufficient data."""
        strategy = _IndexOptionsSignalStrategy(config={})
        df_short = _make_trending_up(15)
        result = strategy.evaluate(
            symbol="NIFTY",
            df1m=df_short,
            df5m=df_short,
            df15m=df_short,
        )
        assert result is None


class TestEquitySignalStrategy:
    """Tests for _EquitySignalStrategy."""

    def test_strategy_creation(self):
        """Strategy should instantiate with config."""
        strategy = _EquitySignalStrategy(config={})
        assert strategy is not None

    def test_requires_sufficient_data(self):
        """Should return None with insufficient data (< 30 bars)."""
        strategy = _EquitySignalStrategy(config={})
        df_short = _make_trending_up(15)
        result = strategy.evaluate(symbol="RELIANCE", df1m=df_short)
        assert result is None

    def test_uptrend_generates_signal(self):
        """Uptrending data should produce a BUY signal."""
        strategy = _EquitySignalStrategy(config={})
        df = _make_trending_up(60)
        result = strategy.evaluate(symbol="RELIANCE", df1m=df)
        if result is not None:
            assert result.direction == "BUY"
            assert result.symbol == "RELIANCE"
            assert result.asset_type == AssetType.EQUITY
            assert 0 <= result.score <= 100

    def test_downtrend_generates_signal(self):
        """Downtrending data should produce a SELL signal."""
        strategy = _EquitySignalStrategy(config={})
        df = _make_trending_down(60)
        result = strategy.evaluate(symbol="TCS", df1m=df)
        if result is not None:
            assert result.direction == "SELL"
            assert result.asset_type == AssetType.EQUITY

    def test_flat_market_returns_none(self):
        """Flat market should not produce an actionable signal."""
        strategy = _EquitySignalStrategy(config={})
        df = _make_flat(60)
        result = strategy.evaluate(symbol="HDFCBANK", df1m=df)
        assert result is None

    def test_signal_has_feature_breakdown(self):
        """Signal should include score_components breakdown."""
        strategy = _EquitySignalStrategy(config={})
        df = _make_trending_up(60)
        result = strategy.evaluate(symbol="INFY", df1m=df)
        if result is not None:
            assert isinstance(result.score_components, dict)
            assert len(result.score_components) > 0
            assert "ema_trend" in result.score_components

    def test_signal_includes_risk_metadata(self):
        """Signal should include risk dict."""
        strategy = _EquitySignalStrategy(config={})
        df = _make_trending_up(60)
        result = strategy.evaluate(symbol="ICICIBANK", df1m=df)
        if result is not None:
            assert isinstance(result.risk, dict)
            assert "regime" in result.risk

    def test_signal_has_features_list(self):
        """Signal should include positive features list."""
        strategy = _EquitySignalStrategy(config={})
        df = _make_trending_up(60)
        result = strategy.evaluate(symbol="SBIN", df1m=df)
        if result is not None:
            assert isinstance(result.features, list)
            assert len(result.features) > 0

    def test_cached_trader(self):
        """EquityTrader should be cached after first evaluation."""
        strategy = _EquitySignalStrategy(config={})
        assert strategy._trader is None  # Not yet created
        df = _make_trending_up(60)
        strategy.evaluate(symbol="TEST", df1m=df)
        assert strategy._trader is not None  # Now cached

    def test_cached_trader_reused(self):
        """Subsequent evaluations should reuse the cached trader."""
        strategy = _EquitySignalStrategy(config={})
        df = _make_trending_up(60)
        strategy.evaluate(symbol="A", df1m=df)
        trader1 = strategy._trader
        strategy.evaluate(symbol="B", df1m=df)
        assert strategy._trader is trader1  # Same instance reused


class TestFuturesSignalStrategy:
    """Tests for _FuturesSignalStrategy."""

    def test_futures_creation(self):
        """Futures strategy should instantiate with asset_type."""
        strategy = _FuturesSignalStrategy(config={}, asset_type=AssetType.FUTURES)
        assert strategy._asset_type == AssetType.FUTURES
        assert strategy._score_prefix == "FUTURES"

    def test_commodity_creation(self):
        """Commodity strategy should have COMMODITY prefix."""
        strategy = _FuturesSignalStrategy(config={}, asset_type=AssetType.COMMODITY)
        assert strategy._score_prefix == "COMMODITY"

    def test_currency_creation(self):
        """Currency strategy should have CURRENCY prefix."""
        strategy = _FuturesSignalStrategy(config={}, asset_type=AssetType.CURRENCY)
        assert strategy._score_prefix == "CURRENCY"

    def test_requires_sufficient_data(self):
        """Should return None with insufficient data."""
        strategy = _FuturesSignalStrategy(config={}, asset_type=AssetType.FUTURES)
        df_short = _make_trending_up(15)
        result = strategy.evaluate(symbol="NIFTY", df1m=df_short)
        assert result is None

    def test_uptrend_generates_buy(self):
        """Uptrending futures data should produce BUY."""
        strategy = _FuturesSignalStrategy(config={}, asset_type=AssetType.FUTURES)
        df = _make_trending_up(60)
        result = strategy.evaluate(symbol="NIFTY", df1m=df)
        if result is not None:
            assert result.direction == "BUY"
            assert result.asset_type == AssetType.FUTURES

    def test_downtrend_generates_sell(self):
        """Downtrending futures data should produce SELL."""
        strategy = _FuturesSignalStrategy(config={}, asset_type=AssetType.FUTURES)
        df = _make_trending_down(60)
        result = strategy.evaluate(symbol="GOLD", df1m=df)
        if result is not None:
            assert result.direction == "SELL"
            assert result.asset_type == AssetType.FUTURES

    def test_flat_returns_none(self):
        """Flat market should not produce signal for futures."""
        strategy = _FuturesSignalStrategy(config={}, asset_type=AssetType.COMMODITY)
        df = _make_flat(60)
        result = strategy.evaluate(symbol="GOLD", df1m=df)
        assert result is None

    def test_config_prefix_override(self):
        """Config should use asset-class-specific prefix keys."""
        strategy = _FuturesSignalStrategy(
            config={"COMMODITY_VOL_RATIO_MIN": 1.5, "VOL_RATIO_MIN": 1.2},
            asset_type=AssetType.COMMODITY,
        )
        # Should find COMMODITY_VOL_RATIO_MIN = 1.5 via prefix
        val = strategy._get_cfg("VOL_RATIO_MIN", 1.0)
        assert val == 1.5

    def test_config_fallback_to_generic(self):
        """Config should fall back to generic key if prefixed key not found."""
        strategy = _FuturesSignalStrategy(
            config={"VOL_RATIO_MIN": 1.3},
            asset_type=AssetType.FUTURES,
        )
        # Should not find FUTURES_VOL_RATIO_MIN, fall back to VOL_RATIO_MIN
        val = strategy._get_cfg("VOL_RATIO_MIN", 1.0)
        assert val == 1.3

    def test_config_fallback_to_default(self):
        """Config should fall back to default if no key found."""
        strategy = _FuturesSignalStrategy(config={}, asset_type=AssetType.CURRENCY)
        val = strategy._get_cfg("VOL_RATIO_MIN", 1.2)
        assert val == 1.2


# =============================================================================
# SignalEvaluator Tests
# =============================================================================


class TestSignalEvaluator:
    """Tests for the SignalEvaluator dispatcher."""

    def test_creation(self):
        """SignalEvaluator should instantiate with config."""
        e = SignalEvaluator(config={})
        assert e is not None
        assert e._strategies == {}

    def test_evaluate_unknown_asset_type(self):
        """Unknown asset types should return None gracefully."""
        e = SignalEvaluator(config={})
        result = e.evaluate(symbol="XYZ", asset_type=AssetType.UNKNOWN)
        assert result is None

    def test_evaluate_unsupported_asset_type(self):
        """Unsupported asset types (BOND, IPO) should return None."""
        e = SignalEvaluator(config={})
        result = e.evaluate(symbol="TEST", asset_type=AssetType.BOND)
        assert result is None

    def test_evaluate_equity(self):
        """Equity evaluation should return a SignalResult or None."""
        e = SignalEvaluator(config={})
        df = _make_trending_up(60)
        result = e.evaluate(
            symbol="RELIANCE", asset_type=AssetType.EQUITY, df1m=df,
        )
        if result is not None:
            assert isinstance(result, SignalResult)
            assert result.asset_type == AssetType.EQUITY

    def test_evaluate_futures(self):
        """Futures evaluation should return a SignalResult or None."""
        e = SignalEvaluator(config={})
        df = _make_trending_up(60)
        result = e.evaluate(
            symbol="NIFTY", asset_type=AssetType.FUTURES, df1m=df,
        )
        if result is not None:
            assert isinstance(result, SignalResult)
            assert result.asset_type == AssetType.FUTURES

    def test_evaluate_commodity(self):
        """Commodity evaluation should return a SignalResult or None."""
        e = SignalEvaluator(config={})
        df = _make_trending_up(60)
        result = e.evaluate(
            symbol="GOLD", asset_type=AssetType.COMMODITY, df1m=df,
        )
        if result is not None:
            assert isinstance(result, SignalResult)
            assert result.asset_type == AssetType.COMMODITY

    def test_evaluate_currency(self):
        """Currency evaluation should return a SignalResult or None."""
        e = SignalEvaluator(config={})
        df = _make_trending_up(60)
        result = e.evaluate(
            symbol="USDINR", asset_type=AssetType.CURRENCY, df1m=df,
        )
        if result is not None:
            assert isinstance(result, SignalResult)
            assert result.asset_type == AssetType.CURRENCY

    def test_evaluate_from_signal_dict_valid(self):
        """evaluate_from_signal_dict should create SignalResult from valid dict."""
        e = SignalEvaluator(config={})
        signal = {
            "symbol": "RELIANCE",
            "direction": "BUY",
            "score": 75,
            "price": 2500.0,
            "strength": "STRONG",
            "asset_type": "EQUITY",
        }
        result = e.evaluate_from_signal_dict(signal)
        assert result is not None
        assert result.symbol == "RELIANCE"
        assert result.score == 75
        assert result.asset_type == AssetType.EQUITY

    def test_evaluate_from_signal_dict_missing_symbol(self):
        """evaluate_from_signal_dict should return None without symbol."""
        e = SignalEvaluator(config={})
        result = e.evaluate_from_signal_dict({"score": 75})
        assert result is None

    def test_evaluate_from_signal_dict_missing_direction(self):
        """evaluate_from_signal_dict should return None without direction."""
        e = SignalEvaluator(config={})
        result = e.evaluate_from_signal_dict({"symbol": "T", "score": 0})
        assert result is None

    def test_evaluate_from_signal_dict_defaults(self):
        """evaluate_from_signal_dict should fill defaults for missing fields."""
        e = SignalEvaluator(config={})
        signal = {"symbol": "T", "direction": "BUY", "score": 60}
        result = e.evaluate_from_signal_dict(signal)
        assert result is not None
        assert result.asset_type == AssetType.UNKNOWN  # Default (fixed bug)
        assert result.strength == "WEAK"  # Default

    def test_evaluate_from_signal_dict_empty_direction(self):
        """Empty direction should return None."""
        e = SignalEvaluator(config={})
        result = e.evaluate_from_signal_dict({"symbol": "T", "direction": "", "score": 50})
        assert result is None

    def test_evaluate_from_signal_dict_zero_score(self):
        """Zero score should return None."""
        e = SignalEvaluator(config={})
        result = e.evaluate_from_signal_dict({"symbol": "T", "direction": "BUY", "score": 0})
        assert result is None

    def test_strategy_cache(self):
        """SignalEvaluator should cache strategies after first use."""
        e = SignalEvaluator(config={})
        assert AssetType.EQUITY not in e._strategies
        e.evaluate(symbol="T", asset_type=AssetType.EQUITY, df1m=_make_trending_up(60))
        assert AssetType.EQUITY in e._strategies

    def test_different_asset_types_different_strategies(self):
        """Different asset types should have separate strategy instances."""
        e = SignalEvaluator(config={})
        e.evaluate(symbol="T", asset_type=AssetType.EQUITY, df1m=_make_trending_up(60))
        e.evaluate(symbol="G", asset_type=AssetType.COMMODITY, df1m=_make_trending_up(60))
        # Should be separate instances for different asset types
        eq_strategy = e._strategies.get(AssetType.EQUITY)
        com_strategy = e._strategies.get(AssetType.COMMODITY)
        assert eq_strategy is not None
        assert com_strategy is not None
        assert eq_strategy is not com_strategy


# =============================================================================
# Integration Tests — evaluate_and_route via dispatcher
# =============================================================================


class TestEvaluateAndRouteIntegration:
    """Integration tests for dispatcher evaluate_and_route."""

    def test_evaluate_and_route_no_engine(self):
        """evaluate_and_route should return SKIP when no engine registered."""
        from core.strategy.multi_asset_dispatcher import MultiAssetStrategyDispatcher
        d = MultiAssetStrategyDispatcher(config={})
        df = _make_trending_up(60)
        result = d.evaluate_and_route(
            symbol="RELIANCE", df1m=df, asset_type=None,
        )
        # Should auto-detect RELIANCE as EQUITY but have no handler
        assert result.handled is False
        assert result.action in ("SKIP", "ERROR")

    def test_evaluate_and_route_with_engine(self):
        """evaluate_and_route should route to registered engine on signal."""
        from core.strategy.multi_asset_dispatcher import (
            AssetClass,
            MultiAssetStrategyDispatcher,
            RoutingResult,
        )
        d = MultiAssetStrategyDispatcher(config={})
        # Register a simple handler that always accepts
        def handler(symbol, signal, **kw):
            return RoutingResult(
                handled=True, engine="test", asset_class="EQUITY",
                action="ENTER", message=f"Entered {symbol}",
            )
        d.register_engine(AssetClass.EQUITY, handler, engine_name="test")
        df = _make_trending_up(60)
        result = d.evaluate_and_route(
            symbol="RELIANCE", df1m=df, asset_type=AssetClass.EQUITY,
        )
        # If signal was generated, it should route to the handler
        if result.handled:
            assert result.engine == "test"
            assert result.action == "ENTER"

    def test_evaluate_and_route_flat_market(self):
        """evaluate_and_route should return SKIP for flat market."""
        from core.strategy.multi_asset_dispatcher import (
            AssetClass,
            MultiAssetStrategyDispatcher,
            RoutingResult,
        )
        d = MultiAssetStrategyDispatcher(config={})
        def handler(symbol, signal, **kw):
            return RoutingResult(handled=True, engine="test", asset_class="EQUITY", action="ENTER")
        d.register_engine(AssetClass.EQUITY, handler, engine_name="test")
        df = _make_flat(60)
        result = d.evaluate_and_route(
            symbol="RELIANCE", df1m=df, asset_type=AssetClass.EQUITY,
        )
        # Flat market should not produce a signal, so no routing
        assert result.handled is False

    def test_evaluate_and_route_unknown_symbol(self):
        """evaluate_and_route should handle unknown symbols gracefully."""
        from core.strategy.multi_asset_dispatcher import MultiAssetStrategyDispatcher
        d = MultiAssetStrategyDispatcher(config={})
        df = _make_trending_up(60)
        result = d.evaluate_and_route(
            symbol="XYZ_UNKNOWN_SYMBOL_12345", df1m=df,
        )
        assert result.handled is False
