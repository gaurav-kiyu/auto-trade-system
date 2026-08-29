"""Tests for core/strategy/ma_crossover.py.

Verifies MA crossover detection on synthetic OHLCV data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from core.strategy.ma_crossover import MACrossoverResult, detect_ma_crossover


def _trending_df(n: int = 80) -> pd.DataFrame:
    """Build a synthetic trending OHLCV frame with capitalized columns."""
    close = np.linspace(100.0, 130.0, n) + np.sin(np.arange(n)) * 0.5
    high = close + 1.5
    low = close - 1.5
    open_ = close - 0.5
    volume = np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}
    )


def test_detect_ma_crossover_returns_result():
    """detect_ma_crossover must return a MACrossoverResult without raising."""
    result = detect_ma_crossover(_trending_df())
    assert isinstance(result, MACrossoverResult)


def test_detect_ma_crossover_short_frame_no_crash():
    """A short frame must not raise."""
    result = detect_ma_crossover(_trending_df(n=15))
    assert isinstance(result, MACrossoverResult)


def test_result_exposes_signal_attribute():
    """The result should expose a signal/action field."""
    result = detect_ma_crossover(_trending_df())
    assert hasattr(result, "signal") or hasattr(result, "action")
