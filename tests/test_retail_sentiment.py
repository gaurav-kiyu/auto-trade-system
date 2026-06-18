"""Tests for core/retail_sentiment.py - retail euphoria/panic detection."""

from __future__ import annotations

import numpy as np
import pandas as pd
from core.retail_sentiment import RetailSentimentAnalyzer, RetailSentimentResult


def _make_df(close_prices: list[float], volumes: list[int]) -> pd.DataFrame:
    return pd.DataFrame({"Close": close_prices, "Volume": volumes})


class TestInit:
    def test_default_config(self) -> None:
        r = RetailSentimentAnalyzer({})
        assert r.vol_z_threshold == 2.0
        assert r.price_stagnation_thresh == 0.001

    def test_custom_config(self) -> None:
        r = RetailSentimentAnalyzer({
            "retail_vol_z_threshold": 3.0,
            "retail_stagnation_pct": 0.005,
        })
        assert r.vol_z_threshold == 3.0
        assert r.price_stagnation_thresh == 0.005


class TestAnalyze:
    def test_none_df_returns_neutral(self) -> None:
        r = RetailSentimentAnalyzer({})
        result = r.analyze("NIFTY", "CALL", None)
        assert isinstance(result, RetailSentimentResult)
        assert result.is_blocked is False
        assert result.sentiment == "NEUTRAL"
        assert "Insufficient" in result.reason

    def test_short_df_returns_neutral(self) -> None:
        r = RetailSentimentAnalyzer({})
        df = _make_df([100.0] * 10, [1000] * 10)
        result = r.analyze("NIFTY", "CALL", df)
        assert result.is_blocked is False
        assert result.sentiment == "NEUTRAL"

    def test_sufficient_data_healthy(self) -> None:
        r = RetailSentimentAnalyzer({})
        prices = list(np.linspace(100, 105, 30))
        volumes = [1000 + i * 10 for i in range(30)]
        df = _make_df(prices, volumes)
        result = r.analyze("NIFTY", "CALL", df)
        assert result.sentiment == "NEUTRAL"
        assert result.is_blocked is False

    def test_euphoria_detected(self) -> None:
        """Volume spike (z > threshold) with price stagnation on CALL = Euphoria."""
        r = RetailSentimentAnalyzer({
            "retail_vol_z_threshold": 1.0,
            "retail_stagnation_pct": 0.02,
        })
        rng = np.random.default_rng(42)
        volumes = list(rng.integers(900, 1100, 29)) + [3000]
        prices = [100.0] * 29 + [100.05]
        df = _make_df(prices, volumes)
        result = r.analyze("NIFTY", "CALL", df)
        assert result.is_blocked is True, f"Expected blocked, got {result}"
        assert result.sentiment == "EUPHORIA"

    def test_panic_detected(self) -> None:
        """Volume spike (z > threshold) with price stagnation on PUT = Panic."""
        r = RetailSentimentAnalyzer({
            "retail_vol_z_threshold": 1.0,
            "retail_stagnation_pct": 0.02,
        })
        rng = np.random.default_rng(42)
        volumes = list(rng.integers(900, 1100, 29)) + [3000]
        prices = [100.0] * 29 + [100.05]
        df = _make_df(prices, volumes)
        result = r.analyze("NIFTY", "PUT", df)
        assert result.is_blocked is True, f"Expected blocked, got {result}"
        assert result.sentiment == "PANIC"

    def test_volume_spike_with_price_move_not_blocked(self) -> None:
        """Volume spike is fine if price moves (no stagnation)."""
        r = RetailSentimentAnalyzer({
            "retail_vol_z_threshold": 1.0,
            "retail_stagnation_pct": 0.001,
        })
        rng = np.random.default_rng(42)
        volumes = list(rng.integers(900, 1100, 29)) + [3000]
        prices = [100.0] * 29 + [105.0]
        df = _make_df(prices, volumes)
        result = r.analyze("NIFTY", "CALL", df)
        assert result.is_blocked is False
        assert result.sentiment == "NEUTRAL"

    def test_low_z_score_not_blocked(self) -> None:
        r = RetailSentimentAnalyzer({"retail_vol_z_threshold": 3.0})
        rng = np.random.default_rng(42)
        volumes = list(rng.integers(900, 1100, 30))
        prices = list(np.linspace(100, 103, 30))
        df = _make_df(prices, volumes)
        result = r.analyze("NIFTY", "CALL", df)
        assert result.is_blocked is False
        assert result.sentiment == "NEUTRAL"

    def test_confidence_caps_at_one(self) -> None:
        r = RetailSentimentAnalyzer({
            "retail_vol_z_threshold": 1.0,
            "retail_stagnation_pct": 0.02,
        })
        rng = np.random.default_rng(42)
        volumes = list(rng.integers(900, 1100, 29)) + [5000]
        prices = [100.0] * 29 + [100.05]
        df = _make_df(prices, volumes)
        result = r.analyze("NIFTY", "CALL", df)
        assert result.confidence <= 1.0

    def test_result_dataclass(self) -> None:
        result = RetailSentimentResult(
            is_blocked=True,
            sentiment="EUPHORIA",
            confidence=0.8,
            reason="Test reason",
        )
        assert result.is_blocked is True
        assert result.sentiment == "EUPHORIA"
        assert result.confidence == 0.8
        assert result.reason == "Test reason"
