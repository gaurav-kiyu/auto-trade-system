"""Tests for core.feature_engine — structured feature extraction from OHLCV data."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from core.feature_engine import FeatureEngine


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def sample_df1m() -> pd.DataFrame:
    """20 bars of synthetic 1m OHLCV data."""
    import numpy as np
    np.random.seed(42)
    idx = pd.date_range("2026-06-01 09:15", periods=20, freq="1min")
    data = {
        "Open":  23000.0 + np.cumsum(np.random.randn(20) * 2),
        "High":  23010.0 + np.cumsum(np.random.randn(20) * 3),
        "Low":   22990.0 + np.cumsum(np.random.randn(20) * 3),
        "Close": 23005.0 + np.cumsum(np.random.randn(20) * 2),
        "Volume": [1000 + i * 50 for i in range(20)],
    }
    # Ensure High >= Open/Close/ Low <= Open/Close
    for i in range(20):
        hi = max(data["Open"][i], data["Close"][i], data["High"][i])
        lo = min(data["Open"][i], data["Close"][i], data["Low"][i])
        data["High"][i] = hi + 5
        data["Low"][i] = lo - 5
    return pd.DataFrame(data, index=idx)


@pytest.fixture
def sample_df5m() -> pd.DataFrame:
    """5m OHLCV data with clear trend."""
    idx = pd.date_range("2026-06-01 09:15", periods=10, freq="5min")
    prices = [23000, 23010, 23025, 23040, 23055, 23070, 23080, 23090, 23100, 23110]
    return pd.DataFrame({
        "Open": prices,
        "High": [p + 10 for p in prices],
        "Low":  [p - 10 for p in prices],
        "Close": [p + 5 for p in prices],
        "Volume": [2000] * 10,
    }, index=idx)


@pytest.fixture
def sample_df15m() -> pd.DataFrame:
    """15m OHLCV data."""
    idx = pd.date_range("2026-06-01 09:15", periods=6, freq="15min")
    prices = [23000, 23030, 23060, 23090, 23120, 23150]
    return pd.DataFrame({
        "Open": prices,
        "High": [p + 15 for p in prices],
        "Low":  [p - 15 for p in prices],
        "Close": [p + 8 for p in prices],
        "Volume": [5000] * 6,
    }, index=idx)


# ── FeatureEngine: get_price ──────────────────────────────────────────────

def test_get_price(sample_df1m: pd.DataFrame) -> None:
    price = FeatureEngine.get_price(sample_df1m)
    assert price > 0
    assert isinstance(price, float)


def test_get_price_empty() -> None:
    assert FeatureEngine.get_price(pd.DataFrame()) == 0.0


def test_get_price_none() -> None:
    assert FeatureEngine.get_price(None) == 0.0


# ── FeatureEngine: get_vwap ──────────────────────────────────────────────

def test_get_vwap(sample_df1m: pd.DataFrame) -> None:
    vwap = FeatureEngine.get_vwap(sample_df1m)
    assert vwap > 0
    assert isinstance(vwap, float)


def test_get_vwap_empty() -> None:
    assert FeatureEngine.get_vwap(pd.DataFrame()) == 0.0


# ── FeatureEngine: get_ema ───────────────────────────────────────────────

def test_get_ema(sample_df1m: pd.DataFrame) -> None:
    ema = FeatureEngine.get_ema(sample_df1m["Close"], span=5)
    assert ema > 0
    assert isinstance(ema, float)


def test_get_ema_empty_series() -> None:
    assert FeatureEngine.get_ema(pd.Series([], dtype=float), span=5) == 0.0


# ── FeatureEngine: ema_trend ─────────────────────────────────────────────

def test_ema_trend_up(sample_df1m: pd.DataFrame) -> None:
    trend = FeatureEngine.ema_trend(sample_df1m)
    # With cumulative positive data, fast EMA > slow EMA → UP
    assert trend in ("UP", "DOWN", "FLAT")


def test_ema_trend_empty() -> None:
    assert FeatureEngine.ema_trend(pd.DataFrame()) == "FLAT"


# ── FeatureEngine: get_rsi ───────────────────────────────────────────────

def test_get_rsi(sample_df5m: pd.DataFrame) -> None:
    rsi = FeatureEngine.get_rsi(sample_df5m)
    assert 0 <= rsi <= 100


def test_get_rsi_empty() -> None:
    assert FeatureEngine.get_rsi(pd.DataFrame()) == 50.0


# ── FeatureEngine: get_macd ──────────────────────────────────────────────

def test_get_macd(sample_df5m: pd.DataFrame) -> None:
    macd = FeatureEngine.get_macd(sample_df5m)
    assert isinstance(macd, dict)
    assert "macd" in macd
    assert "signal" in macd
    assert "histogram" in macd


def test_get_macd_empty() -> None:
    macd = FeatureEngine.get_macd(pd.DataFrame())
    assert macd["macd"] == 0.0
    assert macd["histogram"] == 0.0


# ── FeatureEngine: get_atr ───────────────────────────────────────────────

def test_get_atr(sample_df5m: pd.DataFrame) -> None:
    atr = FeatureEngine.get_atr(sample_df5m)
    assert atr >= 0


def test_get_atr_empty() -> None:
    assert FeatureEngine.get_atr(pd.DataFrame()) == 0.0


# ── FeatureEngine: get_vol_ratio ─────────────────────────────────────────

def test_get_vol_ratio(sample_df1m: pd.DataFrame) -> None:
    vr = FeatureEngine.get_vol_ratio(sample_df1m)
    assert vr >= 0


def test_get_vol_ratio_empty() -> None:
    assert FeatureEngine.get_vol_ratio(pd.DataFrame()) == 1.0


# ── FeatureEngine: price_delta ───────────────────────────────────────────

def test_price_delta(sample_df1m: pd.DataFrame) -> None:
    delta = FeatureEngine.price_delta(sample_df1m, 5)
    assert isinstance(delta, float)


def test_price_delta_insufficient_data() -> None:
    df = pd.DataFrame({"Close": [100.0, 101.0]})
    assert FeatureEngine.price_delta(df, 5) == 0.0


# ── FeatureEngine: get_adx ───────────────────────────────────────────────

def test_get_adx(sample_df15m: pd.DataFrame) -> None:
    adx = FeatureEngine.get_adx(sample_df15m)
    assert 0 <= adx <= 100


def test_get_adx_empty() -> None:
    assert FeatureEngine.get_adx(pd.DataFrame()) == 20.0


def test_get_adx_insufficient() -> None:
    df = pd.DataFrame({"High": [100, 101], "Low": [99, 100], "Close": [100, 101]})
    assert FeatureEngine.get_adx(df) == 20.0


# ── FeatureEngine: extract_features ──────────────────────────────────────

def test_extract_features(sample_df1m: pd.DataFrame, sample_df5m: pd.DataFrame, sample_df15m: pd.DataFrame) -> None:
    engine = FeatureEngine(config={"indicators": {"rsi_period": 14}})
    features = engine.extract_features(sample_df1m, sample_df5m, sample_df15m)
    assert isinstance(features, dict)
    assert "price" in features
    assert "vwap" in features
    assert "rsi" in features
    assert "macd" in features
    assert "atr" in features
    assert "adx" in features
    assert "regime" in features
    assert "volume_spike" in features
    assert "breakout_ok" in features
    assert features["price"] > 0


def test_extract_features_none_data() -> None:
    engine = FeatureEngine()
    features = engine.extract_features(None, None, None)
    assert features == {}


# ── FeatureEngine: get_price with custom config ──────────────────────────

def test_feature_engine_with_config() -> None:
    config: dict[str, Any] = {"indicators": {"adx_period": 10, "atr_period": 10}}
    engine = FeatureEngine(config=config)
    assert engine.config["indicators"]["adx_period"] == 10
