"""
SHARED SIGNAL ENGINE v1.0
═════════════════════════
One signal calculation module used by BOTH the dashboard + Telegram engine.
No duplicated logic. All indicators computed from live OHLCV data.
Zero hardcoded prices or levels — everything is dynamically calculated.

Indicators: RSI(14), MACD(12,26,9), EMA(20/50/200), VWAP, Volume Ratio,
            ATR-based Stop Loss, Fibonacci TP levels, OI-based Support/Resistance

Signal output follows a strict schema consumed by dashboard and Telegram.
"""

import math, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import numpy as np

from core.defaults_loader import load_defaults_file
from core.feature_engine import FeatureEngine
from core.scoring_engine import ScoringEngine
from core.decision_engine import DecisionEngine
from core.utils_numeric import safe_num as _safe_num
from core.time_provider import time_provider

log = logging.getLogger("signal_engine")
IST = timezone(timedelta(hours=5, minutes=30))

_REPO_ROOT = Path(__file__).resolve().parent


def _bundled_index_defaults() -> dict[str, Any]:
    """Fresh dict from disk each call (small file; avoids mutable module-level cache)."""
    return dict(load_defaults_file(_REPO_ROOT, "index_config.defaults.json"))


def _bundled_stock_defaults() -> dict[str, Any]:
    return dict(load_defaults_file(_REPO_ROOT, "stock_config.defaults.json"))


def _learning_score_adj_limit(cfg: Optional[dict], asset_type: str = "index") -> int:
    raw = None
    if isinstance(cfg, dict) and "LEARNING_SCORE_ADJ_CLAMP" in cfg:
        raw = cfg.get("LEARNING_SCORE_ADJ_CLAMP")
    if raw is None:
        bundle = _bundled_stock_defaults() if str(asset_type).lower() == "stock" else _bundled_index_defaults()
        raw = bundle.get("LEARNING_SCORE_ADJ_CLAMP", 20)
    try:
        lim = int(raw)
    except (TypeError, ValueError):
        lim = 20
    return max(1, lim)


# ═══════════════════════════════════════════════════════════════
# CORE INDICATOR FUNCTIONS  — Pure, no side effects
# ═══════════════════════════════════════════════════════════════

get_price = FeatureEngine.get_price
get_vwap = FeatureEngine.get_vwap
get_ema = FeatureEngine.get_ema
ema_trend = FeatureEngine.ema_trend
get_rsi = FeatureEngine.get_rsi
get_macd = FeatureEngine.get_macd
get_atr = FeatureEngine.get_atr
get_vol_ratio = FeatureEngine.get_vol_ratio
price_delta = FeatureEngine.price_delta

def get_open(df: pd.DataFrame) -> float:
    try:
        val: float = float(df['Open'].iloc[-1])
        return val
    except Exception: return 0.0

def get_high(df: pd.DataFrame) -> float:
    try:
        val: float = float(df['High'].iloc[-1])
        return val
    except Exception: return 0.0

def get_low(df: pd.DataFrame) -> float:
    try:
        val: float = float(df['Low'].iloc[-1])
        return val
    except Exception: return 0.0

def get_ema_series(series: pd.Series, span: int) -> pd.Series:
    try: return series.ewm(span=span, adjust=False).mean()
    except Exception: return series


def breakout_strength_ok(df: pd.DataFrame) -> bool:
    try:
        if len(df) < 3:
            return False
        p = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2])
        if prev <= 0:
            return False
        price_move = abs(p - prev) / prev
        # Require meaningful price move (0.4%) AND volume confirmation (1.3x avg)
        # Prevents a random 0.25% tick from being counted as a breakout
        n = min(10, len(df) - 1)
        vol_cur = float(df["Volume"].iloc[-1])
        vol_avg = float(df["Volume"].iloc[-n - 1:-1].mean())
        vol_ok = vol_avg > 0 and vol_cur >= vol_avg * 1.3
        return price_move > 0.004 and vol_ok
    except Exception as e:
        log.debug(f"breakout_strength_ok fallback: {e}", exc_info=False)
        return False

