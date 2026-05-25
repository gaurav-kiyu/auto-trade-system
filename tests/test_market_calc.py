"""Tests for core.market_calc."""

from __future__ import annotations

import time

import pandas as pd
from core.market_calc import (
    calc_adx,
    calc_dynamic_slippage,
    calc_dynamic_targets,
    detect_regime,
    detect_regime_and_adx,
    latency_within_budget,
)


def _ohlcv_rows(n: int) -> pd.DataFrame:
    r = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "High": [110.0 + i * 0.1 for i in range(n)],
            "Low": [100.0 + i * 0.1 for i in range(n)],
            "Close": [105.0 + i * 0.1 for i in range(n)],
        },
        index=r,
    )


def test_calc_adx_returns_float():
    df = _ohlcv_rows(40)
    v = calc_adx(df, period=14)
    assert isinstance(v, float)
    assert v >= 0.0


def test_detect_regime_event_on_vix():
    df = _ohlcv_rows(40)
    assert detect_regime(df, df, vix=99.0, vix_block_threshold=30.0, adx_trend_threshold=25.0, adx_chop_threshold=20.0) == "EVENT"


def test_detect_regime_and_adx_tuple():
    df = _ohlcv_rows(40)
    reg, adx = detect_regime_and_adx(
        df, df, vix=0.0, vix_block_threshold=99.0, adx_trend_threshold=25.0, adx_chop_threshold=20.0
    )
    assert reg in ("TRENDING", "CHOPPY", "NEUTRAL", "EVENT")
    assert isinstance(adx, float)


def test_calc_dynamic_slippage_cap():
    s = calc_dynamic_slippage(
        50.0,
        0.1,
        base_slippage=0.01,
        vix_halt_threshold=10.0,
        slippage_vix_factor=1.0,
        slippage_low_vol_extra=0.5,
        max_slippage=0.03,
    )
    assert s == 0.03


def test_calc_dynamic_targets():
    sl, tgt = calc_dynamic_targets(
        100.0,
        2.0,
        "BUY",
        0.0,
        vix_halt_threshold=30.0,
        dynamic_sl_atr_mult=2.0,
        dynamic_target_atr_mult=3.0,
        sl_pct=0.9,
        target_pct=1.1,
    )
    assert sl < 100.0
    assert tgt > 100.0


def test_latency_within_budget():
    t0 = time.monotonic()
    assert latency_within_budget(t0, 60_000) is True
