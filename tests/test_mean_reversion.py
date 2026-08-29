"""Tests for core/strategy/mean_reversion.py.

Verifies mean reversion detection on synthetic OHLCV data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from core.strategy.mean_reversion import MeanReversionResult, detect_mean_reversion


def _mean_reverting_df(n: int = 80) -> pd.DataFrame:
    """Build a synthetic mean-reverting OHLCV frame with capitalized columns."""
    base = np.full(n, 120.0)
    waves = np.sin(np.arange(n) / 3.0) * 4.0
    close = base + waves
    high = close + 1.5
    low = close - 1.5
    open_ = close - 0.5
    volume = np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}
    )


def test_detect_mean_reversion_returns_result():
    """detect_mean_reversion must return a MeanReversionResult without raising."""
    result = detect_mean_reversion(_mean_reverting_df())
    assert isinstance(result, MeanReversionResult)


def test_detect_mean_reversion_short_frame_no_crash():
    """A short frame must not raise."""
    result = detect_mean_reversion(_mean_reverting_df(n=15))
    assert isinstance(result, MeanReversionResult)


def test_result_exposes_signal_attribute():
    """The result should expose a signal/action field."""
    result = detect_mean_reversion(_mean_reverting_df())
    assert hasattr(result, "signal") or hasattr(result, "action")
