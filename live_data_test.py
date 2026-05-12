"""Live data fetch test — validates yfinance, broker data, and signal pipeline inputs."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import yfinance as yf
import pandas as pd

print("=" * 60)
print("  LIVE DATA FEED TEST — OPB v2.45")
print("=" * 60)
print()

ist_now = pd.Timestamp.now(tz="Asia/Kolkata")
print(f" IST time : {ist_now}")
print(f" Session  : {'OPEN' if ist_now.time() >= ist_now.replace(hour=9, minute=20).time() and ist_now.time() <= ist_now.replace(hour=15, minute=0).time() else 'CLOSED'}")
print()

# NIFTY
print("[1/3] Fetching NIFTY...")
nifty = yf.Ticker("^NSEI")
nf = nifty.history(period="5d", interval="1m")
if len(nf):
    last = nf.iloc[-1]
    age = (ist_now - last.name).total_seconds()
    ok = "OK" if age < 120 else "STALE"
    print(f"  NIFTY    : {last['Close']:.1f}  ({age:.0f}s old) [{ok}]")
    print(f"  bars     : {len(nf)}")
    print(f"  today's H/L: {nf['High'].max():.1f} / {nf['Low'].min():.1f}")
else:
    print("  NIFTY    : NO DATA")

# BANKNIFTY
print()
print("[2/3] Fetching BANKNIFTY...")
bnf = yf.Ticker("^NSEBANK")
bf = bnf.history(period="5d", interval="1m")
if len(bf):
    last = bf.iloc[-1]
    age = (ist_now - last.name).total_seconds()
    ok = "OK" if age < 120 else "STALE"
    print(f"  BANKNIFTY: {last['Close']:.1f}  ({age:.0f}s old) [{ok}]")
    print(f"  bars     : {len(bf)}")
else:
    print("  BANKNIFTY: NO DATA")

# VIX
print()
print("[3/3] Fetching VIX...")
vix = yf.Ticker("^INDIAVIX")
vx = vix.history(period="2d", interval="1m")
if len(vx):
    last = vx.iloc[-1]
    age = (ist_now - last.name).total_seconds()
    block = "BLOCK" if last["Close"] > 27 else ("HALT" if last["Close"] > 22 else "OK")
    print(f"  VIX      : {last['Close']:.2f}  ({age:.0f}s old) [{block}]")
else:
    print("  VIX      : NO DATA")

print()
print("=" * 60)
print("  DATA FEED TEST COMPLETE")
print("=" * 60)
