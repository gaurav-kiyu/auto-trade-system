"""Live signal pipeline test — validates end-to-end signal generation with real market data."""
from __future__ import annotations

import sys
import datetime
import time as time_module
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import yfinance as yf
import pandas as pd

from core.pure_index_signal import (
    PureIndexRegimeParams,
    PureIndexSignalParams,
    evaluate_index_signal_partial,
    finalize_index_signal_with_threshold,
)
from core.session_classifier import classify_session, SessionType
from core.market_calc import detect_regime_and_adx
from core.data_freshness_guard import check_data_freshness, FreshnessResult

print("=" * 60)
print("  LIVE SIGNAL PIPELINE TEST — OPB v2.45")
print("=" * 60)
print()

ist_now = pd.Timestamp.now(tz="Asia/Kolkata")
print(f" IST time  : {ist_now}")
print()

# ── 1. Fetch live data ────────────────────────────────────────────
print("[1/5] Fetching live market data...")

def fetch_1m(ticker: str, period: str = "5d") -> pd.DataFrame:
    df = yf.Ticker(ticker).history(period=period, interval="1m")
    df.index = df.index.tz_convert("Asia/Kolkata")
    return df

nifty_1m = fetch_1m("^NSEI")
bnf_1m   = fetch_1m("^NSEBANK")
vix_1m   = fetch_1m("^INDIAVIX", "2d")

nifty_ltp = float(nifty_1m["Close"].iloc[-1]) if len(nifty_1m) else 0
bnf_ltp   = float(bnf_1m["Close"].iloc[-1])   if len(bnf_1m)   else 0
vix_val   = float(vix_1m["Close"].iloc[-1])   if len(vix_1m)   else 0

print(f"  NIFTY LTP    : {nifty_ltp:.1f}")
print(f"  BANKNIFTY LTP: {bnf_ltp:.1f}")
print(f"  VIX          : {vix_val:.2f}")

# ── 2. Build frames ───────────────────────────────────────────────
print()
print("[2/5] Building multi-timeframe frames...")

def build_frames(base: pd.DataFrame) -> dict:
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    frames = {"1m": base.copy()}
    for rule, key in [("5min", "5m"), ("15min", "15m")]:
        rs = base.resample(rule, label="right", closed="right").agg(agg).dropna(
            subset=["Open", "High", "Low", "Close"])
        frames[key] = rs
    return frames

nf_frames = build_frames(nifty_1m)
df1  = nf_frames["1m"]
df5  = nf_frames["5m"]
df15 = nf_frames["15m"]

print(f"  1m bars: {len(df1)} | 5m bars: {len(df5)} | 15m bars: {len(df15)}")

# ── 3. Freshness guard ────────────────────────────────────────────
print()
print("[3/5] Freshness guard check...")

frames_for_guard = {"1m": df1.copy(), "5m": df5.copy(), "15m": df15.copy()}
vix_ts = time_module.time()
fr = check_data_freshness(frames=frames_for_guard, vix_ts=vix_ts)

fresh = fr.passed
if fresh:
    print(f"  Result    : PASSED (all bars fresh)")
else:
    print(f"  Result    : REJECTED — {fr.reject_reason}")

# ── 4. Session check ───────────────────────────────────────────────
print()
print("[4/5] Session classifier...")

session = classify_session(ist_now)  # now accepts Timestamp directly
adj_map = {
    SessionType.TRENDING:   "+5 (BEST WINDOW)",
    SessionType.CHOPPY:     "-15 (AVOID)",
    SessionType.OPENING:    "-10 (volatile)",
    SessionType.PRE_CLOSE:  "-5 (caution)",
    SessionType.RECOVERY:   "0 (neutral)",
    SessionType.PRE_MARKET: "BLOCKED",
    SessionType.CLOSED:     "BLOCKED",
}
print(f"  Session    : {session.value}")
print(f"  Adjustment : {adj_map.get(session, '0')}")

# VIX block check
vix_block = "BLOCK ALL" if vix_val > 27 else "HALT" if vix_val > 22 else "OK"
print(f"  VIX block  : {vix_block} (VIX={vix_val:.2f})")

# ── 5. Signal generation ─────────────────────────────────────────
print()
print("[5/5] Signal generation (NIFTY)...")

regime, adx_val = detect_regime_and_adx(df5, df15, vix=float(vix_val))
print(f"  Detected   : regime={regime}, ADX={adx_val:.1f}")

# Compute RSI manually
delta = df1["Close"].diff()
gain = delta.where(delta > 0, 0.0)
loss = (-delta.where(delta < 0, 0.0))
avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
rs = avg_gain / avg_loss
rsi_val = float((100 - (100 / (1 + rs))).iloc[-1])
print(f"  RSI (14)   : {rsi_val:.1f}")

params = PureIndexSignalParams(
    name="NIFTY",
    signal_cfg={
        "AI_THRESHOLD": 55,
        "TF_ALIGN_MIN": 3,
        "IV_SPIKE_THRESHOLD": 45.0,
        "VOL_RATIO_MIN": 1.2,
        "FRAME_ALIGN_1M_5M": 99999,
        "FRAME_ALIGN_1M_15M": 99999,
    },
    regime=PureIndexRegimeParams(
        vix_block_threshold=27.0,
        adx_trend_threshold=16.0,
        adx_chop_threshold=12.0,
    ),
    iv_spike_threshold=45.0,
    vol_ratio_min=1.2,
    is_early_session=False,
)

partial, reason = evaluate_index_signal_partial(
    params=params,
    df1=df1, df5=df5, df15=df15,
    vix=vix_val, iv=0.0,
    oi_sup=0.0, oi_res=0.0, pcr=1.0, smart=1.0,
    learning_score_bonus=0,
)

if partial:
    fin = finalize_index_signal_with_threshold(
        partial, threshold=55, regime=regime or "NEUTRAL",
        adaptive_delta=0, adaptive_reason="live_test", trace_id="live-test",
        signal_cfg=params.signal_cfg,
    )
    score = fin.get("score", 0)
    direction = fin.get("direction", "NONE")
    action = fin.get("action", "SKIP")
    print(f"  Raw score  : {partial.get('score', 0)}")
    print(f"  Final score: {score}")
    print(f"  Direction  : {direction}")
    print(f"  Action     : {action}")
    print()
    if action == "BUY":
        tier = "STRONG" if score >= 80 else "MODERATE" if score >= 70 else "WEAK"
        print(f"  >>> TRADE SIGNAL: {direction} on NIFTY @ {nifty_ltp:.1f}")
        print(f"  >>> Tier: {tier} (score={score})")
        print(f"  >>> Session: {session.value} {adj_map.get(session, '')}")
    else:
        print(f"  >>> NO TRADE — score {score} < threshold 55")
        print(f"  >>> Reason: {reason}")
else:
    print(f"  >>> NO TRADE — signal rejected: {reason}")

print()
print("=" * 60)
print("  LIVE SIGNAL PIPELINE TEST COMPLETE")
print("=" * 60)