# ═══════════════════════════════════════════════════════════════
# SUPPORT / RESISTANCE / FIBONACCI TARGETS
# ═══════════════════════════════════════════════════════════════

def calc_support_resistance_pivot(df: pd.DataFrame) -> dict:
    """Pivot-point based support/resistance from recent price action."""
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
    except Exception:
        return {"pivot": 0, "support_1": 0, "support_2": 0, "resistance_1": 0, "resistance_2": 0}

def calc_fibonacci_targets(entry: float, atr: float, direction: str,
                           fib_r1: float = 0.618, fib_r2: float = 1.0,
                           fib_r3: float = 1.618, vix: float = 0.0) -> dict:
    """ATR-based Fibonacci extension targets with dynamic VIX scaling."""
    if atr <= 0:
        atr = entry * 0.01
        
    # Dynamic Volatility-Adjusted Profit Targets
    # If VIX is high (>18), shrink targets to secure profits quickly.
    # If VIX is low (<12), expand targets to let runners run.
    scale_factor = 1.0
    if vix > 18:
        scale_factor = 0.8
    elif vix < 12 and vix > 0:
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

def calc_chandelier_exit(df: pd.DataFrame, period: int = 22, multiplier: float = 3.0, direction: str = "CALL") -> float:
    """
    Active Trailing Position Manager: Chandelier Exit.
    Trails the stop loss based on the highest high or lowest low of the period.
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
    except Exception:
        return 0.0

def calc_atr_stop_loss(entry: float, atr: float, direction: str, multiplier: float = 1.5) -> float:
    """ATR-based dynamic stop loss."""
    if atr <= 0:
        atr = entry * 0.01
    if direction in ("CALL", "UP", "BUY"):
        return round(entry - multiplier * atr, 2)
    else:
        return round(entry + multiplier * atr, 2)

# ═══════════════════════════════════════════════════════════════
# SIGNAL STRENGTH CLASSIFICATION
# ═══════════════════════════════════════════════════════════════

def classify_strength(score: int, threshold: int = 60,
                       strong_min: int = 85, moderate_min: int = 70) -> str:
    if score >= strong_min:
        return "STRONG"
    if score >= moderate_min:
        return "MODERATE"
    if score >= threshold:
        return "WEAK"
    return "NONE"

def classify_signal(direction: str, score: int, threshold: int = 60) -> str:
    if score < threshold:
        return "HOLD"
    return "BUY" if direction in ("CALL", "UP") else "SELL"

def score_to_stars(score: int, threshold: int = 60) -> str:
    if score >= 90: return "\u2b50\u2b50\u2b50\u2b50\u2b50"
    if score >= 80: return "\u2b50\u2b50\u2b50\u2b50"
    if score >= 70: return "\u2b50\u2b50\u2b50"
    if score >= threshold: return "\u2b50\u2b50"
    if score >= threshold - 10: return "\u2b50"
    return ""

def score_to_label(score: int, direction: str, threshold: int = 60) -> str:
    side = "Buy CE" if direction == "CALL" else "Buy PE"
    if score >= 85: return f"Strong {side}"
    if score >= 70: return f"{side}"
    if score >= threshold: return f"Weak {side}"
    return "No Signal"

# ═══════════════════════════════════════════════════════════════
# UNIFIED SCORING ENGINE  — Parameterised for stock vs index
# ═══════════════════════════════════════════════════════════════

def compute_score_stock(
    t5: str, t15: str, price: float, vwap: float, atr: float,
    vol: float, d1: float, d5: float, pcr: float, smart: str,
    rsi: float, vol_min: float = 1.2,
    rsi_overbought: float = 70, rsi_oversold: float = 30,
    learning_adj: int = 0,
    atr_min: float = 0.5, pcr_bullish: float = 1.2, pcr_bearish: float = 0.8,
) -> int:
    """Stock scoring — includes RSI component. All thresholds parameterised."""
    s = 0
    s += 15 if t5 == t15 else 0
    s += 12 if (t5 == "UP" and price > vwap) or (t5 == "DOWN" and price < vwap) else 0
    s += 12 if (t5 == "UP" and d1 > 0) or (t5 == "DOWN" and d1 < 0) else 0
    s += 8  if (t5 == "UP" and d5 > 0) or (t5 == "DOWN" and d5 < 0) else 0
    s += 8  if vol >= vol_min else 0
    s += 5  if atr > atr_min else 0
    s += 8  if (t5 == "UP" and smart == "BULLISH") or (t5 == "DOWN" and smart == "BEARISH") else 0
    s += 5  if (t5 == "UP" and pcr > pcr_bullish) or (t5 == "DOWN" and pcr < pcr_bearish) else 0
    if t5 == "UP" and 40 <= rsi <= rsi_overbought: s += 8
    elif t5 == "DOWN" and rsi_oversold <= rsi <= 60: s += 8
    if t5 == "UP" and rsi > rsi_overbought: s -= 10
    if t5 == "DOWN" and rsi < rsi_oversold: s -= 10
    lim = _learning_score_adj_limit(None, "stock")
    adj = max(-lim, min(lim, int(learning_adj)))
    s += adj
    return max(0, min(100, s))

def compute_score_index(
    t5: str, t15: str, price: float, vwap: float, atr: float,
    vol: float, d1: float, d5: float, pcr: float, smart: str,
    vol_min: float = 1.2, learning_adj: int = 0,
    atr_min: float = 0.5, pcr_bullish: float = 1.2, pcr_bearish: float = 0.8,
) -> int:
    """Index scoring — all thresholds parameterised."""
    s = 0
    s += 20 if t5 == t15 else 0
    s += 15 if (t5 == "UP" and price > vwap) else 0
    s += 15 if (t5 == "DOWN" and price < vwap) else 0
    s += 15 if (t5 == "UP" and d1 > 0) else 0
    s += 15 if (t5 == "DOWN" and d1 < 0) else 0
    s += 10 if (t5 == "UP" and d5 > 0) else 0
    s += 10 if (t5 == "DOWN" and d5 < 0) else 0
    s += 10 if vol >= vol_min else 0
    s += 5  if atr > atr_min else 0
    s += 10 if (t5 == "UP" and smart == "BULLISH") or (t5 == "DOWN" and smart == "BEARISH") else 0
    s += 5  if (t5 == "UP" and pcr > pcr_bullish) or (t5 == "DOWN" and pcr < pcr_bearish) else 0
    lim = _learning_score_adj_limit(None, "index")
    adj = max(-lim, min(lim, int(learning_adj)))
    s += adj
    return max(0, min(100, s))

# ═══════════════════════════════════════════════════════════════
# REGIME DETECTION  — Lightweight, pure, config-driven
# ═══════════════════════════════════════════════════════════════

def detect_regime(features: dict, config: dict) -> str:
    """
    Classify current market regime from already-computed features.

    Returns one of: "TREND" | "RANGE" | "HIGH_VOL" | "NEUTRAL"

    Priority: HIGH_VOL > TREND > RANGE > NEUTRAL
    This ensures volatile markets are always gated first regardless of ADX.
    """
    adx     = float(features.get("adx") or 0)
    vix     = float(features.get("vix") or 0)

    adx_trend = float(config.get("REGIME_ADX_TREND", 20))
    adx_range = float(config.get("REGIME_ADX_RANGE", 15))
    vix_high  = float(config.get("REGIME_VIX_HIGH", 22))

    if vix >= vix_high:
        return "HIGH_VOL"    # elevated fear — widen spreads, avoid new entries

    if adx >= adx_trend:
        return "TREND"       # directional momentum confirmed

    if adx > 0 and adx <= adx_range:
        return "RANGE"       # low-ADX chop — mean-reversion conditions

    return "NEUTRAL"         # ambiguous; apply mild caution


# ═══════════════════════════════════════════════════════════════
# FULL SIGNAL BUILDER — Returns standardised schema
# ═══════════════════════════════════════════════════════════════

def build_full_signal(
    symbol: str,
    df1m: pd.DataFrame,
    df5m: pd.DataFrame,
    df15m: pd.DataFrame,
    asset_type: str = "stock",
    oi_data: Optional[dict] = None,
    iv: float = 0.0,
    vix: float = 0.0,
    sector: str = "",
    category: str = "",
    tags: list | None = None,
    threshold: int = 60,
    learning_adj: int = 0,
    config: dict | None = None,
) -> Optional[dict]:
    """
    Build a complete signal from raw OHLCV frames using V2 Engines.
    Returns the standardised signal schema with explicit reasons payload.
    """
    cfg = config or {}
    
    if df1m is None or len(df1m) < 30: return None
    if df5m is None or len(df5m) < 10: return None
    if df15m is None or len(df15m) < 2: return None

    # 1. Feature Extraction
    fe = FeatureEngine(config=cfg)
    features = fe.extract_features(df1m, df5m, df15m, oi_data)
    
    t5 = features.get("trend_5m", "FLAT")
    t15 = features.get("trend_15m", "FLAT")
    
    # Safe direction fallback
    direction = "CALL" if t5 == "UP" or (t5 == "FLAT" and features.get("vwap_position") == "above") else "PUT"
    
    # Map config for Scoring Engine (bridge flat config to V2 if needed)
    se_config = {
        "rsi_overbought": cfg.get("RSI_OVERBOUGHT", 70),
        "rsi_oversold": cfg.get("RSI_OVERSOLD", 30),
        "vol_ratio_min": cfg.get("VOL_RATIO_MIN", 1.2),
        "atr_min_threshold": cfg.get("ATR_MIN_THRESHOLD", 0.5),
        "pcr_bullish": cfg.get("PCR_BULLISH", 1.2),
        "pcr_bearish": cfg.get("PCR_BEARISH", 0.8),
        "macd_bonus": cfg.get("MACD_BONUS", 5)
    }

    # 2. Strategy Scoring
    se = ScoringEngine(se_config)
    score_data = se.score(features, direction)
    
    # Learning adjustment (positive or negative); clamp once after all score tweaks.
    _lim = _learning_score_adj_limit(cfg, str(asset_type or "index"))
    learning_clamped = max(-_lim, min(_lim, int(learning_adj)))
    final_score = score_data["total_score"] + learning_clamped

    # 3. Regime detection — inject vix into features so detect_regime has all it needs
    features["vix"] = vix
    _regime_enabled = bool(cfg.get("REGIME_ENABLED", True))
    regime = detect_regime(features, cfg) if _regime_enabled else "NEUTRAL"

    _pen = int(cfg.get("REGIME_SCORE_PENALTY", 5))
    _bon = int(cfg.get("REGIME_SCORE_BONUS",  5))

    # 4. Breakout bonus — skip in RANGE: a breakout in choppy conditions is noise
    if features.get("breakout_ok") and regime != "RANGE":
        final_score += 8

    # 5. Regime-based score adjustment
    if regime == "TREND":
        # Trending market: optimal for directional options buying — no change
        pass

    elif regime == "RANGE":
        # Mean-reversion conditions: RSI at extremes improves edge, otherwise penalise
        rsi = float(features.get("rsi") or 50)
        if (direction == "CALL" and rsi <= 35) or (direction == "PUT" and rsi >= 65):
            final_score += _bon   # extreme RSI = valid mean-reversion setup
        else:
            final_score -= _pen   # mid-RSI breakout in range = noise

    elif regime == "HIGH_VOL":
        # Elevated VIX: option premiums inflated, spreads wide — strong penalty
        final_score -= _pen * 2

    else:  # NEUTRAL
        # Ambiguous regime: apply mild caution to avoid marginal trades
        final_score -= _pen

    score_data["total_score"] = max(0, min(100, final_score))
    final_score = int(score_data["total_score"])

    # Confidence tracks the clamped score only (volume is already scored in VolumeStrategy).
    confidence = min(100, max(0, final_score))

    # 3. Decision Engine
    de_config = {
        "thresholds": {
            "early": cfg.get("MODERATE_THRESHOLD", 70), # map to early
            "strong": cfg.get("STRONG_THRESHOLD", 85)
        }
    }
    de = DecisionEngine(de_config)
    decision = de.evaluate_decision(score_data)
    sig_class = str(decision.get("class") or "WEAK")
    # Single strength vocabulary aligned with DecisionEngine tiers (no second classifier).
    if int(score_data["total_score"]) < threshold:
        strength_label = "NONE"
    else:
        strength_label = {"STRONG": "STRONG", "EARLY": "MODERATE", "WEAK": "WEAK"}.get(sig_class, "WEAK")
    signal_type = decision.get("signal_type") or ("WATCH" if sig_class == "WEAK" else sig_class)

    price = features["price"]
    atr_val = _safe_num(features["atr"], price * 0.01)
    
    ind_cfg = cfg.get("indicators", {})
    chandelier_period = ind_cfg.get("chandelier_period", 22)
    chandelier_multiplier = ind_cfg.get("chandelier_multiplier", 3.0)
    
    atr_sl_mult = cfg.get("ATR_SL_MULTIPLIER", 1.5)
    stop_loss = calc_atr_stop_loss(price, atr_val, direction, atr_sl_mult)
    trailing_sl = calc_chandelier_exit(df1m, period=chandelier_period, multiplier=chandelier_multiplier, direction=direction)
    try:
        ts = float(trailing_sl.iloc[-1]) if hasattr(trailing_sl, 'iloc') else float(trailing_sl)
    except (TypeError, ValueError, IndexError):
        ts = 0.0
    trailing_sl = ts if ts != 0.0 else stop_loss
        
    targets = calc_fibonacci_targets(price, atr_val, direction, 
                                     cfg.get("FIB_TP1_RATIO", 0.618), 
                                     cfg.get("FIB_TP2_RATIO", 1.0), 
                                     cfg.get("FIB_TP3_RATIO", 1.618),
                                     vix=vix)
    pivots = calc_support_resistance_pivot(df1m)
    bar_ts = pd.Timestamp(df1m.index[-1])
    try:
        ts_ist = bar_ts.tz_localize("Asia/Kolkata") if bar_ts.tz is None else bar_ts.tz_convert("Asia/Kolkata")
        wall = ts_ist.to_pydatetime()
        signal_ts_bar = float(bar_ts.timestamp())
    except Exception:
        wall = time_provider.now()
        signal_ts_bar = float(wall.timestamp())

    # Compile final payload combining Legacy required fields + V2 architecture fields
    return {
        # --- V2 Payload ---
        "decision": decision,
        "reasons": decision.get("reasons", []),
        "signal_class": sig_class,
        "is_eligible": decision.get("eligible", False),
        "confidence": confidence,
        "signal_type": signal_type,
        
        # --- Legacy Payload (Must be preserved for index_trader.py) ---
        "symbol": symbol,
        "asset_type": asset_type,
        "price": price,
        "open": get_open(df1m),
        "high": get_high(df1m),
        "low": get_low(df1m),
        "signal": ("BUY" if direction in ("CALL", "UP") else "SELL") if decision.get("eligible") else "HOLD",
        "strength": strength_label,
        "direction": direction,
        "score": final_score,
        "threshold": threshold,
        "rsi": features["rsi"],
        "macd": features["macd"],
        "vwap": features["vwap"],
        "atr": atr_val,
        "vol_ratio": features["vol_ratio"],
        "support": oi_data.get("support") if oi_data else pivots["support_1"],
        "resistance": oi_data.get("resistance") if oi_data else pivots["resistance_1"],
        "pivot": pivots["pivot"],
        "stop_loss": stop_loss,
        "trailing_sl": trailing_sl,
        "tp1": targets["tp1"],
        "tp2": targets["tp2"],
        "tp3": targets["tp3"],
        "pcr": features["pcr"],
        "smart_money": features["smart_money"],
        "iv": iv,
        "vix": round(vix, 1),
        "sector": sector,
        "category": category,
        "tags": tags or [],
        "trend_5m": t5,
        "trend_15m": t15,
        "breakout_ok": features["breakout_ok"],
        "stars": score_to_stars(final_score, threshold),
        "label": score_to_label(final_score, direction, threshold),
        "timestamp": wall.strftime("%d-%b-%Y %H:%M:%S"),
        "timestamp_iso": wall.isoformat(),
        "signal_ts": signal_ts_bar,
        "regime":    regime,
    }

# ═══════════════════════════════════════════════════════════════
# DATA VALIDATION  — Shared OHLCV cleaner
# ═══════════════════════════════════════════════════════════════

def validate_ohlcv(df: pd.DataFrame, interval: str = "1m", max_drop_ratio: float = 0.15) -> tuple[pd.DataFrame | None, int]:
    """Clean OHLCV data. Returns (clean_df, dropped_count) or (None, dropped_count)."""
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
# EXPLAIN WHY  — Layman-readable signal explanation
# ═══════════════════════════════════════════════════════════════

def explain_signal(sig: dict, asset_label: str = "Stock") -> str:
    if not sig:
        return "No signal data"
    parts = []
    t = sig.get("trend_5m", sig.get("trend", ""))
    word = "going UP" if t in ("UP", "CALL") else ("going DOWN" if t in ("DOWN", "PUT") else "sideways")
    parts.append(f"{asset_label} {word}")

    p, v = sig.get("price", 0), sig.get("vwap", 0)
    if t in ("UP", "CALL") and p > v:
        parts.append("above average price (VWAP)")
    elif t in ("DOWN", "PUT") and p < v:
        parts.append("below average price (VWAP)")

    vr = sig.get("vol_ratio", 0)
    if vr >= 2.0: parts.append(f"very high volume ({vr}x)")
    elif vr >= 1.2: parts.append(f"good volume ({vr}x)")

    sm = sig.get("smart_money", sig.get("smart", ""))
    if sm == "BULLISH": parts.append("big buyers active (OI bullish)")
    elif sm == "BEARISH": parts.append("big sellers active (OI bearish)")

    rsi = sig.get("rsi", 50)
    if 40 <= rsi <= 70: parts.append(f"RSI healthy ({rsi})")
    elif rsi > 70: parts.append(f"RSI high ({rsi}) — overbought")
    elif rsi < 30: parts.append(f"RSI low ({rsi}) — oversold")

    macd = sig.get("macd", {})
    if isinstance(macd, dict) and macd.get("histogram", 0) != 0:
        h = macd["histogram"]
        parts.append(f"MACD {'bullish' if h > 0 else 'bearish'} ({h:+.2f})")

    vix = sig.get("vix", 0)
    if 0 < vix <= 15: parts.append(f"low fear (VIX {vix})")
    elif 15 < vix <= 22: parts.append(f"moderate fear (VIX {vix})")
    elif vix > 22: parts.append(f"high fear (VIX {vix}) — risky")

    return ", ".join(parts) if parts else "Multiple signals aligned"

# ═══════════════════════════════════════════════════════════════
# SCORE BREAKDOWN  — Human-readable component attribution
# ═══════════════════════════════════════════════════════════════

def score_breakdown(sig: dict, config: dict | None = None) -> str:
    """
    Returns a compact one-line breakdown of which scoring components fired.
    Works with both generate_signal() output (index_trader) and
    build_full_signal() output (signal_engine), handling both naming
    conventions (trend_5m/trend vs smart_money/smart).

    Example:
      "Score 78/72 (+6) [PASS]  ←  TF +20, VWAP +15, Vol 1.8x +10, OI +10, ATR +5, MACD +5"
    """
    if not sig:
        return "No signal"
    cfg      = config or {}
    vol_min  = _safe_num(cfg.get("VOL_RATIO_MIN", 1.2), 1.2)
    atr_min  = _safe_num(cfg.get("ATR_MIN_THRESHOLD", 0.5), 0.5)
    pcr_bull = _safe_num(cfg.get("PCR_BULLISH", 1.2), 1.2)
    pcr_bear = _safe_num(cfg.get("PCR_BEARISH", 0.8), 0.8)
    macd_b   = int(_safe_num(cfg.get("MACD_BONUS", 5), 5))

    score     = int(_safe_num(sig.get("score"), 0))
    thr       = int(_safe_num(sig.get("threshold"), 60))
    direction = sig.get("direction", "")
    is_call   = direction in ("CALL", "UP", "BUY")

    # Support both naming conventions
    t5    = sig.get("trend_5m") or sig.get("trend") or ""
    t15   = sig.get("trend_15m") or ""
    price = _safe_num(sig.get("price"), 0)
    vwap  = _safe_num(sig.get("vwap"), 0)
    vol   = _safe_num(sig.get("vol_ratio"), 0)
    atr   = _safe_num(sig.get("atr"), 0)
    smart = sig.get("smart_money") or sig.get("smart") or "NEUTRAL"
    pcr   = _safe_num(sig.get("pcr"), 1.0)
    macd  = sig.get("macd") or {}

    parts = []

    # Timeframe alignment (+20 index / +15 stock)
    if t5 and (not t15 or t5 == t15):
        parts.append(("TF align", 20))

    # VWAP position confirms trend (+15)
    if price > 0 and vwap > 0:
        if (is_call and price > vwap) or (not is_call and price < vwap):
            parts.append(("VWAP", 15))

    # Volume surge (+10)
    if vol >= vol_min:
        parts.append((f"Vol {vol:.1f}x", 10))

    # ATR confirms real movement (+5)
    if atr > atr_min:
        parts.append(("ATR", 5))

    # Smart money / OI alignment (+10)
    if (is_call and smart == "BULLISH") or (not is_call and smart == "BEARISH"):
        parts.append(("OI", 10))

    # PCR supports direction (+5)
    if (is_call and pcr > pcr_bull) or (not is_call and pcr < pcr_bear):
        parts.append((f"PCR {pcr:.1f}", 5))

    # MACD momentum bonus (configurable)
    if isinstance(macd, dict):
        hist   = _safe_num(macd.get("histogram"), 0)
        m_line = _safe_num(macd.get("macd"), 0)
        s_line = _safe_num(macd.get("signal"), 0)
        if (is_call and hist > 0 and m_line > s_line) or \
           (not is_call and hist < 0 and m_line < s_line):
            parts.append((f"MACD", macd_b))

    # RSI
    rsi = sig.get("rsi", 50)
    if 40 <= rsi <= 70:
        parts.append(("RSI", 8))
    elif rsi > 70:
        parts.append(("RSI OB", -10))

    # Breakout
    if sig.get("breakout_ok"):
        parts.append(("Breakout", 8))
        
    gap      = score - thr
    status   = "PASS" if gap >= 0 else f"NEED +{abs(gap)}"
    breakdown = ", ".join(f"{name} +{pts}" for name, pts in parts) if parts else "—"
    return f"Score {score}/{thr} ({gap:+d}) [{status}]  \u2190  {breakdown}"


# ═══════════════════════════════════════════════════════════════
# FORMAT HELPERS  — Used by dashboard and Telegram
# ═══════════════════════════════════════════════════════════════

R = chr(0x20B9)

def format_pnl(val: Any) -> str:
    val = _safe_num(val, 0.0)
    if val >= 0:
        return f"+{R}{round(val, 0):,.0f}"
    return f"-{R}{abs(round(val, 0)):,.0f}"

def format_change(chg: Any, pct: Any) -> str:
    chg = _safe_num(chg, 0.0)
    pct = _safe_num(pct, 0.0)
    arrow = "\u25b2" if chg >= 0 else "\u25bc"
    return f"{arrow}{chg:+.1f} ({pct:+.1f}%)"
