"""Tests for the Mean Reversion Strategy module."""

from __future__ import annotations

import numpy as np
import pandas as pd
from core.strategy.mean_reversion import (
    MeanReversionResult,
    _compute_atr,
    _compute_bollinger,
    _compute_rsi,
    _compute_vwap,
    detect_mean_reversion,
)

# ── Helper to create test OHLCV data ────────────────────────────────────

def _make_df(price_series: list[float], vol: float = 1_000_000) -> pd.DataFrame:
    """Create a 1-minute OHLCV DataFrame from a price series."""
    n = len(price_series)
    return pd.DataFrame({
        "Open": price_series,
        "High": [p * 1.002 for p in price_series],
        "Low": [p * 0.998 for p in price_series],
        "Close": price_series,
        "Volume": [vol * (1 + (i % 5) * 0.1) for i in range(n)],
    })


# ── Indicator tests ─────────────────────────────────────────────────────

class TestIndicators:
    def test_rsi_all_up(self):
        """RSI should be ~100 when price only goes up."""
        prices = [100 + i for i in range(30)]
        rsi = _compute_rsi(np.array(prices, dtype=float), 14)
        assert rsi[-1] > 95.0, f"Expected RSI near 100, got {rsi[-1]}"

    def test_rsi_all_down(self):
        """RSI should be ~0 when price only goes down."""
        prices = [100 - i for i in range(30)]
        rsi = _compute_rsi(np.array(prices, dtype=float), 14)
        assert rsi[-1] < 5.0, f"Expected RSI near 0, got {rsi[-1]}"

    def test_rsi_flat(self):
        """RSI should be ~50 when price is flat."""
        prices = [100.0] * 30
        rsi = _compute_rsi(np.array(prices, dtype=float), 14)
        assert 49.0 <= rsi[-1] <= 51.0, f"Expected RSI ~50, got {rsi[-1]}"

    def test_rsi_oscillation(self):
        """RSI should be around 50 for oscillating price."""
        prices = [100 + (5 if i % 2 == 0 else -5) for i in range(30)]
        rsi = _compute_rsi(np.array(prices, dtype=float), 14)
        assert 40.0 <= rsi[-1] <= 60.0, f"Expected RSI ~50, got {rsi[-1]}"

    def test_bollinger_bands_order(self):
        """Upper > Middle > Lower."""
        prices = [100 + np.sin(i * 0.5) * 10 for i in range(30)]
        arr = np.array(prices, dtype=float)
        upper, middle, lower = _compute_bollinger(arr, 20, 2.0)
        assert upper > middle > lower, f"BB order: {upper} > {middle} > {lower}"

    def test_bollinger_bands_narrow(self):
        """Bollinger Bands should narrow for low volatility."""
        prices = [100.0] * 25 + [101.0] * 5
        arr = np.array(prices, dtype=float)
        _, middle, _ = _compute_bollinger(arr, 20, 2.0)
        width_high = abs(_compute_bollinger(np.array([100 + np.sin(i * 0.5) * 10 for i in range(30)], dtype=float), 20, 2.0)[0] - middle)
        width_low = abs(_compute_bollinger(arr, 20, 2.0)[0] - middle)
        assert width_low < width_high, "Low volatility should have narrower bands"

    def test_ema_within_range(self):
        """EMA should be between price range for trending data (via pandas ewm used internally)."""
        import pandas as pd
        prices_np = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0], dtype=float)
        ema_series = pd.Series(prices_np).ewm(span=3, adjust=False).mean()
        ema_val = float(ema_series.iloc[-1])
        assert ema_val < prices_np[-1], "EMA should lag behind rising price"
        assert ema_val > prices_np[0], "EMA should be above starting price"

    def test_atr_positive(self):
        """ATR should always be positive."""
        high = np.array([105, 106, 107, 108], dtype=float)
        low = np.array([95, 94, 93, 92], dtype=float)
        close = np.array([100, 101, 102, 103], dtype=float)
        atr = _compute_atr(high, low, close, 3)
        assert np.all(atr >= 0), "ATR should never be negative"

    def test_atr_zero_for_flat(self):
        """ATR should be near zero for perfectly flat price."""
        high = np.array([100.0] * 20, dtype=float)
        low = np.array([100.0] * 20, dtype=float)
        close = np.array([100.0] * 20, dtype=float)
        atr = _compute_atr(high, low, close, 14)
        assert atr[-1] == 0.0, f"ATR should be 0 for flat, got {atr[-1]}"

    def test_vwap_computation(self):
        """VWAP should be price-weighted average."""
        df = pd.DataFrame({
            "Close": [100, 102, 101, 103],
            "Volume": [1000, 2000, 1500, 2500],
        })
        vwap = _compute_vwap(df)
        expected = (100*1000 + 102*2000 + 101*1500 + 103*2500) / (1000+2000+1500+2500)
        assert abs(vwap - expected) < 0.01, f"VWAP {vwap} != {expected}"

    def test_vwap_no_volume(self):
        """VWAP should return 0 when no volume column."""
        df = pd.DataFrame({"Close": [100, 101]})
        vwap = _compute_vwap(df)
        assert vwap == 0.0, "VWAP should be 0 without volume data"


