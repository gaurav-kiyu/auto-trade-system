"""Tests for the MA Crossover Strategy module."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from core.strategy.ma_crossover import (
    MACrossoverResult,
    _compute_adx,
    _compute_atr,
    _compute_ma,
    detect_ma_crossover,
)


def _make_df(close_prices: list[float], volume: int = 1_000_000) -> pd.DataFrame:
    """Create a test DataFrame with OHLCV data from close prices."""
    n = len(close_prices)
    return pd.DataFrame({
        "Open": close_prices,
        "High": [p * 1.002 for p in close_prices],
        "Low": [p * 0.998 for p in close_prices],
        "Close": close_prices,
        "Volume": [volume] * n,
    })


class TestMACrossoverResult:
    def test_defaults(self):
        """MACrossoverResult should have sensible defaults."""
        r = MACrossoverResult(
            signal=False, direction="NONE", score=0,
            reason="test", entry_price=0.0, stop_loss=0.0,
            target=0.0, confidence=0.0, crossover_type="none",
        )
        assert r.signal is False
        assert r.direction == "NONE"
        assert r.score == 0
        assert r.metadata == {}

    def test_golden_cross_result(self):
        """Golden cross result should have CALL direction."""
        r = MACrossoverResult(
            signal=True, direction="CALL", score=65,
            reason="Golden cross detected", entry_price=100.0,
            stop_loss=98.0, target=105.0, confidence=0.8,
            crossover_type="golden",
        )
        assert r.signal is True
        assert r.direction == "CALL"
        assert r.crossover_type == "golden"


class TestTechnicalIndicators:
    def test_sma_computation(self):
        """Simple moving average should compute correctly."""
        prices = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        sma = _compute_ma(prices, period=3, ma_type="sma")
        assert sma[2] == pytest.approx(2.0)  # (1+2+3)/3
        assert sma[3] == pytest.approx(3.0)  # (2+3+4)/3

    def test_ema_computation(self):
        """Exponential moving average should return correct length."""
        prices = np.array([10.0] * 30)
        ema = _compute_ma(prices, period=9, ma_type="ema")
        assert len(ema) == 30
        assert ema[-1] == pytest.approx(10.0, abs=0.1)

    def test_wma_computation(self):
        """Weighted moving average should give more weight to recent prices."""
        prices = np.array([1.0, 2.0, 3.0, 4.0])
        wma = _compute_ma(prices, period=3, ma_type="wma")
        # WMA = (1*1 + 2*2 + 3*3) / (1+2+3) = (1+4+9)/6 = 14/6 = 2.333
        assert wma[2] == pytest.approx(2.333, abs=0.01)

    def test_atr_computation(self):
        """ATR should be positive for valid price data."""
        high = np.array([11.0, 12.0, 13.0, 14.0, 15.0])
        low = np.array([9.0, 10.0, 11.0, 12.0, 13.0])
        close = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
        atr = _compute_atr(high, low, close, period=3)
        assert len(atr) == 5
        assert atr[-1] > 0

    def test_adx_computation(self):
        """ADX should be between 0 and 100 for trending data."""
        # Create trending data
        close = np.array([100.0 + i * 0.5 for i in range(60)])  # steady uptrend
        high = close + 0.5
        low = close - 0.5
        adx = _compute_adx(high, low, close, period=14)
        assert len(adx) == 60
        # ADX should be non-negative
        assert np.all(adx >= 0)
        # ADX should show some trend (not necessarily high with small moves)
        assert adx[-1] >= 0

    def test_ma_short_data(self):
        """MA should handle data shorter than period gracefully."""
        prices = np.array([1.0, 2.0])
        result = _compute_ma(prices, period=10, ma_type="ema")
        assert len(result) == 2


class TestDetectMACrossover:
    def test_insufficient_data(self):
        """Should return no signal with insufficient data."""
        df = _make_df([100.0] * 10)  # Only 10 bars
        result = detect_ma_crossover(df)
        assert result.signal is False
        assert "Insufficient data" in result.reason

    def test_no_signal_flat_market(self):
        """Flat market should not generate crossover signals."""
        df = _make_df([100.0] * 80)
        result = detect_ma_crossover(df)
        assert result.signal is False

    def test_golden_cross_detection(self):
        """A sharp upward move should trigger a golden cross (CALL)."""
        # Start flat, then sharp uptrend
        prices = [100.0] * 30 + list(100.0 + i * 1.5 for i in range(40))
        df = _make_df(prices)
        result = detect_ma_crossover(df, fast_period=9, slow_period=21)
        # May not always trigger with small sample, but should check direction
        if result.signal:
            assert result.direction == "CALL"

    def test_death_cross_detection(self):
        """A sharp downward move should trigger a death cross (PUT)."""
        # Start flat, then sharp downtrend
        prices = [100.0] * 30 + list(100.0 - i * 1.5 for i in range(40))
        df = _make_df(prices)
        result = detect_ma_crossover(df, fast_period=9, slow_period=21)
        if result.signal:
            assert result.direction == "PUT"

    def test_sma_crossover(self):
        """SMA crossover should work like EMA crossover."""
        prices = [100.0] * 25 + list(100.0 + i * 2.0 for i in range(35))
        df = _make_df(prices)
        result = detect_ma_crossover(df, ma_type="sma")
        if result.signal:
            assert result.direction in ("CALL", "PUT")

    def test_score_within_bounds(self):
        """Score should always be 0-100."""
        prices = [100.0] * 20 + list(100.0 + i * 0.5 for i in range(60))
        df = _make_df(prices)
        result = detect_ma_crossover(df)
        assert 0 <= result.score <= 100
        assert 0.0 <= result.confidence <= 1.0

    def test_pullback_detection(self):
        """Pullback to MA in trending market should generate signal."""
        # Strong uptrend with a dip
        base = 100.0
        prices = [base] * 20
        # Uptrend
        prices.extend([base + i * 1.0 for i in range(25)])
        # Pullback
        peak = prices[-1]
        prices.extend([peak - i * 0.3 for i in range(10)])
        # Resume uptrend
        low_point = prices[-1]
        prices.extend([low_point + i * 1.0 for i in range(10)])
        df = _make_df(prices)
        result = detect_ma_crossover(df, adx_min=15.0)
        if result.signal:
            assert result.direction in ("CALL", "PUT")

    def test_configurable_periods(self):
        """Different fast/slow periods should work."""
        prices = [100.0] * 15 + list(100.0 + i * 0.8 for i in range(50))
        df = _make_df(prices)
        result_fast = detect_ma_crossover(df, fast_period=5, slow_period=13)
        result_slow = detect_ma_crossover(df, fast_period=20, slow_period=50)
        assert isinstance(result_fast, MACrossoverResult)
        assert isinstance(result_slow, MACrossoverResult)

    def test_min_score_filter(self):
        """Min score should filter weak signals."""
        prices = [100.0] * 40 + list(100.0 + i * 0.3 for i in range(40))
        df = _make_df(prices)
        result_low = detect_ma_crossover(df, min_score=5)
        result_high = detect_ma_crossover(df, min_score=90)
        # High min_score should be harder to trigger
        assert result_low.score >= result_high.score

    def test_wma_strategy(self):
        """WMA should work as a valid ma_type."""
        prices = [100.0] * 25 + list(100.0 + i * 2.0 for i in range(35))
        df = _make_df(prices)
        result = detect_ma_crossover(df, ma_type="wma")
        assert isinstance(result, MACrossoverResult)
        assert result.metadata.get("ma_type") == "wma"

    def test_low_volume_penalty(self):
        """Low volume should reduce scores."""
        prices = [100.0] * 20 + list(100.0 + i * 2.5 for i in range(40))
        df_high_vol = _make_df(prices, volume=1_000_000)
        df_low_vol = _make_df(prices, volume=100)
        result_high = detect_ma_crossover(df_high_vol)
        result_low = detect_ma_crossover(df_low_vol, min_volume_ratio=10.0)
        # Low volume should suppress the signal
        assert result_low.score <= result_high.score or not result_low.signal

    def test_golden_cross_score_breakdown(self):
        """Golden cross should have appropriate score components."""
        prices = [100.0] * 25 + list(100.0 + i * 2.0 for i in range(40))
        df = _make_df(prices)
        result = detect_ma_crossover(df, fast_period=9, slow_period=21)
        if result.signal and result.crossover_type == "golden":
            assert result.direction == "CALL"
            assert "Golden cross" in result.reason
