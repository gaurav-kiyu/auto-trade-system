"""MA Crossover Strategy — Moving Average crossover detection for trend-following entries.

Detects golden crosses (fast MA crosses above slow MA → CALL) and death crosses
(fast MA crosses below slow MA → PUT) across multiple timeframe configurations.

Integrates with the signal pipeline via the adaptive_signal_score_adjusters layer.

Key Concepts:
  - Works BEST in TRENDING regimes
  - Works WORST in CHOPPY/range-bound regimes
  - Supports EMA, SMA, and WMA variants
  - Configurable fast/slow periods for different trading styles
  - Includes volume confirmation and pullback-to-MA entry triggers
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class MACrossoverResult:
    """Result of a moving average crossover evaluation."""

    signal: bool            # True if a crossover setup is detected
    direction: str          # "CALL" (golden cross) or "PUT" (death cross)
    score: int              # 0-100 confidence score
    reason: str             # Human-readable explanation
    entry_price: float      # Suggested entry price
    stop_loss: float        # Suggested stop-loss price
    target: float           # Suggested target price
    confidence: float       # 0.0-1.0 confidence multiplier
    crossover_type: str     # "golden", "death", or "pullback"
    metadata: dict[str, Any] = field(default_factory=dict)


def detect_ma_crossover(
    df1: pd.DataFrame,
    *,
    fast_period: int = 9,
    slow_period: int = 21,
    ma_type: str = "ema",          # "ema", "sma", "wma"
    crossover_lookback: int = 5,   # bars to check for crossover
    pullback_threshold: float = 0.3,  # pct of MA distance for pullback entry
    adx_min: float = 20.0,         # minimum ADX for trend strength
    min_volume_ratio: float = 0.8,
    min_score: int = 30,
) -> MACrossoverResult:
    """Evaluate market for moving average crossover setups.

    Analyzes price action for:
      1. Recent golden cross (fast MA crossing above slow MA) → CALL
      2. Recent death cross (fast MA crossing below slow MA) → PUT
      3. Pullback to MA in trending market → re-entry

    Args:
        df1: 1-minute OHLCV DataFrame with at least `slow_period + crossover_lookback + 5` bars
        fast_period: Fast MA period (default 9)
        slow_period: Slow MA period (default 21)
        ma_type: Type of moving average - "ema", "sma", or "wma"
        crossover_lookback: Number of bars to look back for crossover detection
        pullback_threshold: Distance from MA as fraction of ATR for pullback entry
        adx_min: Minimum ADX value for valid trend
        min_volume_ratio: Minimum volume ratio for signal confirmation
        min_score: Minimum score to generate a signal

    Returns:
        MACrossoverResult with signal status and trade parameters
    """
    min_bars = max(slow_period + crossover_lookback + 10, 50)
    if df1 is None or len(df1) < min_bars:
        return MACrossoverResult(
            signal=False, direction="NONE", score=0,
            reason=f"Insufficient data (need {min_bars}, got {len(df1) if df1 is not None else 0})",
            entry_price=0.0, stop_loss=0.0, target=0.0,
            confidence=0.0, crossover_type="none",
        )

    close = df1["Close"].values.astype(float)
    high = df1["High"].values.astype(float)
    low = df1["Low"].values.astype(float)
    volume = df1["Volume"].values.astype(float) if "Volume" in df1.columns else None
    price = float(close[-1])

    # ── Compute moving averages ─────────────────────────────────────────
    fast_ma = _compute_ma(close, fast_period, ma_type)
    slow_ma = _compute_ma(close, slow_period, ma_type)

    # ── Trend strength via ADX ──────────────────────────────────────────
    adx = _compute_adx(high, low, close, 14)
    adx_val = float(adx[-1]) if len(adx) > 0 else 0.0

    # ── Volume ratio ────────────────────────────────────────────────────
    vol_ratio = 1.0
    if volume is not None and len(volume) > 20:
        avg_vol = float(np.mean(volume[-21:-1]))
        current_vol = float(volume[-1])
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0

    # ── ATR for stop-loss sizing ────────────────────────────────────────
    atr = _compute_atr(high, low, close, 14)
    atr_val = float(atr[-1]) if len(atr) > 0 else price * 0.005

    # ── Crossover detection ─────────────────────────────────────────────
    # Check if fast MA crossed above/below slow MA in the lookback window
    golden_cross = False
    death_cross = False
    cross_bar = -1

    for i in range(
        max(slow_period, fast_period) + 1,
        len(fast_ma),
    ):
        prev_fast = float(fast_ma[i - 1])
        prev_slow = float(slow_ma[i - 1])
        curr_fast = float(fast_ma[i])
        curr_slow = float(slow_ma[i])

        if prev_fast <= prev_slow and curr_fast > curr_slow:
            golden_cross = True
            cross_bar = i
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            death_cross = True
            cross_bar = i

    # Check how recent the crossover is
    bars_since_cross = len(close) - 1 - cross_bar if cross_bar > 0 else 999

    # ── Current MA alignment ────────────────────────────────────────────
    curr_fast = float(fast_ma[-1])
    curr_slow = float(slow_ma[-1])
    ma_diff_pct = abs(curr_fast - curr_slow) / max(curr_slow, 1) * 100
    above_fast = price > curr_fast
    above_slow = price > curr_slow

    # ── Score calculation ───────────────────────────────────────────────
    call_score = 0
    put_score = 0
    call_reasons: list[str] = []
    put_reasons: list[str] = []
    crossover_type = "none"

    # Primary signal: recent crossover with trend confirmation
    if golden_cross and bars_since_cross <= crossover_lookback * 2:
        call_score += 35
        crossover_type = "golden"
        call_reasons.append(f"Golden cross {bars_since_cross}b ago (FAST={fast_period} SLOW={slow_period})")

        # Price above both MAs confirms trend
        if above_fast and above_slow:
            call_score += 15
            call_reasons.append("Price above both MAs")

        # MA spread widening → strong trend
        if ma_diff_pct > 1.0:
            call_score += 10
            call_reasons.append(f"MA spread widening ({ma_diff_pct:.2f}%)")

    elif death_cross and bars_since_cross <= crossover_lookback * 2:
        put_score += 35
        crossover_type = "death"
        put_reasons.append(f"Death cross {bars_since_cross}b ago (FAST={fast_period} SLOW={slow_period})")

        if not above_fast and not above_slow:
            put_score += 15
            put_reasons.append("Price below both MAs")

        if ma_diff_pct > 1.0:
            put_score += 10
            put_reasons.append(f"MA spread widening ({ma_diff_pct:.2f}%)")

    # Secondary signal: pullback to MA in trending market
    if adx_val >= adx_min:
        if above_slow and price < curr_fast and not golden_cross:
            # Pullback to fast MA in uptrend
            pullback_pct = (curr_fast - price) / max(atr_val, 1)
            if pullback_pct < pullback_threshold:
                call_score += 20
                crossover_type = "pullback"
                call_reasons.append(f"Pullback to {fast_period}-{ma_type.upper()} in uptrend")

        elif not above_slow and price > curr_fast and not death_cross:
            # Pullback to fast MA in downtrend
            pullback_pct = (price - curr_fast) / max(atr_val, 1)
            if pullback_pct < pullback_threshold:
                put_score += 20
                crossover_type = "pullback"
                put_reasons.append(f"Pullback to {fast_period}-{ma_type.upper()} in downtrend")

    # ADX bonus: strong trend adds confidence
    if adx_val >= adx_min:
        call_score += 5 if call_score > 0 else 0
        put_score += 5 if put_score > 0 else 0

    # Volume confirmation
    if vol_ratio < min_volume_ratio:
        if call_score > 0:
            call_score = max(0, call_score - 8)
        if put_score > 0:
            put_score = max(0, put_score - 8)

    # ── Determine direction and finalize ────────────────────────────────
    score = 0
    direction = "NONE"
    entry_price = price
    stop_loss = price
    target = price
    confidence = 0.0
    reason = "No MA crossover setup"
    metadata: dict[str, Any] = {
        f"ma_{fast_period}": round(curr_fast, 2),
        f"ma_{slow_period}": round(curr_slow, 2),
        "ma_diff_pct": round(ma_diff_pct, 3),
        "above_fast_ma": above_fast,
        "above_slow_ma": above_slow,
        "adx": round(adx_val, 1),
        "vol_ratio": round(vol_ratio, 2),
        "atr": round(atr_val, 2),
        "crossover_type": crossover_type,
        "bars_since_cross": bars_since_cross if cross_bar > 0 else None,
        "ma_type": ma_type,
    }

    if call_score >= min_score and call_score > put_score:
        score = min(100, call_score)
        direction = "CALL"
        stop_loss = price - atr_val * 2.0
        target = price + atr_val * 3.0
        confidence = min(1.0, score / 80.0)
        reason = " | ".join(call_reasons) if call_reasons else "MA Crossover CALL setup"
        metadata["setup_type"] = "golden_cross" if crossover_type == "golden" else "pullback_call"

    elif put_score >= min_score and put_score > call_score:
        score = min(100, put_score)
        direction = "PUT"
        stop_loss = price + atr_val * 2.0
        target = price - atr_val * 3.0
        confidence = min(1.0, score / 80.0)
        reason = " | ".join(put_reasons) if put_reasons else "MA Crossover PUT setup"
        metadata["setup_type"] = "death_cross" if crossover_type == "death" else "pullback_put"

    return MACrossoverResult(
        signal=score >= min_score,
        direction=direction,
        score=score,
        reason=reason,
        entry_price=round(entry_price, 2),
        stop_loss=round(stop_loss, 2),
        target=round(target, 2),
        confidence=confidence,
        crossover_type=crossover_type,
        metadata=metadata,
    )


# ── Technical indicator helpers ──────────────────────────────────────────


def _compute_ma(close: np.ndarray, period: int, ma_type: str = "ema") -> np.ndarray:
    """Compute moving average of specified type."""
    if len(close) < period:
        return np.full(len(close), float(np.mean(close)))
    if ma_type == "sma":
        result = np.full(len(close), 0.0)
        for i in range(period - 1, len(close)):
            result[i] = float(np.mean(close[i - period + 1:i + 1]))
        return result
    elif ma_type == "wma":
        result = np.full(len(close), 0.0)
        weights = np.arange(1, period + 1)
        for i in range(period - 1, len(close)):
            result[i] = float(np.sum(close[i - period + 1:i + 1] * weights) / np.sum(weights))
        return result
    else:
        # EMA using pandas ewm (consistent with mean_reversion.py)
        return pd.Series(close).ewm(span=period, adjust=False).mean().values


def _compute_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Compute Average Directional Index."""
    n = len(close)
    if n < period + 2:
        return np.full(n, 0.0)

    # True Range
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

    # Directional Movement
    up_move = np.zeros(n)
    down_move = np.zeros(n)
    for i in range(1, n):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        up_move[i] = max(up, 0) if up > down else 0
        down_move[i] = max(down, 0) if down > up else 0

    # Wilder smoothing in RAW units — DI percentages are derived only when
    # computing DX. This prevents the DI values from compounding with *100
    # on every bar (which previously overflowed float64 and emitted
    # RuntimeWarning: overflow / invalid value during live signal scans).
    atr = np.full(n, np.nan)
    di_plus = np.full(n, np.nan)
    di_minus = np.full(n, np.nan)
    atr[period] = float(np.mean(tr[1:period + 1]))
    di_plus[period] = float(np.mean(up_move[1:period + 1]))
    di_minus[period] = float(np.mean(down_move[1:period + 1]))

    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
        di_plus[i] = (di_plus[i - 1] * (period - 1) + up_move[i]) / period
        di_minus[i] = (di_minus[i - 1] * (period - 1) + down_move[i]) / period

    # DX and ADX
    dx = np.zeros(n)
    for i in range(period, n):
        if atr[i] > 0 and np.isfinite(atr[i]):
            p_ratio = di_plus[i] / atr[i] * 100.0
            m_ratio = di_minus[i] / atr[i] * 100.0
            di_sum = p_ratio + m_ratio
            if di_sum > 0:
                dx[i] = abs(p_ratio - m_ratio) / di_sum * 100.0

    adx = np.full(n, 0.0)
    mid = period * 2 - 1
    if mid < n:
        adx[mid] = float(np.mean(dx[period:mid + 1]))
        for i in range(mid + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    return adx


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


__all__ = [
    "MACrossoverResult",
    "detect_ma_crossover",
]
