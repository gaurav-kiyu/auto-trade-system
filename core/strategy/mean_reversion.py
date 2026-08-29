"""Enhanced Mean Reversion Strategy for range-bound and overextended markets.

Detects price pullbacks to key moving averages, Bollinger Band extremes,
and RSI oversold/overbought conditions for mean-reversion trade entries.

Integrates with the existing signal pipeline via the strategy plugin framework
and can be used standalone for backtesting.

Key Concepts:
  - Mean reversion works BEST in CHOPPY/NEUTRAL regimes
  - Works WORST in strong TRENDING regimes
  - Uses Bollinger Bands, RSI, and VWAP distance for signal generation
  - Includes volatility filter to avoid trading during low-volatility periods
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class MeanReversionResult:
    """Result of a mean reversion evaluation."""

    signal: bool            # True if a mean-reversion setup is detected
    direction: str          # "CALL" for bounce, "PUT" for reject
    score: int              # 0-100 confidence score
    reason: str             # Human-readable explanation
    entry_price: float      # Suggested entry price
    stop_loss: float        # Suggested stop-loss price
    target: float           # Suggested target price
    confidence: float       # 0.0-1.0 confidence multiplier
    metadata: dict[str, Any] = field(default_factory=dict)


def detect_mean_reversion(
    df1: pd.DataFrame,
    *,
    rsi_period: int = 14,
    bb_period: int = 20,
    bb_std: float = 2.0,
    oversold_rsi: float = 35.0,
    overbought_rsi: float = 65.0,
    oversold_extreme_rsi: float = 25.0,
    overbought_extreme_rsi: float = 75.0,
    min_vol_ratio: float = 0.8,
    ema_fast: int = 9,
    ema_slow: int = 21,
    min_score: int = 30,
) -> MeanReversionResult:
    """Evaluate market for mean-reversion setups.

    Analyzes price action for pullback-to-mean or extreme-extension setups
    that indicate a high-probability mean-reversion trade.

    Args:
        df1: 1-minute OHLCV DataFrame
        rsi_period: RSI calculation period
        bb_period: Bollinger Band period
        bb_std: Bollinger Band standard deviation multiplier
        oversold_rsi: RSI threshold for oversold (CALL setup)
        overbought_rsi: RSI threshold for overbought (PUT setup)
        oversold_extreme_rsi: Extreme oversold threshold (higher confidence)
        overbought_extreme_rsi: Extreme overbought threshold (higher confidence)
        min_vol_ratio: Minimum volume ratio for valid signal
        ema_fast: Fast EMA period for trend context
        ema_slow: Slow EMA period for trend context
        min_score: Minimum score to generate a signal

    Returns:
        MeanReversionResult with signal status and trade parameters
    """
    if df1 is None or len(df1) < max(bb_period + 5, 30):
        return MeanReversionResult(
            signal=False, direction="NONE", score=0,
            reason="Insufficient data", entry_price=0.0,
            stop_loss=0.0, target=0.0, confidence=0.0,
        )

    close = df1["Close"].values.astype(float)
    high = df1["High"].values.astype(float)
    low = df1["Low"].values.astype(float)
    volume = df1["Volume"].values.astype(float) if "Volume" in df1.columns else None
    price = float(close[-1])

    # ── Compute indicators ─────────────────────────────────────────────

    # RSI
    rsi_values = _compute_rsi(close, rsi_period)
    rsi_val = float(rsi_values[-1]) if len(rsi_values) > 0 else 50.0

    # Bollinger Bands
    bb_upper, bb_middle, bb_lower = _compute_bollinger(close, bb_period, bb_std)

    # EMAs using pandas (consistent with existing codebase)
    close_series = pd.Series(close)
    ema_fast_val = float(close_series.ewm(span=ema_fast, adjust=False).mean().iloc[-1])
    ema_slow_val = float(close_series.ewm(span=ema_slow, adjust=False).mean().iloc[-1])

    # ATR for stop-loss sizing
    atr = _compute_atr(high, low, close, 14)
    atr_val = float(atr[-1]) if len(atr) > 0 else price * 0.005

    # Volume ratio
    vol_ratio = 1.0
    if volume is not None and len(volume) > 20:
        avg_vol = float(np.mean(volume[-21:-1]))
        current_vol = float(volume[-1])
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0

    # ── Trend context ──────────────────────────────────────────────────
    trend = "UP" if ema_fast_val > ema_slow_val else ("DOWN" if ema_fast_val < ema_slow_val else "FLAT")
    bb_range = bb_upper - bb_lower
    bb_position = (price - bb_lower) / bb_range if bb_range > 0 else 0.5

    # ── Score calculation ──────────────────────────────────────────────
    call_score = 0
    put_score = 0
    call_reasons: list[str] = []
    put_reasons: list[str] = []

    # REVERSAL: Check if RSI has meaningful range first
    rsi_range = float(np.max(rsi_values[-rsi_period:]) - np.min(rsi_values[-rsi_period:])) if len(rsi_values) >= rsi_period else 0
    if rsi_range < 10.0:
        # RSI is flat - no extreme to revert from
        pass
    else:
        # RSI extreme oversold → CALL bounce signal
        if rsi_val <= oversold_extreme_rsi:
            call_score += 35
            call_reasons.append(f"RSI extreme oversold ({rsi_val:.0f})")
        elif rsi_val <= oversold_rsi:
            call_score += 20
            call_reasons.append(f"RSI oversold ({rsi_val:.0f})")

        # RSI extreme overbought → PUT reject signal
        if rsi_val >= overbought_extreme_rsi:
            put_score += 35
            put_reasons.append(f"RSI extreme overbought ({rsi_val:.0f})")
        elif rsi_val >= overbought_rsi:
            put_score += 20
            put_reasons.append(f"RSI overbought ({rsi_val:.0f})")

    # BOLLINGER: Price below lower band → CALL bounce
    if price <= bb_lower:
        call_score += 25
        call_reasons.append("Price below lower Bollinger Band")
        penetration = (bb_lower - price) / bb_range * 100 if bb_range > 0 else 0
        if penetration > 10:
            call_score += 10
            call_reasons.append(f"Deep BB penetration ({penetration:.0f}%)")
    elif price >= bb_upper:
        put_score += 25
        put_reasons.append("Price above upper Bollinger Band")
        penetration = (price - bb_upper) / bb_range * 100 if bb_range > 0 else 0
        if penetration > 10:
            put_score += 10
            put_reasons.append(f"Deep BB penetration ({penetration:.0f}%)")

    # VWAP distance: price stretched from VWAP → mean reversion opportunity
    vwap = _compute_vwap(df1)
    if vwap > 0:
        vwap_dist = (price - vwap) / vwap * 100
        if vwap_dist < -0.5:
            call_score += min(15, int(abs(vwap_dist) * 5))
            call_reasons.append(f"Below VWAP ({vwap_dist:.2f}%)")
        elif vwap_dist > 0.5:
            put_score += min(15, int(vwap_dist * 5))
            put_reasons.append(f"Above VWAP ({vwap_dist:.2f}%)")

    # TREND CONTEXT: penalty for strong trend (mean reversion dangerous)
    if trend == "UP" and bb_position < 0.3:
        call_score += 10
        call_reasons.append("Uptrend, near lower band")
    if trend == "DOWN" and bb_position > 0.7:
        put_score += 10
        put_reasons.append("Downtrend, near upper band")

    # VOLUME: confirming volume in reversal direction
    if vol_ratio < min_vol_ratio:
        call_score = max(0, call_score - 10)
        put_score = max(0, put_score - 10)

    # BOLLINGER BAND SQUEEZE: narrow bands → impending expansion
    if bb_range / bb_middle < 0.02 if bb_middle > 0 else False:
        call_score = max(0, call_score - 5)
        put_score = max(0, put_score - 5)

    # ── Determine direction and final score ────────────────────────────
    score = 0
    direction = "NONE"
    entry_price = price
    stop_loss = price
    target = price
    confidence = 0.0
    reason = "No mean reversion setup"
    metadata: dict[str, Any] = {
        "rsi": round(rsi_val, 1),
        "rsi_range": round(rsi_range, 1),
        "bb_upper": round(bb_upper, 2),
        "bb_middle": round(bb_middle, 2),
        "bb_lower": round(bb_lower, 2),
        "bb_width": round(bb_range / bb_middle, 4) if bb_middle > 0 else 0,
        "bb_position": round(bb_position, 3),
        "trend": trend,
        "vol_ratio": round(vol_ratio, 2),
        "vwap": round(vwap, 2) if vwap > 0 else None,
        "atr": round(atr_val, 2),
        "ema_fast": round(ema_fast_val, 2),
        "ema_slow": round(ema_slow_val, 2),
    }

    if call_score >= min_score and call_score > put_score:
        score = min(100, call_score)
        direction = "CALL"
        stop_loss = price - atr_val * 1.5
        target = price + atr_val * 2.0
        confidence = min(1.0, score / 80.0)
        reason = " | ".join(call_reasons) if call_reasons else "Mean reversion CALL setup"
        metadata["setup_type"] = "oversold_bounce"

    elif put_score >= min_score and put_score > call_score:
        score = min(100, put_score)
        direction = "PUT"
        stop_loss = price + atr_val * 1.5
        target = price - atr_val * 2.0
        confidence = min(1.0, score / 80.0)
        reason = " | ".join(put_reasons) if put_reasons else "Mean reversion PUT setup"
        metadata["setup_type"] = "overbought_reject"

    return MeanReversionResult(
        signal=score >= min_score,
        direction=direction,
        score=score,
        reason=reason,
        entry_price=round(entry_price, 2),
        stop_loss=round(stop_loss, 2),
        target=round(target, 2),
        confidence=confidence,
        metadata=metadata,
    )


# ── Technical indicator helpers ──────────────────────────────────────────


def _compute_rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    """Compute Relative Strength Index."""
    if len(close) < period + 1:
        return np.array([50.0] * len(close))
    deltas = np.diff(close)
    # Check if all deltas are zero (flat price)
    if np.all(deltas == 0):
        return np.full(len(close), 50.0)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    if avg_loss == 0:
        result = np.full(len(close), 50.0)
        result[period:] = 100.0
        return result
    rs = avg_gain / avg_loss
    first_rsi = 100.0 - (100.0 / (1.0 + rs))
    result = np.full(len(close), 50.0)
    result[period] = first_rsi
    # Wilder's smoothing
    for i in range(period + 1, len(close)):
        delta = deltas[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(delta, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-delta, 0)) / period
        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - (100.0 / (1.0 + rs))
    return result


def _compute_bollinger(
    close: np.ndarray, period: int = 20, std_mult: float = 2.0,
) -> tuple[float, float, float]:
    """Compute Bollinger Bands (upper, middle, lower) for the latest bar."""
    if len(close) < period:
        mid = float(np.mean(close))
        std = float(np.std(close)) or mid * 0.01
        return mid + std_mult * std, mid, mid - std_mult * std
    window = close[-period:]
    mid = float(np.mean(window))
    std = float(np.std(window, ddof=1))
    return mid + std_mult * std, mid, mid - std_mult * std


def _compute_atr(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14,
) -> np.ndarray:
    """Compute Average True Range."""
    n = len(close)
    if n < 2:
        return np.full(n, 0.0)
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
    atr = np.full(n, float(np.mean(tr[1:min(period + 1, n)])))
    for i in range(min(period + 1, n), n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def _compute_vwap(df: pd.DataFrame) -> float:
    """Compute Volume-Weighted Average Price for the entire dataframe."""
    if "Volume" not in df.columns or "Close" not in df.columns:
        return 0.0
    try:
        vol = df["Volume"].values.astype(float)
        close = df["Close"].values.astype(float)
        if np.sum(vol) <= 0:
            return 0.0
        return float(np.sum(close * vol) / np.sum(vol))
    except (ValueError, TypeError, KeyError, IndexError):
        return 0.0


__all__ = [
    "MeanReversionResult",
    "detect_mean_reversion",
]