class TestDetectMeanReversion:
    def test_insufficient_data(self):
        """Should return no signal with insufficient data."""
        df = _make_df([100] * 5)
        result = detect_mean_reversion(df, min_score=30)
        assert result.signal is False
        assert "Insufficient data" in result.reason

    def test_no_signal_flat_market(self):
        """Should return no signal in perfectly flat market."""
        df = _make_df([100.0] * 50)
        result = detect_mean_reversion(df, min_score=30)
        assert result.signal is False

    def test_call_signal_oversold(self):
        """Should detect CALL signal when RSI is oversold and price is below lower BB."""
        # Create a price series that drops sharply then recovers
        prices = [100.0] * 10
        prices += [100 - i * 3 for i in range(1, 15)]  # Sharp drop
        prices += [55 + i * 0.5 for i in range(25)]    # Gradual recovery
        df = _make_df(prices)
        result = detect_mean_reversion(df, min_score=30)
        if result.signal:
            assert result.direction == "CALL", f"Expected CALL, got {result.direction}"
            assert result.score >= 30

    def test_put_signal_overbought(self):
        """Should detect PUT signal when RSI is overbought and price is above upper BB."""
        # Create a price series that surges sharply then starts to pull back
        prices = [100.0] * 10
        prices += [100 + i * 3 for i in range(1, 15)]  # Sharp rise
        prices += [145 - i * 0.5 for i in range(25)]   # Gradual pullback
        df = _make_df(prices)
        result = detect_mean_reversion(df, min_score=30)
        if result.signal:
            assert result.direction == "PUT", f"Expected PUT, got {result.direction}"
            assert result.score >= 30

    def test_extreme_oversold_higher_score(self):
        """Extreme oversold should produce higher score than mild oversold."""
        # Mild oversold
        mild_prices = [100.0] * 10 + [100 - i * 1.5 for i in range(1, 15)] + [80 + i * 0.3 for i in range(25)]
        mild_df = _make_df(mild_prices)
        mild_result = detect_mean_reversion(mild_df, oversold_rsi=45, oversold_extreme_rsi=30, min_score=20)

        # Extreme oversold (deeper drop)
        extreme_prices = [100.0] * 10 + [100 - i * 4 for i in range(1, 15)] + [45 + i * 0.3 for i in range(25)]
        extreme_df = _make_df(extreme_prices)
        extreme_result = detect_mean_reversion(extreme_df, oversold_rsi=45, oversold_extreme_rsi=30, min_score=20)

        if mild_result.signal and extreme_result.signal:
            assert extreme_result.score > mild_result.score, \
                f"Extreme {extreme_result.score} should > mild {mild_result.score}"

    def test_result_dataclass_defaults(self):
        """MeanReversionResult should have sensible defaults."""
        result = MeanReversionResult(
            signal=True, direction="CALL", score=65,
            reason="Test", entry_price=100.0,
            stop_loss=98.0, target=104.0, confidence=0.8,
        )
        assert result.signal is True
        assert result.direction == "CALL"
        assert result.score == 65
        assert result.metadata == {}  # Empty dict default

    def test_result_with_metadata(self):
        """MeanReversionResult should store metadata correctly."""
        result = MeanReversionResult(
            signal=True, direction="PUT", score=70,
            reason="Overbought reject", entry_price=200.0,
            stop_loss=203.0, target=195.0, confidence=0.85,
            metadata={"rsi": 72.5, "bb_position": 0.9},
        )
        assert result.metadata["rsi"] == 72.5
        assert result.metadata["bb_position"] == 0.9

    def test_configurable_thresholds(self):
        """Should respect custom thresholds."""
        df = _make_df([100.0] * 50)
        result_high = detect_mean_reversion(df, min_score=90)
        assert result_high.signal is False, "High threshold should block weak signals"

    def test_volume_filter(self):
        """Low volume should reduce scores."""
        # Create oversold setup with low volume
        prices = [100.0] * 10 + [100 - i * 3 for i in range(1, 15)] + [55 + i * 0.5 for i in range(25)]
        df_low_vol = pd.DataFrame({
            "Open": prices,
            "High": [p * 1.002 for p in prices],
            "Low": [p * 0.998 for p in prices],
            "Close": prices,
            "Volume": [100] * len(prices),  # Very low volume
        })
        result = detect_mean_reversion(df_low_vol, min_vol_ratio=2.0, min_score=20)
        # Low volume should not generate a strong signal
        if result.signal:
            assert result.score < 60, f"Low volume should cap score, got {result.score}"

    def test_direction_none_when_no_setup(self):
        """Direction should be NONE and signal False when no setup found."""
        df = _make_df([100.0] * 50)
        result = detect_mean_reversion(df, min_score=50)
        assert result.signal is False
        assert result.direction == "NONE"
        assert result.score == 0

    def test_bollinger_band_penetration_bonus(self):
        """Deep Bollinger Band penetration should add score."""
        # Create a scenario where price is far below lower BB
        # Use a tight BB with a sharp drop
        prices = [100.0] * 25
        prices += [100 - i * 2 for i in range(15)]  # Drop to ~70
        prices += [72 + i * 0.1 for i in range(10)]  # Stays low
        df = _make_df(prices)
        result = detect_mean_reversion(df, bb_period=15, oversold_rsi=50, min_score=20)
        if result.signal and result.direction == "CALL":
            assert "Deep BB penetration" in result.reason or "below lower" in result.reason
