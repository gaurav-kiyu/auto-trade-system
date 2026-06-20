"""
Tests for core/strategy/strategies.py - Strategy implementations.

Covers:
  - BaseStrategy (abstract evaluate)
  - TrendAlignmentStrategy (trend UP/DOWN/FLAT, aligned, regime CHOPPY)
  - MeanReversionStrategy (CHOPPY regime, oversold/overbought, stretched)
  - VWAPStrategy (above/below, CHOPPY regime disabled)
  - VolumeStrategy (surge >= threshold, low volume)
  - ATRStrategy (healthy ATR, low ATR)
  - MomentumStrategy (MACD bullish/bearish/neutral)
  - RSIStrategy (overbought/oversold/healthy/neutral, regime-aware)
  - SmartMoneyStrategy (OI BULLISH/BEARISH, PCR support/neutral)
"""

from __future__ import annotations

import pytest

from core.strategy.strategies import (
    ATRStrategy,
    BaseStrategy,
    MeanReversionStrategy,
    MomentumStrategy,
    RSIStrategy,
    SmartMoneyStrategy,
    TrendAlignmentStrategy,
    VolumeStrategy,
    VWAPStrategy,
)


class TestBaseStrategy:
    def test_abstract_evaluate(self):
        s = BaseStrategy("test", {})
        with pytest.raises(NotImplementedError):
            s.evaluate({}, "CALL")


class TestTrendAlignmentStrategy:
    @pytest.fixture
    def strat(self):
        return TrendAlignmentStrategy("trend_align", {})

    def test_flat_trend_returns_zero(self, strat):
        result = strat.evaluate({"trend_5m": "FLAT"}, "CALL")
        assert result["score"] == 0
        assert "FLAT" in result["reason"]

    def test_direction_contradicts_trend(self, strat):
        result = strat.evaluate({"trend_5m": "UP"}, "PUT")
        assert result["score"] == 0
        assert "contradicts" in result["reason"]

    def test_aligned_timeframes(self, strat):
        result = strat.evaluate({"trend_5m": "UP", "timeframe_aligned": True, "regime": "TRENDING"}, "CALL")
        assert result["score"] == 20
        assert result["status"] is True

    def test_unaligned_timeframes(self, strat):
        result = strat.evaluate({"trend_5m": "UP", "timeframe_aligned": False, "regime": "TRENDING"}, "CALL")
        assert result["score"] == 10
        assert result["status"] is True

    def test_choppy_regime(self, strat):
        result = strat.evaluate({"trend_5m": "UP", "timeframe_aligned": True, "regime": "CHOPPY"}, "CALL")
        assert result["score"] == 5
        assert "CHOPPY" in result["reason"]

    def test_down_trend_call_conflict(self, strat):
        result = strat.evaluate({"trend_5m": "DOWN"}, "CALL")
        assert result["score"] == 0

    def test_down_trend_put_align(self, strat):
        result = strat.evaluate({"trend_5m": "DOWN", "timeframe_aligned": True, "regime": "TRENDING"}, "PUT")
        assert result["score"] == 20


class TestMeanReversionStrategy:
    @pytest.fixture
    def strat(self):
        return MeanReversionStrategy("mean_rev", {})

    def test_not_choppy_returns_zero(self, strat):
        result = strat.evaluate({"regime": "TRENDING"}, "CALL")
        assert result["score"] == 0
        assert "Not a choppy regime" in result["reason"]

    def test_call_oversold_under_vwap(self, strat):
        # price=50000, vwap=50300: dist_pct = 300/50300 = 0.00596 > 0.005 (stretched)
        result = strat.evaluate({"regime": "CHOPPY", "rsi": 30, "price": 50000, "vwap": 50300}, "CALL")
        assert result["score"] == 25
        assert result["status"] is True

    def test_put_overbought_above_vwap(self, strat):
        # price=50300, vwap=50000: dist_pct = 300/50000 = 0.006 > 0.005 (stretched)
        result = strat.evaluate({"regime": "CHOPPY", "rsi": 65, "price": 50300, "vwap": 50000}, "PUT")
        assert result["score"] == 25
        assert result["status"] is True

    def test_not_stretched(self, strat):
        result = strat.evaluate({"regime": "CHOPPY", "rsi": 30, "price": 50005, "vwap": 50100}, "CALL")
        assert result["score"] == 0  # dist_pct = 95/50100 = 0.0019 < 0.005

    def test_no_setup(self, strat):
        result = strat.evaluate({"regime": "CHOPPY", "rsi": 50, "price": 50000, "vwap": 50000}, "CALL")
        assert result["score"] == 0


class TestVWAPStrategy:
    @pytest.fixture
    def strat(self):
        return VWAPStrategy("vwap", {})

    def test_choppy_disabled(self, strat):
        result = strat.evaluate({"vwap_position": "above", "regime": "CHOPPY"}, "CALL")
        assert result["score"] == 0
        assert "CHOPPY" in result["reason"]

    def test_call_above_vwap(self, strat):
        result = strat.evaluate({"vwap_position": "above", "regime": "TRENDING"}, "CALL")
        assert result["score"] == 15

    def test_put_below_vwap(self, strat):
        result = strat.evaluate({"vwap_position": "below", "regime": "TRENDING"}, "PUT")
        assert result["score"] == 15

    def test_contradicts_direction(self, strat):
        result = strat.evaluate({"vwap_position": "above", "regime": "TRENDING"}, "PUT")
        assert result["score"] == 0
        assert "against" in result["reason"]


