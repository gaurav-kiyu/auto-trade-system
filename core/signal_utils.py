"""
Signal utility functions extracted from core.legacy.signal_engine.

These pure, stateless helper functions are used by adaptive_signal.py,
pure_index_signal.py, and external scripts. They have no dependencies
on the deprecated legacy module tree.

Indicators: RSI(14), MACD(12,26,9), EMA(20/50/200), VWAP, Volume Ratio,
            ATR-based Stop Loss, Fibonacci TP levels, OI-based Support/Resistance

.. versionadded:: 2.54.0
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# BREAKOUT STRENGTH CHECK
# ═══════════════════════════════════════════════════════════════


def breakout_strength_ok(df: pd.DataFrame) -> bool:
    """Check if the latest bar shows a meaningful breakout (price move + volume).

    Returns True when:
    - At least 3 bars exist
    - The last close moved > 0.4% from the previous close
    - Volume on the last bar is >= 1.3x the average of the prior N bars

    Args:
        df: OHLCV DataFrame with 'Close' and 'Volume' columns.

    Returns:
        True if breakout conditions are met.
    """
    try:
        if len(df) < 3:
            return False
        p = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2])
        if prev <= 0:
            return False
        price_move = abs(p - prev) / prev
        n = min(10, len(df) - 1)
        vol_cur = float(df["Volume"].iloc[-1])
        vol_avg = float(df["Volume"].iloc[-n - 1:-1].mean())
        vol_ok = vol_avg > 0 and vol_cur >= vol_avg * 1.3
        return price_move > 0.004 and vol_ok
    except (KeyError, TypeError, ValueError, IndexError) as e:
        log.debug("breakout_strength_ok fallback: %s", e)
        return False


# ═══════════════════════════════════════════════════════════════
# SUPPORT / RESISTANCE / FIBONACCI TARGETS
# ═══════════════════════════════════════════════════════════════


def calc_support_resistance_pivot(df: pd.DataFrame) -> dict[str, float]:
    """Calculate pivot-based support and resistance levels.

    Uses standard pivot point formula from high/low/close of the input DataFrame.

    Args:
        df: OHLCV DataFrame with 'High', 'Low', 'Close' columns.

    Returns:
        Dict with keys: pivot, support_1, support_2, resistance_1, resistance_2.
    """
    try:
        h = float(df["High"].max())
        low_price = float(df["Low"].min())
        c = float(df["Close"].iloc[-1])
        pivot = round((h + low_price + c) / 3, 2)
        return {
            "pivot": pivot,
            "support_1": round(2 * pivot - h, 2),
            "support_2": round(pivot - (h - low_price), 2),
            "resistance_1": round(2 * pivot - low_price, 2),
            "resistance_2": round(pivot + (h - low_price), 2),
        }
    except (KeyError, TypeError, ValueError, IndexError):
        return {"pivot": 0, "support_1": 0, "support_2": 0, "resistance_1": 0, "resistance_2": 0}


def calc_fibonacci_targets(
    entry: float,
    atr: float,
    direction: str,
    fib_r1: float = 0.618,
    fib_r2: float = 1.0,
    fib_r3: float = 1.618,
    vix: float = 0.0,
) -> dict[str, float]:
    """Calculate Fibonacci extension take-profit targets.

    The ATR-based targets are scaled by VIX: lower VIX → wider targets,
    higher VIX → tighter targets (accounting for premium expansion).

    Args:
        entry: Entry price.
        atr: Average True Range value.
        direction: "CALL", "UP", "BUY" (bullish) or "PUT", "DOWN", "SELL" (bearish).
        fib_r1: First Fibonacci ratio (default 0.618).
        fib_r2: Second Fibonacci ratio (default 1.0).
        fib_r3: Third Fibonacci ratio (default 1.618).
        vix: India VIX value for volatility scaling (0 = no scaling).

    Returns:
        Dict with keys: tp1, tp2, tp3.
    """
    if atr <= 0:
        atr = entry * 0.01
    scale_factor = 1.0
    if vix > 18:
        scale_factor = 0.8
    elif 0 < vix < 12:
        scale_factor = 1.2
    adj_r1 = fib_r1 * scale_factor
    adj_r2 = fib_r2 * scale_factor
    adj_r3 = fib_r3 * scale_factor
    if direction in ("CALL", "UP", "BUY"):
        return {
            "tp1": round(entry + adj_r1 * atr, 2),
            "tp2": round(entry + adj_r2 * atr, 2),
            "tp3": round(entry + adj_r3 * atr, 2),
        }
    else:
        return {
            "tp1": round(entry - adj_r1 * atr, 2),
            "tp2": round(entry - adj_r2 * atr, 2),
            "tp3": round(entry - adj_r3 * atr, 2),
        }


def calc_chandelier_exit(
    df: pd.DataFrame,
    period: int = 22,
    multiplier: float = 3.0,
    direction: str = "CALL",
) -> float:
    """Calculate Chandelier Exit trailing stop level.

    For CALL: highest high over period - (ATR × multiplier).
    For PUT: lowest low over period + (ATR × multiplier).

    Args:
        df: OHLCV DataFrame.
        period: Lookback period (default 22).
        multiplier: ATR multiplier (default 3.0).
        direction: "CALL" or "PUT".

    Returns:
        Chandelier exit price, or 0.0 if insufficient data.
    """
    if df is None or len(df) < period:
        return 0.0
    try:
        atr_series = pd.DataFrame()
        atr_series["tr0"] = abs(df["High"] - df["Low"])
        atr_series["tr1"] = abs(df["High"] - df["Close"].shift())
        atr_series["tr2"] = abs(df["Low"] - df["Close"].shift())
        tr = atr_series[["tr0", "tr1", "tr2"]].max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        atr_val: float = float(atr)
        if direction in ("CALL", "UP", "BUY"):
            highest_high: float = float(df["High"].rolling(period).max().iloc[-1])
            return round(highest_high - atr_val * multiplier, 2)
        else:
            lowest_low: float = float(df["Low"].rolling(period).min().iloc[-1])
            return round(lowest_low + atr_val * multiplier, 2)
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError):
        return 0.0


def calc_atr_stop_loss(
    entry: float,
    atr: float,
    direction: str,
    multiplier: float = 1.5,
) -> float:
    """Calculate ATR-based stop loss level.

    For CALL: entry - (ATR × multiplier).
    For PUT: entry + (ATR × multiplier).

    Args:
        entry: Entry price.
        atr: ATR value (auto-defaults to 1% of entry if <= 0).
        direction: "CALL", "UP", "BUY" or "PUT", "DOWN", "SELL".
        multiplier: ATR multiplier (default 1.5).

    Returns:
        Stop loss price, rounded to 2 decimal places.
    """
    if atr <= 0:
        atr = entry * 0.01
    if direction in ("CALL", "UP", "BUY"):
        return round(entry - multiplier * atr, 2)
    else:
        return round(entry + multiplier * atr, 2)


# ═══════════════════════════════════════════════════════════════
# SIGNAL STRENGTH CLASSIFICATION
# ═══════════════════════════════════════════════════════════════


def classify_strength(
    score: int,
    threshold: int = 60,
    strong_min: int = 85,
    moderate_min: int = 70,
) -> str:
    """Classify signal strength based on score thresholds.

    Args:
        score: Signal score (0-100).
        threshold: Minimum score for any signal.
        strong_min: Minimum score for STRONG classification.
        moderate_min: Minimum score for MODERATE classification.

    Returns:
        "STRONG", "MODERATE", "WEAK", or "NONE".
    """
    if score >= strong_min:
        return "STRONG"
    if score >= moderate_min:
        return "MODERATE"
    if score >= threshold:
        return "WEAK"
    return "NONE"


def classify_signal(direction: str, score: int, threshold: int = 60) -> str:
    """Classify trading action based on score and direction.

    Args:
        direction: "CALL", "UP" (bullish) or other (bearish).
        score: Signal score.
        threshold: Minimum score for a trade signal.

    Returns:
        "BUY" if score >= threshold and direction is bullish, "HOLD" otherwise.
    """
    if score < threshold:
        return "HOLD"
    return "BUY" if direction in ("CALL", "UP") else "SELL"


def score_to_stars(score: int, threshold: int = 60) -> str:
    """Convert score to star rating for UI display.

    Args:
        score: Signal score (0-100).
        threshold: Minimum score for a signal.

    Returns:
        String of star characters (1-5) or empty string.
    """
    if score >= 90:
        return "\u2b50\u2b50\u2b50\u2b50\u2b50"
    if score >= 80:
        return "\u2b50\u2b50\u2b50\u2b50"
    if score >= 70:
        return "\u2b50\u2b50\u2b50"
    if score >= threshold:
        return "\u2b50\u2b50"
    if score >= threshold - 10:
        return "\u2b50"
    return ""


def score_to_label(score: int, direction: str, threshold: int = 60) -> str:
    """Generate a human-readable label for a signal score.

    Args:
        score: Signal score (0-100).
        direction: "CALL" or "PUT".
        threshold: Minimum score for a signal.

    Returns:
        e.g. "Strong Buy CE", "Buy CE", "Weak Buy CE", "No Signal".
    """
    side = "Buy CE" if direction == "CALL" else "Buy PE"
    if score >= 85:
        return f"Strong {side}"
    if score >= 70:
        return f"{side}"
    if score >= threshold:
        return f"Weak {side}"
    return "No Signal"


# ═══════════════════════════════════════════════════════════════
# OHLCV VALIDATION
# ═══════════════════════════════════════════════════════════════


def validate_ohlcv(
    df: pd.DataFrame,
    interval: str = "1m",
    max_drop_ratio: float = 0.15,
) -> tuple[pd.DataFrame | None, int]:
    """Validate an OHLCV DataFrame for common data quality issues.

    Checks:
    - Required columns exist (Open, High, Low, Close, Volume)
    - High >= Low for all rows
    - Close is within [Low, High] range
    - Volume > 0 for at least one row
    - Drop ratio does not exceed max_drop_ratio

    Args:
        df: OHLCV DataFrame to validate.
        interval: Label for logging (default "1m").
        max_drop_ratio: Maximum allowed fraction of dropped rows (default 0.15).

    Returns:
        (cleaned_df or None, number_of_dropped_rows).
    """
    if df is None or df.empty:
        return None, 0
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns):
        return None, 0
    n = len(df)
    df = df[df["High"] >= df["Low"]]
    df = df[(df["Close"] >= df["Low"]) & (df["Close"] <= df["High"])]
    if (df["Volume"] > 0).any():
        df = df[df["Volume"] > 0]
    n_drop = n - len(df)
    if n > 0 and n_drop / n > max_drop_ratio:
        return None, n_drop
    return (df.dropna() if len(df) >= 3 else None), n_drop


# ═══════════════════════════════════════════════════════════════
# SIGNAL EXPLANATION / BREAKDOWN
# ═══════════════════════════════════════════════════════════════


def explain_signal(sig: dict[str, Any], asset_label: str = "Stock") -> str:
    """Generate a plain-English explanation of a signal.

    Args:
        sig: Signal dictionary with keys like trend_5m, price, vwap, etc.
        asset_label: Name for the asset type (default "Stock").

    Returns:
        Human-readable explanation string.
    """
    if not sig:
        return "No signal data"
    parts: list[str] = []
    t = sig.get("trend_5m", sig.get("trend", ""))
    word = (
        "going UP" if t in ("UP", "CALL")
        else ("going DOWN" if t in ("DOWN", "PUT") else "sideways")
    )
    parts.append(f"{asset_label} {word}")
    p, v = sig.get("price", 0), sig.get("vwap", 0)
    if t in ("UP", "CALL") and p > v:
        parts.append("above average price (VWAP)")
    elif t in ("DOWN", "PUT") and p < v:
        parts.append("below average price (VWAP)")
    vr = sig.get("vol_ratio", 0)
    if vr >= 2.0:
        parts.append(f"very high volume ({vr}x)")
    elif vr >= 1.2:
        parts.append(f"good volume ({vr}x)")
    sm = sig.get("smart_money", sig.get("smart", ""))
    if sm == "BULLISH":
        parts.append("big buyers active (OI bullish)")
    elif sm == "BEARISH":
        parts.append("big sellers active (OI bearish)")
    rsi = sig.get("rsi", 50)
    if 40 <= rsi <= 70:
        parts.append(f"RSI healthy ({rsi})")
    elif rsi > 70:
        parts.append(f"RSI high ({rsi}) - overbought")
    elif rsi < 30:
        parts.append(f"RSI low ({rsi}) - oversold")
    macd = sig.get("macd", {})
    if isinstance(macd, dict) and macd.get("histogram", 0) != 0:
        h = macd["histogram"]
        parts.append(f"MACD {'bullish' if h > 0 else 'bearish'} ({h:+.2f})")
    vix = sig.get("vix", 0)
    if 0 < vix <= 15:
        parts.append(f"low fear (VIX {vix})")
    elif 15 < vix <= 22:
        parts.append(f"moderate fear (VIX {vix})")
    elif vix > 22:
        parts.append(f"high fear (VIX {vix}) - risky")
    return ", ".join(parts) if parts else "Multiple signals aligned"


def format_pnl(val: Any) -> str:
    """Format a P&L value as a human-readable INR string."""
    from core.utils_numeric import safe_num

    v = safe_num(val, 0.0)
    r = "\u20b9"
    if v >= 0:
        return f"+{r}{round(v, 0):,.0f}"
    return f"-{r}{abs(round(v, 0)):,.0f}"


def format_change(chg: Any, pct: Any) -> str:
    """Format a price change and percentage as a display string."""
    from core.utils_numeric import safe_num

    c = safe_num(chg, 0.0)
    p = safe_num(pct, 0.0)
    arrow = "\u25b2" if c >= 0 else "\u25bc"
    return f"{arrow}{c:+.1f} ({p:+.1f}%)"


__all__ = [
    "breakout_strength_ok",
    "calc_atr_stop_loss",
    "calc_chandelier_exit",
    "calc_fibonacci_targets",
    "calc_support_resistance_pivot",
    "classify_signal",
    "classify_strength",
    "explain_signal",
    "format_change",
    "format_pnl",
    "score_to_label",
    "score_to_stars",
    "validate_ohlcv",
]
