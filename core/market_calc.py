"""Shared ADX/regime, slippage, target, and latency helpers (index + stock)."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

__all__ = [
    "calc_adx",
    "calc_dynamic_slippage",
    "calc_dynamic_targets",
    "detect_regime",
    "detect_regime_and_adx",
    "latency_within_budget",
]

def calc_adx(df: Any, period: int = 14) -> float:
    try:
        if df is None or len(df) < period * 2:
            return 0.0
        high = df["High"]
        low = df["Low"]
        close = df["Close"]
        plus_dm = high.diff()
        minus_dm = low.diff().mul(-1)
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean().replace(0, float("nan")).ffill().fillna(1.0)
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1)) * 100
        adx = dx.rolling(window=period).mean()
        val = float(adx.iloc[-1])
        if pd.isna(val) or val < 0:
            return 0.0
        return round(val, 2)
    except (KeyError, ValueError, TypeError, IndexError):
        return 0.0


def detect_regime(
    df5: Any,
    df15: Any,
    *,
    vix: float,
    vix_block_threshold: float,
    adx_trend_threshold: float,
    adx_chop_threshold: float,
) -> str:
    # Compute ADX before VIX check so regime label is always based on actual ADX
    adx5 = calc_adx(df5)
    adx15 = calc_adx(df15) if df15 is not None and len(df15) >= 28 else adx5
    avg_adx = (adx5 + adx15) / 2
    if vix >= vix_block_threshold:
        return "EVENT"
    if avg_adx >= adx_trend_threshold:
        return "TRENDING"
    if avg_adx <= adx_chop_threshold:
        return "CHOPPY"
    return "NEUTRAL"


def detect_regime_and_adx(
    df5: Any,
    df15: Any,
    *,
    vix: float = 18.0,
    vix_block_threshold: float = 27.0,
    adx_trend_threshold: float = 16.0,
    adx_chop_threshold: float = 12.0,
) -> tuple[str, float]:
    # Always compute ADX so callers (dashboard, signal log) show the real value
    # even when regime is EVENT. ADX=0 on EVENT would hide trend-strength info.
    adx5 = calc_adx(df5)
    adx15 = calc_adx(df15) if df15 is not None and len(df15) >= 28 else adx5
    avg_adx = round((adx5 + adx15) / 2, 2)
    if vix >= vix_block_threshold:
        return ("EVENT", avg_adx)
    if avg_adx >= adx_trend_threshold:
        return ("TRENDING", avg_adx)
    if avg_adx <= adx_chop_threshold:
        return ("CHOPPY", avg_adx)
    return ("NEUTRAL", avg_adx)


def calc_dynamic_slippage(
    vix: float,
    vol_ratio: float,
    *,
    base_slippage: float,
    vix_halt_threshold: float,
    slippage_vix_factor: float,
    slippage_low_vol_extra: float,
    max_slippage: float = 0.03,
) -> float:
    base = base_slippage
    if vix > vix_halt_threshold:
        base += slippage_vix_factor * (vix - vix_halt_threshold)
    if vol_ratio < 0.5:
        base += slippage_low_vol_extra
    return min(base, max_slippage)


def calc_dynamic_targets(
    entry: float,
    atr: float,
    direction: str,
    vix: float,
    *,
    vix_halt_threshold: float,
    dynamic_sl_atr_mult: float,
    dynamic_target_atr_mult: float,
    sl_pct: float,
    target_pct: float,
) -> tuple[float, float]:
    _ = direction
    vix_mult = 1.0 + (max(0, vix - vix_halt_threshold) * 0.02) if vix > vix_halt_threshold else 1.0
    sl_dist = atr * dynamic_sl_atr_mult * vix_mult
    tgt_dist = atr * dynamic_target_atr_mult * vix_mult
    sl_pct_eff = max(sl_pct, (entry - sl_dist) / entry if entry > 0 else sl_pct)
    tgt_pct_eff = min(target_pct * 1.5, (entry + tgt_dist) / entry if entry > 0 else target_pct)
    sl = round(entry * sl_pct_eff, 2)
    target = round(entry * tgt_pct_eff, 2)
    return sl, target


def latency_within_budget(start_ts_monotonic: float, budget_ms: float) -> bool:
    elapsed_ms = (time.monotonic() - start_ts_monotonic) * 1000
    return elapsed_ms <= budget_ms