class TestVolumeStrategy:
    @pytest.fixture
    def strat(self):
        return VolumeStrategy("vol", {})

    def test_high_volume(self, strat):
        result = strat.evaluate({"vol_ratio": 2.0}, "CALL")
        assert result["score"] == 10
        assert "Surge" in result["reason"]

    def test_low_volume(self, strat):
        result = strat.evaluate({"vol_ratio": 1.0}, "CALL")
        assert result["score"] == 0
        assert "Low Volume" in result["reason"]

    def test_custom_threshold(self, strat):
        result = strat.evaluate({"vol_ratio": 1.5}, "CALL")
        assert result["score"] == 10  # 1.5 >= 1.2


class TestATRStrategy:
    @pytest.fixture
    def strat(self):
        return ATRStrategy("atr", {})

    def test_healthy_atr(self, strat):
        result = strat.evaluate({"atr": 1.0}, "CALL")
        assert result["score"] == 5
        assert "Healthy" in result["reason"]

    def test_low_atr(self, strat):
        result = strat.evaluate({"atr": 0.1}, "CALL")
        assert result["score"] == 0
        assert "Low ATR" in result["reason"]


class TestMomentumStrategy:
    @pytest.fixture
    def strat(self):
        return MomentumStrategy("momentum", {})

    def test_bullish_macd(self, strat):
        result = strat.evaluate({"macd": {"histogram": 5.0, "macd": 10.0, "signal": 8.0}}, "CALL")
        assert result["score"] == 5
        assert "Bullish" in result["reason"]

    def test_bearish_macd(self, strat):
        result = strat.evaluate({"macd": {"histogram": -5.0, "macd": 8.0, "signal": 10.0}}, "PUT")
        assert result["score"] == 5
        assert "Bearish" in result["reason"]

    def test_neutral_macd(self, strat):
        result = strat.evaluate({"macd": {"histogram": 0, "macd": 10.0, "signal": 10.0}}, "CALL")
        assert result["score"] == 0
        assert "Neutral" in result["reason"]

    def test_bullish_histogram_but_below_signal(self, strat):
        result = strat.evaluate({"macd": {"histogram": 5.0, "macd": 8.0, "signal": 10.0}}, "CALL")
        assert result["score"] == 0  # m_line < s_line


class TestRSIStrategy:
    @pytest.fixture
    def strat(self):
        return RSIStrategy("rsi", {})

    def test_trending_overbought_call_penalty(self, strat):
        result = strat.evaluate({"rsi": 75, "regime": "TRENDING"}, "CALL")
        assert result["score"] == -10
        assert "Overbought" in result["reason"]

    def test_trending_oversold_put_penalty(self, strat):
        result = strat.evaluate({"rsi": 25, "regime": "TRENDING"}, "PUT")
        assert result["score"] == -10
        assert "Oversold" in result["reason"]

    def test_healthy_call_rsi(self, strat):
        result = strat.evaluate({"rsi": 50, "regime": "TRENDING"}, "CALL")
        assert result["score"] == 8
        assert result["status"] is True

    def test_healthy_put_rsi(self, strat):
        result = strat.evaluate({"rsi": 45, "regime": "TRENDING"}, "PUT")
        assert result["score"] == 8
        assert result["status"] is True

    def test_neutral_rsi(self, strat):
        # rsi=35 with CALL: below healthy range (40-70) but not overbought (>70) — neutral
        result = strat.evaluate({"rsi": 35, "regime": "TRENDING"}, "CALL")
        assert result["score"] == 0

    def test_choppy_no_penalty(self, strat):
        """In CHOPPY regime, overbought doesn't get penalty."""
        result = strat.evaluate({"rsi": 75, "regime": "CHOPPY"}, "CALL")
        assert result["score"] >= 0  # No -10 penalty


class TestSmartMoneyStrategy:
    @pytest.fixture
    def strat(self):
        return SmartMoneyStrategy("smart_money", {})

    def test_bullish_oi_and_pcr(self, strat):
        result = strat.evaluate({"smart_money": "BULLISH", "pcr": 1.5}, "CALL")
        assert result["status"] is True
        assert result["score"] == 15  # 10 (OI) + 5 (PCR)

    def test_bearish_oi_and_pcr(self, strat):
        result = strat.evaluate({"smart_money": "BEARISH", "pcr": 0.5}, "PUT")
        assert result["status"] is True
        assert result["score"] == 15

    def test_oi_neutral_pcr_supports(self, strat):
        result = strat.evaluate({"smart_money": "NEUTRAL", "pcr": 1.5}, "CALL")
        assert result["score"] == 5  # 0 (OI) + 5 (PCR)
        assert result["status"] is True

    def test_oi_neutral_pcr_neutral(self, strat):
        result = strat.evaluate({"smart_money": "NEUTRAL", "pcr": 1.0}, "CALL")
        assert result["score"] == 0
