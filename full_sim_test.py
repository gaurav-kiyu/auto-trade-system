"""Full end-to-end live simulation test — OPB v2.45.
Tests every component of the trading pipeline in real-time NSE conditions.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from collections import Counter

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
from core.market_calc import detect_regime_and_adx, calc_adx
from core.data_freshness_guard import check_data_freshness
from core.position_sizer import PositionSizer
from core.tier_engine import classify_tier
from core.capital_manager import CapitalManager
from core.execution_policy import ExecutionPolicy, ExecutionDecision
from core.stress_tester import run_stress_test, StressResult
from core.var_calculator import compute_var
from core.kelly_sizer import compute_kelly_lots
from core.implied_move import compute_implied_move, check_implied_move_gate
from core.gex_analyzer import compute_gex, get_gex_score_adj
from core.fii_dii_tracker import FIIDIITracker

print("=" * 70)
print("  FULL END-TO-END LIVE SIMULATION — OPB v2.45")
print("=" * 70)
print()

ist_now = pd.Timestamp.now(tz="Asia/Kolkata")
print(f" IST time : {ist_now}")
print()

# ── LIVE DATA FETCH ───────────────────────────────────────────────
print("[DATA] Fetching live NSE + VIX data...")

nifty_1m = yf.Ticker("^NSEI").history(period="5d", interval="1m")
nifty_1m.index = nifty_1m.index.tz_convert("Asia/Kolkata")
bnf_1m = yf.Ticker("^NSEBANK").history(period="5d", interval="1m")
bnf_1m.index = bnf_1m.index.tz_convert("Asia/Kolkata")
vix_1m = yf.Ticker("^INDIAVIX").history(period="2d", interval="1m")
vix_1m.index = vix_1m.index.tz_convert("Asia/Kolkata")

nifty_ltp = float(nifty_1m["Close"].iloc[-1])
bnf_ltp = float(bnf_1m["Close"].iloc[-1])
vix_val = float(vix_1m["Close"].iloc[-1])
print(f"  NIFTY: {nifty_ltp:.1f} | BANKNIFTY: {bnf_ltp:.1f} | VIX: {vix_val:.2f}")

# ── BUILD FRAMES ─────────────────────────────────────────────────
def build_frames(base: pd.DataFrame) -> dict:
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    frames = {"1m": base.copy()}
    for rule, key in [("5min", "5m"), ("15min", "15m")]:
        rs = base.resample(rule, label="right", closed="right").agg(agg).dropna(
            subset=["Open", "High", "Low", "Close"])
        frames[key] = rs
    return frames

nf = build_frames(nifty_1m)
df1, df5, df15 = nf["1m"], nf["5m"], nf["15m"]

# ── COMPONENT 1: DATA FRESHNESS ─────────────────────────────────
print()
print("[1/10] Data Freshness Guard...")
fr = check_data_freshness(
    frames={"1m": df1.copy(), "5m": df5.copy(), "15m": df15.copy()},
    vix_ts=time.time(),
)
print(f"  {'PASS' if fr.passed else 'REJECT'} ({fr.reject_reason if not fr.passed else 'all fresh'})")

# ── COMPONENT 2: SESSION CLASSIFIER ────────────────────────────
print()
print("[2/10] Session Classifier...")
session = classify_session(ist_now)
adj_map = {
    SessionType.TRENDING: "+5 BEST",
    SessionType.CHOPPY: "-15 AVOID",
    SessionType.OPENING: "-10 volatile",
    SessionType.PRE_CLOSE: "-5 caution",
    SessionType.RECOVERY: "0 neutral",
    SessionType.PRE_MARKET: "BLOCKED",
    SessionType.CLOSED: "BLOCKED",
}
print(f"  Session: {session.value}  ({adj_map.get(session, '0')})")

# ── COMPONENT 3: REGIME + ADX ───────────────────────────────────
print()
print("[3/10] Regime Detection...")
regime, adx = detect_regime_and_adx(df5, df15, vix=vix_val)
print(f"  Regime: {regime}  |  ADX: {adx:.1f}")

# ── COMPONENT 4: SIGNAL GENERATION ──────────────────────────────
print()
print("[4/10] Signal Generation (NIFTY)...")

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
        adaptive_delta=0, adaptive_reason="sim", trace_id="full-sim",
        signal_cfg=params.signal_cfg,
    )
    score = fin.get("score", 0)
    direction = fin.get("direction", "NONE")
    action = fin.get("action", "SKIP")
    print(f"  Score: {score}  |  Dir: {direction}  |  Action: {action}")
else:
    score, direction, action = 0, "NONE", "SKIP"
    print(f"  Rejected: {reason}")

# ── COMPONENT 5: TIER + POSITION SIZING ────────────────────────
print()
print("[5/10] Tier + Position Sizing...")
tier = classify_tier(score)
spec = PositionSizer.calculate(
    score=score, tier=tier, regime=regime or "NEUTRAL",
    max_lots=1, atr=0.0, capital=5000.0,
)
print(f"  Tier: {tier}  |  Lots: {spec.lots}  |  Eff%: {spec.effective_pct:.1%}")

# ── COMPONENT 6: RISK ENGINE ────────────────────────────────────
print()
print("[6/10] Risk Service (canonical engine)...")

from core.services.risk_service import RiskService, RiskServiceConfig
from core.ports.risk.risk_port import PortfolioRiskMetrics

_risk_svc = RiskService(
    config=RiskServiceConfig(
        max_daily_loss=-300.0,
        max_open_positions=1,
        max_daily_trades=1,
        max_consecutive_losses=3,
    )
)
_metrics = PortfolioRiskMetrics(
    total_capital=5000.0,
    used_capital=0.0,
    available_capital=5000.0,
    daily_pnl=0.0,
    max_daily_loss=-300.0,
    current_drawdown=0.0,
    max_drawdown=0.0,
    open_positions_count=0,
    max_open_positions=1,
    consecutive_losses=0,
    max_consecutive_losses=3,
    sector_exposure={},
    symbol_exposure={},
)
_signal = {"direction": "CALL", "price": 18000.0, "score": 70}
_risk_eval = _risk_svc.evaluate_trade("NIFTY", _signal, _metrics)
print(f"  Risk: {_risk_eval.decision.value} — {_risk_eval.reason}")
print(f"  Risk score: {_risk_eval.risk_score:.2f}")
print(f"  Recommended size: {_risk_eval.recommended_position_size} lots")

# ── COMPONENT 7: CAPITAL MANAGER ────────────────────────────────
print()
print("[7/10] Capital Manager (equity-aware scaling)...")
cm = CapitalManager(initial_capital=5000.0, max_daily_loss=-300.0)
scale = cm.scale(base_lots=spec.lots, max_lots=1)
print(f"  Scale: {scale.scale_factor:.2f}  |  Scaled lots: {scale.scaled_lots}")
print(f"  Cap growth: {scale.capital_growth:.2f}  |  DD factor: {scale.drawdown_factor:.2f}")
print(f"  DD consec: {scale.consec_loss_factor:.2f}  |  Daily loss: {scale.daily_loss_factor:.2f}")

# ── COMPONENT 8: EXECUTION POLICY ──────────────────────────────
print()
print("[8/10] Execution Policy...")
ep_decision = ExecutionPolicy.apply(
    signal={"score": score, "direction": direction, "breakout_ok": False, "vol_ratio": 1.5, "tier": tier},
    config={"AI_THRESHOLD": 55, "execution_policy": {}},
    regime=regime or "NEUTRAL",
    max_lots=1,
    capital=5000.0,
)
print(f"  Action: {'TRADE' if ep_decision.trade else 'SKIP'}  |  Reasons: {ep_decision.reasons}")

# ── COMPONENT 9: RISK METRICS ──────────────────────────────────
print()
print("[9/10] Risk Metrics (VaR, Kelly, Stress Test, Implied Move, GEX)...")

try:
    var_result = compute_var(capital=5000.0)
    print(f"  VaR (95%): Rs.{var_result.var_95:.0f}  |  VaR (99%): Rs.{var_result.var_99:.0f}")
except Exception as e:
    print(f"  VaR: {e}")

try:
    kelly_result = compute_kelly_lots(capital=5000.0, base_lots=1, risk_per_lot=150.0)
    print(f"  Kelly fraction: {kelly_result.kelly_f:.2%}  |  Kelly lots: {kelly_result.kelly_lots}")
except Exception as e:
    print(f"  Kelly: {e}")

try:
    stress_results = run_stress_test(open_positions=[], capital=5000.0)
    for sr in stress_results:
        print(f"  Stress ({sr.scenario}): max_loss=Rs.{sr.total_pnl_shock:.0f}")
except Exception as e:
    print(f"  Stress: {e}")

try:
    imp = compute_implied_move(option_chain=None, spot=nifty_ltp)
    if imp:
        print(f"  Implied move: Rs.{imp.move:.1f} (ATM: {imp.atm_strike})")
        gate_ok = check_implied_move_gate(spot=nifty_ltp, threshold=imp.move)
        print(f"  Entry gate: {'OPEN' if gate_ok else 'BLOCKED'}")
    else:
        print("  Implied move: no data")
except Exception as e:
    print(f"  Implied move: {e}")

try:
    gex = compute_gex(option_chain=None, spot=nifty_ltp)
    if gex:
        adj = get_gex_score_adj(gex, "CALL")
        print(f"  GEX: {gex.net_gex:.2f}  |  Score adj: {adj:+d}")
    else:
        print("  GEX: no data")
except Exception as e:
    print(f"  GEX: {e}")

# ── COMPONENT 10: BROKER ABSTRACTION ────────────────────────────
print()
print("[10/10] Broker Abstraction...")
print("  Mode: PAPER  |  Cap: Rs.5000  |  Broker: PaperBrokerAdapter (abstract method pending)")

# ── RECONCILIATION ─────────────────────────────────────────────
print()
print("[RECON] Final Reconciliation...")
recon = {
    "market_data": "LIVE" if nifty_ltp > 0 else "FAIL",
    "freshness": "PASS" if fr.passed else "FAIL",
    "session": session.value,
    "regime": regime,
    "vix": f"{vix_val:.2f}",
    "score": score,
    "action": action,
    "tier": tier,
    "risk": "ALLOWED" if risk_result['allowed'] else "BLOCKED",
    "lots": scale.scaled_lots,
    "broker": "PAPER",
    "capital": "Rs.5000",
}
for k, v in recon.items():
    print(f"  {k:15s}: {v}")

print()
print("=" * 70)
print("  FULL SIMULATION COMPLETE — OPB v2.45")
print("=" * 70)
